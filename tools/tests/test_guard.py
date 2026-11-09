"""Tests for the kubectl guard and the crew session launcher.

A fake ``kubectl``, ``claude`` and ``copilot`` on PATH record how they were called, so
nothing here talks to a cluster or starts a real agent.
"""

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "k8s-crew"
GUARD = SKILL / "scripts" / "kubectl-guard"
START = SKILL / "scripts" / "crew-start.sh"

FAKE_KUBECTL = """#!/usr/bin/env bash
echo "real kubectl KUBECONFIG=$KUBECONFIG KUBERC=${KUBERC:-} args=$*" >> "$FAKE_LOG"
exit 0
"""
# The fake agents record their environment and arguments, then try kubectl through PATH.
FAKE_AGENT = """#!/usr/bin/env bash
{
  echo "agent=$(basename "$0")"
  echo "KUBECONFIG=$KUBECONFIG"
  echo "K8S_CREW_GUARD=$K8S_CREW_GUARD"
  echo "kubectl=$(command -v kubectl)"
  printf 'arg=%s\\n' "$@"
} >> "$FAKE_LOG"
kubectl get pods > /dev/null 2>&1; echo "plain=$?" >> "$FAKE_LOG"
kubectl get pods --kubeconfig /tmp/admin > /dev/null 2>&1; echo "flag=$?" >> "$FAKE_LOG"
"""


@pytest.fixture
def env(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name, text in (("kubectl", FAKE_KUBECTL), ("claude", FAKE_AGENT), ("copilot", FAKE_AGENT)):
        (bindir / name).write_text(text)
        (bindir / name).chmod(0o755)
    home = tmp_path / "home"
    (home / ".kube").mkdir(parents=True)
    (home / ".kube" / "k8s-crew-viewer").write_text("fake viewer")
    (tmp_path / "tmp").mkdir()
    result = dict(os.environ)
    result.update(
        PATH=f"{bindir}:{os.environ['PATH']}",
        HOME=str(home),
        FAKE_LOG=str(tmp_path / "log"),
        TMPDIR=str(tmp_path / "tmp"),
    )
    for name in ("KUBECONFIG", "K8S_CREW_GUARD"):
        result.pop(name, None)
    return result


def install(tmp_path, env, viewer=None):
    """Install the guard into tmp_path/guard; return (bin dir, viewer path, env for it)."""
    viewer = viewer or tmp_path / "viewer.kubeconfig"
    viewer.write_text("fake viewer")
    bindir = tmp_path / "guard"
    bindir.mkdir()
    res = subprocess.run(
        ["bash", str(GUARD), "install", str(bindir), str(viewer)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, res.stderr
    guarded = {**env, "PATH": f"{bindir}:{env['PATH']}", "KUBECONFIG": str(viewer)}
    return bindir, viewer, guarded


def kubectl(env, *args):
    return subprocess.run(["kubectl", *args], env=env, capture_output=True, text=True, check=False)


def log(tmp_path):
    path = tmp_path / "log"
    return path.read_text() if path.exists() else ""


def test_guard_runs_real_kubectl_with_viewer(tmp_path, env):
    _bindir, viewer, guarded = install(tmp_path, env)
    res = kubectl(guarded, "get", "pods", "-n", "kube-system")
    assert res.returncode == 0, res.stderr
    assert f"real kubectl KUBECONFIG={viewer} KUBERC=off args=get pods -n kube-system" in log(
        tmp_path
    )


@pytest.mark.parametrize(
    "args",
    [
        ["get", "pods", "--kubeconfig", "/tmp/admin"],
        ["get", "pods", "--kubeconfig=/tmp/admin"],
        ["--context", "admin", "delete", "pod", "x"],
        ["-n", "x", "get", "pods", "--context=admin"],
        ["get", "pods", "--cluster", "other"],
        ["get", "pods", "--server", "https://example.com"],
        ["get", "pods", "-s", "https://example.com"],
        ["-shttps://example.com", "get", "pods"],
        ["-s=https://example.com", "get", "pods"],
        ["-As", "https://example.com", "get", "pods"],
        ["get", "pods", "--token", "abc"],
        ["get", "pods", "--user", "admin"],
        ["get", "pods", "--username=admin"],
        ["get", "pods", "--password=x"],
        ["get", "pods", "--as", "system:admin"],
        ["get", "pods", "--as-group=system:masters"],
        ["get", "pods", "--as-uid", "1"],
        ["get", "pods", "--client-certificate", "/tmp/c"],
        ["get", "pods", "--client-key=/tmp/k"],
        ["get", "pods", "--certificate-authority", "/tmp/ca"],
        ["get", "pods", "--kuberc", "/tmp/rc"],
    ],
)
def test_guard_refuses_target_flags(tmp_path, env, args):
    _bindir, _viewer, guarded = install(tmp_path, env)
    res = kubectl(guarded, *args)
    assert res.returncode == 126
    assert "k8s-crew kubectl guard" in res.stderr
    assert "real kubectl" not in log(tmp_path)


@pytest.mark.parametrize(
    "args",
    [
        ["get", "pods", "-nkube-system"],
        ["logs", "my-pod", "--since", "1h"],
        ["get", "pods", "-A", "-o", "wide"],
        ["get", "pods", "-l", "app=my-app"],
    ],
)
def test_guard_allows_ordinary_flags(tmp_path, env, args):
    _bindir, _viewer, guarded = install(tmp_path, env)
    assert kubectl(guarded, *args).returncode == 0


@pytest.mark.parametrize("value", [None, "/tmp/admin", "VIEWER:/tmp/admin"])
def test_guard_refuses_other_kubeconfig(tmp_path, env, value):
    _bindir, viewer, guarded = install(tmp_path, env)
    if value is None:
        guarded.pop("KUBECONFIG")
    else:
        guarded["KUBECONFIG"] = value.replace("VIEWER", str(viewer))
    res = kubectl(guarded, "get", "pods")
    assert res.returncode == 126
    assert "KUBECONFIG" in res.stderr
    assert "real kubectl" not in log(tmp_path)


def test_guard_refuses_bad_install(tmp_path, env):
    bindir = tmp_path / "guard"
    bindir.mkdir()
    for viewer in ("relative.kubeconfig", str(tmp_path / "missing"), "/tmp/a:/tmp/b"):
        res = subprocess.run(
            ["bash", str(GUARD), "install", str(bindir), viewer],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert res.returncode == 2, viewer
    assert not (bindir / "kubectl").exists()


def test_guard_not_installed_only_installs(tmp_path, env):
    res = subprocess.run(
        ["bash", str(GUARD), "get", "pods"], env=env, capture_output=True, text=True, check=False
    )
    assert res.returncode == 2
    assert "real kubectl" not in log(tmp_path)


def test_guard_skips_another_guard_when_nested(tmp_path, env):
    """A guard installed while another guard is first on PATH still finds the real kubectl."""
    _first, viewer, guarded = install(tmp_path, env)
    second = tmp_path / "guard2"
    second.mkdir()
    res = subprocess.run(
        ["bash", str(GUARD), "install", str(second), str(viewer)],
        env=guarded,
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, res.stderr
    real = (second / "kubectl-guard.conf").read_text()
    assert str(tmp_path / "bin" / "kubectl") in real


def start(env, *args, cwd=None):
    return subprocess.run(
        ["bash", str(START), *args], env=env, capture_output=True, text=True, check=False, cwd=cwd
    )


def agent_lines(tmp_path):
    return log(tmp_path).splitlines()


def test_start_claude_gets_guard_env_and_deny_settings(tmp_path, env):
    res = start(env, "claude", "--permission-mode", "default")
    assert res.returncode == 0, res.stderr
    lines = agent_lines(tmp_path)
    viewer = Path(env["HOME"]) / ".kube" / "k8s-crew-viewer"
    assert "agent=claude" in lines
    assert f"KUBECONFIG={viewer.resolve()}" in lines
    guard = next(x for x in lines if x.startswith("K8S_CREW_GUARD=")).split("=", 1)[1]
    assert guard and f"kubectl={guard}/kubectl" in lines
    settings = SKILL / "config" / "claude-settings.example.json"
    assert "arg=--settings" in lines
    assert f"arg={settings.resolve()}" in lines
    args = [x for x in lines if x.startswith("arg=")]
    assert args[-2:] == ["arg=--permission-mode", "arg=default"]
    assert "plain=0" in lines
    assert "flag=126" in lines


def test_start_claude_auto_allow_allows_read_verbs_only(tmp_path, env):
    res = start(env, "--auto-allow", "claude")
    assert res.returncode == 0, res.stderr
    args = [x[4:] for x in agent_lines(tmp_path) if x.startswith("arg=")]
    allowed = args[args.index("--allowedTools") + 1 : args.index("--settings")]
    assert "Bash(kubectl get *)" in allowed
    assert "Bash(kubectl auth can-i *)" in allowed
    assert not any(verb in rule for rule in allowed for verb in ("delete", "apply", "exec"))
    assert any(rule.endswith("/scripts/preflight.sh *)") for rule in allowed)


def test_start_copilot_gets_deny_rules(tmp_path, env):
    res = start(env, "--viewer", str(Path(env["HOME"]) / ".kube" / "k8s-crew-viewer"), "copilot")
    assert res.returncode == 0, res.stderr
    args = [x[4:] for x in agent_lines(tmp_path) if x.startswith("arg=")]
    assert "shell(kubectl delete:*)" in args
    assert "shell(kubectl --kubeconfig:*)" in args
    assert f"read({env['HOME']}/.kube/**)" in args
    assert "shell(kubectl:*)" not in args
    assert "flag=126" in agent_lines(tmp_path)


def test_start_copilot_auto_allow(tmp_path, env):
    res = start(env, "--auto-allow", "copilot", "--model", "x")
    assert res.returncode == 0, res.stderr
    args = [x[4:] for x in agent_lines(tmp_path) if x.startswith("arg=")]
    assert "shell(kubectl:*)" in args
    assert args[-2:] == ["--model", "x"]


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["codex"],
        ["--viewer"],
        ["--viewer", "/no/such/file", "claude"],
        ["--viewer", "/tmp/a:/tmp/b", "claude"],
    ],
)
def test_start_refuses_bad_arguments(tmp_path, env, args):
    res = start(env, *args)
    assert res.returncode == 2
    assert "agent=" not in log(tmp_path)


def test_start_needs_viewer_kubeconfig(tmp_path, env):
    (Path(env["HOME"]) / ".kube" / "k8s-crew-viewer").unlink()
    res = start(env, "claude")
    assert res.returncode == 2
    assert "viewer-kubeconfig.sh" in res.stderr
    assert "agent=" not in log(tmp_path)


def test_copilot_auto_allow_refused_without_launcher(tmp_path, env):
    deny = SKILL / "config" / "copilot-deny-tools.sh"
    res = subprocess.run(
        ["bash", str(deny), "--auto-allow", "--lines"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 3
    assert "crew-start.sh" in res.stderr


def test_start_shell_for_herdr_panes(tmp_path, env):
    res = start(
        env, "shell", "-c", "printenv KUBECONFIG; command -v kubectl; kubectl --context x get pods"
    )
    viewer = (Path(env["HOME"]) / ".kube" / "k8s-crew-viewer").resolve()
    out = res.stdout.splitlines()
    assert out[0] == str(viewer)
    assert out[1].endswith("/kubectl") and "k8s-crew-guard." in out[1]
    assert res.returncode == 126


SETTINGS = SKILL / "config" / "claude-settings.example.json"
DENY_SCRIPT = SKILL / "config" / "copilot-deny-tools.sh"
TARGET_FLAGS = [
    "--kubeconfig",
    "--context",
    "--cluster",
    "--server",
    "--token",
    "--user",
    "--username",
    "--password",
    "--as",
    "--as-group",
    "--as-uid",
    "--client-certificate",
    "--client-key",
    "--certificate-authority",
    "--kuberc",
]


def claude_denies() -> list[str]:
    import json

    return json.loads(SETTINGS.read_text())["permissions"]["deny"]


def copilot_rules(env) -> list[str]:
    res = subprocess.run(
        ["bash", str(DENY_SCRIPT), "--lines"], env=env, capture_output=True, text=True, check=True
    )
    return res.stdout.splitlines()


def test_claude_and_copilot_deny_the_same_kubectl_commands(env):
    import re

    copilot = set()
    for rule in copilot_rules(env):
        found = re.fullmatch(r"shell\(kubectl ([a-z][a-z -]*):\*\)", rule)
        if found:
            copilot.add(found.group(1))
    claude = set()
    for rule in claude_denies():
        found = re.fullmatch(r"Bash\(kubectl ([a-z][a-z -]*?)( \*|\*)?\)", rule)
        if found:
            verb = found.group(1)
            claude |= {verb, verb + "s"} if found.group(2) == "*" else {verb}
    assert copilot
    assert claude == copilot


def test_claude_denies_every_verb_with_and_without_arguments():
    denies = claude_denies()
    for rule in denies:
        if rule.startswith("Bash(kubectl ") and rule.endswith(" *)"):
            assert rule[:-3] + ")" in denies, rule


def test_claude_denies_target_flags_paths_and_private_files():
    denies = claude_denies()
    for flag in TARGET_FLAGS:
        assert f"Bash(kubectl *{flag}*)" in denies
    for rule in (
        "Bash(kubectl * -s *)",
        "Bash(kubectl -s*)",
        "Bash(*/kubectl *)",
        "Bash(*/kubectl)",
        "Bash(*KUBECONFIG=*)",
        "Bash(*PATH=*)",
        "Bash(*.kube/*)",
        "Read(~/.kube/**)",
        "Read(~/.claude/*)",
        "Read(~/.claude/projects/**)",
        "Read(~/.copilot/*)",
        "Read(~/.config/gh/**)",
    ):
        assert rule in denies


def test_copilot_denies_leading_target_flags_and_private_files(env):
    rules = copilot_rules(env)
    for flag in [*TARGET_FLAGS, "-s"]:
        assert f"shell(kubectl {flag}:*)" in rules
    home = env["HOME"]
    for path in (
        ".kube/**",
        ".claude/.credentials.json",
        ".claude/settings.json",
        ".claude/projects/**",
        ".copilot/config.json",
        ".copilot/session-state/**",
        ".config/gh/**",
    ):
        assert f"read({home}/{path})" in rules
