#!/usr/bin/env python3
"""
Watchdog for ai-agent-console — periodically checks tmux agent health.

Detects:
  - dead        : tmux session doesn't exist
  - zombie      : session exists but cwd doesn't match role's workdir
  - stale       : session alive but latest.json.cycle_id older than 2× cadence
  - pristine    : session alive but no latest.json yet (first cycle never finished)
  - parse_error : latest.json exists but is unreadable / malformed

De-dupes via $AAC_HOME/memory/watchdog_state.json so it only notifies on
state CHANGE (new issue or recovery).

Roles come from config/roles.yaml via lib.config.load_roles(). Each role is
expected to write its heartbeat to $AAC_HOME/memory/<id>/latest.json with a
`cycle_id` (ISO timestamp); the watchdog uses this plus the role's `cadence`
to decide staleness.

Intended for cron / a systemd timer (see systemd/aac-watchdog.timer).
Run with --dry-run to check state without notifying or writing state.
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Tuple

# Skill dir: .claude/skills/agent-console/scripts/watchdog.py
# parents: scripts → agent-console → skills → .claude → <PROJECT_ROOT>
SKILL_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = Path(os.getenv("AAC_HOME") or SKILL_DIR.parent.parent.parent)
sys.path.insert(0, str(SKILL_DIR))

from lib.config import load_roles  # noqa: E402
from lib.notify import send  # noqa: E402

STATE_FILE = PROJECT_ROOT / "agent" / "memory" / "watchdog_state.json"
MEMORY_ROOT = PROJECT_ROOT / "agent" / "memory"


def parse_cadence_minutes(cadence: str) -> int:
    """Convert a /loop-style cadence ('30m', '1h', '6h', '45s') to minutes.

    Returns max(1, minutes) so nothing is ever treated as zero-cadence. Falls
    back to 30 minutes for unparseable strings.
    """
    s = str(cadence).strip().lower()
    m = re.match(r"^(\d+)([smhd]?)$", s)
    if not m:
        return 30
    n, unit = int(m.group(1)), m.group(2)
    if unit == "h":
        return n * 60
    if unit == "d":
        return n * 60 * 24
    if unit == "s":
        return max(1, n // 60)
    return max(1, n)


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"last_alert_key": None}


def save_state(s: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(s, indent=2))


def _tmux(*args) -> subprocess.CompletedProcess:
    """Run tmux, returning a CompletedProcess. Treat missing tmux as a failure."""
    try:
        return subprocess.run(["tmux", *args], capture_output=True, text=True)
    except FileNotFoundError:
        return subprocess.CompletedProcess(args=args, returncode=127, stdout="", stderr="tmux: not found")


def _resolve_workdir(workdir: str) -> str:
    return workdir if os.path.isabs(workdir) else str(PROJECT_ROOT / workdir)


def check_role(role: dict) -> Tuple[str, object]:
    session = role["session"]
    workdir = _resolve_workdir(role["workdir"])

    r = _tmux("has-session", "-t", session)
    if r.returncode != 0:
        return "dead", None

    p = _tmux("display-message", "-t", session, "-p", "#{pane_current_path}")
    cwd = (p.stdout or "").strip()
    if cwd and cwd != workdir:
        return "zombie", cwd

    latest = MEMORY_ROOT / role["id"] / "latest.json"
    if not latest.exists():
        return "pristine", None

    try:
        data = json.loads(latest.read_text())
        ts = data.get("cycle_id") or data.get("last_update") or data.get("ts")
        if not ts:
            return "pristine", None
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        age_min = (datetime.now(timezone.utc) - dt).total_seconds() / 60
        threshold = parse_cadence_minutes(role["cadence"]) * 2
        if age_min > threshold:
            return "stale", int(age_min)
    except Exception as e:
        return "parse_error", str(e)

    return "ok", None


def human_line(role: dict, status: str, detail) -> str:
    rid = role["id"]
    session = role["session"]
    cad = parse_cadence_minutes(role["cadence"])
    if status == "dead":
        return f"• *{rid}*: sesión caída — ningún tmux para `{session}`"
    if status == "zombie":
        return f"• *{rid}*: zombie — cwd incorrecto, no va a volver a ciclar"
    if status == "stale":
        return f"• *{rid}*: lleva *{detail} min* sin ciclar (cadencia {cad} min)"
    if status == "pristine":
        return f"• *{rid}*: sin primer ciclo aún (recién respawneado?)"
    if status == "parse_error":
        return f"• *{rid}*: no puedo leer su latest.json — {detail}"
    return f"• *{rid}*: {status} — {detail}"


def main() -> int:
    ap = argparse.ArgumentParser(description="ai-agent-console watchdog")
    ap.add_argument("--dry-run", action="store_true",
                    help="check roles and print status; don't notify or save state")
    args = ap.parse_args()

    roles = load_roles().get("roles") or []
    if not roles:
        if args.dry_run:
            print("no roles configured — nothing to check")
        return 0

    state = load_state()
    issues = []
    for role in roles:
        status, detail = check_role(role)
        if args.dry_run:
            print(f"{role['id']:<16} {role['session']:<28} {status}"
                  + (f"  ({detail})" if detail else ""))
        if status != "ok":
            issues.append((role, status, detail))

    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    alert_key = "|".join(sorted(f"{r['id']}:{s}" for r, s, _ in issues))
    last_key = state.get("last_alert_key") or ""

    if args.dry_run:
        print(f"\n{len(issues)} issue(s); alert_key={alert_key or '<none>'}")
        return 0

    if issues and alert_key != last_key:
        lines = ["🚨 *Watchdog* — agentes con problemas:\n"]
        for role, status, detail in issues:
            lines.append(human_line(role, status, detail))
        lines.append("\nDime `respawn zombies` si quieres que los reviva.")
        send("System", "\n".join(lines))
        state["last_alert_key"] = alert_key
        state["last_alert_ts"] = now_iso
    elif not issues and last_key:
        send("System", "✅ Todos los agentes están sanos otra vez.")
        state["last_alert_key"] = ""
        state["last_recover_ts"] = now_iso

    state["last_check_ts"] = now_iso
    state["n_issues"] = len(issues)
    save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
