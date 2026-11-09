#!/usr/bin/env bash
# Print Copilot CLI --deny-tool flags that block kubectl write commands and Secret reads,
# matching config/claude-settings.example.json. A safety net, not a guarantee: command
# matching is easy to get around, and the view-only kubeconfig is the real lock.
#
# Usage, from the k8s-crew skill folder: eval "copilot $(config/copilot-deny-tools.sh)"
set -euo pipefail

verbs=(
  apply create delete edit patch replace scale set
  "rollout restart" "rollout undo"
  cordon uncordon drain taint label annotate
  exec cp port-forward debug
  "get secret" "get secrets"
)

flags=()
for verb in "${verbs[@]}"; do
  flags+=("--deny-tool 'shell(kubectl ${verb}:*)'")
done
echo "${flags[*]}"
