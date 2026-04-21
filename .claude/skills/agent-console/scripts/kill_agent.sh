#!/usr/bin/env bash
# kill_agent.sh — kill one agent tmux session by role id.
#
# Resolves the full session name as "${PREFIX}${ROLE_ID}" and issues
# `tmux kill-session`. Default prefix is "agent-"; override with the
# $AAC_SESSION_PREFIX env var to match your agent/config/roles.yaml.
#
# Usage:
#   kill_agent.sh <role_id>
#   AAC_SESSION_PREFIX=alfred- kill_agent.sh trader
#
# Exit codes:
#   0 = session killed (or didn't exist)
#   1 = tmux missing, or no role id passed

set -euo pipefail

if ! command -v tmux >/dev/null 2>&1; then
  echo "kill_agent: tmux not found on PATH" >&2
  exit 1
fi

if [[ $# -lt 1 || -z "${1:-}" ]]; then
  echo "usage: $0 <role_id>" >&2
  exit 1
fi

PREFIX="${AAC_SESSION_PREFIX:-agent-}"
ROLE="$1"
SESSION="${PREFIX}${ROLE}"

if tmux has-session -t "$SESSION" 2>/dev/null; then
  tmux kill-session -t "$SESSION"
  echo "killed: $SESSION"
else
  echo "no session: $SESSION (already gone)"
fi
