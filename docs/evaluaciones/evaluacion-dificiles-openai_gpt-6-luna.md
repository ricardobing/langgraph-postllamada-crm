# Evaluación con casos difíciles: `openai/gpt-6-luna`

Modelo `openai/gpt-6-luna` · 2026-09-30 12:55 · 10 repeticiones por caso · acierto 138/140 (98.6 %) · latencia mediana por evento 3.1 s · gasto informado USD 0.0162

| Caso | Esperado | Aciertos | Resultados |
|---|---|---|---|
| d01-baja-al-final-tras-visita.json | `no_contactar` | 10/10 | {'no_contactar': 10} |
| d02-baja-indirecta.json | `no_contactar` | 10/10 | {'no_contactar': 10} |
| d03-descartado-sin-baja.json | `descartado` | 10/10 | {'descartado': 10} |
| d04-tercero-sabe-cuando.json | `callback` | 8/10 | {'callback': 8, 'otro': 2} |
| d05-equivocado-pide-no-llamar.json | `persona_equivocada` | 10/10 | {'persona_equivocada': 10} |
| d06-luego-sin-hora.json | `callback` | 10/10 | {'callback': 10} |
| d07-reunion-sin-pedir-llamada.json | `otro` | 10/10 | {'otro': 10} |
| d08-doc-cualquier-canal.json | `documentacion_enviada` | 10/10 | {'documentacion_enviada': 10} |
| d09-callback-domingo.json | `callback` | 10/10 | {'callback': 10} |
| d10-numero-de-hermano.json | `persona_equivocada` | 10/10 | {'persona_equivocada': 10} |
| d11-compro-pero-hermano-busca.json | `descartado` | 10/10 | {'descartado': 10} |
| d12-ironia.json | `descartado` | 10/10 | {'descartado': 10} |
| d13-cortada-mitad-presupuesto.json | `cortada` | 10/10 | {'cortada': 10} |
| d14-amd-uncertain-media-hora.json | `callback` | 10/10 | {'callback': 10} |
