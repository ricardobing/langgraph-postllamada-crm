"""Jev (TypeSafe, vía OpenRouter) como añadido OPCIONAL: solo con JEV_ACTIVADO=1 y OPENROUTER_API_KEY.

Jev no genera texto: recibe el estado y una pregunta con opciones y devuelve la opción elegida con su probabilidad y
una confianza. Se usa en tres casos:
1. **Duda:** si el modelo principal devuelve confianza < UMBRAL_DUDA, se consulta a Jev y se queda la opinión más
   segura. El motivo registra las dos.
2. **Caída:** si el modelo principal falla del todo, clasifica Jev en lugar de mandar la llamada a revisión.
3. **Modo rápido** (JEV_MODO=rapido): Jev decide primero y, si está muy seguro de una etiqueta que no necesita datos,
   se evita la llamada al modelo principal.

Si Jev falla, no pasa nada: se sigue con lo que hubiera sin él. El sistema completo funciona sin este módulo (el
enunciado pide un modelo de OpenAI; Jev es un añadido que no puede ser imprescindible).
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Callable

import httpx
import yaml

from .llm import ErrorClasificacion
from .tipos import Clasificacion, DatosConversacion

RUTA_CRITERIOS = Path(__file__).resolve().parent.parent / "prompts" / "jev_criterios.yaml"
URL_DECISIONES = "https://openrouter.ai/api/alpha/decisions"
MODELO_JEV = "typesafe/jev-1.13"  # versión fijada, no el alias "latest"
UMBRAL_DUDA = 0.75     # por debajo, el modelo principal "duda" y se consulta a Jev
UMBRAL_RAPIDO = 0.90   # modo rápido: por encima, Jev decide solo
MODOS = ("segunda_opinion", "rapido")
# Etiquetas que no necesitan nada extraído de la conversación: las órdenes solo dependen de la etiqueta. Las demás
# (callback → hora, documentación → email, cortada → nota…) siempre pasan por el modelo principal, que extrae.
ETIQUETAS_SIN_DATOS = frozenset({"no_contactar", "descartado", "persona_equivocada"})

Transporte = Callable[[dict], dict]  # recibe el cuerpo de la petición y devuelve el JSON de respuesta


def _transporte_http(cuerpo: dict) -> dict:
    r = httpx.post(URL_DECISIONES, json=cuerpo, timeout=15,
                   headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"})
    r.raise_for_status()
    return r.json()


class Jev:
    def __init__(self, transporte: Transporte = _transporte_http):
        self.transporte = transporte
        self.criterios = yaml.safe_load(RUTA_CRITERIOS.read_text(encoding="utf-8"))
        self.consultas = 0
        self.costo_usd = 0.0  # OpenRouter lo informa en usage.cost, para medir en la evaluación

    def decidir(self, evento: dict) -> tuple[str, float]:
        """Devuelve (etiqueta, confianza). Lanza excepción si la respuesta no sirve."""
        transcripcion = "\n".join(f"{m.get('role')}: {m.get('message')}" for m in evento.get("transcript") or [])
        respuesta = self.transporte({
            "model": MODELO_JEV,
            "state": {"transcripcion": transcripcion, "notas_del_agente": (evento.get("agent_outcome") or {}).get("slots_snapshot") or {}},
            "questions": {"etiqueta": {"type": "choice", "instructions": self.criterios["instrucciones"],
                                       "criteria": self.criterios["criterios"]}},
        })
        self.consultas += 1
        self.costo_usd += float((respuesta.get("usage") or {}).get("cost") or 0)
        respuesta_etiqueta = respuesta["answers"]["etiqueta"]
        etiqueta = respuesta_etiqueta["choice"]
        if etiqueta not in self.criterios["criterios"]:
            raise ValueError(f"Jev devolvió una opción desconocida: {etiqueta}")
        probabilidades = respuesta_etiqueta.get("probabilities") or {}
        confianza = float(probabilidades.get(etiqueta, respuesta_etiqueta.get("confidence", 0.0)))
        return etiqueta, max(0.0, min(1.0, confianza))


def _motivo(criterio: str) -> str:
    """El criterio de la etiqueta, sin las aclaraciones entre paréntesis (son para Jev, no para el CRM)."""
    return re.sub(r"\s*\([^)]*\)", "", criterio).rstrip(".")


class ClasificadorConJev:
    """Envuelve al clasificador principal (el de OpenAI) sin cambiar su interfaz: el grafo no sabe que existe.

    Modos:
    - ``segunda_opinion``: primero el modelo principal. Jev solo se consulta si el principal duda o se cae.
    - ``rapido``: primero Jev (≈0,4 s). Si está muy seguro de una etiqueta que no necesita datos extraídos, se
      evita la llamada al modelo principal. Si no, sigue como ``segunda_opinion``, reutilizando la opinión de Jev
      ya obtenida (Jev se consulta una sola vez por evento).
    """

    def __init__(self, principal, jev: Jev | None = None, modo: str = "segunda_opinion"):
        if modo not in MODOS:
            raise ValueError(f"modo de Jev desconocido: {modo} (válidos: {', '.join(MODOS)})")
        self.principal = principal
        self.jev = jev or Jev()
        self.modo = modo

    def _opinar(self, evento: dict) -> tuple[str, float] | None:
        try:
            return self.jev.decidir(evento)
        except Exception:  # Jev es un añadido: si falla, se sigue como si no existiera
            return None

    def clasificar(self, evento: dict, zona) -> Clasificacion:
        opinion = None
        if self.modo == "rapido":
            opinion = self._opinar(evento)
            if opinion and opinion[0] in ETIQUETAS_SIN_DATOS and opinion[1] >= UMBRAL_RAPIDO:
                etiqueta, confianza = opinion
                return Clasificacion(etiqueta, f"Jev ({confianza:.2f}): {_motivo(self.jev.criterios['criterios'][etiqueta])}",
                                     round(confianza, 2), "jev", DatosConversacion())
        try:
            clasif = self.principal.clasificar(evento, zona)
        except ErrorClasificacion:
            opinion = opinion or self._opinar(evento)
            if opinion is None:
                raise
            etiqueta, confianza = opinion
            return Clasificacion(etiqueta, f"clasificada por Jev (el modelo principal no respondió): {etiqueta}",
                                 round(confianza, 2), "jev", DatosConversacion())
        if clasif.confianza >= UMBRAL_DUDA:
            return clasif
        opinion = opinion or self._opinar(evento)
        if opinion is None:
            return clasif
        etiqueta, confianza = opinion
        if etiqueta == clasif.etiqueta:
            return Clasificacion(clasif.etiqueta, f"{clasif.motivo} (Jev coincide, {confianza:.2f})",
                                 round(max(clasif.confianza, confianza), 2), clasif.fuente, clasif.datos)
        if confianza > clasif.confianza:
            # Se queda la etiqueta de Jev, pero los datos extraídos por el LLM (hora del callback, nota…) se conservan.
            return Clasificacion(etiqueta, f"Jev ({confianza:.2f}) corrige a «{etiqueta}» la duda del modelo «{clasif.etiqueta}» ({clasif.confianza:.2f}): {clasif.motivo}",
                                 round(confianza, 2), "jev", clasif.datos)
        return Clasificacion(clasif.etiqueta, f"{clasif.motivo} (Jev proponía «{etiqueta}» con {confianza:.2f})",
                             clasif.confianza, clasif.fuente, clasif.datos)
