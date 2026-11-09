from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_repo_has_license_and_agents_md():
    assert "Apache License" in (ROOT / "LICENSE").read_text()
    assert "Never read Secrets" in (ROOT / "AGENTS.md").read_text()


def test_plugin_manifest():
    import json

    manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
    assert manifest["name"] == "k8s-crew"
    assert manifest["license"] == "Apache-2.0"
    assert manifest["agents"] == ["./skills/k8s-crew/agents/k8s-crew-investigator.md"]
    assert manifest["skills"] == ["./skills/"]
    for path in manifest["agents"] + manifest["skills"]:
        assert (ROOT / path).exists(), path
    # k8s-skills lives in its own marketplace, so the dependency names it.
    deps = [d if isinstance(d, str) else d["name"] for d in manifest["dependencies"]]
    assert [d.split("@")[0] for d in deps] == ["k8s-skills"]

    market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
    assert market["name"] == "k8s-crew"
    assert [p["name"] for p in market["plugins"]] == ["k8s-crew"]
    assert market["plugins"][0]["source"] == "./"
    assert "k8s-skills" in market["allowCrossMarketplaceDependenciesOn"]

    # release-please owns the version: plugin.json is one of its extra files.
    config = json.loads((ROOT / "release-please-config.json").read_text())
    extra = config["packages"]["."]["extra-files"]
    assert {"type": "json", "path": ".claude-plugin/plugin.json", "jsonpath": "$.version"} in extra
