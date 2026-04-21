---
name: agent-console
description: Spawnea, gestiona y orquesta agentes de propósito general (researcher, designer, watcher, analyst, extractor, changewatcher) en tmux con memoria folder-driven, taskmaster compartido, journal post-evento, DB SQLite, bridge HTTP cross-VPS vía Tailscale. Úsala cuando el usuario quiera crear/listar/matar agentes, delegar tareas entre agentes, añadir un rol nuevo, consultar estado del team, o conectar dos instancias de Alfred.
---

# Agent Console Skill

## Qué hace
Meta-sistema para correr N agentes Claude Code especializados en paralelo en una VPS. Cada rol vive en su propia sesión tmux, ciclando en `/loop <cadencia>`, coordinándose por archivos compartidos (no por prompts inyectados). La skill expone las librerías, scripts, templates y el bridge HTTP para que un "brain" conversacional pueda spawnear roles, asignarles tareas, vigilarlos y hablar con otros Alfred en otras VPS.

## Cuándo invocarla
- "crea un agente researcher / designer / watcher / ..."
- "lista los agentes / estado del team / quién está vivo"
- "mata / respawn el agente X"
- "asigna esta tarea a Y" (taskmaster)
- "añade un rol nuevo llamado Z"
- "conecta con el Alfred de la otra VPS"

## Scripts disponibles
- `scripts/spawn_agent.sh <role> [cadence]` — levanta una tmux session con el loop del rol (también acepta `--list`, `--zombies`, `--dry-run <role>`)
- `scripts/list_agents.sh` — lista sessions activas (alias de `spawn_agent.sh --list`)
- `scripts/kill_agent.sh <role>` — detiene el agente
- `scripts/watchdog.py` — daemon que detecta dead/zombie/stale/pristine y avisa por Telegram solo en cambios de estado

## Librerías importables
Todas en `.claude/skills/agent-console/lib/`:
- `lib.taskmaster` — `create_task(title, owner, source, ...)`, `update_task(id, {...})`, `list_tasks(owner=..., status=...)`
- `lib.journal` — `write_entry(event, context, analysis)` — markdown por día en `agent/journal/`
- `lib.db` — `init_db()`, `log_event(type, actor, payload)`, `log_decision(actor, action, reasoning)`, `query_events(since=...)`
- `lib.notify` — `send(role, message, silent=False)` → Telegram con emoji prefix por rol
- `lib.bridge` — FastAPI app (`/api/alfred/ping|state|ask|push_event`) con auth `X-Peer-Token`
- `lib.config` — `load_config()`, `load_roles()` — lee `config/config.yaml` y `config/roles.yaml`

Import desde el brain del negocio (importlib por path, o `sys.path.insert`):
```python
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(".claude/skills/agent-console/lib").resolve()))
from taskmaster import create_task
from notify import send
```

## Patrón folder-driven (crítico)
Cada rol lee su `agent/memory/<role>/inbox.md` y `next_cycle.md` al inicio de cada ciclo. **Nunca se le inyecta contexto por prompt.** Cualquier comunicación inter-agente (o del operador) va por archivos — el operador puede escribir en el inbox de cualquier rol entre ciclos y el siguiente ciclo lo recoge sin restart.

Outputs del ciclo a:
- `agent/memory/<role>/latest.md`   — narrativa humana del último ciclo
- `agent/memory/<role>/latest.json` — heartbeat estructurado (con `cycle_id` ISO)
- `agent/memory/<role>/next_cycle.md` — notas que quieres leer la próxima vez
- `agent/memory/<role>/hypotheses.md` — ideas acumuladas a validar

## Cómo añadir un rol nuevo
1. Crea `agent/agents/<new_role>.md` con el prompt del loop (bloque ```delimitado```)
2. Crea `agent/memory/<new_role>/` con `inbox.md` vacío
3. Añade entrada en `config/roles.yaml` con `id: <new_role>` y `cadence: <Xm|Xh>`
4. `scripts/spawn_agent.sh <new_role>`
5. Añade el id a `agent/state.json.active_roles`

## Bridge cross-VPS
Si la VPS tiene Tailscale, `lib/bridge.py` expone endpoints para que otro Alfred (en otra VPS) consulte estado o pase mensajes:

```
GET  /api/alfred/ping         → {ok, name, version}
GET  /api/alfred/state        → state.json + last_cycle_ts por rol
POST /api/alfred/ask          → encola pregunta en memory/inbox_peer.md
POST /api/alfred/push_event   → loga evento a journal + DB
```

Auth vía header `X-Peer-Token` que debe coincidir con `PEER_TOKEN` (env var). CORS abierto al rango Tailscale `100.64.0.0/10`.

Arranque standalone:
```
./venv/bin/python .claude/skills/agent-console/lib/bridge.py
```

El brain del negocio procesa `inbox_peer.md` en su siguiente ciclo folder-driven — el bridge nunca invoca al modelo.

## Estados persistidos
- `agent/memory/**`         — folder-driven memory (markdown + json)
- `agent/journal/YYYY-MM-DD.md` — markdown post-evento
- `agent/data/agent.db`     — SQLite con `events`, `decisions`, `tasks`, `performance`
- `agent/state.json`        — runtime state (assistant_name, active_roles, cadence_sec, peer_alfred_ip, ...)
- `.env.local`              — `ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `PEER_TOKEN`

## Debugging
- Logs de un agente: `tmux capture-pane -t agent-<role> -p | tail -200`
- Estado del team: `scripts/spawn_agent.sh --list`
- Dry-run watchdog: `./venv/bin/python scripts/watchdog.py --dry-run`
- Estado DB: `sqlite3 agent/data/agent.db ".tables"`
- Test notify: `./venv/bin/python -m lib.notify`
- Test bridge (local): `curl -H "X-Peer-Token: $PEER_TOKEN" http://localhost:8787/api/alfred/ping`

## Instalación
Desde una VPS fresca Ubuntu/Debian:
```bash
curl -fsSL https://raw.githubusercontent.com/aatshadow/ai-agent-console/main/install.sh | bash
```
O en local: `./install.sh` (flags: `--no-tailscale`, `--no-wizard`, `--quiet`). El installer deja el wizard (`wizard.py`) corriendo para configurar asistente, negocio, Telegram y roles iniciales.
