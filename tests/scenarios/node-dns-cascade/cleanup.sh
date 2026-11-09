#!/usr/bin/env bash
# Start the worker's kubelet again and wait for the node, remove the nodeSelector key
# setup.sh added to CoreDNS (its spec is then exactly what it was) and wait for CoreDNS,
# and remove the namespace.
set -euo pipefail
# shellcheck source=../../lib.sh disable=SC1091
source "$(dirname "$0")/../../lib.sh"
require_test_cluster

WORKER="${CLUSTER_NAME}-worker"

docker exec "$WORKER" systemctl start kubelet
kubectl wait --for=condition=Ready "node/$WORKER" --timeout=180s

selector="$(kubectl -n kube-system get deployment coredns \
  -o jsonpath='{.spec.template.spec.nodeSelector}')"
if [[ "$selector" == *kubernetes.io/hostname* ]]; then
  kubectl -n kube-system patch deployment coredns --type=json -p \
    '[{"op":"remove","path":"/spec/template/spec/nodeSelector/kubernetes.io~1hostname"}]'
fi
kubectl -n kube-system rollout status deployment/coredns --timeout=180s

kubectl delete namespace my-namespace --ignore-not-found --wait=true
