# Decisiones de diseño

Cada decisión trae la alternativa descartada y el motivo. Las cuatro primeras las tomé antes de escribir código.

| # | Decisión | Alternativa descartada | Por qué |
|---|---|---|---|
| 1 | **Memoria entre procesos en tablas SQLite propias** (`hechos`, `ordenes`, `leads`, `recordatorios`). LangGraph orquesta; el estado de negocio vive en tablas que controlo | Checkpointer de LangGraph (`SqliteSaver`) con `thread_id` = lead | El estado cruza leads (reentregas por `idempotency_key`), necesita consultas (intentos, cortadas, recordatorios pendientes) y tiene que escribirse en la misma transacción que las órdenes. Con tablas explícitas se puede leer, probar y depurar sin depender de cómo serializa LangGraph |
| 2 | **Una sola llamada al LLM, con salida estructurada** (JSON Schema estricto + pydantic): etiqueta, motivo, confianza y los datos que hagan falta (hora del callback, visita acordada, rechazo de WhatsApp, email, nota) | Dos llamadas: clasificar y después extraer | La mitad de llamadas, de coste y de latencia. Una sola fuente de verdad por evento |
| 3 | **El LLM solo interpreta; el código decide.** Fechas, ventana, intentos, plantillas y órdenes son código puro (`ordenes.py`, `tiempo.py`) | Pedirle al modelo la acción o la fecha final | Lo determinista es testeable y no alucina. El modelo devuelve fecha y hora literales, más un flag `hora_ambigua`; el código resuelve «las seis» → 18:00 porque las 06:00 caen fuera de la ventana |
| 4 | **N3 (canal de respaldo) aplica a toda etiqueta que reprograma una llamada**, también `callback` y `cortada` | Respetar un `callback` aunque el lead haya agotado los intentos | La regla dice «agotados los intentos de voz». El máximo es por lead y sale de la configuración |
| 5 | **La telefonía decide antes que el LLM**: 486, 603, 408/480, 5xx, buzón (`machine-vm` / `machine-unavailable`) e IVR no llegan al modelo | Mandar todo al LLM | Es lo que dice el ejemplo resuelto («llamar al modelo aquí es gastar dinero»). En el lote, 8 de 16 eventos no llaman al modelo |
| 6 | **`visita_reservada` la decide la regla** (`appointment` presente). El LLM se consulta igual, solo para que una baja pueda mandar sobre la cita | Clasificar la cita con el LLM | La cita es un hecho del CRM. «10 contra todo»: una baja manda incluso sobre una cita |
| 7 | **Reentrega = `idempotency_key` ya registrada**, no `delivery_attempt > 1` | Mirar `delivery_attempt` | Si la primera entrega falló y no se registró, la segunda tiene que procesarse. Además, la tabla `ordenes` tiene la clave única de idempotencia como segunda barrera |
| 8 | **`orden_id` = `ord_` + SHA-1(idempotency_key)[:8]** | Un UUID aleatorio | Estable entre ejecuciones, y es el esquema del ejemplo resuelto: el evento 02 sale idéntico, byte a byte |
| 9 | **`reminder_id` generado y persistido** en `recordatorios`, con estado `pendiente` / `cancelado` | — | R7: el `cancelar_recordatorio` de otro proceso necesita el id que creamos. «Pendiente» = no cancelado **y** con fecha posterior al mensaje (uno que ya venció ya se ejecutó) |
| 10 | **Ocupado: punto medio del rango 30–90 min**; si cae fuera de la ventana, el primer instante válido del rango; si no hay, la siguiente apertura | Siempre el mínimo | El punto medio reproduce el ejemplo (10:31 → 11:31). Cortada y visita sin confirmar: el mínimo, porque el catálogo dice «lo antes posible» |
| 11 | **Plazos en horas = tiempo real (UTC); plazos en días = calendario de Madrid** | Sumar `timedelta` a fechas con zona | En Python eso suma «hora de reloj», y en el cambio de hora (25/10) desplaza una hora. Hay test |
| 12 | **El estado vive en `salida/estado.sqlite`** | Una carpeta aparte | Si se borra `salida/` para empezar de cero, como hace la evaluación, se borra también la memoria. No quedan restos del lote anterior |
| 13 | **Sin modelo no se rompe:** si no hay clave o el LLM falla (3 reintentos + modelo de respaldo), la llamada con conversación es `otro` + `revisar_llamada`. Con cita, `visita_reservada` | Salir con error | R8. Un humano revisa lo que la máquina no pudo leer |
| 14 | **Jev como segunda opinión opcional**, desactivada por defecto | Jev como clasificador principal | El enunciado pide un modelo de OpenAI y «sin red salvo el modelo». Jev añade velocidad y una red de seguridad, pero nunca puede ser imprescindible |

## Casos que el enunciado no fija y cómo los resolví

- **WhatsApp rechazado y hace falta el canal de respaldo:** tarea `revisar_llamada` («sin canal de respaldo
  disponible»). No se envía nada por WhatsApp (N1).
- **Callback sin hora concreta** («llámame otro día»): separación mínima general (2 h), llevada a la ventana.
- **Visita inminente** (menos de 2 h): la tarea `confirmar_visita_direccion` vence en el momento del evento.
- **Lead dado de baja:** en llamadas posteriores solo `cerrar_llamada`. Cerrar la entrada de cola no contacta al lead.
- **Descolgaron sin conversación** (200, humano, transcripción vacía): `otro` + revisión.
- **SIP no contemplado** (404, 487…): `otro` + revisión.
