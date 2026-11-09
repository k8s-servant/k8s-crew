#!/usr/bin/env bash
# Refuse to start unless the current kubectl identity is view-only. Fails closed:
# a "yes" or any answer other than "no" (error, no cluster) blocks the crew.
set -euo pipefail

subagents=false
platform=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --subagents) subagents=true; shift ;;
    --platform) platform="${2:?--platform needs claude or copilot}"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

blocked=0
check() {
  local label="$1"; shift
  local answer
  answer="$(kubectl auth can-i "$@" 2>/dev/null || true)"
  if [[ "$answer" != "no" ]]; then
    echo "NOT view-only: can-i $label answered '${answer:-no answer}'"
    blocked=1
  fi
}
check "create deployments -A" create deployments -A
check "delete pods -A" delete pods -A
check "patch nodes" patch nodes
check "get secrets -A" get secrets -A

if [[ "$blocked" -ne 0 ]]; then
  echo "run scripts/viewer-kubeconfig.sh and export KUBECONFIG=<path>"
  exit 3
fi

# Folders from $PWD up to the git root (only $PWD outside a git repository), nearest first.
project_dirs() {
  local dir top
  dir="$(pwd -P)"
  top="$(git rev-parse --show-toplevel 2>/dev/null || true)"
  [[ -n "$top" ]] && top="$(cd "$top" && pwd -P)"
  while :; do
    echo "$dir"
    [[ -z "$top" || "$dir" == "$top" || "$dir" == / ]] && break
    dir="$(dirname "$dir")"
  done
}

# Every place the platform loads the investigator from, in the order it looks.
candidates() {
  local dir
  case "$platform" in
    claude)
      while IFS= read -r dir; do
        echo "$dir/.claude/agents/k8s-crew-investigator.md"
      done < <(project_dirs)
      echo "$HOME/.claude/agents/k8s-crew-investigator.md"
      ;;
    copilot)
      echo "$HOME/.copilot/agents/k8s-crew-investigator.agent.md"
      echo "$HOME/.copilot/agents/k8s-crew-investigator.md"
      while IFS= read -r dir; do
        for sub in .github/agents .claude/agents; do
          echo "$dir/$sub/k8s-crew-investigator.agent.md"
          echo "$dir/$sub/k8s-crew-investigator.md"
        done
      done < <(project_dirs)
      ;;
  esac
}

if [[ "$subagents" == true ]]; then
  case "$platform" in
    claude|copilot) ;;
    *) echo "--subagents needs --platform claude|copilot" >&2; exit 2 ;;
  esac
  found=""
  while IFS= read -r agent; do
    if [[ -e "$agent" ]]; then
      found="$agent"
      break
    fi
  done < <(candidates)
  if [[ -z "$found" ]]; then
    echo "investigator agent missing: not found in any $platform agent folder:"
    candidates | sed 's/^/  /'
    echo "run scripts/install-agents.sh"
    exit 4
  fi
fi

echo "viewer ok"
