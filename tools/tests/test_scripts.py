"""Tests for the viewer identity, preflight and agent install scripts.

The scripts run against a fake ``kubectl`` first on PATH and a throwaway HOME, so the
tests never touch a real cluster or the real ``~/.claude`` / ``~/.kube`` folders.
"""

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "k8s-crew"
SCRIPTS = SKILL / "scripts"

FAKE_KUBECTL = """#!/usr/bin/env bash
echo "kubectl $*" >> "$FAKE_LOG"
case "$1 $2" in
  "auth can-i")
    if [[ -n "${FAKE_CAN_I_ERR:-}" ]]; then echo "$FAKE_CAN_I_ERR" >&2; exit 1; fi
    answer="${FAKE_CAN_I:-no}"
    IFS='|' read -ra yes <<< "${FAKE_YES:-}"
    for pattern in "${yes[@]}"; do
      [[ -n "$pattern" && "$*" == *"$pattern"* ]] && answer=yes
    done
    echo "$answer"; [[ "$answer" == yes ]] && exit 0 || exit 1 ;;
  "get namespaces")
    if [[ -n "${FAKE_NS_ERR:-}" ]]; then echo "$FAKE_NS_ERR" >&2; exit 1; fi
    echo "${FAKE_NAMESPACES-default my-namespace}" ;;
  "create token") echo "fake-token-value" ;;
  "config view")
    case "$*" in
      *--flatten*) ;;
      *) echo "config view without --flatten" >&2; exit 9 ;;
    esac
    case "$*" in
      *cluster.server*) echo "${FAKE_SERVER-https://example.com:6443}" ;;
      *certificate-authority-data*) echo "${FAKE_CA-RkFLRS1DQQ==}" ;;
      *tls-server-name*) echo "${FAKE_TLS_NAME:-}" ;;
      *proxy-url*) echo "${FAKE_PROXY:-}" ;;
      *insecure-skip-tls-verify*) echo "${FAKE_INSECURE:-}" ;;
      *) echo "client-certificate-data: FAKE-ADMIN-CERT" ;;
    esac ;;
esac
exit 0
"""
GUARD = SCRIPTS / "kubectl-guard"


def make_env(tmp_path, can_i="no", guard=True):
    """A fake kubectl and throwaway HOME; with ``guard``, the crew guard first on PATH."""
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    kubectl = bindir / "kubectl"
    kubectl.write_text(FAKE_KUBECTL)
    kubectl.chmod(0o755)
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = dict(os.environ)
    env.update(
        PATH=f"{bindir}:{env['PATH']}",
        HOME=str(home),
        FAKE_LOG=str(tmp_path / "log"),
        FAKE_CAN_I=can_i,
    )
    env.pop("KUBECONFIG", None)
    env.pop("K8S_CREW_GUARD", None)
    if guard:
        viewer = tmp_path / "viewer.kubeconfig"
        viewer.write_text("fake viewer")
        guard_bin = tmp_path / "guard"
        guard_bin.mkdir(exist_ok=True)
        subprocess.run(
            ["bash", str(GUARD), "install", str(guard_bin), str(viewer)], env=env, check=True
        )
        guard_bin = guard_bin.resolve()
        env.update(
            PATH=f"{guard_bin}:{env['PATH']}",
            KUBECONFIG=str(viewer),
            K8S_CREW_GUARD=str(guard_bin),
        )
    return env, home


def run(script, args, env, cwd=None):
    return subprocess.run(
        ["bash", str(SCRIPTS / script), *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        cwd=cwd,
    )


def make_project(tmp_path):
    """A git repository with a nested working folder, outside the real repository."""
    project = tmp_path / "project"
    work = project / "src" / "deep"
    work.mkdir(parents=True)
    subprocess.run(["git", "init", "--quiet", str(project)], check=True)
    return project, work


def test_rbac_never_mentions_secrets():
    text = (SKILL / "rbac" / "crew-viewer.yaml").read_text()
    assert "secrets" not in text
    assert "serviceaccounts/token" not in text


def test_preflight_refuses_writer(tmp_path):
    env, _ = make_env(tmp_path, can_i="yes")
    res = run("preflight.sh", [], env)
    assert res.returncode == 3
    assert "viewer-kubeconfig.sh" in res.stdout


def test_preflight_accepts_viewer(tmp_path):
    env, _ = make_env(tmp_path, can_i="no")
    res = run("preflight.sh", [], env)
    assert res.returncode == 0
    assert "viewer ok" in res.stdout


def test_preflight_fails_closed_on_unexpected_answer(tmp_path):
    env, _ = make_env(tmp_path, can_i="maybe")
    res = run("preflight.sh", [], env)
    assert res.returncode == 3
    assert "NOT view-only" in res.stdout


@pytest.mark.parametrize(
    "answer", ["no - RBAC: access denied", "no - Azure does not have opinion for this user."]
)
def test_preflight_accepts_denial_with_reason(tmp_path, answer):
    env, _ = make_env(tmp_path, can_i=answer)
    res = run("preflight.sh", [], env)
    assert res.returncode == 0, res.stdout
    assert "viewer ok" in res.stdout


@pytest.mark.parametrize("answer", ["no -", "nope", "no\nyes", "no - x\nyes"])
def test_preflight_refuses_near_denials(tmp_path, answer):
    env, _ = make_env(tmp_path, can_i=answer.replace("\\n", "\n"))
    res = run("preflight.sh", [], env)
    assert res.returncode == 3, res.stdout


@pytest.mark.parametrize(
    "error",
    [
        "error: You must be logged in to the server (Unauthorized)",
        "Unable to connect to the server: dial tcp 192.0.2.1:6443: i/o timeout",
    ],
)
def test_preflight_reports_check_errors_apart(tmp_path, error):
    env, _ = make_env(tmp_path)
    env["FAKE_CAN_I_ERR"] = error
    res = run("preflight.sh", [], env)
    assert res.returncode == 5, res.stdout
    assert f"cannot check identity: can-i create deployments -A: {error}" in res.stdout
    assert "NOT view-only" not in res.stdout
    assert "viewer-kubeconfig.sh" in res.stdout


def test_preflight_write_wins_over_errors(tmp_path):
    env, _ = make_env(tmp_path)
    env["FAKE_YES"] = "patch nodes"
    env["FAKE_NS_ERR"] = "error: forbidden"
    res = run("preflight.sh", [], env)
    assert res.returncode == 3, res.stdout


@pytest.mark.parametrize(
    "grant",
    ["create deployments -n my-namespace", "delete pods -n my-namespace", "get secrets -n default"],
)
def test_preflight_refuses_namespace_scoped_access(tmp_path, grant):
    env, _ = make_env(tmp_path)
    env["FAKE_YES"] = grant
    res = run("preflight.sh", [], env)
    assert res.returncode == 3, res.stdout
    assert f"NOT view-only: can-i {grant} answered 'yes'" in res.stdout


def test_preflight_checks_every_namespace(tmp_path):
    env, _ = make_env(tmp_path)
    res = run("preflight.sh", [], env)
    assert res.returncode == 0, res.stdout
    log = (tmp_path / "log").read_text()
    for ns in ("default", "my-namespace"):
        for check in ("create deployments", "delete pods", "get secrets"):
            assert f"kubectl auth can-i {check} -n {ns}" in log


@pytest.mark.parametrize("names", ["", None])
def test_preflight_namespace_listing_failure_is_an_error(tmp_path, names):
    env, _ = make_env(tmp_path)
    if names is None:
        env["FAKE_NS_ERR"] = "error: You must be logged in to the server (Unauthorized)"
    else:
        env["FAKE_NAMESPACES"] = names
    res = run("preflight.sh", [], env)
    assert res.returncode == 5, res.stdout
    assert "cannot check identity" in res.stdout


def test_preflight_needs_the_guard(tmp_path):
    env, _ = make_env(tmp_path, guard=False)
    res = run("preflight.sh", [], env)
    assert res.returncode == 6
    assert "crew-start.sh" in res.stdout
    assert not (tmp_path / "log").exists()


def test_preflight_needs_the_guard_first_on_path(tmp_path):
    env, _ = make_env(tmp_path)
    env["PATH"] = f"{tmp_path / 'bin'}:{env['PATH']}"
    res = run("preflight.sh", [], env)
    assert res.returncode == 6


def test_preflight_refuses_a_kubeconfig_list(tmp_path):
    env, _ = make_env(tmp_path)
    env["KUBECONFIG"] = f"{env['KUBECONFIG']}:{tmp_path / 'admin'}"
    res = run("preflight.sh", [], env)
    assert res.returncode == 5, res.stdout
    assert "k8s-crew kubectl guard" in res.stdout


def test_preflight_needs_agent_for_subagents(tmp_path):
    env, _ = make_env(tmp_path)
    res = run("preflight.sh", ["--subagents", "--platform", "claude"], env)
    assert res.returncode == 4
    assert "install-agents.sh" in res.stdout + res.stderr


def test_preflight_finds_installed_agent(tmp_path):
    env, _ = make_env(tmp_path)
    assert run("install-agents.sh", ["--copilot"], env).returncode == 0
    res = run("preflight.sh", ["--subagents", "--platform", "copilot"], env)
    assert res.returncode == 0
    res = run("preflight.sh", ["--subagents", "--platform", "claude"], env)
    assert res.returncode == 4


def test_install_agents_links_both(tmp_path):
    env, home = make_env(tmp_path)
    source = SKILL / "agents" / "k8s-crew-investigator.md"
    for _ in range(2):
        assert run("install-agents.sh", [], env).returncode == 0
    claude = home / ".claude/agents/k8s-crew-investigator.md"
    copilot = home / ".copilot/agents/k8s-crew-investigator.agent.md"
    for link in (claude, copilot):
        assert link.is_symlink()
        assert link.resolve() == source.resolve()


def test_install_agents_keeps_user_file(tmp_path):
    env, home = make_env(tmp_path)
    target = home / ".claude/agents/k8s-crew-investigator.md"
    target.parent.mkdir(parents=True)
    target.write_text("mine")
    res = run("install-agents.sh", ["--claude"], env)
    assert res.returncode != 0
    assert target.read_text() == "mine"
    assert not target.is_symlink()


def test_viewer_kubeconfig_writes_token_only_file(tmp_path):
    env, _ = make_env(tmp_path, guard=False)
    out = tmp_path / "viewer.kubeconfig"
    res = run("viewer-kubeconfig.sh", ["--out", str(out)], env)
    assert res.returncode == 0, res.stderr
    assert str(out) in res.stdout
    assert "fake-token-value" not in res.stdout + res.stderr
    assert (out.stat().st_mode & 0o777) == 0o600
    # The script builds the file itself from server, CA and token only.
    assert "https://example.com:6443" in out.read_text()
    assert "RkFLRS1DQQ==" in out.read_text()
    assert "FAKE-ADMIN-CERT" not in out.read_text()
    log = (tmp_path / "log").read_text()
    assert "create token crew-viewer -n k8s-crew --duration 8h" in log
    assert "apply -f" in log
    # --flatten inlines a CA given as a file path, also a relative one.
    assert "config view --raw --minify --flatten" in log
    assert "tls-server-name" not in out.read_text()
    assert "proxy-url" not in out.read_text()


def viewer_kubeconfig(tmp_path, **fake):
    env, _ = make_env(tmp_path, guard=False)
    env.update(fake)
    out = tmp_path / "viewer.kubeconfig"
    return run("viewer-kubeconfig.sh", ["--out", str(out)], env), out


def test_viewer_kubeconfig_carries_tls_server_name_and_proxy(tmp_path):
    res, out = viewer_kubeconfig(
        tmp_path, FAKE_TLS_NAME="api.example.com", FAKE_PROXY="http://proxy.example.com:3128"
    )
    assert res.returncode == 0, res.stderr
    text = out.read_text()
    assert "    tls-server-name: api.example.com\n" in text
    assert "    proxy-url: http://proxy.example.com:3128\n" in text


def test_viewer_kubeconfig_refuses_https_without_ca(tmp_path):
    res, out = viewer_kubeconfig(tmp_path, FAKE_CA="")
    assert res.returncode == 3
    assert "no CA" in res.stderr
    assert not out.exists()


def test_viewer_kubeconfig_keeps_insecure_skip_loudly(tmp_path):
    res, out = viewer_kubeconfig(tmp_path, FAKE_CA="", FAKE_INSECURE="true")
    assert res.returncode == 0, res.stderr
    assert "WARNING" in res.stderr
    assert "    insecure-skip-tls-verify: true\n" in out.read_text()


def test_viewer_kubeconfig_plain_http_needs_no_ca(tmp_path):
    res, out = viewer_kubeconfig(tmp_path, FAKE_CA="", FAKE_SERVER="http://127.0.0.1:8080")
    assert res.returncode == 0, res.stderr
    assert "certificate-authority-data" not in out.read_text()


def test_viewer_kubeconfig_refuses_no_server(tmp_path):
    res, out = viewer_kubeconfig(tmp_path, FAKE_SERVER="")
    assert res.returncode == 3
    assert not out.exists()


def test_preflight_finds_claude_agent_in_project(tmp_path):
    env, _ = make_env(tmp_path)
    project, work = make_project(tmp_path)
    agents = project / ".claude" / "agents"
    agents.mkdir(parents=True)
    (agents / "k8s-crew-investigator.md").write_text("x")
    res = run("preflight.sh", ["--subagents", "--platform", "claude"], env, cwd=work)
    assert res.returncode == 0, res.stdout
    assert "viewer ok" in res.stdout


@pytest.mark.parametrize(
    "rel",
    [
        ".github/agents/k8s-crew-investigator.agent.md",
        ".github/agents/k8s-crew-investigator.md",
        ".claude/agents/k8s-crew-investigator.md",
        ".claude/agents/k8s-crew-investigator.agent.md",
    ],
)
def test_preflight_finds_copilot_agent_in_project(tmp_path, rel):
    env, _ = make_env(tmp_path)
    project, work = make_project(tmp_path)
    target = project / rel
    target.parent.mkdir(parents=True)
    target.write_text("x")
    res = run("preflight.sh", ["--subagents", "--platform", "copilot"], env, cwd=work)
    assert res.returncode == 0, res.stdout


def test_preflight_copilot_home_agent_without_suffix(tmp_path):
    env, home = make_env(tmp_path)
    target = home / ".copilot" / "agents" / "k8s-crew-investigator.md"
    target.parent.mkdir(parents=True)
    target.write_text("x")
    res = run("preflight.sh", ["--subagents", "--platform", "copilot"], env, cwd=tmp_path)
    assert res.returncode == 0, res.stdout


def test_preflight_claude_ignores_github_agents(tmp_path):
    env, _ = make_env(tmp_path)
    project, work = make_project(tmp_path)
    target = project / ".github" / "agents" / "k8s-crew-investigator.agent.md"
    target.parent.mkdir(parents=True)
    target.write_text("x")
    res = run("preflight.sh", ["--subagents", "--platform", "claude"], env, cwd=work)
    assert res.returncode == 4


@pytest.mark.parametrize("platform", ["claude", "copilot"])
def test_preflight_agent_not_found_anywhere(tmp_path, platform):
    env, _ = make_env(tmp_path)
    _project, work = make_project(tmp_path)
    res = run("preflight.sh", ["--subagents", "--platform", platform], env, cwd=work)
    assert res.returncode == 4
    assert "investigator agent missing" in res.stdout
    assert "install-agents.sh" in res.stdout


def make_plugin_install(home, with_manifest=True, record=True, name="k8s-crew"):
    """A fake Claude Code plugin install of k8s-crew under HOME, as Claude Code lays it out."""
    root = home / ".claude" / "plugins" / "cache" / "k8s-crew" / "k8s-crew" / "0.1.0"
    agent = root / "skills" / "k8s-crew" / "agents" / "k8s-crew-investigator.md"
    agent.parent.mkdir(parents=True)
    agent.write_text("x")
    if with_manifest:
        (root / ".claude-plugin").mkdir()
        (root / ".claude-plugin" / "plugin.json").write_text(f'{{"name": "{name}"}}\n')
    if record:
        (home / ".claude" / "plugins" / "installed_plugins.json").write_text(
            '{"version": 2, "plugins": {"k8s-crew@k8s-crew": [{"scope": "user", '
            f'"installPath": "{root}", "version": "0.1.0"}}]}}}}\n'
        )
    return root


def test_preflight_names_user_install(tmp_path):
    env, _ = make_env(tmp_path)
    assert run("install-agents.sh", ["--claude"], env).returncode == 0
    res = run("preflight.sh", ["--subagents", "--platform", "claude"], env, cwd=tmp_path)
    assert res.returncode == 0, res.stdout
    assert "investigator: user k8s-crew-investigator" in res.stdout


def test_preflight_names_project_install(tmp_path):
    env, _ = make_env(tmp_path)
    project, work = make_project(tmp_path)
    agents = project / ".claude" / "agents"
    agents.mkdir(parents=True)
    (agents / "k8s-crew-investigator.md").write_text("x")
    res = run("preflight.sh", ["--subagents", "--platform", "claude"], env, cwd=work)
    assert "investigator: project k8s-crew-investigator" in res.stdout


def test_preflight_finds_claude_plugin_install(tmp_path):
    env, home = make_env(tmp_path)
    _project, work = make_project(tmp_path)
    make_plugin_install(home)
    res = run("preflight.sh", ["--subagents", "--platform", "claude"], env, cwd=work)
    assert res.returncode == 0, res.stdout
    assert "investigator: plugin k8s-crew:k8s-crew-investigator" in res.stdout
    assert "viewer ok" in res.stdout


def test_preflight_prefers_plain_install_over_plugin(tmp_path):
    env, home = make_env(tmp_path)
    make_plugin_install(home)
    assert run("install-agents.sh", ["--claude"], env).returncode == 0
    res = run("preflight.sh", ["--subagents", "--platform", "claude"], env, cwd=tmp_path)
    assert "investigator: user k8s-crew-investigator" in res.stdout


@pytest.mark.parametrize(
    "kwargs",
    [{"with_manifest": False}, {"record": False}, {"name": "something-else"}],
    ids=["no-plugin-json", "not-installed", "other-plugin"],
)
def test_preflight_rejects_incomplete_plugin_layout(tmp_path, kwargs):
    env, home = make_env(tmp_path)
    _project, work = make_project(tmp_path)
    make_plugin_install(home, **kwargs)
    res = run("preflight.sh", ["--subagents", "--platform", "claude"], env, cwd=work)
    assert res.returncode == 4, res.stdout


def test_preflight_copilot_ignores_claude_plugin(tmp_path):
    env, home = make_env(tmp_path)
    _project, work = make_project(tmp_path)
    make_plugin_install(home)
    res = run("preflight.sh", ["--subagents", "--platform", "copilot"], env, cwd=work)
    assert res.returncode == 4


def copy_skill_as_plugin(dest, with_manifest):
    """A copy of the skill folder inside a plugin root, run from there."""
    import shutil

    shutil.copytree(SKILL, dest / "skills" / "k8s-crew")
    if with_manifest:
        (dest / ".claude-plugin").mkdir(parents=True)
        (dest / ".claude-plugin" / "plugin.json").write_text('{"name": "k8s-crew"}\n')
    return dest / "skills" / "k8s-crew" / "scripts" / "preflight.sh"


@pytest.mark.parametrize("with_manifest", [True, False])
def test_preflight_running_from_plugin_cache(tmp_path, with_manifest):
    env, home = make_env(tmp_path)
    _project, work = make_project(tmp_path)
    root = home / ".claude" / "plugins" / "cache" / "my-marketplace" / "k8s-crew" / "abc123"
    script = copy_skill_as_plugin(root, with_manifest)
    args = ["bash", str(script), "--subagents", "--platform", "claude"]
    res = subprocess.run(args, capture_output=True, text=True, env=env, cwd=work, check=False)
    if with_manifest:
        assert res.returncode == 0, res.stdout
        assert "investigator: plugin k8s-crew:k8s-crew-investigator" in res.stdout
    else:
        assert res.returncode == 4, res.stdout


def test_preflight_ignores_plugin_checkout_outside_claude_plugins(tmp_path):
    # A git clone has .claude-plugin/plugin.json too, but nothing installed it.
    env, _ = make_env(tmp_path)
    _project, work = make_project(tmp_path)
    script = copy_skill_as_plugin(tmp_path / "clone", with_manifest=True)
    args = ["bash", str(script), "--subagents", "--platform", "claude"]
    res = subprocess.run(args, capture_output=True, text=True, env=env, cwd=work, check=False)
    assert res.returncode == 4, res.stdout
