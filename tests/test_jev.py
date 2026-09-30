"""Capa 1: Jev como añadido opcional (segunda opinión y modo rápido), con un transporte falso (sin red)."""
import pytest

from conftest import cargar, llm
from postllamada.jev import ClasificadorConJev, Jev
from postllamada.llm import ErrorClasificacion


class Principal:
    def __init__(self, resultado=None):
        self.resultado = resultado
        self.llamadas = 0

    def clasificar(self, evento, zona):
        self.llamadas += 1
        if self.resultado is None:
            raise ErrorClasificacion("caído")
        return self.resultado


def jev_que_responde(etiqueta: str, prob: float, llamadas: list | None = None):
    def responder(cuerpo):
        if llamadas is not None:
            llamadas.append(cuerpo)
        return {"answers": {"etiqueta": {"type": "choice", "choice": etiqueta, "confidence": prob,
                                         "probabilities": {etiqueta: prob}}}}
    return Jev(responder)


def jev_caido():
    def falla(cuerpo):
        raise ConnectionError("sin red")
    return Jev(falla)


EV = cargar("04-call-ended-rosa.json")


def test_con_confianza_alta_no_consulta_a_jev():
    llamadas = []
    jev = Jev(lambda c: llamadas.append(c) or {})
    r = ClasificadorConJev(Principal(llm("cortada", 0.9)), jev).clasificar(EV, None)
    assert r.etiqueta == "cortada" and llamadas == []


def test_con_duda_gana_la_opinion_mas_segura():
    r = ClasificadorConJev(Principal(llm("otro", 0.5, nota_contexto="n")), jev_que_responde("cortada", 0.9)).clasificar(EV, None)
    assert r.etiqueta == "cortada" and r.fuente == "jev" and r.confianza == 0.9
    assert r.datos.nota_contexto == "n"  # se conservan los datos del LLM


def test_con_duda_si_jev_esta_menos_seguro_se_queda_el_llm():
    r = ClasificadorConJev(Principal(llm("otro", 0.6)), jev_que_responde("cortada", 0.4)).clasificar(EV, None)
    assert r.etiqueta == "otro" and "Jev proponía" in r.motivo


def test_si_coinciden_sube_la_confianza():
    r = ClasificadorConJev(Principal(llm("cortada", 0.6)), jev_que_responde("cortada", 0.95)).clasificar(EV, None)
    assert r.etiqueta == "cortada" and r.confianza == 0.95


def test_si_el_principal_cae_clasifica_jev():
    r = ClasificadorConJev(Principal(None), jev_que_responde("descartado", 0.88)).clasificar(EV, None)
    assert r.etiqueta == "descartado" and r.fuente == "jev"


def test_si_caen_los_dos_se_propaga_el_error_del_principal():
    with pytest.raises(ErrorClasificacion):
        ClasificadorConJev(Principal(None), jev_caido()).clasificar(EV, None)


def test_si_jev_cae_con_duda_se_queda_el_llm():
    r = ClasificadorConJev(Principal(llm("otro", 0.5)), jev_caido()).clasificar(EV, None)
    assert r.etiqueta == "otro"


def test_opcion_desconocida_de_jev_se_ignora():
    r = ClasificadorConJev(Principal(llm("otro", 0.5)), jev_que_responde("inventada", 0.99)).clasificar(EV, None)
    assert r.etiqueta == "otro"


def test_la_peticion_lleva_la_transcripcion_y_los_criterios_versionados():
    enviado = {}
    Jev(lambda c: enviado.update(c) or {"answers": {"etiqueta": {"choice": "cortada", "confidence": 1}}}).decidir(EV)
    assert enviado["model"] == "typesafe/jev-1.13"
    assert "mil dosci" in enviado["state"]["transcripcion"]
    assert set(enviado["questions"]["etiqueta"]["criteria"]) >= {"no_contactar", "cortada", "otro"}


# --- Modo rápido: Jev primero ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("etiqueta", ["no_contactar", "descartado", "persona_equivocada"])
def test_rapido_jev_seguro_sin_datos_evita_el_modelo_principal(etiqueta):
    principal = Principal(llm("otro", 0.99))
    r = ClasificadorConJev(principal, jev_que_responde(etiqueta, 0.97), modo="rapido").clasificar(EV, None)
    assert (r.etiqueta, r.fuente, r.confianza, principal.llamadas) == (etiqueta, "jev", 0.97, 0)
    assert r.motivo.startswith("Jev (0.97): ")
    assert "(" not in r.motivo.removeprefix("Jev (0.97)")


def test_rapido_etiqueta_que_necesita_datos_pasa_por_el_principal():
    principal, consultas = Principal(llm("callback", 0.95, callback_hora="18:00")), []
    r = ClasificadorConJev(principal, jev_que_responde("callback", 0.99, consultas), modo="rapido").clasificar(EV, None)
    assert (r.etiqueta, r.fuente, r.datos.callback_hora, principal.llamadas, len(consultas)) == ("callback", "llm", "18:00", 1, 1)


def test_rapido_jev_poco_seguro_pasa_por_el_principal():
    principal = Principal(llm("cortada", 0.9))
    r = ClasificadorConJev(principal, jev_que_responde("descartado", 0.85), modo="rapido").clasificar(EV, None)
    assert (r.etiqueta, principal.llamadas) == ("cortada", 1)


def test_rapido_reutiliza_la_opinion_de_jev_si_el_principal_duda():
    consultas = []
    r = ClasificadorConJev(Principal(llm("otro", 0.5)), jev_que_responde("cortada", 0.8, consultas), modo="rapido").clasificar(EV, None)
    assert (r.etiqueta, r.fuente, len(consultas)) == ("cortada", "jev", 1)


def test_rapido_si_cae_el_principal_usa_la_opinion_ya_obtenida():
    consultas = []
    r = ClasificadorConJev(Principal(None), jev_que_responde("callback", 0.8, consultas), modo="rapido").clasificar(EV, None)
    assert (r.etiqueta, r.fuente, len(consultas)) == ("callback", "jev", 1)


def test_rapido_con_jev_caido_es_igual_que_sin_jev():
    principal = Principal(llm("cortada", 0.9))
    r = ClasificadorConJev(principal, jev_caido(), modo="rapido").clasificar(EV, None)
    assert (r.etiqueta, r.fuente, principal.llamadas) == ("cortada", "llm", 1)


def test_modo_desconocido_se_rechaza():
    with pytest.raises(ValueError):
        ClasificadorConJev(Principal(), jev_caido(), modo="turbo")


# --- Activación desde run.py: apagado por defecto -------------------------------------------------------------------

@pytest.fixture
def entorno_run(monkeypatch):
    import run
    for var in ("JEV_ACTIVADO", "JEV_MODO", "OPENROUTER_API_KEY", "OPENAI_BASE_URL", "MODELO", "MODELO_RESPALDO"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-prueba")
    return run


def test_por_defecto_solo_el_modelo_de_openai(entorno_run, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "clave")  # tener la clave no basta: hay que activarlo
    assert type(entorno_run.crear_clasificador()).__name__ == "ClasificadorOpenAI"


@pytest.mark.parametrize("modo, esperado", [(None, "segunda_opinion"), ("rapido", "rapido")])
def test_activado_con_clave_envuelve_al_principal(entorno_run, monkeypatch, modo, esperado):
    monkeypatch.setenv("JEV_ACTIVADO", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "clave")
    if modo:
        monkeypatch.setenv("JEV_MODO", modo)
    c = entorno_run.crear_clasificador()
    assert isinstance(c, ClasificadorConJev) and c.modo == esperado
    assert type(c.principal).__name__ == "ClasificadorOpenAI"


@pytest.mark.parametrize("variables", [{"JEV_ACTIVADO": "1"}, {"JEV_ACTIVADO": "1", "OPENROUTER_API_KEY": "clave", "JEV_MODO": "turbo"}])
def test_mal_configurado_avisa_y_sigue_solo_con_openai(entorno_run, monkeypatch, capsys, variables):
    for k, v in variables.items():
        monkeypatch.setenv(k, v)
    assert type(entorno_run.crear_clasificador()).__name__ == "ClasificadorOpenAI"
    assert "aviso: JEV" in capsys.readouterr().err


# --- Integración: el lote completo con Jev en modo rápido da la misma salida ----------------------------------------

def test_lote_con_jev_rapido_da_la_misma_salida_que_sin_jev(tmp_path, cfg):
    from conftest import ClasificadorFalso, Entorno, errores_de_formato
    from test_lote_ejemplo import RESPUESTAS_LLM, orden_del_lote

    def lote(clasificador, carpeta):
        e = Entorno(tmp_path / carpeta, cfg, clasificador)
        for nombre in orden_del_lote():
            e.procesar(cargar(nombre))
        return e

    # Jev "acierta" con alta confianza lo mismo que el LLM falso: las etiquetas sin datos ya no llegan al LLM.
    jev = Jev(lambda c: {"answers": {"etiqueta": {"choice": ETIQUETA_POR_TRANSCRIPCION(c), "confidence": 0.97}}})
    solo = lote(ClasificadorFalso(RESPUESTAS_LLM), "solo")
    principal = ClasificadorFalso(RESPUESTAS_LLM)
    con_jev = lote(ClasificadorConJev(principal, jev, modo="rapido"), "jev")

    # Cambian los textos que citan el motivo y la confianza (los pone Jev); todo lo demás es idéntico.
    sin_motivo = lambda d: {k: v for k, v in d.items() if k not in ("motivo", "confianza", "detalle")}
    assert [sin_motivo(d) for d in con_jev.decisiones()] == [sin_motivo(d) for d in solo.decisiones()]
    assert [{**o, "cuerpo": sin_motivo(o["cuerpo"])} for o in con_jev.ordenes()] ==            [{**o, "cuerpo": sin_motivo(o["cuerpo"])} for o in solo.ordenes()]
    assert errores_de_formato(con_jev.decisiones(), con_jev.ordenes()) == []
    # 8 conversaciones en el lote; persona_equivocada (03) y no_contactar (06) las resolvió Jev solo
    assert principal.llamadas == 6


def ETIQUETA_POR_TRANSCRIPCION(cuerpo: dict) -> str:
    from test_lote_ejemplo import RESPUESTAS_LLM
    for evento in _eventos_con_conversacion():
        if evento["transcript"] and evento["transcript"][-1]["message"] in cuerpo["state"]["transcripcion"]:
            return RESPUESTAS_LLM[evento["idempotency_key"]].etiqueta
    raise AssertionError("transcripción desconocida")


def _eventos_con_conversacion():
    from test_lote_ejemplo import orden_del_lote
    return [e for e in map(cargar, orden_del_lote()) if e.get("transcript")]
