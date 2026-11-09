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

# The current context's cluster entry. --flatten inlines a CA given as a file path (a
# relative path is resolved against the kubeconfig's own folder, as kubectl does), so
# the viewer kubeconfig needs no file next to it.
cluster() {
  kubectl config view --raw --minify --flatten -o "jsonpath={.clusters[0].cluster.$1}"
}
server="$(cluster server)"
ca_data="$(cluster certificate-authority-data)"
tls_server_name="$(cluster tls-server-name)"
proxy_url="$(cluster proxy-url)"
insecure="$(cluster insecure-skip-tls-verify)"
if [[ -z "$server" ]]; then
  echo "viewer-kubeconfig.sh: the current context has no cluster server" >&2
  exit 3
fi
if [[ "$server" == https://* && -z "$ca_data" ]]; then
  if [[ "$insecure" != true ]]; then
    echo "viewer-kubeconfig.sh: the current context has no CA for $server (no" \
      "certificate-authority-data or certificate-authority), so the viewer kubeconfig" \
      "could not verify the server. Fix the cluster entry of your kubeconfig first." >&2
    exit 3
  fi
  echo "WARNING: the current context sets insecure-skip-tls-verify and has no CA; the" \
    "viewer kubeconfig keeps it and will not verify the server's certificate." >&2
fi

kubectl apply -f "$here/../rbac/crew-viewer.yaml" >&2
token="$(kubectl create token crew-viewer -n k8s-crew --duration 8h)"
if [[ -z "$token" ]]; then
  echo "viewer-kubeconfig.sh: kubectl create token returned no token" >&2
  exit 3
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
  [[ -z "$ca_data" && "$insecure" == true ]] && echo "    insecure-skip-tls-verify: true"
  [[ -n "$tls_server_name" ]] && echo "    tls-server-name: $tls_server_name"
  [[ -n "$proxy_url" ]] && echo "    proxy-url: $proxy_url"
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
