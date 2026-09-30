"""Tipos del dominio que viajan por el grafo."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Etiqueta = Literal[
    "visita_reservada", "documentacion_enviada", "callback", "sin_respuesta", "ocupado", "buzon", "cortada",
    "visita_sin_confirmar", "persona_equivocada", "no_contactar", "rechazada", "documentacion_pendiente",
    "descartado", "otro", "no_aplica",
]

# Estado de cola que lleva cerrar_llamada, fijado por la etiqueta (casos.md). No se decide: se consulta.
ESTADO_COLA: dict[str, str] = {
    "visita_reservada": "successful",
    "documentacion_enviada": "completed",
    "documentacion_pendiente": "completed",
    "callback": "callback_requested",
    "sin_respuesta": "no_answer",
    "ocupado": "no_answer",
    "buzon": "no_answer",
    "cortada": "needs_review",
    "visita_sin_confirmar": "needs_review",
    "otro": "needs_review",
    "persona_equivocada": "failed",
    "no_contactar": "dnc",
    "rechazada": "refused",
    "descartado": "skipped",
}

# Etiquetas cuya acción natural es volver a llamar (sujetas al máximo de intentos, regla N3).
ETIQUETAS_CON_REINTENTO = {"sin_respuesta", "ocupado", "buzon", "cortada", "visita_sin_confirmar", "callback"}

# Etiquetas de "llamada cortada" que cuentan para la regla N4 (segunda cortada con el mismo lead).
ETIQUETAS_CORTADA = {"cortada", "visita_sin_confirmar"}


@dataclass
class DatosConversacion:
    """Lo que el LLM extrae de la conversación además de la etiqueta. Las fechas se resuelven en código."""
    callback_fecha: str | None = None        # YYYY-MM-DD
    callback_hora: str | None = None         # HH:MM (24 h)
    callback_hora_ambigua: bool = False      # "a las seis" sin "de la tarde / de la mañana"
    callback_texto: str | None = None        # tal como lo dijo el lead
    visita_acordada: str | None = None       # texto: "jueves 17 a las 17:00"
    whatsapp_rechazado: bool = False
    email: str | None = None
    nota_contexto: str | None = None


@dataclass
class Clasificacion:
    etiqueta: str
    motivo: str
    confianza: float
    fuente: Literal["senalizacion", "llm", "respaldo_llm", "jev", "sin_llm", "estado"]
    datos: DatosConversacion = field(default_factory=DatosConversacion)


@dataclass
class Recordatorio:
    reminder_id: str
    canal: str
    cuando: str  # ISO con offset


@dataclass
class ContextoLead:
    """Lo que se recuerda del lead de eventos anteriores (leído de SQLite antes de decidir)."""
    intentos_previos: int = 0
    cortadas_previas: int = 0
    dnc: bool = False
    whatsapp_rechazado: bool = False
    recordatorios_pendientes: list[Recordatorio] = field(default_factory=list)


@dataclass
class Efecto:
    """Cambio de estado a persistir junto con las órdenes (misma transacción)."""
    tipo: Literal["marcar_dnc", "marcar_whatsapp_rechazado", "crear_recordatorio", "cancelar_recordatorio"]
    datos: dict = field(default_factory=dict)
