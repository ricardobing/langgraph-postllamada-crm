# Evaluación de Jev (segunda opinión opcional)

`typesafe/jev-1.13` vía OpenRouter, **en solitario** (sin el LLM principal), sobre las 20 conversaciones de la
evaluación. `visita_reservada` queda fuera porque la decide la regla de la cita, no un clasificador.

- **Acierto:** 20/20.
- **Latencia mediana:** 0,39 s. El LLM principal tarda unos 3 s.
- **Confianza** en la opción elegida: 0,89–1,00. La más baja fue «ahora no puedo» (`otro`, 0,89), que es justo el
  caso más ambiguo del catálogo.

Uso en el sistema (`postllamada/jev.py`), solo con `JEV_ACTIVADO=1` y `OPENROUTER_API_KEY`:
- **Duda:** si el modelo principal devuelve confianza < 0,75, se consulta a Jev y se queda la opinión más segura.
- **Caída:** si el modelo principal no responde, clasifica Jev en vez de mandar la llamada a revisión humana.

Sin esas variables, el sistema funciona completo solo con el modelo de OpenAI, como pide el enunciado.
