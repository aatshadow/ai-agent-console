"""
Taskmaster — shared task board for the operator + all agents.

Append-only event log at `agent/memory/taskmaster/tasks.jsonl` (under the
adopting project's root). Each line is an event (create/update). Current task
state = merge of all events with the same id.

Why append-only: lossless audit trail (the operator can see exactly who
changed what and when), trivial to reconstruct, and safe under concurrent
writes from multiple agents.

Every task tracks: owner (who executes), source (who requested), status
(inbox/in_progress/done/blocked), tokens_used, duration_sec, notes.

Usage from any agent:
    from lib.taskmaster import create_task, update_task, list_tasks
    tid = create_task("Build kanban UI", owner="designer", source="operator",
                      description="...", priority=1)
    update_task(tid, {"status": "in_progress"}, by="designer")
    update_task(tid, {"status": "done", "tokens_delta": 12000,
                      "duration_delta": 420}, by="designer")
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Skill dir: .claude/skills/agent-console/lib/taskmaster.py
# parents: lib → agent-console → skills → .claude → <PROJECT_ROOT>
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
STORE_DIR = PROJECT_ROOT / "agent" / "memory" / "taskmaster"
TASKS_LOG = STORE_DIR / "tasks.jsonl"

VALID_STATUS = {"inbox", "in_progress", "done", "blocked"}
# owner / source are free-form strings — any agent id, "operator", "system",
# "brain", etc. Validation is intentionally loose so new roles work without
# updates here.


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    # Short, sortable, URL-safe: t_YYYYMMDDhhmmss_xxxx
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    suffix = uuid.uuid4().hex[:5]
    return f"t_{stamp}_{suffix}"


def _append_event(event: dict[str, Any]) -> None:
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    with TASKS_LOG.open("a") as f:
        f.write(json.dumps(event, default=str) + "\n")


def _load_events() -> list[dict[str, Any]]:
    if not TASKS_LOG.exists():
        return []
    out: list[dict[str, Any]] = []
    with TASKS_LOG.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _reduce(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Fold the event log into current-state dict keyed by task id."""
    tasks: dict[str, dict[str, Any]] = {}
    for ev in events:
        tid = ev.get("id")
        if not tid:
            continue
        if ev.get("event") == "create":
            base = {
                "id": tid,
                "title": ev.get("title", "(untitled)"),
                "description": ev.get("description", ""),
                "owner": ev.get("owner", "operator"),
                "source": ev.get("source", "operator"),
                "status": "inbox",
                "priority": ev.get("priority", 2),
                "tokens_used": 0,
                "duration_sec": 0,
                "notes": [],
                "created_at": ev.get("ts"),
                "started_at": None,
                "completed_at": None,
                "updated_at": ev.get("ts"),
            }
            tasks[tid] = base
        elif ev.get("event") == "update":
            if tid not in tasks:
                # Orphan update: reconstruct a stub so we don't drop it silently
                tasks[tid] = {
                    "id": tid,
                    "title": "(recovered)",
                    "description": "",
                    "owner": "operator",
                    "source": "operator",
                    "status": "inbox",
                    "priority": 2,
                    "tokens_used": 0,
                    "duration_sec": 0,
                    "notes": [],
                    "created_at": ev.get("ts"),
                    "started_at": None,
                    "completed_at": None,
                    "updated_at": ev.get("ts"),
                }
            t = tasks[tid]
            patch = ev.get("patch") or {}
            # Auto-stamp timestamps on status transitions
            new_status = patch.get("status")
            if new_status == "in_progress" and not t.get("started_at"):
                t["started_at"] = ev.get("ts")
            if new_status == "done" and not t.get("completed_at"):
                t["completed_at"] = ev.get("ts")
            # Accumulate tokens/duration instead of overwrite when sent as deltas
            if "tokens_delta" in patch:
                t["tokens_used"] = (t.get("tokens_used") or 0) + int(patch["tokens_delta"])
            if "duration_delta" in patch:
                t["duration_sec"] = (t.get("duration_sec") or 0) + float(patch["duration_delta"])
            # Notes append
            if "note" in patch:
                t.setdefault("notes", []).append({
                    "ts": ev.get("ts"),
                    "by": ev.get("by", "unknown"),
                    "note": patch["note"],
                })
            # Straight fields
            for k in ("title", "description", "owner", "source", "status",
                      "priority", "tokens_used", "duration_sec"):
                if k in patch:
                    t[k] = patch[k]
            t["updated_at"] = ev.get("ts")
    return tasks


# ── Public API ──────────────────────────────────────────────────────────────

def create_task(
    title: str,
    *,
    owner: str = "operator",
    source: str = "operator",
    description: str = "",
    priority: int = 2,
) -> str:
    """Create a new task. Returns the generated task id."""
    tid = _new_id()
    _append_event({
        "event": "create",
        "id": tid,
        "ts": _now(),
        "by": source,
        "title": title,
        "description": description,
        "owner": owner,
        "source": source,
        "priority": priority,
    })
    return tid


def update_task(task_id: str, patch: dict[str, Any], *, by: str) -> None:
    """Apply a patch. Supports straight fields + tokens_delta/duration_delta/note."""
    if patch.get("status") and patch["status"] not in VALID_STATUS:
        raise ValueError(f"invalid status: {patch['status']}")
    _append_event({
        "event": "update",
        "id": task_id,
        "ts": _now(),
        "by": by,
        "patch": patch,
    })


def add_note(task_id: str, note: str, *, by: str) -> None:
    update_task(task_id, {"note": note}, by=by)


def record_cycle(task_id: str, *, by: str, tokens: int, duration_sec: float) -> None:
    """Shortcut: an agent completed a cycle of work on this task."""
    update_task(
        task_id,
        {"tokens_delta": tokens, "duration_delta": duration_sec},
        by=by,
    )


def list_tasks(
    *,
    owner: str | None = None,
    status: str | None = None,
    source: str | None = None,
) -> list[dict[str, Any]]:
    """Return current-state of all tasks, optionally filtered."""
    tasks = _reduce(_load_events())
    out = list(tasks.values())
    if owner:
        out = [t for t in out if t.get("owner") == owner]
    if status:
        out = [t for t in out if t.get("status") == status]
    if source:
        out = [t for t in out if t.get("source") == source]

    def sort_key(t: dict[str, Any]) -> tuple:
        order = {"in_progress": 0, "inbox": 1, "blocked": 2, "done": 3}.get(
            t.get("status", "inbox"), 9
        )
        return (order, t.get("priority", 2), -(_parse_ts(t.get("updated_at"))))

    out.sort(key=sort_key)
    return out


def get_task(task_id: str) -> dict[str, Any] | None:
    return _reduce(_load_events()).get(task_id)


def stats() -> dict[str, Any]:
    """Aggregate metrics for dashboards."""
    tasks = list(_reduce(_load_events()).values())
    total_tokens = sum(int(t.get("tokens_used") or 0) for t in tasks)
    total_duration = sum(float(t.get("duration_sec") or 0) for t in tasks)
    by_status: dict[str, int] = {}
    by_owner: dict[str, int] = {}
    for t in tasks:
        by_status[t["status"]] = by_status.get(t["status"], 0) + 1
        by_owner[t["owner"]] = by_owner.get(t["owner"], 0) + 1
    return {
        "total_tasks": len(tasks),
        "total_tokens": total_tokens,
        "total_duration_sec": total_duration,
        "by_status": by_status,
        "by_owner": by_owner,
    }


def _parse_ts(ts: str | None) -> float:
    if not ts:
        return 0.0
    try:
        return datetime.fromisoformat(ts).timestamp()
    except Exception:
        return 0.0


if __name__ == "__main__":
    # Tiny CLI for manual poking: python3 -m lib.taskmaster list
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "list":
        for t in list_tasks():
            print(f"[{t['status']:12}] {t['id']}  owner={t['owner']:10} "
                  f"src={t['source']:8} {t['title']}")
    elif cmd == "stats":
        print(json.dumps(stats(), indent=2))
    elif cmd == "create" and len(sys.argv) >= 3:
        tid = create_task(" ".join(sys.argv[2:]), owner="operator", source="operator")
        print(tid)
    else:
        print("usage: python3 -m lib.taskmaster [list|stats|create <title>]")
