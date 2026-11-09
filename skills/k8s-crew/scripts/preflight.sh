#!/usr/bin/env bash
# Refuse to start the crew unless the session is held to the view-only identity.
# Fails closed: anything it cannot positively confirm blocks the crew.
#
# Exit codes (SKILL.md tells the boss what to say for each):
#   0  viewer ok
#   2  bad arguments
#   3  NOT view-only: some can-i check answered something other than a denial
#   4  investigator agent missing (with --subagents)
#   5  cannot check identity: kubectl failed (expired token, unreachable cluster, the
#      kubectl guard refused the call)
#   6  kubectl guard not active: the session was not started with scripts/crew-start.sh
set -euo pipefail

subagents=false
platform=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --subagents) subagents=true; shift ;;
    --platform) platform="${2:?--platform needs claude or copilot}"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

# The kubectl guard (scripts/kubectl-guard, put first on PATH by scripts/crew-start.sh)
# is what keeps every agent in the session on the viewer kubeconfig: without it, a
# kubectl --kubeconfig or --context flag reaches any other kubeconfig on the machine.
if [[ -z "${K8S_CREW_GUARD:-}" || "$(command -v kubectl || true)" != "$K8S_CREW_GUARD/kubectl" ]]
then
  echo "kubectl guard not active: this session was not started with scripts/crew-start.sh."
  echo "Without it, any other kubeconfig on this machine (your admin one) is reachable."
  echo "Start a new session with <skill-dir>/scripts/crew-start.sh claude (or copilot)."
  exit 6
fi

errfile="$(mktemp)"
trap 'rm -f "$errfile"' EXIT
nl=$'\n'
# A denial is "no", or "no - <reason>" when the authorizer gives one (webhook
# authorizers such as AKS Azure RBAC do). One line only.
denial="^no( - [^${nl}]+)?$"
blocked=0
errors=0
check() {
  local label="$1"; shift
  local answer
  answer="$(kubectl auth can-i "$@" 2>"$errfile" || true)"
  if [[ "$answer" =~ $denial ]]; then
    return 0
  elif [[ -z "$answer" ]]; then
    echo "cannot check identity: can-i $label: $(head -n 1 "$errfile" || true)"
    errors=1
  else
    echo "NOT view-only: can-i $label answered '$answer'"
    blocked=1
  fi
}
check "create deployments -A" create deployments -A
check "delete pods -A" delete pods -A
check "patch nodes" patch nodes
check "get secrets -A" get secrets -A

# The checks above ask about cluster scope only (-A asks for every namespace at once,
# which only a ClusterRoleBinding grants). A RoleBinding gives rights in one namespace,
# so an identity with cluster-wide view plus edit or Secret read in a few namespaces
# passes them. So the same questions are asked again in every namespace the identity
# can list. `can-i --list` is not used: it relies on SelfSubjectRulesReview, which
# webhook authorizers (AKS Azure RBAC) answer incompletely, so it would miss rights and
# fail open. Explicit checks are authoritative; they cost three API calls per namespace,
# once per session. The loop stops at the first namespace with a problem.
if [[ "$blocked" -eq 0 && "$errors" -eq 0 ]]; then
  if ! namespaces="$(kubectl get namespaces -o 'jsonpath={.items[*].metadata.name}' \
    2>"$errfile")"; then
    echo "cannot check identity: get namespaces: $(head -n 1 "$errfile" || true)"
    errors=1
  elif [[ -z "${namespaces// /}" ]]; then
    echo "cannot check identity: get namespaces listed no namespace"
    errors=1
  else
    for ns in $namespaces; do
      check "create deployments -n $ns" create deployments -n "$ns"
      check "delete pods -n $ns" delete pods -n "$ns"
      check "get secrets -n $ns" get secrets -n "$ns"
      [[ "$blocked" -eq 0 && "$errors" -eq 0 ]] || break
    done
  fi
fi

if [[ "$blocked" -ne 0 ]]; then
  echo "This identity can change the cluster or read Secrets. Create the viewer"
  echo "kubeconfig with scripts/viewer-kubeconfig.sh and start a new session with"
  echo "scripts/crew-start.sh."
  exit 3
fi
if [[ "$errors" -ne 0 ]]; then
  echo "Could not check the identity: the cluster is unreachable, the viewer token has"
  echo "expired (it lasts 8 hours), or the kubectl guard refused the call. Run"
  echo "scripts/viewer-kubeconfig.sh again in your own terminal, then start a new"
  echo "session with scripts/crew-start.sh."
  exit 5
fi

# Folders from $PWD up to the git root (only $PWD outside a git repository), nearest first.
project_dirs() {
  local dir top
  dir="$(pwd -P)"
  top="$(git rev-parse --show-toplevel 2>/dev/null || true)"
  [[ -n "$top" ]] && top="$(cd "$top" && pwd -P)"
  while :; do
    echo "$dir"
    [[ -z "$top" || "$dir" == "$top" || "$dir" == / ]] && break
    dir="$(dirname "$dir")"
  done
}

# Every place the platform loads the investigator from, in the order it looks.
candidates() {
  local dir
  case "$platform" in
    claude)
      while IFS= read -r dir; do
        echo "$dir/.claude/agents/k8s-crew-investigator.md"
      done < <(project_dirs)
      echo "$HOME/.claude/agents/k8s-crew-investigator.md"
      ;;
    copilot)
      echo "$HOME/.copilot/agents/k8s-crew-investigator.agent.md"
      echo "$HOME/.copilot/agents/k8s-crew-investigator.md"
      while IFS= read -r dir; do
        for sub in .github/agents .claude/agents; do
          echo "$dir/$sub/k8s-crew-investigator.agent.md"
          echo "$dir/$sub/k8s-crew-investigator.md"
        done
      done < <(project_dirs)
      ;;
  esac
}

# True when $1 is the root of a k8s-crew Claude Code plugin with the investigator in it.
is_crew_plugin() {
  local root="$1"
  [[ -f "$root/skills/k8s-crew/agents/k8s-crew-investigator.md" ]] || return 1
  grep -Eq '"name"[[:space:]]*:[[:space:]]*"k8s-crew"' "$root/.claude-plugin/plugin.json" \
    2>/dev/null
}

# Roots of k8s-crew plugins Claude Code installed: the install paths it records, and the
# plugin this script runs from when that is inside ~/.claude/plugins (a git clone also
# has a plugin.json, but nothing installed it, so it does not count).
plugin_roots() {
  local record="$HOME/.claude/plugins/installed_plugins.json" own
  if [[ -f "$record" ]]; then
    grep -Eo '"installPath"[[:space:]]*:[[:space:]]*"[^"]*"' "$record" \
      | sed -E 's/.*:[[:space:]]*"(.*)"$/\1/' || true
  fi
  own="$(cd "$here/../../.." && pwd -P)"
  case "$own/" in
    "$(cd "$HOME" && pwd -P)/.claude/plugins/"*) echo "$own" ;;
  esac
}

if [[ "$subagents" == true ]]; then
  case "$platform" in
    claude|copilot) ;;
    *) echo "--subagents needs --platform claude|copilot" >&2; exit 2 ;;
  esac
  found=""
  kind=""
  while IFS= read -r agent; do
    if [[ -e "$agent" ]]; then
      found="$agent"
      case "$agent" in
        "$HOME"/.claude/agents/*|"$HOME"/.copilot/agents/*) kind="user" ;;
        *) kind="project" ;;
      esac
      break
    fi
  done < <(candidates)
  if [[ -z "$found" && "$platform" == claude ]]; then
    here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
    while IFS= read -r root; do
      if [[ -n "$root" ]] && is_crew_plugin "$root"; then
        found="$root/skills/k8s-crew/agents/k8s-crew-investigator.md"
        kind="plugin"
        break
      fi
    done < <(plugin_roots)
  fi
  if [[ -z "$found" ]]; then
    echo "investigator agent missing: not found in any $platform agent folder:"
    candidates | sed 's/^/  /'
    [[ "$platform" == claude ]] && echo "  or a k8s-crew Claude Code plugin install"
    echo "run scripts/install-agents.sh"
    exit 4
  fi
  name="k8s-crew-investigator"
  [[ "$kind" == plugin ]] && name="k8s-crew:k8s-crew-investigator"
  echo "investigator: $kind $name ($found)"
fi

echo "viewer ok"
