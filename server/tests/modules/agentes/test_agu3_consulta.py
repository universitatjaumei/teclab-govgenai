"""#175 — la consulta: prompt compuesto y URL, nunca el contenido.

Un cliente externo —la extensión de #176, o una persona copiando y pegando— manda la pregunta y el
agente, y recibe el prompt del agente con los enlaces a los documentos pertinentes. Lo ejecuta el
asistente general de la organización, que abre las URL con la identidad de quien pregunta.

Lo que fija este fichero:

* **Dos puertas independientes**: la plataforma selecciona y el almacén autoriza. Por eso se
  devuelven URL y no texto, y por eso **no se comprueba la accesibilidad** de cada enlace: la
  plataforma sólo podría hacerlo con su propia identidad, y eso no dice nada de la de quien pregunta.
* **Una instrucción de abstención explícita** en el prompt, literal: convierte el fallo silencioso
  —un enlace que no se puede abrir— en uno que quien pregunta lee.
* **Lo usa el colectivo, no quien publica**: la consulta no exige el módulo `agentes`, y un token
  necesita un alcance propio y estrecho, `agentes:consulta`.
* **Se registra lo que se ofreció, nunca lo que se preguntó**: quién, cuándo, qué agente, qué
  documentos y con qué puntuación. Ni la consulta ni el contenido llegan al registro.
"""
from __future__ import annotations

import hashlib
import uuid

import pytest
from sqlalchemy import select

from server.tests.modules.agentes._comun import (
    FICHAS,
    persona as _persona,
    publicar as _publicar,
)

ABSTENCION = "Si no puedes abrir los documentos enlazados, dilo y no respondas a partir de otra cosa."
PREGUNTA = "¿Cuál es el importe máximo de un contrato menor de servicios?"


async def _con_indice(c, **declaracion) -> dict:
    agente = await _publicar(c, **declaracion)
    r = await c.put(f"/api/v1/agentes/{agente['id']}/indice", json={"fichas": FICHAS})
    assert r.status_code == 200, r.text
    return agente


async def _consultar(c, agente_id, consulta=PREGUNTA, **extra):
    return await c.post(f"/api/v1/agentes/{agente_id}/consulta", json={"consulta": consulta, **extra})


class TestLoQueDevuelve:

    @pytest.mark.asyncio
    async def test_el_prompt_lleva_el_del_agente_la_pregunta_la_abstencion_y_los_enlaces(self, http):
        c, quien = http
        agente = await _con_indice(c)
        quien.actual = _persona()

        r = await _consultar(c, agente["id"])
        assert r.status_code == 200, r.text
        cuerpo = r.json()
        prompt = cuerpo["prompt"]
        assert "Eres el asistente de contratación." in prompt
        assert PREGUNTA in prompt
        assert ABSTENCION in prompt
        for doc in cuerpo["documentos"]:
            assert doc["url"] in prompt

    @pytest.mark.asyncio
    async def test_devuelve_url_y_no_contenido(self, http):
        c, quien = http
        agente = await _con_indice(c)
        quien.actual = _persona()
        cuerpo = (await _consultar(c, agente["id"])).json()

        assert set(cuerpo["documentos"][0]) == {"url", "titulo", "score", "revision_vencida"}
        # El resumen es de la ficha, no del documento, y tampoco va: el prompt lleva enlaces.
        assert "Trata del contrato menor." not in cuerpo["prompt"]

    @pytest.mark.asyncio
    async def test_lo_no_vigente_no_se_ofrece(self, http):
        c, quien = http
        agente = await _con_indice(c)
        quien.actual = _persona()
        urls = [d["url"] for d in (await _consultar(c, agente["id"])).json()["documentos"]]
        assert "https://drive.google.com/file/d/2" not in urls

    @pytest.mark.asyncio
    async def test_nunca_mas_que_el_presupuesto(self, http):
        c, quien = http
        agente = await _publicar(c, presupuesto_documentos=1)
        fichas = [
            {"url": f"https://drive.google.com/file/d/{n}", "titulo": f"Contrato {n}", "resumen": "contrato"}
            for n in range(5)
        ]
        await c.put(f"/api/v1/agentes/{agente['id']}/indice", json={"fichas": fichas})
        quien.actual = _persona()
        assert len((await _consultar(c, agente["id"])).json()["documentos"]) == 1

    @pytest.mark.asyncio
    async def test_sin_documentos_pertinentes_el_prompt_pide_decirlo(self, http):
        c, quien = http
        agente = await _publicar(c)
        quien.actual = _persona()
        cuerpo = (await _consultar(c, agente["id"])).json()
        assert cuerpo["documentos"] == []
        assert ABSTENCION in cuerpo["prompt"]
        assert "ningún documento" in cuerpo["prompt"]

    @pytest.mark.asyncio
    async def test_un_documento_pendiente_de_revision_se_marca(self, http):
        c, quien = http
        agente = await _publicar(c)
        fichas = [{**FICHAS[0], "revision_prevista_en": "2020-01-01"}]
        await c.put(f"/api/v1/agentes/{agente['id']}/indice", json={"fichas": fichas})
        quien.actual = _persona()
        cuerpo = (await _consultar(c, agente["id"])).json()
        assert cuerpo["documentos"][0]["revision_vencida"] is True
        assert "pendiente de revisión" in cuerpo["prompt"]

    @pytest.mark.asyncio
    async def test_en_valenciano_las_instrucciones_van_en_valenciano(self, http):
        c, quien = http
        agente = await _con_indice(c)
        quien.actual = _persona()
        prompt = (await _consultar(c, agente["id"], lengua="ca")).json()["prompt"]
        assert "Si no pots obrir els documents enllaçats" in prompt


class TestQuienPuede:

    @pytest.mark.asyncio
    async def test_un_token_sin_el_alcance_no_consulta(self, http):
        c, quien = http
        agente = await _con_indice(c)
        quien.actual = _persona()
        r = await c.post(
            f"/api/v1/agentes/{agente['id']}/consulta",
            json={"consulta": PREGUNTA},
            headers={"X-Prueba-Scopes": "agentes:indice"},
        )
        assert r.status_code == 403
        assert "PAT_SCOPE_MISSING" in r.text

    @pytest.mark.asyncio
    async def test_un_token_con_el_alcance_consulta(self, http):
        c, quien = http
        agente = await _con_indice(c)
        quien.actual = _persona()
        r = await c.post(
            f"/api/v1/agentes/{agente['id']}/consulta",
            json={"consulta": PREGUNTA},
            headers={"X-Prueba-Scopes": "agentes:consulta"},
        )
        assert r.status_code == 200, r.text

    @pytest.mark.asyncio
    async def test_fuera_del_colectivo_no_se_ofrece(self, http):
        c, quien = http
        agente = await _con_indice(c, colectivo="grupos", grupos=["PDI"])
        quien.actual = _persona()
        r = await _consultar(c, agente["id"])
        assert r.status_code == 403
        assert "AGENTE_NO_DISPONIBLE" in r.text

    @pytest.mark.asyncio
    async def test_suspendido_no_se_ofrece(self, http):
        c, quien = http
        agente = await _con_indice(c)
        quien.actual = _persona("admin")
        await c.post(f"/api/v1/agentes/{agente['id']}/suspender", json={"motivo": "anexo superado"})
        quien.actual = _persona()
        assert (await _consultar(c, agente["id"])).status_code == 403

    @pytest.mark.asyncio
    async def test_de_otra_organizacion_es_un_404(self, http):
        c, quien = http
        agente = await _con_indice(c)
        quien.actual = _persona(orgs=(str(uuid.uuid4()),))
        assert (await _consultar(c, agente["id"])).status_code == 404

    @pytest.mark.asyncio
    @pytest.mark.parametrize("consulta", ["", "   ", "x" * 2001])
    async def test_una_consulta_vacia_o_desmedida_es_un_422(self, http, consulta):
        c, quien = http
        agente = await _con_indice(c)
        quien.actual = _persona()
        assert (await _consultar(c, agente["id"], consulta=consulta)).status_code == 422

    @pytest.mark.asyncio
    async def test_un_indice_de_otro_modelo_es_un_409(self, http, db_session):
        from sqlalchemy import update

        from server.app.modules.agents_hub.database.operational_models import HubAgenteFicha

        c, quien = http
        agente = await _con_indice(c)
        await db_session.execute(update(HubAgenteFicha).values(embedding_model="otro-modelo"))
        await db_session.commit()
        quien.actual = _persona()
        r = await _consultar(c, agente["id"])
        assert r.status_code == 409
        assert "volver a cargar" in r.text


class TestLoQueSeRegistra:

    @pytest.mark.asyncio
    async def test_queda_un_uso_en_el_registro_con_sus_metadatos(self, http, db_session):
        from server.app.modules.agents_hub.database.operational_models import HubActividadIA

        c, quien = http
        agente = await _con_indice(c)
        persona = _persona()
        quien.actual = persona
        cuerpo = (await _consultar(c, agente["id"])).json()

        filas = (await db_session.execute(select(HubActividadIA))).scalars().all()
        assert len(filas) == 1
        uso = filas[0]
        assert str(uso.organizacion_id) == persona.organizacion_ids[0]
        assert uso.actor == persona.user_id
        assert uso.herramienta == "agente-de-unidad"
        assert agente["id"] in uso.agente
        assert uso.finalidad == "Orientar"
        # El hash del prompt entregado: coteja sin guardar el texto.
        assert uso.payload_hash == hashlib.sha256(cuerpo["prompt"].encode("utf-8")).hexdigest()

    @pytest.mark.asyncio
    async def test_queda_que_documentos_se_ofrecieron_y_con_que_puntuacion(self, http, db_session):
        from server.app.modules.agents_hub.database.operational_models import HubAgenteConsulta

        c, quien = http
        agente = await _con_indice(c)
        quien.actual = _persona()
        cuerpo = (await _consultar(c, agente["id"])).json()

        consulta = (await db_session.execute(select(HubAgenteConsulta))).scalars().one()
        assert str(consulta.agente_id) == agente["id"]
        assert consulta.version == 1
        assert consulta.documentos == [{"url": d["url"], "score": d["score"]} for d in cuerpo["documentos"]]

    @pytest.mark.asyncio
    async def test_la_pregunta_no_llega_a_ningun_registro(self, http, db_session):
        """Ni en el registro de actividad ni en el de consultas, en ninguna columna."""
        from server.app.modules.agents_hub.database.operational_models import (
            HubActividadIA,
            HubAgenteConsulta,
        )

        c, quien = http
        agente = await _con_indice(c)
        quien.actual = _persona()
        await _consultar(c, agente["id"])

        for modelo in (HubActividadIA, HubAgenteConsulta):
            for fila in (await db_session.execute(select(modelo))).scalars():
                for columna in modelo.__table__.columns:
                    assert "importe máximo" not in str(getattr(fila, columna.key, ""))

    @pytest.mark.asyncio
    async def test_un_fallo_no_registra_un_uso(self, http, db_session):
        from server.app.modules.agents_hub.database.operational_models import HubActividadIA

        c, quien = http
        agente = await _con_indice(c, colectivo="grupos", grupos=["PDI"])
        quien.actual = _persona()
        await _consultar(c, agente["id"])
        assert (await db_session.execute(select(HubActividadIA))).scalars().all() == []


class TestElToken:

    def test_hay_un_alcance_para_consultar(self):
        from server.app.core.auth.pat.scopes import AGENTES_CONSULTA, ALL_SCOPES

        assert AGENTES_CONSULTA == "agentes:consulta"
        assert AGENTES_CONSULTA in ALL_SCOPES

