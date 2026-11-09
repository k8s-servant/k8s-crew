"""Tests for the viewer identity, preflight and agent install scripts.

The scripts run against a fake ``kubectl`` first on PATH and a throwaway HOME, so the
tests never touch a real cluster or the real ``~/.claude`` / ``~/.kube`` folders.
"""

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "k8s-crew"
SCRIPTS = SKILL / "scripts"

FAKE_KUBECTL = """#!/usr/bin/env bash
echo "kubectl $*" >> "$FAKE_LOG"
case "$1 $2" in
  "auth can-i") echo "${FAKE_CAN_I:-no}"; [[ "${FAKE_CAN_I:-no}" == "no" ]] && exit 1 || exit 0 ;;
  "create token") echo "fake-token-value" ;;
  "config view")
    case "$*" in
      *cluster.server*) echo "https://example.com:6443" ;;
      *certificate-authority-data*) echo "RkFLRS1DQQ==" ;;
      *) echo "client-certificate-data: FAKE-ADMIN-CERT" ;;
    esac ;;
esac
exit 0
"""


def make_env(tmp_path, can_i="no"):
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
    return env, home


def run(script, args, env):
    return subprocess.run(
        ["bash", str(SCRIPTS / script), *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


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


def test_preflight_fails_closed_on_error(tmp_path):
    env, _ = make_env(tmp_path, can_i="error: unable to connect")
    res = run("preflight.sh", [], env)
    assert res.returncode == 3


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
    env, _ = make_env(tmp_path)
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
