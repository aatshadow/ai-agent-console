"""
Agent memory — SQLite store for arbitrary events, decisions, and role
performance metrics. Domain-agnostic: no trades, no positions, no prices.

Three tables:

  events
    id | created_at | type | actor | payload_json | tags
    Generic log of anything worth remembering (a deploy, a scrape, a
    detected anomaly, a user message). `payload_json` is opaque to the DB;
    `tags` is a comma-separated string for cheap LIKE filtering.

  decisions
    id | created_at | actor | action | reasoning | context_json | outcome | outcome_at
    Record of a choice an agent (or the operator) made, plus the
    eventual outcome once known. `outcome` is nullable — set it later
    via `record_outcome(decision_id, outcome)`.

  performance
    id | role | metric | value | measured_at
    Time-series of arbitrary per-role metrics (cycles_completed,
    items_processed, tokens_used, p95_latency_ms, …). Append-only; query
    with `performance_history(role, metric, since=...)`.

DB path: `<PROJECT_ROOT>/agent/data/agent.db`.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Skill dir: .claude/skills/agent-console/lib/db.py
# parents: lib → agent-console → skills → .claude → <PROJECT_ROOT>
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
DATA_DIR = PROJECT_ROOT / "agent" / "data"
DB_PATH = DATA_DIR / "agent.db"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_conn() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS events (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at   TEXT NOT NULL,
            type         TEXT NOT NULL,
            actor        TEXT NOT NULL,
            payload_json TEXT,
            tags         TEXT
        );

        CREATE TABLE IF NOT EXISTS decisions (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at   TEXT NOT NULL,
            actor        TEXT NOT NULL,
            action       TEXT NOT NULL,
            reasoning    TEXT,
            context_json TEXT,
            outcome      TEXT,
            outcome_at   TEXT
        );

        CREATE TABLE IF NOT EXISTS performance (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            role         TEXT NOT NULL,
            metric       TEXT NOT NULL,
            value        REAL NOT NULL,
            measured_at  TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_events_type       ON events(type);
        CREATE INDEX IF NOT EXISTS idx_events_actor      ON events(actor);
        CREATE INDEX IF NOT EXISTS idx_events_created    ON events(created_at);
        CREATE INDEX IF NOT EXISTS idx_decisions_actor   ON decisions(actor);
        CREATE INDEX IF NOT EXISTS idx_decisions_action  ON decisions(action);
        CREATE INDEX IF NOT EXISTS idx_decisions_created ON decisions(created_at);
        CREATE INDEX IF NOT EXISTS idx_perf_role_metric  ON performance(role, metric);
    """)
    conn.commit()
    conn.close()


# ── Events ────────────────────────────────────────────────────────────────

def log_event(
    event_type: str,
    actor: str,
    payload: dict[str, Any] | None = None,
    tags: list[str] | None = None,
) -> int:
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO events (created_at, type, actor, payload_json, tags)
           VALUES (?, ?, ?, ?, ?)""",
        (
            _now(),
            event_type,
            actor,
            json.dumps(payload) if payload is not None else None,
            ",".join(tags) if tags else None,
        ),
    )
    eid = cur.lastrowid
    conn.commit()
    conn.close()
    return eid


def get_events(
    *,
    event_type: str | None = None,
    actor: str | None = None,
    tag: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    conn = get_conn()
    clauses: list[str] = []
    params: list[Any] = []
    if event_type:
        clauses.append("type = ?")
        params.append(event_type)
    if actor:
        clauses.append("actor = ?")
        params.append(actor)
    if tag:
        clauses.append("tags LIKE ?")
        params.append(f"%{tag}%")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"SELECT * FROM events {where} ORDER BY created_at DESC LIMIT ?",
        (*params, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Decisions ─────────────────────────────────────────────────────────────

def log_decision(
    actor: str,
    action: str,
    reasoning: str | None = None,
    context: dict[str, Any] | None = None,
) -> int:
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO decisions (created_at, actor, action, reasoning, context_json)
           VALUES (?, ?, ?, ?, ?)""",
        (
            _now(),
            actor,
            action,
            reasoning,
            json.dumps(context) if context is not None else None,
        ),
    )
    did = cur.lastrowid
    conn.commit()
    conn.close()
    return did


def record_outcome(decision_id: int, outcome: str) -> None:
    conn = get_conn()
    conn.execute(
        "UPDATE decisions SET outcome = ?, outcome_at = ? WHERE id = ?",
        (outcome, _now(), decision_id),
    )
    conn.commit()
    conn.close()


def get_decisions(
    *,
    actor: str | None = None,
    action: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    conn = get_conn()
    clauses: list[str] = []
    params: list[Any] = []
    if actor:
        clauses.append("actor = ?")
        params.append(actor)
    if action:
        clauses.append("action = ?")
        params.append(action)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"SELECT * FROM decisions {where} ORDER BY created_at DESC LIMIT ?",
        (*params, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Performance ───────────────────────────────────────────────────────────

def record_metric(role: str, metric: str, value: float) -> int:
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO performance (role, metric, value, measured_at)
           VALUES (?, ?, ?, ?)""",
        (role, metric, float(value), _now()),
    )
    pid = cur.lastrowid
    conn.commit()
    conn.close()
    return pid


def performance_history(
    role: str,
    metric: str,
    *,
    since: str | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    conn = get_conn()
    clauses = ["role = ?", "metric = ?"]
    params: list[Any] = [role, metric]
    if since:
        clauses.append("measured_at >= ?")
        params.append(since)
    where = " AND ".join(clauses)
    rows = conn.execute(
        f"""SELECT measured_at, value FROM performance
            WHERE {where} ORDER BY measured_at DESC LIMIT ?""",
        (*params, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def latest_metric(role: str, metric: str) -> float | None:
    conn = get_conn()
    row = conn.execute(
        """SELECT value FROM performance WHERE role = ? AND metric = ?
           ORDER BY measured_at DESC LIMIT 1""",
        (role, metric),
    ).fetchone()
    conn.close()
    return float(row["value"]) if row else None


# Initialize on import so callers don't have to remember.
init_db()
