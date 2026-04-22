#!/usr/bin/env python3
"""
ai-agent-console — onboarding wizard.

Asks a handful of questions, renders the brain/voice/soul templates into
`agent/`, writes `.env.local` + `agent/state.json`, and ensures per-role
memory folders exist. Uses only stdlib.

Templates consumed (rendered with simple `{{VAR}}` replacement):
  .claude/skills/agent-console/templates/brain/SOUL.md.template
  .claude/skills/agent-console/templates/brain/VOICE.md.template
  .claude/skills/agent-console/templates/brain/BRAIN.md.template
  .claude/skills/agent-console/templates/brain/TELEGRAM_VOICE.md.template
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
AGENT_DIR = REPO_ROOT / "agent"
TPL_BRAIN = REPO_ROOT / ".claude" / "skills" / "agent-console" / "templates" / "brain"
ENV_FILE = REPO_ROOT / ".env.local"

sys.path.insert(0, str(REPO_ROOT / ".claude" / "skills" / "agent-console" / "lib"))
import license as lic  # noqa: E402

DEFAULT_ROLES = ["researcher", "designer", "watcher", "analyst",
                 "extractor", "changewatcher", "taskmaster"]
CADENCE_MAP = {"15min": 900, "30min": 1800, "60min": 3600}


# ── prompt helpers ──────────────────────────────────────────────────────────
def prompt(question: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        ans = input(f"{question}{suffix}: ").strip()
    except EOFError:
        ans = ""
    return ans or default


def prompt_choice(question: str, choices: list[str], default: str) -> str:
    opts = "/".join(choices)
    while True:
        ans = prompt(f"{question} ({opts})", default).lower()
        if ans in choices:
            return ans
        print(f"  → elige una de: {opts}")


def prompt_yes_no(question: str, default: str = "n") -> bool:
    ans = prompt(f"{question} (y/n)", default).lower()
    return ans in ("y", "yes", "s", "si", "sí")


def prompt_roles(default: list[str]) -> list[str]:
    print(f"  roles disponibles: {', '.join(DEFAULT_ROLES)}")
    raw = prompt("  activa cuáles (coma-separado, * = todos)", ",".join(default))
    if raw.strip() == "*":
        return list(DEFAULT_ROLES)
    picked = [r.strip() for r in raw.split(",") if r.strip()]
    unknown = [r for r in picked if r not in DEFAULT_ROLES]
    if unknown:
        print(f"  ignorando desconocidos: {', '.join(unknown)}")
        picked = [r for r in picked if r in DEFAULT_ROLES]
    return picked or list(default)


# ── template rendering ─────────────────────────────────────────────────────-
def render_template(name: str, ctx: dict, out_path: Path) -> bool:
    src = TPL_BRAIN / f"{name}.template"
    if not src.exists():
        print(f"  [!] template faltante: {src} — salto {out_path.name}")
        return False
    text = src.read_text(encoding="utf-8")
    for k, v in ctx.items():
        text = text.replace("{{" + k + "}}", str(v))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    print(f"  [✓] {out_path.relative_to(REPO_ROOT)}")
    return True


# ── env file writer ─────────────────────────────────────────────────────────
def write_env(values: dict) -> None:
    existing = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, _, v = line.partition("=")
                existing[k.strip()] = v
    existing.update({k: v for k, v in values.items()})
    lines = [f"{k}={v}" for k, v in existing.items()]
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  [✓] {ENV_FILE.relative_to(REPO_ROOT)}")


# ── main ────────────────────────────────────────────────────────────────────
def main() -> int:
    print()
    print("═══ ai-agent-console — wizard de onboarding ═══")
    print()

    # ── step 0: license gate ───────────────────────────────────────────────
    existing_key = ""
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            if line.startswith("LICENSE_KEY="):
                existing_key = line.partition("=")[2].strip()
                break
    while True:
        key = prompt("0. License key (AAC1-...)", existing_key)
        if not key:
            print("  → se necesita una key para continuar. Escríbenos a support@blackwolfsec.io si no tienes.")
            continue
        result = lic.verify(key)
        if result.ok:
            payload = result.payload or {}
            exp = payload.get("expires_at") or "perpetua"
            print(f"  [✓] key válida — {payload.get('email','?')} · tier={payload.get('tier','?')} · expira={exp}")
            break
        print(f"  [✗] key inválida: {result.reason}")
        if result.reason.startswith("LICENSE_SECRET"):
            # Running without the secret we cannot verify at all — abort loudly.
            print("      El installer no trae el secret público para verificar keys. Reinstala desde el release oficial.")
            return 2

    assistant     = prompt("1. Nombre del asistente", "Alfred")
    biz_name      = prompt("2. Nombre del negocio", "")
    biz_mission   = prompt("3. Misión del negocio (1 frase)", "")
    operator      = prompt("4. Nombre del usuario principal", "Sir Alex")
    language      = prompt_choice("5. Idioma", ["es", "en"], "es")
    tone          = prompt_choice("6. Tono", ["formal", "familiar", "directo"], "directo")
    cadence       = prompt_choice("7. Cadencia del brain", ["15min", "30min", "60min"], "30min")
    timezone      = prompt("8. Timezone", "Europe/Madrid")
    tg_token      = prompt("9. Telegram Bot Token (enter para saltar)", "")
    tg_chat       = prompt("10. Telegram Chat ID (enter para saltar)", "")
    anthropic_key = prompt("11. Anthropic API Key (recomendado dejar vacío y ponerla luego en .env.local)", "")

    print("12. Roles iniciales a activar")
    active_roles = prompt_roles(["researcher", "watcher", "analyst"])

    peer_ip = ""
    if prompt_yes_no("13. ¿Conectar con otro Alfred vía Tailscale?", "n"):
        peer_ip = prompt("    IP Tailscale del peer", "")

    # ── render brain templates ──────────────────────────────────────────────
    ctx = {
        "ASSISTANT_NAME": assistant,
        "BUSINESS_NAME":  biz_name,
        "BUSINESS_MISSION": biz_mission,
        "OPERATOR_NAME":  operator,
        "LANGUAGE":       language,
        "TONE":           tone,
        "CADENCE":        cadence,
        "CADENCE_SEC":    CADENCE_MAP.get(cadence, 1800),
        "TIMEZONE":       timezone,
        "PEER_ALFRED_IP": peer_ip,
        "ACTIVE_ROLES":   ", ".join(active_roles),
    }

    print("\n→ renderizando templates")
    render_template("SOUL",           ctx, AGENT_DIR / "SOUL.md")
    render_template("VOICE",          ctx, AGENT_DIR / "VOICE.md")
    render_template("BRAIN",          ctx, AGENT_DIR / "BRAIN.md")
    render_template("TELEGRAM_VOICE", ctx, AGENT_DIR / "TELEGRAM_VOICE.md")

    # ── .env.local ──────────────────────────────────────────────────────────
    print("\n→ escribiendo .env.local")
    write_env({
        "LICENSE_KEY":         key,
        "ANTHROPIC_API_KEY":   anthropic_key,
        "TELEGRAM_BOT_TOKEN":  tg_token,
        "TELEGRAM_CHAT_ID":    tg_chat,
        "PEER_TOKEN":          os.urandom(16).hex() if not os.getenv("PEER_TOKEN") else os.environ["PEER_TOKEN"],
    })

    # ── state.json ──────────────────────────────────────────────────────────
    print("\n→ escribiendo agent/state.json")
    state = {
        "assistant_name": assistant,
        "business_name":  biz_name,
        "operator_name":  operator,
        "language":       language,
        "tone":           tone,
        "timezone":       timezone,
        "active_roles":   active_roles,
        "cadence":        cadence,
        "cadence_sec":    CADENCE_MAP.get(cadence, 1800),
        "peer_alfred_ip": peer_ip,
    }
    AGENT_DIR.mkdir(parents=True, exist_ok=True)
    (AGENT_DIR / "state.json").write_text(json.dumps(state, indent=2, ensure_ascii=False))
    print(f"  [✓] agent/state.json")

    # ── per-role scaffolding ────────────────────────────────────────────────
    print("\n→ asegurando carpetas de rol")
    for role in active_roles:
        role_dir = AGENT_DIR / "memory" / role
        role_dir.mkdir(parents=True, exist_ok=True)
        inbox = role_dir / "inbox.md"
        if not inbox.exists():
            inbox.write_text(f"# {role} inbox\n\n(vacío — escribe aquí para inyectar contexto al próximo ciclo)\n")
        print(f"  [✓] agent/memory/{role}/")

    # ── next steps ──────────────────────────────────────────────────────────
    print()
    print("═══ listo ═══")
    print()
    print("Siguientes pasos:")
    if not anthropic_key:
        print("  1. edita .env.local y pega tu ANTHROPIC_API_KEY")
    print("  2. arranca el HTTP bridge cross-VPS:")
    print("       ./venv/bin/python .claude/skills/agent-console/lib/bridge.py")
    print("  3. spawnea un agente:")
    print("       .claude/skills/agent-console/scripts/spawn_agent.sh researcher")
    print("  4. lee .claude/skills/agent-console/SKILL.md para el resto")
    print()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n[!] wizard cancelado")
        sys.exit(130)
