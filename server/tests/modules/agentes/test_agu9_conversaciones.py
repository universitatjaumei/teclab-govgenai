"""#216 — registrar las conversaciones con los agentes, en validación o sólo las incidencias.

Decisión del usuario (2026-10-03): son conversaciones de trabajo sobre documentos de la
organización, quien las tiene sabe que se registran, y **prevalece la calidad de las respuestas**.
Como las conversaciones de los chatbots (`hub_interactions`).

Dos modos por agente:

* **validación** —el de partida—: cada consulta guarda la pregunta, y la extensión manda la
  respuesta que leyó en el asistente;
* **incidencias**: sólo se guarda lo que quien usa el agente informa como inadecuado.

Lo que fija:
- el modo lo cambian quien publica y quien revisa, con su sesión; y se anuncia en el catálogo y en
  la consulta, para que la pantalla avise de que se guarda;
- **sólo quien consultó** manda la respuesta y la valoración de su consulta;
- **el registro de actividad sigue sin la pregunta**: registra usos, no conversaciones;
- un informe dice un motivo de los que sirve la plataforma, no uno inventado por la pantalla.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from server.tests.modules.agentes._comun import FICHAS, persona, publicar

PREGUNTA = "¿Cuál es el importe máximo de un contrato menor de servicios?"
RESPUESTA = "El importe máximo de un contrato menor de servicios es de 15.000 euros, IVA excluido."
CONSULTA = {"X-Prueba-Scopes": "agentes:consulta"}


async def _agente(c, **declaracion) -> dict:
    agente = await publicar(c, **declaracion)
    assert (await c.put(f"/api/v1/agentes/{agente['id']}/indice", json={"fichas": FICHAS})).status_code == 200
    return agente


async def _consultar(c, agente_id) -> dict:
    r = await c.post(f"/api/v1/agentes/{agente_id}/consulta", json={"consulta": PREGUNTA}, headers=CONSULTA)
    assert r.status_code == 200, r.text
    return r.json()


async def _fila(db_session, consulta_id):
    from server.app.modules.agents_hub.database.operational_models import HubAgenteConsulta

    db_session.expire_all()
    return (
        await db_session.execute(select(HubAgenteConsulta).where(HubAgenteConsulta.id == consulta_id))
    ).scalar_one()


class TestElModo:

    @pytest.mark.asyncio
    async def test_un_agente_nuevo_empieza_en_validacion(self, http):
        c, _ = http
        agente = await _agente(c)
        assert agente["modo_registro"] == "validacion"
        assert "cambiar_registro" in agente["version"]["acciones_permitidas"]

    @pytest.mark.asyncio
    async def test_quien_publica_lo_pasa_a_incidencias(self, http):
        c, _ = http
        agente = await _agente(c)
        r = await c.post(f"/api/v1/agentes/{agente['id']}/registro", json={"modo": "incidencias"})
        assert r.status_code == 200, r.text
        assert r.json()["modo_registro"] == "incidencias"

    @pytest.mark.asyncio
    async def test_y_quien_revisa_tambien(self, http):
        c, quien = http
        agente = await _agente(c)
        quien.actual = persona("admin")
        r = await c.post(f"/api/v1/agentes/{agente['id']}/registro", json={"modo": "incidencias"})
        assert r.status_code == 200, r.text

    @pytest.mark.asyncio
    async def test_quien_sólo_lo_usa_no(self, http):
        c, quien = http
        agente = await _agente(c)
        quien.actual = persona()
        r = await c.post(f"/api/v1/agentes/{agente['id']}/registro", json={"modo": "incidencias"})
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_ni_con_un_token(self, http):
        c, _ = http
        agente = await _agente(c)
        r = await c.post(
            f"/api/v1/agentes/{agente['id']}/registro", json={"modo": "incidencias"}, headers=CONSULTA
        )
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_solo_los_dos_modos_que_hay(self, http):
        c, _ = http
        agente = await _agente(c)
        r = await c.post(f"/api/v1/agentes/{agente['id']}/registro", json={"modo": "todo"})
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_el_catalogo_y_la_consulta_lo_anuncian(self, http):
        c, quien = http
        agente = await _agente(c)
        quien.actual = persona()
        assert (await c.get("/api/v1/agentes/catalogo")).json()[0]["modo_registro"] == "validacion"
        cuerpo = await _consultar(c, agente["id"])
        assert cuerpo["modo_registro"] == "validacion"
        assert cuerpo["consulta_id"]


class TestEnValidacion:

    @pytest.mark.asyncio
    async def test_la_consulta_guarda_la_pregunta(self, http, db_session):
        c, quien = http
        agente = await _agente(c)
        quien.actual = persona()
        cuerpo = await _consultar(c, agente["id"])
        fila = await _fila(db_session, cuerpo["consulta_id"])
        assert fila.pregunta == PREGUNTA
        assert fila.modo == "validacion"

    @pytest.mark.asyncio
    async def test_la_extension_manda_la_respuesta_y_las_fuentes(self, http, db_session):
        c, quien = http
        agente = await _agente(c)
        quien.actual = persona()
        cuerpo = await _consultar(c, agente["id"])
        r = await c.post(
            f"/api/v1/agentes/consultas/{cuerpo['consulta_id']}/respuesta",
            json={"texto": RESPUESTA, "fuentes": ["https://drive.google.com/file/d/1"]},
            headers=CONSULTA,
        )
        assert r.status_code == 204, r.text
        fila = await _fila(db_session, cuerpo["consulta_id"])
        assert fila.respuesta == RESPUESTA
        assert fila.fuentes == ["https://drive.google.com/file/d/1"]
        assert fila.respuesta_en is not None

    @pytest.mark.asyncio
    async def test_si_no_pudo_leerla_lo_dice_y_queda_contado(self, http, db_session):
        c, quien = http
        agente = await _agente(c)
        quien.actual = persona()
        cuerpo = await _consultar(c, agente["id"])
        r = await c.post(
            f"/api/v1/agentes/consultas/{cuerpo['consulta_id']}/respuesta",
            json={"no_capturada": "sin_terminar"},
            headers=CONSULTA,
        )
        assert r.status_code == 204, r.text
        fila = await _fila(db_session, cuerpo["consulta_id"])
        assert fila.respuesta is None
        assert fila.respuesta_no_capturada == "sin_terminar"

    @pytest.mark.asyncio
    async def test_o_la_respuesta_o_por_que_no_la_hay(self, http):
        c, quien = http
        agente = await _agente(c)
        quien.actual = persona()
        cuerpo = await _consultar(c, agente["id"])
        url = f"/api/v1/agentes/consultas/{cuerpo['consulta_id']}/respuesta"
        assert (await c.post(url, json={}, headers=CONSULTA)).status_code == 422
        assert (
            await c.post(url, json={"texto": RESPUESTA, "no_capturada": "sin_terminar"}, headers=CONSULTA)
        ).status_code == 422

    @pytest.mark.asyncio
    async def test_la_respuesta_se_manda_una_vez(self, http):
        c, quien = http
        agente = await _agente(c)
        quien.actual = persona()
        cuerpo = await _consultar(c, agente["id"])
        url = f"/api/v1/agentes/consultas/{cuerpo['consulta_id']}/respuesta"
        assert (await c.post(url, json={"texto": RESPUESTA}, headers=CONSULTA)).status_code == 204
        assert (await c.post(url, json={"texto": "otra"}, headers=CONSULTA)).status_code == 409

    @pytest.mark.asyncio
    async def test_la_de_otra_persona_no_existe(self, http):
        c, quien = http
        agente = await _agente(c)
        quien.actual = persona()
        cuerpo = await _consultar(c, agente["id"])
        quien.actual = persona()
        r = await c.post(
            f"/api/v1/agentes/consultas/{cuerpo['consulta_id']}/respuesta",
            json={"texto": RESPUESTA},
            headers=CONSULTA,
        )
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_el_registro_de_actividad_sigue_sin_la_pregunta(self, http, db_session):
        from server.app.modules.agents_hub.database.operational_models import HubActividadIA

        c, quien = http
        agente = await _agente(c)
        quien.actual = persona()
        await _consultar(c, agente["id"])
        for fila in (await db_session.execute(select(HubActividadIA))).scalars():
            for columna in HubActividadIA.__table__.columns:
                assert "importe máximo" not in str(getattr(fila, columna.key, ""))


class TestEnIncidencias:

    async def _en_incidencias(self, c) -> dict:
        agente = await _agente(c)
        await c.post(f"/api/v1/agentes/{agente['id']}/registro", json={"modo": "incidencias"})
        return agente

    @pytest.mark.asyncio
    async def test_la_consulta_no_guarda_la_pregunta(self, http, db_session):
        c, quien = http
        agente = await self._en_incidencias(c)
        quien.actual = persona()
        cuerpo = await _consultar(c, agente["id"])
        assert cuerpo["modo_registro"] == "incidencias"
        fila = await _fila(db_session, cuerpo["consulta_id"])
        assert fila.pregunta is None
        assert fila.modo == "incidencias"

    @pytest.mark.asyncio
    async def test_no_se_manda_la_respuesta_de_cada_consulta(self, http):
        c, quien = http
        agente = await self._en_incidencias(c)
        quien.actual = persona()
        cuerpo = await _consultar(c, agente["id"])
        r = await c.post(
            f"/api/v1/agentes/consultas/{cuerpo['consulta_id']}/respuesta",
            json={"texto": RESPUESTA},
            headers=CONSULTA,
        )
        assert r.status_code == 409

    @pytest.mark.asyncio
    async def test_un_informe_guarda_la_pregunta_la_respuesta_el_motivo_y_el_comentario(self, http, db_session):
        c, quien = http
        agente = await self._en_incidencias(c)
        quien.actual = persona()
        cuerpo = await _consultar(c, agente["id"])
        r = await c.post(
            f"/api/v1/agentes/consultas/{cuerpo['consulta_id']}/valoracion",
            json={
                "puntuacion": -1,
                "motivo": "desactualizado",
                "comentario": "La instrucción nueva dice otra cosa",
                "pregunta": PREGUNTA,
                "respuesta": RESPUESTA,
            },
            headers=CONSULTA,
        )
        assert r.status_code == 204, r.text
        fila = await _fila(db_session, cuerpo["consulta_id"])
        assert (fila.puntuacion, fila.motivo, fila.comentario) == (-1, "desactualizado", "La instrucción nueva dice otra cosa")
        assert (fila.pregunta, fila.respuesta) == (PREGUNTA, RESPUESTA)

    @pytest.mark.asyncio
    async def test_una_valoracion_buena_no_guarda_contenido(self, http, db_session):
        c, quien = http
        agente = await self._en_incidencias(c)
        quien.actual = persona()
        cuerpo = await _consultar(c, agente["id"])
        r = await c.post(
            f"/api/v1/agentes/consultas/{cuerpo['consulta_id']}/valoracion",
            json={"puntuacion": 1, "pregunta": PREGUNTA, "respuesta": RESPUESTA},
            headers=CONSULTA,
        )
        assert r.status_code == 204, r.text
        fila = await _fila(db_session, cuerpo["consulta_id"])
        assert fila.puntuacion == 1
        assert fila.pregunta is None and fila.respuesta is None


class TestLaValoracion:

    @pytest.mark.asyncio
    async def test_en_validacion_se_valora_y_se_puede_cambiar(self, http, db_session):
        c, quien = http
        agente = await _agente(c)
        quien.actual = persona()
        cuerpo = await _consultar(c, agente["id"])
        url = f"/api/v1/agentes/consultas/{cuerpo['consulta_id']}/valoracion"
        assert (await c.post(url, json={"puntuacion": 1}, headers=CONSULTA)).status_code == 204
        r = await c.post(url, json={"puntuacion": -1, "motivo": "inventa"}, headers=CONSULTA)
        assert r.status_code == 204, r.text
        fila = await _fila(db_session, cuerpo["consulta_id"])
        assert (fila.puntuacion, fila.motivo) == (-1, "inventa")
        # La pregunta ya estaba; la valoración no la pisa.
        assert fila.pregunta == PREGUNTA

    @pytest.mark.asyncio
    async def test_un_informe_lleva_motivo_y_de_los_que_hay(self, http):
        c, quien = http
        agente = await _agente(c)
        quien.actual = persona()
        cuerpo = await _consultar(c, agente["id"])
        url = f"/api/v1/agentes/consultas/{cuerpo['consulta_id']}/valoracion"
        assert (await c.post(url, json={"puntuacion": -1}, headers=CONSULTA)).status_code == 422
        assert (await c.post(url, json={"puntuacion": -1, "motivo": "me cae mal"}, headers=CONSULTA)).status_code == 422
        assert (await c.post(url, json={"puntuacion": 0}, headers=CONSULTA)).status_code == 422

    @pytest.mark.asyncio
    async def test_la_de_otra_persona_no_existe(self, http):
        c, quien = http
        agente = await _agente(c)
        quien.actual = persona()
        cuerpo = await _consultar(c, agente["id"])
        quien.actual = persona()
        r = await c.post(
            f"/api/v1/agentes/consultas/{cuerpo['consulta_id']}/valoracion", json={"puntuacion": 1}, headers=CONSULTA
        )
        assert r.status_code == 404


class TestLosMotivos:

    @pytest.mark.asyncio
    async def test_los_sirve_la_plataforma_en_la_lengua_pedida(self, http):
        c, _ = http
        r = await c.get("/api/v1/agentes/motivos-de-informe", params={"lengua": "ca"}, headers=CONSULTA)
        assert r.status_code == 200, r.text
        motivos = {m["codigo"]: m["etiqueta"] for m in r.json()}
        assert set(motivos) == {"no_abre", "desactualizado", "inventa", "incompleta", "no_responde", "otro"}
        assert motivos["inventa"] == "S'inventa coses"
