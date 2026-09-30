"""Memoria entre ejecuciones (R4, R5, R7): un fichero SQLite local.

Cada evento es un proceso nuevo, así que todo lo que haya que recordar vive aquí:
- `hechos`: cada evento procesado por primera vez (clave: idempotency_key). Sirve para detectar reentregas (R5),
  contar intentos por lead (R4) y contar llamadas cortadas (N4).
- `ordenes`: cada orden emitida (clave única: su idempotency_key). Última barrera contra duplicados.
- `leads`: bajas (N2) y rechazo de WhatsApp (N1).
- `recordatorios`: los que programamos, con el reminder_id que generamos, para poder cancelarlos (R7).

Todo lo que produce un evento se guarda en UNA transacción: o queda todo o no queda nada.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .tipos import ETIQUETAS_CORTADA, ContextoLead, Efecto, Recordatorio

ESQUEMA = """
CREATE TABLE IF NOT EXISTS hechos (
    idempotency_key TEXT PRIMARY KEY,
    tipo            TEXT NOT NULL,
    event_id        TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    contact_id      TEXT NOT NULL,
    call_id         TEXT,
    etiqueta        TEXT NOT NULL,
    motivo          TEXT NOT NULL,
    confianza       REAL NOT NULL,
    occurred_at     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ordenes (
    orden_id        TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    event_id        TEXT NOT NULL,
    operacion       TEXT NOT NULL,
    cuerpo          TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS leads (
    organization_id    TEXT NOT NULL,
    contact_id         TEXT NOT NULL,
    dnc                INTEGER NOT NULL DEFAULT 0,
    whatsapp_rechazado INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (organization_id, contact_id)
);
CREATE TABLE IF NOT EXISTS recordatorios (
    reminder_id     TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    contact_id      TEXT NOT NULL,
    canal           TEXT NOT NULL,
    cuando          TEXT NOT NULL,
    estado          TEXT NOT NULL DEFAULT 'pendiente'
);
"""


class Estado:
    def __init__(self, ruta: str | Path):
        Path(ruta).parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(ruta, timeout=30)
        self.con.row_factory = sqlite3.Row
        self.con.executescript(ESQUEMA)

    def cerrar(self) -> None:
        self.con.close()

    # --- Lecturas (antes de decidir) -------------------------------------------------------------

    def hecho_previo(self, idempotency_key: str) -> dict | None:
        """La decisión original si este hecho ya se procesó (reentrega, R5)."""
        fila = self.con.execute("SELECT * FROM hechos WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
        return dict(fila) if fila else None

    def contexto(self, organization_id: str, contact_id: str) -> ContextoLead:
        llamadas = self.con.execute(
            "SELECT etiqueta FROM hechos WHERE tipo = 'call.ended' AND organization_id = ? AND contact_id = ?",
            (organization_id, contact_id),
        ).fetchall()
        lead = self.con.execute(
            "SELECT dnc, whatsapp_rechazado FROM leads WHERE organization_id = ? AND contact_id = ?",
            (organization_id, contact_id),
        ).fetchone()
        pendientes = self.con.execute(
            "SELECT reminder_id, canal, cuando FROM recordatorios "
            "WHERE organization_id = ? AND contact_id = ? AND estado = 'pendiente' ORDER BY cuando, reminder_id",
            (organization_id, contact_id),
        ).fetchall()
        return ContextoLead(
            intentos_previos=len(llamadas),
            cortadas_previas=sum(1 for f in llamadas if f["etiqueta"] in ETIQUETAS_CORTADA),
            dnc=bool(lead and lead["dnc"]),
            whatsapp_rechazado=bool(lead and lead["whatsapp_rechazado"]),
            recordatorios_pendientes=[Recordatorio(f["reminder_id"], f["canal"], f["cuando"]) for f in pendientes],
        )

    def orden_existe(self, idempotency_key: str) -> bool:
        return self.con.execute("SELECT 1 FROM ordenes WHERE idempotency_key = ?", (idempotency_key,)).fetchone() is not None

    # --- Escritura (después de decidir), en una sola transacción ---------------------------------

    def guardar(self, evento: dict, decision: dict, ordenes: list[dict], efectos: list[Efecto], registrar_hecho: bool) -> list[dict]:
        """Persiste el resultado del evento. Devuelve las órdenes realmente nuevas (sin duplicados, R5)."""
        org = evento["organization_id"]
        contact_id = evento["lead"]["contact_id"]
        nuevas: list[dict] = []
        with self.con:  # BEGIN … COMMIT, o ROLLBACK si algo falla
            if registrar_hecho:
                self.con.execute(
                    "INSERT OR IGNORE INTO hechos VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (evento["idempotency_key"], evento["type"], evento["event_id"], org, contact_id,
                     decision.get("call_id"), decision["etiqueta"], decision["motivo"], decision["confianza"],
                     evento["occurred_at"]),
                )
            for orden in ordenes:
                cursor = self.con.execute(
                    "INSERT OR IGNORE INTO ordenes VALUES (?,?,?,?,?)",
                    (orden["orden_id"], orden["idempotency_key"], orden["event_id"], orden["operacion"],
                     json.dumps(orden["cuerpo"], ensure_ascii=False)),
                )
                if cursor.rowcount == 1:
                    nuevas.append(orden)
            for efecto in efectos:
                self._aplicar(efecto, org, contact_id)
        return nuevas

    def _aplicar(self, efecto: Efecto, org: str, contact_id: str) -> None:
        if efecto.tipo in ("marcar_dnc", "marcar_whatsapp_rechazado"):
            columna = "dnc" if efecto.tipo == "marcar_dnc" else "whatsapp_rechazado"
            self.con.execute(
                f"INSERT INTO leads (organization_id, contact_id, {columna}) VALUES (?,?,1) "
                f"ON CONFLICT(organization_id, contact_id) DO UPDATE SET {columna} = 1",
                (org, contact_id),
            )
        elif efecto.tipo == "crear_recordatorio":
            d = efecto.datos
            self.con.execute(
                "INSERT OR IGNORE INTO recordatorios (reminder_id, organization_id, contact_id, canal, cuando) VALUES (?,?,?,?,?)",
                (d["reminder_id"], org, contact_id, d["canal"], d["cuando"]),
            )
        elif efecto.tipo == "cancelar_recordatorio":
            self.con.execute(
                "UPDATE recordatorios SET estado = 'cancelado' WHERE reminder_id = ?", (efecto.datos["reminder_id"],)
            )
