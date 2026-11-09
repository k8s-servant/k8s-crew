#!/usr/bin/env bash
# Symlink the investigator agent into the Claude Code and Copilot CLI agent folders.
# Idempotent; never overwrites a file that is not a symlink.
set -euo pipefail

claude=false
copilot=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --claude) claude=true; shift ;;
    --copilot) copilot=true; shift ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
if [[ "$claude" == false && "$copilot" == false ]]; then
  claude=true
  copilot=true
fi

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source_file="$here/../agents/k8s-crew-investigator.md"
source_file="$(cd "$(dirname "$source_file")" && pwd)/$(basename "$source_file")"

link() {
  local target="$1"
  mkdir -p "$(dirname "$target")"
  if [[ -e "$target" && ! -L "$target" ]]; then
    echo "refusing to overwrite $target: it is not a symlink" >&2
    return 1
  fi
  ln -sfn "$source_file" "$target"
  echo "linked $target"
}

status=0
[[ "$claude" == true ]] && { link "$HOME/.claude/agents/k8s-crew-investigator.md" || status=1; }
[[ "$copilot" == true ]] && { link "$HOME/.copilot/agents/k8s-crew-investigator.agent.md" || status=1; }
exit "$status"
