"""agent-console skill — shared library primitives.

This package exposes the core building blocks used by every role:

  - config     : YAML loaders for agent/config/{config,roles}.yaml
  - notify     : Telegram sink with local-log fallback
  - taskmaster : append-only shared task board (create/update/list)
  - journal    : markdown event journal (one file per event)
  - db         : SQLite store (events, decisions, performance)

All modules assume this skill lives at
`.claude/skills/agent-console/lib/` inside the adopting project, and
resolve the adopting project's root five parents up from this file.
"""
