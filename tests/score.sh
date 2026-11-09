#!/usr/bin/env bash
# Score one crew run: script-only hard checks (tools/score.py), then the AI judge
# (tests/judge.md, run with claude -p and no tools). Writes <run-dir>/score.json and
# keeps the judge's raw reply in <run-dir>/judge.json.
#
# Usage: tests/score.sh <run-dir>
# Exit 0 when the run passes both, 1 when it fails either, 2 on errors.
set -euo pipefail

usage() {
  echo "usage: tests/score.sh <run-dir>" >&2
  exit 2
}
[[ $# -eq 1 && -f "$1/meta.json" ]] || usage

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
run_dir="$(cd "$1" && pwd)"
py="$REPO_ROOT/.venv/bin/python"
[[ -x "$py" ]] || py="python3"

scenario="$("$py" -c 'import json, sys; print(json.load(open(sys.argv[1]))["scenario"])' \
  "$run_dir/meta.json")"
expected="$REPO_ROOT/tests/scenarios/$scenario/expected.md"
[[ "$scenario" =~ ^[a-z0-9-]+$ && -f "$expected" ]] || {
  echo "unknown scenario in meta.json: $scenario" >&2
  exit 2
}

judge_out="$run_dir/judge.json"
rm -f "$judge_out"
if [[ -f "$run_dir/report.md" ]]; then
  # The judge runs in an empty folder: no project instructions, settings or tools.
  work="$(mktemp -d "${TMPDIR:-/tmp}/k8s-crew-judge.XXXXXX")"
  trap 'rm -rf "$work"' EXIT
  {
    cat "$REPO_ROOT/tests/judge.md"
    printf '\n<expected.md>\n'
    cat "$expected"
    printf '\n</expected.md>\n\n<report.md>\n'
    cat "$run_dir/report.md"
    printf '\n</report.md>\n'
  } > "$work/prompt.md"
  (cd "$work" && claude -p --output-format json --tools "" \
    --setting-sources project,local --strict-mcp-config --no-session-persistence \
    < "$work/prompt.md" > "$judge_out" 2> "$run_dir/judge-stderr.txt") \
    || echo "warning: judge run failed, see $run_dir/judge-stderr.txt" >&2
else
  echo "warning: no report.md, the judge is skipped" >&2
fi

cd "$REPO_ROOT"
"$py" -m tools.score score "$run_dir" --judge-output "$judge_out"
