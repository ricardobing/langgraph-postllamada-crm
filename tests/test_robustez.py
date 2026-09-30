"""Capa 5: robustez. Eventos aleatorios o raros: el sistema nunca lanza una excepción, siempre deja su línea de
decisión y todo lo que emite cumple los esquemas. Y el ejecutable real (run.py) devuelve los códigos de salida del
contrato."""
import copy
import json
import os
import subprocess
import sys

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from conftest import RAIZ, ClasificadorFalso, Entorno, cargar, errores_de_formato, llm

BASES = ["01-call-ended-nuria.json", "04-call-ended-rosa.json", "07-call-ended-laura.json",
         "08-call-ended-marcos.json", "09-call-ended-javier.json", "14-message-received-marcos.json"]

ETIQUETAS_LLM = ["no_contactar", "persona_equivocada", "descartado", "callback", "documentacion_enviada",
                 "documentacion_pendiente", "visita_sin_confirmar", "cortada", "otro"]

evento_aleatorio = st.fixed_dictionaries({
    "base": st.sampled_from(BASES),
    "sip": st.sampled_from([200, 408, 480, 486, 487, 500, 503, 603, 404]),
    "amd": st.sampled_from(["human", "machine-vm", "machine-ivr", "machine-unavailable", "uncertain", "not_run"]),
    "dia": st.integers(min_value=14, max_value=27),  # incluye fines de semana y el cambio de hora no (septiembre)
    "hora": st.integers(min_value=0, max_value=23),
    "minuto": st.integers(min_value=0, max_value=59),
    "org": st.sampled_from(["org_demo_a", "org_demo_a", "org_demo_b"]),
    "contacto": st.sampled_from(["c_1", "c_2", "c_3"]),
    "idem": st.integers(min_value=1, max_value=6),  # colisiones = reentregas
    "etiqueta_llm": st.sampled_from(ETIQUETAS_LLM),
    "cb_fecha": st.one_of(st.none(), st.sampled_from(["2026-09-16", "2026-09-20", "2026-13-40", "mañana"])),
    "cb_hora": st.one_of(st.none(), st.sampled_from(["06:00", "18:00", "23:59", "25:61", "seis"])),
    "llm_cae": st.booleans(),
})


def construir(p: dict) -> tuple[dict, ClasificadorFalso]:
    ev = copy.deepcopy(cargar(p["base"]))
    ev["event_id"] = f"evt_f{p['idem']}_{p['dia']}{p['hora']}{p['minuto']}"
    ev["idempotency_key"] = f"k{p['idem']}"
    ev["organization_id"] = p["org"]
    ev["lead"]["contact_id"] = p["contacto"]
    ev["occurred_at"] = f"2026-09-{p['dia']:02d}T{p['hora']:02d}:{p['minuto']:02d}:00+02:00"
    if ev["type"] == "call.ended":
        ev["telephony"]["sip_status_code"] = p["sip"]
        ev["telephony"]["amd"]["result"] = p["amd"]
        ev["telephony"]["call_id"] = ev["idempotency_key"]
    respuestas = {} if p["llm_cae"] else {ev["idempotency_key"]: llm(p["etiqueta_llm"], callback_fecha=p["cb_fecha"], callback_hora=p["cb_hora"])}
    return ev, ClasificadorFalso(respuestas)


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(secuencia=st.lists(evento_aleatorio, min_size=1, max_size=8))
def test_secuencias_aleatorias_nunca_rompen(tmp_path_factory, cfg, secuencia):
    carpeta = tmp_path_factory.mktemp("fuzz")
    recibidos = 0
    for p in secuencia:
        ev, clasificador = construir(p)
        Entorno(carpeta, cfg, clasificador).procesar(ev)  # no debe lanzar nada
        recibidos += 1
    e = Entorno(carpeta, cfg, None)
    assert len(e.decisiones()) == recibidos  # una línea por evento recibido
    assert errores_de_formato(e.decisiones(), e.ordenes()) == []
    claves = [o["idempotency_key"] for o in e.ordenes()]
    assert len(claves) == len(set(claves))  # R5: ninguna orden duplicada, pase lo que pase


# --- El ejecutable real, como proceso ------------------------------------------------------------------------------

def correr(args: list[str], tmp_path, sin_clave: bool = True) -> subprocess.CompletedProcess:
    env = {**os.environ, "SALIDA_DIR": str(tmp_path / "salida"), "PYTHONIOENCODING": "utf-8"}
    if sin_clave:
        env["OPENAI_API_KEY"] = ""  # sin red: solo lo que decide la telefonía
    return subprocess.run([sys.executable, str(RAIZ / "run.py"), *args], env=env, capture_output=True, text=True,
                          encoding="utf-8", cwd=tmp_path)


def test_run_procesa_y_devuelve_0(tmp_path):
    r = correr([str(RAIZ / "eventos" / "02-call-ended-tomas.json")], tmp_path)
    assert r.returncode == 0, r.stderr
    lineas = (tmp_path / "salida" / "ordenes.jsonl").read_text(encoding="utf-8").splitlines()
    ejemplo = (RAIZ / "ejemplo-resuelto" / "salida" / "ordenes.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(l) for l in lineas] == [json.loads(l) for l in ejemplo]


def test_run_reproduce_el_ejemplo_resuelto_byte_a_byte(tmp_path):
    """Orden de campos, separadores, UTF-8 sin escapar y LF: el formato exacto, no solo el contenido."""
    r = correr([str(RAIZ / "eventos" / "02-call-ended-tomas.json")], tmp_path)
    assert r.returncode == 0, r.stderr
    for nombre in ("decisiones.jsonl", "ordenes.jsonl"):
        assert (tmp_path / "salida" / nombre).read_bytes() == (RAIZ / "ejemplo-resuelto" / "salida" / nombre).read_bytes(), nombre


def test_run_json_roto_devuelve_distinto_de_0(tmp_path):
    roto = tmp_path / "roto.json"
    roto.write_text("{ esto no es json", encoding="utf-8")
    assert correr([str(roto)], tmp_path).returncode != 0


def test_run_evento_fuera_de_esquema_devuelve_distinto_de_0(tmp_path):
    malo = tmp_path / "malo.json"
    malo.write_text(json.dumps({"event_id": "x", "type": "call.ended"}), encoding="utf-8")
    assert correr([str(malo)], tmp_path).returncode != 0


def test_run_fichero_inexistente_y_sin_argumentos(tmp_path):
    assert correr([str(tmp_path / "no-existe.json")], tmp_path).returncode != 0
    assert correr([], tmp_path).returncode != 0


def test_un_fallo_no_impide_procesar_el_siguiente(tmp_path):
    """R8: un evento ilegible en medio del lote no deja estado a medias ni bloquea los siguientes."""
    roto = tmp_path / "roto.json"
    roto.write_text("{", encoding="utf-8")
    assert correr([str(RAIZ / "eventos" / "01-call-ended-nuria.json")], tmp_path).returncode == 0
    assert correr([str(roto)], tmp_path).returncode != 0
    assert correr([str(RAIZ / "eventos" / "05-call-ended-nuria.json")], tmp_path).returncode == 0
    decisiones = (tmp_path / "salida" / "decisiones.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(l)["event_id"] for l in decisiones] == ["evt_01", "evt_05"]


def test_sin_clave_de_openai_la_conversacion_va_a_revision(tmp_path):
    r = correr([str(RAIZ / "eventos" / "04-call-ended-rosa.json")], tmp_path)
    assert r.returncode == 0
    d = json.loads((tmp_path / "salida" / "decisiones.jsonl").read_text(encoding="utf-8"))
    assert d["etiqueta"] == "otro"
