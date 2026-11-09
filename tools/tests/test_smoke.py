from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_repo_has_license_and_agents_md():
    assert "Apache License" in (ROOT / "LICENSE").read_text()
    assert "Never read Secrets" in (ROOT / "AGENTS.md").read_text()
