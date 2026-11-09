"""Tests for the kind test kit: the context guard and cluster.sh.

The scripts run against fake ``kubectl`` and ``kind`` executables placed first on
PATH, inside a throwaway copy of the repo layout, so the tests never touch a real
cluster or the real ``.kube/`` folder.
"""

import os
import shutil
import subprocess
from pathlib import Path

REAL_TESTS = Path(__file__).resolve().parents[2] / "tests"
CONTEXT = "kind-k8s-crew-test"
REFUSAL = f"refusing to run: current context is not {CONTEXT}"

FAKE_KUBECTL = """#!/usr/bin/env bash
echo "kubectl $*" >> "$FAKE_LOG"
case "$1 $2" in
  "config current-context") echo "${FAKE_CONTEXT:-}" ;;
esac
"""
FAKE_KIND = """#!/usr/bin/env bash
echo "kind $*" >> "$FAKE_LOG"
while [[ $# -gt 0 ]]; do
  if [[ "$1" == "--config" ]]; then cat "$2" >> "$FAKE_LOG"; fi
  shift
done
"""


def make_repo(tmp_path: Path) -> Path:
    """Copy the kit's scripts into a tmp repo and put fake kubectl/kind on PATH."""
    repo = tmp_path / "repo"
    shutil.copytree(REAL_TESTS, repo / "tests")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, text in (("kubectl", FAKE_KUBECTL), ("kind", FAKE_KIND)):
        path = bin_dir / name
        path.write_text(text)
        path.chmod(0o755)
    return repo


def run(
    repo: Path, tmp_path: Path, script: list[str], **env: str
) -> tuple[subprocess.CompletedProcess, str]:
    log = tmp_path / "calls.log"
    log.touch()
    full_env = {
        **os.environ,
        "PATH": f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}",
        "FAKE_LOG": str(log),
        **env,
    }
    proc = subprocess.run(
        script, cwd=repo, env=full_env, capture_output=True, text=True, check=False
    )
    return proc, log.read_text()


def test_lib_uses_own_cluster() -> None:
    text = (REAL_TESTS / "lib.sh").read_text()
    assert 'CLUSTER_NAME="k8s-crew-test"' in text
    assert "k8s-skills-test" not in text


def test_require_guard_refuses_other_context(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    (repo / ".kube").mkdir()
    (repo / ".kube" / "k8s-crew-test").write_text("fake")
    proc, _ = run(
        repo,
        tmp_path,
        ["bash", "-c", "source tests/lib.sh; require_test_cluster; echo ran"],
        FAKE_CONTEXT="kind-other",
    )
    assert proc.returncode == 2
    assert REFUSAL in proc.stderr
    assert "ran" not in proc.stdout


def test_require_guard_accepts_test_context(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    (repo / ".kube").mkdir()
    (repo / ".kube" / "k8s-crew-test").write_text("fake")
    proc, _ = run(
        repo,
        tmp_path,
        ["bash", "-c", "source tests/lib.sh; require_test_cluster; echo ran"],
        FAKE_CONTEXT=CONTEXT,
    )
    assert proc.returncode == 0
    assert "ran" in proc.stdout


def test_lib_uses_repo_kubeconfig(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    proc, _ = run(
        repo,
        tmp_path,
        ["bash", "-c", "source tests/lib.sh; echo $KUBECONFIG"],
        KUBECONFIG="/home/someone/.kube/config",
    )
    assert proc.stdout.strip() == str(repo / ".kube" / "k8s-crew-test")


def test_cluster_default_has_worker(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    proc, log = run(repo, tmp_path, ["bash", "tests/cluster.sh", "up"])
    assert proc.returncode == 0, proc.stderr
    assert "--name k8s-crew-test" in log
    assert "role: control-plane" in log
    assert log.count("role: worker") == 1
    assert "kubectl wait --for=condition=Ready nodes --all" in log


def test_cluster_workers_flag(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    _, log = run(repo, tmp_path, ["bash", "tests/cluster.sh", "up", "--workers", "2"])
    assert log.count("role: worker") == 2


def test_cluster_down_deletes_only_test_cluster(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    proc, log = run(repo, tmp_path, ["bash", "tests/cluster.sh", "down"])
    assert proc.returncode == 0, proc.stderr
    assert "kind delete cluster --name k8s-crew-test" in log


def test_cluster_usage_on_bad_args(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    proc, _ = run(repo, tmp_path, ["bash", "tests/cluster.sh", "up", "--cni", "calico"])
    assert proc.returncode == 64
