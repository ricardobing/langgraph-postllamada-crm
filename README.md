# Orquestador post-llamada con LangGraph

Recibe el evento de fin de cada llamada de un agente de voz inmobiliario (o un WhatsApp del lead), clasifica cómo
fue cruzando telefonía y transcripción, y decide las órdenes contra el CRM: reprogramar, tareas, recordatorios,
bajas y canal de respaldo. **Python + LangGraph + un modelo de OpenAI.** La IA interpreta; el código decide.

```
START → preparar ─┬─ otra_organizacion ───────────────────────────────┐
                  ├─ reentrega ───────────────────────────────────────┤
                  ├─ mensaje (cancela recordatorios) ─────────────────┤
                  └─ clasificar_senalizacion ─┬─ planificar_llamada ──┤
                                              └─ leer_conversacion ┘  ▼
                                                       registrar_y_emitir → END
```

## Cómo se ejecuta

```bash
uv sync                     # o: pip install -r requirements.txt   (Python ≥ 3.12)
cp .env.example .env        # completar OPENAI_API_KEY (MODELO ya viene en gpt-5.6-luna)
python run.py eventos/01-call-ended-nuria.json      # con uv: uv run python run.py …
```

- **Contrato:** un evento por invocación y un proceso nuevo cada vez. Append en `salida/decisiones.jsonl` y
  `salida/ordenes.jsonl`. Código `0` si procesó el evento; si no pudo, `2` (ilegible), `3` (no cumple
  `evento.schema.json`) o `1` (error inesperado), y en esos casos no deja línea de decisión.
- **Memoria entre procesos:** `salida/estado.sqlite`. Borrar `salida/` es empezar de cero.
- **Lote completo:** `python scripts/ejecutar_lote.py [carpeta_eventos] [carpeta_salida]` (borra la carpeta de salida).
- **Pruebas:** `uv run pytest`. **Evaluación con el modelo real:** `uv run python eval/evaluar_llm.py [repeticiones]
  [--dificiles] [--jev rapido]` (reescribe los informes de `docs/evaluaciones/`).
- **Modelo: `gpt-5.6-luna`, con `gpt-6-luna` de respaldo** (otro modelo de OpenAI, misma clave; `MODELO_RESPALDO`
  lo cambia). Empatan en casi todo, pero en la conversación más ambigua `gpt-5.6-luna` acierta 86 % contra 62 %, por
  USD 0,00015 más por llamada: [`docs/evaluaciones/comparacion-modelos.md`](docs/evaluaciones/comparacion-modelos.md).
- **Desarrollo:** medí todo vía OpenRouter con el mismo SDK (`OPENAI_BASE_URL`, `MODELO=openai/gpt-5.6-luna`). Sin
  `OPENAI_BASE_URL` el cliente va directo a `api.openai.com`; ese camino lo probé hasta la autenticación, no con una
  clasificación real. Si el modelo no responde, la llamada va a revisión humana y el proceso sigue.
- **Extra opcional, apagado por defecto: Jev** (`JEV_ACTIVADO=1` + `OPENROUTER_API_KEY`). Medido: aporta velocidad,
  no acierto, así que queda apagado. Ver [`docs/jev.md`](docs/jev.md).

Qué hace cada pieza y las 15 decisiones de diseño con su alternativa descartada: [`docs/decisiones.md`](docs/decisiones.md).

## Qué dejé fuera y por qué

- **Checkpointer de LangGraph:** guarda el estado de *un hilo* para reanudarlo, y acá cada evento sería un hilo
  distinto. La memoria que hace falta cruza eventos, se consulta (intentos, bajas, recordatorios, reentregas) y se
  tiene que guardar en la misma transacción que las órdenes. Con tablas SQLite propias es explícito y transaccional.
- **Outbox transaccional:** la salida se escribe después del commit de SQLite. Si el proceso muere entre el commit y
  los appends, esas líneas se pierden; si muere entre el de órdenes y el de la decisión, quedan órdenes sin decisión.
  En los dos casos una reentrega no las repite. En producción: marcar las órdenes «escritas» después del append.
- **Llamadas reales al CRM, reintentos HTTP y trazas (LangSmith):** fuera de alcance (no hay red).

## Cómo verifiqué que hace lo que creo

1. **Escribí la salida esperada de los 16 eventos antes de programar** ([`docs/analisis.md`](docs/analisis.md)).
   Es el oráculo de los tests.
2. **132 tests** (pytest), con un LLM falso y determinista, sin red: fechas y ventana (bordes, sábado, domingo,
   cambio de hora), telefonía, el lote completo contra el oráculo, **toda salida validada contra
   `decision.schema.json` y los `requestBody` del OpenAPI**, 43 casos extra que imitan el lote oculto (los ⚠,
   callbacks con y sin día, intentos agotados, bajas, WhatsApp rechazado, segunda cortada, reentregas, otra
   organización, LLM caído), fuzz con 150 secuencias aleatorias, `run.py` como proceso (códigos de salida y R8) y Jev.
3. **El ejemplo resuelto sale idéntico byte a byte** (hay test que corre `run.py` y compara los ficheros).
4. **Evaluación con el modelo real** ([`docs/evaluaciones/`](docs/evaluaciones)): 21 conversaciones × 5 y un set
   difícil de 14 × 10 que lleva al límite los «pares que se parecen». Encontró un error del prompt (un tercero que
   decía «no llamen más a este número» salía como baja) y lo corregí.
5. **Auditoría final requisito por requisito** contra el enunciado, los casos, los esquemas y la config, con sondeos
   de variantes (horas, días, cambio de hora, SIP y AMD, intentos, reentregas). Encontró que un callback con hora
   pero sin día («llámame a las cinco») perdía la hora; está corregido y cubierto por tests.

Prompts del sistema: [`prompts/`](prompts). Cómo trabajé con el asistente de programación y dónde se equivocó:
[`docs/proceso-con-ia.md`](docs/proceso-con-ia.md).
