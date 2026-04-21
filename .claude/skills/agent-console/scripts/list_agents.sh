#!/usr/bin/env bash
# list_agents.sh — list tmux sessions that look like agent-console agents.
#
# Prints one session per line. Matches any session whose name starts with
# "agent-" (the default session_prefix in agent/config/roles.yaml). Override
# the prefix by passing it as the first argument.
#
# Exit codes:
#   0 = at least one session listed (or tmux not running, but handled cleanly)
#   1 = tmux missing from PATH
#
# Usage:
#   list_agents.sh              # default prefix "agent-"
#   list_agents.sh alfred-      # custom prefix

set -euo pipefail

PREFIX="${1:-agent-}"

if ! command -v tmux >/dev/null 2>&1; then
  echo "list_agents: tmux not found on PATH" >&2
  exit 1
fi

# `tmux ls` returns 1 when no server is running; treat that as "no agents".
sessions="$(tmux ls 2>/dev/null || true)"
if [[ -z "$sessions" ]]; then
  echo "(no tmux sessions)"
  exit 0
fi

matched="$(echo "$sessions" | grep "^${PREFIX}" || true)"
if [[ -z "$matched" ]]; then
  echo "(no sessions matching prefix '${PREFIX}')"
else
  echo "$matched"
fi
