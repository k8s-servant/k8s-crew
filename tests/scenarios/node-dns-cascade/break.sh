#!/usr/bin/env bash
# Stop the worker's kubelet (the node every CoreDNS replica runs on), wait until the
# node's Ready condition is no longer True, then until the knock-on effect shows: the
# kube-dns Service has no ready endpoints and my-app's DNS readiness probe fails.
set -euo pipefail
# shellcheck source=../../lib.sh disable=SC1091
source "$(dirname "$0")/../../lib.sh"
require_test_cluster

WORKER="${CLUSTER_NAME}-worker"

# kind nodes are containers; stopping the kubelet is how a node dies in real life.
docker exec "$WORKER" systemctl stop kubelet

node_down=false
for _ in $(seq 1 40); do
  ready="$(kubectl get node "$WORKER" \
    -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}')"
  if [[ "$ready" != "True" ]]; then
    node_down=true
    break
  fi
  sleep 5
done
if [[ "$node_down" != true ]]; then
  echo "$WORKER is still Ready" >&2
  exit 1
fi

for _ in $(seq 1 40); do
  dns_ready="$(kubectl -n kube-system get endpointslices -l kubernetes.io/service-name=kube-dns \
    -o jsonpath='{.items[*].endpoints[?(@.conditions.ready==true)].addresses[*]}')"
  app_ready="$(kubectl -n my-namespace get pods -l app=my-app \
    -o jsonpath='{.items[*].status.conditions[?(@.type=="Ready")].status}')"
  if [[ -z "$dns_ready" && "$app_ready" != *True* ]]; then
    exit 0
  fi
  sleep 5
done
echo "knock-on effect not seen: ready DNS endpoints='$dns_ready', my-app Ready='$app_ready'" >&2
exit 1
