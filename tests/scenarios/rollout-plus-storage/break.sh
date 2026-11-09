#!/usr/bin/env bash
# Two faults that have nothing to do with each other, in the same namespace:
# 1. my-app is rolled to an image tag that does not exist (a typo in the tag).
# 2. A new workload, my-worker, comes with a PVC my-data that asks for a StorageClass
#    this cluster does not have (the manifest was copied from another cluster).
# Then wait until both faults have been reported.
set -euo pipefail
# shellcheck source=../../lib.sh disable=SC1091
source "$(dirname "$0")/../../lib.sh"
# shellcheck source=../../versions.env disable=SC1091
source "$(dirname "$0")/../../versions.env"
require_test_cluster

kubectl -n my-namespace set image deployment/my-app app=nginx:1.299-alpine

kubectl apply -f - <<YAML
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: my-data
  namespace: my-namespace
spec:
  storageClassName: fast-ssd
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 1Gi
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-worker
  namespace: my-namespace
spec:
  replicas: 1
  selector:
    matchLabels:
      app: my-worker
  template:
    metadata:
      labels:
        app: my-worker
    spec:
      containers:
        - name: worker
          image: ${BUSYBOX_IMAGE}
          command: ["sh", "-c", "date >> /data/started; sleep 3600"]
          volumeMounts:
            - name: data
              mountPath: /data
          resources:
            requests:
              cpu: 10m
              memory: 16Mi
            limits:
              memory: 32Mi
      volumes:
        - name: data
          persistentVolumeClaim:
            claimName: my-data
YAML

pull_failed=false
provisioning_failed=false
for _ in $(seq 1 60); do
  reasons="$(kubectl -n my-namespace get pods -l app=my-app \
    -o jsonpath='{.items[*].status.containerStatuses[*].state.waiting.reason}')"
  if [[ "$reasons" == *ImagePullBackOff* || "$reasons" == *ErrImagePull* ]]; then
    pull_failed=true
  fi
  if kubectl -n my-namespace get events --field-selector reason=ProvisioningFailed -o name \
    | grep -q .; then
    provisioning_failed=true
  fi
  if [[ "$pull_failed" == true && "$provisioning_failed" == true ]]; then
    exit 0
  fi
  sleep 3
done
echo "faults not reported: image pull failed=$pull_failed, provisioning failed=$provisioning_failed" >&2
exit 1
