"""
Telegram notification helper — any agent can import and call.

Reads TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID from .env.local at the repo root. If
either is missing (or the API call fails), the message is written to a local log
instead — never crashes the caller.

Role emoji prefixes are loaded from `config/config.yaml` under key
`notify.role_emojis` (merged on top of built-in defaults). Unknown roles get a
generic fallback glyph.

Usage:
    from lib.notify import send
    send("System", "Hello — the wizard finished.")
"""
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

# Skill dir: .claude/skills/agent-console/lib/notify.py
# parents: lib → agent-console → skills → .claude → <PROJECT_ROOT>
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env.local")

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
API = f"https://api.telegram.org/bot{TOKEN}"
LOG_PATH = PROJECT_ROOT / "agent" / "memory" / "notify.log"
CONFIG_PATH = PROJECT_ROOT / "agent" / "config" / "config.yaml"

DEFAULT_ROLE_EMOJIS = {"System": "⚙️"}
DEFAULT_FALLBACK_EMOJI = "🤖"


def _load_role_emojis() -> dict:
    """Merge DEFAULT_ROLE_EMOJIS with config/config.yaml:notify.role_emojis if present."""
    emojis = dict(DEFAULT_ROLE_EMOJIS)
    if not CONFIG_PATH.exists():
        return emojis
    try:
        import yaml  # lazy — pyyaml is optional at import time
        with CONFIG_PATH.open() as f:
            cfg = yaml.safe_load(f) or {}
        extras = (cfg.get("notify") or {}).get("role_emojis") or {}
        if isinstance(extras, dict):
            emojis.update({str(k): str(v) for k, v in extras.items()})
    except Exception:
        # Bad config shouldn't break notifications — fall back to defaults.
        pass
    return emojis


def _local_log(role: str, msg: str, reason: str = ""):
    """Fallback sink when Telegram is not configured or fails."""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a") as f:
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        f.write(f"[{ts}] [{role}] {reason}{msg}\n\n")


def send(role: str, message: str, silent: bool = False) -> dict:
    """Send a message to the configured Telegram chat. Returns a status dict.

    - role: short name (looked up in the emoji map; unknown roles get the fallback)
    - message: body (prefixed with role emoji + role tag)
    - silent: deliver without notification sound (useful for routine pings)
    """
    emojis = _load_role_emojis()
    prefix = emojis.get(role, DEFAULT_FALLBACK_EMOJI)
    body = f"{prefix} *[{role}]*\n{message}"

    if not TOKEN:
        _local_log(role, message, "NO_TOKEN ")
        return {"ok": False, "error": "TELEGRAM_BOT_TOKEN missing", "logged_locally": True}

    if not CHAT_ID:
        _local_log(role, message, "NO_CHAT_ID ")
        return {"ok": False, "error": "TELEGRAM_CHAT_ID missing — message the bot first", "logged_locally": True}

    try:
        r = requests.post(
            f"{API}/sendMessage",
            json={
                "chat_id": CHAT_ID,
                "text": body,
                "parse_mode": "Markdown",
                "disable_notification": silent,
            },
            timeout=10,
        )
        if r.status_code == 200:
            return {"ok": True, "message_id": r.json()["result"]["message_id"]}
        _local_log(role, message, f"API_ERROR {r.status_code} ")
        return {"ok": False, "error": f"Telegram API {r.status_code}: {r.text[:200]}", "logged_locally": True}
    except requests.exceptions.RequestException as e:
        _local_log(role, message, "NETWORK_ERROR ")
        return {"ok": False, "error": f"network: {e}", "logged_locally": True}


def self_test() -> dict:
    """Diagnostic: verify token works and chat_id is set."""
    if not TOKEN:
        return {"ok": False, "stage": "token", "error": "TELEGRAM_BOT_TOKEN missing from .env.local"}
    try:
        r = requests.get(f"{API}/getMe", timeout=10).json()
        if not r.get("ok"):
            return {"ok": False, "stage": "token", "error": r.get("description")}
        bot = r["result"]
        if not CHAT_ID:
            return {
                "ok": False,
                "stage": "chat_id",
                "error": "TELEGRAM_CHAT_ID missing. Message the bot on Telegram first, then run: python3 -m lib.notify --detect-chat-id",
                "bot_username": bot["username"],
            }
        return send("System", f"Self-test from `{bot['username']}` — all wired.")
    except Exception as e:
        return {"ok": False, "stage": "exception", "error": str(e)}


def detect_chat_id() -> dict:
    """Poll recent bot updates to auto-detect chat_id of whoever messaged the bot."""
    if not TOKEN:
        return {"ok": False, "error": "no token"}
    r = requests.get(f"{API}/getUpdates", timeout=10).json()
    updates = r.get("result", [])
    if not updates:
        return {
            "ok": False,
            "error": "No messages yet. Open Telegram, find your bot, press START and send any message, then re-run.",
        }
    chats = {}
    for u in updates:
        msg = u.get("message") or u.get("edited_message") or {}
        chat = msg.get("chat", {})
        if "id" in chat:
            chats[chat["id"]] = (
                f"{chat.get('first_name', '')} {chat.get('last_name', '') or ''}".strip()
                or chat.get("username", "unknown")
            )
    return {"ok": True, "chats": chats}


if __name__ == "__main__":
    import json
    if len(sys.argv) > 1 and sys.argv[1] == "--detect-chat-id":
        print(json.dumps(detect_chat_id(), indent=2))
    else:
        print(json.dumps(self_test(), indent=2))
