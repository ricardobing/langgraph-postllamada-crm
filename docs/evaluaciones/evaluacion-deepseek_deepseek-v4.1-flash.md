# Evaluación con el modelo real: `deepseek/deepseek-v4.1-flash`

Modelo `deepseek/deepseek-v4.1-flash` · 2026-09-30 11:49 · 3 repeticiones por caso · acierto 63/63 (100.0 %) · latencia mediana por evento 3.6 s · gasto informado USD 0.0181

| Caso | Esperado | Aciertos | Resultados |
|---|---|---|---|
| 03-call-ended-elena.json | `persona_equivocada` | 3/3 | {'persona_equivocada': 3} |
| 04-call-ended-rosa.json | `cortada` | 3/3 | {'cortada': 3} |
| 06-call-ended-pedro.json | `no_contactar` | 3/3 | {'no_contactar': 3} |
| 07-call-ended-laura.json | `visita_reservada` | 3/3 | {'visita_reservada': 3} |
| 08-call-ended-marcos.json | `documentacion_enviada` | 3/3 | {'documentacion_enviada': 3} |
| 09-call-ended-javier.json | `callback` | 3/3 | {'callback': 3} |
| 11-call-ended-carla.json | `visita_sin_confirmar` | 3/3 | {'visita_sin_confirmar': 3} |
| 13-call-ended-ivan.json | `documentacion_pendiente` | 3/3 | {'documentacion_pendiente': 3} |
| c01-callback-noche.json | `callback` | 3/3 | {'callback': 3} |
| c02-callback-lunes.json | `callback` | 3/3 | {'callback': 3} |
| c03-ahora-no-puedo.json | `otro` | 3/3 | {'otro': 3} |
| c04-descartado.json | `descartado` | 3/3 | {'descartado': 3} |
| c05-descartado-cuelga.json | `descartado` | 3/3 | {'descartado': 3} |
| c06-baja-ya-encontre.json | `no_contactar` | 3/3 | {'no_contactar': 3} |
| c07-baja-y-sigue.json | `no_contactar` | 3/3 | {'no_contactar': 3} |
| c08-equivocado-padre.json | `persona_equivocada` | 3/3 | {'persona_equivocada': 3} |
| c09-doc-email.json | `documentacion_pendiente` | 3/3 | {'documentacion_pendiente': 3} |
| c10-doc-whatsapp.json | `documentacion_enviada` | 3/3 | {'documentacion_enviada': 3} |
| c11-visita-verbal.json | `visita_sin_confirmar` | 3/3 | {'visita_sin_confirmar': 3} |
| c12-cortada.json | `cortada` | 3/3 | {'cortada': 3} |
| c13-callback-ambiguo.json | `callback` | 3/3 | {'callback': 3} |
