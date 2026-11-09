#!/usr/bin/env bash
# Pin CoreDNS to the worker node, then deploy my-api (nginx) and my-app (a busybox
# client that calls my-api by its Service name in a loop) on the control-plane node, so
# only DNS depends on the worker. Waits until everything is placed and Ready.
set -euo pipefail
# shellcheck source=../../lib.sh disable=SC1091
source "$(dirname "$0")/../../lib.sh"
# shellcheck source=../../versions.env disable=SC1091
source "$(dirname "$0")/../../versions.env"
require_test_cluster

WORKER="${CLUSTER_NAME}-worker"
CONTROL_PLANE="${CLUSTER_NAME}-control-plane"

if ! kubectl get node "$WORKER" >/dev/null 2>&1; then
  echo "this scenario needs a worker node: tests/cluster.sh up --workers 1" >&2
  exit 1
fi

# cleanup.sh removes exactly the key added here, so refuse if it is already set
# (a previous run was not cleaned up, or someone pinned CoreDNS on purpose).
selector="$(kubectl -n kube-system get deployment coredns \
  -o jsonpath='{.spec.template.spec.nodeSelector}')"
if [[ "$selector" == *kubernetes.io/hostname* ]]; then
  echo "CoreDNS already has a kubernetes.io/hostname nodeSelector: run cleanup.sh first" >&2
  exit 1
fi
kubectl -n kube-system patch deployment coredns --type=strategic -p \
  "{\"spec\":{\"template\":{\"spec\":{\"nodeSelector\":{\"kubernetes.io/hostname\":\"$WORKER\"}}}}}"
kubectl -n kube-system rollout status deployment/coredns --timeout=180s
# rollout status returns while the old pods are still terminating; wait until they are gone.
for _ in $(seq 1 36); do
  elsewhere="$(kubectl -n kube-system get pods -l k8s-app=kube-dns \
    --field-selector "spec.nodeName!=$WORKER" -o name)"
  if [[ -z "$elsewhere" ]]; then
    break
  fi
  sleep 5
done
if [[ -n "$elsewhere" ]]; then
  echo "CoreDNS pods still off $WORKER: $elsewhere" >&2
  exit 1
fi

kubectl apply -f - <<YAML
apiVersion: v1
kind: Namespace
metadata:
  name: my-namespace
---
apiVersion: v1
kind: Service
metadata:
  name: my-api
  namespace: my-namespace
spec:
  selector:
    app: my-api
  ports:
    - port: 80
      targetPort: 80
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-api
  namespace: my-namespace
spec:
  replicas: 1
  selector:
    matchLabels:
      app: my-api
  template:
    metadata:
      labels:
        app: my-api
    spec:
      nodeSelector:
        kubernetes.io/hostname: ${CONTROL_PLANE}
      tolerations:
        - key: node-role.kubernetes.io/control-plane
          operator: Exists
          effect: NoSchedule
      containers:
        - name: api
          image: ${NGINX_IMAGE}  # nginx:1.29-alpine, pinned in tests/versions.env
          ports:
            - containerPort: 80
          readinessProbe:
            httpGet:
              path: /
              port: 80
            periodSeconds: 5
          resources:
            requests:
              cpu: 10m
              memory: 16Mi
            limits:
              memory: 64Mi
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
  namespace: my-namespace
spec:
  replicas: 1
  selector:
    matchLabels:
      app: my-app
  template:
    metadata:
      labels:
        app: my-app
    spec:
      nodeSelector:
        kubernetes.io/hostname: ${CONTROL_PLANE}
      tolerations:
        - key: node-role.kubernetes.io/control-plane
          operator: Exists
          effect: NoSchedule
      containers:
        - name: app
          image: ${BUSYBOX_IMAGE}
          command:
            - sh
            - -c
            - |
              while true; do
                if wget -q -T 3 -O /dev/null http://my-api.my-namespace.svc/ 2>/tmp/err; then
                  echo "\$(date -u +%FT%TZ) GET http://my-api.my-namespace.svc/ ok"
                else
                  echo "\$(date -u +%FT%TZ) GET http://my-api.my-namespace.svc/ failed: \$(cat /tmp/err)"
                fi
                sleep 5
              done
          readinessProbe:
            exec:
              # busybox nslookup ignores the search list, so ask for the full name.
              command: ["nslookup", "my-api.my-namespace.svc.cluster.local"]
            periodSeconds: 5
            timeoutSeconds: 4
            failureThreshold: 2
          resources:
            requests:
              cpu: 10m
              memory: 16Mi
            limits:
              memory: 32Mi
YAML
kubectl -n my-namespace rollout status deployment/my-api --timeout=180s
kubectl -n my-namespace rollout status deployment/my-app --timeout=180s
