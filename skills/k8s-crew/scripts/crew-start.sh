#!/usr/bin/env bash
# Start a k8s-crew session that can only use the crew viewer kubeconfig.
#
#   crew-start.sh [--viewer PATH] [--auto-allow] claude|copilot [agent arguments...]
#   crew-start.sh [--viewer PATH] shell
#
# Setting KUBECONFIG alone does not take your admin kubeconfig away: ~/.kube/config is
# still on disk, and `kubectl --kubeconfig ~/.kube/config ...` or `--context <admin>`
# would use it. This launcher closes that gap as far as a launcher can:
#
# 1. It puts scripts/kubectl-guard first on PATH as `kubectl`, in a private temp
#    folder. The guard refuses every call unless KUBECONFIG is exactly the viewer
#    kubeconfig, and refuses any flag that picks another kubeconfig, context, cluster,
#    server or identity, wherever it is in the command.
# 2. It exports PATH, KUBECONFIG (the viewer file) and K8S_CREW_GUARD (the guard's
#    folder; scripts/preflight.sh refuses to start the crew without it).
# 3. It starts the agent with the crew's deny rules, without touching your own settings:
#    - claude:  --settings config/claude-settings.example.json (kubectl writes, Secret
#      reads, the target flags, kubectl by full path, reading kubeconfig and agent
#      credential files). With --auto-allow, also --allowedTools for the read-only
#      kubectl commands and the preflight, so those run without asking. The pipe filters
#      are not auto-allowed: Claude Code matches each pipe stage as its own command, so
#      a rule cannot say "only after a pipe", and Bash(grep *) would also let
#      `grep -r client-key-data ~` read credentials without a prompt. A pipe into a
#      filter asks first.
#    - copilot: config/copilot-deny-tools.sh --run (the same rules, as Copilot can
#      express them). With --auto-allow, kubectl runs without asking.
#    - shell:   an interactive bash with the same PATH and KUBECONFIG and no startup
#      files, for a herdr helper pane; `herdr agent start` then runs the agent in it.
#      It takes no arguments: `shell -c <text>` would run anything.
#
# --viewer defaults to ~/.kube/k8s-crew-viewer, written by scripts/viewer-kubeconfig.sh.
# Use --auto-allow only through this launcher: it is safe only because the guard and
# the viewer identity are in place. Residual risk: an agent that calls a kubectl binary
# by its full path skips the guard (Claude Code denies that form; Copilot cannot), and
# then only the RBAC of the identity it finds protects the cluster. Keep the admin
# kubeconfig out of the session's reach where you can.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
skill_dir="$(cd "$here/.." && pwd)"

usage() {
  echo "usage: crew-start.sh [--viewer PATH] [--auto-allow] claude|copilot [agent arguments...]" >&2
  echo "       crew-start.sh [--viewer PATH] shell" >&2
  exit 2
}

viewer="$HOME/.kube/k8s-crew-viewer"
auto_allow=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --viewer) [[ $# -ge 2 ]] || usage; viewer="$2"; shift 2 ;;
    --auto-allow) auto_allow=true; shift ;;
    claude|copilot|shell) break ;;
    *) usage ;;
  esac
done
[[ $# -gt 0 ]] || usage
kind="$1"
shift

if [[ "$viewer" == *:* ]]; then
  echo "crew-start.sh: --viewer takes one kubeconfig file, not a list: $viewer" >&2
  exit 2
fi
if [[ ! -f "$viewer" || ! -r "$viewer" ]]; then
  echo "crew-start.sh: no viewer kubeconfig at $viewer." >&2
  echo "Create it in your own terminal with $here/viewer-kubeconfig.sh" >&2
  exit 2
fi
viewer="$(cd "$(dirname "$viewer")" && pwd -P)/$(basename "$viewer")"

bin="$(mktemp -d "${TMPDIR:-/tmp}/k8s-crew-guard.XXXXXX")"
bin="$(cd "$bin" && pwd -P)"
"$here/kubectl-guard" install "$bin" "$viewer"

export PATH="$bin:$PATH"
export KUBECONFIG="$viewer"
export K8S_CREW_GUARD="$bin"

# Read-only kubectl commands that --auto-allow lets run without asking (the run-freely
# list of recipes/triage.md).
read_verbs=(
  get describe logs events top explain api-resources api-versions version cluster-info
  "auth can-i" "auth whoami" "rollout status" "rollout history"
)

case "$kind" in
  claude)
    args=()
    if [[ "$auto_allow" == true ]]; then
      args+=(--allowedTools)
      for verb in "${read_verbs[@]}"; do
        args+=("Bash(kubectl $verb)" "Bash(kubectl $verb *)")
      done
      for path in "$here/preflight.sh" "$(cd "$here" && pwd -P)/preflight.sh"; do
        args+=("Bash($path)" "Bash($path *)")
      done
    fi
    # --settings also ends the --allowedTools list, so the user's arguments stay theirs.
    args+=(--settings "$(cd "$skill_dir/config" && pwd -P)/claude-settings.example.json")
    exec claude "${args[@]}" "$@"
    ;;
  copilot)
    deny=("$skill_dir/config/copilot-deny-tools.sh")
    [[ "$auto_allow" == true ]] && deny+=(--auto-allow)
    exec "${deny[@]}" --run "$@"
    ;;
  shell)
    [[ "$auto_allow" == false && $# -eq 0 ]] || usage
    exec bash --noprofile --norc -i
    ;;
esac
