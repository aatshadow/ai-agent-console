"""
Cross-VPS HTTP bridge for ai-agent-console.

Minimal FastAPI app that one Alfred can expose so a peer Alfred (on another
VPS, over Tailscale) can ping, read state, ask questions, or push events. The
business-side brain picks up queued questions from memory/inbox_peer.md on its
next folder-driven cycle — the bridge never invokes the model itself.

Endpoints (all require header `X-Peer-Token: $PEER_TOKEN`):
  GET  /api/alfred/ping         → liveness + assistant name + version
  GET  /api/alfred/state        → agent/state.json + per-role last_cycle_ts
  POST /api/alfred/ask          → queue a question to inbox_peer.md
  POST /api/alfred/push_event   → log an event (journal + DB)

Run standalone:
  ./venv/bin/python .claude/skills/agent-console/lib/bridge.py

Or mount as sub-app from the business brain:
  from bridge import app as alfred_bridge
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ── paths ──────────────────────────────────────────────────────────────────-
# REPO_ROOT = /opt/ai-agent-console (3 parents up: lib → agent-console → skills → .claude → repo)
LIB_DIR = Path(__file__).resolve().parent
REPO_ROOT = LIB_DIR.parent.parent.parent.parent
AGENT_DIR = REPO_ROOT / "agent"
STATE_FILE = AGENT_DIR / "state.json"
INBOX_PEER = AGENT_DIR / "memory" / "inbox_peer.md"
JOURNAL_DIR = AGENT_DIR / "journal"

VERSION = "0.1.0"
PEER_TOKEN = os.getenv("PEER_TOKEN", "")


# ── db/journal lazy loaders ────────────────────────────────────────────────-
# db.py and journal.py are provided by the sibling subagent; import by file
# path so we don't need the package structure resolved at import time.
def _load_lib(name: str):
    path = LIB_DIR / f"{name}.py"
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location(f"aac_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return mod
    except Exception as e:  # pragma: no cover — best-effort import
        sys.stderr.write(f"bridge: could not load lib/{name}.py: {e}\n")
        return None


# ── app ─────────────────────────────────────────────────────────────────────
app = FastAPI(title="ai-agent-console bridge", version=VERSION)

# Tailscale CGNAT range — 100.64.0.0/10 in regex form.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d+\.\d+(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _require_token(x_peer_token: Optional[str]) -> None:
    if not PEER_TOKEN:
        raise HTTPException(status_code=503, detail="PEER_TOKEN not configured on this host")
    if x_peer_token != PEER_TOKEN:
        raise HTTPException(status_code=401, detail="invalid X-Peer-Token")


def _read_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def _role_last_cycle(role: str) -> Optional[str]:
    latest = AGENT_DIR / "memory" / role / "latest.json"
    if not latest.exists():
        return None
    try:
        data = json.loads(latest.read_text())
        return data.get("cycle_id") or data.get("last_update") or data.get("ts")
    except Exception:
        return None


# ── schemas ────────────────────────────────────────────────────────────────-
class AskBody(BaseModel):
    from_: str = ""  # alias for `from` (reserved word in python)
    question: str
    context: dict[str, Any] = {}

    class Config:
        fields = {"from_": "from"}


class EventBody(BaseModel):
    from_: str = ""
    event_type: str
    payload: dict[str, Any] = {}

    class Config:
        fields = {"from_": "from"}


# ── endpoints ───────────────────────────────────────────────────────────────
@app.get("/api/alfred/ping")
def ping(x_peer_token: Optional[str] = Header(None)):
    _require_token(x_peer_token)
    state = _read_state()
    return {
        "ok": True,
        "name": state.get("assistant_name") or "Alfred",
        "version": VERSION,
    }


@app.get("/api/alfred/state")
def state(x_peer_token: Optional[str] = Header(None)):
    _require_token(x_peer_token)
    st = _read_state()
    roles = st.get("active_roles") or []
    per_role = {r: {"last_cycle_ts": _role_last_cycle(r)} for r in roles}
    return {
        "state": st,
        "active_roles_count": len(roles),
        "roles": per_role,
    }


@app.post("/api/alfred/ask")
async def ask(request: Request, x_peer_token: Optional[str] = Header(None)):
    _require_token(x_peer_token)
    # Parse manually so `from` (reserved word) works cleanly over the wire.
    body = await request.json()
    peer = body.get("from") or body.get("from_") or "unknown"
    question = (body.get("question") or "").strip()
    ctx = body.get("context") or {}
    if not question:
        raise HTTPException(status_code=400, detail="question is required")

    queued_at = int(time.time())
    INBOX_PEER.parent.mkdir(parents=True, exist_ok=True)
    entry = (
        f"\n## {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(queued_at))} "
        f"from={peer}\n\n"
        f"**Q:** {question}\n\n"
        f"**context:** `{json.dumps(ctx, ensure_ascii=False)}`\n"
    )
    with INBOX_PEER.open("a", encoding="utf-8") as f:
        f.write(entry)

    return {"received": True, "queued_at": queued_at, "inbox": str(INBOX_PEER)}


@app.post("/api/alfred/push_event")
async def push_event(request: Request, x_peer_token: Optional[str] = Header(None)):
    _require_token(x_peer_token)
    body = await request.json()
    peer = body.get("from") or body.get("from_") or "unknown"
    event_type = body.get("event_type") or ""
    payload = body.get("payload") or {}
    if not event_type:
        raise HTTPException(status_code=400, detail="event_type is required")

    ts = int(time.time())

    # journal (markdown, best-effort — journal.py ported by sibling subagent)
    journal = _load_lib("journal")
    if journal and hasattr(journal, "write_entry"):
        try:
            journal.write_entry(
                event=f"peer_event/{event_type}",
                context={"from": peer, "payload": payload},
                analysis="",
            )
        except Exception as e:
            sys.stderr.write(f"bridge: journal.write_entry failed: {e}\n")
    else:
        # fallback: append raw markdown
        JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
        (JOURNAL_DIR / f"{time.strftime('%Y-%m-%d', time.gmtime(ts))}.md").open("a", encoding="utf-8").write(
            f"\n## {time.strftime('%H:%M:%SZ', time.gmtime(ts))} peer_event/{event_type} from={peer}\n"
            f"`{json.dumps(payload, ensure_ascii=False)}`\n"
        )

    # DB event (best-effort — db.py ported by sibling subagent)
    db = _load_lib("db")
    if db and hasattr(db, "log_event"):
        try:
            db.log_event(type=event_type, actor=peer, payload=payload)
        except Exception as e:
            sys.stderr.write(f"bridge: db.log_event failed: {e}\n")

    return {"received": True, "ts": ts}


# ── entry point ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("BRIDGE_PORT", "8787"))
    uvicorn.run("bridge:app", host="0.0.0.0", port=port, reload=False)
