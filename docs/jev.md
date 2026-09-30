# Jev: un añadido opcional, medido

## Por qué está, si no lo pidieron

Me gusta probar lo nuevo que va saliendo en proyectos reales, medir si aporta de verdad y recién ahí decidir si se
queda. Jev (`typesafe/jev-1.13`, de TypeSafe) es un modelo de **decisión**: no genera texto, elige una opción entre
varias y devuelve su probabilidad. Clasificar una llamada entre 9 etiquetas es justo su caso de uso, así que valía la
pena medirlo contra el modelo de OpenAI.

La regla que me puse: **por defecto el sistema hace exactamente lo que pide el enunciado** (un modelo de OpenAI, sin
red salvo el modelo). Jev se prende a mano y, si falla, el sistema sigue como si no existiera.

## Cómo se activa

```bash
JEV_ACTIVADO=1
OPENROUTER_API_KEY=...        # Jev se sirve por OpenRouter
JEV_MODO=segunda_opinion      # o: rapido
```

- **Mal configurado** (sin clave o con un modo que no existe): `run.py` avisa por stderr y sigue solo con OpenAI.
- **Proveedor:** está probado por OpenRouter. TypeSafe tiene API directa (en acceso anticipado), y Vercel AI Gateway
  y Cloudflare AI Gateway también lo sirven, pero no los probé.

## Los dos modos

Todo vive en `ClasificadorConJev` ([`postllamada/jev.py`](../postllamada/jev.py)), que envuelve al clasificador de
OpenAI con la misma interfaz. El grafo no cambia ni sabe que Jev existe.

| Modo | Qué hace |
|---|---|
| `segunda_opinion` | Primero el modelo de OpenAI. Jev solo se consulta si el modelo **duda** (confianza < 0,75) o **se cae**. Con duda, se queda la opinión más segura, pero conserva los datos que extrajo el modelo |
| `rapido` | Primero Jev (≈0,5 s). Si está muy seguro (≥ 0,90) de una etiqueta que **no necesita datos extraídos** (`no_contactar`, `descartado`, `persona_equivocada`), decide él y no se llama al modelo. Si no, sigue como `segunda_opinion` reutilizando la opinión ya obtenida: Jev se consulta una sola vez por evento |

Solo esas tres etiquetas porque Jev elige, pero no extrae texto. Un callback necesita la hora, la documentación
pendiente necesita el email y una cortada necesita la nota de contexto: eso lo hace siempre el modelo de OpenAI.

## Qué medí

Mismo evaluador que el modelo principal (`eval/evaluar_llm.py --jev <modo>`), grafo completo y 5 repeticiones por
caso. El gasto es el que informa el proveedor. Informes en [`evaluaciones/`](evaluaciones).

**Set normal** (21 conversaciones × 5 = 105 eventos):

| Configuración | Acierto | Llamadas al modelo | Latencia: solo Jev / con modelo | Costo total |
|---|---|---|---|---|
| `gpt-5.6-luna` solo (el principal) | 105/105 | 105 | — / 3,2 s | USD 0,0265 |
| `gpt-5.6-luna` + Jev rápido | 105/105 | **70** (−33 %) | **0,5 s** / 3,9 s | USD 0,0232 (−12 %) |
| `gpt-6-luna` solo | 104/105¹ | 105 | — / 3,1 s | USD 0,0120 |
| `gpt-6-luna` + Jev rápido | 105/105 | **70** (−33 %) | **0,4 s** / 3,7 s | USD 0,0119 |

**Set difícil** (14 conversaciones × 5 = 70 eventos):

| Configuración | Acierto | Llamadas al modelo | Latencia: solo Jev / con modelo | Costo total |
|---|---|---|---|---|
| `gpt-5.6-luna` solo (el principal) | 70/70 | 70 | — / 3,1 s | USD 0,0187 |
| `gpt-5.6-luna` + Jev rápido | 69/70² | **41** (−41 %) | **0,4 s** / 3,7 s | USD 0,0142 (−24 %) |
| `gpt-6-luna` + Jev rápido | 67/70² | **40** (−43 %) | **0,5 s** / 3,6 s | USD 0,0072 |

¹ Una hora de callback mal en 5 repeticiones; la etiqueta, bien. ² Todos los fallos son del d04 (un tercero dice
cuándo llamar), que decide el modelo y no Jev: es un `callback` y necesita la hora.

- **Todas las decisiones que tomó Jev solo fueron correctas**, incluidas las trampas del set difícil: bajas dichas al
  final o de forma indirecta, «ya compré» con la puerta abierta, ironía y un equivocado que pide no llamar.
- **En modo `segunda_opinion`, Jev no se consultó ni una vez** en 350 eventos: los modelos de OpenAI nunca
  devolvieron confianza < 0,75.
- **Jev en solitario**, sin el modelo: 20/20 ([`evaluaciones/jev-en-solitario.md`](evaluaciones/jev-en-solitario.md)).

## Conclusión: cuándo elegir cada uno

| Opción | Cuándo |
|---|---|
| **Sin Jev** (por defecto) | Lo que pide el enunciado. Una sola dependencia externa y una sola clave. Es lo que evalúan |
| `rapido` | Cuando importa la latencia: un tercio de los eventos se resuelve en 0,5 s en vez de ~3,5 s, sin perder acierto. Ahorra costo con el modelo principal (−12 % a −24 % con `gpt-5.6-luna`) y queda neutro con uno barato (con `gpt-6-luna`, lo que cuesta Jev es lo que se ahorra). Suma ~0,5 s a los eventos que igual van al modelo |
| `segunda_opinion` | Como red de seguridad ante una caída del proveedor principal. En la práctica ya la cubre el modelo de respaldo, y los modelos nunca dudaron, así que **hoy no aporta**. La dejo porque no cuesta nada cuando no actúa |

Resumen honesto: **Jev aporta velocidad, no acierto.** En este proceso, que corre después de la llamada, 3 segundos
no le importan a nadie, así que apagado por defecto es la decisión correcta. Lo encendería si la clasificación se
usara durante la llamada o con mucho volumen sobre un modelo más caro.

## Riesgos

- **El endpoint de Jev es `alpha`:** versión fijada (`typesafe/jev-1.13`, no `latest`) y, si falla, se sigue sin él.
  Hay tests para Jev caído en cada modo.
- **Una segunda clave y un segundo proveedor:** por eso nunca es imprescindible.
- **Umbrales** (0,75 de duda, 0,90 del modo rápido) y la lista de etiquetas sin datos: son decisiones mías, con tests
  y medidas arriba.

## Tests

`tests/test_jev.py` (24, sin red, con un transporte falso):
- los dos modos, con Jev seguro, con Jev inseguro y con Jev caído;
- que se consulte una sola vez por evento;
- la activación desde `run.py`: apagado por defecto, mal configurado avisa y sigue;
- **el lote completo con Jev en modo rápido da las mismas órdenes que sin Jev**; cambian solo el motivo y la
  confianza, y el modelo se llama 6 veces en vez de 8.
