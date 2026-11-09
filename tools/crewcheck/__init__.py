"""Static checks for the crew's skill, recipe, role, runners and investigator agent.

The crew is Markdown an agent follows, so the checks hold it to the same promises as
k8s-skills: every command it shows is in the run-freely tier unless it sits in a marked
ask-first or proposed-fix block, nothing reads Secrets, and the fixed report and finding
shapes are spelled out where the agents read them. Commands are checked with the pinned
k8s-skills checker (``tools.k8sskills``), never a copy of it.

A few lines in fenced blocks drive the crew's own tooling (``herdr``, the scripts in
``scripts/``). They are not cluster commands, so they are allowed by name; any kubectl or
az command written inside them is still checked.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from pathlib import Path

import yaml

from tools.k8sskills import Checker, load_checker
from tools.report import REPORT_SECTIONS

FINDING_SECTIONS: tuple[str, ...] = (
    "### Finding",
    "### Evidence",
    "### Confidence",
    "### Proposed fixes",
)

# The skill folder is all that `npx skills add` installs, so everything the crew needs is in it.
SKILL_DIR = Path("skills/k8s-crew")
AGENT = SKILL_DIR / "agents" / "k8s-crew-investigator.md"
ROLE = SKILL_DIR / "roles" / "investigator.md"
RECIPE = SKILL_DIR / "recipes" / "triage.md"
HERDR_RUNNER = SKILL_DIR / "runners" / "herdr.md"
AGENT_NAME = "k8s-crew-investigator"
AGENT_TOOLS = {"Bash", "Read", "Grep", "Glob"}
WRITE_HINT = "run python -m tools.crewcheck check --write"
GENERATED_NOTE = (
    "<!-- Generated from roles/investigator.md by python -m tools.crewcheck check --write."
    " Do not edit by hand. -->\n\n"
)
# Programs of the crew's own tooling, allowed as the first word of a line in a code block.
# A script may also be written by its full path, as <skill-dir>/scripts/<name>.
CREW_PROGRAMS = {
    "herdr",
    "printenv",
    "scripts/preflight.sh",
    "scripts/crew-start.sh",
    "scripts/install-agents.sh",
    "scripts/viewer-kubeconfig.sh",
    "config/copilot-deny-tools.sh",
}
REQUIRED_TEXT = {
    SKILL_DIR / "SKILL.md": (
        ("one plain command per call", "must state one plain command per call for the boss"),
        ("denied", "must say what the boss does when a command is denied"),
    ),
    RECIPE: (
        (
            "**Trigger, not precondition.**",
            "must state the rule **Trigger, not precondition.** for the root cause",
        ),
        ("One issue, one section.", "must state the rule One issue, one section."),
    ),
    HERDR_RUNNER: (
        ("agent_prompt_stalled", "must say what to do on agent_prompt_stalled (never resend)"),
        (
            "crew-start.sh --viewer",
            "must give every helper pane the guard with scripts/crew-start.sh --viewer",
        ),
    ),
}
# herdr helpers have no agent definition, so their prompt must carry the hard rules itself.
HERDR_PROMPT_HEADING = "## 6. Hand out the tasks"
HERDR_PROMPT_RULES = (
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
)
# The prompt is sent as one single-quoted shell argument, so nothing in it may be shell-active.
HERDR_PROMPT_FORBIDDEN = ("$", "`", '"', "'")
HERDR_SEND = re.compile(r"^herdr agent prompt (\S+) (.*)$")
# The crew never runs a fix, so its files and reports cannot use the k8s-skills ask-first
# marker, which says "the agent runs this only after the user approves it". They use this
# marker instead. It is mapped to the pinned checker's marker before parsing, so the
# pinned ask-first rules (an allow-listed change, an # Undo: line) still apply to the
# block under it.
CREW_ASK_MARKER = "> Ask first: changes the cluster. Run it yourself after review."


@dataclass(frozen=True)
class Finding:
    """One problem, printed as ``path:line: message`` (``path: message`` without a line)."""

    path: Path
    line: int | None
    message: str

    def __str__(self) -> str:
        where = str(self.path) if self.line is None else f"{self.path}:{self.line}"
        return f"{where}: {self.message}"


def split_frontmatter(text: str) -> tuple[str | None, str, int]:
    """Return (frontmatter text, body, 1-based line of the body's first line)."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None, text, 1
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return "\n".join(lines[1:index]), "\n".join(lines[index + 1 :]), index + 2
    return None, text, 1


def _parse_meta(raw: str | None, rel: Path) -> tuple[dict, list[Finding]]:
    if raw is None:
        return {}, [Finding(rel, 1, "frontmatter missing")]
    try:
        meta = yaml.safe_load(raw) or {}
    except yaml.YAMLError as exc:
        return {}, [Finding(rel, 1, f"frontmatter is not valid YAML: {exc}")]
    if not isinstance(meta, dict):
        return {}, [Finding(rel, 1, "frontmatter is not a mapping")]
    return meta, []


def _crew_line_problems(command: str, checker: Checker) -> list[str] | None:
    """Problems of a line that runs a crew program, or None if it is not one."""
    try:
        first = shlex.split(command)[0]
    except (ValueError, IndexError):
        return None
    if first.removeprefix("<skill-dir>/") not in CREW_PROGRAMS:
        return None
    module = checker.commands_module
    keys = set(checker.allowlist["commands"])
    problems = list(checker.secret_problems(command))
    for embedded in module._embedded_commands(command, keys):
        problems += checker.check_command(embedded.strip("'\" "))
    problems += _chain_problems(command, checker)
    return problems


def _chain_problems(command: str, checker: Checker) -> list[str]:
    """Every command chained with ``&&``, ``||``, ``;``, ``&`` or ``|`` must be allowed too."""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|")
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        return [f"cannot parse command: {command}"]
    segments: list[tuple[str, list[str]]] = [("", [])]
    for token in tokens:
        if token and set(token) <= set(";&|"):
            segments.append((token, []))
        else:
            segments[-1][1].append(token)
    problems: list[str] = []
    for operator, words in segments[1:]:
        if not words or words[0].removeprefix("<skill-dir>/") in CREW_PROGRAMS:
            continue
        if operator == "|" and words[0] in checker.allowlist["filters"]:
            continue
        problems += checker.check_command(shlex.join(words))
    return problems


def crew_markdown(text: str, module) -> str:
    """The text with each crew ask-first marker line replaced by the pinned marker."""
    lines = text.split("\n")
    return "\n".join(module.ASK_MARKER if ln.rstrip() == CREW_ASK_MARKER else ln for ln in lines)


def check_markdown(rel: Path, text: str, first_line: int, checker: Checker) -> list[Finding]:
    """Check every command in a Markdown text the way k8s-skills checks a skill."""
    module = checker.commands_module
    allowlist = checker.allowlist
    found: list[Finding] = [
        Finding(rel, first_line + offset, f"use the crew ask-first marker: {CREW_ASK_MARKER}")
        for offset, line in enumerate(text.split("\n"))
        if line.strip() == module.ASK_MARKER
    ]
    text = crew_markdown(text, module)
    blocks, prose = module._parse_markdown(
        text,
        first_line,
        frozenset(allowlist["commands"]),
        frozenset(allowlist["kubectl_commands"]),
        frozenset(allowlist["az_groups"]),
    )
    keys = set(allowlist["commands"])
    for block in blocks:
        if block.lang is None:
            found.append(Finding(rel, block.start_line, "fenced block needs a language"))
            continue
        is_command_lang = block.lang in allowlist["command_langs"]
        has_undo = any(ln.strip().startswith(module.UNDO_PREFIX) for ln in block.lines)
        mode = "other"
        if is_command_lang:
            mode = "console" if block.lang == "console" else "command"
        if block.is_fix and is_command_lang and not has_undo:
            found.append(Finding(rel, block.start_line, "proposed fix needs an '# Undo:' line"))
        if block.is_ask and not is_command_lang:
            found.append(Finding(rel, block.start_line, module.ASK_LANG_MESSAGE))
        if block.is_ask and is_command_lang and not has_undo:
            commands = module._commands_in(block.lines, block.start_line + 1, mode, keys)
            if any(module._is_ask_change(c, allowlist) for _, c in commands):
                found.append(Finding(rel, block.start_line, module.ASK_UNDO_MESSAGE))
        if block.is_fix or block.is_ask or mode == "other":
            kind = module._kind(block)
            for line_no, message in module._check_lines(
                block.lines, block.start_line + 1, kind, allowlist, mode
            ):
                found.append(Finding(rel, line_no, message))
            continue
        for line_no, command in module._commands_in(block.lines, block.start_line + 1, mode, keys):
            problems = _crew_line_problems(command, checker)
            if problems is None:
                problems = checker.secret_problems(command) + checker.check_command(command)
            found += [Finding(rel, line_no, m) for m in dict.fromkeys(problems)]
    for line_no, command in prose:
        for message in checker.secret_problems(command) + checker.check_command(command):
            found.append(Finding(rel, line_no, message))
    return found


def _headings_in_order(rel: Path, text: str, headings: tuple[str, ...], what: str):
    lines = [ln.strip() for ln in text.splitlines()]
    found: list[Finding] = []
    for heading in headings:
        if heading not in lines:
            found.append(Finding(rel, None, f"{what} is missing heading: {heading}"))
    if not found:
        positions = [lines.index(h) for h in headings]
        if positions != sorted(positions):
            found.append(
                Finding(rel, None, f"{what} headings out of order; expected: {', '.join(headings)}")
            )
    return found


def check_herdr_prompt(text: str, checker: Checker) -> list[Finding]:
    """The helper prompt template (first text block under the heading) has the hard rules."""
    lines = text.split("\n")
    heading = next((i + 1 for i, ln in enumerate(lines) if ln.strip() == HERDR_PROMPT_HEADING), 0)
    blocks = checker.commands_module.extract_blocks(text)
    prompt = next((b for b in blocks if b.start_line > heading and b.lang == "text"), None)
    if not heading or prompt is None:
        return [
            Finding(
                HERDR_RUNNER, None, f"helper prompt template missing under {HERDR_PROMPT_HEADING}"
            )
        ]
    body = " ".join(prompt.lines)
    found = [
        Finding(HERDR_RUNNER, prompt.start_line, f"helper prompt must contain inline: {rule}")
        for rule in HERDR_PROMPT_RULES
        if rule not in body
    ]
    found += [
        Finding(HERDR_RUNNER, prompt.start_line, f"helper prompt must not contain: {char}")
        for char in HERDR_PROMPT_FORBIDDEN
        if char in body
    ]
    sends = [
        (b.start_line + 1 + i, HERDR_SEND.match(line.strip()))
        for b in blocks
        if b.lang in ("bash", "sh", "shell")
        for i, line in enumerate(b.lines)
    ]
    sends = [(n, m) for n, m in sends if m]
    if not sends:
        found.append(Finding(HERDR_RUNNER, None, "no herdr agent prompt example found"))
    for line_no, match in sends:
        if not re.match(r"'[^']*'(\s|$)", match.group(2)):
            found.append(
                Finding(
                    HERDR_RUNNER,
                    line_no,
                    "herdr agent prompt must send the prompt in single quotes",
                )
            )
    return found


def check_skill(repo: Path, skill_file: Path) -> list[Finding]:
    """Frontmatter both Claude Code and Copilot CLI accept."""
    rel = skill_file.relative_to(repo)
    raw, _body, _line = split_frontmatter(skill_file.read_text(encoding="utf-8"))
    meta, found = _parse_meta(raw, rel)
    if found:
        return found
    if not meta.get("name"):
        found.append(Finding(rel, 1, "frontmatter needs a name"))
    elif meta["name"] != skill_file.parent.name:
        found.append(Finding(rel, 1, f"name must equal the folder: {skill_file.parent.name}"))
    if not meta.get("description"):
        found.append(Finding(rel, 1, "frontmatter needs a description"))
    for number, line in enumerate(raw.split("\n"), start=2):
        if line.startswith("argument-hint:"):
            value = line.split(":", 1)[1].strip()
            quoted = value[:1] in ('"', "'")
            if not quoted or not isinstance(meta.get("argument-hint"), str):
                found.append(Finding(rel, number, "argument-hint must be a quoted string"))
    return found


def expected_agent(repo: Path, agent_text: str) -> str:
    """The agent file with its frontmatter kept and its body generated from the role."""
    raw, _body, _line = split_frontmatter(agent_text)
    role = (repo / ROLE).read_text(encoding="utf-8")
    return f"---\n{raw}\n---\n\n{GENERATED_NOTE}{role}"


def check_agent(repo: Path) -> list[Finding]:
    """Name, read-only tools, and a body generated from the role."""
    path = repo / AGENT
    if not path.is_file():
        return [Finding(AGENT, None, "investigator agent missing")]
    text = path.read_text(encoding="utf-8")
    raw, _body, _line = split_frontmatter(text)
    meta, found = _parse_meta(raw, AGENT)
    if found:
        return found
    if meta.get("name") != AGENT_NAME:
        found.append(Finding(AGENT, 1, f"name must be {AGENT_NAME}"))
    if not meta.get("description"):
        found.append(Finding(AGENT, 1, "frontmatter needs a description"))
    tools = meta.get("tools")
    if not isinstance(tools, str) or not tools.strip():
        found.append(Finding(AGENT, 1, "tools must list only: " + ", ".join(sorted(AGENT_TOOLS))))
    else:
        for tool in (t.strip() for t in tools.split(",")):
            if tool not in AGENT_TOOLS:
                found.append(Finding(AGENT, 1, f"tool not allowed for the investigator: {tool}"))
    if not isinstance(meta.get("skills"), list):
        # Copilot CLI refuses the agent when skills is missing a value ("Expected array").
        found.append(Finding(AGENT, 1, "skills must be a YAML list, for example skills: []"))
    if (repo / ROLE).is_file() and text != expected_agent(repo, text):
        found.append(Finding(AGENT, None, f"body differs from {ROLE}: {WRITE_HINT}"))
    return found


def write_agent(repo: Path) -> None:
    """Regenerate the agent body from the role, keeping the agent's frontmatter."""
    path = repo / AGENT
    path.write_text(expected_agent(repo, path.read_text(encoding="utf-8")), encoding="utf-8")


def collect(repo: Path, checker: Checker | None = None) -> list[Finding]:
    """Run every check over a repository and return the findings, sorted."""
    checker = checker or load_checker()
    found: list[Finding] = []

    def markdown(path: Path, body_only: bool = False) -> None:
        rel = path.relative_to(repo)
        text = path.read_text(encoding="utf-8")
        body, first = text, 1
        if body_only:
            _raw, body, first = split_frontmatter(text)
        found.extend(check_markdown(rel, body, first, checker))

    skills = sorted((repo / "skills").glob("*/SKILL.md"))
    if not skills:
        found.append(Finding(Path("skills"), None, "no skills/*/SKILL.md found"))
    for skill in skills:
        found.extend(check_skill(repo, skill))
        markdown(skill, body_only=True)
        for ref in sorted(skill.parent.rglob("*.md")):
            if ref != skill and ref != repo / AGENT:
                markdown(ref)
    for rel in (RECIPE, ROLE, HERDR_RUNNER):
        if not (repo / rel).is_file():
            found.append(Finding(rel, None, "file missing"))
    if (repo / RECIPE).is_file():
        text = (repo / RECIPE).read_text(encoding="utf-8")
        found += _headings_in_order(RECIPE, text, REPORT_SECTIONS, "report template")
    if (repo / ROLE).is_file():
        text = (repo / ROLE).read_text(encoding="utf-8")
        found += _headings_in_order(ROLE, text, FINDING_SECTIONS, "finding template")
    for rel, rules in REQUIRED_TEXT.items():
        if (repo / rel).is_file():
            text = (repo / rel).read_text(encoding="utf-8")
            found += [Finding(rel, None, msg) for needle, msg in rules if needle not in text]
    if (repo / HERDR_RUNNER).is_file():
        found += check_herdr_prompt((repo / HERDR_RUNNER).read_text(encoding="utf-8"), checker)
    found += check_agent(repo)
    if (repo / AGENT).is_file():
        markdown(repo / AGENT, body_only=True)
    unique = set(found)
    return sorted(unique, key=lambda f: (str(f.path), f.line or 0, f.message))


def run_check(repo: Path, write: bool = False) -> int:
    """Check a repository, print each finding, return the exit code (0 when clean)."""
    if write and (repo / AGENT).is_file() and (repo / ROLE).is_file():
        write_agent(repo)
    found = collect(repo)
    for finding in found:
        print(finding)
    if found:
        return 1
    print("ok: crew files are clean")
    return 0
