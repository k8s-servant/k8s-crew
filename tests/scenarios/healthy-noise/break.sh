#!/usr/bin/env bash
# Nothing stays broken here. my-app (nginx) only starts serving its readiness path
# /ready.html about 60 seconds after it starts (a slow warm-up), so its readiness probe
# fails for a minute and leaves Warning "Unhealthy" events behind, then passes. Waits
# until the events exist and my-app is Ready again, so the cluster is healthy at the end.
set -euo pipefail
# shellcheck source=../../lib.sh disable=SC1091
source "$(dirname "$0")/../../lib.sh"
# shellcheck source=../../versions.env disable=SC1091
source "$(dirname "$0")/../../versions.env"
require_test_cluster

kubectl apply -f - <<YAML
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
      containers:
        - name: app
          image: ${NGINX_IMAGE}  # nginx:1.29-alpine, pinned in tests/versions.env
          command:
            - sh
            - -c
            - (sleep 60; echo ok > /usr/share/nginx/html/ready.html) & exec nginx -g 'daemon off;'
          ports:
            - containerPort: 80
          readinessProbe:
            httpGet:
              path: /ready.html
              port: 80
            periodSeconds: 5
            failureThreshold: 3
          resources:
            requests:
              cpu: 10m
              memory: 16Mi
            limits:
              memory: 64Mi
YAML
kubectl -n my-namespace rollout status deployment/my-app --timeout=180s
# The kubelet sends events in batches, so give the last ones a moment to arrive.
for _ in $(seq 1 12); do
  if kubectl -n my-namespace get events --field-selector reason=Unhealthy -o name | grep -q .; then
    exit 0
  fi
  sleep 5
done
echo "my-app became Ready without leaving Unhealthy events" >&2
exit 1
