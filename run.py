"""Punto de entrada: procesa UN evento y termina.

    python run.py eventos/01-call-ended-nuria.json

Código de salida: 0 si el evento se procesó (aunque se haya rechazado o haya ido a revisión humana), distinto de 0 si
no se pudo procesar (fichero ilegible, evento que no cumple el esquema, error inesperado). Un fallo en un evento no
deja estado a medias: la escritura en SQLite es transaccional (R8).
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

from dotenv import load_dotenv
from jsonschema import Draft202012Validator

from postllamada.config import cargar_config
from postllamada.estado import Estado
from postllamada.grafo import construir_grafo
from postllamada.salida import Salida

RAIZ = Path(__file__).resolve().parent


def validar_evento(evento: dict) -> list[str]:
    esquema = json.loads((RAIZ / "esquemas" / "evento.schema.json").read_text(encoding="utf-8"))
    return [f"{'/'.join(map(str, e.path)) or '(raíz)'}: {e.message}" for e in Draft202012Validator(esquema).iter_errors(evento)]


def crear_clasificador():
    """El modelo de OpenAI, si hay clave. Sin clave, el grafo no llama a ningún modelo y lo que haya que leer va a
    revisión humana (etiqueta `otro`)."""
    if not os.environ.get("OPENAI_API_KEY"):
        print("aviso: OPENAI_API_KEY no está definida; las llamadas con conversación irán a revisión humana", file=sys.stderr)
        return None
    from postllamada.llm import ClasificadorOpenAI

    clasificador = ClasificadorOpenAI.desde_entorno()
    if os.environ.get("JEV_ACTIVADO") == "1":  # añadido opcional, apagado por defecto (ver postllamada/jev.py)
        from postllamada.jev import MODOS, ClasificadorConJev

        modo = os.environ.get("JEV_MODO") or "segunda_opinion"
        if not os.environ.get("OPENROUTER_API_KEY"):
            print("aviso: JEV_ACTIVADO=1 sin OPENROUTER_API_KEY; sigo solo con el modelo de OpenAI", file=sys.stderr)
        elif modo not in MODOS:
            print(f"aviso: JEV_MODO={modo} no existe ({', '.join(MODOS)}); sigo solo con el modelo de OpenAI", file=sys.stderr)
        else:
            clasificador = ClasificadorConJev(clasificador, modo=modo)
    return clasificador


def procesar(ruta_evento: str) -> int:
    try:
        evento = json.loads(Path(ruta_evento).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"error: no se pudo leer el evento {ruta_evento}: {e}", file=sys.stderr)
        return 2
    errores = validar_evento(evento)
    if errores:
        print(f"error: el evento {ruta_evento} no cumple evento.schema.json: {errores[:3]}", file=sys.stderr)
        return 3

    cfg = cargar_config(os.environ.get("CONFIG_CAMPANA") or RAIZ / "config" / "campana.yaml")
    carpeta_salida = Path(os.environ.get("SALIDA_DIR") or "salida")
    # El estado vive junto a la salida: si se borra salida/ para empezar de cero, se borra también la memoria.
    estado = Estado(os.environ.get("ESTADO_DB") or carpeta_salida / "estado.sqlite")
    try:
        grafo = construir_grafo(cfg, estado, crear_clasificador(), Salida(carpeta_salida))
        resultado = grafo.invoke({"evento": evento})
        d = resultado["decision"]
        print(f"{d['event_id']}: {d['etiqueta']} ({len(d['ordenes'])} órdenes) · {d['motivo']}")
        return 0
    except Exception:
        traceback.print_exc()
        return 1
    finally:
        estado.cerrar()


if __name__ == "__main__":
    load_dotenv(RAIZ / ".env")
    if len(sys.argv) != 2:
        print("uso: python run.py <ruta-del-evento.json>", file=sys.stderr)
        sys.exit(64)
    sys.exit(procesar(sys.argv[1]))
