"""Utilidades compartidas por los tests.

`procesar()` imita la evaluación: por cada evento construye un grafo nuevo sobre el MISMO fichero SQLite, igual que
un proceso nuevo por evento. El LLM se sustituye por un clasificador falso y determinista (sin red, sin coste).
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

from postllamada.config import cargar_config
from postllamada.estado import Estado
from postllamada.grafo import construir_grafo
from postllamada.salida import Salida
from postllamada.tipos import Clasificacion, DatosConversacion

RAIZ = Path(__file__).resolve().parent.parent
EVENTOS = RAIZ / "eventos"
EXTRA = Path(__file__).resolve().parent / "eventos_extra"


@pytest.fixture
def cfg():
    return cargar_config(RAIZ / "config" / "campana.yaml")


def cargar(nombre: str) -> dict:
    ruta = EVENTOS / nombre if (EVENTOS / nombre).exists() else EXTRA / nombre
    return json.loads(ruta.read_text(encoding="utf-8"))


class ClasificadorFalso:
    """Devuelve lo que se le indique por idempotency_key. Si no hay nada indicado, falla como un LLM caído."""

    def __init__(self, respuestas: dict[str, Clasificacion] | None = None):
        self.respuestas = respuestas or {}
        self.llamadas = 0

    def clasificar(self, evento: dict, zona) -> Clasificacion:
        from postllamada.llm import ErrorClasificacion

        self.llamadas += 1
        if evento["idempotency_key"] not in self.respuestas:
            raise ErrorClasificacion("sin respuesta preparada")
        return copy.deepcopy(self.respuestas[evento["idempotency_key"]])


def llm(etiqueta: str, confianza: float = 0.9, **datos) -> Clasificacion:
    return Clasificacion(etiqueta, f"falso: {etiqueta}", confianza, "llm", DatosConversacion(**datos))


class Entorno:
    def __init__(self, tmp_path: Path, cfg, clasificador):
        self.cfg = cfg
        self.carpeta = tmp_path / "salida"
        self.db = self.carpeta / "estado.sqlite"
        self.clasificador = clasificador

    def procesar(self, evento: dict) -> dict:
        estado = Estado(self.db)
        try:
            grafo = construir_grafo(self.cfg, estado, self.clasificador, Salida(self.carpeta))
            return grafo.invoke({"evento": evento})["decision"]
        finally:
            estado.cerrar()

    def decisiones(self) -> list[dict]:
        return _leer(self.carpeta / "decisiones.jsonl")

    def ordenes(self) -> list[dict]:
        return _leer(self.carpeta / "ordenes.jsonl")

    def ordenes_de(self, event_id: str) -> list[dict]:
        return [o for o in self.ordenes() if o["event_id"] == event_id]


def _leer(ruta: Path) -> list[dict]:
    if not ruta.exists():
        return []
    return [json.loads(l) for l in ruta.read_text(encoding="utf-8").splitlines() if l.strip()]


@pytest.fixture
def entorno(tmp_path, cfg):
    def crear(respuestas: dict[str, Clasificacion] | None = None) -> Entorno:
        return Entorno(tmp_path, cfg, ClasificadorFalso(respuestas))
    return crear


# --- Validadores de los esquemas oficiales -------------------------------------------------------------------------

VALIDADOR_DECISION = Draft202012Validator(json.loads((RAIZ / "esquemas" / "decision.schema.json").read_text(encoding="utf-8")))
VALIDADOR_EVENTO = Draft202012Validator(json.loads((RAIZ / "esquemas" / "evento.schema.json").read_text(encoding="utf-8")))


def _validadores_openapi() -> dict[str, Draft202012Validator]:
    api = yaml.safe_load((RAIZ / "esquemas" / "crm-openapi.yaml").read_text(encoding="utf-8"))
    validadores = {}
    for camino in api["paths"].values():
        for op in camino.values():
            esquema = op["requestBody"]["content"]["application/json"]["schema"]
            validadores[op["operationId"]] = Draft202012Validator(esquema)
    return validadores


VALIDADORES_ORDEN = _validadores_openapi()


def errores_de_formato(decisiones: list[dict], ordenes: list[dict]) -> list[str]:
    """Todo lo que no cumple decision.schema.json o el requestBody de la operación en el OpenAPI."""
    errores = [f"decisión {d.get('event_id')}: {e.message}" for d in decisiones for e in VALIDADOR_DECISION.iter_errors(d)]
    for o in ordenes:
        for campo in ("orden_id", "event_id", "operacion", "idempotency_key", "cuerpo"):
            if campo not in o:
                errores.append(f"orden sin {campo}: {o}")
        v = VALIDADORES_ORDEN.get(o.get("operacion"))
        if v is None:
            errores.append(f"operación desconocida {o.get('operacion')}")
            continue
        errores += [f"{o['operacion']} {o['orden_id']}: {e.message}" for e in v.iter_errors(o["cuerpo"])]
    ids = [o["orden_id"] for o in ordenes]
    if len(ids) != len(set(ids)):
        errores.append("orden_id repetido")
    claves = [o["idempotency_key"] for o in ordenes]
    if len(claves) != len(set(claves)):
        errores.append("idempotency_key repetida")
    for d in decisiones:
        for oid in d["ordenes"]:
            if oid not in ids:
                errores.append(f"la decisión {d['event_id']} referencia una orden inexistente {oid}")
    return errores
