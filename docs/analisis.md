# Análisis del enunciado y salida esperada

Documento de trabajo escrito **antes** de programar. Es la especificación contra la que se prueba el sistema: la
tabla de §3 es el oráculo de los tests de integración.

## 1. Contrato

- `python run.py <evento.json>`: un proceso por evento, en el orden de `eventos/orden.txt`.
- Salida por append:
  - `salida/decisiones.jsonl`: una línea por evento recibido, también los rechazados;
  - `salida/ordenes.jsonl`: una línea por orden.
- Código de salida: `0` si procesó el evento, distinto de `0` si no pudo.
- **Nada en memoria entre eventos.** Todo lo que haya que recordar se persiste en SQLite local:
  - intentos por lead;
  - llamadas ya procesadas (para detectar reentregas);
  - bajas (DNC);
  - rechazo de WhatsApp;
  - recordatorios pendientes con su `reminder_id`;
  - llamadas cortadas.
- Se evalúa con **otro lote, desde cero**: casos ⚠ sin ejemplo y variantes con otras fechas y horas.

## 2. Reglas que fijan el resultado

### Clasificación por señalización (sin LLM)

| Señal | Etiqueta |
|---|---|
| otra `organization_id` | `no_aplica`, sin órdenes |
| `idempotency_key` ya procesada | la etiqueta original, sin órdenes |
| `message.received` | `no_aplica` + `cancelar_recordatorio` de cada recordatorio pendiente del lead |
| SIP `486` | `ocupado` |
| SIP `603` | `rechazada` |
| SIP `408` / `480` | `sin_respuesta` |
| SIP `5xx` | `otro` (N4) |
| `200` + `amd` `machine-vm` / `machine-unavailable` (cualquier fuente) | `buzon` |
| `200` + `amd` `machine-ivr` | `otro` (N4) |
| `200` + `amd` `human` / `uncertain` / `not_run` | **se lee la conversación** (LLM) |
| `200` + `agent_outcome.appointment` presente | `visita_reservada`, salvo que haya una baja (la baja manda sobre todo) |

### Clasificación por conversación (LLM)

Solo decide entre estas etiquetas:
- `documentacion_enviada`
- `documentacion_pendiente`
- `callback`
- `cortada`
- `visita_sin_confirmar`
- `persona_equivocada`
- `no_contactar`
- `descartado`
- `otro`

Pares a vigilar:
- una baja manda siempre, aunque la conversación siga;
- 3 contra 7: "ahora no puedo" sin pedir otra llamada no es `callback`;
- 7 contra 8: la diferencia es si se acordó una visita;
- 15 contra 7: colgar seco después de decir que ya no busca es `descartado`.

### Plazos (Europe/Madrid)

- **Ventana:** L–V de 10:00 a 20:00, sábado de 10:00 a 14:00, domingo nada. Los extremos cuentan.

| Caso | `no_antes_de` |
|---|---|
| `sin_respuesta`, `buzon` con intentos | evento + 2 h (separación mínima), llevado a la ventana |
| `ocupado` | evento + 60 min, que es el **punto medio** de 30–90 y reproduce el ejemplo resuelto (10:31 → 11:31). Si no cae en la ventana, el primer instante válido del rango; si no hay ninguno, la siguiente apertura |
| `cortada`, `visita_sin_confirmar` | lo antes posible: evento + 30 min, llevado a la ventana |
| `callback` | la hora que pidió el lead. Si cae fuera de la ventana (caso 12): la primera franja válida + plantilla `aviso_cambio_hora` |

Plazos de tareas y recordatorios:
- **Tareas:** `vence_el` = evento + 2 días naturales, salvo `confirmar_visita_direccion`, que vence en cita − 2 h.
- **Recordatorio al lead:** evento + 48 h naturales.
- **Recordatorio al comercial:** evento + 3 días hábiles (L–V; el sábado no cuenta).

### Políticas

- **N1:** con WhatsApp rechazado, nada por WhatsApp (plantillas ni `whatsapp_lead`). Se persiste por lead.
- **N2:** con una baja, ninguna orden saliente. `cerrar_llamada` sí, porque no contacta al lead. Se persiste por
  lead.
- **N3 y R4:** con intentos agotados (3 `call.ended` del lead, sin contar reentregas), no hay más llamadas: se usa
  el canal de respaldo (`enviar_plantilla_whatsapp` `primer_toque_respaldo`).
- **N4:** `otro`, o una segunda `cortada` / `visita_sin_confirmar` del mismo lead → `crear_tarea revisar_llamada`,
  además de lo que corresponda por la etiqueta.
- **N5:** la visita de palabra no se reserva; se vuelve a llamar.
- **`cerrar_llamada`:** en todo `call.ended` procesado por primera vez de la organización, con el estado de cola que
  fija `casos.md`.

### Identificadores

- `idempotency_key` de cada orden = `<idempotency_key del evento>:<operacion>[:distintivo]`.
- `orden_id` = `ord_` + los primeros 8 caracteres del hash SHA-256 de esa clave. Es estable entre ejecuciones.
- `reminder_id` y demás identificadores, generados y persistidos.

## 3. Salida esperada del lote de ejemplo (oráculo)

Todas las fechas son del 15/09/2026 (martes), salvo que se indique otra.

| # | Evento | Etiqueta | `cerrar_llamada.status` | Otras órdenes |
|---|---|---|---|---|
| 01 | Nuria, 480, 10:12 (intento 1) | `sin_respuesta` | `no_answer` | `programar_llamada` 12:12 |
| 02 | Tomás, 486, 10:31 | `ocupado` | `no_answer` | `programar_llamada` 11:31 (**idéntico al ejemplo resuelto**) |
| 03 | Elena: "aquí no vive ninguna Elena" | `persona_equivocada` | `failed` | `crear_tarea verificar_telefono`, vence 17/09 11:04. Sin reintento |
| 04 | Rosa: se corta en "unos mil dosci…" | `cortada` | `needs_review` | `programar_llamada` 12:17, con nota: alquiler, Majadahonda / Las Rozas, presupuesto ~1.200 € (cortado) |
| 05 | Nuria, 480, 12:20 (intento 2) | `sin_respuesta` | `no_answer` | `programar_llamada` 14:20 |
| 06 | Pedro: "dadme de baja" y después pregunta el precio | `no_contactar` | `dnc` | `marcar_no_contactar` canal `todos`. Nada más |
| 07 | Laura: cita `apt_5512` jueves 17 11:00, dirección `null` | `visita_reservada` | `successful` | `crear_tarea confirmar_visita_direccion`, vence 17/09 09:00 |
| 08 | Marcos: acepta la documentación por WhatsApp | `documentacion_enviada` | `completed` | `programar_recordatorio` al lead (`whatsapp_lead`, `recordatorio_documentacion`, 17/09 16:42, `lead_responde`) y al comercial (`tarea_comercial`, `llamar_a_mano`, 18/09 16:42, `lead_responde`) |
| 09 | Javier: "mañana a las seis", a las 17:05 | `callback` | `callback_requested` | `programar_llamada` 16/09 18:00 ("las seis" → 18:00; las 06:00 caen fuera de la ventana) |
| 10 | Sonia: saludo ambiguo, `heuristic_regex` (intento 1) | `buzon` | `no_answer` | `programar_llamada` 19:30 |
| 11 | Carla: visita de palabra el jueves 17:00 y se corta | `visita_sin_confirmar` | `needs_review` | `programar_llamada` 18:20, con nota de la visita acordada. **Sin reservar** |
| 12 | Nuria, buzón, 18:15 (**intento 3 de 3**) | `buzon` | `no_answer` | respaldo: `enviar_plantilla_whatsapp primer_toque_respaldo`. Sin llamada |
| 13 | Iván: pide documentación, rechaza WhatsApp | `documentacion_pendiente` | `completed` | `crear_tarea enviar_documentacion_email`, vence 17/09 18:40. Se persiste el rechazo de WhatsApp |
| 14 | WhatsApp de Marcos, 16/09 09:30 | `no_aplica` | — | 2 × `cancelar_recordatorio`, con los `reminder_id` del evento 08 |
| 15 | Reentrega de `lk-out-0311` (Javier) | `callback` (la original) | — | ninguna |
| 16 | Alberto, `org_demo_b` | `no_aplica` | — | ninguna |

## 4. Casos ⚠ y variantes que hay que cubrir sin ejemplo

| Caso | Qué hay que probar |
|---|---|
| **Rechazada (603)** | `rechazada` / `refused`, respaldo por WhatsApp, sin reintento (salvo N1 o N2) |
| **Callback fuera de la ventana** | Ejemplos: "a las diez de la noche", "el domingo". Primera franja válida + `aviso_cambio_hora` |
| **Descartado** | "Ya alquilé", sin baja: `descartado` / `skipped`, solo `cerrar_llamada` |
| **Variantes** | IVR / 5xx → `otro` + `revisar_llamada`; `uncertain` → se lee la conversación; segunda cortada del mismo lead → `revisar_llamada` |
| **Intentos agotados** | Con `sin_respuesta` / `ocupado` → respaldo |
| **Lead dado de baja** | Una llamada posterior no emite nada saliente |
| **WhatsApp rechazado** | Con respaldo → no se envía WhatsApp |
| **Ventanas y fechas** | Sábado (10:00–14:00), domingo, a las 19:59 / 20:00 / 20:01, viernes tarde → lunes, cambio de horario (25/10) |
