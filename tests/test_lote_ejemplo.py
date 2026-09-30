"""Capa 3: integración. El lote de ejemplo completo, un "proceso" por evento, contra la salida esperada de
docs/analisis.md §3. El LLM es falso: devuelve la etiqueta que un humano asignó leyendo cada transcripción."""
import json
import sqlite3

from conftest import EVENTOS, RAIZ, cargar, errores_de_formato, llm

RESPUESTAS_LLM = {
    "lk-out-0307": llm("persona_equivocada"),
    "lk-out-0305": llm("cortada", nota_contexto="alquiler en Majadahonda o Las Rozas; presupuesto a medias (~1.200 €)"),
    "lk-out-0308": llm("no_contactar"),
    "lk-out-0309": llm("otro"),  # tiene cita: el grafo lo convierte en visita_reservada
    "lk-out-0310": llm("documentacion_enviada"),
    "lk-out-0311": llm("callback", callback_fecha="2026-09-16", callback_hora="06:00", callback_hora_ambigua=True,
                       callback_texto="mañana a las seis"),
    "lk-out-0315": llm("visita_sin_confirmar", visita_acordada="jueves 17 a las 17:00"),
    "lk-out-0314": llm("documentacion_pendiente", whatsapp_rechazado=True, email="ivan.recalde@example.com"),
}

# event_id → (etiqueta, [(operacion, campo, valor esperado)])
ESPERADO = {
    "evt_01": ("sin_respuesta", [("cerrar_llamada", "status", "no_answer"), ("programar_llamada", "no_antes_de", "2026-09-15T12:12:00+02:00")]),
    "evt_02": ("ocupado", [("cerrar_llamada", "status", "no_answer"), ("programar_llamada", "no_antes_de", "2026-09-15T11:31:00+02:00")]),
    "evt_03": ("persona_equivocada", [("cerrar_llamada", "status", "failed"), ("crear_tarea", "tipo", "verificar_telefono")]),
    "evt_04": ("cortada", [("cerrar_llamada", "status", "needs_review"), ("programar_llamada", "no_antes_de", "2026-09-15T12:17:00+02:00")]),
    "evt_05": ("sin_respuesta", [("cerrar_llamada", "status", "no_answer"), ("programar_llamada", "no_antes_de", "2026-09-15T14:20:00+02:00")]),
    "evt_06": ("no_contactar", [("cerrar_llamada", "status", "dnc"), ("marcar_no_contactar", "canal", "todos")]),
    "evt_07": ("visita_reservada", [("cerrar_llamada", "status", "successful"), ("crear_tarea", "vence_el", "2026-09-17T09:00:00+02:00")]),
    "evt_08": ("documentacion_enviada", [("cerrar_llamada", "status", "completed"),
                                          ("programar_recordatorio", "cuando", "2026-09-17T16:42:00+02:00"),
                                          ("programar_recordatorio", "cuando", "2026-09-18T16:42:00+02:00")]),
    "evt_09": ("callback", [("cerrar_llamada", "status", "callback_requested"), ("programar_llamada", "no_antes_de", "2026-09-16T18:00:00+02:00")]),
    "evt_10": ("buzon", [("cerrar_llamada", "status", "no_answer"), ("programar_llamada", "no_antes_de", "2026-09-15T19:30:00+02:00")]),
    "evt_11": ("visita_sin_confirmar", [("cerrar_llamada", "status", "needs_review"), ("programar_llamada", "no_antes_de", "2026-09-15T18:20:00+02:00")]),
    "evt_12": ("buzon", [("cerrar_llamada", "status", "no_answer"), ("enviar_plantilla_whatsapp", "plantilla", "primer_toque_respaldo")]),
    "evt_13": ("documentacion_pendiente", [("cerrar_llamada", "status", "completed"), ("crear_tarea", "tipo", "enviar_documentacion_email")]),
    "evt_14": ("no_aplica", [("cancelar_recordatorio", "motivo", "el lead respondió por WhatsApp")] * 2),
    "evt_15": ("callback", []),
    "evt_16": ("no_aplica", []),
}


def orden_del_lote():
    return [l for l in (EVENTOS / "orden.txt").read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]


def correr_lote(entorno):
    e = entorno(RESPUESTAS_LLM)
    for nombre in orden_del_lote():
        e.procesar(cargar(nombre))
    return e


def test_etiquetas_y_ordenes_esperadas(entorno):
    e = correr_lote(entorno)
    decisiones = {d["event_id"]: d for d in e.decisiones()}
    assert set(decisiones) == set(ESPERADO), "una línea de decisión por evento recibido"
    for event_id, (etiqueta, ordenes_esperadas) in ESPERADO.items():
        d = decisiones[event_id]
        assert d["etiqueta"] == etiqueta, event_id
        ordenes = e.ordenes_de(event_id)
        obtenido = [(o["operacion"], o["cuerpo"].get(campo)) for o, (_, campo, _) in zip(ordenes, ordenes_esperadas)]
        assert len(ordenes) == len(ordenes_esperadas), (event_id, [o["operacion"] for o in ordenes])
        assert obtenido == [(op, v) for op, _, v in ordenes_esperadas], event_id
        assert d["ordenes"] == [o["orden_id"] for o in ordenes], event_id


def test_formato_contra_los_esquemas_oficiales(entorno):
    e = correr_lote(entorno)
    assert errores_de_formato(e.decisiones(), e.ordenes()) == []


def test_ejemplo_resuelto_identico(entorno):
    e = correr_lote(entorno)
    ejemplo_ordenes = [json.loads(l) for l in (RAIZ / "ejemplo-resuelto" / "salida" / "ordenes.jsonl").read_text(encoding="utf-8").splitlines()]
    ejemplo_decision = json.loads((RAIZ / "ejemplo-resuelto" / "salida" / "decisiones.jsonl").read_text(encoding="utf-8"))
    assert e.ordenes_de("evt_02") == ejemplo_ordenes
    assert next(d for d in e.decisiones() if d["event_id"] == "evt_02") == ejemplo_decision


def test_cancelar_recordatorio_usa_los_ids_creados_en_otro_proceso(entorno):
    e = correr_lote(entorno)
    creados = {o["idempotency_key"] for o in e.ordenes_de("evt_08") if o["operacion"] == "programar_recordatorio"}
    cancelados = [o["cuerpo"]["reminder_id"] for o in e.ordenes_de("evt_14")]
    assert len(creados) == 2 and len(set(cancelados)) == 2
    # Los cancelados son exactamente los que se persistieron al programarlos (el martes, en otro proceso).
    con = sqlite3.connect(e.db)
    try:
        persistidos = dict(con.execute("SELECT reminder_id, estado FROM recordatorios WHERE contact_id = 'c_302'").fetchall())
    finally:
        con.close()
    assert set(cancelados) == set(persistidos) and set(persistidos.values()) == {"cancelado"}


def test_repetir_el_lote_entero_no_duplica_nada(entorno):
    """R5 llevado al extremo: si llegaran otra vez todos los eventos, ninguna orden nueva."""
    e = correr_lote(entorno)
    antes = len(e.ordenes())
    for nombre in orden_del_lote():
        e.procesar(cargar(nombre))
    assert len(e.ordenes()) == antes
    assert all(d["ordenes"] == [] for d in e.decisiones()[len(ESPERADO):])


def test_el_llm_solo_se_llama_cuando_hay_conversacion(entorno):
    e = correr_lote(entorno)
    assert e.clasificador.llamadas == len(RESPUESTAS_LLM)  # 8: ni telefonía, ni reentrega, ni otra organización
