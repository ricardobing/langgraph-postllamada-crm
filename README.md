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
cp .env.example .env        # completar OPENAI_API_KEY (MODELO ya viene en gpt-6-luna)
python run.py eventos/01-call-ended-nuria.json      # con uv: uv run python run.py …
```

- **Contrato:** un evento por invocación y un proceso nuevo cada vez.
  - Salida por append en `salida/decisiones.jsonl` y `salida/ordenes.jsonl`.
  - Código de salida `0` si procesó el evento, distinto de `0` si no pudo.
- **Memoria entre procesos:** `salida/estado.sqlite`. Borrar `salida/` es empezar de cero.
- **Lote completo:** `python scripts/ejecutar_lote.py [carpeta_eventos] [carpeta_salida]`.
- **Pruebas:** `uv run pytest`.
- **Evaluación con el modelo real:** `uv run python eval/evaluar_llm.py [repeticiones] [--dificiles] [--jev rapido]`.

**Modelo: `gpt-5.6-luna`, con `gpt-6-luna` de respaldo.** Comparé los dos con salida estructurada (JSON Schema
estricto) sobre las mismas conversaciones, pasadas por el grafo completo:

| | Set normal (21 × 5) | Set difícil (14 × 10) | Caso más ambiguo (d04) | Latencia | Costo por llamada |
|---|---|---|---|---|---|
| `gpt-5.6-luna` | 105/105 | 138/140 | **43/50 (86 %)** | ~3,2 s | ~USD 0,00027 |
| `gpt-6-luna` | 104/105 | 138/140 | 28/45 (62 %) | ~3,1 s | ~USD 0,00012 |

- **Por qué este:** empatan en casi todo, pero donde la conversación es ambigua `gpt-5.6-luna` acierta más. La
  diferencia de costo son unos 15 centavos cada 1.000 eventos: elijo acierto. Detalle en
  [`docs/evaluaciones/comparacion-modelos.md`](docs/evaluaciones/comparacion-modelos.md).
- **Por qué ese respaldo:** es otro modelo de OpenAI, así que funciona con la misma clave si el principal falla o no
  está habilitado en la cuenta. Configurable con `MODELO_RESPALDO` (vacío = sin respaldo).
- **Desarrollo:** `OPENAI_BASE_URL` apunta el mismo SDK a otro servidor compatible. Desarrollé con OpenRouter
  (`MODELO=openai/gpt-5.6-luna`) para medir el costo de cada prueba.

**Extra opcional, apagado por defecto: Jev.** Me gusta probar lo nuevo que va saliendo en proyectos reales y medir si
aporta de verdad. Jev es un modelo de decisión (elige una opción y da su probabilidad). Se activa con
`JEV_ACTIVADO=1` + `OPENROUTER_API_KEY`:
- **`JEV_MODO=rapido`:** Jev decide primero. Si está muy seguro de una baja, un descarte o un número equivocado, no
  se llama al modelo. Resultado: un 33–41 % menos de llamadas, esos eventos en 0,5 s en vez de ~3,5 s, 12–24 % menos
  de costo y el mismo acierto.
- **`JEV_MODO=segunda_opinion`:** Jev solo actúa si el modelo duda o se cae. En 350 eventos no hizo falta ni una vez.
- **Conclusión medida:** aporta velocidad, no acierto. En un proceso post-llamada eso no importa, así que queda
  apagado. Mediciones, tests y cuándo convendría: [`docs/jev.md`](docs/jev.md).

## Qué hace cada pieza

| Pieza | Qué hace |
|---|---|
| `postllamada/grafo.py` | El grafo. Cada nodo devuelve solo lo que cambia; las aristas condicionales eligen el camino |
| `senalizacion.py` | 486, 603, 408/480, 5xx, buzón e IVR, **por reglas**. El modelo solo se llama si contestó una persona |
| `llm.py` + `prompts/` | El modelo **solo interpreta**: etiqueta, motivo, confianza y datos, validados con pydantic. Reintentos y respaldo |
| `ordenes.py` + `tiempo.py` | **El código decide**: órdenes, ventana de llamadas, plazos, días hábiles, intentos y reglas N1–N5 |
| `estado.py` | SQLite. Una transacción por evento con hechos, órdenes (clave de idempotencia única), bajas, rechazo de WhatsApp y recordatorios con su `reminder_id` |
| `jev.py` | *Opcional, apagado por defecto.* Envuelve al clasificador con Jev (modo rápido o segunda opinión). El grafo no sabe que existe |

Las 15 decisiones de diseño, con la alternativa descartada, están en [`docs/decisiones.md`](docs/decisiones.md).

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
2. **123 tests** (pytest), con un LLM falso y determinista, sin red:
   - fechas y ventana: bordes, sábado, domingo, cambio de hora;
   - telefonía;
   - el lote completo, un grafo nuevo por evento sobre el mismo SQLite, contra el oráculo;
   - **toda salida validada contra `decision.schema.json` y los `requestBody` del OpenAPI**;
   - 30 casos extra que imitan el lote oculto: los ⚠ (603, callback fuera de ventana, descartado), intentos
     agotados, bajas, WhatsApp rechazado, segunda cortada, reentregas, otra organización, LLM caído;
   - **fuzz** con hypothesis: 150 secuencias aleatorias. Nunca rompe, una decisión por evento y ninguna orden
     duplicada;
   - `run.py` como proceso: códigos de salida y R8;
   - Jev: los dos modos, Jev caído y apagado por defecto. El lote completo con Jev da las mismas órdenes que sin él.
3. **El ejemplo resuelto sale idéntico**, órdenes y decisión, campo por campo (hay test).
4. **Evaluación con el modelo real** ([`docs/evaluaciones/`](docs/evaluaciones)), con el grafo completo y
   repetida:
   - **set normal:** 21 conversaciones (8 del lote y 13 propias que imitan el catálogo, incluidos los ⚠);
   - **set difícil:** 14 conversaciones que llevan al límite los «pares que se parecen» del catálogo. Encontró un
     error del prompt: un tercero que decía «no llamen más a este número» salía como baja 4 de cada 5 veces. Lo
     corregí y pasó a 5/5.

Prompts del sistema: [`prompts/`](prompts). Cómo trabajé con el asistente de programación y dónde se equivocó:
[`docs/proceso-con-ia.md`](docs/proceso-con-ia.md).
