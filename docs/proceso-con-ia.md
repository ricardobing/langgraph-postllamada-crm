# Cómo trabajé con el asistente de programación

Lo construí con **Claude Code** como asistente. Yo marqué la dirección, tomé las decisiones de diseño y verifiqué;
el asistente escribió el código y las pruebas. Este documento recoge qué le pedí, qué decidí yo y dónde se
equivocó.

## Lo que le pedí, en orden

1. **Antes de abrir el zip:** preparar el entorno, una guía de conceptos de LangGraph para estudiar y una
   comparación de modelos baratos con transcripciones de prueba.
2. **Al abrir el zip:** «Organiza las carpetas e inicia leyendo el enunciado y planificando todo lo que haremos».
   Resultado: [`analisis.md`](analisis.md), con la **salida esperada de los 16 eventos escrita antes de programar**,
   que después fue el oráculo de los tests.
3. **Decisiones que tomé yo** (el asistente propuso opciones con pros y contras): memoria en SQLite propio, una
   sola llamada estructurada al LLM, respaldo por WhatsApp para todas las etiquetas que reprograman, y DeepSeek
   para desarrollar (barato), con la validación final en modelos de OpenAI. Ver [`decisiones.md`](decisiones.md).
4. **«Lo más importante es hacer perfecta la tarea: si no pasa sus tests, no sirve»:** pruebas en 7 capas y casos
   extra que imitan los del lote oculto.
5. **«No pongas tope de gasto: prefiero gastar más y que quede bien»:** evaluación con el modelo real repetida por
   caso.
6. **«Jev usémoslo igual, puede ser mi diferencial»:** integrado como añadido **opcional y apagado por defecto**,
   porque el enunciado exige OpenAI. Después: «que funcione todo como piden y Jev opcional, con todas las mediciones
   y tests». Resultado: dos modos, rápido y segunda opinión, medidos en [`jev.md`](jev.md).
7. **«Que funcione con la clave de OpenAI de ellos, ¿cuál elegir y por qué?»:** un set de casos difíciles para
   separar modelos que empataban. Ver [`evaluaciones/comparacion-modelos.md`](evaluaciones/comparacion-modelos.md).

## Dónde se equivocó la IA (o yo) y cómo se detectó

| # | Qué pasó | Cómo se detectó | Qué se cambió |
|---|---|---|---|
| 1 | La primera comparación de modelos daba 0/8 a DeepSeek y 8/8 a Jev | Antes de creerlo, miré las respuestas crudas: **a Jev le había dado la definición de cada categoría y al LLM no** | Con las mismas definiciones para todos, empate 8/8. Lección: pesan más las definiciones del catálogo que el modelo |
| 2 | El plan inicial ponía Jev + DeepSeek como núcleo | Al leer el enunciado: «modelo de OpenAI» y «sin red salvo el modelo»; el `.env.example` pide `OPENAI_API_KEY` | Núcleo con el SDK oficial de OpenAI. DeepSeek solo para desarrollar (misma interfaz); Jev, opcional |
| 3 | El primer commit tenía 28 archivos, no 29 | Revisando el commit contra el zip: faltaba `.env.example`, ocultado por mi exclusión local de `.env.*` | Añadido a la fuerza y comprobación byte a byte de los 29 archivos |
| 4 | Sumar horas a una fecha con zona en Python suma «hora de reloj» | Revisión del código antes de los tests | `sumar_tiempo` en UTC; test del cambio de hora del 25/10 |
| 5 | **Primera ejecución del lote: 0/16** | `ZoneInfoNotFoundError: Europe/Madrid`. En Windows, Python no trae la base de zonas horarias; la prueba previa había usado otro Python que sí la tenía | Dependencia `tzdata`: funciona igual en cualquier sistema |
| 6 | `orden_id` distinto al del ejemplo | Comparando el evento 02 campo a campo con `ejemplo-resuelto/` | Probé hashes conocidos: el ejemplo usa SHA-1 de la clave. Adoptado; el evento 02 sale idéntico |
| 7 | El motivo del evento 07 mezclaba la cita con un «no encaja en ninguna etiqueta» del modelo | Leyendo las decisiones del lote | Con cita, el motivo lo pone la regla |
| 8 | Un test comparaba mal (variable fuera de ámbito) | El test falló con `NameError`, no el sistema | Corregido el test, no el código |
| 9 | Con un modelo inexistente, el respaldo tardaba 8 s: se reintentaba 3 veces un error que no se arregla reintentando | Probando el respaldo a mano con un nombre de modelo falso | Los errores 400/401/403/404 saltan directo al respaldo (4 s). Hay test |
| 10 | `scripts/ejecutar_lote.py` fallaba 0/16 con rutas relativas | Al lanzarlo con `eventos` en vez de la ruta absoluta | Rutas resueltas antes de lanzar los procesos |
| 11 | El prompt no decía que la baja la tiene que pedir el propio lead: un tercero que decía «no llamen más a este número» salía `no_contactar` | El set difícil (d05): 4 de cada 5 veces, en los dos modelos | Aclarado en el prompt y en los criterios de Jev: 5/5. No era el modelo, era la definición |
| 12 | Con 10 repeticiones concluí que los dos modelos empataban y recomendé el más barato | Seguí repitiendo el caso ambiguo (d04): 86 % contra 62 % en 50 y 45 repeticiones | Volví a `gpt-5.6-luna`. Lección: pocas repeticiones sobre casos fáciles no distinguen modelos |
| 13 | El asistente puso en una tabla una latencia de una corrida que no la medía | Revisando de dónde salía cada número antes de publicarlo | Se relanzó la corrida con la latencia separada y se corrigió la tabla |

## Cómo verifiqué

Ver el README. En resumen:
- 123 tests con LLM falso: sin red, deterministas;
- el lote completo como procesos reales;
- evaluación con el modelo real, repetida (capa 6);
- revisión del ejemplo resuelto campo a campo.
