#!/usr/bin/env bash
# Copilot CLI permission rules for a crew session: deny every kubectl command that is not
# read-only, and Secret reads. Matches the intent of claude-settings.example.json.
#
# Copilot CLI (checked with 1.0.107) matches a rule against a command's leading words
# only. A deny rule can name a subcommand (shell(kubectl delete:*)), but an allow rule
# cannot (shell(kubectl get:*) allows nothing), and a wildcard in the middle
# (shell(kubectl *--context*)) matches nothing. So a flag before the subcommand
# (kubectl -n my-namespace delete ..., kubectl --context my-context apply ...) is not
# matched by any deny rule here.
#
# By default the rules are deny-only: Copilot asks the user before every kubectl call
# that is not denied, so the user sees such a command before it runs.
#
# --auto-allow also allows shell(kubectl:*), so kubectl calls run without asking. Then a
# flag before the subcommand bypasses the deny list, and ONLY the view-only identity
# protects the cluster. Use it only with the crew viewer kubeconfig.
#
# Usage, from the k8s-crew skill folder:
#   config/copilot-deny-tools.sh [--auto-allow] --run [copilot arguments]   start copilot
#   config/copilot-deny-tools.sh [--auto-allow] --lines    one argument per line, no quotes
#   config/copilot-deny-tools.sh [--auto-allow]            shell-quoted, for eval
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

args=()
if [[ "${1:-}" == --auto-allow ]]; then
  args+=(--allow-tool "shell(kubectl:*)")
  shift
fi
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
    echo "usage: $0 [--auto-allow] [--run [copilot arguments] | --lines]" >&2
    exit 2
    ;;
esac
