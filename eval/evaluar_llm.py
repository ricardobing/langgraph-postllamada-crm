"""Capa 6: evaluación con el modelo real (no es un test: cuesta dinero y el resultado no es determinista).

Cada caso pasa por el grafo COMPLETO (con estado limpio), N veces, y se compara la etiqueta final (y la hora del
callback, cuando aplica) con la esperada. Casos:
- las 8 llamadas con conversación del lote de ejemplo;
- 13 conversaciones propias que imitan los casos del catálogo, incluidos los ⚠ sin ejemplo
  (tests/eventos_extra/conversaciones/).

    uv run python eval/evaluar_llm.py [repeticiones] [tope_usd]

Usa MODELO / OPENAI_API_KEY / OPENAI_BASE_URL del .env. Sin tope por defecto; si se pasa uno, se detiene al superarlo.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from postllamada.config import cargar_config  # noqa: E402
from postllamada.estado import Estado  # noqa: E402
from postllamada.grafo import construir_grafo  # noqa: E402
from postllamada.llm import ClasificadorOpenAI  # noqa: E402
from postllamada.salida import Salida  # noqa: E402

CONVERSACIONES = RAIZ / "tests" / "eventos_extra" / "conversaciones"

CASOS_LOTE = {  # evento del lote de ejemplo → etiqueta esperada (docs/analisis.md §3)
    "03-call-ended-elena.json": "persona_equivocada",
    "04-call-ended-rosa.json": "cortada",
    "06-call-ended-pedro.json": "no_contactar",
    "07-call-ended-laura.json": "visita_reservada",
    "08-call-ended-marcos.json": "documentacion_enviada",
    "09-call-ended-javier.json": "callback",
    "11-call-ended-carla.json": "visita_sin_confirmar",
    "13-call-ended-ivan.json": "documentacion_pendiente",
}
HORA_CALLBACK = {  # no_antes_de esperado para los callbacks
    "09-call-ended-javier.json": "2026-09-16T18:00:00+02:00",
    "c01-callback-noche.json": "2026-09-16T10:00:00+02:00",   # pidió las 22:00 → primera franja + aviso_cambio_hora
    "c02-callback-lunes.json": "2026-09-21T11:30:00+02:00",
    "c13-callback-ambiguo.json": "2026-09-17T17:00:00+02:00",  # "mañana a las cinco" → 17:00
}


def casos() -> list[tuple[str, dict, str]]:
    lista = [(n, json.loads((RAIZ / "eventos" / n).read_text(encoding="utf-8")), e) for n, e in CASOS_LOTE.items()]
    esperado = json.loads((CONVERSACIONES / "esperado.json").read_text(encoding="utf-8"))
    for nombre, etiqueta in esperado.items():
        lista.append((f"{nombre}.json", json.loads((CONVERSACIONES / f"{nombre}.json").read_text(encoding="utf-8")), etiqueta))
    return lista


def ejecutar(evento: dict, clasificador, cfg) -> tuple[str, list[dict]]:
    with tempfile.TemporaryDirectory() as tmp:
        estado = Estado(Path(tmp) / "estado.sqlite")
        try:
            decision = construir_grafo(cfg, estado, clasificador, Salida(tmp)).invoke({"evento": evento})["decision"]
        finally:
            estado.cerrar()
        ordenes_path = Path(tmp) / "ordenes.jsonl"
        ordenes = [json.loads(l) for l in ordenes_path.read_text(encoding="utf-8").splitlines()] if ordenes_path.exists() else []
    return decision["etiqueta"], ordenes


def main() -> int:
    load_dotenv(RAIZ / ".env")
    repeticiones = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    tope = float(sys.argv[2]) if len(sys.argv) > 2 else float("inf")
    cfg = cargar_config(RAIZ / "config" / "campana.yaml")
    clasificador = ClasificadorOpenAI.desde_entorno()
    modelo = clasificador.modelos[0]
    filas, total, bien, latencias = [], 0, 0, []
    for nombre, evento, esperado in casos():
        resultados = Counter()
        fallos_hora = 0
        for _ in range(repeticiones):
            if clasificador.costo_usd > tope:
                print(f"TOPE DE GASTO ALCANZADO (USD {clasificador.costo_usd:.4f} > {tope}): me detengo")
                break
            t0 = time.time()
            etiqueta, ordenes = ejecutar(evento, clasificador, cfg)
            latencias.append(time.time() - t0)
            resultados[etiqueta] += 1
            total += 1
            ok = etiqueta == esperado
            if ok and nombre in HORA_CALLBACK:
                llamada = next((o for o in ordenes if o["operacion"] == "programar_llamada"), None)
                if not llamada or llamada["cuerpo"]["no_antes_de"] != HORA_CALLBACK[nombre]:
                    ok = False
                    fallos_hora += 1
            bien += ok
        aciertos = resultados[esperado] - fallos_hora
        filas.append((nombre, esperado, aciertos, sum(resultados.values()), dict(resultados), fallos_hora))
        marca = "OK " if aciertos == sum(resultados.values()) else "!! "
        print(f"{marca}{nombre:32} esperado {esperado:24} {aciertos}/{sum(resultados.values())}  {dict(resultados)}"
              + (f"  (hora de callback mal en {fallos_hora})" if fallos_hora else ""))
    latencias.sort()
    mediana = latencias[len(latencias) // 2] if latencias else 0
    resumen = (f"Modelo `{modelo}` · {datetime.now():%Y-%m-%d %H:%M} · {repeticiones} repeticiones por caso · "
               f"acierto {bien}/{total} ({100 * bien / max(total, 1):.1f} %) · latencia mediana por evento {mediana:.1f} s · "
               f"gasto informado USD {clasificador.costo_usd:.4f}")
    print("\n" + resumen)
    salida = RAIZ / "docs" / f"evaluacion-{modelo.replace('/', '_')}.md"
    lineas = [f"# Evaluación con el modelo real: `{modelo}`", "", resumen, "",
              "| Caso | Esperado | Aciertos | Resultados |", "|---|---|---|---|"]
    lineas += [f"| {n} | `{e}` | {a}/{t} | {r}{' · hora de callback mal: ' + str(fh) if fh else ''} |" for n, e, a, t, r, fh in filas]
    salida.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    print(f"informe: {salida.relative_to(RAIZ)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
