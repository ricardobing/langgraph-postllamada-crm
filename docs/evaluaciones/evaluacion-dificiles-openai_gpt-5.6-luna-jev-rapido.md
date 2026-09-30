# Evaluación con casos difíciles: `openai/gpt-5.6-luna`

Modelo `openai/gpt-5.6-luna` + Jev `rapido` · 2026-09-30 13:16 · 5 repeticiones por caso · acierto 69/70 (98.6 %) · latencia mediana por evento 3.2 s (media 4.1 s) · gasto informado USD 0.0142 (Jev USD 0.0024) · el modelo se llamó en 41/70 eventos · Jev consultado 70 veces · latencia mediana resuelto solo por Jev 0.4 s, con el modelo 3.7 s

| Caso | Esperado | Aciertos | Resultados |
|---|---|---|---|
| d01-baja-al-final-tras-visita.json | `no_contactar` | 5/5 | {'no_contactar': 5} |
| d02-baja-indirecta.json | `no_contactar` | 5/5 | {'no_contactar': 5} |
| d03-descartado-sin-baja.json | `descartado` | 5/5 | {'descartado': 5} |
| d04-tercero-sabe-cuando.json | `callback` | 4/5 | {'callback': 4, 'otro': 1} |
| d05-equivocado-pide-no-llamar.json | `persona_equivocada` | 5/5 | {'persona_equivocada': 5} |
| d06-luego-sin-hora.json | `callback` | 5/5 | {'callback': 5} |
| d07-reunion-sin-pedir-llamada.json | `otro` | 5/5 | {'otro': 5} |
| d08-doc-cualquier-canal.json | `documentacion_enviada` | 5/5 | {'documentacion_enviada': 5} |
| d09-callback-domingo.json | `callback` | 5/5 | {'callback': 5} |
| d10-numero-de-hermano.json | `persona_equivocada` | 5/5 | {'persona_equivocada': 5} |
| d11-compro-pero-hermano-busca.json | `descartado` | 5/5 | {'descartado': 5} |
| d12-ironia.json | `descartado` | 5/5 | {'descartado': 5} |
| d13-cortada-mitad-presupuesto.json | `cortada` | 5/5 | {'cortada': 5} |
| d14-amd-uncertain-media-hora.json | `callback` | 5/5 | {'callback': 5} |
