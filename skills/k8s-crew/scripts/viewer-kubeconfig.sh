#!/usr/bin/env bash
# Create the view-only crew identity and write a kubeconfig that holds only its token.
# Uses the caller's CURRENT kubectl context: this is the one step that needs admin
# access (to create the ServiceAccount and its bindings). Never prints the token.
set -euo pipefail

out="${HOME}/.kube/k8s-crew-viewer"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --out) out="${2:?--out needs a path}"; shift 2 ;;
    -h|--help) echo "usage: viewer-kubeconfig.sh [--out PATH]"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
kubectl apply -f "$here/../rbac/crew-viewer.yaml" >&2

token="$(kubectl create token crew-viewer -n k8s-crew --duration 8h)"
server="$(kubectl config view --raw --minify -o jsonpath='{.clusters[0].cluster.server}')"
ca_data="$(kubectl config view --raw --minify -o jsonpath='{.clusters[0].cluster.certificate-authority-data}')"
if [[ -z "$ca_data" ]]; then
  ca_file="$(kubectl config view --raw --minify -o jsonpath='{.clusters[0].cluster.certificate-authority}')"
  [[ -n "$ca_file" && -r "$ca_file" ]] && ca_data="$(base64 < "$ca_file" | tr -d '\n')"
fi

mkdir -p "$(dirname "$out")"
umask 077
draft="$(mktemp "$out.XXXXXX")"
trap 'rm -f "$draft"' EXIT
{
  echo "apiVersion: v1"
  echo "kind: Config"
  echo "clusters:"
  echo "- name: k8s-crew"
  echo "  cluster:"
  echo "    server: $server"
  [[ -n "$ca_data" ]] && echo "    certificate-authority-data: $ca_data"
  echo "users:"
  echo "- name: crew-viewer"
  echo "  user:"
  echo "    token: $token"
  echo "contexts:"
  echo "- name: k8s-crew"
  echo "  context:"
  echo "    cluster: k8s-crew"
  echo "    user: crew-viewer"
  echo "current-context: k8s-crew"
} > "$draft"
chmod 600 "$draft"
mv "$draft" "$out"
trap - EXIT

echo "$out"
echo "now: export KUBECONFIG=$out" >&2
