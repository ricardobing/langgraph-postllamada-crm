"""Capa 1: el cliente del LLM sin red. Reintentos, respaldo, validación del JSON y lo que ve el modelo."""
import json

import pytest

from conftest import cargar
from postllamada import llm as modulo
from postllamada.config import cargar_config
from postllamada.llm import ESQUEMA_JSON, ClasificadorOpenAI, ErrorClasificacion, SalidaLLM, mensaje_usuario

VALIDA = {"etiqueta": "callback", "motivo": "pide que le llamen", "confianza": 0.9,
          "callback": {"fecha": "2026-09-16", "hora": "06:00", "hora_ambigua": True, "texto_literal": "mañana a las seis"},
          "visita_acordada": None, "whatsapp_rechazado": False, "email": None, "nota_contexto": "venta en Boadilla"}


class ErrorHTTP(Exception):
    def __init__(self, status_code):
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


def clasificador(monkeypatch, respuestas_por_modelo: dict, llamadas: list):
    monkeypatch.setattr(modulo.time, "sleep", lambda s: None)
    c = ClasificadorOpenAI.__new__(ClasificadorOpenAI)
    c.modelos = list(respuestas_por_modelo)
    c.intentos = 3
    c.costo_usd = 0.0
    colas = {m: list(r) for m, r in respuestas_por_modelo.items()}

    def llamar(modelo, evento, zona):
        llamadas.append(modelo)
        r = colas[modelo].pop(0)
        if isinstance(r, Exception):
            raise r
        return SalidaLLM.model_validate(json.loads(r) if isinstance(r, str) else r)

    c._llamar = llamar
    return c


EV = cargar("09-call-ended-javier.json")
ZONA = cargar_config("config/campana.yaml").zona


def test_respuesta_valida_se_convierte_en_clasificacion(monkeypatch):
    c = clasificador(monkeypatch, {"principal": [VALIDA]}, [])
    r = c.clasificar(EV, ZONA)
    assert (r.etiqueta, r.fuente, r.datos.callback_hora, r.datos.callback_hora_ambigua) == ("callback", "llm", "06:00", True)


def test_json_invalido_se_reintenta(monkeypatch):
    llamadas = []
    c = clasificador(monkeypatch, {"principal": ["{no es json", {**VALIDA, "etiqueta": "inventada"}, VALIDA]}, llamadas)
    assert c.clasificar(EV, ZONA).etiqueta == "callback"
    assert llamadas == ["principal"] * 3


def test_error_de_red_reintenta_y_luego_va_al_respaldo(monkeypatch):
    llamadas = []
    c = clasificador(monkeypatch, {"principal": [ErrorHTTP(503)] * 3, "respaldo": [VALIDA]}, llamadas)
    r = c.clasificar(EV, ZONA)
    assert r.fuente == "respaldo_llm" and llamadas == ["principal"] * 3 + ["respaldo"]


def test_modelo_inexistente_salta_al_respaldo_sin_reintentar(monkeypatch):
    llamadas = []
    c = clasificador(monkeypatch, {"principal": [ErrorHTTP(404)], "respaldo": [VALIDA]}, llamadas)
    assert c.clasificar(EV, ZONA).fuente == "respaldo_llm"
    assert llamadas == ["principal", "respaldo"]


def test_si_todo_falla_lanza_error_de_clasificacion(monkeypatch):
    c = clasificador(monkeypatch, {"principal": [ErrorHTTP(401)], "respaldo": [ErrorHTTP(500)] * 3}, [])
    with pytest.raises(ErrorClasificacion):
        c.clasificar(EV, ZONA)


def test_confianza_fuera_de_rango_es_invalida():
    with pytest.raises(Exception):
        SalidaLLM.model_validate({**VALIDA, "confianza": 1.4})


def test_el_esquema_es_estricto_y_coincide_con_el_modelo_pydantic():
    assert ESQUEMA_JSON["additionalProperties"] is False
    assert set(ESQUEMA_JSON["required"]) == set(SalidaLLM.model_fields)


def test_lo_que_ve_el_modelo_lleva_la_referencia_en_madrid_y_la_transcripcion():
    texto = mensaje_usuario(EV, ZONA)
    assert "martes 2026-09-15T17:05:00+02:00" in texto
    assert "¿Me puedes llamar mañana a las seis?" in texto
    assert "Cita creada por el agente durante la llamada: no" in texto


def test_el_prompt_versionado_tiene_todo_el_catalogo():
    prompt = modulo.RUTA_PROMPT.read_text(encoding="utf-8")
    for etiqueta in modulo.ETIQUETAS_CONVERSACION:
        assert f"`{etiqueta}`" in prompt


def test_por_defecto_contra_openai_principal_y_respaldo_son_de_openai(monkeypatch):
    for var in ("OPENAI_BASE_URL", "MODELO", "MODELO_RESPALDO"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-prueba")
    assert ClasificadorOpenAI.desde_entorno().modelos == ["gpt-5.6-luna", "gpt-6-luna"]


def test_por_defecto_contra_openrouter_el_respaldo_es_el_mismo_con_prefijo(monkeypatch):
    monkeypatch.delenv("MODELO_RESPALDO", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-prueba")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("MODELO", "openai/gpt-5.6-luna")
    assert ClasificadorOpenAI.desde_entorno().modelos == ["openai/gpt-5.6-luna", "openai/gpt-6-luna"]


def test_otro_servidor_compatible_sin_respaldo_por_defecto(monkeypatch):
    monkeypatch.delenv("MODELO_RESPALDO", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-prueba")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:8000/v1")
    monkeypatch.setenv("MODELO", "local")
    assert ClasificadorOpenAI.desde_entorno().modelos == ["local"]


def test_cadena_de_respaldo_configurable(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-prueba")
    monkeypatch.setenv("MODELO", "m1")
    monkeypatch.setenv("MODELO_RESPALDO", "m2, m3,,m1")
    assert ClasificadorOpenAI.desde_entorno().modelos == ["m1", "m2", "m3"]


def test_sin_respaldo_si_se_deja_vacio(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-prueba")
    monkeypatch.setenv("MODELO", "m1")
    monkeypatch.setenv("MODELO_RESPALDO", "")
    assert ClasificadorOpenAI.desde_entorno().modelos == ["m1"]
