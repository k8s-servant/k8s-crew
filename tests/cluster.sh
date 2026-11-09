#!/usr/bin/env bash
# Create or delete the throwaway kind cluster used by the scenario tests.
#
# Usage: tests/cluster.sh up [--workers N] | down
# Only the cluster named k8s-crew-test is ever created or deleted here.
set -euo pipefail
# shellcheck source-path=SCRIPTDIR

# shellcheck source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
# shellcheck source=versions.env disable=SC1091
source "$(dirname "${BASH_SOURCE[0]}")/versions.env"

usage() {
  echo "usage: tests/cluster.sh up [--workers N] | down" >&2
  exit 64
}

up() {
  # Default is one worker: node scenarios break a worker and the control plane must keep running.
  local workers=1 i
  # Temp file, removed on every exit path (global, so the EXIT trap still sees it).
  config=""
  trap 'rm -f "$config"' EXIT
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --workers)
        workers="${2:-}"
        [[ "$workers" =~ ^[1-9][0-9]*$ ]] || usage
        shift 2
        ;;
      *) usage ;;
    esac
  done

  mkdir -p "$REPO_ROOT/.kube"
  config="$(mktemp)"
  printf 'kind: Cluster\napiVersion: kind.x-k8s.io/v1alpha4\nnodes:\n  - role: control-plane\n' > "$config"
  for ((i = 0; i < workers; i++)); do
    printf '  - role: worker\n' >> "$config"
  done

  kind create cluster --name "$CLUSTER_NAME" --image "$KIND_NODE_IMAGE" \
    --kubeconfig "$KUBECONFIG" --config "$config"
  kubectl wait --for=condition=Ready nodes --all --timeout=300s
}

down() {
  kind delete cluster --name "$CLUSTER_NAME"
  rm -f "$REPO_ROOT/.kube/$CLUSTER_NAME"
}

case "${1:-}" in
  up) shift; up "$@" ;;
  down) down ;;
  *) usage ;;
esac
