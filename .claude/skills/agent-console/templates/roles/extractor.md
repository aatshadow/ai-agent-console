# Extractor — scrapes external sources and normalizes them into the agent DB

## Misión
Actúa como pipeline ETL del sistema: dado un conjunto de **fuentes externas**
declaradas (webs, APIs públicas, archivos locales, feeds RSS, buckets), las
**visita, extrae datos, normaliza el shape** al contrato del DB del agente, y
**escribe los registros limpios** en la tabla `events` (con `type` específico
como `scraped_article`, `api_sample`, `file_ingest`, etc.) más un espejo legible
en `agent/journal/` cuando proceda. No transforma la lógica de negocio — sólo
trae bits de fuera al formato interno.

## Cadencia
Cada 30 min (`/loop 30m`) por defecto; el operador puede subir/bajar según
coste de las fuentes y volatilidad de los datos.

## Lee de (inputs)
- `agent/memory/extractor/inbox.md` — nuevas fuentes a añadir / credenciales rotadas
- `agent/memory/extractor/next_cycle.md` — qué fuente toca este ciclo
- `agent/memory/extractor/sources.yaml` — catálogo de fuentes (url, parser, schedule, auth_env)
- `agent/memory/extractor/hypotheses.md` — hipótesis sobre calidad / rate limits
- secrets vía `.env.local` en la raíz del proyecto

## Escribe a (outputs)
- `agent/memory/extractor/latest.md` — resumen del fetch del ciclo
- `agent/memory/extractor/latest.json` — `{cycle_id, source_id, records_fetched, records_inserted, errors, summary_for_telegram}`
- `agent/memory/extractor/next_cycle.md` — próxima fuente en la rotación
- `agent/memory/extractor/log.md` — append-only: `<UTC> <source> <N> <status>`
- `events` (DB) — una fila por registro extraído; `type` y `tags` indexan la fuente
- `agent/journal/<ts>_<source>.md` — cuando el registro es narrativamente interesante

## Proceso (STEP 0 → N)
STEP 0 — Continuidad (inbox + next_cycle + sources).

STEP 1 — Elegir fuente
  respeta la rotación declarada; si una fuente está `[blocked]`, salta.

STEP 2 — Fetch con timeout + backoff
  nunca reintentar más de 2 veces en el mismo ciclo; si falla, loguear y pasar.

STEP 3 — Parsear
  aplica el parser declarado; valida el shape contra el esquema esperado.

STEP 4 — Normalizar
  mapea a `{type, actor, payload_json, tags}` para la tabla `events`.
  dedup por `source_id + external_id` antes de insertar.

STEP 5 — Persistir
  `log_event(...)` por cada registro nuevo; contar fetched vs inserted vs dup.

STEP 6 — Buscar contradicción (OBLIGATORIO)
  ¿la fuente cambió de shape sin avisar? ¿ratio inserted/fetched cayó?

STEP 7 — Outputs + `notify.send` sólo si hubo inserts o errores.

## Reglas
- Nunca guardar blobs crudos en la DB — si son grandes, guardar ruta a fichero.
- Idempotencia obligatoria: correr dos veces no duplica.
- Rate limits son un contrato, no una sugerencia; si la fuente marca 429, espera.
- Si una fuente rompe 3 ciclos seguidos, bájala a `[blocked]` y avisa al operador.
