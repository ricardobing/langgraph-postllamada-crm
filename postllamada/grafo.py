"""El orquestador post-llamada como grafo de LangGraph.

    START → preparar ─┬─ otra_organizacion ──────────────────────────────────┐
                      ├─ reentrega ──────────────────────────────────────────┤
                      ├─ mensaje ────────────────────────────────────────────┤
                      └─ clasificar_senalizacion ─┬─ planificar_llamada ─────┤
                                                  └─ leer_conversacion ─┘    │
                                                                             ▼
                                                               registrar_y_emitir → END

- Cada nodo es una función que recibe el estado y devuelve SOLO los campos que cambia.
- Las aristas condicionales deciden el camino según el tipo de evento y si la telefonía basta para clasificar.
- La memoria entre procesos NO está en el grafo: vive en SQLite (`estado.py`). El grafo lee esa memoria al principio
  (`preparar`) y la escribe al final (`registrar_y_emitir`), en una sola transacción.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from . import ordenes as planificador
from .config import Config
from .estado import Estado
from .llm import Clasificador, ErrorClasificacion
from .salida import Salida
from .senalizacion import clasificar_por_senalizacion
from .tipos import Clasificacion, ContextoLead, Efecto

Ruta = Literal["otra_organizacion", "reentrega", "mensaje", "llamada"]


class EstadoGrafo(TypedDict, total=False):
    evento: dict                        # entrada, tal cual
    ruta: Ruta                          # qué tipo de evento es (lo decide `preparar`)
    contexto: ContextoLead              # lo que se recuerda del lead (SQLite)
    decision_previa: dict | None        # si es una reentrega, la decisión original
    clasificacion: Clasificacion | None
    ordenes: list[dict]                 # órdenes planificadas
    efectos: list[Efecto]               # cambios de estado a persistir
    decision: dict                      # la línea de decisiones.jsonl (la escribe el último nodo)


def construir_grafo(cfg: Config, estado: Estado, clasificador: Clasificador | None, salida: Salida):
    """Arma y compila el grafo. Las dependencias (config, SQLite, LLM, salida) se inyectan: en los tests se usan
    un SQLite temporal y un clasificador falso."""

    # --- Nodos -----------------------------------------------------------------------------------------------------

    def preparar(s: EstadoGrafo) -> dict:
        """Decide qué tipo de evento es y carga la memoria del lead."""
        ev = s["evento"]
        lead = ev["lead"]
        if ev["organization_id"] != cfg.organization_id:
            return {"ruta": "otra_organizacion"}  # R6: ni se lee ni se escribe su memoria
        previa = estado.hecho_previo(ev["idempotency_key"])
        if previa is not None:
            return {"ruta": "reentrega", "decision_previa": previa}  # R5: se decide por el hecho, no por delivery_attempt
        ruta: Ruta = "mensaje" if ev["type"] == "message.received" else "llamada"
        return {"ruta": ruta, "contexto": estado.contexto(ev["organization_id"], lead["contact_id"])}

    def otra_organizacion(s: EstadoGrafo) -> dict:
        clasif = Clasificacion("no_aplica", f"evento de otra organización ({s['evento']['organization_id']}): no se actúa", 1.0, "estado")
        return {"clasificacion": clasif, "ordenes": [], "efectos": []}

    def reentrega(s: EstadoGrafo) -> dict:
        previa = s["decision_previa"] or {}
        clasif = Clasificacion(previa.get("etiqueta", "otro"), f"reentrega de {s['evento']['idempotency_key']}: ya procesado, sin órdenes nuevas",
                               float(previa.get("confianza", 1.0)), "estado")
        return {"clasificacion": clasif, "ordenes": [], "efectos": []}

    def mensaje(s: EstadoGrafo) -> dict:
        plan = planificador.planificar_mensaje(s["evento"], s["contexto"], cfg)
        n = len(plan.ordenes)
        motivo = f"el lead respondió por WhatsApp: se cancelan {n} recordatorio(s) pendiente(s)" if n else "el lead respondió por WhatsApp: no tenía recordatorios pendientes"
        clasif = Clasificacion("no_aplica", motivo, 1.0, "estado")
        return {"clasificacion": clasif, "ordenes": plan.ordenes, "efectos": plan.efectos}

    def clasificar_senalizacion(s: EstadoGrafo) -> dict:
        """Casos que decide la telefonía (486, 603, 408/480, 5xx, buzón, IVR). None = hay que leer la conversación."""
        return {"clasificacion": clasificar_por_senalizacion(s["evento"])}

    def leer_conversacion(s: EstadoGrafo) -> dict:
        ev = s["evento"]
        cita = (ev.get("agent_outcome") or {}).get("appointment")
        try:
            if clasificador is None:
                raise ErrorClasificacion("no hay modelo configurado")
            clasif = clasificador.clasificar(ev, cfg.zona)
        except ErrorClasificacion as e:
            # R8: sin modelo no se rompe. Sin cita, la llamada va a revisión humana (N4).
            if cita:
                return {"clasificacion": Clasificacion("visita_reservada", "cita creada por el agente durante la llamada", 0.9, "sin_llm")}
            return {"clasificacion": Clasificacion("otro", f"no se pudo leer la conversación: {e}"[:300], 0.0, "sin_llm")}
        # Caso 1: si el agente creó la cita, es visita_reservada. Solo una baja manda sobre eso (casos.md, 10 contra todo).
        if cita and clasif.etiqueta != "no_contactar":
            clasif = Clasificacion("visita_reservada", f"visita reservada: cita {cita.get('appointment_id')} creada durante la llamada para el {cita.get('start_time')}",
                                   max(clasif.confianza, 0.95), clasif.fuente, clasif.datos)
        return {"clasificacion": clasif}

    def planificar_llamada(s: EstadoGrafo) -> dict:
        plan = planificador.planificar_llamada(s["evento"], s["clasificacion"], s["contexto"], cfg)
        return {"ordenes": plan.ordenes, "efectos": plan.efectos}

    def registrar_y_emitir(s: EstadoGrafo) -> dict:
        """Una transacción SQLite con todo lo del evento; después, las líneas de salida."""
        ev = s["evento"]
        clasif = s["clasificacion"]
        decision = {
            "event_id": ev["event_id"],
            "call_id": (ev.get("telephony") or {}).get("call_id"),
            "etiqueta": clasif.etiqueta,
            "motivo": clasif.motivo,
            "confianza": clasif.confianza,
            "ordenes": [],
        }
        registrar_hecho = s["ruta"] in ("llamada", "mensaje")
        nuevas = estado.guardar(ev, decision, s.get("ordenes", []), s.get("efectos", []), registrar_hecho) if s["ruta"] != "otra_organizacion" else []
        decision["ordenes"] = [o["orden_id"] for o in nuevas]
        salida.escribir(decision, nuevas)
        return {"decision": decision}

    # --- Aristas ---------------------------------------------------------------------------------------------------

    def por_ruta(s: EstadoGrafo) -> str:
        return {"otra_organizacion": "otra_organizacion", "reentrega": "reentrega", "mensaje": "mensaje", "llamada": "clasificar_senalizacion"}[s["ruta"]]

    def tras_senalizacion(s: EstadoGrafo) -> str:
        return "planificar_llamada" if s.get("clasificacion") else "leer_conversacion"

    g = StateGraph(EstadoGrafo)
    for nombre, fn in [
        ("preparar", preparar), ("otra_organizacion", otra_organizacion), ("reentrega", reentrega), ("mensaje", mensaje),
        ("clasificar_senalizacion", clasificar_senalizacion), ("leer_conversacion", leer_conversacion),
        ("planificar_llamada", planificar_llamada), ("registrar_y_emitir", registrar_y_emitir),
    ]:
        g.add_node(nombre, fn)
    g.add_edge(START, "preparar")
    g.add_conditional_edges("preparar", por_ruta, ["otra_organizacion", "reentrega", "mensaje", "clasificar_senalizacion"])
    g.add_conditional_edges("clasificar_senalizacion", tras_senalizacion, ["planificar_llamada", "leer_conversacion"])
    g.add_edge("leer_conversacion", "planificar_llamada")
    for nodo in ("otra_organizacion", "reentrega", "mensaje", "planificar_llamada"):
        g.add_edge(nodo, "registrar_y_emitir")
    g.add_edge("registrar_y_emitir", END)
    return g.compile()


def fecha_evento(evento: dict) -> datetime:
    return datetime.fromisoformat(evento["occurred_at"])
