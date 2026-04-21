"""
Config loaders for the agent-console skill.

Two YAML files live under `agent/config/`:
  - config.yaml   — agent_name, license_key, telegram creds, notify emojis
  - roles.yaml    — roles list + defaults (session_prefix, workdirs_root)

The `load_roles()` function mirrors the resolution logic used by
`scripts/spawn_agent.sh` so Python callers see the same shape the shell script
sees. If fields fall out of sync, the shell script is the source of truth —
update this loader to match it, not the other way around.

Path resolution: this module lives at
`.claude/skills/agent-console/lib/config.py` — five parents up is the
adopting project's root (PROJECT_ROOT). Config lives under
`<PROJECT_ROOT>/agent/config/`.

Usage:
    from lib.config import load_config, load_roles
    cfg = load_config()          # dict from agent/config/config.yaml
    roles = load_roles()         # {"roles": [...resolved...], "defaults": {...}}
"""
from pathlib import Path
from typing import Optional

import yaml

# Skill dir: .claude/skills/agent-console/lib/config.py
# parents: lib → agent-console → skills → .claude → <PROJECT_ROOT>
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "agent" / "config" / "config.yaml"
DEFAULT_ROLES_PATH = PROJECT_ROOT / "agent" / "config" / "roles.yaml"


def load_config(path: Optional[str] = None) -> dict:
    """Load config/config.yaml. Returns {} if the file is missing."""
    p = Path(path) if path else DEFAULT_CONFIG_PATH
    if not p.exists():
        return {}
    with p.open() as f:
        return yaml.safe_load(f) or {}


def load_roles(path: Optional[str] = None) -> dict:
    """Load config/roles.yaml and resolve per-role defaults.

    Returns `{"roles": [...], "defaults": {...}}` where each role dict has
    `id`, `session`, `cadence`, `prompt_file`, `workdir` fully resolved.
    Roles without an `id` are silently dropped (same as respawn_agent.sh).
    Missing file → empty lists/dicts.
    """
    p = Path(path) if path else DEFAULT_ROLES_PATH
    if not p.exists():
        return {"roles": [], "defaults": {}}
    with p.open() as f:
        data = yaml.safe_load(f) or {}

    defaults = data.get("defaults") or {}
    prefix = defaults.get("session_prefix", "agent-")
    workdirs_root = defaults.get("workdirs_root", "agent/workdirs")

    resolved = []
    for r in data.get("roles") or []:
        if not r or not r.get("id"):
            continue
        rid = r["id"]
        resolved.append({
            "id": rid,
            "session": r.get("session") or f"{prefix}{rid}",
            "cadence": r.get("cadence") or "30m",
            "prompt_file": r.get("prompt_file") or f"agent/roles/{rid}.md",
            "workdir": r.get("workdir") or f"{workdirs_root}/{rid}",
        })
    return {"roles": resolved, "defaults": defaults}


if __name__ == "__main__":
    import json
    import sys
    cfg_path = sys.argv[1] if len(sys.argv) > 1 else None
    roles_path = sys.argv[2] if len(sys.argv) > 2 else None
    print(json.dumps({
        "config": load_config(cfg_path),
        "roles": load_roles(roles_path),
    }, indent=2, ensure_ascii=False))
