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

if [[ "$subagents" == true ]]; then
  case "$platform" in
    claude) agent="$HOME/.claude/agents/k8s-crew-investigator.md" ;;
    copilot) agent="$HOME/.copilot/agents/k8s-crew-investigator.agent.md" ;;
    *) echo "--subagents needs --platform claude|copilot" >&2; exit 2 ;;
  esac
  if [[ ! -e "$agent" ]]; then
    echo "investigator agent missing: $agent"
    echo "run scripts/install-agents.sh"
    exit 4
  fi
fi

echo "viewer ok"
