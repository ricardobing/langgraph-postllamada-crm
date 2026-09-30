"""Capa 4: casos sin ejemplo en eventos/ (los ⚠ de casos.md) y variantes con otros datos, horas y días.

Cada evento se construye a partir de uno real del lote, cambiando solo lo necesario, y se valida contra
evento.schema.json para que sea un evento posible.
"""
import copy
import itertools

import pytest

from conftest import VALIDADOR_EVENTO, cargar, errores_de_formato, llm

_contador = itertools.count(900)


def variante(base: str, occurred_at: str | None = None, contact_id: str | None = None, sip: int | None = None,
             amd: str | None = None, amd_fuente: str | None = None, transcript=None, appointment="sin_cambio",
             org: str | None = None, tipo: str | None = None, texto: str | None = None, idem: str | None = None) -> dict:
    ev = copy.deepcopy(cargar(base))
    n = next(_contador)
    ev["event_id"] = f"evt_x{n}"
    ev["idempotency_key"] = idem or f"lk-out-x{n}"
    if "telephony" in ev:
        ev["telephony"]["call_id"] = ev["idempotency_key"]
    if occurred_at:
        ev["occurred_at"] = occurred_at
        if "telephony" in ev:
            ev["telephony"]["ended_at"] = occurred_at
    if contact_id:
        ev["lead"]["contact_id"] = contact_id
    if org:
        ev["organization_id"] = org
    if sip is not None:
        ev["telephony"]["sip_status_code"] = sip
    if amd is not None:
        ev["telephony"]["amd"]["result"] = amd
    if amd_fuente is not None:
        ev["telephony"]["amd"]["source"] = amd_fuente
    if transcript is not None:
        ev["transcript"] = transcript
    if appointment != "sin_cambio":
        ev["agent_outcome"]["appointment"] = appointment
    if tipo == "message.received":
        ev = {k: v for k, v in ev.items() if k not in ("telephony", "transcript", "agent_outcome", "recording", "metrics")}
        ev["type"] = "message.received"
        ev["message"] = {"channel": "whatsapp", "text": texto or "hola"}
    errores = [e.message for e in VALIDADOR_EVENTO.iter_errors(ev)]
    assert not errores, errores
    return ev


def ops(e, decision) -> list[str]:
    return [o["operacion"] for o in e.ordenes_de(decision["event_id"])]


def cuerpo(e, decision, operacion) -> dict:
    return next(o["cuerpo"] for o in e.ordenes_de(decision["event_id"]) if o["operacion"] == operacion)


HABLA = [{"role": "agent", "message": "Hola", "time_in_call_secs": 2}, {"role": "user", "message": "Dime", "time_in_call_secs": 4}]


# --- Casos ⚠ de casos.md -------------------------------------------------------------------------------------------

def test_caso_11_rechazada_va_al_respaldo_sin_reintento(entorno):
    e = entorno()
    d = e.procesar(variante("02-call-ended-tomas.json", sip=603))
    assert d["etiqueta"] == "rechazada"
    assert ops(e, d) == ["cerrar_llamada", "enviar_plantilla_whatsapp"]
    assert cuerpo(e, d, "cerrar_llamada")["status"] == "refused"
    assert cuerpo(e, d, "enviar_plantilla_whatsapp")["plantilla"] == "primer_toque_respaldo"


@pytest.mark.parametrize("fecha, hora, ambigua, esperado", [
    ("2026-09-15", "22:00", False, "2026-09-16T10:00:00+02:00"),  # de noche → primera franja del día siguiente
    ("2026-09-20", "12:00", False, "2026-09-21T10:00:00+02:00"),  # domingo → lunes
    ("2026-09-19", "17:00", False, "2026-09-21T10:00:00+02:00"),  # sábado tarde (cierra 14:00) → lunes
    ("2026-09-16", "09:00", True, "2026-09-16T10:00:00+02:00"),   # "a las nueve": 09:00 y 21:00 fuera → 10:00
])
def test_caso_12_callback_fuera_de_ventana(entorno, fecha, hora, ambigua, esperado):
    ev = variante("09-call-ended-javier.json")
    e = entorno({ev["idempotency_key"]: llm("callback", callback_fecha=fecha, callback_hora=hora, callback_hora_ambigua=ambigua)})
    d = e.procesar(ev)
    assert ops(e, d) == ["cerrar_llamada", "programar_llamada", "enviar_plantilla_whatsapp"]
    assert cuerpo(e, d, "programar_llamada")["no_antes_de"] == esperado
    assert cuerpo(e, d, "enviar_plantilla_whatsapp")["plantilla"] == "aviso_cambio_hora"


def test_caso_15_descartado_solo_cierra(entorno):
    ev = variante("04-call-ended-rosa.json")
    e = entorno({ev["idempotency_key"]: llm("descartado")})
    d = e.procesar(ev)
    assert ops(e, d) == ["cerrar_llamada"]
    assert cuerpo(e, d, "cerrar_llamada")["status"] == "skipped"


# --- Variantes de los casos con ejemplo -----------------------------------------------------------------------------

def test_callback_dentro_de_ventana_sin_aviso(entorno):
    ev = variante("09-call-ended-javier.json")
    e = entorno({ev["idempotency_key"]: llm("callback", callback_fecha="2026-09-17", callback_hora="12:30")})
    d = e.procesar(ev)
    assert ops(e, d) == ["cerrar_llamada", "programar_llamada"]
    assert cuerpo(e, d, "programar_llamada")["no_antes_de"] == "2026-09-17T12:30:00+02:00"


def test_callback_sin_hora_concreta_aplica_la_separacion_general(entorno):
    ev = variante("09-call-ended-javier.json")  # 17:05
    e = entorno({ev["idempotency_key"]: llm("callback")})
    d = e.procesar(ev)
    assert cuerpo(e, d, "programar_llamada")["no_antes_de"] == "2026-09-15T19:05:00+02:00"


@pytest.mark.parametrize("sip, amd, fuente", [(200, "machine-ivr", "livekit_amd"), (503, "not_run", "none")])
def test_otro_por_senalizacion_lleva_revisar_llamada(entorno, sip, amd, fuente):
    e = entorno()
    d = e.procesar(variante("01-call-ended-nuria.json", sip=sip, amd=amd, amd_fuente=fuente))
    assert d["etiqueta"] == "otro"
    assert ops(e, d) == ["cerrar_llamada", "crear_tarea"]
    assert cuerpo(e, d, "crear_tarea")["tipo"] == "revisar_llamada"
    assert cuerpo(e, d, "cerrar_llamada")["status"] == "needs_review"


def test_amd_uncertain_se_trata_como_persona(entorno):
    ev = variante("04-call-ended-rosa.json", amd="uncertain")
    e = entorno({ev["idempotency_key"]: llm("cortada")})
    d = e.procesar(ev)
    assert d["etiqueta"] == "cortada" and e.clasificador.llamadas == 1


def test_segunda_cortada_del_mismo_lead_va_a_revision(entorno):
    a = variante("04-call-ended-rosa.json")
    b = variante("11-call-ended-carla.json", contact_id="c_305", occurred_at="2026-09-15T13:00:00+02:00")
    e = entorno({a["idempotency_key"]: llm("cortada"), b["idempotency_key"]: llm("visita_sin_confirmar")})
    e.procesar(a)
    d = e.procesar(b)
    assert ops(e, d) == ["cerrar_llamada", "programar_llamada", "crear_tarea"]
    assert cuerpo(e, d, "crear_tarea")["tipo"] == "revisar_llamada"


@pytest.mark.parametrize("sip", [480, 486])
def test_intentos_agotados_van_al_respaldo(entorno, sip):
    e = entorno()
    horas = ["10:00", "13:00", "16:00"]
    for h in horas[:2]:
        e.procesar(variante("01-call-ended-nuria.json", contact_id="c_777", occurred_at=f"2026-09-15T{h}:00+02:00"))
    d = e.procesar(variante("01-call-ended-nuria.json", contact_id="c_777", sip=sip, occurred_at="2026-09-15T16:00:00+02:00"))
    assert ops(e, d) == ["cerrar_llamada", "enviar_plantilla_whatsapp"]
    assert cuerpo(e, d, "enviar_plantilla_whatsapp")["plantilla"] == "primer_toque_respaldo"


def test_callback_con_intentos_agotados_tambien_va_al_respaldo(entorno):
    """Decisión documentada: N3 se aplica a toda etiqueta que reprograma una llamada."""
    ev = variante("09-call-ended-javier.json", contact_id="c_778", occurred_at="2026-09-15T17:05:00+02:00")
    e = entorno({ev["idempotency_key"]: llm("callback", callback_fecha="2026-09-16", callback_hora="18:00")})
    e.procesar(variante("01-call-ended-nuria.json", contact_id="c_778", occurred_at="2026-09-15T10:00:00+02:00"))
    e.procesar(variante("01-call-ended-nuria.json", contact_id="c_778", occurred_at="2026-09-15T13:00:00+02:00"))
    d = e.procesar(ev)
    assert ops(e, d) == ["cerrar_llamada", "enviar_plantilla_whatsapp"]


def test_una_reentrega_no_cuenta_como_intento(entorno):
    e = entorno()
    primera = variante("01-call-ended-nuria.json", contact_id="c_779", occurred_at="2026-09-15T10:00:00+02:00")
    e.procesar(primera)
    reentrega = copy.deepcopy(primera)
    reentrega["event_id"] = "evt_reent"
    reentrega["delivery_attempt"] = 2
    e.procesar(reentrega)
    d = e.procesar(variante("01-call-ended-nuria.json", contact_id="c_779", occurred_at="2026-09-15T13:00:00+02:00"))
    assert "programar_llamada" in ops(e, d)  # es el 2.º intento, no el 3.º


def test_lead_dado_de_baja_no_recibe_nada_despues(entorno):
    baja = variante("06-call-ended-pedro.json")
    e = entorno({baja["idempotency_key"]: llm("no_contactar")})
    e.procesar(baja)
    d = e.procesar(variante("01-call-ended-nuria.json", contact_id="c_308", occurred_at="2026-09-16T11:00:00+02:00"))
    assert ops(e, d) == ["cerrar_llamada"]


def test_whatsapp_rechazado_bloquea_el_respaldo_por_whatsapp(entorno):
    iv = variante("13-call-ended-ivan.json")
    e = entorno({iv["idempotency_key"]: llm("documentacion_pendiente", whatsapp_rechazado=True)})
    e.procesar(iv)
    d = e.procesar(variante("02-call-ended-tomas.json", contact_id="c_311", sip=603, occurred_at="2026-09-16T11:00:00+02:00"))
    assert "enviar_plantilla_whatsapp" not in ops(e, d)
    assert cuerpo(e, d, "crear_tarea")["tipo"] == "revisar_llamada"


def test_documentacion_enviada_con_whatsapp_rechazado_solo_avisa_al_comercial(entorno):
    iv = variante("13-call-ended-ivan.json")
    doc = variante("08-call-ended-marcos.json", contact_id="c_311", occurred_at="2026-09-16T11:00:00+02:00")
    e = entorno({iv["idempotency_key"]: llm("documentacion_pendiente", whatsapp_rechazado=True),
                 doc["idempotency_key"]: llm("documentacion_enviada")})
    e.procesar(iv)
    d = e.procesar(doc)
    canales = [o["cuerpo"]["canal"] for o in e.ordenes_de(d["event_id"]) if o["operacion"] == "programar_recordatorio"]
    assert canales == ["tarea_comercial"]


def test_persona_equivocada_no_ensucia_la_lista_de_no_contactar(entorno):
    ev = variante("03-call-ended-elena.json")
    e = entorno({ev["idempotency_key"]: llm("persona_equivocada")})
    d = e.procesar(ev)
    assert "marcar_no_contactar" not in ops(e, d)


def test_visita_inminente_la_tarea_vence_ya(entorno):
    ev = variante("07-call-ended-laura.json", appointment={"appointment_id": "apt_1", "start_time": "2026-09-15T17:00:00+02:00"})
    e = entorno({ev["idempotency_key"]: llm("otro")})
    d = e.procesar(ev)  # llamada a las 16:10, visita a las 17:00: 17:00 − 2 h ya pasó
    assert cuerpo(e, d, "crear_tarea")["vence_el"] == "2026-09-15T16:10:00+02:00"


def test_baja_con_cita_manda_la_baja(entorno):
    ev = variante("07-call-ended-laura.json")
    e = entorno({ev["idempotency_key"]: llm("no_contactar")})
    d = e.procesar(ev)
    assert d["etiqueta"] == "no_contactar" and ops(e, d) == ["cerrar_llamada", "marcar_no_contactar"]


# --- Fechas en los bordes de la ventana ------------------------------------------------------------------------------

@pytest.mark.parametrize("base, sip, occurred_at, esperado", [
    ("01-call-ended-nuria.json", 480, "2026-09-18T19:00:00+02:00", "2026-09-19T10:00:00+02:00"),  # viernes 21:00 → sábado 10:00
    ("01-call-ended-nuria.json", 480, "2026-09-19T13:00:00+02:00", "2026-09-21T10:00:00+02:00"),  # sábado 15:00 → lunes
    ("01-call-ended-nuria.json", 480, "2026-09-15T18:00:00+02:00", "2026-09-15T20:00:00+02:00"),  # justo el cierre (inclusive)
    ("02-call-ended-tomas.json", 486, "2026-09-19T13:50:00+02:00", "2026-09-21T10:00:00+02:00"),  # ocupado sábado 13:50
    ("02-call-ended-tomas.json", 486, "2026-09-15T19:10:00+02:00", "2026-09-15T19:40:00+02:00"),  # medio fuera, mínimo dentro
])
def test_reintentos_en_los_bordes(entorno, base, sip, occurred_at, esperado):
    e = entorno()
    d = e.procesar(variante(base, sip=sip, occurred_at=occurred_at))
    assert cuerpo(e, d, "programar_llamada")["no_antes_de"] == esperado


def test_cortada_al_final_del_dia_pasa_a_la_manana_siguiente(entorno):
    ev = variante("04-call-ended-rosa.json", occurred_at="2026-09-15T19:45:00+02:00")
    e = entorno({ev["idempotency_key"]: llm("cortada")})
    d = e.procesar(ev)
    assert cuerpo(e, d, "programar_llamada")["no_antes_de"] == "2026-09-16T10:00:00+02:00"


# --- Mensajes, reentregas, otras organizaciones ------------------------------------------------------------------

def test_mensaje_sin_recordatorios_no_emite_nada(entorno):
    e = entorno()
    d = e.procesar(variante("14-message-received-marcos.json", tipo="message.received", contact_id="c_000"))
    assert d["etiqueta"] == "no_aplica" and d["ordenes"] == []


def test_mensaje_despues_de_que_venza_el_recordatorio_no_lo_cancela(entorno):
    doc = variante("08-call-ended-marcos.json", contact_id="c_555")
    e = entorno({doc["idempotency_key"]: llm("documentacion_enviada")})
    e.procesar(doc)  # recordatorio al lead a las 48 h (17/09 16:42); al comercial el 18/09
    d = e.procesar(variante("14-message-received-marcos.json", tipo="message.received", contact_id="c_555",
                            occurred_at="2026-09-17T20:00:00+02:00"))
    assert len(e.ordenes_de(d["event_id"])) == 1  # solo el del comercial sigue pendiente


def test_mensaje_reentregado_no_cancela_dos_veces(entorno):
    doc = variante("08-call-ended-marcos.json", contact_id="c_556")
    e = entorno({doc["idempotency_key"]: llm("documentacion_enviada")})
    e.procesar(doc)
    msg = variante("14-message-received-marcos.json", tipo="message.received", contact_id="c_556", idem="wa-x1",
                   occurred_at="2026-09-16T09:30:00+02:00")
    e.procesar(msg)
    otra = copy.deepcopy(msg)
    otra["event_id"] = "evt_msg_reent"
    d = e.procesar(otra)
    assert d["ordenes"] == [] and d["etiqueta"] == "no_aplica"


def test_otra_organizacion_no_toca_la_memoria(entorno):
    e = entorno()
    e.procesar(variante("01-call-ended-nuria.json", org="org_demo_b", contact_id="c_900"))
    e.procesar(variante("01-call-ended-nuria.json", org="org_demo_b", contact_id="c_900"))
    d = e.procesar(variante("01-call-ended-nuria.json", contact_id="c_900"))
    assert "programar_llamada" in ops(e, d)  # es su 1.er intento en nuestra organización


def test_llm_caido_manda_a_revision_y_no_rompe(entorno):
    e = entorno()  # el falso no tiene respuestas: falla como un LLM caído
    d = e.procesar(variante("04-call-ended-rosa.json"))
    assert d["etiqueta"] == "otro" and ops(e, d) == ["cerrar_llamada", "crear_tarea"]


def test_llm_caido_con_cita_sigue_siendo_visita_reservada(entorno):
    e = entorno()
    d = e.procesar(variante("07-call-ended-laura.json"))
    assert d["etiqueta"] == "visita_reservada"


def test_todo_lo_emitido_cumple_los_esquemas(entorno):
    """Pasa por casi todos los caminos y valida el formato de todo lo que sale."""
    ev_cb = variante("09-call-ended-javier.json")
    ev_doc = variante("08-call-ended-marcos.json")
    e = entorno({ev_cb["idempotency_key"]: llm("callback", callback_fecha="2026-09-20", callback_hora="12:00"),
                 ev_doc["idempotency_key"]: llm("documentacion_enviada")})
    for ev in [ev_cb, ev_doc, variante("02-call-ended-tomas.json", sip=603), variante("01-call-ended-nuria.json", sip=503),
               variante("14-message-received-marcos.json", tipo="message.received", contact_id="c_302")]:
        e.procesar(ev)
    assert errores_de_formato(e.decisiones(), e.ordenes()) == []
