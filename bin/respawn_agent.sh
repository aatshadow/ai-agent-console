#!/usr/bin/env bash
# respawn_agent.sh — AI Agent Console primitive
#
# Usage:
#   respawn_agent.sh <role> [cadence]   respawn (or spawn) one agent
#   respawn_agent.sh --list             status of all known roles
#   respawn_agent.sh --zombies          respawn every session NOT in its workdir
#   respawn_agent.sh --dry-run <role>   show what would happen, don't touch tmux
#
# A "zombie" = tmux session whose cwd is not the role's configured workdir
# (so it's typically locked out of its own scheduler / memory files).
#
# Roles, sessions, cadences, and workdirs come from:
#   $AAC_HOME/config/roles.yaml       (override with $AAC_ROLES_CONFIG)
#
# $AAC_HOME is auto-detected as the parent of this script's directory
# unless explicitly set in the environment.
#
# Skip roles in --zombies by listing their ids in $SAFE_SKIP (space-separated).

set -euo pipefail

if [[ -z "${AAC_HOME:-}" ]]; then
  AAC_HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fi
export AAC_HOME

CONFIG_FILE="${AAC_ROLES_CONFIG:-$AAC_HOME/config/roles.yaml}"
SAFE_SKIP="${SAFE_SKIP-}"

declare -A SESSIONS CADENCES PROMPTS WORKDIRS
ROLE_IDS=()

# --- config loader --------------------------------------------------------
# Emits one pipe-delimited line per role: id|session|cadence|prompt_file|workdir
# prompt_file and workdir are resolved to absolute paths against $AAC_HOME.
load_roles() {
  python3 - "$CONFIG_FILE" "$AAC_HOME" <<'PY'
import os, sys
try:
    import yaml
except ImportError:
    sys.stderr.write("respawn_agent: python3 pyyaml is required to parse roles.yaml\n")
    sys.exit(3)
cfg_path, home = sys.argv[1], sys.argv[2]
with open(cfg_path) as f:
    cfg = yaml.safe_load(f) or {}
roles = cfg.get("roles") or []
defaults = cfg.get("defaults") or {}
prefix = defaults.get("session_prefix", "agent-")
workdirs_root = defaults.get("workdirs_root", "workdirs")
for r in roles:
    rid = (r or {}).get("id")
    if not rid:
        continue
    session = r.get("session") or f"{prefix}{rid}"
    cadence = r.get("cadence") or "30m"
    prompt_file = r.get("prompt_file") or f"roles/{rid}.md"
    workdir = r.get("workdir") or f"{workdirs_root}/{rid}"
    if not os.path.isabs(prompt_file):
        prompt_file = os.path.join(home, prompt_file)
    if not os.path.isabs(workdir):
        workdir = os.path.join(home, workdir)
    print(f"{rid}|{session}|{cadence}|{prompt_file}|{workdir}")
PY
}

load_config_into_arrays() {
  [[ -f "$CONFIG_FILE" ]] || return 1
  local lines
  if ! lines=$(load_roles); then
    echo "✗ failed to parse $CONFIG_FILE" >&2
    exit 2
  fi
  [[ -z "$lines" ]] && return 1
  while IFS='|' read -r rid session cadence prompt workdir; do
    [[ -z "$rid" ]] && continue
    ROLE_IDS+=("$rid")
    SESSIONS[$rid]="$session"
    CADENCES[$rid]="$cadence"
    PROMPTS[$rid]="$prompt"
    WORKDIRS[$rid]="$workdir"
  done <<< "$lines"
  [[ ${#ROLE_IDS[@]} -gt 0 ]]
}

no_roles_msg() {
  cat >&2 <<EOF
no roles configured yet
  expected: $CONFIG_FILE
  AAC_HOME: $AAC_HOME
  copy config/roles.yaml.example to config/roles.yaml to get started
  or set AAC_ROLES_CONFIG to point at a different file
EOF
}

extract_prompt() {
  # print lines strictly between the first ``` and the next ```
  awk '/^```/{n++; next} n==1' "$1"
}

wait_for_tui() {
  local session="$1" waited=0
  while ! tmux capture-pane -t "$session" -p | grep -qE '(shortcuts|Welcome|\? for)'; do
    sleep 1; waited=$((waited+1))
    if [[ $waited -gt 40 ]]; then
      echo "  ✗ claude TUI didn't boot after 40s — aborting" >&2
      return 1
    fi
  done
  return 0
}

respawn_one() {
  local role="$1" cadence="${2:-}" dry="${DRY:-0}"
  [[ -n "${CADENCES[$role]:-}" ]] || { echo "✗ unknown role: $role" >&2; return 1; }

  cadence="${cadence:-${CADENCES[$role]}}"
  local workdir="${WORKDIRS[$role]}"
  local session="${SESSIONS[$role]}"
  local prompt_path="${PROMPTS[$role]}"

  [[ ! -d "$workdir" ]] && { echo "✗ workdir missing: $workdir" >&2; return 1; }
  [[ ! -f "$prompt_path" ]] && { echo "✗ role file missing: $prompt_path" >&2; return 1; }

  local tmp_prompt; tmp_prompt=$(mktemp -t "respawn_${role}.XXXXXX")
  extract_prompt "$prompt_path" > "$tmp_prompt"
  local nlines; nlines=$(wc -l < "$tmp_prompt")
  [[ ! -s "$tmp_prompt" ]] && { echo "✗ empty prompt from $prompt_path" >&2; rm -f "$tmp_prompt"; return 1; }

  echo "── $role ──────────────────────────────────────"
  echo "  session : $session"
  echo "  workdir : $workdir"
  echo "  cadence : /loop $cadence"
  echo "  prompt  : $prompt_path ($nlines lines)"

  if [[ "$dry" == "1" ]]; then
    echo "  (dry-run — not touching tmux)"
    rm -f "$tmp_prompt"; return 0
  fi

  echo "  → killing old session (if any)"
  tmux kill-session -t "$session" 2>/dev/null || true

  echo "  → tmux new-session -c $workdir"
  tmux new-session -d -s "$session" -c "$workdir"
  sleep 1

  echo "  → launching claude"
  tmux send-keys -t "$session" 'claude' Enter
  wait_for_tui "$session" || { rm -f "$tmp_prompt"; return 1; }

  echo "  → /loop $cadence"
  tmux send-keys -t "$session" "/loop $cadence" Enter
  sleep 3

  echo "  → pasting role prompt (bracketed)"
  tmux load-buffer -t "$session" "$tmp_prompt"
  tmux paste-buffer -p -t "$session"
  sleep 1
  tmux send-keys -t "$session" Enter

  rm -f "$tmp_prompt"
  echo "  ✓ $role online"
}

list_status() {
  printf "%-15s %-24s %-42s %s\n" ROLE SESSION CWD STATUS
  for role in "${ROLE_IDS[@]}"; do
    local session="${SESSIONS[$role]}"
    local expected="${WORKDIRS[$role]}"
    local cwd status
    if tmux has-session -t "$session" 2>/dev/null; then
      cwd=$(tmux display-message -t "$session" -p '#{pane_current_path}' 2>/dev/null || echo "?")
      if [[ "$cwd" == "$expected" ]]; then
        status="✓ healthy"
      else
        status="⚠ zombie (old cwd)"
      fi
    else
      cwd="—"; status="✗ no session"
    fi
    printf "%-15s %-24s %-42s %s\n" "$role" "$session" "$cwd" "$status"
  done | sort
}

respawn_zombies() {
  local skipped=() respawned=0 failed=0
  for role in "${ROLE_IDS[@]}"; do
    local session="${SESSIONS[$role]}"
    tmux has-session -t "$session" 2>/dev/null || continue
    local cwd; cwd=$(tmux display-message -t "$session" -p '#{pane_current_path}' 2>/dev/null || true)
    local expected="${WORKDIRS[$role]}"
    [[ "$cwd" == "$expected" ]] && continue
    if [[ " $SAFE_SKIP " == *" $role "* ]]; then
      skipped+=("$role"); continue
    fi
    echo
    if respawn_one "$role"; then
      respawned=$((respawned+1))
    else
      failed=$((failed+1))
    fi
  done
  echo
  echo "────────────────"
  echo "respawned: $respawned   failed: $failed   skipped: ${skipped[*]:-none}"
}

main() {
  local have_config=1
  load_config_into_arrays || have_config=0

  case "${1:-}" in
    --list)
      if [[ "$have_config" == "0" ]]; then no_roles_msg; exit 0; fi
      list_status
      ;;
    --zombies)
      if [[ "$have_config" == "0" ]]; then no_roles_msg; exit 0; fi
      respawn_zombies
      ;;
    --dry-run)
      shift
      if [[ "$have_config" == "0" ]]; then no_roles_msg; exit 2; fi
      DRY=1 respawn_one "$@"
      ;;
    "")
      echo "usage: $0 <role> [cadence] | --list | --zombies | --dry-run <role>" >&2
      exit 2
      ;;
    -*)
      echo "unknown flag: $1" >&2
      exit 2
      ;;
    *)
      if [[ "$have_config" == "0" ]]; then no_roles_msg; exit 2; fi
      respawn_one "$@"
      ;;
  esac
}

main "$@"
