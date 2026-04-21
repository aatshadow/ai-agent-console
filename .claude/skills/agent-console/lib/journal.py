"""
Journal — append-only markdown journal of arbitrary events.

Each event writes a single markdown file to
`<PROJECT_ROOT>/agent/journal/<timestamp>_<event_type>.md`.

The journal is intentionally **generic**: it stores whatever `event: dict`
the caller passes. The skill doesn't prescribe keys — different roles log
different things (a trader logs trades; a scraper logs fetches; a designer
logs commits). The front-matter is the flattened event dict plus type/actor;
the body is free-form markdown assembled from context + analysis.

Usage:
    from lib.journal import write_entry
    write_entry(
        event={
            "type": "deploy",
            "actor": "designer",
            "commit": "abc123",
            "status": "success",
        },
        context="npm run build green; 12 files touched.",
        analysis="Migration from hardcoded colors to brand tokens landed clean.",
    )
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Skill dir: .claude/skills/agent-console/lib/journal.py
# parents: lib → agent-console → skills → .claude → <PROJECT_ROOT>
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
JOURNAL_DIR = PROJECT_ROOT / "agent" / "journal"


def _slug(s: str) -> str:
    """Filesystem-safe slug. Empty → 'event'."""
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s or "event"


def _front_matter(event: dict[str, Any]) -> str:
    lines = ["---"]
    for k, v in event.items():
        # Scalars go naked; nested things get JSON-encoded on one line.
        if isinstance(v, (dict, list)):
            lines.append(f"{k}: {json.dumps(v, default=str, ensure_ascii=False)}")
        else:
            lines.append(f"{k}: {v}")
    lines.append("---")
    return "\n".join(lines)


def write_entry(
    event: dict[str, Any],
    context: str = "",
    analysis: str = "",
) -> str:
    """Write a markdown journal entry and return its absolute path.

    - event: arbitrary dict. Keys `type` and `actor` are recommended; if
      `type` is missing it defaults to "event". All keys become front-matter.
    - context: what was happening when the event fired (inputs, state).
    - analysis: post-hoc reasoning, lesson, grade — whatever the caller
      wants to preserve for future cycles.
    """
    JOURNAL_DIR.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y-%m-%d_%H%M%S")
    event_type = str(event.get("type") or "event")
    actor = str(event.get("actor") or "unknown")

    # Don't clobber the caller's dict.
    meta = dict(event)
    meta.setdefault("type", event_type)
    meta.setdefault("actor", actor)
    meta.setdefault("logged_at", now.isoformat())

    filename = f"{timestamp}_{_slug(event_type)}.md"
    filepath = JOURNAL_DIR / filename

    body = f"""{_front_matter(meta)}

# {event_type} — {actor}

## Event
```
{json.dumps(event, indent=2, default=str, ensure_ascii=False)}
```

## Context
{context or "_(none provided)_"}

## Analysis
{analysis or "_(pending)_"}
"""
    filepath.write_text(body)
    return str(filepath)


def get_recent_entries(n: int = 10) -> list[str]:
    """Return the raw markdown of the last N journal entries, newest first."""
    if not JOURNAL_DIR.exists():
        return []
    entries = sorted(JOURNAL_DIR.glob("*.md"), reverse=True)[:n]
    return [e.read_text() for e in entries]


def get_entries_by_type(event_type: str, n: int = 20) -> list[str]:
    """Return entries whose front-matter `type:` matches."""
    if not JOURNAL_DIR.exists():
        return []
    out: list[str] = []
    needle = f"type: {event_type}"
    for f in sorted(JOURNAL_DIR.glob("*.md"), reverse=True):
        content = f.read_text()
        if needle in content:
            out.append(content)
            if len(out) >= n:
                break
    return out


def get_entries_by_actor(actor: str, n: int = 20) -> list[str]:
    """Return entries whose front-matter `actor:` matches."""
    if not JOURNAL_DIR.exists():
        return []
    out: list[str] = []
    needle = f"actor: {actor}"
    for f in sorted(JOURNAL_DIR.glob("*.md"), reverse=True):
        content = f.read_text()
        if needle in content:
            out.append(content)
            if len(out) >= n:
                break
    return out
