#!/usr/bin/env bash
# usage: sol.sh <task-name> <prompt-file>
set -uo pipefail
NAME="$1"; PROMPT_FILE="$2"
cd "$(dirname "$0")/.."
mkdir -p .sol/logs
# --ephemeral         : no session persistence, so parallel runs cannot collide
# --sandbox           : workspace-write lets Sol edit files without approval prompts
# network_access      : lets him start the API and verify his own work. Every UI
#                       bug so far (render crash, rAF dependency, unreachable
#                       dashboard panels) was caught by Fable in a browser
#                       because Sol could not bind a port.
# -m                  : pinned rather than inherited from ~/.codex/config.toml
codex exec \
  --sandbox workspace-write \
  --ephemeral \
  -m gpt-5.6-sol \
  -c sandbox_workspace_write.network_access=true \
  -o ".sol/logs/${NAME}.final.md" \
  "$(cat "$PROMPT_FILE")" \
  > ".sol/logs/${NAME}.out" 2> ".sol/logs/${NAME}.err"
CODE=$?
echo "exit=${CODE} name=${NAME}"
date -u +"%Y-%m-%dT%H:%M:%SZ" >> ".sol/logs/${NAME}.done"
exit $CODE
