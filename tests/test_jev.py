"""Capa 1: la segunda opinión de Jev, con un transporte falso (sin red)."""
import pytest

from conftest import cargar, llm
from postllamada.jev import ConSegundaOpinionJev, Jev
from postllamada.llm import ErrorClasificacion


class Principal:
    def __init__(self, resultado=None):
        self.resultado = resultado

    def clasificar(self, evento, zona):
        if self.resultado is None:
            raise ErrorClasificacion("caído")
        return self.resultado


def jev_que_responde(etiqueta: str, prob: float):
    return Jev(lambda cuerpo: {"answers": {"etiqueta": {"type": "choice", "choice": etiqueta, "confidence": prob,
                                                          "probabilities": {etiqueta: prob}}}})


def jev_caido():
    def falla(cuerpo):
        raise ConnectionError("sin red")
    return Jev(falla)


EV = cargar("04-call-ended-rosa.json")


def test_con_confianza_alta_no_consulta_a_jev():
    llamadas = []
    jev = Jev(lambda c: llamadas.append(c) or {})
    r = ConSegundaOpinionJev(Principal(llm("cortada", 0.9)), jev).clasificar(EV, None)
    assert r.etiqueta == "cortada" and llamadas == []


def test_con_duda_gana_la_opinion_mas_segura():
    r = ConSegundaOpinionJev(Principal(llm("otro", 0.5, nota_contexto="n")), jev_que_responde("cortada", 0.9)).clasificar(EV, None)
    assert r.etiqueta == "cortada" and r.fuente == "jev" and r.confianza == 0.9
    assert r.datos.nota_contexto == "n"  # se conservan los datos del LLM


def test_con_duda_si_jev_esta_menos_seguro_se_queda_el_llm():
    r = ConSegundaOpinionJev(Principal(llm("otro", 0.6)), jev_que_responde("cortada", 0.4)).clasificar(EV, None)
    assert r.etiqueta == "otro" and "Jev proponía" in r.motivo


def test_si_coinciden_sube_la_confianza():
    r = ConSegundaOpinionJev(Principal(llm("cortada", 0.6)), jev_que_responde("cortada", 0.95)).clasificar(EV, None)
    assert r.etiqueta == "cortada" and r.confianza == 0.95


def test_si_el_principal_cae_clasifica_jev():
    r = ConSegundaOpinionJev(Principal(None), jev_que_responde("descartado", 0.88)).clasificar(EV, None)
    assert r.etiqueta == "descartado" and r.fuente == "jev"


def test_si_caen_los_dos_se_propaga_el_error_del_principal():
    with pytest.raises(ErrorClasificacion):
        ConSegundaOpinionJev(Principal(None), jev_caido()).clasificar(EV, None)


def test_si_jev_cae_con_duda_se_queda_el_llm():
    r = ConSegundaOpinionJev(Principal(llm("otro", 0.5)), jev_caido()).clasificar(EV, None)
    assert r.etiqueta == "otro"


def test_opcion_desconocida_de_jev_se_ignora():
    r = ConSegundaOpinionJev(Principal(llm("otro", 0.5)), jev_que_responde("inventada", 0.99)).clasificar(EV, None)
    assert r.etiqueta == "otro"


def test_la_peticion_lleva_la_transcripcion_y_los_criterios_versionados():
    enviado = {}
    Jev(lambda c: enviado.update(c) or {"answers": {"etiqueta": {"choice": "cortada", "confidence": 1}}}).decidir(EV)
    assert enviado["model"] == "typesafe/jev-1.13"
    assert "mil dosci" in enviado["state"]["transcripcion"]
    assert set(enviado["questions"]["etiqueta"]["criteria"]) >= {"no_contactar", "cortada", "otro"}
