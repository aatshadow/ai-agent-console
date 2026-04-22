#!/usr/bin/env python3
"""Materialize a new agent role from a JSON spec.

Invoked by the brain (Alfred) after a conversational probe with the operator.
Given a validated spec, this writes:

  1. roles/<id>.md             — operational role doc with fenced prompt block
                                  that `spawn_agent.sh` extracts and pastes into
                                  Claude Code after `/loop <cadence>`
  2. config/roles.yaml          — appends a roles entry (creates file from the
                                  example if absent)
  3. agent/memory/<id>/inbox.md — scaffolds memory folder with a seed inbox

Reads the spec from a JSON file (``--spec path.json``) or stdin (``--stdin``).

Spec schema (all string unless noted):
    id                  slug (required, ^[a-z][a-z0-9_-]{1,31}$)
    mission             1–2 sentences describing what the role does each cycle
    cadence             e.g. "15m", "30m", "1h"
    scope               "read_only" | "read_write"   (default read_write)
    assistant_name      e.g. "Alfred"               (default from state.json)
    project_root_abs    absolute path               (default: detected AAC_HOME)
    inputs              list[str]  — file paths the role must read each cycle
    outputs             list[str]  — file paths the role writes each cycle
    steps               list[str]  — STEP 0 → N bodies (STEP 0 MUST be continuity;
                                    at least one step MUST be contradiction hunt)
    json_schema_keys    list[str]  — required keys in latest.json
    telegram_voice      1–3 sentences of tone guidance, role-specific
    session             tmux session name (default agent-<id>)
    extras              dict       — optional freeform notes appended to the doc

Exit codes:  0 ok · 2 validation error · 3 IO error
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import textwrap
from pathlib import Path

SLUG_RE = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")
CADENCE_RE = re.compile(r"^\d+(?:s|m|h)$|^dynamic$")

HERE = Path(__file__).resolve().parent
SKILL_DIR = HERE.parent
LIB_DIR = SKILL_DIR / "lib"


def detect_home() -> Path:
    env = os.getenv("AAC_HOME")
    if env:
        return Path(env).resolve()
    # scripts/ → agent-console/ → skills/ → .claude/ → <PROJECT_ROOT>
    return HERE.parent.parent.parent.parent.resolve()


# ── validation ──────────────────────────────────────────────────────────────

REQUIRED = ("id", "mission", "cadence", "inputs", "outputs",
            "steps", "json_schema_keys", "telegram_voice")


class SpecError(Exception):
    pass


def validate(spec: dict) -> None:
    missing = [k for k in REQUIRED if not spec.get(k)]
    if missing:
        raise SpecError(f"missing required fields: {', '.join(missing)}")
    if not SLUG_RE.match(spec["id"]):
        raise SpecError(f"id must match {SLUG_RE.pattern!r}")
    if not CADENCE_RE.match(spec["cadence"]):
        raise SpecError("cadence must be like '15m', '1h', '30s', or 'dynamic'")
    steps = spec["steps"]
    if not isinstance(steps, list) or len(steps) < 4:
        raise SpecError("need at least 4 steps (continuity, work, contradiction, output)")
    if not any("contradicc" in s.lower() or "contradict" in s.lower() for s in steps):
        raise SpecError("at least one step must be a contradiction hunt")
    if "step 0" not in steps[0].lower():
        raise SpecError("first step must start with 'STEP 0' (continuity read)")
    scope = spec.get("scope", "read_write")
    if scope not in ("read_only", "read_write"):
        raise SpecError("scope must be 'read_only' or 'read_write'")


# ── renderer ────────────────────────────────────────────────────────────────

DOC_TEMPLATE = """\
# {assistant} — {id_cap} ({session})

{mission}

**Loop**: `/loop {cadence}`
**Tmux**: `{session}`
**Scope**: {scope_human}

---

## Prompt — pegar después de `/loop {cadence}`

```
You are {assistant}, {id_cap} role. {scope_sentence}

MANDATORY VOICE RULE — applies to every notify.send(role, summary) call:
BEFORE composing summary_for_telegram, run:
  cat {project_root}/agent/TELEGRAM_VOICE.md
and follow it strictly. Plus role-specific voice:
  {telegram_voice}

Inputs to read at the start of every cycle:
{inputs_block}

Outputs to write every cycle (atomic — write all or none):
{outputs_block}

latest.json MUST contain these keys at minimum:
{schema_block}

{steps_block}

STEP FINAL — Schedule next cycle (MANDATORY)
  Use ScheduleWakeup with:
    delaySeconds: (derived from cadence {cadence})
    reason: "routine cycle — {id}"
    prompt: "Re-read {project_root}/roles/{id}.md and run the loop again."

If any STEP fails, still write latest.json with "error" populated and notify
with silent=False so Sir sees the failure.
```

---

## Memory layout

- `agent/memory/{id}/inbox.md`     — operator/peer injections between cycles
- `agent/memory/{id}/next_cycle.md` — continuity notes written by previous cycle
- `agent/memory/{id}/latest.md`     — human narrative of the last cycle
- `agent/memory/{id}/latest.json`   — machine-readable cycle summary
- `agent/memory/{id}/hypotheses.md` — append-only ideas under test

## Reglas

- Sin `summary_for_telegram` no se cierra el ciclo.
- Cada output lleva `cycle_id` ISO-8601 — nada de "ahora" relativo.
- Si no se encuentra contradicción, dilo explícitamente.
{extras}
"""


def _bullet_block(items: list[str], prefix: str = "  - ") -> str:
    return "\n".join(f"{prefix}{i}" for i in items) if items else f"{prefix}(none)"


def _schema_block(keys: list[str]) -> str:
    return "\n".join(f"  - {k}" for k in keys)


def _steps_block(steps: list[str]) -> str:
    # Each step is rendered as-is; operator is expected to author them with
    # STEP 0, STEP 1, … headings. We only indent-normalise.
    return "\n\n".join(textwrap.dedent(s).strip() for s in steps)


def render(spec: dict, *, project_root: Path, assistant: str) -> str:
    rid = spec["id"]
    session = spec.get("session") or f"agent-{rid}"
    scope = spec.get("scope", "read_write")
    scope_human = {
        "read_only":  "solo lee (no escribe en ningún sistema externo)",
        "read_write": "puede escribir a memoria y DB locales",
    }[scope]
    scope_sentence = {
        "read_only":  "You read only. You DO NOT modify external state.",
        "read_write": "You may write to agent/memory and agent.db only.",
    }[scope]
    extras = spec.get("extras") or {}
    extras_md = ""
    if extras:
        lines = ["\n## Notas adicionales\n"]
        for k, v in extras.items():
            lines.append(f"- **{k}**: {v}")
        extras_md = "\n".join(lines)
    return DOC_TEMPLATE.format(
        id=rid,
        id_cap=rid.capitalize(),
        session=session,
        cadence=spec["cadence"],
        assistant=assistant,
        project_root=str(project_root),
        mission=spec["mission"].strip(),
        scope_human=scope_human,
        scope_sentence=scope_sentence,
        telegram_voice=spec["telegram_voice"].strip(),
        inputs_block=_bullet_block(spec["inputs"]),
        outputs_block=_bullet_block(spec["outputs"]),
        schema_block=_schema_block(spec["json_schema_keys"]),
        steps_block=_steps_block(spec["steps"]),
        extras=extras_md,
    )


# ── writers ─────────────────────────────────────────────────────────────────

def write_role_doc(home: Path, spec: dict, assistant: str) -> Path:
    doc = render(spec, project_root=home, assistant=assistant)
    out = home / "roles" / f"{spec['id']}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        raise SpecError(f"role doc already exists: {out} — pick a different id or delete manually")
    out.write_text(doc, encoding="utf-8")
    return out


def append_roles_yaml(home: Path, spec: dict) -> Path:
    cfg_dir = home / "agent" / "config"
    cfg = cfg_dir / "roles.yaml"
    if not cfg.exists():
        # Bootstrap from the repo example if present
        example = home / "config" / "roles.yaml.example"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        if example.exists():
            cfg.write_text(example.read_text())
        else:
            cfg.write_text("defaults:\n  session_prefix: \"agent-\"\n  workdirs_root: \"workdirs\"\n\nroles: []\n")
    text = cfg.read_text()
    # Idempotence: if an entry with this id already exists, refuse.
    if re.search(rf"^\s*-\s*id:\s*{re.escape(spec['id'])}\s*$", text, re.MULTILINE):
        raise SpecError(f"config/roles.yaml already has id={spec['id']!r}")
    entry = f'\n  - id: {spec["id"]}\n    cadence: "{spec["cadence"]}"\n'
    if spec.get("session"):
        entry += f'    session: {spec["session"]}\n'
    # Ensure the file ends with a newline and has a `roles:` key.
    if "roles:" not in text:
        text += "\nroles:\n"
    if not text.endswith("\n"):
        text += "\n"
    text += entry
    cfg.write_text(text)
    return cfg


def scaffold_memory(home: Path, rid: str) -> Path:
    mem = home / "agent" / "memory" / rid
    mem.mkdir(parents=True, exist_ok=True)
    inbox = mem / "inbox.md"
    if not inbox.exists():
        inbox.write_text(f"# {rid} inbox\n\n(vacío — escribe aquí para inyectar contexto al próximo ciclo)\n")
    (mem / "next_cycle.md").touch(exist_ok=True)
    return mem


# ── assistant name from state.json ─────────────────────────────────────────

def read_assistant(home: Path) -> str:
    state = home / "agent" / "state.json"
    if state.exists():
        try:
            return json.loads(state.read_text()).get("assistant_name") or "Alfred"
        except Exception:
            pass
    return "Alfred"


# ── main ────────────────────────────────────────────────────────────────────

def load_spec(args) -> dict:
    if args.stdin:
        raw = sys.stdin.read()
    elif args.spec:
        raw = Path(args.spec).read_text()
    else:
        raise SpecError("need --spec PATH or --stdin")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise SpecError(f"spec is not valid JSON: {e}")


def main() -> int:
    p = argparse.ArgumentParser(description="Materialize a new agent role from a JSON spec.")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--spec", help="path to JSON spec file")
    src.add_argument("--stdin", action="store_true", help="read JSON spec from stdin")
    p.add_argument("--dry-run", action="store_true", help="validate and render, don't write")
    args = p.parse_args()

    try:
        spec = load_spec(args)
        validate(spec)
    except SpecError as e:
        print(f"spec error: {e}", file=sys.stderr)
        return 2

    home = Path(spec.get("project_root_abs") or detect_home())
    assistant = spec.get("assistant_name") or read_assistant(home)

    if args.dry_run:
        print(render(spec, project_root=home, assistant=assistant))
        return 0

    try:
        role_path = write_role_doc(home, spec, assistant)
        cfg_path = append_roles_yaml(home, spec)
        mem_path = scaffold_memory(home, spec["id"])
    except SpecError as e:
        print(f"write error: {e}", file=sys.stderr)
        return 2
    except OSError as e:
        print(f"io error: {e}", file=sys.stderr)
        return 3

    print(json.dumps({
        "ok": True,
        "id": spec["id"],
        "role_doc": str(role_path),
        "config": str(cfg_path),
        "memory": str(mem_path),
        "next": [
            f"revisar: cat {role_path}",
            f"lanzar:  .claude/skills/agent-console/scripts/spawn_agent.sh {spec['id']}",
        ],
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
