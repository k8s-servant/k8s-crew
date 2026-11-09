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
