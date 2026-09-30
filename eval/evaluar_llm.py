"""Capa 6: evaluación con el modelo real (no es un test: cuesta dinero y el resultado no es determinista).

Cada caso pasa por el grafo COMPLETO (con estado limpio), N veces, y se compara la etiqueta final (y la hora del
callback, cuando aplica) con la esperada. Casos:
- las 8 llamadas con conversación del lote de ejemplo;
- 13 conversaciones propias que imitan los casos del catálogo, incluidos los ⚠ sin ejemplo
  (tests/eventos_extra/conversaciones/).

    uv run python eval/evaluar_llm.py [repeticiones] [tope_usd] [--dificiles] [--jev segunda_opinion|rapido]

--dificiles evalúa en cambio 14 conversaciones difíciles (tests/eventos_extra/dificiles/): los «pares que se parecen»
del catálogo llevados al límite. Sirve para comparar modelos que empatan en el set normal.
--solo a,b evalúa solo los casos cuyo nombre empieza por esos prefijos (para repetir mucho los que dudan).
--jev envuelve al modelo con Jev en ese modo (necesita OPENROUTER_API_KEY) y mide cuántas veces se evitó el modelo.

Usa MODELO / OPENAI_API_KEY / OPENAI_BASE_URL del .env. Mide solo el modelo principal: el respaldo se desactiva para
que no tape sus fallos. Sin tope por defecto; si se pasa uno, se detiene al superarlo.
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
from postllamada.jev import ClasificadorConJev, Jev  # noqa: E402
from postllamada.llm import ClasificadorOpenAI  # noqa: E402
from postllamada.salida import Salida  # noqa: E402

CONVERSACIONES = RAIZ / "tests" / "eventos_extra" / "conversaciones"
DIFICILES = RAIZ / "tests" / "eventos_extra" / "dificiles"

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


def casos(dificiles: bool = False) -> list[tuple[str, dict, str]]:
    carpeta = DIFICILES if dificiles else CONVERSACIONES
    lista = [] if dificiles else [(n, json.loads((RAIZ / "eventos" / n).read_text(encoding="utf-8")), e)
                                  for n, e in CASOS_LOTE.items()]
    esperado = json.loads((carpeta / "esperado.json").read_text(encoding="utf-8"))
    for nombre, etiqueta in esperado.items():
        lista.append((f"{nombre}.json", json.loads((carpeta / f"{nombre}.json").read_text(encoding="utf-8")), etiqueta))
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
    dificiles = "--dificiles" in sys.argv
    modo_jev = sys.argv[sys.argv.index("--jev") + 1] if "--jev" in sys.argv else None
    solo = sys.argv[sys.argv.index("--solo") + 1].split(",") if "--solo" in sys.argv else None
    args = [a for a in sys.argv[1:] if a not in ("--dificiles", "--jev", modo_jev, "--solo", ",".join(solo or []))]
    repeticiones = int(args[0]) if args else 3
    tope = float(args[1]) if len(args) > 1 else float("inf")
    cfg = cargar_config(RAIZ / "config" / "campana.yaml")
    os.environ["MODELO_RESPALDO"] = ""
    principal = ClasificadorOpenAI.desde_entorno()
    modelo = principal.modelos[0]
    llamadas_modelo = [0]
    clasificar_modelo = principal.clasificar

    def contar(evento, zona):
        llamadas_modelo[0] += 1
        return clasificar_modelo(evento, zona)

    principal.clasificar = contar
    jev = Jev() if modo_jev else None
    clasificador = ClasificadorConJev(principal, jev, modo_jev) if modo_jev else principal
    costo = lambda: principal.costo_usd + (jev.costo_usd if jev else 0.0)
    
    filas, total, bien, latencias = [], 0, 0, []
    latencias_solo_jev, latencias_con_modelo = [], []  # modo rápido: quién resolvió cada evento
    for nombre, evento, esperado in casos(dificiles):
        if solo and not any(nombre.startswith(p) for p in solo):
            continue
        resultados = Counter()
        fallos_hora = 0
        horas_mal = Counter()
        for _ in range(repeticiones):
            if costo() > tope:
                print(f"TOPE DE GASTO ALCANZADO (USD {costo():.4f} > {tope}): me detengo")
                break
            t0, llamadas_antes = time.time(), llamadas_modelo[0]
            etiqueta, ordenes = ejecutar(evento, clasificador, cfg)
            latencias.append(time.time() - t0)
            (latencias_con_modelo if llamadas_modelo[0] > llamadas_antes else latencias_solo_jev).append(latencias[-1])
            resultados[etiqueta] += 1
            total += 1
            ok = etiqueta == esperado
            if ok and nombre in HORA_CALLBACK:
                llamada = next((o for o in ordenes if o["operacion"] == "programar_llamada"), None)
                if not llamada or llamada["cuerpo"]["no_antes_de"] != HORA_CALLBACK[nombre]:
                    ok = False
                    fallos_hora += 1
                    horas_mal[llamada["cuerpo"]["no_antes_de"] if llamada else "sin llamada"] += 1
            bien += ok
        aciertos = resultados[esperado] - fallos_hora
        filas.append((nombre, esperado, aciertos, sum(resultados.values()), dict(resultados), fallos_hora))
        marca = "OK " if aciertos == sum(resultados.values()) else "!! "
        print(f"{marca}{nombre:32} esperado {esperado:24} {aciertos}/{sum(resultados.values())}  {dict(resultados)}"
              + (f"  (hora de callback mal en {fallos_hora}: {dict(horas_mal)})" if fallos_hora else ""))
    def mediana_de(valores: list[float]) -> float:
        return sorted(valores)[len(valores) // 2] if valores else 0.0

    mediana = mediana_de(latencias)
    resumen = (f"Modelo `{modelo}`{f' + Jev `{modo_jev}`' if modo_jev else ''} · {datetime.now():%Y-%m-%d %H:%M} · "
               f"{repeticiones} repeticiones por caso · acierto {bien}/{total} ({100 * bien / max(total, 1):.1f} %) · "
               f"latencia mediana por evento {mediana:.1f} s (media {sum(latencias) / max(len(latencias), 1):.1f} s) · "
               f"gasto informado USD {costo():.4f}")
    if jev:
        resumen += (f" (Jev USD {jev.costo_usd:.4f}) · el modelo se llamó en {llamadas_modelo[0]}/{total} eventos · "
                    f"Jev consultado {jev.consultas} veces · latencia mediana resuelto solo por Jev "
                    f"{mediana_de(latencias_solo_jev):.1f} s, con el modelo {mediana_de(latencias_con_modelo):.1f} s")
    print("\n" + resumen)
    sufijo = "-dificiles" if dificiles else ""
    sufijo_jev = f"-jev-{modo_jev}" if modo_jev else ""
    if solo:  # una corrida parcial no pisa el informe completo
        sufijo_jev += "-solo-" + "-".join(p.rstrip("-") for p in solo)
    salida = RAIZ / "docs" / "evaluaciones" / f"evaluacion{sufijo}-{modelo.replace('/', '_')}{sufijo_jev}.md"
    titulo = "casos difíciles" if dificiles else "el modelo real"
    lineas = [f"# Evaluación con {titulo}: `{modelo}`", "", resumen, "",
              "| Caso | Esperado | Aciertos | Resultados |", "|---|---|---|---|"]
    lineas += [f"| {n} | `{e}` | {a}/{t} | {r}{' · hora de callback mal: ' + str(fh) if fh else ''} |" for n, e, a, t, r, fh in filas]
    salida.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    print(f"informe: {salida.relative_to(RAIZ)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
