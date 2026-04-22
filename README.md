# AI Agent Console

> Self-hosted multi-agent orchestration. Run many specialised Claude Code agents in parallel on your own VPS, coordinated through a single Telegram chat.

## What it is

One command installs a system where you have:

- **N Claude Code agents** running in isolated tmux sessions, each with its own role, cadence, and memory.
- **A Telegram bot** as your single control surface — spawn, kill, respawn, status, ask, all from your phone.
- **Folder-driven coordination** — agents talk to each other by writing to shared memory folders, not by sharing prompts. You can inject orders, bug reports, or priorities into any agent's inbox and the next cycle picks them up.
- **A watchdog** that alerts you when any agent dies, zombies, or stops cycling.
- **A voice layer** that forces every agent's Telegram output to be plain, human Spanish — no jargon, no data dumps.

You bring: a VPS, a Claude Code subscription, a Telegram bot, a license key. The wizard handles the rest.

## Why this exists

The usual problem running Claude Code long-lived:

- SSH closes → session lost.
- Multiple `claude` instances in the same project → they fight over the scheduler lock, most go zombie.
- Agents report in dense technical output you can't parse on your phone.
- No idea when one dies. No way to revive from your pocket.
- No coordination between specialised agents.

This project is the full fix.

## Architecture

```
             ┌─────────────────────────────────┐
             │  Telegram — your single surface │
             └──────────────┬──────────────────┘
                            │
                    ┌───────┴────────┐
                    │  brain (Claude) │  ← long-running, conversational
                    └───────┬────────┘
                            │ tool calls
      ┌──────────────┬──────┴──────┬──────────────┐
      ▼              ▼             ▼              ▼
  ┌───────┐     ┌────────┐    ┌────────┐     ┌──────────┐
  │role A │     │ role B │    │ role C │ ... │ watchdog │
  │ tmux  │     │  tmux  │    │  tmux  │     │  timer   │
  └───┬───┘     └────┬───┘    └────┬───┘     └────┬─────┘
      │              │             │              │
      └──────────────┴─────┬───────┴──────────────┘
                           ▼
                  shared memory folders
                (inbox / next_cycle / latest)
```

Each agent lives in its own isolated workdir — own `.claude/` config, own scheduler lock. They read and write to shared memory folders under `agent/memory/<role>/`, so you can inject context into any of them between cycles without restart.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/aatshadow/ai-agent-console/main/install.sh | bash
```

The wizard asks you:

1. **License key** — the one you got when you bought.
2. **Telegram bot token** — create one at `@BotFather`, paste.
3. **Bot chat setup** — send `/start` to your bot, the wizard captures your chat_id.
4. **API keys** — opens `.env` in your `$EDITOR`. Fill in Anthropic, OpenAI, any others your roles need.
5. **Role selection** — pick from templates (Researcher, Designer, Watcher, Chat) or start empty.

Three minutes later you have a running multi-agent system.

## Pricing

**Pago único. Una licencia. Es tuya para siempre.**

No suscripciones. No SaaS. No phone-home en normal operation — la key se verifica localmente por firma.

Cuando compras, recibes una license key por email. Pegas la key durante la instalación. Los agents la verifican al arrancar. Fin.

Comprar: *(landing en preparación)*

## Core pieces

| File | What it does |
|------|-------------|
| `install.sh` | One-command installer — clones, creates venv, runs wizard |
| `wizard.py` | Interactive setup — license gate, Telegram, `.env.local`, roles |
| `.claude/skills/agent-console/SKILL.md` | Skill manifest the brain reads to know how to orchestrate |
| `.../scripts/spawn_agent.sh` | Spawn / respawn / list / zombie-sweep the tmux sessions |
| `.../scripts/kill_agent.sh` | Stop a role |
| `.../scripts/watchdog.py` | Detect dead / zombie / stale / pristine agents, notify on state change |
| `.../scripts/create_role.py` | Materialize a new role from a JSON spec (validates, writes doc + config + memory) |
| `.../CREATE_ROLE.md` | Conversational protocol the brain follows when Sir asks for a new role |
| `.../lib/notify.py` | Telegram send helper — every role imports this |
| `.../lib/taskmaster.py` | Shared append-only task board across operator + all agents |
| `.../lib/license.py` | Offline HMAC license verification |
| `.../lib/bridge.py` | FastAPI bridge for cross-VPS Alfred-to-Alfred calls |
| `.../templates/brain/TELEGRAM_VOICE.md.template` | Canonical Telegram voice rules rendered into `agent/` |
| `.../templates/roles/*.md` | Role blueprints (researcher, designer, watcher, analyst, extractor, changewatcher) |
| `tools/issue_key.py` | Mint / verify license keys (needs `LICENSE_SECRET`) |

## Status

**Core shipped.** Design battle-tested on a live 9-agent crypto-trading stack (`/opt/wolftrader`) running for weeks. The extraction is usable today on a fresh VPS.

Done:

- [x] Repackaged as a Claude Code skill (`.claude/skills/agent-console/`)
- [x] `install.sh` + `wizard.py` (stdlib only, license gate as step 0)
- [x] Skill libs: `taskmaster`, `journal`, `db`, `notify`, `bridge`, `config`, `license`
- [x] Skill scripts: `spawn_agent.sh`, `kill_agent.sh`, `list_agents.sh`, `watchdog.py`, `create_role.py`
- [x] Role templates: researcher, designer, watcher, analyst, extractor, changewatcher
- [x] Brain templates: SOUL, VOICE, BRAIN, TELEGRAM_VOICE
- [x] Cross-VPS bridge (FastAPI, `X-Peer-Token`, CORS to Tailscale `100.64.0.0/10`)
- [x] Conversational role-creation flow (`CREATE_ROLE.md` guides the brain; `create_role.py` materializes)
- [x] Offline HMAC license verification + `tools/issue_key.py` keygen

Remaining:

- [ ] Whop webhook to auto-issue keys on purchase (today: manual via `tools/issue_key.py`)
- [ ] Landing page + sales copy
- [ ] Demo video

## License

MIT for the code. Running a full installation requires a valid license key issued at purchase.

## Credits

Built by [@aatshadow](https://github.com/aatshadow) with Claude.
