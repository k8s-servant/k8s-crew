"""Structure tests for the multi-fault kind scenarios in tests/scenarios/.

These never touch a cluster: they read the files, and run each script against fake
``kubectl`` and ``docker`` executables with the wrong context to prove the guard stops
it before anything else runs.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCENARIOS_DIR = ROOT / "tests" / "scenarios"
SCENARIOS = ("node-dns-cascade", "rollout-plus-storage", "healthy-noise")
SCRIPTS = ("setup.sh", "break.sh", "cleanup.sh")
FILES = (*SCRIPTS, "expected.md")
SECTIONS = [
    "Prompt",
    "Causes",
    "Relationships",
    "Evidence",
    "Acceptable fixes",
    "Wrong answers",
    "Must not run",
]

FAKE_TOOL = """#!/usr/bin/env bash
echo "$(basename "$0") $*" >> "$FAKE_LOG"
case "$1 $2" in
  "config current-context") echo "kind-other" ;;
esac
"""


def scenario_files() -> list[Path]:
    return [SCENARIOS_DIR / s / f for s in SCENARIOS for f in FILES]


def test_only_the_v1_scenarios_exist() -> None:
    found = sorted(p.name for p in SCENARIOS_DIR.iterdir() if p.is_dir())
    assert found == sorted(SCENARIOS)


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_scenario_has_all_files(scenario: str) -> None:
    for name in FILES:
        assert (SCENARIOS_DIR / scenario / name).is_file(), f"{scenario}/{name} missing"


@pytest.mark.parametrize("scenario", SCENARIOS)
@pytest.mark.parametrize("script", SCRIPTS)
def test_script_is_guarded(scenario: str, script: str) -> None:
    path = SCENARIOS_DIR / scenario / script
    assert os.access(path, os.X_OK), f"{scenario}/{script} not executable"
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "#!/usr/bin/env bash"
    assert "set -euo pipefail" in lines
    assert any(re.match(r'source "\$\(dirname "\$0"\)/\.\./\.\./lib\.sh"', ln) for ln in lines)
    guard = lines.index("require_test_cluster")
    # Nothing may talk to a cluster or a node before the guard.
    for line in lines[:guard]:
        assert not re.search(r"\b(kubectl|docker|kind)\b", line.split("#")[0]), line


@pytest.mark.parametrize("scenario", SCENARIOS)
@pytest.mark.parametrize("script", SCRIPTS)
def test_script_refuses_other_context(tmp_path: Path, scenario: str, script: str) -> None:
    repo = tmp_path / "repo"
    shutil.copytree(ROOT / "tests", repo / "tests")
    (repo / ".kube").mkdir()
    (repo / ".kube" / "k8s-crew-test").write_text("fake")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for tool in ("kubectl", "docker", "kind"):
        (bindir / tool).write_text(FAKE_TOOL)
        (bindir / tool).chmod(0o755)
    log = tmp_path / "calls.log"
    log.touch()
    env = {**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}", "FAKE_LOG": str(log)}
    proc = subprocess.run(
        ["bash", str(repo / "tests" / "scenarios" / scenario / script)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2, proc.stderr
    assert log.read_text().splitlines() == ["kubectl config current-context"]


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_expected_sections_exact_and_in_order(scenario: str) -> None:
    text = (SCENARIOS_DIR / scenario / "expected.md").read_text(encoding="utf-8")
    headings = re.findall(r"^## (.+)$", text, flags=re.MULTILINE)
    assert headings == SECTIONS
    assert text.startswith(f"# {scenario}\n")
    bodies = re.split(r"^## .+$", text, flags=re.MULTILINE)[1:]
    for title, body in zip(SECTIONS, bodies, strict=True):
        assert body.strip(), f"{scenario}: section {title} is empty"


@pytest.mark.parametrize("path", scenario_files(), ids=lambda p: f"{p.parent.name}/{p.name}")
def test_no_secret_in_kubectl_commands(path: Path) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        if "kubectl" in line:
            assert "secret" not in line.lower(), line


@pytest.mark.parametrize("path", scenario_files(), ids=lambda p: f"{p.parent.name}/{p.name}")
def test_uses_the_crew_test_cluster_only(path: Path) -> None:
    assert "k8s-skills-test" not in path.read_text(encoding="utf-8")


SETUP_KUBECTL = """#!/usr/bin/env bash
echo "kubectl $*" >> "$FAKE_LOG"
case "$*" in
  "config current-context") echo "kind-k8s-crew-test" ;;
  *"get replicasets"*) echo "coredns-unpinned coredns-older" ;;
esac
exit 0
"""
SETUP_SLEEP = """#!/usr/bin/env bash
echo "sleep $*" >> "$FAKE_LOG"
"""


def run_dns_setup(tmp_path: Path, settle: str | None) -> list[str]:
    repo = tmp_path / "repo"
    shutil.copytree(ROOT / "tests", repo / "tests")
    (repo / ".kube").mkdir()
    (repo / ".kube" / "k8s-crew-test").write_text("fake")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name, text in (("kubectl", SETUP_KUBECTL), ("sleep", SETUP_SLEEP)):
        (bindir / name).write_text(text)
        (bindir / name).chmod(0o755)
    log = tmp_path / "calls.log"
    log.touch()
    env = {**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}", "FAKE_LOG": str(log)}
    if settle is not None:
        env["CREW_PIN_SETTLE_SECONDS"] = settle
    proc = subprocess.run(
        ["bash", str(repo / "tests" / "scenarios" / "node-dns-cascade" / "setup.sh")],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return log.read_text().splitlines()


def test_dns_setup_makes_the_pin_look_settled(tmp_path: Path) -> None:
    """The pin is a standing weakness, not today's change (local test: the crew read
    managedFields and saw it 30 s before the fault)."""
    calls = run_dns_setup(tmp_path, None)
    patch = next(i for i, c in enumerate(calls) if "patch deployment coredns" in c)
    # The unpinned ReplicaSet is removed, so rollout history shows only the pinned one.
    find = next(i for i, c in enumerate(calls) if "get replicasets" in c)
    delete = calls.index("kubectl -n kube-system delete replicaset coredns-unpinned coredns-older")
    assert patch < find < delete
    assert "spec.replicas" in calls[find] and "0" in calls[find]
    # Then it settles before break.sh runs: the default wait is 120 s, after everything.
    assert calls[-1] == "sleep 120"


def test_dns_setup_settle_time_can_be_changed(tmp_path: Path) -> None:
    assert run_dns_setup(tmp_path, "300")[-1] == "sleep 300"
    assert run_dns_setup(tmp_path / "zero", "0")[-1].startswith("kubectl ")


def test_dns_cleanup_restores_one_coredns_replicaset(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    shutil.copytree(ROOT / "tests", repo / "tests")
    (repo / ".kube").mkdir()
    (repo / ".kube" / "k8s-crew-test").write_text("fake")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fakes = (
        ("kubectl", SETUP_KUBECTL.replace("coredns-unpinned coredns-older", "coredns-pinned")),
        ("docker", SETUP_SLEEP.replace("sleep", "docker")),
    )
    for name, text in fakes:
        (bindir / name).write_text(text)
        (bindir / name).chmod(0o755)
    log = tmp_path / "calls.log"
    log.touch()
    env = {**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}", "FAKE_LOG": str(log)}
    script = repo / "tests" / "scenarios" / "node-dns-cascade" / "cleanup.sh"
    proc = subprocess.run(
        ["bash", str(script)], env=env, capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stderr
    calls = log.read_text().splitlines()
    rollout = calls.index("kubectl -n kube-system rollout status deployment/coredns --timeout=180s")
    delete = calls.index("kubectl -n kube-system delete replicaset coredns-pinned")
    assert rollout < delete
