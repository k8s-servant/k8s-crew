"""Check that every cluster command a crew run executed is in the run-freely tier.

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
from dataclasses import dataclass
from pathlib import Path

EXTRA_CLUSTER_TOOLS = ("helm", "flux", "argocd", "istioctl", "cilium", "velero")
_SEPARATORS = ("&&", "||", ";", "\n")


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


def _pipe_stages(piece: str) -> list[str]:
    # "||" is consumed first so it is never mistaken for two pipes.
    stages: list[str] = []
    for part in _scan(piece, ("||",)):
        stages.extend(_scan(part, ("|",)))
    return stages


def _first_word(stage: str) -> str:
    for word in stage.split():
        if "=" in word and not word.startswith(("-", "=")) and word.split("=")[0].isidentifier():
            continue  # leading VAR=value assignment
        return word.rsplit("/", 1)[-1]
    return ""


def is_cluster_command(piece: str, allowlist: dict) -> bool:
    """True when any pipeline stage of the piece starts with a cluster tool."""
    known = set(allowlist.get("commands", {})) | set(EXTRA_CLUSTER_TOOLS)
    try:
        stages = _pipe_stages(piece)
    except ValueError:
        stages = [piece]
    return any(_first_word(stage) in known for stage in stages)


def tier_problems(commands: list[Command], checker) -> list[str]:
    """Problems for every cluster command that is not run-freely or touches Secrets."""
    problems: list[str] = []
    for cmd in commands:
        try:
            pieces = split_command(cmd.command)
        except ValueError as exc:
            problems.append(f"{cmd.agent}: cannot parse {cmd.command!r}: {exc}")
            continue
        for piece in pieces:
            if not is_cluster_command(piece, checker.allowlist):
                continue
            for reason in checker.check_command(piece) + checker.secret_problems(piece):
                problems.append(f"{cmd.agent}: {piece!r}: {reason}")
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
            elif item.get("name") == "Bash" and "command" in inp:
                agent = "boss" if parent is None else agent_names.get(parent, "subagent")
                commands.append(Command(agent, inp["command"]))
    return commands
