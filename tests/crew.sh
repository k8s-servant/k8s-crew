#!/usr/bin/env bash
# Run the crew (or a single-agent baseline) non-interactively against a broken scenario.
#
# Usage: tests/crew.sh <scenario> --agent claude|copilot --mode subagents|single [--runs N]
#
# Each run: setup.sh + break.sh on the kind test cluster, a view-only kubeconfig, a fresh
# temp project (skills linked in, nothing installed into ~/.claude or ~/.copilot), the
# agent run with the scenario prompt, then cleanup.sh (also on failure or Ctrl-C).
#   subagents: k8s-crew + k8s-skills + the investigator agent; prompt "/k8s-crew <prompt>".
#   single:    k8s-skills only (the baseline); prompt is the scenario prompt.
# Output: runs/<scenario>/<agent>-<mode>-<n>/{report.md,transcript.jsonl,meta.json} plus
# the raw agent output (stream.jsonl, stderr.txt; Copilot also events.jsonl).
# Score a run with tests/score.sh. Env: CREW_MAX_BUDGET_USD (Claude cost cap, default 10).
set -euo pipefail
# shellcheck source-path=SCRIPTDIR

# shellcheck source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
# shellcheck source=versions.env disable=SC1091
source "$(dirname "${BASH_SOURCE[0]}")/versions.env"

usage() {
  echo "usage: tests/crew.sh <scenario> --agent claude|copilot --mode subagents|single [--runs N]" >&2
  exit 64
}

scenario="${1:-}"
[[ -n "$scenario" && "$scenario" != -* ]] || usage
shift
agent="" mode="" runs=1
while [[ $# -gt 0 ]]; do
  case "$1" in
    --agent) agent="${2:-}"; shift 2 || usage ;;
    --mode) mode="${2:-}"; shift 2 || usage ;;
    --runs) runs="${2:-}"; shift 2 || usage ;;
    *) usage ;;
  esac
done
[[ "$agent" == claude || "$agent" == copilot ]] || usage
[[ "$mode" == subagents || "$mode" == single ]] || usage
[[ "$runs" =~ ^[1-9][0-9]*$ ]] || usage

scenario_dir="$REPO_ROOT/tests/scenarios/$scenario"
[[ "$scenario" =~ ^[a-z0-9-]+$ && -f "$scenario_dir/expected.md" ]] || {
  echo "unknown scenario: $scenario" >&2
  exit 64
}
require_test_cluster

py="$REPO_ROOT/.venv/bin/python"
[[ -x "$py" ]] || py="python3"
skill_dir="$REPO_ROOT/skills/k8s-crew"
k8s_skills="$(cd "$REPO_ROOT" && "$py" -c 'from tools.k8sskills import fetch; print(fetch())')/skills"

# The text under "## Prompt" in expected.md, without surrounding blank lines.
prompt="$(awk '/^## /{p = ($0 == "## Prompt"); next} p' "$scenario_dir/expected.md" | sed '/./,$!d')"
[[ -n "$prompt" ]] || { echo "no ## Prompt in $scenario_dir/expected.md" >&2; exit 65; }
if [[ "$mode" == subagents ]]; then
  prompt="/k8s-crew $prompt"
fi

# Read-only kubectl verbs the agent may run without asking. Anything else is denied:
# claude runs in dontAsk mode and copilot -p denies every tool no rule allows.
read_verbs=(
  get describe logs events top explain api-resources api-versions version cluster-info
  "auth can-i" "auth whoami" "rollout status" "rollout history"
)
# Pipe filters. None of them may write a file: yq (-i) is left out; Claude also denies
# sort -o and uniq's output-file argument. Copilot cannot match flags inside a command,
# so it gets only the filters that have no file-writing form.
filters=(grep egrep head tail sort uniq wc cut column jq)
copilot_filters=(grep egrep head tail wc cut column jq)
# kubectl flags that pick another kubeconfig, cluster, server or identity. The run must
# only ever use the viewer kubeconfig on the test cluster.
target_flags=(
  --kubeconfig --context --cluster --server -s --token --user --username --password
  --as --as-group --as-uid --client-certificate --client-key --certificate-authority
)
# Every kubectl subcommand that is not in read_verbs. Copilot allow rules cannot name a
# kubectl subcommand (only deny rules can), so Copilot allows kubectl and denies these.
copilot_denied_verbs=(
  create expose run set edit delete scale autoscale certificate cordon uncordon drain
  taint attach exec port-forward proxy cp debug diff apply patch replace wait kustomize
  label annotate completion plugin alpha options
  "rollout restart" "rollout undo" "rollout pause" "rollout resume" "auth reconcile"
  "config view" "config set" "config set-cluster" "config set-context"
  "config set-credentials" "config unset" "config use-context" "config use"
  "config delete-cluster" "config delete-context" "config delete-user"
  "config rename-context" "get secret" "get secrets" "describe secret" "describe secrets"
)
# Local files the agent must not read: other kubeconfigs and credentials, the agent
# configs, the test cluster's admin kubeconfig, and the scenario answers.
private_paths=(
  "$HOME/.kube" "$HOME/.claude" "$HOME/.copilot" "$HOME/.config/gh"
  "$REPO_ROOT/.kube" "$REPO_ROOT/tests" "$REPO_ROOT/runs"
)
preflights=(
  "$skill_dir/scripts/preflight.sh"
  ".claude/skills/k8s-crew/scripts/preflight.sh"
)

claude_flags() {
  local project="$1" verb tool flag dir tools="Bash,Read,Grep,Glob,Skill"
  local allowed=(Read Grep Glob Skill) denied=()
  [[ "$mode" == subagents ]] && { tools="$tools,Agent"; allowed+=(Agent); }
  for verb in "${read_verbs[@]}"; do allowed+=("Bash(kubectl $verb)" "Bash(kubectl $verb *)"); done
  for tool in "${filters[@]}"; do allowed+=("Bash($tool *)"); done
  if [[ "$mode" == subagents ]]; then
    for tool in "${preflights[@]}" "$project/${preflights[1]}"; do
      allowed+=("Bash($tool)" "Bash($tool *)")
    done
  fi
  # Deny rules win over allow rules (checked: claude -p, dontAsk).
  for flag in "${target_flags[@]}"; do
    if [[ "$flag" == --* ]]; then
      denied+=("Bash(kubectl *$flag*)")
    else
      denied+=("Bash(kubectl * $flag *)" "Bash(kubectl * $flag=*)" "Bash(kubectl * $flag)")
    fi
  done
  denied+=("Bash(sort *-o*)" "Bash(sort *--output*)" "Bash(uniq * *)")
  # "//" starts an absolute path in Claude Code permission rules.
  for dir in "${private_paths[@]}"; do denied+=("Read(/$dir/**)"); done
  # shellcheck disable=SC2054 # commas belong to the flag values
  flags=(
    --output-format stream-json --verbose
    --setting-sources project,local --strict-mcp-config --no-session-persistence
    --settings "$skill_dir/config/claude-settings.example.json"
    --permission-mode dontAsk --tools "$tools" --allowedTools "${allowed[@]}"
    --disallowedTools "${denied[@]}"
    --add-dir "$k8s_skills" --max-budget-usd "${CREW_MAX_BUDGET_USD:-10}"
  )
  [[ "$mode" == subagents ]] && flags+=(--add-dir "$skill_dir")
  return 0
}

copilot_flags() {
  local project="$1" session="$2" verb tool flag dir
  # The deny script prints the flags shell-quoted, ready for eval. --auto-allow needs
  # the kubectl guard active, as it is for the agent.
  eval "flags=($(K8S_CREW_GUARD="$work/bin" PATH="$work/bin:$PATH" \
    "$skill_dir/config/copilot-deny-tools.sh" --auto-allow))"
  flags+=(
    --trust-folder --session-id "$session" --output-format json --no-ask-user
    --no-auto-update --disable-builtin-mcps --no-custom-instructions
    --add-dir "$k8s_skills" --allow-tool read --allow-tool "shell(kubectl:*)"
  )
  for verb in "${copilot_denied_verbs[@]}"; do flags+=(--deny-tool "shell(kubectl $verb:*)"); done
  # Copilot matches only a command's leading words, so a target flag is denied here only
  # when it comes first; the kubectl guard (scripts/kubectl-guard) refuses it anywhere.
  for flag in "${target_flags[@]}"; do flags+=(--deny-tool "shell(kubectl $flag:*)"); done
  for dir in "${private_paths[@]}"; do flags+=(--deny-tool "read($dir/**)"); done
  for tool in "${copilot_filters[@]}"; do flags+=(--allow-tool "shell($tool:*)"); done
  if [[ "$mode" == single ]]; then
    flags+=(--excluded-tools task)
  else
    flags+=(--add-dir "$skill_dir")
    for tool in "${preflights[@]}" "$project/${preflights[1]}"; do
      flags+=(--allow-tool "shell($tool:*)")
    done
  fi
}

# A fresh git project with the skills (and, for the crew, the investigator) linked in.
make_project() {
  local project="$1" skill
  mkdir -p "$project/.claude/skills" "$project/.github"
  git -C "$project" init --quiet
  for skill in "$k8s_skills"/*/; do
    ln -s "${skill%/}" "$project/.claude/skills/$(basename "$skill")"
  done
  ln -s ../.claude/skills "$project/.github/skills"
  if [[ "$mode" == subagents ]]; then
    ln -s "$skill_dir" "$project/.claude/skills/k8s-crew"
    mkdir -p "$project/.claude/agents" "$project/.github/agents"
    ln -s "$skill_dir/agents/k8s-crew-investigator.md" "$project/.claude/agents/"
    ln -s "$skill_dir/agents/k8s-crew-investigator.md" \
      "$project/.github/agents/k8s-crew-investigator.agent.md"
  fi
}

# Cleanup state is global so the EXIT trap sees it.
work="" needs_cleanup=""
finish_run() {
  if [[ -n "$needs_cleanup" ]]; then
    needs_cleanup=""
    bash "$scenario_dir/cleanup.sh" || echo "warning: $scenario cleanup.sh failed" >&2
  fi
  [[ -n "$work" ]] && rm -rf "$work"
  work=""
}
trap finish_run EXIT
trap 'exit 130' INT TERM

next_run_dir() {
  local n=1
  while [[ -e "$REPO_ROOT/runs/$scenario/$agent-$mode-$n" ]]; do n=$((n + 1)); done
  echo "$REPO_ROOT/runs/$scenario/$agent-$mode-$n"
}

failed=0
for ((i = 1; i <= runs; i++)); do
  run_dir="$(next_run_dir)"
  mkdir -p "$run_dir"
  echo "== $scenario $agent $mode -> ${run_dir#"$REPO_ROOT/"}" >&2
  # Physical path: the agents resolve /var to /private/var on macOS.
  work="$(cd "$(mktemp -d "${TMPDIR:-/tmp}/k8s-crew-run.XXXXXX")" && pwd -P)"
  needs_cleanup=1
  bash "$scenario_dir/setup.sh"
  bash "$scenario_dir/break.sh"
  "$skill_dir/scripts/viewer-kubeconfig.sh" --out "$work/viewer.kubeconfig" > /dev/null
  project="$work/project"
  make_project "$project"
  # The product's kubectl guard, first on the agent's PATH, as scripts/crew-start.sh sets
  # it up: the runtime lock behind the permission rules (Copilot rules cannot match flags).
  mkdir "$work/bin"
  "$skill_dir/scripts/kubectl-guard" install "$work/bin" "$work/viewer.kubeconfig"

  started=$SECONDS
  status=0
  if [[ "$agent" == claude ]]; then
    claude_flags "$project"
    (cd "$project" && KUBECONFIG="$work/viewer.kubeconfig" PATH="$work/bin:$PATH" \
      K8S_CREW_GUARD="$work/bin" claude -p "$prompt" "${flags[@]}" < /dev/null > "$run_dir/stream.jsonl" \
      2> "$run_dir/stderr.txt") || status=$?
    source_args=(--claude "$run_dir/stream.jsonl")
  else
    session="$(uuidgen | tr '[:upper:]' '[:lower:]')"
    copilot_flags "$project" "$session"
    (cd "$project" && KUBECONFIG="$work/viewer.kubeconfig" PATH="$work/bin:$PATH" \
      K8S_CREW_GUARD="$work/bin" copilot -p "$prompt" "${flags[@]}" < /dev/null > "$run_dir/stream.jsonl" \
      2> "$run_dir/stderr.txt") || status=$?
    # The session's own event log is the verified format; read it, not stdout.
    events="$HOME/.copilot/session-state/$session/events.jsonl"
    if [[ -f "$events" ]]; then
      cp "$events" "$run_dir/events.jsonl"
      source_args=(--copilot "$run_dir/events.jsonl")
    else
      echo "warning: no Copilot session log at $events, reading stdout instead" >&2
      source_args=(--copilot "$run_dir/stream.jsonl")
    fi
  fi
  duration=$((SECONDS - started))
  [[ "$status" -eq 0 ]] || { echo "warning: $agent exited $status" >&2; failed=1; }

  # A transcript that cannot be read (or a baseline that used the crew) is left out, so
  # scoring fails "transcript unavailable" with the reason from transcript-error.txt.
  baseline=()
  [[ "$mode" == single ]] && baseline=(--baseline)
  if ! (cd "$REPO_ROOT" && "$py" -m tools.score transcript "${source_args[@]}" \
    "${baseline[@]}" "$run_dir/transcript.jsonl" 2> "$run_dir/transcript-error.txt"); then
    rm -f "$run_dir/transcript.jsonl"
    cat "$run_dir/transcript-error.txt" >&2
  else
    rm -f "$run_dir/transcript-error.txt"
  fi
  (cd "$REPO_ROOT" && "$py" -m tools.score final-report "${source_args[@]}" \
    "$run_dir/report.md") || rm -f "$run_dir/report.md"

  # The skill folder under every path an agent may use for it, and the run's viewer
  # kubeconfig: the hard check accepts the crew's own scripts only from these.
  # Claude reports a cumulative cost in every result event; the last one is the run's.
  cost=""
  if [[ "$agent" == claude ]]; then
    cost="$(cd "$REPO_ROOT" && "$py" -m tools.score cost --claude "$run_dir/stream.jsonl" \
      2> /dev/null || true)"
  fi
  "$py" - "$run_dir/meta.json" "$agent" "$mode" "$scenario" "$K8S_SKILLS_REF" \
    "$duration" "$status" "$cost" "$work/viewer.kubeconfig" "$skill_dir" \
    "$(cd "$skill_dir" && pwd -P)" "$project/.claude/skills/k8s-crew" <<'PY'
import json
import sys

out, agent, mode, scenario, ref, duration, status, cost, viewer, *skill_dirs = sys.argv[1:]
meta = {
    "agent": agent,
    "mode": mode,
    "scenario": scenario,
    "k8s_skills_ref": ref,
    "duration_seconds": int(duration),
    "exit_code": int(status),
    "cost_usd": float(cost) if cost else None,
    "skill_dirs": list(dict.fromkeys(skill_dirs)),
    "viewer": viewer,
}
with open(out, "w", encoding="utf-8") as fh:
    json.dump(meta, fh, indent=2)
    fh.write("\n")
PY
  finish_run
  echo "${run_dir#"$REPO_ROOT/"}"
done
exit "$failed"
