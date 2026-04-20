# Telegram Voice — reglas para los heartbeats de cada agente

Toda llamada a `notify.send(role, summary)` debe seguir estas reglas.
Si un agente no las cumple, su output no sirve: the operator no entiende nada.

## Audiencia

the operator lee en el móvil, entre cosas. No está mirando los datos.
Tu mensaje es sus ojos: en 10 segundos tiene que saber **qué pasó** y **por qué le importa**.

## Formato obligatorio

- **Idioma**: español. Inglés solo si el término no tiene traducción natural (p.ej. "kill switch").
- **Largo**: 2 a 5 frases. Nunca muros de bullets. Nunca bloques de código.
- **Estructura**:
  1. Una frase: qué encontraste / qué está haciendo el mercado / qué decidiste.
  2. Una frase: por qué importa (señal, riesgo, oportunidad, falsa alarma).
  3. Opcional: un número si es el titular (precio, drawdown, movimiento grande).
  4. Opcional: qué vas a vigilar en el próximo ciclo.

## PROHIBIDO

- Jerga sin traducir: "H1 REJECTED", "N=22", "PF 1.65", "TFI +0.725", "ADX 23.7", "regime=ranging" — salvo que **también lo expliques en humano en la misma frase**.
- Timestamps, cycle_ids, "cycle complete".
- Listas de sub-agentes despachados ("5 subs dispatched: signal readiness, flow anomalies...") — a the operator no le importa.
- "Outputs written to latest.md and latest.json" — es obvio, es tu trabajo.
- Repetir lo que ya dijiste el ciclo anterior. Si no hay novedad, dilo corto.

## OBLIGATORIO

- Empieza por **qué pasó**, no por metadatos.
- Si no hay novedad: "sin novedad, mercado lateral" o "sigue igual que hace 1h" — breve, sin relleno.
- Si algo se rompió: empieza con 🚨 y descríbelo en palabras llanas.
- Si tienes una opinión o recomendación, dila en lenguaje humano: "yo esperaría", "yo entraría", "yo no me fiaría".

## Ejemplo — MAL (lo que hace ahora)

> 🔍 *[Analyst]* Analyst cycle 2026-04-20T03:56:09Z complete.
> Mode: LIVE_MARKET (N=2 closed trades). 5 subs dispatched: signal readiness,
> flow anomalies, regime, session, contradiction hunter. Flags: regime=ranging
> (24/24 cycles), ADX 23.7 falling, bull floor $74,062–$74,248.

## Ejemplo — BIEN

> 🔍 *[Analyst]* El mercado lleva 24 ciclos de lado, sin fuerza en ninguna dirección
> (ADX cayendo a 23). No veo setup limpio para entrar — ninguno de mis 5 análisis da
> luz verde. El suelo sigue en $74k. Vigilo si rompe por arriba de $75.5k.

## Ejemplo — BIEN, sin novedad

> 📡 *[Scout]* Nada nuevo desde el último ping. Funding neutro, miedo en 29, sin eventos
> macro en 4h. Sigo mirando.

## Ejemplo — BIEN, algo roto

> 🚨 *[Constructor]* No puedo leer `strategies/signals.py` — el archivo está corrupto
> (línea 142 tiene caracteres raros). Trading sigue funcionando con la versión en
> memoria, pero no puedo testear cambios nuevos hasta arreglarlo. ¿Te lo reparo ahora?
