"""Clasificación por señalización de telefonía: reglas, sin LLM.

Casos 4, 5, 6, 11 y 13 de casos.md, más lo que el catálogo manda a `otro` (5xx, IVR). Si descolgó una persona
(o el detector no está seguro), devuelve None: esa llamada hay que leerla.
"""
from __future__ import annotations

from .tipos import Clasificacion

CONFIANZA_REGLA = 0.97  # la señalización es un hecho del operador, no una interpretación


def clasificar_por_senalizacion(evento: dict) -> Clasificacion | None:
    tel = evento.get("telephony") or {}
    sip = tel.get("sip_status_code")
    texto_sip = f"{sip} {tel.get('sip_status') or ''}".strip()
    amd = tel.get("amd") or {}
    resultado_amd = amd.get("result")

    if sip == 486:
        # LiveKit lo expone como USER_REJECTED, pero es "comunica", no un rechazo del lead.
        return Clasificacion("ocupado", f"{texto_sip}: la línea comunica", CONFIANZA_REGLA, "senalizacion")
    if sip == 603:
        return Clasificacion("rechazada", f"{texto_sip}: el lead rechazó la llamada antes de descolgar", CONFIANZA_REGLA, "senalizacion")
    if sip in (408, 480):
        return Clasificacion("sin_respuesta", f"{texto_sip}: nadie descolgó", CONFIANZA_REGLA, "senalizacion")
    if isinstance(sip, int) and 500 <= sip <= 599:
        return Clasificacion("otro", f"{texto_sip}: fallo del trunk antes de conectar", CONFIANZA_REGLA, "senalizacion")
    if sip != 200:
        return Clasificacion("otro", f"{texto_sip}: señalización no contemplada en el catálogo", 0.8, "senalizacion")

    # 200 OK: contestó alguien o algo. Un buzón también contesta con 200; la única pista es el AMD.
    if resultado_amd in ("machine-vm", "machine-unavailable"):
        fuente = amd.get("source") or "none"
        # Caso 13: con heuristic_regex el saludo puede ser ambiguo; da igual, manda el recuento de intentos.
        return Clasificacion("buzon", f"saltó el buzón de voz (AMD {resultado_amd}, {fuente})", CONFIANZA_REGLA if fuente == "livekit_amd" else 0.85, "senalizacion")
    if resultado_amd == "machine-ivr":
        return Clasificacion("otro", "contestó una centralita automática (IVR), no el lead", CONFIANZA_REGLA, "senalizacion")

    # human, uncertain ("se trata como persona"), not_run o sin AMD: hay que leer la conversación.
    if not evento.get("transcript"):
        return Clasificacion("otro", "descolgaron pero no hubo conversación que clasificar", 0.7, "senalizacion")
    return None
