"""Check that every command a crew run executed is in the run-freely tier.

The check is default-deny: each piece of a command line (split on ``&&``, ``||``, ``;``
and newlines) must be either a cluster command that the pinned k8s-skills checker
passes, or one of the few local programs a crew run is told it may use (see
``LOCAL_PROGRAMS``). Anything else, such as ``docker``, ``ssh``, ``curl`` or
``systemctl``, fails the run: those reach a node or the API server around the checker.

Two transcript formats are read:

* Normalized JSONL: one object per line, ``{"agent": "<name>", "command": "<shell line>"}``.
* Claude Code stream JSON (``claude -p --output-format stream-json --verbose``). The
  assumed format, to be validated against a real run: one JSON object per line; objects
  with ``type == "assistant"`` carry ``message.content[]`` items, and the ones with
  ``type == "tool_use"`` and ``name == "Bash"`` hold the shell line in ``input.command``.
  Messages from a subagent carry a non-null ``parent_tool_use_id`` that equals the ``id``
  of the parent ``Agent``/``Task`` tool_use; that tool_use's ``input.subagent_type`` names
  the agent (fallback ``"subagent"``). Main-thread commands get the agent name ``"boss"``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

EXTRA_CLUSTER_TOOLS = ("helm", "flux", "argocd", "istioctl", "cilium", "velero")
_SEPARATORS = ("&&", "||", ";", "\n")

# Local programs a crew run may use besides cluster tools, each for one reason and only
# in the forms the crew's own files tell an agent to run. Keep it minimal: every entry is
# a way to act outside the pinned checker.
#   - the pipe filters: read stdin only (their flags and arguments are checked by the
#     pinned checker's filter rules, so any file argument fails);
#   - herdr: the boss's own orchestration in herdr mode, limited to HERDR_SUBCOMMANDS;
#     the text of ``herdr pane run`` is a command in another pane and is checked too,
#     and ``herdr agent start`` only takes the helper arguments runners/herdr.md gives;
#   - preflight.sh from a k8s-crew skill folder, by full path, with its documented flags;
#   - crew-start.sh only as the text of ``herdr pane run``, exactly
#     ``<skill-dir>/scripts/crew-start.sh --viewer <viewer kubeconfig> shell``: that is
#     the one form runners/herdr.md gives. Agents never start claude or copilot with it,
#     and any other form (``shell -c ...``, ``--auto-allow``, another kubeconfig) would
#     run outside this check;
#   - ``printenv NAME``: the herdr runner reads HERDR_ENV, PWD, HERDR_PANE_ID and
#     KUBECONFIG to write their values into later commands, since commands may not use
#     shell variables. One name per call: a bare printenv would print every variable.
FILTERS = ("grep", "egrep", "head", "tail", "sort", "uniq", "wc", "cut", "column", "jq")
LOCAL_PROGRAMS = (*FILTERS, "herdr", "preflight.sh", "crew-start.sh", "printenv")
HERDR_SUBCOMMANDS = {
    "pane": {"split", "list", "get", "layout", "run", "wait-output", "read", "close"},
    "agent": {"list", "get", "start", "prompt", "wait", "read"},
}
_PREFLIGHT = re.compile(r"/.*(?<![^/])k8s-crew/scripts/preflight\.sh")
_CREW_START = re.compile(r"/.*(?<![^/])k8s-crew/scripts/crew-start\.sh")
_CLAUDE_SETTINGS = re.compile(r"/.*(?<![^/])k8s-crew/config/claude-settings\.example\.json")
_PREFLIGHT_ARGS = (
    [],
    ["--subagents", "--platform", "claude"],
    ["--subagents", "--platform", "copilot"],
)
# The viewer kubeconfig names the crew writes: viewer-kubeconfig.sh's default
# (~/.kube/k8s-crew-viewer) and the test kit's (<run>/viewer.kubeconfig). Nothing in the
# transcript says which file the session was started with, so the name is the check;
# crew-start.sh itself refuses a file that is not a crew viewer kubeconfig.
_VIEWER = re.compile(r"/[^:]*/(k8s-crew-viewer|[^/:]*viewer\.kubeconfig)")
_HERDR_START_OPTIONS = {"--kind", "--pane", "--timeout"}
_ENV_NAME = re.compile(r"[A-Z_][A-Z0-9_]*")


@dataclass(frozen=True)
class Command:
    agent: str
    command: str


def _scan(line: str, separators: tuple[str, ...]) -> list[str]:
    """Split on top-level separators, honouring quotes and backslash escapes."""
    pieces: list[str] = []
    buf: list[str] = []
    quote = ""
    i = 0
    while i < len(line):
        ch = line[i]
        if quote:
            buf.append(ch)
            if ch == "\\" and quote == '"' and i + 1 < len(line):
                i += 1
                buf.append(line[i])
            elif ch == quote:
                quote = ""
        elif ch == "\\" and i + 1 < len(line):
            buf.append(ch + line[i + 1])
            i += 1
        elif ch in "'\"":
            quote = ch
            buf.append(ch)
        else:
            sep = next((s for s in separators if line.startswith(s, i)), None)
            if sep is None:
                buf.append(ch)
            else:
                pieces.append("".join(buf))
                buf = []
                i += len(sep) - 1
        i += 1
    if quote:
        raise ValueError(f"unterminated {quote} quote")
    pieces.append("".join(buf))
    return [p.strip() for p in pieces if p.strip()]


def split_command(line: str) -> list[str]:
    """Split on ``&&``, ``||``, ``;`` and newline outside quotes. Pipes stay in a piece."""
    return _scan(line, _SEPARATORS)


def is_cluster_command(piece: str, allowlist: dict) -> bool:
    """True when any word in the piece names a cluster tool.

    Deliberately broad: wrappers, substitutions and subshells all contain the tool name
    as a word, so they reach the strict checker. False positives fail closed.
    """
    tools = sorted(set(allowlist.get("commands", {})) | set(EXTRA_CLUSTER_TOOLS))
    pattern = r"(?<![\w./-])(?:[\w./-]*/)?(?:" + "|".join(map(re.escape, tools)) + r")(?![\w.-])"
    return re.search(pattern, piece) is not None


def _herdr_start_problems(args: list[str]) -> list[str]:
    """``herdr agent start <name> --kind K --pane P [--timeout N] -- <helper args>``."""
    if "--" not in args:
        return ["herdr agent start without the crew helper arguments after --"]
    split = args.index("--")
    options, helper = args[1:split], args[split + 1 :]
    pairs = dict(zip(options[::2], options[1::2], strict=False))
    if len(options) % 2 or not set(pairs) <= _HERDR_START_OPTIONS or len(pairs) * 2 != len(options):
        return [f"herdr agent start option not allowed: {' '.join(options)}"]
    kind = pairs.get("--kind")
    if kind == "claude":
        ok = (
            len(helper) == 4
            and helper[:3] == ["--permission-mode", "default", "--settings"]
            and _CLAUDE_SETTINGS.fullmatch(helper[3])
        )
        if not ok:
            return [
                (
                    "a Claude helper starts only with: --permission-mode default --settings "
                    "<skill-dir>/config/claude-settings.example.json"
                )
            ]
    elif kind == "copilot":
        rules = list(zip(helper[::2], helper[1::2], strict=False))
        ok = (
            helper
            and len(helper) % 2 == 0
            and all(
                (flag == "--deny-tool" and rule)
                or (flag == "--allow-tool" and rule == "shell(kubectl:*)")
                for flag, rule in rules
            )
        )
        if not ok:
            return ["a Copilot helper starts only with the copilot-deny-tools.sh --lines rules"]
    else:
        return [f"helper kind not allowed: {kind}"]
    return []


def _herdr_problems(args: list[str], checker, nested: bool) -> list[str]:
    if len(args) < 2 or args[1] not in HERDR_SUBCOMMANDS.get(args[0], ()):
        return [f"herdr command not allowed: herdr {' '.join(args[:2])}"]
    if args[:2] == ["pane", "run"]:
        if nested or len(args) != 4:
            return ["herdr pane run takes one pane and one command"]
        return [f"in pane: {problem}" for problem in command_problems(args[3], checker, True)]
    if args[:2] == ["agent", "start"]:
        return _herdr_start_problems(args[2:])
    return []


def _crew_start_problems(words: list[str], nested: bool) -> list[str]:
    if not nested:
        return ["crew-start.sh runs only as the text of herdr pane run"]
    ok = (
        len(words) == 4
        and _CREW_START.fullmatch(words[0])
        and words[1] == "--viewer"
        and _VIEWER.fullmatch(words[2])
        and words[3] == "shell"
    )
    if not ok:
        return [
            (
                "crew-start.sh is allowed only as: <skill-dir>/scripts/crew-start.sh "
                "--viewer <viewer kubeconfig> shell"
            )
        ]
    return []


def _local_problems(piece: str, checker, nested: bool = False) -> list[str]:
    """Problems of a piece that is not a cluster command; "herdr" marks herdr plumbing."""
    module = checker.commands_module
    segments = module._scan(piece)
    if segments == "control":
        return ["shell control not allowed"]
    if segments == "parse":
        return ["cannot parse command"]
    problems: list[str] = []
    for index, words in enumerate(segments):
        program = words[0] if words else ""
        name = program.rsplit("/", 1)[-1]
        if index and program not in FILTERS:
            problems.append("pipe must lead to an allow-listed filter")
        elif program in FILTERS:
            problems += module._check_filter(words, checker.allowlist)
        elif program == "herdr":
            problems.append("herdr")
        elif name == "preflight.sh":
            if not _PREFLIGHT.fullmatch(program) or words[1:] not in _PREFLIGHT_ARGS:
                problems.append(
                    "preflight.sh is allowed only by its full path in a k8s-crew skill "
                    "folder, with no flags or --subagents --platform claude|copilot"
                )
        elif name == "crew-start.sh":
            problems += _crew_start_problems(words, nested)
        elif program == "printenv":
            if len(words) != 2 or not _ENV_NAME.fullmatch(words[1]):
                problems.append("printenv takes exactly one variable name")
        else:
            problems.append(f"not an allowed program: {program or piece}")
    return problems


def command_problems(line: str, checker, nested: bool = False) -> list[str]:
    """Problems of one command line, each as ``'<piece>': <reason>``."""
    try:
        pieces = split_command(line)
    except ValueError as exc:
        return [f"cannot parse {line!r}: {exc}"]
    problems: list[str] = []
    for piece in pieces:
        local = _local_problems(piece, checker, nested)
        if "herdr" in local:
            # herdr plumbing: its own arguments (prompt text, agent flags) are not shell
            # commands; only the text of `herdr pane run` is checked as one.
            words = checker.commands_module._scan(piece)[0]
            reasons = [r for r in local if r != "herdr"]
            reasons += _herdr_problems(words[1:], checker, nested)
        elif is_cluster_command(piece, checker.allowlist):
            reasons = checker.check_command(piece) + checker.secret_problems(piece)
        else:
            reasons = local
        problems += [f"{piece!r}: {reason}" for reason in dict.fromkeys(reasons)]
    return problems


def tier_problems(commands: list[Command], checker) -> list[str]:
    """Problems for every command that is not run-freely, not allowed or touches Secrets."""
    problems: list[str] = []
    for cmd in commands:
        problems += [
            f"{cmd.agent}: {problem}" for problem in command_problems(cmd.command, checker)
        ]
    return problems


def read_transcript(path: Path) -> list[Command]:
    """Read the normalized JSONL format."""
    commands = []
    for number, line in enumerate(Path(path).read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
            commands.append(Command(str(obj["agent"]), str(obj["command"])))
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ValueError(f"{path}:{number}: bad transcript line: {exc}") from exc
    return commands


def read_claude_stream(path: Path) -> list[Command]:
    """Read Bash commands from Claude Code stream-json output (see module docstring)."""
    agent_names: dict[str, str] = {}
    commands: list[Command] = []
    for number, line in enumerate(Path(path).read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{number}: bad stream line: {exc}") from exc
        if event.get("type") != "assistant":
            continue
        parent = event.get("parent_tool_use_id")
        content = (event.get("message") or {}).get("content") or []
        for item in content:
            if not isinstance(item, dict) or item.get("type") != "tool_use":
                continue
            inp = item.get("input") or {}
            if item.get("name") in ("Agent", "Task"):
                agent_names[item.get("id", "")] = inp.get("subagent_type") or "subagent"
            elif item.get("name") == "Bash":
                if not isinstance(inp.get("command"), str):
                    raise ValueError(f"{path}:{number}: Bash tool_use without a string command")
                agent = "boss" if parent is None else agent_names.get(parent, "subagent")
                commands.append(Command(agent, inp["command"]))
    return commands
