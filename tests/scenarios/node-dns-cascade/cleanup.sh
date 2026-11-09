#!/usr/bin/env bash
# Start the worker's kubelet again and wait for the node, remove the nodeSelector key
# setup.sh added to CoreDNS (its spec is then exactly what it was), wait for CoreDNS and
# remove the pinned ReplicaSet it leaves behind, and remove the namespace.
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
# The pinned ReplicaSet is left with 0 replicas; remove it, so CoreDNS has the one
# ReplicaSet it had before setup.sh (setup.sh removed the unpinned one).
pinned="$(kubectl -n kube-system get replicasets -l k8s-app=kube-dns \
  -o jsonpath='{.items[?(@.spec.replicas==0)].metadata.name}')"
if [[ -n "$pinned" ]]; then
  # shellcheck disable=SC2086 # one ReplicaSet name per word
  kubectl -n kube-system delete replicaset $pinned
fi

kubectl delete namespace my-namespace --ignore-not-found --wait=true
