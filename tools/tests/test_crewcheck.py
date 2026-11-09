"""Tests for crewcheck, the static check of the crew's skill, recipe, role, runners and agent.

Each test copies the real crew files into a temporary repository, breaks one thing and
expects the matching finding, so a finding can only come from the change under test.
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tools.crewcheck import collect, run_check, write_agent
from tools.k8sskills import load_checker

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


CREW_ASK = "> Ask first: changes the cluster. Run it yourself after review."
K8S_SKILLS_ASK = "> Ask first: the agent runs this only after the user approves it."


def append(repo: Path, rel: str, text: str) -> None:
    path = repo / rel
    path.write_text(path.read_text(encoding="utf-8") + text, encoding="utf-8")


@network
def test_crew_ask_first_block_is_allowed(tmp_path):
    repo = make_repo(tmp_path)
    append(
        repo,
        RECIPE,
        f"\n{CREW_ASK}\n\n```bash\nkubectl uncordon my-node\n# Undo: kubectl cordon my-node\n```\n",
    )
    assert messages(repo) == []


@network
def test_crew_ask_first_block_is_checked_as_ask_first(tmp_path):
    """The crew marker maps to the pinned checker's ask-first rules: an undo is required."""
    repo = make_repo(tmp_path)
    append(repo, RECIPE, f"\n{CREW_ASK}\n\n```bash\nkubectl uncordon my-node\n```\n")
    found = messages(repo)
    assert any(m.startswith(f"{RECIPE}:") and "ask-first change needs" in m for m in found)


@network
def test_k8s_skills_ask_marker_is_refused_in_crew_files(tmp_path):
    """In a crew report it would say the agent runs the fix after approval: it never does."""
    repo = make_repo(tmp_path)
    append(
        repo,
        RECIPE,
        f"\n{K8S_SKILLS_ASK}\n\n```bash\nkubectl uncordon my-node\n"
        "# Undo: kubectl cordon my-node\n```\n",
    )
    found = messages(repo)
    assert any(m.startswith(f"{RECIPE}:") and "crew ask-first marker" in m for m in found)


@network
def test_crew_marker_maps_to_the_pinned_marker():
    from tools.crewcheck import CREW_ASK_MARKER, crew_markdown

    module = load_checker().commands_module
    assert CREW_ASK_MARKER == CREW_ASK
    text = f"a\n{CREW_ASK}\n\nb\n"
    assert crew_markdown(text, module) == f"a\n{module.ASK_MARKER}\n\nb\n"


def test_report_template_and_role_use_the_crew_marker():
    for rel in (RECIPE, ROLE):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert CREW_ASK in text, rel
        assert K8S_SKILLS_ASK not in text, rel
        assert "> Proposed fix: review before running. The agent does not run this." in text


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
def test_herdr_runner_starts_panes_through_the_launcher(tmp_path):
    repo = make_repo(tmp_path)
    path = repo / HERDR
    path.write_text(
        path.read_text(encoding="utf-8").replace("crew-start.sh --viewer", "crew-start.sh"),
        encoding="utf-8",
    )
    assert any(m.startswith(HERDR) and "crew-start.sh --viewer" in m for m in messages(repo))


def herdr_commands() -> list[str]:
    text = (ROOT / HERDR).read_text(encoding="utf-8")
    blocks = re.findall(r"^```bash\n(.*?)^```", text, re.MULTILINE | re.DOTALL)
    return [line for block in blocks for line in block.splitlines() if line.strip()]


def test_herdr_runner_commands_follow_the_boss_rules():
    """SKILL.md: no shell variables, no chaining, no job control in the boss's commands."""
    commands = herdr_commands()
    assert commands
    for line in commands:
        assert "$" not in line, line
        assert not re.search(r"&\s*$|&&|\|\||;", line), line
        assert line.split()[0] != "wait", line
        assert not line.startswith("test "), line


def test_herdr_claude_helpers_get_the_deny_settings():
    starts = [c for c in herdr_commands() if c.startswith("herdr agent start") and "claude" in c]
    assert starts
    for line in starts:
        assert "--settings <skill-dir>/config/claude-settings.example.json" in line
        assert "--permission-mode default" in line


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
        "Ask first",
        "Proposed fix",
        "never read Secrets",
        "### Finding",
        "### Evidence",
        "### Confidence (confirmed | likely | not sure)",
        "### Proposed fixes",
        "roles/investigator.md",
        "if you cannot read",
        "one plain command per call",
        "pipe only into grep",
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


def _herdr_prompt_span(text):
    start = text.index("```text", text.index("## 6. Hand out the tasks")) + len("```text\n")
    return start, text.index("```", start)


@network
@pytest.mark.parametrize("char", ["$", "`", '"', "'"])
def test_herdr_prompt_has_no_shell_characters(tmp_path, char):
    repo = make_repo(tmp_path)
    path = repo / HERDR
    text = path.read_text(encoding="utf-8")
    start, end = _herdr_prompt_span(text)
    assert char not in text[start:end]
    path.write_text(text[:start] + f"Run {char}x. " + text[start:], encoding="utf-8")
    assert any(m.startswith(HERDR) and "must not contain" in m for m in messages(repo))


@network
def test_herdr_prompt_send_uses_single_quotes(tmp_path):
    repo = make_repo(tmp_path)
    path = repo / HERDR
    text = path.read_text(encoding="utf-8")
    assert "crew-claude '<prompt>'" in text
    path.write_text(text.replace("'<prompt>'", '"<prompt>"'), encoding="utf-8")
    assert any(m.startswith(HERDR) and "single quotes" in m for m in messages(repo))


@network
@pytest.mark.parametrize("needle", ["one plain command per call", "denied"])
def test_skill_states_plain_command_rule_for_the_boss(tmp_path, needle):
    repo = make_repo(tmp_path)
    path = repo / SKILL / "SKILL.md"
    text = path.read_text(encoding="utf-8")
    assert needle in text
    path.write_text(text.replace(needle, "x"), encoding="utf-8")
    assert any(m.startswith(f"{SKILL}/SKILL.md") and needle in m for m in messages(repo))


def guard_env(tmp_path: Path, env: dict | None = None) -> dict:
    """An environment where the kubectl guard looks active, as under crew-start.sh."""
    guard = tmp_path / "guard"
    guard.mkdir(exist_ok=True)
    (guard / "kubectl").write_text("#!/usr/bin/env bash\n")
    (guard / "kubectl").chmod(0o755)
    env = dict(env or os.environ)
    env.update(PATH=f"{guard}:{env['PATH']}", K8S_CREW_GUARD=str(guard))
    return env


def copilot_args(*args, env=None):
    done = subprocess.run(
        ["bash", str(CONFIG / "copilot-deny-tools.sh"), *args],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    return done.stdout


@pytest.mark.parametrize("auto", [False, True])
def test_copilot_lines_have_no_quotes_and_pair_each_flag(tmp_path, auto):
    prefix = ["--auto-allow"] if auto else []
    lines = copilot_args(*prefix, "--lines", env=guard_env(tmp_path)).splitlines()
    assert not any(c in "".join(lines) for c in "'\"\\`$")
    pairs = list(zip(lines[::2], lines[1::2], strict=True))
    allows = [rule for flag, rule in pairs if flag == "--allow-tool"]
    # Deny-only unless auto-allow is chosen: flags before a subcommand bypass the denies.
    assert allows == (["shell(kubectl:*)"] if auto else [])
    if auto:
        assert lines[:2] == ["--allow-tool", "shell(kubectl:*)"]
    assert all(flag in ("--allow-tool", "--deny-tool") for flag, _ in pairs)
    denied = {rule for flag, rule in pairs if flag == "--deny-tool"}
    for verb in WRITE_VERBS + ["get secret", "get secrets", "describe secret", "config"]:
        assert f"shell(kubectl {verb}:*)" in denied, verb
    # Copilot 1.0.107 matches leading words only: no wildcard before the end of a rule.
    for _flag, rule in pairs:
        if rule.startswith("shell("):
            assert "*" not in rule.removesuffix(":*)"), rule
        else:
            assert rule.startswith("read(") and "*" not in rule.removesuffix("/**)"), rule


@network
def test_copilot_denies_every_kubectl_command_that_is_not_run_freely():
    from tools.k8sskills import load_checker

    allowlist = load_checker().allowlist
    run_freely = {c.split()[0] for c in allowlist["commands"]["kubectl"]}
    lines = copilot_args("--lines").splitlines()
    denied = {
        rule.removeprefix("shell(kubectl ").removesuffix(":*)")
        for flag, rule in zip(lines[::2], lines[1::2], strict=True)
        if flag == "--deny-tool"
    }
    for name in allowlist["kubectl_commands"]:
        if name not in run_freely and name != "help":
            assert name in denied, name
    for sub in ("rollout restart", "rollout undo", "rollout pause", "rollout resume"):
        assert sub in denied
    assert "auth reconcile" in denied


@pytest.mark.parametrize("prefix", ["", "--auto-allow"])
def test_copilot_default_output_evals_to_the_same_arguments(tmp_path, prefix):
    script = CONFIG / "copilot-deny-tools.sh"
    env = guard_env(tmp_path)
    done = subprocess.run(
        ["bash", "-c", f'eval "flags=($(bash {script} {prefix}))"; printf "%s\\n" "${{flags[@]}}"'],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    args = [prefix] if prefix else []
    assert done.stdout == copilot_args(*args, "--lines", env=env)


@pytest.mark.parametrize("prefix", [[], ["--auto-allow"]])
def test_copilot_run_starts_copilot_with_the_rules(tmp_path, prefix):
    fake = tmp_path / "copilot"
    fake.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$@"\n')
    fake.chmod(0o755)
    env = guard_env(tmp_path, {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"})
    out = copilot_args(*prefix, "--run", "--agent", "my-agent", env=env)
    assert out == copilot_args(*prefix, "--lines", env=env) + "--agent\nmy-agent\n"


TRIGGER_NEEDLES = ["**Trigger, not precondition.**", "One issue, one section."]


@network
@pytest.mark.parametrize("needle", TRIGGER_NEEDLES)
def test_recipe_separates_trigger_from_preconditions(tmp_path, needle):
    repo = make_repo(tmp_path)
    path = repo / RECIPE
    text = path.read_text(encoding="utf-8")
    assert needle in text
    path.write_text(text.replace(needle, "x"), encoding="utf-8")
    assert any(m.startswith(RECIPE) and needle in m for m in messages(repo))


@pytest.mark.parametrize("rel", [RECIPE, ROLE])
def test_agents_are_told_the_command_shapes_the_check_reads(rel):
    text = (ROOT / rel).read_text(encoding="utf-8")
    assert "`-o name`" in text and "`-o wide`" in text
    assert "no file arguments" in text


EVIDENCE_RULES = {
    RECIPE: [
        "**Scoped tasks.**",
        "**Confirmed needs shown evidence.**",
        "**Timestamps are not history.**",
        "**Fix the cause, not its effects.**",
    ],
    ROLE: [
        "**No speculative weaknesses.**",
        "**Confirmed needs shown evidence.**",
        "**Timestamps are not history.**",
        "**Fix the cause, not its effects.**",
    ],
}


@network
@pytest.mark.parametrize(
    ("rel", "needle"), [(rel, n) for rel, needles in EVIDENCE_RULES.items() for n in needles]
)
def test_evidence_discipline_rules_are_required(tmp_path, rel, needle):
    repo = make_repo(tmp_path)
    path = repo / rel
    text = path.read_text(encoding="utf-8")
    assert needle in text
    path.write_text(text.replace(needle, "x"), encoding="utf-8")
    assert any(m.startswith(rel) and needle in m for m in messages(repo))


def test_herdr_prompt_carries_the_evidence_rules():
    text = (ROOT / HERDR).read_text(encoding="utf-8")
    for rule in ("no speculative weaknesses", "confirmed only", "never a knock-on effect"):
        assert rule in text, rule


AGENT_FILE = f"{SKILL}/agents/k8s-crew-investigator.md"
SKILL_SUMMARY_RULES = [
    "no speculative weaknesses",
    "`confirmed` only with a command result shown",
    "a timestamp alone is not a recent change",
    "fixes for the cause and not its knock-on effects",
]


@network
@pytest.mark.parametrize("needle", SKILL_SUMMARY_RULES)
def test_skill_summary_carries_the_evidence_rules(tmp_path, needle):
    repo = make_repo(tmp_path)
    path = repo / SKILL / "SKILL.md"
    text = path.read_text(encoding="utf-8")
    assert needle in text
    path.write_text(text.replace(needle, "x"), encoding="utf-8")
    assert any(m.startswith(f"{SKILL}/SKILL.md") and needle in m for m in messages(repo))


@network
@pytest.mark.parametrize("needle", EVIDENCE_RULES[ROLE])
def test_generated_agent_carries_the_evidence_rules(tmp_path, needle):
    """Checked on the agent file itself, not only through the role it is built from."""
    repo = make_repo(tmp_path)
    path = repo / AGENT_FILE
    text = path.read_text(encoding="utf-8")
    assert needle in text
    path.write_text(text.replace(needle, "x"), encoding="utf-8")
    found = messages(repo)
    assert any(m.startswith(AGENT_FILE) and needle in m for m in found), found


def test_role_and_skill_lines_are_wrapped():
    for rel in (ROLE, f"{SKILL}/SKILL.md"):
        lines = (ROOT / rel).read_text(encoding="utf-8").splitlines()
        long = [n for n, line in enumerate(lines, 1) if len(line) > 92]
        assert not long, (rel, long)


JQ_LIMITS = "no string interpolation"


@network
@pytest.mark.parametrize("rel", [RECIPE, ROLE, AGENT_FILE, HERDR])
def test_agents_are_told_the_jq_limits(tmp_path, rel):
    repo = make_repo(tmp_path)
    path = repo / rel
    text = path.read_text(encoding="utf-8")
    assert JQ_LIMITS in text
    assert "-r, -c, -e, -s or --arg" in text.replace("`", "")
    path.write_text(text.replace(JQ_LIMITS, "x"), encoding="utf-8")
    assert any(m.startswith(rel) and JQ_LIMITS in m for m in messages(repo))
