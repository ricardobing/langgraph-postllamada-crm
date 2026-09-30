"""De la etiqueta a las órdenes contra el CRM (R2, R3, R4, R7 y reglas N1–N5).

Código puro, sin LLM: recibe el evento, la clasificación, lo que se recuerda del lead y la configuración, y devuelve
las órdenes y los cambios de estado. "La IA entiende, el sistema decide."
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta

from . import tiempo
from .config import Config
from .tipos import (
    ESTADO_COLA,
    ETIQUETAS_CON_REINTENTO,
    ETIQUETAS_CORTADA,
    Clasificacion,
    ContextoLead,
    Efecto,
)


def _hash(texto: str, largo: int) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()[:largo]


def orden_id_de(idempotency_key: str) -> str:
    """Estable entre ejecuciones: el mismo hecho produce el mismo id (enunciado §4.2).

    SHA-1 de la clave de idempotencia, 8 caracteres: el mismo esquema que usa el ejemplo resuelto
    (`lk-out-0306:cerrar_llamada` → `ord_96decc21`). No es un uso criptográfico: solo un identificador estable.
    """
    return "ord_" + hashlib.sha1(idempotency_key.encode("utf-8")).hexdigest()[:8]


@dataclass
class Plan:
    ordenes: list[dict] = field(default_factory=list)
    efectos: list[Efecto] = field(default_factory=list)


class _Constructor:
    """Acumula órdenes con su idempotency_key `<clave del evento>:<operacion>[:distintivo]` y sin repetirlas."""

    def __init__(self, evento: dict):
        self.evento = evento
        self.plan = Plan()

    def orden(self, operacion: str, cuerpo: dict, distintivo: str | None = None) -> dict:
        clave = f"{self.evento['idempotency_key']}:{operacion}" + (f":{distintivo}" if distintivo else "")
        if any(o["idempotency_key"] == clave for o in self.plan.ordenes):
            return next(o for o in self.plan.ordenes if o["idempotency_key"] == clave)
        orden = {
            "orden_id": orden_id_de(clave),
            "event_id": self.evento["event_id"],
            "operacion": operacion,
            "idempotency_key": clave,
            "cuerpo": cuerpo,
        }
        self.plan.ordenes.append(orden)
        return orden


def planificar_llamada(evento: dict, clasif: Clasificacion, ctx: ContextoLead, cfg: Config) -> Plan:
    """Órdenes para un call.ended procesado por primera vez, de la organización de la campaña."""
    c = _Constructor(evento)
    lead = evento["lead"]
    tel = evento.get("telephony") or {}
    t = datetime.fromisoformat(evento["occurred_at"])
    etiqueta = clasif.etiqueta
    datos = clasif.datos

    # 1. Cerrar la llamada: siempre, con el estado de cola que fija la etiqueta.
    c.orden("cerrar_llamada", {
        "entry_id": evento["campaign"]["entry_id"],
        "status": ESTADO_COLA[etiqueta],
        "etiqueta": etiqueta,
        "motivo": clasif.motivo,
        "confianza": clasif.confianza,
        "duration_seconds": int(tel.get("duration_seconds") or 0),
    })

    # Cambios de estado que se deducen de la conversación, pase lo que pase después.
    whatsapp_rechazado = ctx.whatsapp_rechazado or datos.whatsapp_rechazado or etiqueta == "documentacion_pendiente"
    if whatsapp_rechazado and not ctx.whatsapp_rechazado:
        c.plan.efectos.append(Efecto("marcar_whatsapp_rechazado"))

    # N2: un lead dado de baja no recibe ninguna orden saliente (ni en esta llamada ni en las siguientes).
    if etiqueta == "no_contactar":
        c.orden("marcar_no_contactar", {
            "telefono": lead["phone"],
            "contact_id": lead["contact_id"],
            "canal": "todos",
            "motivo": clasif.motivo,
            "origen": f"llamada {tel.get('call_id') or evento['idempotency_key']}",
        })
        c.plan.efectos.append(Efecto("marcar_dnc"))
        return c.plan
    if ctx.dnc:
        return c.plan

    ayudante = _Ayudante(c, evento, cfg, t, whatsapp_rechazado)
    intento_actual = ctx.intentos_previos + 1  # este call.ended es un intento (una reentrega no llega aquí)
    quedan_intentos = intento_actual < cfg.max_intentos

    # 2. Lo que toca por la etiqueta.
    if etiqueta in ETIQUETAS_CON_REINTENTO and not quedan_intentos:
        # N3: agotados los intentos de voz, canal de respaldo (decisión: aplica a toda etiqueta que reprograma).
        ayudante.respaldo(f"{etiqueta}: agotados los {cfg.max_intentos} intentos de voz")
    elif etiqueta in ("sin_respuesta", "buzon"):
        cuando = tiempo.siguiente_en_ventana(tiempo.sumar_tiempo(t, timedelta(hours=cfg.separacion_minima_horas), cfg), cfg)
        motivo = "no contestó, reintento tras la separación mínima" if etiqueta == "sin_respuesta" else "saltó el buzón, reintento tras la separación mínima"
        ayudante.programar_llamada(cuando, motivo, datos.nota_contexto or _nota_sin_conversacion(etiqueta))
    elif etiqueta == "ocupado":
        desde = tiempo.sumar_tiempo(t, timedelta(minutes=cfg.ocupado_minutos_min), cfg)
        hasta = tiempo.sumar_tiempo(t, timedelta(minutes=cfg.ocupado_minutos_max), cfg)
        # Punto medio del rango: reproduce el ejemplo resuelto (10:31 → 11:31) y deja margen a los dos lados.
        preferido = tiempo.sumar_tiempo(t, timedelta(minutes=(cfg.ocupado_minutos_min + cfg.ocupado_minutos_max) / 2), cfg)
        ayudante.programar_llamada(tiempo.primero_en_rango(desde, hasta, preferido, cfg), "línea comunicando, reintento corto", "no se llegó a hablar con el lead")
    elif etiqueta in ETIQUETAS_CORTADA:
        # Casos 7 y 8: lo antes posible dentro de la ventana, con los plazos de cortada. N5: la visita no se reserva.
        desde = tiempo.sumar_tiempo(t, timedelta(minutes=cfg.cortada_minutos_min), cfg)
        hasta = tiempo.sumar_tiempo(t, timedelta(hours=cfg.cortada_horas_max), cfg)
        motivo = "la llamada se cortó a mitad de la cualificación" if etiqueta == "cortada" else "se acordó una visita de palabra y la llamada cayó antes de reservarla"
        nota = datos.nota_contexto or ("visita acordada de palabra: " + datos.visita_acordada if datos.visita_acordada else "llamada cortada")
        ayudante.programar_llamada(tiempo.primero_en_rango(desde, hasta, desde, cfg), motivo, nota)
    elif etiqueta == "callback":
        ayudante.callback(datos)
    elif etiqueta == "rechazada":
        ayudante.respaldo("rechazo activo de la llamada (603): sin reintento por voz")
    elif etiqueta == "persona_equivocada":
        ayudante.tarea("verificar_telefono", "Verificar teléfono del lead",
                       f"Contestó otra persona: {clasif.motivo}. No se reintenta la llamada.")
    elif etiqueta == "visita_reservada":
        ayudante.tarea_confirmar_visita(evento)
    elif etiqueta == "documentacion_enviada":
        ayudante.recordatorios_documentacion()
    elif etiqueta == "documentacion_pendiente":
        destino = f" a {datos.email}" if datos.email else ""
        ayudante.tarea("enviar_documentacion_email", "Enviar documentación por email",
                       f"El lead pidió la documentación y rechazó WhatsApp: enviarla por email{destino}.")
    # descartado y otro: nada más por la etiqueta.

    # 3. N4: `otro`, o una segunda llamada cortada con el mismo lead → revisión humana.
    if etiqueta == "otro":
        ayudante.tarea("revisar_llamada", "Revisar llamada", f"Llamada sin etiqueta clara: {clasif.motivo}")
    elif etiqueta in ETIQUETAS_CORTADA and ctx.cortadas_previas >= 1:
        ayudante.tarea("revisar_llamada", "Revisar llamada: segunda llamada cortada",
                       f"Es la {ctx.cortadas_previas + 1}.ª llamada cortada con este lead: {clasif.motivo}")
    return c.plan


def planificar_mensaje(evento: dict, ctx: ContextoLead, cfg: Config) -> Plan:
    """message.received (R7): cancelar cada recordatorio pendiente del lead.

    "Pendiente" = no cancelado y con fecha posterior al mensaje: uno cuya hora ya pasó ya se ejecutó.
    """
    c = _Constructor(evento)
    t = datetime.fromisoformat(evento["occurred_at"])
    for rec in ctx.recordatorios_pendientes:
        if datetime.fromisoformat(rec.cuando) <= t:
            continue
        c.orden("cancelar_recordatorio", {"reminder_id": rec.reminder_id, "motivo": "el lead respondió por WhatsApp"}, rec.reminder_id)
        c.plan.efectos.append(Efecto("cancelar_recordatorio", {"reminder_id": rec.reminder_id}))
    return c.plan


def _nota_sin_conversacion(etiqueta: str) -> str:
    return "saltó el buzón de voz, no se habló con el lead" if etiqueta == "buzon" else "no se llegó a hablar con el lead"


class _Ayudante:
    """Constructores de cada tipo de orden, con las reglas de canal (N1) aplicadas."""

    def __init__(self, c: _Constructor, evento: dict, cfg: Config, t: datetime, whatsapp_rechazado: bool):
        self.c, self.evento, self.cfg, self.t = c, evento, cfg, t
        self.lead = evento["lead"]
        self.whatsapp_permitido = not whatsapp_rechazado

    def programar_llamada(self, cuando: datetime, motivo: str, nota: str) -> None:
        self.c.orden("programar_llamada", {
            "entry_id": self.evento["campaign"]["entry_id"],
            "telefono": self.lead["phone"],
            "no_antes_de": tiempo.iso(cuando, self.cfg),
            "motivo": motivo,
            "nota_contexto": nota,
        })

    def plantilla(self, plantilla: str, parametros: dict[str, str]) -> bool:
        """Envía una plantilla de WhatsApp si el canal está permitido (N1). Devuelve si se emitió."""
        if not self.whatsapp_permitido:
            return False
        self.c.orden("enviar_plantilla_whatsapp", {
            "organization_id": self.evento["organization_id"],
            "telefono": self.lead["phone"],
            "plantilla": plantilla,
            "parametros": {k: v for k, v in parametros.items() if v},
            "idioma": self.lead.get("language") or "es",
        }, plantilla)
        return True

    def respaldo(self, motivo: str) -> None:
        """N3: canal de respaldo de la configuración. Si ese canal está vetado (N1), revisión humana."""
        if self.cfg.canal_respaldo == "whatsapp" and self.plantilla("primer_toque_respaldo", {"nombre": self.lead.get("full_name") or ""}):
            return
        self.tarea("revisar_llamada", "Revisar lead: sin canal de respaldo disponible",
                   f"{motivo}; el canal de respaldo ({self.cfg.canal_respaldo}) no está permitido para este lead.")

    def tarea(self, tipo: str, titulo: str, detalle: str, vence: datetime | None = None) -> None:
        vence = vence or tiempo.sumar_dias_naturales(self.t, self.cfg.vencimiento_por_defecto_dias, self.cfg)
        self.c.orden("crear_tarea", {
            "contact_id": self.lead["contact_id"],
            "call_id": (self.evento.get("telephony") or {}).get("call_id"),
            "tipo": tipo,
            "titulo": titulo,
            "detalle": detalle,
            "vence_el": tiempo.iso(vence, self.cfg),
            "asignada_a": "comercial_asignado",
        }, tipo)

    def tarea_confirmar_visita(self, evento: dict) -> None:
        cita = (evento.get("agent_outcome") or {}).get("appointment") or {}
        inicio = datetime.fromisoformat(cita["start_time"])
        vence = tiempo.sumar_tiempo(inicio, -timedelta(hours=self.cfg.confirmar_visita_margen_horas), self.cfg)
        vence = max(vence, self.t)  # si la visita es inminente, vence ya
        direccion = self.lead.get("property_address")
        detalle = (f"Visita {cita.get('appointment_id')} el {tiempo.iso(inicio, self.cfg)}. "
                   + (f"Confirmar la dirección exacta: {direccion}." if direccion else
                      "El inmueble no tiene dirección registrada: conseguirla y confirmársela al lead."))
        self.tarea("confirmar_visita_direccion", "Confirmar dirección de la visita", detalle, vence)

    def recordatorios_documentacion(self) -> None:
        """Caso 2: recordatorio al lead (si WhatsApp está permitido) y al comercial, cancelables si el lead responde."""
        cuando_lead = tiempo.sumar_tiempo(self.t, timedelta(hours=self.cfg.documentacion_lead_horas), self.cfg)
        cuando_comercial = tiempo.sumar_dias_habiles(self.t, self.cfg.seguimiento_comercial_dias_habiles, self.cfg)
        if self.whatsapp_permitido:
            self._recordatorio("lead", {"canal": "whatsapp_lead", "plantilla": "recordatorio_documentacion"}, cuando_lead)
        self._recordatorio("comercial", {"canal": "tarea_comercial", "tipo_tarea": "llamar_a_mano"}, cuando_comercial)

    def _recordatorio(self, distintivo: str, campos: dict, cuando: datetime) -> None:
        clave = f"{self.evento['idempotency_key']}:programar_recordatorio:{distintivo}"
        reminder_id = "rem_" + _hash(clave, 10)  # generado por nosotros y persistido (enunciado §4.2)
        cuerpo = {"contact_id": self.lead["contact_id"], **campos, "cuando": tiempo.iso(cuando, self.cfg), "cancelar_si": "lead_responde"}
        self.c.orden("programar_recordatorio", cuerpo, distintivo)
        self.c.plan.efectos.append(Efecto("crear_recordatorio", {"reminder_id": reminder_id, "canal": campos["canal"], "cuando": cuerpo["cuando"]}))

    def callback(self, datos) -> None:
        """Casos 3 y 12: a la hora pedida; si cae fuera de la ventana, primera franja válida + aviso_cambio_hora."""
        pedido = resolver_hora_callback(datos, self.t, self.cfg)
        nota = datos.nota_contexto or (f"pidió que se le llame: «{datos.callback_texto}»" if datos.callback_texto else "pidió que se le llame en otro momento")
        if pedido is None:
            # Pidió otra llamada sin concretar cuándo: se aplica la separación mínima general.
            cuando = tiempo.siguiente_en_ventana(tiempo.sumar_tiempo(self.t, timedelta(hours=self.cfg.separacion_minima_horas), self.cfg), self.cfg)
            self.programar_llamada(cuando, "callback solicitado sin hora concreta", nota)
            return
        if pedido > self.t and tiempo.en_ventana(pedido, self.cfg):
            self.programar_llamada(pedido, "callback solicitado", nota)
            return
        cuando = tiempo.siguiente_en_ventana(max(pedido, self.t), self.cfg)
        self.programar_llamada(cuando, "callback solicitado fuera de la ventana: primera franja válida", nota)
        self.plantilla("aviso_cambio_hora", {"nombre": self.lead.get("full_name") or "", "hora_pedida": tiempo.iso(pedido, self.cfg), "nueva_hora": tiempo.iso(cuando, self.cfg)})


def resolver_hora_callback(datos, t: datetime, cfg: Config) -> datetime | None:
    """Convierte la fecha y hora que extrajo el LLM en un instante de Madrid. None = sin momento concreto.

    - Día sin hora ("el lunes"): la apertura de la franja de ese día. Si el día es hoy ("hoy más tarde"), None.
    - Hora sin día ("a las cinco"), o con el día de hoy: la primera lectura que todavía no pasó; si ya pasaron
      todas, la de mañana.
    - Si la hora es ambigua ("a las seis"), se prefiere la lectura de 12 h que cae dentro de la ventana de ese día
      (06:00 no, 18:00 sí). Si ninguna de las dos cae, la de la mañana, salvo que sea antes de las 8 (nadie pide que
      le llamen de madrugada): entonces, la de la tarde.
    """
    if not datos.callback_fecha and not datos.callback_hora:
        return None
    hoy = tiempo.a_local(t, cfg).date()
    try:
        fecha = datetime.fromisoformat(datos.callback_fecha).date() if datos.callback_fecha else None
        if not datos.callback_hora:
            if fecha == hoy:
                return None
            franja = cfg.ventana[fecha.weekday()]
            horas, minutos = (franja[0].hour, franja[0].minute) if franja else (10, 0)
            return datetime.combine(fecha, time(horas, minutos), tzinfo=cfg.zona)
        horas, minutos = (int(x) for x in datos.callback_hora.split(":")[:2])
        lecturas = [time(horas, minutos)]
        if datos.callback_hora_ambigua and horas < 12:
            lecturas.append(time(horas + 12, minutos))
    except (ValueError, TypeError, AttributeError):
        return None

    def por_preferencia(dia) -> list[datetime]:
        candidatos = [datetime.combine(dia, lectura, tzinfo=cfg.zona) for lectura in lecturas]
        if len(candidatos) == 2 and not tiempo.en_ventana(candidatos[0], cfg) and (tiempo.en_ventana(candidatos[1], cfg) or horas < 8):
            candidatos.reverse()
        return candidatos

    if fecha is None or fecha == hoy:
        # "Llámame a las cinco" dicho hoy: la lectura preferida que aún no pasó (a las 12:00, "a las seis" es 18:00).
        futuras = [c for c in por_preferencia(hoy) if c > t]
        if futuras:
            return futuras[0]
        fecha = hoy + timedelta(days=1)
    return por_preferencia(fecha)[0]
