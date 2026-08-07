#!/usr/bin/env bash
# usage: sol.sh <task-name> <prompt-file>
set -uo pipefail
NAME="$1"; PROMPT_FILE="$2"
mkdir -p .sol/logs
codex exec \
  --sandbox workspace-write \
  --ephemeral \
  -o ".sol/logs/${NAME}.final.md" \
  "$(cat "$PROMPT_FILE")" \
  > ".sol/logs/${NAME}.out" 2> ".sol/logs/${NAME}.err"
CODE=$?
echo "exit=${CODE} name=${NAME}"
date -u +"%Y-%m-%dT%H:%M:%SZ" >> ".sol/logs/${NAME}.done"
exit $CODE
