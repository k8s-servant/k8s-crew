#!/usr/bin/env bash
# Copilot CLI permission rules for a crew session: deny every kubectl command that is not
# read-only, Secret reads, the kubectl flags that pick another kubeconfig, context or
# identity, and reading kubeconfig and credential files. Matches the intent of
# claude-settings.example.json.
#
# Start crew sessions with scripts/crew-start.sh copilot, which runs this script with
# --run after it has put the kubectl guard on PATH and pointed KUBECONFIG at the viewer
# kubeconfig. Without the launcher, any other kubeconfig on the machine (your admin
# ~/.kube/config) is reachable from the session.
#
# Copilot CLI (checked with 1.0.107) matches a rule against a command's leading words
# only. A deny rule can name a subcommand (shell(kubectl delete:*)), but an allow rule
# cannot (shell(kubectl get:*) allows nothing), and a wildcard in the middle
# (shell(kubectl *--context*)) matches nothing. So a flag before the subcommand
# (kubectl -n my-namespace delete ...) is not matched by a subcommand rule, and a target
# flag is denied here only when it comes first (kubectl --context my-context ...). The
# kubectl guard refuses a target flag anywhere in the command.
#
# By default the rules are deny-only: Copilot asks the user before every kubectl call
# that is not denied, so the user sees such a command before it runs.
#
# --auto-allow also allows shell(kubectl:*), so kubectl calls run without asking. Then a
# flag before the subcommand bypasses the subcommand deny list, and only the guard and
# the view-only identity protect the cluster. So --auto-allow is refused unless the
# kubectl guard is active (the session was started with scripts/crew-start.sh).
# Residual risk: Copilot cannot deny a kubectl binary called by its full path, which
# skips the guard.
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
# kubectl flags that pick another kubeconfig, cluster, server or identity.
target_flags=(
  --kubeconfig --context --cluster --server -s --token --user --username --password
  --as --as-group --as-uid --client-certificate --client-key --certificate-authority
  --kuberc
)
# Files no crew agent needs: kubeconfigs, the agents' own settings, credentials and
# session logs, and the logins of the CLIs that can mint a kubeconfig. Skill and agent
# folders under ~/.claude and ~/.copilot stay readable: the crew reads its recipe there.
# Files are named one by one where a folder also holds skills (a "*" in the middle of
# a Copilot rule is not known to work).
private_reads=(
  "$HOME/.kube/**" "$HOME/.claude.json" "$HOME/.claude/.credentials.json"
  "$HOME/.claude/settings.json" "$HOME/.claude/settings.local.json"
  "$HOME/.claude/projects/**" "$HOME/.copilot/config.json"
  "$HOME/.copilot/mcp-config.json" "$HOME/.copilot/session-state/**"
  "$HOME/.config/gh/**" "$HOME/.azure/**" "$HOME/.aws/**" "$HOME/.config/gcloud/**"
)

args=()
if [[ "${1:-}" == --auto-allow ]]; then
  if [[ -z "${K8S_CREW_GUARD:-}" || "$(command -v kubectl)" != "$K8S_CREW_GUARD/kubectl" ]]
  then
    echo "copilot-deny-tools.sh: --auto-allow needs the kubectl guard: start the session" \
      "with scripts/crew-start.sh --auto-allow copilot" >&2
    exit 3
  fi
  args+=(--allow-tool "shell(kubectl:*)")
  shift
fi
for verb in "${denied[@]}"; do
  args+=(--deny-tool "shell(kubectl ${verb}:*)")
done
for flag in "${target_flags[@]}"; do
  args+=(--deny-tool "shell(kubectl ${flag}:*)")
done
for path in "${private_reads[@]}"; do
  args+=(--deny-tool "read(${path})")
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
