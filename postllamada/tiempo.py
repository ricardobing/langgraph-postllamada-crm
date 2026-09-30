"""Cálculo de fechas: ventana de llamadas, plazos y días hábiles (R3).

Funciones puras: reciben la configuración y un instante con zona horaria, y devuelven otro instante en
Europe/Madrid. Toda la aritmética se hace en la zona de la campaña para que los cambios de hora (DST) no desplacen
la hora de pared.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .config import Config


def a_local(instante: datetime, cfg: Config) -> datetime:
    return instante.astimezone(cfg.zona)


def en_ventana(instante: datetime, cfg: Config) -> bool:
    """True si se puede llamar en ese instante. Los extremos de la franja cuentan (enunciado §3)."""
    local = a_local(instante, cfg)
    franja = cfg.ventana[local.weekday()]
    if franja is None:
        return False
    desde, hasta = franja
    hora = local.time().replace(tzinfo=None)
    return desde <= hora <= hasta


def siguiente_en_ventana(instante: datetime, cfg: Config) -> datetime:
    """El primer instante >= `instante` que cae dentro de la ventana de llamadas."""
    local = a_local(instante, cfg)
    if en_ventana(local, cfg):
        return local
    # Probamos la franja de hoy (si aún no abrió) y las de los 7 días siguientes.
    for dias in range(0, 8):
        dia = (local + timedelta(days=dias)).date()
        franja = cfg.ventana[dia.weekday()]
        if franja is None:
            continue
        apertura = datetime.combine(dia, franja[0], tzinfo=cfg.zona)
        if apertura >= local:
            return apertura
    raise ValueError("la configuración no tiene ninguna franja de llamadas")


def primero_en_rango(desde: datetime, hasta: datetime, preferido: datetime, cfg: Config) -> datetime:
    """Instante para un reintento con rango [desde, hasta] (ocupado, cortada).

    1. El preferido, si cae en ventana y dentro del rango.
    2. Si no, el primer instante del rango que caiga en ventana.
    3. Si el rango entero queda fuera de la ventana, la siguiente apertura (la ventana manda: fuera de ella ninguna
       llamada es válida).
    """
    if desde <= preferido <= hasta and en_ventana(preferido, cfg):
        return a_local(preferido, cfg)
    candidato = siguiente_en_ventana(desde, cfg)
    return candidato


def sumar_tiempo(instante: datetime, delta: timedelta, cfg: Config) -> datetime:
    """Suma tiempo real transcurrido (plazos en horas o minutos: separación entre intentos, 48 h naturales…).

    Se suma en UTC: en Python, sumar un timedelta a una fecha con zona suma "hora de reloj", y en el día del cambio
    de hora eso da una hora de más o de menos.
    """
    return (instante.astimezone(timezone.utc) + delta).astimezone(cfg.zona)


def sumar_dias_naturales(instante: datetime, dias: int, cfg: Config) -> datetime:
    """Suma días de calendario manteniendo la hora de pared ("vence en 2 días")."""
    local = a_local(instante, cfg)
    return datetime.combine(local.date() + timedelta(days=dias), local.timetz().replace(tzinfo=None), tzinfo=cfg.zona)


def sumar_dias_habiles(instante: datetime, dias: int, cfg: Config) -> datetime:
    """Suma días hábiles (los de `dias_habiles`; el sábado no cuenta) manteniendo la hora de pared."""
    local = a_local(instante, cfg)
    fecha = local.date()
    restantes = dias
    while restantes > 0:
        fecha += timedelta(days=1)
        if fecha.weekday() in cfg.dias_habiles:
            restantes -= 1
    return datetime.combine(fecha, local.timetz().replace(tzinfo=None), tzinfo=cfg.zona)


def iso(instante: datetime, cfg: Config) -> str:
    """ISO 8601 con offset explícito, en la zona de la campaña y sin microsegundos."""
    return a_local(instante, cfg).replace(microsecond=0).isoformat()
