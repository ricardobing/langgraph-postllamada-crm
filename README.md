# Orquestador post-llamada con LangGraph

Recibe el evento de fin de cada llamada de un agente de voz inmobiliario (o un WhatsApp del lead), clasifica cómo
fue cruzando telefonía y transcripción, y decide las órdenes contra el CRM: reprogramar, tareas, recordatorios,
bajas y canal de respaldo. **Python + LangGraph + un modelo de OpenAI.**

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
cp .env.example .env        # OPENAI_API_KEY=… y MODELO=gpt-6-luna
python run.py eventos/01-call-ended-nuria.json      # con uv: uv run python run.py …
```

- **Contrato:** un evento por invocación y un proceso nuevo cada vez.
  - Salida por append en `salida/decisiones.jsonl` y `salida/ordenes.jsonl`.
  - Código de salida `0` si procesó el evento, distinto de `0` si no pudo.
- **Memoria entre procesos:** `salida/estado.sqlite`. Borrar `salida/` es empezar de cero.
- **Lote completo:** `python scripts/ejecutar_lote.py [carpeta_eventos] [carpeta_salida]`.
- **Pruebas:** `uv run pytest`.
- **Evaluación con el modelo real:** `uv run python eval/evaluar_llm.py [repeticiones]`.

**Modelo: `gpt-6-luna`.** Es el modelo rápido y barato de OpenAI, pensado para clasificación, y admite salida
estructurada con JSON Schema estricto.
- **Evaluación:** 105/105 aciertos, con 5 repeticiones de cada una de las 21 conversaciones y USD 0,012 en total.
- **Respaldo automático:** `gpt-4.1-mini`, por si el modelo principal no estuviera habilitado en la cuenta.
  Configurable con `MODELO_RESPALDO`.
- **Desarrollo:** `OPENAI_BASE_URL` permite apuntar el mismo SDK a otro servidor compatible. Desarrollé con DeepSeek
  V4.1 Flash, que dio 63/63.

## Qué hace cada pieza

| Pieza | Qué hace |
|---|---|
| `postllamada/grafo.py` | El grafo. Cada nodo devuelve solo lo que cambia; las aristas condicionales eligen el camino |
| `senalizacion.py` | 486, 603, 408/480, 5xx, buzón e IVR, **por reglas**. El modelo solo se llama si contestó una persona |
| `llm.py` + `prompts/` | El modelo **solo interpreta**: etiqueta, motivo, confianza y datos, validados con pydantic. Reintentos y respaldo |
| `ordenes.py` + `tiempo.py` | **El código decide**: órdenes, ventana de llamadas, plazos, días hábiles, intentos y reglas N1–N5 |
| `estado.py` | SQLite. Una transacción por evento con hechos, órdenes (clave de idempotencia única), bajas, rechazo de WhatsApp y recordatorios con su `reminder_id` |
| `jev.py` | *Opcional* (`JEV_ACTIVADO=1` + `OPENROUTER_API_KEY`): segunda opinión con Jev, un modelo de decisión que devuelve probabilidades. Actúa si el modelo duda o se cae. 20/20 en solitario, 0,4 s |

Las 14 decisiones de diseño, con la alternativa descartada, están en [`docs/decisiones.md`](docs/decisiones.md).

## Qué dejé fuera y por qué

- **Checkpointer de LangGraph para la memoria:** el estado cruza leads y se consulta. Con tablas propias es
  explícito, transaccional y se prueba directamente.
- **Outbox transaccional:** hoy, si el proceso muere justo entre el commit de SQLite y el append al `.jsonl`, esas
  líneas se pierden y una reentrega no las repetiría. En producción, las órdenes se marcarían «escritas» después
  del append.
- **Leer «ahora no puedo» como callback:** el catálogo dice que no lo es. Va a `otro` + revisión.
- **Llamadas reales al CRM, reintentos HTTP y trazas (LangSmith):** fuera de alcance (no hay red).

## Cómo verifiqué que hace lo que creo

1. **Escribí la salida esperada de los 16 eventos antes de programar** ([`docs/analisis.md`](docs/analisis.md)).
   Es el oráculo de los tests.
2. **94 tests** (pytest), con un LLM falso y determinista, sin red:
   - fechas y ventana: bordes, sábado, domingo, cambio de hora;
   - telefonía;
   - el lote completo, un grafo nuevo por evento sobre el mismo SQLite, contra el oráculo;
   - **toda salida validada contra `decision.schema.json` y los `requestBody` del OpenAPI**;
   - 30 casos extra que imitan el lote oculto: los ⚠ (603, callback fuera de ventana, descartado), intentos
     agotados, bajas, WhatsApp rechazado, segunda cortada, reentregas, otra organización, LLM caído;
   - **fuzz** con hypothesis: 150 secuencias aleatorias. Nunca rompe, una decisión por evento y ninguna orden
     duplicada;
   - `run.py` como proceso: códigos de salida y R8.
3. **El ejemplo resuelto sale idéntico**, órdenes y decisión, campo por campo (hay test).
4. **Evaluación con el modelo real** ([`docs/`](docs)): 21 conversaciones (8 del lote y 13 propias) pasadas por el
   grafo completo y repetidas.
   - `gpt-6-luna`: 105/105;
   - `deepseek-v4.1-flash`: 63/63;
   - Jev en solitario: 20/20.

Prompts del sistema: [`prompts/`](prompts). Cómo trabajé con el asistente de programación y dónde se equivocó:
[`docs/proceso-con-ia.md`](docs/proceso-con-ia.md).
