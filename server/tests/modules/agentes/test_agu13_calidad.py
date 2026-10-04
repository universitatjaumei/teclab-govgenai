"""#217 — la calidad de un agente: conversaciones, informes y dónde está el fallo.

Lo que se guarda desde #216 —pregunta, datos, documentos ofrecidos, respuesta leída, valoración—
se ve en una pestaña para **quien publicó el agente y quien lo revisa en su organización**, y
nadie más. Con todo junto se ve dónde está el fallo: el índice (no se ofreció el documento que
tocaba, o estaba superado), el prompt (el documento estaba y la respuesta no lo usó) o el modelo.

Lo que fija:
- la lista, de lo más reciente a lo más antiguo, con los títulos de los documentos ofrecidos y
  **sin decir quién preguntó**: para corregir el agente no hace falta, y no se enseña;
- los filtros: modo, valoración, motivo y lo que falta por revisar;
- el veredicto `good`/`bad`/`mixed` y una nota, como en la revisión de los chatbots;
- una pista por motivo, que calcula el servidor;
- los contadores en la ficha: consultas, respuestas leídas e informes sin revisar.
"""
from __future__ import annotations

import uuid

import pytest

from server.tests.modules.agentes._comun import FICHAS, ORG, persona, publicar

CONSULTA = {"X-Prueba-Scopes": "agentes:consulta"}


async def _agente(c) -> dict:
    agente = await publicar(c)
    assert (await c.put(f"/api/v1/agentes/{agente['id']}/indice", json={"fichas": FICHAS})).status_code == 200
    return agente


async def _conversacion(c, quien, agente_id, *, respuesta=None, valoracion=None, pregunta="¿Importe del contrato menor?"):
    autora = quien.actual
    quien.actual = persona()
    cuerpo = (await c.post(f"/api/v1/agentes/{agente_id}/consulta", json={"consulta": pregunta}, headers=CONSULTA)).json()
    if respuesta is not None:
        await c.post(f"/api/v1/agentes/consultas/{cuerpo['consulta_id']}/respuesta", json={"texto": respuesta}, headers=CONSULTA)
    if valoracion is not None:
        await c.post(f"/api/v1/agentes/consultas/{cuerpo['consulta_id']}/valoracion", json=valoracion, headers=CONSULTA)
    quien.actual = autora
    return cuerpo["consulta_id"]


class TestQuienLaVe:

    @pytest.mark.asyncio
    async def test_quien_publica_tiene_la_accion(self, http):
        c, _ = http
        agente = await _agente(c)
        assert "ver_calidad" in agente["version"]["acciones_permitidas"]

    @pytest.mark.asyncio
    async def test_quien_lo_revisa_tambien(self, http):
        c, quien = http
        agente = await _agente(c)
        quien.actual = persona("admin")
        assert (await c.get(f"/api/v1/agentes/{agente['id']}/conversaciones")).status_code == 200

    @pytest.mark.asyncio
    async def test_quien_solo_lo_usa_no(self, http):
        c, quien = http
        agente = await _agente(c)
        quien.actual = persona()
        assert (await c.get(f"/api/v1/agentes/{agente['id']}/conversaciones")).status_code == 403

    @pytest.mark.asyncio
    async def test_otra_organizacion_no_existe(self, http):
        c, quien = http
        agente = await _agente(c)
        quien.actual = persona("admin", orgs=(str(uuid.uuid4()),))
        assert (await c.get(f"/api/v1/agentes/{agente['id']}/conversaciones")).status_code == 404


class TestLaLista:

    @pytest.mark.asyncio
    async def test_lo_mas_reciente_primero_con_titulos_y_sin_quien_pregunto(self, http):
        c, quien = http
        agente = await _agente(c)
        await _conversacion(c, quien, agente["id"], pregunta="Primera pregunta")
        await _conversacion(
            c, quien, agente["id"], pregunta="Segunda pregunta", respuesta="Son 15.000 euros.",
            valoracion={"puntuacion": -1, "motivo": "desactualizado", "comentario": "Ya son 15.000"},
        )
        lista = (await c.get(f"/api/v1/agentes/{agente['id']}/conversaciones")).json()
        assert [x["pregunta"] for x in lista] == ["Segunda pregunta", "Primera pregunta"]
        segunda = lista[0]
        assert segunda["respuesta"] == "Son 15.000 euros."
        assert segunda["documentos"][0]["titulo"] == "Instrucción de contrato menor"
        assert segunda["puntuacion"] == -1
        assert segunda["motivo"] == "desactualizado"
        assert segunda["comentario"] == "Ya son 15.000"
        assert segunda["veredicto"] is None
        assert "actor" not in segunda

    @pytest.mark.asyncio
    async def test_la_pista_la_da_el_servidor_segun_el_motivo(self, http):
        c, quien = http
        agente = await _agente(c)
        for motivo in ("no_abre", "desactualizado", "inventa", "incompleta", "no_responde", "otro"):
            await _conversacion(c, quien, agente["id"], valoracion={"puntuacion": -1, "motivo": motivo})
        pistas = {x["motivo"]: x["pista"] for x in (await c.get(f"/api/v1/agentes/{agente['id']}/conversaciones")).json()}
        assert pistas == {
            "no_abre": "almacen",
            "desactualizado": "indice",
            "inventa": "prompt",
            "incompleta": "seleccion",
            "no_responde": "prompt",
            "otro": None,
        }

    @pytest.mark.asyncio
    async def test_los_filtros(self, http):
        c, quien = http
        agente = await _agente(c)
        buena = await _conversacion(c, quien, agente["id"], valoracion={"puntuacion": 1})
        mala = await _conversacion(c, quien, agente["id"], valoracion={"puntuacion": -1, "motivo": "inventa"})
        otra_mala = await _conversacion(c, quien, agente["id"], valoracion={"puntuacion": -1, "motivo": "incompleta"})
        sin_valorar = await _conversacion(c, quien, agente["id"])
        url = f"/api/v1/agentes/{agente['id']}/conversaciones"

        async def ids(**filtros):
            return {x["id"] for x in (await c.get(url, params=filtros)).json()}

        assert await ids(puntuacion=-1) == {mala, otra_mala}
        assert await ids(puntuacion=1) == {buena}
        assert await ids(motivo="inventa") == {mala}
        assert await ids(modo="validacion") == {buena, mala, otra_mala, sin_valorar}
        await c.put(f"/api/v1/agentes/consultas/{mala}/revision", json={"veredicto": "bad"})
        assert await ids(sin_revisar=True) == {buena, otra_mala, sin_valorar}


class TestLaRevision:

    @pytest.mark.asyncio
    async def test_veredicto_y_nota_como_en_los_chatbots(self, http):
        c, quien = http
        agente = await _agente(c)
        consulta = await _conversacion(c, quien, agente["id"], valoracion={"puntuacion": -1, "motivo": "inventa"})
        quien.actual = persona("admin")
        r = await c.put(f"/api/v1/agentes/consultas/{consulta}/revision", json={"veredicto": "bad", "nota": "Cita una norma derogada"})
        assert r.status_code == 200, r.text
        assert r.json()["veredicto"] == "bad"
        assert r.json()["nota_revision"] == "Cita una norma derogada"
        assert r.json()["revisada_en"] is not None

    @pytest.mark.asyncio
    async def test_solo_los_tres_veredictos(self, http):
        c, quien = http
        agente = await _agente(c)
        consulta = await _conversacion(c, quien, agente["id"])
        r = await c.put(f"/api/v1/agentes/consultas/{consulta}/revision", json={"veredicto": "regular"})
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_quien_solo_lo_usa_no_revisa(self, http):
        c, quien = http
        agente = await _agente(c)
        consulta = await _conversacion(c, quien, agente["id"])
        quien.actual = persona()
        assert (await c.put(f"/api/v1/agentes/consultas/{consulta}/revision", json={"veredicto": "good"})).status_code == 403

    @pytest.mark.asyncio
    async def test_ni_con_un_token(self, http):
        c, quien = http
        agente = await _agente(c)
        consulta = await _conversacion(c, quien, agente["id"])
        r = await c.put(f"/api/v1/agentes/consultas/{consulta}/revision", json={"veredicto": "good"}, headers=CONSULTA)
        assert r.status_code == 403


class TestLosContadores:

    @pytest.mark.asyncio
    async def test_la_ficha_cuenta_consultas_respuestas_leidas_e_informes_sin_revisar(self, http):
        c, quien = http
        agente = await _agente(c)
        await _conversacion(c, quien, agente["id"], respuesta="Respuesta")
        informe = await _conversacion(c, quien, agente["id"], valoracion={"puntuacion": -1, "motivo": "inventa"})
        await _conversacion(c, quien, agente["id"])

        def calidad():
            return c.get("/api/v1/agentes")

        [vista] = (await calidad()).json()["agentes"]
        assert vista["calidad"] == {"consultas": 3, "respuestas_leidas": 1, "informes_sin_revisar": 1}
        await c.put(f"/api/v1/agentes/consultas/{informe}/revision", json={"veredicto": "bad"})
        [vista] = (await calidad()).json()["agentes"]
        assert vista["calidad"]["informes_sin_revisar"] == 0

    @pytest.mark.asyncio
    async def test_quien_no_ve_la_calidad_no_ve_los_contadores(self, http):
        c, quien = http
        agente = await _agente(c)
        quien.actual = persona("user", orgs=(ORG,))
        # Una persona cualquiera de la organización ve el agente en la gestión si tiene el módulo,
        # pero no su calidad.
        vistas = (await c.get("/api/v1/agentes")).json()["agentes"]
        assert all(v["calidad"] is None for v in vistas if v["id"] == agente["id"])
