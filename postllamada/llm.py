"""Lectura de la conversación con un modelo de OpenAI (R1), con salida estructurada y validada.

- El prompt vive en `prompts/clasificar_llamada.md` (versionado en el repo).
- El modelo solo INTERPRETA: devuelve etiqueta, motivo, confianza y datos. Las fechas y las órdenes las calcula el
  código.
- Salida con JSON Schema estricto + validación con pydantic. Si el JSON no es válido o la API falla: reintentos, y
  después el modelo de respaldo (si está configurado).
- Si todo falla, se lanza `ErrorClasificacion`: el grafo lo convierte en `otro` + revisión humana (nunca rompe).
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, Field, ValidationError

from .tipos import Clasificacion, DatosConversacion

RAIZ = Path(__file__).resolve().parent.parent
RUTA_PROMPT = RAIZ / "prompts" / "clasificar_llamada.md"

ETIQUETAS_CONVERSACION = [
    "no_contactar", "persona_equivocada", "descartado", "callback", "documentacion_enviada",
    "documentacion_pendiente", "visita_sin_confirmar", "cortada", "otro",
]
DIAS_SEMANA = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


class ErrorClasificacion(Exception):
    pass


class Clasificador(Protocol):
    """Lo que el grafo necesita del LLM. En los tests se inyecta uno falso y determinista."""

    def clasificar(self, evento: dict, zona) -> Clasificacion: ...


# --- Esquema de salida (el mismo se envía como JSON Schema estricto y se valida con pydantic) ---------------------

class _Callback(BaseModel):
    fecha: str | None
    hora: str | None
    hora_ambigua: bool
    texto_literal: str | None


class SalidaLLM(BaseModel):
    etiqueta: Literal[tuple(ETIQUETAS_CONVERSACION)]  # type: ignore[valid-type]
    motivo: str
    confianza: float = Field(ge=0, le=1)
    callback: _Callback | None
    visita_acordada: str | None
    whatsapp_rechazado: bool
    email: str | None
    nota_contexto: str


def _nullable(schema: dict) -> dict:
    return {"anyOf": [schema, {"type": "null"}]}


ESQUEMA_JSON = {
    "type": "object",
    "additionalProperties": False,
    "required": ["etiqueta", "motivo", "confianza", "callback", "visita_acordada", "whatsapp_rechazado", "email", "nota_contexto"],
    "properties": {
        "etiqueta": {"type": "string", "enum": ETIQUETAS_CONVERSACION},
        "motivo": {"type": "string"},
        "confianza": {"type": "number"},
        "callback": _nullable({
            "type": "object",
            "additionalProperties": False,
            "required": ["fecha", "hora", "hora_ambigua", "texto_literal"],
            "properties": {
                "fecha": _nullable({"type": "string"}),
                "hora": _nullable({"type": "string"}),
                "hora_ambigua": {"type": "boolean"},
                "texto_literal": _nullable({"type": "string"}),
            },
        }),
        "visita_acordada": _nullable({"type": "string"}),
        "whatsapp_rechazado": {"type": "boolean"},
        "email": _nullable({"type": "string"}),
        "nota_contexto": {"type": "string"},
    },
}


def mensaje_usuario(evento: dict, zona) -> str:
    """Lo que ve el modelo: instante de referencia en Madrid, datos del lead, notas del agente y transcripción."""
    t = datetime.fromisoformat(evento["occurred_at"]).astimezone(zona)
    lead = evento.get("lead") or {}
    outcome = evento.get("agent_outcome") or {}
    lineas = [f"[{m.get('time_in_call_secs', '?')}s] {m.get('role')}: {m.get('message')}" for m in evento.get("transcript") or []]
    return "\n".join([
        f"Instante de referencia (fin de la llamada): {DIAS_SEMANA[t.weekday()]} {t.isoformat()} (Europe/Madrid).",
        f"Lead: {lead.get('full_name')} · inmueble: {lead.get('property_address')} ({lead.get('property_ref')}).",
        f"Cita creada por el agente durante la llamada: {'sí' if outcome.get('appointment') else 'no'}.",
        f"Notas del agente (pistas parciales, pueden estar obsoletas): {json.dumps(outcome.get('slots_snapshot') or {}, ensure_ascii=False)}",
        "",
        "Transcripción:",
        *(lineas or ["(vacía)"]),
    ])


def a_clasificacion(salida: SalidaLLM, fuente: str) -> Clasificacion:
    cb = salida.callback
    return Clasificacion(
        etiqueta=salida.etiqueta,
        motivo=salida.motivo.strip() or salida.etiqueta,
        confianza=round(float(salida.confianza), 2),
        fuente=fuente,  # type: ignore[arg-type]
        datos=DatosConversacion(
            callback_fecha=cb.fecha if cb else None,
            callback_hora=cb.hora if cb else None,
            callback_hora_ambigua=bool(cb and cb.hora_ambigua),
            callback_texto=cb.texto_literal if cb else None,
            visita_acordada=salida.visita_acordada,
            whatsapp_rechazado=salida.whatsapp_rechazado,
            email=salida.email,
            nota_contexto=salida.nota_contexto.strip() or None,
        ),
    )


class ClasificadorOpenAI:
    """Cliente del SDK oficial de OpenAI.

    Con la configuración por defecto habla con OpenAI (OPENAI_API_KEY + MODELO). `OPENAI_BASE_URL` permite apuntar
    a otro servidor compatible durante el desarrollo sin tocar código.
    """

    def __init__(self, modelo: str, modelo_respaldo: str | None = None, intentos: int = 3, timeout: float = 30.0):
        from openai import OpenAI  # import tardío: los tests no necesitan el SDK configurado

        self.cliente = OpenAI(
            api_key=os.environ.get("OPENAI_API_KEY"),
            base_url=os.environ.get("OPENAI_BASE_URL") or None,
            timeout=timeout,
            max_retries=0,  # los reintentos los controlamos aquí, junto con la validación del JSON
        )
        self.modelos = [m for m in (modelo, modelo_respaldo) if m]
        self.intentos = intentos
        self.prompt = RUTA_PROMPT.read_text(encoding="utf-8")
        self.costo_usd = 0.0  # si el proveedor lo informa (OpenRouter), para medir en la evaluación

    @classmethod
    def desde_entorno(cls) -> "ClasificadorOpenAI":
        return cls(
            modelo=os.environ.get("MODELO") or "gpt-6-luna",
            modelo_respaldo=os.environ.get("MODELO_RESPALDO") or None,
        )

    def clasificar(self, evento: dict, zona) -> Clasificacion:
        errores: list[str] = []
        for i, modelo in enumerate(self.modelos):
            for intento in range(self.intentos):
                try:
                    salida = self._llamar(modelo, evento, zona)
                    return a_clasificacion(salida, "llm" if i == 0 else "respaldo_llm")
                except (ValidationError, json.JSONDecodeError, KeyError, IndexError, TypeError) as e:
                    errores.append(f"{modelo}: respuesta inválida ({type(e).__name__})")
                except Exception as e:  # red, cuota, timeout…: se reintenta igual
                    errores.append(f"{modelo}: {type(e).__name__}: {str(e)[:120]}")
                time.sleep(min(2 ** intento, 4) * 0.5)
        raise ErrorClasificacion("; ".join(errores[-3:]))

    def _llamar(self, modelo: str, evento: dict, zona) -> SalidaLLM:
        respuesta = self.cliente.chat.completions.create(
            model=modelo,
            messages=[
                {"role": "system", "content": self.prompt},
                {"role": "user", "content": mensaje_usuario(evento, zona)},
            ],
            response_format={"type": "json_schema", "json_schema": {"name": "clasificacion_llamada", "strict": True, "schema": ESQUEMA_JSON}},
            # Sin temperature ni seed: los modelos de razonamiento de OpenAI rechazan parámetros de muestreo.
        )
        uso = getattr(respuesta, "usage", None)
        costo = getattr(uso, "cost", None) if uso else None
        if isinstance(costo, (int, float)):
            self.costo_usd += costo
        contenido = respuesta.choices[0].message.content
        return SalidaLLM.model_validate(json.loads(contenido))
