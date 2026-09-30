"""Escritura de salida/decisiones.jsonl y salida/ordenes.jsonl (append, una línea JSON por registro)."""
from __future__ import annotations

import json
from pathlib import Path


class Salida:
    def __init__(self, carpeta: str | Path = "salida"):
        self.carpeta = Path(carpeta)
        self.carpeta.mkdir(parents=True, exist_ok=True)

    def escribir(self, decision: dict, ordenes: list[dict]) -> None:
        # Primero las órdenes y después la decisión que las referencia.
        self._append("ordenes.jsonl", ordenes)
        self._append("decisiones.jsonl", [decision])

    def _append(self, nombre: str, registros: list[dict]) -> None:
        if not registros:
            return
        with open(self.carpeta / nombre, "a", encoding="utf-8", newline="\n") as f:
            for r in registros:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
