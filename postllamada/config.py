"""Configuración de la campaña (config/campana.yaml) como objeto tipado.

Todo lo que es "política" (ventanas, intentos, plazos, canal de respaldo) sale de aquí: el código no tiene números
de negocio escritos a mano.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

# Claves de días del YAML en el orden de datetime.weekday() (lunes = 0).
DIAS = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]


@dataclass(frozen=True)
class Config:
    organization_id: str
    zona: ZoneInfo
    # Por día de la semana (0 = lunes): (desde, hasta) o None si ese día no se llama.
    ventana: tuple[tuple[time, time] | None, ...]
    max_intentos: int
    separacion_minima_horas: float
    ocupado_minutos_min: int
    ocupado_minutos_max: int
    cortada_minutos_min: int
    cortada_horas_max: float
    canal_respaldo: str
    dias_habiles: frozenset[int]
    documentacion_lead_horas: float
    seguimiento_comercial_dias_habiles: int
    confirmar_visita_margen_horas: float
    vencimiento_por_defecto_dias: int


def _hora(texto: str) -> time:
    horas, minutos = texto.split(":")
    return time(int(horas), int(minutos))


def cargar_config(ruta: str | Path = "config/campana.yaml") -> Config:
    datos = yaml.safe_load(Path(ruta).read_text(encoding="utf-8"))
    ventana = []
    for dia in DIAS:
        franja = datos["ventana_llamadas"].get(dia) or []
        ventana.append((_hora(franja[0]), _hora(franja[1])) if len(franja) == 2 else None)
    r = datos["reintentos"]
    return Config(
        organization_id=datos["campana"]["organization_id"],
        zona=ZoneInfo(datos["campana"]["zona_horaria"]),
        ventana=tuple(ventana),
        max_intentos=int(r["max_intentos"]),
        separacion_minima_horas=float(r["separacion_minima_horas"]),
        ocupado_minutos_min=int(r["ocupado_minutos_min"]),
        ocupado_minutos_max=int(r["ocupado_minutos_max"]),
        cortada_minutos_min=int(r["cortada_minutos_min"]),
        cortada_horas_max=float(r["cortada_horas_max"]),
        canal_respaldo=datos["canal_respaldo"],
        dias_habiles=frozenset(DIAS.index(d) for d in datos["dias_habiles"]),
        documentacion_lead_horas=float(datos["recordatorios"]["documentacion_lead_horas"]),
        seguimiento_comercial_dias_habiles=int(datos["recordatorios"]["seguimiento_comercial_dias_habiles"]),
        confirmar_visita_margen_horas=float(datos["tareas"]["confirmar_visita_margen_horas"]),
        vencimiento_por_defecto_dias=int(datos["tareas"]["vencimiento_por_defecto_dias"]),
    )
