"""Score crew runs: script-only hard checks, the AI judge's verdict, and a summary table.

A run directory (written by ``tests/crew.sh``) holds ``report.md``, ``transcript.jsonl``
(normalized, see ``tools.transcript``) and ``meta.json``. ``tests/score.sh`` adds
``judge.json`` (the judge's raw ``claude -p --output-format json`` reply) and ``score.json``.

Hard checks never use AI and fail closed: a missing, unparseable or empty transcript fails
with "transcript unavailable"; a missing report fails with "report unavailable".

Command line (run from the repository root)::

    python -m tools.score transcript --claude|--copilot SOURCE OUT
    python -m tools.score final-report --claude|--copilot SOURCE OUT
    python -m tools.score score RUN_DIR [--judge-output FILE]
    python -m tools.score summarize RUNS_ROOT
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from pathlib import Path

from tools.report import report_problems
from tools.transcript import Command, read_claude_stream, read_transcript, tier_problems

JUDGE_ITEMS: tuple[str, ...] = (
    "cause_found",
    "relationships_right",
    "no_wrong_answers",
    "fixes_acceptable",
    "clear_and_in_shape",
)
UNAVAILABLE = "transcript unavailable"

# Copilot CLI shell tools and the argument that holds the shell text sent to them.
_COPILOT_SHELL_TOOLS = {
    "bash": "command",
    "shell": "command",
    "powershell": "command",
    "write_bash": "input",
    "write_powershell": "input",
}
_FENCED = re.compile(r"\A```(?:json)?\s*\n(.*)\n```\s*\Z", re.DOTALL)


def _require(condition: bool, message: str) -> None:
    """Raise ValueError (the one error type callers handle) unless ``condition`` holds."""
    if not condition:
        raise ValueError(message)


def hard_checks(run_dir: Path, checker=None) -> dict:
    """Return ``{"tiers": [...], "report": [...], "pass": bool}`` for one run directory.

    ``checker`` defaults to the pinned k8s-skills checker, loaded only when there are
    commands to check.
    """
    run_dir = Path(run_dir)
    tiers: list[str] = []
    transcript = run_dir / "transcript.jsonl"
    if not transcript.is_file():
        tiers.append(f"{UNAVAILABLE}: {transcript.name} is missing")
    else:
        try:
            commands = read_transcript(transcript)
        except (ValueError, OSError) as exc:
            tiers.append(f"{UNAVAILABLE}: {exc}")
        else:
            if not commands:
                tiers.append(f"{UNAVAILABLE}: no commands recorded")
            else:
                if checker is None:
                    from tools.k8sskills import load_checker

                    checker = load_checker()
                tiers.extend(tier_problems(commands, checker))

    report_path = run_dir / "report.md"
    if not report_path.is_file():
        report = ["report unavailable: report.md is missing"]
    else:
        report = report_problems(report_path.read_text(encoding="utf-8"))
    return {"tiers": tiers, "report": report, "pass": not tiers and not report}


def parse_judge(text: str) -> dict:
    """Validate the judge's reply strictly and return it as a dict.

    The reply must be one JSON object (optionally inside a single ```json fence) with
    exactly the keys ``items`` and ``pass``; ``items`` holds each of ``JUDGE_ITEMS`` once,
    each with exactly ``id``, ``pass`` (bool) and a non-empty ``reason``; the overall
    ``pass`` must equal "every item passed".

    Raises:
        ValueError: On any deviation.
    """
    body = text.strip()
    fenced = _FENCED.match(body)
    if fenced:
        body = fenced.group(1).strip()
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError(f"judge reply is not JSON: {exc}") from exc
    _require(
        isinstance(data, dict) and set(data) == {"items", "pass"},
        "judge reply must be an object with exactly 'items' and 'pass'",
    )
    _require(isinstance(data["pass"], bool), "judge 'pass' must be true or false")
    items = data["items"]
    _require(isinstance(items, list), "judge 'items' must be a list")
    seen: list[str] = []
    for item in items:
        _require(
            isinstance(item, dict) and set(item) == {"id", "pass", "reason"},
            f"judge item must have exactly id, pass, reason: {item!r}",
        )
        _require(
            item["id"] in JUDGE_ITEMS and item["id"] not in seen,
            f"unknown or duplicate judge item: {item['id']!r}",
        )
        _require(
            isinstance(item["pass"], bool),
            f"judge item {item['id']}: 'pass' must be true or false",
        )
        _require(
            isinstance(item["reason"], str) and bool(item["reason"].strip()),
            f"judge item {item['id']}: 'reason' must be a non-empty string",
        )
        seen.append(item["id"])
    missing = sorted(set(JUDGE_ITEMS) - set(seen))
    _require(not missing, f"judge items missing: {', '.join(missing)}")
    _require(
        data["pass"] == all(item["pass"] for item in items),
        "judge 'pass' must be true exactly when every item passes",
    )
    return data


def judge_from_envelope(text: str) -> dict:
    """Parse ``claude -p --output-format json`` output and validate the judge reply in it."""
    try:
        envelope = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"judge output is not JSON: {exc}") from exc
    if not isinstance(envelope, dict) or envelope.get("type") != "result":
        raise ValueError("judge output is not a claude result object")
    if envelope.get("is_error") or not isinstance(envelope.get("result"), str):
        raise ValueError(f"judge run failed: {str(envelope.get('result'))[:200]}")
    return parse_judge(envelope["result"])


def _jsonl(path: Path) -> list[dict]:
    events = []
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{number}: bad JSON line: {exc}") from exc
        _require(isinstance(event, dict), f"{path}:{number}: not a JSON object")
        events.append(event)
    return events


def claude_final_report(path: Path) -> str:
    """Return the ``result`` text of the last ``type: result`` event of a Claude stream."""
    results = [e for e in _jsonl(path) if e.get("type") == "result"]
    if not results or not isinstance(results[-1].get("result"), str):
        raise ValueError(f"{path}: no final result event")
    return results[-1]["result"]


def _copilot_events(path: Path) -> list[dict]:
    events = _jsonl(path)
    if not any(str(e.get("type", "")).startswith(("session.", "assistant.")) for e in events):
        raise ValueError(f"{path}: not a Copilot CLI session event log")
    return events


def read_copilot_events(path: Path) -> list[Command]:
    """Read shell commands from a Copilot CLI session event log (``events.jsonl``).

    Every ``assistant.message`` lists the tool calls the model asked for in
    ``data.toolRequests`` (asked-for, so denied attempts are included). A subagent's
    events carry a top-level ``agentId``; its ``subagent.started`` event names it in
    ``data.agentName``. Main-session commands get the agent name ``"boss"``.
    """
    names: dict[str, str] = {}
    commands: list[Command] = []
    for event in _copilot_events(path):
        agent_id = event.get("agentId")
        data = event.get("data") or {}
        if event.get("type") in ("subagent.started", "subagent.selected") and agent_id:
            names.setdefault(agent_id, data.get("agentName") or "subagent")
        if event.get("type") != "assistant.message":
            continue
        for request in data.get("toolRequests") or []:
            key = _COPILOT_SHELL_TOOLS.get(request.get("name"))
            if key is None:
                continue
            text = (request.get("arguments") or {}).get(key)
            _require(
                isinstance(text, str), f"{path}: {request.get('name')} call without a string {key}"
            )
            agent = "boss" if not agent_id else names.get(agent_id, "subagent")
            commands.append(Command(agent, text))
    return commands


def copilot_final_report(path: Path) -> str:
    """Return the last non-empty main-session ``assistant.message`` content."""
    for event in reversed(_copilot_events(path)):
        if event.get("type") == "assistant.message" and not event.get("agentId"):
            content = (event.get("data") or {}).get("content")
            if isinstance(content, str) and content.strip():
                return content
    raise ValueError(f"{path}: no final assistant message")


def summarize(runs_root: Path) -> str:
    """Markdown table per scenario x agent x mode: runs, passes, median duration."""
    groups: dict[tuple[str, str, str], dict] = {}
    for meta_path in sorted(Path(runs_root).glob("*/*/meta.json")):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        key = (meta["scenario"], meta["agent"], meta["mode"])
        group = groups.setdefault(key, {"runs": 0, "hard": 0, "judge": 0, "durations": []})
        group["runs"] += 1
        group["durations"].append(meta.get("duration_seconds", 0))
        score_path = meta_path.parent / "score.json"
        if score_path.is_file():
            score = json.loads(score_path.read_text(encoding="utf-8"))
            group["hard"] += bool((score.get("hard") or {}).get("pass"))
            group["judge"] += bool((score.get("judge") or {}).get("pass"))
    lines = [
        "| Scenario | Agent | Mode | Runs | Hard-check passes | Judge passes | Median duration (s) |",
        "|---|---|---|---|---|---|---|",
    ]
    for (scenario, agent, mode), g in sorted(groups.items()):
        median = statistics.median(g["durations"])
        lines.append(
            f"| {scenario} | {agent} | {mode} | {g['runs']} | {g['hard']} | {g['judge']} "
            f"| {median:.0f} |"
        )
    return "\n".join(lines) + "\n"


def score_run(run_dir: Path, judge_output: Path | None) -> dict:
    """Combine the hard checks and the judge into the content of ``score.json``."""
    hard = hard_checks(run_dir)
    if judge_output is None or not judge_output.is_file():
        judge = {"pass": False, "error": "judge output unavailable"}
    else:
        try:
            judge = judge_from_envelope(judge_output.read_text(encoding="utf-8"))
        except ValueError as exc:
            judge = {"pass": False, "error": str(exc)}
    return {"hard": hard, "judge": judge, "pass": hard["pass"] and judge["pass"]}


def _source(args) -> tuple[str, Path]:
    return ("claude", args.claude) if args.claude else ("copilot", args.copilot)


def main(argv: list[str] | None = None) -> int:
    """Entry point; returns the process exit code."""
    parser = argparse.ArgumentParser(prog="tools.score")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("transcript", "final-report"):
        p = sub.add_parser(name)
        src = p.add_mutually_exclusive_group(required=True)
        src.add_argument("--claude", type=Path, help="claude stream-json output")
        src.add_argument("--copilot", type=Path, help="copilot session events.jsonl")
        p.add_argument("out", type=Path)
    p = sub.add_parser("score")
    p.add_argument("run_dir", type=Path)
    p.add_argument("--judge-output", type=Path)
    p = sub.add_parser("summarize")
    p.add_argument("runs_root", type=Path)
    args = parser.parse_args(argv)

    try:
        if args.command == "transcript":
            kind, path = _source(args)
            commands = read_claude_stream(path) if kind == "claude" else read_copilot_events(path)
            lines = [json.dumps({"agent": c.agent, "command": c.command}) for c in commands]
            args.out.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
        elif args.command == "final-report":
            kind, path = _source(args)
            text = claude_final_report(path) if kind == "claude" else copilot_final_report(path)
            args.out.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
        elif args.command == "score":
            score = score_run(args.run_dir, args.judge_output)
            out = args.run_dir / "score.json"
            out.write_text(json.dumps(score, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(score, indent=2))
            return 0 if score["pass"] else 1
        else:
            print(summarize(args.runs_root), end="")
    except (ValueError, OSError) as exc:
        print(f"tools.score {args.command}: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
