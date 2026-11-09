#!/usr/bin/env bash
# Copilot CLI permission rules for a crew session: allow kubectl, then deny every kubectl
# command that is not read-only, and Secret reads. Matches the intent of
# claude-settings.example.json.
#
# Copilot CLI (checked with 1.0.107) matches a rule against a command's leading words
# only. A deny rule can name a subcommand (shell(kubectl delete:*)), but an allow rule
# cannot (shell(kubectl get:*) allows nothing), and a wildcard in the middle
# (shell(kubectl *--context*)) matches nothing. So flags such as --context, --kubeconfig
# or -n before the subcommand cannot be denied here. This is a safety net; the view-only
# kubeconfig is what blocks writes and other clusters.
#
# Usage, from the k8s-crew skill folder:
#   config/copilot-deny-tools.sh --run [copilot arguments]   start copilot with the rules
#   config/copilot-deny-tools.sh --lines                     one argument per line, no quotes
#   config/copilot-deny-tools.sh                             shell-quoted, for eval
set -euo pipefail

# Every kubectl command that is not in the run-freely tier (help is harmless), whole or
# by subcommand, plus the Secret reads.
denied=(
  create expose run set edit delete scale autoscale certificate cordon uncordon drain
  taint attach exec port-forward proxy cp debug diff apply patch replace wait kustomize
  label annotate completion config kuberc plugin options alpha
  "rollout restart" "rollout undo" "rollout pause" "rollout resume" "auth reconcile"
  "get secret" "get secrets" "describe secret" "describe secrets"
)

args=(--allow-tool "shell(kubectl:*)")
for verb in "${denied[@]}"; do
  args+=(--deny-tool "shell(kubectl ${verb}:*)")
done

case "${1:-}" in
  --run)
    shift
    exec copilot "${args[@]}" "$@"
    ;;
  --lines)
    printf '%s\n' "${args[@]}"
    ;;
  "")
    out=()
    for arg in "${args[@]}"; do
      if [[ "$arg" == --* ]]; then out+=("$arg"); else out+=("'$arg'"); fi
    done
    echo "${out[*]}"
    ;;
  *)
    echo "usage: $0 [--run [copilot arguments] | --lines]" >&2
    exit 2
    ;;
esac
