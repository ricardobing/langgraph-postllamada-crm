# Comparación de modelos: `gpt-5.6-luna` contra `gpt-6-luna`

Mismo prompt, mismo esquema estricto y el grafo completo. Todo por OpenRouter para medir el gasto informado.

## Resultado general

| Set | `gpt-5.6-luna` | `gpt-6-luna` |
|---|---|---|
| Normal (21 conversaciones × 5) | 105/105 | 104/105 (una hora de callback mal) |
| Difícil (14 × 10) | 138/140 | 138/140 |
| Callbacks 09, c01 y c13 (× 20) | 60/60 | 60/60 |
| Latencia mediana | ~3,2 s | ~3,1 s |
| Costo por llamada | ~USD 0,00027 | ~USD 0,00012 |

Con 10 repeticiones parecía un empate. **La diferencia aparece en el caso más ambiguo**, así que lo repetí más.

## El caso que los separa: d04

Atiende la mujer del lead y dice «llamadle a partir de las siete». No es el lead, pero dice cuándo localizarlo, así
que es `callback` (`persona_equivocada` es «no se sabe cuándo localizarlo»).

| Corrida | `gpt-5.6-luna` | `gpt-6-luna` |
|---|---|---|
| Set difícil × 5 | 5/5 | 4/5 |
| Set difícil × 10 | 8/10 | 8/10 |
| Con Jev (el d04 lo decide el modelo) | 3/5 · 5/5 · 4/5 | 2/5 · 2/5 |
| Solo d04 × 20 | 18/20 | 12/20 |
| **Total** | **43/50 (86 %)** | **28/45 (62 %)** |

Los dos fallan hacia `otro`, que manda la llamada a revisión humana: es una falla segura, pero se pierde el callback.

## Decisión

**`gpt-5.6-luna` como principal y `gpt-6-luna` como respaldo.** Acierta más donde la conversación es ambigua, que es
justo lo que el lote oculto puede traer. La diferencia de costo son USD 0,00015 por llamada, unos 15 centavos cada
1.000 eventos. Entre acierto y centavos, elijo acierto.

Lección: una comparación con pocas repeticiones sobre casos fáciles no distingue modelos. Hay que buscar el caso
donde dudan y repetirlo hasta que la diferencia sea clara o desaparezca.
