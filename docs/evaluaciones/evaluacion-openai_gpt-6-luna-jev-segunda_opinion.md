# Evaluación con el modelo real: `openai/gpt-6-luna`

Modelo `openai/gpt-6-luna` + Jev `segunda_opinion` · 2026-09-30 13:09 · 5 repeticiones por caso · acierto 105/105 (100.0 %) · latencia mediana por evento 3.3 s (media 6.3 s) · gasto informado USD 0.0116 (Jev USD 0.0000) · el modelo se llamó en 105/105 eventos · Jev consultado 0 veces · latencia mediana resuelto solo por Jev 0.0 s, con el modelo 3.3 s

| Caso | Esperado | Aciertos | Resultados |
|---|---|---|---|
| 03-call-ended-elena.json | `persona_equivocada` | 5/5 | {'persona_equivocada': 5} |
| 04-call-ended-rosa.json | `cortada` | 5/5 | {'cortada': 5} |
| 06-call-ended-pedro.json | `no_contactar` | 5/5 | {'no_contactar': 5} |
| 07-call-ended-laura.json | `visita_reservada` | 5/5 | {'visita_reservada': 5} |
| 08-call-ended-marcos.json | `documentacion_enviada` | 5/5 | {'documentacion_enviada': 5} |
| 09-call-ended-javier.json | `callback` | 5/5 | {'callback': 5} |
| 11-call-ended-carla.json | `visita_sin_confirmar` | 5/5 | {'visita_sin_confirmar': 5} |
| 13-call-ended-ivan.json | `documentacion_pendiente` | 5/5 | {'documentacion_pendiente': 5} |
| c01-callback-noche.json | `callback` | 5/5 | {'callback': 5} |
| c02-callback-lunes.json | `callback` | 5/5 | {'callback': 5} |
| c03-ahora-no-puedo.json | `otro` | 5/5 | {'otro': 5} |
| c04-descartado.json | `descartado` | 5/5 | {'descartado': 5} |
| c05-descartado-cuelga.json | `descartado` | 5/5 | {'descartado': 5} |
| c06-baja-ya-encontre.json | `no_contactar` | 5/5 | {'no_contactar': 5} |
| c07-baja-y-sigue.json | `no_contactar` | 5/5 | {'no_contactar': 5} |
| c08-equivocado-padre.json | `persona_equivocada` | 5/5 | {'persona_equivocada': 5} |
| c09-doc-email.json | `documentacion_pendiente` | 5/5 | {'documentacion_pendiente': 5} |
| c10-doc-whatsapp.json | `documentacion_enviada` | 5/5 | {'documentacion_enviada': 5} |
| c11-visita-verbal.json | `visita_sin_confirmar` | 5/5 | {'visita_sin_confirmar': 5} |
| c12-cortada.json | `cortada` | 5/5 | {'cortada': 5} |
| c13-callback-ambiguo.json | `callback` | 5/5 | {'callback': 5} |
