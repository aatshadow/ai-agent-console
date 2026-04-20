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
| `wizard.py` | Interactive setup — license, Telegram, .env, roles |
| `bin/respawn_agent.sh` | Spawn, kill, respawn, status. The primitive |
| `bin/watchdog.py` | Every 5min, alerts on dead / zombie / stale agents |
| `agent/brain.py` | Telegram-facing conversational agent with tool use |
| `agent/notify.py` | Telegram send helper — every role uses this |
| `agent/license.py` | Offline license key verification |
| `agent/TELEGRAM_VOICE.md` | Canonical rules all agents follow for Telegram output |
| `roles/templates/` | Role prompt templates you clone when adding agents |

## Status

**🚧 Currently being extracted from a parent project.** The design is battle-tested on a live 9-agent crypto-trading stack that has been running for weeks. This repo is the clean generic version.

Extraction TODO:

- [ ] Strip all trading-specific code (only the orchestration pattern)
- [ ] Write `install.sh`
- [ ] Write `wizard.py` with Telegram bootstrap + .env editor
- [ ] Write `agent/license.py` with HMAC-signed key verification
- [ ] Generic role templates (Researcher, Designer, Watcher, Chat — no trading)
- [ ] Whop integration for automatic key issuance on purchase
- [ ] Landing page + copy
- [ ] Demo video

## License

MIT for the code. Running a full installation requires a valid license key issued at purchase.

## Credits

Built by [@aatshadow](https://github.com/aatshadow) with Claude.
