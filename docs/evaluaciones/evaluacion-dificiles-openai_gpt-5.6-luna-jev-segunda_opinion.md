# Evaluación con casos difíciles: `openai/gpt-5.6-luna`

Modelo `openai/gpt-5.6-luna` + Jev `segunda_opinion` · 2026-09-30 12:45 · 5 repeticiones por caso · acierto 68/70 (97.1 %) · latencia mediana por evento 3.2 s · gasto informado USD 0.0184 (Jev USD 0.0000) · el modelo se llamó en 70/70 eventos · Jev consultado 0 veces

| Caso | Esperado | Aciertos | Resultados |
|---|---|---|---|
| d01-baja-al-final-tras-visita.json | `no_contactar` | 5/5 | {'no_contactar': 5} |
| d02-baja-indirecta.json | `no_contactar` | 5/5 | {'no_contactar': 5} |
| d03-descartado-sin-baja.json | `descartado` | 5/5 | {'descartado': 5} |
| d04-tercero-sabe-cuando.json | `callback` | 3/5 | {'otro': 1, 'callback': 3, 'persona_equivocada': 1} |
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
