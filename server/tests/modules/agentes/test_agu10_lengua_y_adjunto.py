"""#218 — la lengua de la respuesta y el adjunto en tres niveles.

Decisiones del usuario (2026-10-04), tras probar la extensión:

* **La lengua de la respuesta es una declaración del agente**, no texto del prompt: hay documentos
  que se redactan siempre en castellano (pliegos), otros siempre en valenciano (resoluciones), y en
  lo demás se responde en la lengua de la pregunta. **La instrucción la añade la plataforma**,
  como la abstención, para que se cumpla igual aunque la unidad no la escriba.
* **El adjunto, en tres niveles**: `no`, `opcional` —quien pregunta dice si adjunta— y
  `obligatorio`. Lo decide la unidad, sin obligar a quien pregunta a pensarlo en cada consulta.
* **El asistente de prompts las recibe**, para no repetir ni contradecir lo que añade la plataforma.
"""
from __future__ import annotations

import pytest

from server.tests.modules.agentes._comun import FICHAS, persona, publicar

PREGUNTA = "¿Cuál es el importe máximo de un contrato menor de servicios?"
CON_ADJUNTO = "te adjuntará un documento"


async def _agente(c, **declaracion) -> dict:
    agente = await publicar(c, **declaracion)
    assert (await c.put(f"/api/v1/agentes/{agente['id']}/indice", json={"fichas": FICHAS})).status_code == 200
    return agente


async def _prompt(c, quien, agente_id, **extra) -> dict:
    quien.actual = persona()
    r = await c.post(f"/api/v1/agentes/{agente_id}/consulta", json={"consulta": PREGUNTA, **extra})
    assert r.status_code == 200, r.text
    return r.json()


class TestLaDeclaracion:

    @pytest.mark.asyncio
    async def test_por_defecto_la_lengua_de_la_pregunta_y_sin_adjunto(self, http):
        c, _ = http
        version = (await publicar(c))["version"]
        assert version["lengua_respuesta"] == "pregunta"
        assert version["adjunto"] == "no"

    @pytest.mark.asyncio
    async def test_se_declaran_al_publicar_y_el_catalogo_dice_el_adjunto(self, http):
        c, quien = http
        agente = await publicar(c, lengua_respuesta="es", adjunto="opcional")
        assert agente["version"]["lengua_respuesta"] == "es"
        assert agente["version"]["adjunto"] == "opcional"
        quien.actual = persona()
        [en_catalogo] = (await c.get("/api/v1/agentes/catalogo")).json()
        assert en_catalogo["adjunto"] == "opcional"

    @pytest.mark.parametrize("campo,valor", [("lengua_respuesta", "fr"), ("adjunto", "a veces")])
    @pytest.mark.asyncio
    async def test_solo_los_valores_que_hay(self, http, campo, valor):
        from server.tests.modules.agentes._comun import declaracion

        c, _ = http
        r = await c.post("/api/v1/agentes", json=declaracion(**{campo: valor}))
        assert r.status_code == 422


class TestLaLenguaDeLaRespuesta:

    @pytest.mark.asyncio
    async def test_la_de_la_pregunta(self, http):
        c, quien = http
        agente = await _agente(c)
        prompt = (await _prompt(c, quien, agente["id"]))["prompt"]
        assert "Responde en la lengua en que está escrita la pregunta." in prompt

    @pytest.mark.asyncio
    async def test_siempre_en_castellano(self, http):
        c, quien = http
        agente = await _agente(c, lengua_respuesta="es")
        prompt = (await _prompt(c, quien, agente["id"]))["prompt"]
        assert "Redacta la respuesta en castellano, aunque la pregunta o los documentos estén en otra lengua." in prompt

    @pytest.mark.asyncio
    async def test_siempre_en_valenciano_y_la_instruccion_en_la_lengua_de_la_pantalla(self, http):
        c, quien = http
        agente = await _agente(c, lengua_respuesta="ca")
        prompt = (await _prompt(c, quien, agente["id"], lengua="ca"))["prompt"]
        assert "Redacta la resposta en valencià, encara que la pregunta o els documents estiguen en una altra llengua." in prompt


class TestElAdjunto:

    @pytest.mark.asyncio
    async def test_opcional_y_quien_pregunta_dice_que_adjunta(self, http):
        c, quien = http
        agente = await _agente(c, adjunto="opcional")
        cuerpo = await _prompt(c, quien, agente["id"], adjunta=True)
        assert CON_ADJUNTO in cuerpo["prompt"]
        assert cuerpo["espera_adjunto"] is True

    @pytest.mark.asyncio
    async def test_opcional_y_no_adjunta(self, http):
        c, quien = http
        agente = await _agente(c, adjunto="opcional")
        cuerpo = await _prompt(c, quien, agente["id"])
        assert CON_ADJUNTO not in cuerpo["prompt"]
        assert cuerpo["espera_adjunto"] is False

    @pytest.mark.asyncio
    async def test_obligatorio_aunque_no_lo_diga(self, http):
        c, quien = http
        agente = await _agente(c, adjunto="obligatorio")
        cuerpo = await _prompt(c, quien, agente["id"])
        assert CON_ADJUNTO in cuerpo["prompt"]
        assert cuerpo["espera_adjunto"] is True

    @pytest.mark.asyncio
    async def test_sin_adjunto_aunque_lo_diga(self, http):
        c, quien = http
        agente = await _agente(c, adjunto="no")
        cuerpo = await _prompt(c, quien, agente["id"], adjunta=True)
        assert CON_ADJUNTO not in cuerpo["prompt"]
        assert cuerpo["espera_adjunto"] is False


class TestElAsistenteDePrompts:

    def test_sabe_que_la_lengua_la_pone_la_plataforma(self):
        from server.app.modules.agentes import propuesta

        sistema = propuesta.meta_prompt("es", adjunto="no")
        assert "en qué lengua responder" in sistema
        assert propuesta.VERSION_META_PROMPT == "propuesta-prompt-v2"

    def test_recibe_las_dos_declaraciones(self):
        from server.app.modules.agentes import propuesta

        [_, usuario] = propuesta.mensajes(
            descripcion="Revisar pliegos de contratación",
            nombre=None,
            unidad=None,
            finalidad=None,
            colectivo=None,
            grupos=[],
            adjunto="opcional",
            lengua_respuesta="es",
            lengua="es",
        )
        assert "Quien consulta puede adjuntar un documento propio, o no" in usuario["content"]
        assert "La respuesta se redacta siempre en castellano" in usuario["content"]

    def test_con_adjunto_opcional_el_prompt_sirve_para_los_dos_casos(self):
        from server.app.modules.agentes import propuesta

        sistema = propuesta.meta_prompt("es", adjunto="opcional")
        assert "los dos casos" in sistema
