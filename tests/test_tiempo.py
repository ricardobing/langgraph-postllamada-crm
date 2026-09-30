"""Capa 1: fechas, ventana de llamadas y plazos (R3)."""
from datetime import datetime, timedelta

import pytest

from postllamada import tiempo


def madrid(texto: str) -> datetime:
    return datetime.fromisoformat(texto)


@pytest.mark.parametrize("instante, esperado", [
    ("2026-09-15T10:00:00+02:00", True),   # martes, apertura (inclusive)
    ("2026-09-15T20:00:00+02:00", True),   # martes, cierre (inclusive)
    ("2026-09-15T20:00:01+02:00", False),
    ("2026-09-15T09:59:59+02:00", False),
    ("2026-09-19T14:00:00+02:00", True),   # sábado, cierre 14:00 inclusive
    ("2026-09-19T14:01:00+02:00", False),
    ("2026-09-20T12:00:00+02:00", False),  # domingo: no se llama
    ("2026-09-15T08:30:00+00:00", True),   # otra zona: 10:30 en Madrid
])
def test_en_ventana(cfg, instante, esperado):
    assert tiempo.en_ventana(madrid(instante), cfg) is esperado


@pytest.mark.parametrize("instante, esperado", [
    ("2026-09-15T12:12:00+02:00", "2026-09-15T12:12:00+02:00"),  # ya está dentro
    ("2026-09-15T20:30:00+02:00", "2026-09-16T10:00:00+02:00"),  # martes noche → miércoles 10:00
    ("2026-09-15T07:00:00+02:00", "2026-09-15T10:00:00+02:00"),  # madrugada → mismo día 10:00
    ("2026-09-18T21:00:00+02:00", "2026-09-19T10:00:00+02:00"),  # viernes noche → sábado 10:00
    ("2026-09-19T15:00:00+02:00", "2026-09-21T10:00:00+02:00"),  # sábado tarde → lunes (domingo cerrado)
    ("2026-09-20T11:00:00+02:00", "2026-09-21T10:00:00+02:00"),  # domingo → lunes
])
def test_siguiente_en_ventana(cfg, instante, esperado):
    assert tiempo.iso(tiempo.siguiente_en_ventana(madrid(instante), cfg), cfg) == esperado


def test_primero_en_rango_prefiere_el_punto_medio(cfg):
    t = madrid("2026-09-15T10:31:00+02:00")
    r = tiempo.primero_en_rango(t + timedelta(minutes=30), t + timedelta(minutes=90), t + timedelta(minutes=60), cfg)
    assert tiempo.iso(r, cfg) == "2026-09-15T11:31:00+02:00"  # el ejemplo resuelto


def test_primero_en_rango_si_el_preferido_cae_fuera_usa_el_primer_instante_valido(cfg):
    t = madrid("2026-09-15T19:10:00+02:00")  # +60 = 20:10 (fuera); +30 = 19:40 (dentro)
    r = tiempo.primero_en_rango(t + timedelta(minutes=30), t + timedelta(minutes=90), t + timedelta(minutes=60), cfg)
    assert tiempo.iso(r, cfg) == "2026-09-15T19:40:00+02:00"


def test_primero_en_rango_todo_fuera_va_a_la_siguiente_apertura(cfg):
    t = madrid("2026-09-15T19:45:00+02:00")  # +30 = 20:15, ya fuera
    r = tiempo.primero_en_rango(t + timedelta(minutes=30), t + timedelta(minutes=90), t + timedelta(minutes=60), cfg)
    assert tiempo.iso(r, cfg) == "2026-09-16T10:00:00+02:00"


def test_dias_habiles_saltan_sabado_y_domingo(cfg):
    viernes = madrid("2026-09-18T16:00:00+02:00")
    assert tiempo.iso(tiempo.sumar_dias_habiles(viernes, 3, cfg), cfg) == "2026-09-23T16:00:00+02:00"  # miércoles
    martes = madrid("2026-09-15T16:42:00+02:00")
    assert tiempo.iso(tiempo.sumar_dias_habiles(martes, 3, cfg), cfg) == "2026-09-18T16:42:00+02:00"


def test_sumar_tiempo_real_en_el_cambio_de_hora(cfg):
    # 25/10/2026 03:00 CEST → 02:00 CET. Sábado 24 a las 20:00 + 48 h reales = lunes 26 a las 19:00 (hora de invierno).
    t = madrid("2026-10-24T20:00:00+02:00")
    assert tiempo.iso(tiempo.sumar_tiempo(t, timedelta(hours=48), cfg), cfg) == "2026-10-26T19:00:00+01:00"


def test_dias_naturales_mantienen_la_hora_de_pared_en_el_cambio_de_hora(cfg):
    t = madrid("2026-10-24T11:00:00+02:00")
    assert tiempo.iso(tiempo.sumar_dias_naturales(t, 2, cfg), cfg) == "2026-10-26T11:00:00+01:00"


def test_iso_lleva_offset_y_sin_microsegundos(cfg):
    assert tiempo.iso(madrid("2026-09-15T08:31:00.123456+00:00"), cfg) == "2026-09-15T10:31:00+02:00"
