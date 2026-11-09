"""Check that a crew report has the fixed shape.

Script-only gate: the six H2 headings appear exactly once, in order, with no other H2
between or around them; ``## Fixes`` has at least one fenced code block, or says exactly
"No fixes needed."; every fenced block under it has a ``# Undo:`` line and no ``# Undo:``
line is empty; the ``## Fixes`` prose never claims a fix was run (the crew only prints
fixes). A fix given only as prose or an indented block has no checkable undo, so it fails.
"""

from __future__ import annotations

import re

REPORT_SECTIONS: tuple[str, ...] = (
    "## Root cause",
    "## Knock-on effects",
    "## Separate issues",
    "## Fixes",
    "## What was checked",
    "## Helper details",
)

_FIXES = "## Fixes"
_FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
_UNDO = re.compile(r"^\s*# Undo:")
_EMPTY_UNDO = re.compile(r"^\s*# Undo:\s*$")
NO_FIXES = "No fixes needed."
_RAN = re.compile(r"\b(I ran|I applied|has been applied)\b", re.IGNORECASE)


def report_problems(markdown: str) -> list[str]:
    """Return a list of human-readable problems; empty means the report is well-formed."""
    headings: list[str] = []
    fix_prose: list[str] = []
    fix_blocks: list[list[str]] = []
    fence: str | None = None
    section = ""

    for line in markdown.splitlines():
        match = _FENCE.match(line)
        if fence is not None:
            if match and match.group(1)[0] == fence[0] and len(match.group(1)) >= len(fence):
                fence = None
            elif section == _FIXES:
                fix_blocks[-1].append(line)
            continue
        if match:
            fence = match.group(1)
            if section == _FIXES:
                fix_blocks.append([])
            continue
        if line.startswith("## "):
            section = line.rstrip()
            headings.append(section)
        elif section == _FIXES:
            fix_prose.append(line)

    problems: list[str] = []
    for heading in REPORT_SECTIONS:
        if heading not in headings:
            problems.append(f"missing heading: {heading}")
    for heading in headings:
        if heading not in REPORT_SECTIONS:
            problems.append(f"unexpected heading: {heading}")
        elif headings.count(heading) > 1:
            problems.append(f"duplicate heading: {heading}")
    known = [h for h in headings if h in REPORT_SECTIONS]
    if not problems and known != list(REPORT_SECTIONS):
        problems.append("headings are out of order; expected: " + ", ".join(REPORT_SECTIONS))

    prose = " ".join(line.strip() for line in fix_prose if line.strip())
    if _FIXES in headings and not fix_blocks and prose != NO_FIXES:
        problems.append(
            f"{_FIXES} has no fenced fix block; with no fixes it must say exactly: {NO_FIXES}"
        )
    for number, block in enumerate(fix_blocks, start=1):
        if not any(_UNDO.match(line) for line in block):
            problems.append(f"{_FIXES} code block {number} is missing # Undo: line")
        elif any(_EMPTY_UNDO.match(line) for line in block):
            problems.append(f"{_FIXES} code block {number} has an empty # Undo: line")
    for line in fix_prose:
        if _RAN.search(line):
            problems.append(
                f"{_FIXES} claims a fix was run (crew never runs fixes): {line.strip()}"
            )
    return problems
