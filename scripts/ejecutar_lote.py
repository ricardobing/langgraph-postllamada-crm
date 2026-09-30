"""Ejecuta un lote como lo hará la evaluación: desde cero, un proceso nuevo por evento, en el orden de orden.txt.

    python scripts/ejecutar_lote.py [carpeta_eventos] [carpeta_salida]

Por defecto: eventos/ y salida/. Borra la carpeta de salida (y con ella el estado) antes de empezar.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def main() -> int:
    # Rutas absolutas: los procesos corren desde la raíz del repo, no desde donde se lanzó el script.
    eventos = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else RAIZ / "eventos"
    salida = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else RAIZ / "salida"
    if salida.exists():
        shutil.rmtree(salida)
    orden = [l.strip() for l in (eventos / "orden.txt").read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]
    fallos = 0
    for nombre in orden:
        r = subprocess.run([sys.executable, str(RAIZ / "run.py"), str(eventos / nombre)], cwd=RAIZ,
                           env={**__import__("os").environ, "SALIDA_DIR": str(salida), "PYTHONIOENCODING": "utf-8"},
                           capture_output=True, text=True, encoding="utf-8")
        estado = "ok " if r.returncode == 0 else f"ERROR {r.returncode}"
        fallos += r.returncode != 0
        print(f"[{estado}] {nombre}: {r.stdout.strip() or r.stderr.strip()[-300:]}")
    print(f"\n{len(orden) - fallos}/{len(orden)} eventos procesados · salida en {salida}")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
