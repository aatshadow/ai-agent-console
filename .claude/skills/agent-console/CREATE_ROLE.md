# Crear un rol nuevo (flujo conversacional)

Cuando Sir pide "crea un agente que haga X" **no dispares preguntas genéricas de wizard**. Eres un arquitecto: conduce una conversación breve, construye un borrador a la vista, y materialízalo con `create_role.py` solo cuando Sir apruebe.

## Principios

1. **Indaga, no interrogues.** Cada pregunta sale de lo que Sir ya dijo. Si mencionó "emails fríos", no vuelvas a preguntar qué hace — pregunta qué es un lead válido para él.
2. **Muestra el documento mientras lo construyes.** Cada 2–3 turnos, manda por Telegram un bloque markdown con las secciones ya rellenadas y las que faltan marcadas `TODO`. Sir tiene que poder verlo y corregirlo en la pantalla.
3. **No escribas archivos hasta el final.** El helper se llama una sola vez con el spec completo.
4. **Copia la estructura de los roles battle-tested**, no la inventes. `/opt/wolftrader/agent/agents/*.md` son la referencia (si tienes acceso) — o `roles/<existing>.md` del proyecto actual.

## El spec que tienes que rellenar

```json
{
  "id": "<slug>",               // [a-z][a-z0-9_-]{1,31}
  "mission": "<1-2 frases>",    // qué hace en cada ciclo, concreto
  "cadence": "<15m|30m|1h|…>",
  "scope": "read_only|read_write",
  "inputs":  ["agent/memory/<id>/inbox.md", "..."],
  "outputs": ["agent/memory/<id>/latest.md", "..."],
  "steps": [
    "STEP 0 — Continuidad: cat agent/memory/<id>/next_cycle.md …",
    "STEP 1 — …",
    "STEP N — Buscar contradicción (OBLIGATORIO): …",
    "STEP N+1 — Escribir outputs + notify.send(…)"
  ],
  "json_schema_keys": ["cycle_id", "mode", "summary_for_telegram", "..."],
  "telegram_voice": "<1-3 frases de tono específico para este rol>",
  "session": "agent-<id>"       // opcional
}
```

## Guion de la conversación (7 rondas máx)

Cada ronda = 1 mensaje de Telegram tuyo → 1 respuesta de Sir. No mezcles preguntas.

| # | Pregunta | Qué rellena |
|---|---|---|
| 1 | "¿Qué hace este agente en una frase y con qué cadencia quieres que corra?" | `mission`, `cadence` |
| 2 | "¿Qué datos o archivos necesita leer al empezar cada ciclo? (incluye inbox del rol)" | `inputs` |
| 3 | "¿Qué deja escrito al final? (latest.md, latest.json, algo más?)" | `outputs`, primeros `json_schema_keys` |
| 4 | "Cuéntame el trabajo del ciclo por pasos — 3 a 6 pasos. Voy añadiendo STEP 0 continuidad y STEP final de output yo." | `steps` (cuerpo) |
| 5 | "¿Qué tipo de contradicciones debería cazar este rol? (pasado vs hoy, este agente vs otro, plan vs realidad...)" | añade el STEP obligatorio a `steps` |
| 6 | "¿Puede este rol escribir en sistemas externos, o es read-only?" | `scope` |
| 7 | "Para Telegram: ¿cómo quieres que suenen sus mensajes? Hay alguna regla específica (formato, longitud, cosas a evitar)?" | `telegram_voice` |

Tras la ronda 3, manda el primer **draft parcial** en Telegram (fenced code block con el doc medio hecho). Tras la 7, manda el **draft final** y pregunta: *"¿lo creo así o cambias algo?"*

## Cuando Sir diga "créalo"

1. Escribe el spec a un archivo temporal: `/tmp/role_<id>.json`
2. Ejecuta:
   ```bash
   .claude/skills/agent-console/scripts/create_role.py --spec /tmp/role_<id>.json
   ```
3. Si el helper devuelve error de validación, léele el error a Sir, pregúntale lo que falte, y reintenta. No inventes.
4. Al éxito: `notify.send("<Id>", "Rol creado. Para lanzarlo: scripts/spawn_agent.sh <id>")` y espera confirmación antes de spawnear.

## Anti-patrones (no hagas esto)

- ❌ Preguntar "¿y el timezone?" o "¿tono formal o familiar?" — eso ya está en `state.json`.
- ❌ Preguntar las 7 cosas en un bombardeo.
- ❌ Escribir `roles/<id>.md` a mano — usa siempre el helper, valida por ti.
- ❌ Saltarte el contradiction hunt "porque este rol es simple". Sin él, el agente repite loops sin aprender.
- ❌ Dejar `steps` en prosa suelta — cada paso debe ser accionable, con verbo imperativo y archivo/comando concreto.
