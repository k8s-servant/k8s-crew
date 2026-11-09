"""Tests for crewcheck, the static check of the crew's skill, recipe, role, runners and agent.

Each test copies the real crew files into a temporary repository, breaks one thing and
expects the matching finding, so a finding can only come from the change under test.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tools.crewcheck import collect, run_check, write_agent

ROOT = Path(__file__).resolve().parents[2]
SKILL = "skills/k8s-crew"
AGENT = Path(SKILL) / "agents" / "k8s-crew-investigator.md"
RECIPE = f"{SKILL}/recipes/triage.md"
ROLE = f"{SKILL}/roles/investigator.md"
HERDR = f"{SKILL}/runners/herdr.md"
CONFIG = ROOT / SKILL / "config"

network = pytest.mark.skipif(os.environ.get("K8S_CREW_OFFLINE") == "1", reason="K8S_CREW_OFFLINE=1")

WRITE_VERBS = [
    "apply",
    "create",
    "delete",
    "edit",
    "patch",
    "replace",
    "scale",
    "set",
    "rollout restart",
    "rollout undo",
    "cordon",
    "uncordon",
    "drain",
    "taint",
    "label",
    "annotate",
    "exec",
    "cp",
    "port-forward",
    "debug",
]


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    shutil.copytree(ROOT / SKILL, repo / SKILL)
    return repo


def messages(repo: Path) -> list[str]:
    return [str(f) for f in collect(repo)]


def edit(repo: Path, rel: str, old: str, new: str) -> None:
    path = repo / rel
    text = path.read_text(encoding="utf-8")
    assert old in text, f"{old!r} not in {rel}"
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


@network
def test_copied_repo_is_clean(tmp_path):
    assert messages(make_repo(tmp_path)) == []


@network
def test_commands_in_markdown_are_run_freely(tmp_path):
    repo = make_repo(tmp_path)
    path = repo / RECIPE
    path.write_text(
        path.read_text(encoding="utf-8") + "\n```bash\nkubectl delete pod x\n```\n",
        encoding="utf-8",
    )
    found = messages(repo)
    assert any(m.startswith(f"{RECIPE}:") and "kubectl delete" in m for m in found)


@network
def test_ask_first_block_is_allowed(tmp_path):
    repo = make_repo(tmp_path)
    path = repo / RECIPE
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\n> Ask first: the agent runs this only after the user approves it.\n\n"
        + "```bash\nkubectl uncordon my-node\n# Undo: kubectl cordon my-node\n```\n",
        encoding="utf-8",
    )
    assert messages(repo) == []


@network
def test_crew_tool_line_with_embedded_write_is_found(tmp_path):
    repo = make_repo(tmp_path)
    path = repo / HERDR
    path.write_text(
        path.read_text(encoding="utf-8")
        + '\n```bash\nherdr pane run my-pane "kubectl delete pod x"\n```\n',
        encoding="utf-8",
    )
    assert any(m.startswith(f"{HERDR}:") for m in messages(repo))


@network
def test_secret_in_prose_command_is_found(tmp_path):
    repo = make_repo(tmp_path)
    path = repo / ROLE
    path.write_text(
        path.read_text(encoding="utf-8") + "\nRun `kubectl get secrets -A` first.\n",
        encoding="utf-8",
    )
    assert any("Secret" in m and m.startswith(f"{ROLE}:") for m in messages(repo))


@network
def test_report_headings_in_recipe_match(tmp_path):
    repo = make_repo(tmp_path)
    edit(repo, RECIPE, "## Separate issues", "## Other issues")
    assert any(m.startswith(RECIPE) and "## Separate issues" in m for m in messages(repo))


@network
def test_finding_headings_in_role_match(tmp_path):
    repo = make_repo(tmp_path)
    edit(repo, ROLE, "### Confidence", "### Certainty")
    write_agent(repo)
    assert any(m.startswith(ROLE) and "### Confidence" in m for m in messages(repo))


@network
def test_agent_has_no_write_tools(tmp_path):
    repo = make_repo(tmp_path)
    edit(repo, str(AGENT), "tools: Bash, Read, Grep, Glob", "tools: Bash, Edit")
    assert any(m.startswith(str(AGENT)) and "Edit" in m for m in messages(repo))


@network
def test_agent_without_tools_line_is_found(tmp_path):
    repo = make_repo(tmp_path)
    edit(repo, str(AGENT), "tools: Bash, Read, Grep, Glob\n", "")
    assert any(m.startswith(str(AGENT)) and "tools" in m for m in messages(repo))


@network
def test_agent_body_matches_role(tmp_path):
    repo = make_repo(tmp_path)
    path = repo / AGENT
    path.write_text(path.read_text(encoding="utf-8") + "\nExtra line.\n", encoding="utf-8")
    found = messages(repo)
    assert any("run python -m tools.crewcheck check --write" in m for m in found)
    write_agent(repo)
    assert messages(repo) == []


@network
def test_herdr_runner_forbids_resend(tmp_path):
    repo = make_repo(tmp_path)
    path = repo / HERDR
    path.write_text(
        path.read_text(encoding="utf-8").replace("agent_prompt_stalled", "stalled"),
        encoding="utf-8",
    )
    assert any(m.startswith(HERDR) and "agent_prompt_stalled" in m for m in messages(repo))


@network
def test_herdr_runner_sets_viewer_kubeconfig(tmp_path):
    repo = make_repo(tmp_path)
    path = repo / HERDR
    path.write_text(
        path.read_text(encoding="utf-8").replace("export KUBECONFIG=", "KUBECONFIG="),
        encoding="utf-8",
    )
    assert any(m.startswith(HERDR) and "export KUBECONFIG=" in m for m in messages(repo))


@network
def test_skill_frontmatter(tmp_path):
    repo = make_repo(tmp_path)
    edit(repo, "skills/k8s-crew/SKILL.md", "name: k8s-crew\n", "")
    assert any(m.startswith("skills/k8s-crew/SKILL.md") and "name" in m for m in messages(repo))

    repo = make_repo(tmp_path / "second")
    path = repo / "skills" / "k8s-crew" / "SKILL.md"
    text = path.read_text(encoding="utf-8")
    line = next(ln for ln in text.splitlines() if ln.startswith("argument-hint:"))
    value = line.split(":", 1)[1].strip().strip("\"'")
    path.write_text(text.replace(line, f"argument-hint: [{value}]"), encoding="utf-8")
    assert any(
        m.startswith("skills/k8s-crew/SKILL.md") and "argument-hint" in m for m in messages(repo)
    )


@network
def test_real_repo_is_clean(capsys):
    assert run_check(ROOT) == 0
    assert capsys.readouterr().out.startswith("ok")


def test_claude_settings_deny_write_verbs_and_secrets():
    settings = json.loads((CONFIG / "claude-settings.example.json").read_text())
    deny = settings["permissions"]["deny"]
    for verb in WRITE_VERBS:
        assert f"Bash(kubectl {verb} *)" in deny, verb
    assert "Bash(kubectl get secret*)" in deny


def test_copilot_deny_tools_prints_every_verb():
    done = subprocess.run(
        ["bash", str(CONFIG / "copilot-deny-tools.sh")],
        capture_output=True,
        text=True,
        check=True,
    )
    for verb in WRITE_VERBS:
        assert f"--deny-tool 'shell(kubectl {verb}:*)'" in done.stdout, verb
    assert "--deny-tool 'shell(kubectl get secret:*)'" in done.stdout
    assert "--deny-tool 'shell(kubectl get secrets:*)'" in done.stdout


@network
def test_crew_line_chained_to_other_program_is_found(tmp_path):
    repo = make_repo(tmp_path)
    path = repo / HERDR
    path.write_text(
        path.read_text(encoding="utf-8") + "\n```bash\nherdr agent list && rm -rf my-dir\n```\n",
        encoding="utf-8",
    )
    assert any(m.startswith(f"{HERDR}:") and "rm" in m for m in messages(repo))


@network
@pytest.mark.parametrize(
    "needle",
    [
        "read-only",
        '"Ask first"',
        '"Proposed fix"',
        "never read Secrets",
        "### Finding",
        "### Evidence",
        "### Confidence (confirmed | likely | not sure)",
        "### Proposed fixes",
        "roles/investigator.md",
        "if you cannot read",
    ],
)
def test_herdr_prompt_has_hard_rules_inline(tmp_path, needle):
    repo = make_repo(tmp_path)
    path = repo / HERDR
    text = path.read_text(encoding="utf-8")
    start = text.index("```text", text.index("## 6. Hand out the tasks")) + len("```text")
    prompt_end = text.index("```", start)
    prompt = text[start:prompt_end]
    assert needle in prompt
    path.write_text(text[:start] + prompt.replace(needle, "") + text[prompt_end:], encoding="utf-8")
    assert any(m.startswith(HERDR) and "helper prompt" in m for m in messages(repo))


@network
@pytest.mark.parametrize("line", ["skills:\n", "skills: my-skill\n", ""])
def test_agent_skills_must_be_a_list(tmp_path, line):
    repo = make_repo(tmp_path)
    edit(repo, str(AGENT), "skills: []\n", line)
    assert any(m.startswith(str(AGENT)) and "skills" in m for m in messages(repo))
