"""Command line: ``python -m tools.crewcheck check [--write] [--repo PATH]``."""

import argparse
import sys
from pathlib import Path

from tools.crewcheck import run_check


def main(argv: list[str] | None = None) -> int:
    """Entry point; returns the process exit code."""
    parser = argparse.ArgumentParser(prog="crewcheck")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="check the crew skill, recipe, role, runners and agent")
    check.add_argument("--repo", type=Path, default=Path.cwd(), help="repository root")
    check.add_argument(
        "--write",
        action="store_true",
        help="regenerate the investigator agent body from roles/investigator.md first",
    )
    args = parser.parse_args(argv)
    return run_check(args.repo.resolve(), write=args.write)


if __name__ == "__main__":
    sys.exit(main())
