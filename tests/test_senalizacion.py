"""Capa 1: clasificación por telefonía (sin LLM)."""
import pytest

from postllamada.senalizacion import clasificar_por_senalizacion


def evento(sip: int, amd: str = "not_run", fuente: str = "none", transcript=None) -> dict:
    return {"telephony": {"sip_status_code": sip, "sip_status": "x", "amd": {"result": amd, "source": fuente}},
            "transcript": transcript if transcript is not None else []}


@pytest.mark.parametrize("sip, amd, fuente, etiqueta", [
    (486, "not_run", "none", "ocupado"),
    (603, "not_run", "none", "rechazada"),
    (408, "not_run", "none", "sin_respuesta"),
    (480, "not_run", "none", "sin_respuesta"),
    (503, "not_run", "none", "otro"),            # 5xx: fallo de trunk
    (500, "not_run", "none", "otro"),
    (404, "not_run", "none", "otro"),            # no contemplado
    (200, "machine-vm", "livekit_amd", "buzon"),
    (200, "machine-unavailable", "livekit_amd", "buzon"),
    (200, "machine-vm", "heuristic_regex", "buzon"),  # caso 13: saludo ambiguo, sigue siendo buzón
    (200, "machine-ivr", "livekit_amd", "otro"),
])
def test_senalizacion_decide(sip, amd, fuente, etiqueta):
    assert clasificar_por_senalizacion(evento(sip, amd, fuente)).etiqueta == etiqueta


@pytest.mark.parametrize("amd", ["human", "uncertain", "not_run"])
def test_persona_o_incierto_con_conversacion_se_lee(amd):
    assert clasificar_por_senalizacion(evento(200, amd, "livekit_amd", [{"role": "user", "message": "hola", "time_in_call_secs": 1}])) is None


def test_descolgaron_sin_conversacion_es_otro():
    assert clasificar_por_senalizacion(evento(200, "human", "livekit_amd", [])).etiqueta == "otro"


def test_486_no_es_rechazo_aunque_livekit_diga_user_rejected():
    ev = evento(486)
    ev["telephony"]["disconnect_reason"] = "USER_REJECTED"
    assert clasificar_por_senalizacion(ev).etiqueta == "ocupado"
