import os
import subprocess
from pathlib import Path

import pytest

from tools import k8sskills
from tools.k8sskills import load_checker, read_ref, read_sha

network = pytest.mark.skipif(os.environ.get("K8S_CREW_OFFLINE") == "1", reason="K8S_CREW_OFFLINE=1")


def test_ref_read_from_versions_env():
    assert read_ref() == "v0.10.0"


@network
def test_checker_accepts_read_only():
    assert load_checker().check_command("kubectl get pods -A") == []


@network
def test_checker_rejects_write():
    assert load_checker().check_command("kubectl delete pod my-app -n my-namespace") != []


@network
def test_checker_flags_secret():
    assert load_checker().secret_problems("kubectl get secret -n my-namespace") != []


@network
def test_commands_module_exposes_extract_blocks():
    assert hasattr(load_checker().commands_module, "extract_blocks")


@network
def test_own_tools_package_not_clobbered():
    import sys

    load_checker()
    import tools.k8sskills

    assert tools.k8sskills.__file__.startswith(os.getcwd())
    assert not any(m.startswith("tools.skillcheck") for m in sys.modules)


def test_sha_read_from_versions_env():
    assert read_sha() == "de23b57dd3888628abc62c20d2ed322751fc7d12"


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _make_origin(path):
    path.mkdir()
    _git("init", "-q", cwd=path)
    (path / "f.txt").write_text("x")
    _git("add", ".", cwd=path)
    _git("-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "c", cwd=path)
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=path, check=True, capture_output=True, text=True
    ).stdout.strip()
    _git("config", "uploadpack.allowReachableSHA1InWant", "true", cwd=path)
    return sha


@pytest.fixture
def origin(tmp_path, monkeypatch):
    src = tmp_path / "origin"
    sha = _make_origin(src)
    monkeypatch.setattr(k8sskills, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(k8sskills, "REPO_URL", src.as_uri())
    monkeypatch.setattr(k8sskills, "read_sha", lambda: sha)
    return sha


def test_fetch_clones_the_pinned_sha(origin):
    path = k8sskills.fetch("vtest")
    assert (path / "f.txt").exists()


def test_fetch_replaces_a_checkout_at_the_wrong_commit(origin, tmp_path):
    bad = tmp_path / "cache" / "k8s-skills-vtest"
    bad.mkdir(parents=True)
    _git("init", "-q", cwd=bad)
    (bad / "evil.py").write_text("raise SystemExit")
    _git("add", ".", cwd=bad)
    _git("-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "e", cwd=bad)
    path = k8sskills.fetch("vtest")
    assert not (path / "evil.py").exists()
    assert (path / "f.txt").exists()


def test_fetch_replaces_a_checkout_with_modified_files(origin):
    path = k8sskills.fetch("vtest")
    (path / "f.txt").write_text("tampered")
    (path / "extra.py").write_text("raise SystemExit")
    again = k8sskills.fetch("vtest")
    assert (again / "f.txt").read_text() == "x"
    assert not (again / "extra.py").exists()
    assert k8sskills._dirty(again) == ""


def test_fetch_replaces_a_checkout_with_ignored_files(origin):
    path = k8sskills.fetch("vtest")
    (path / ".git" / "info" / "exclude").write_text("*.pyc\n")
    (path / "hidden.pyc").write_text("x")
    assert not (k8sskills.fetch("vtest") / "hidden.pyc").exists()


def test_fetch_rejects_wrong_commit(origin, tmp_path, monkeypatch):
    def download_wrong_commit(sha, target):
        target.mkdir(parents=True)
        _git("init", "-q", cwd=target)
        (target / "evil.py").write_text("raise SystemExit")
        _git("add", ".", cwd=target)
        _git(
            "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "e", cwd=target
        )

    monkeypatch.setattr(k8sskills, "_download", download_wrong_commit)
    with pytest.raises(RuntimeError) as err:
        k8sskills.fetch("vtest")
    assert origin in str(err.value)
    assert not (tmp_path / "cache" / "k8s-skills-vtest").exists()


def test_git_helper_always_disables_config_driven_code(monkeypatch, tmp_path):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(k8sskills.subprocess, "run", fake_run)
    k8sskills._git("status", cwd=tmp_path)
    k8sskills._head(tmp_path)
    k8sskills._dirty(tmp_path)
    assert calls
    for cmd, kwargs in calls:
        assert cmd[:5] == ["git", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null"]
        assert kwargs["env"]["GIT_CONFIG_NOSYSTEM"] == "1"
        assert kwargs["env"]["GIT_CONFIG_GLOBAL"] == "/dev/null"


def test_every_git_call_goes_through_the_helper():
    source = Path(k8sskills.__file__).read_text()
    assert source.count("subprocess.run(") == 1


def test_ci_does_not_restore_the_checkout_from_a_cache():
    ci = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"
    assert "actions/cache" not in ci.read_text()
