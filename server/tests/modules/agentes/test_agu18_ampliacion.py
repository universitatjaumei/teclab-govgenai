"""#225 — «Buscar más documentos» en la misma conversación, con su propio texto.

Decisión del usuario (2026-10-05): va antes de las primeras pruebas del piloto, porque con este
botón los primeros documentos sólo tienen que ser un buen punto de partida.

Lo que fija:
- la ampliación busca **con su texto y sus datos**, no con la pregunta original;
- **no repite** lo ya ofrecido en la consulta ni en sus ampliaciones anteriores;
- se aplica la misma selección —filtro, prioritarias, reservas por capa— sobre lo que queda;
- lo que se pega es corto: el texto y los enlaces nuevos, sin el prompt del agente;
- es una consulta más, ligada a la primera, y **sólo la amplía quien la hizo**;
- deja su fila en el registro de actividad, como cualquier uso.
"""
from __future__ import annotations

import pytest
from sqlalchemy import func, select

from server.tests.modules.agentes._comun import persona, publicar

CONSULTA = {"X-Prueba-Scopes": "agentes:consulta"}


def _ficha(nombre: str, texto: str, **metadatos) -> dict:
    return {
        "url": f"https://drive.google.com/file/d/{nombre}",
        "titulo": nombre,
        "resumen": texto,
        "metadatos": metadatos,
    }


#: Parecidas a «contrato», cada vez menos.
CONTRATOS = [_ficha(f"c{n}", "contrato " + "matricula " * n) for n in range(1, 7)]
#: Parecidas a «viaje».
VIAJES = [_ficha(f"v{n}", "viaje " + "matricula " * n) for n in range(1, 4)]


async def _agente(c, fichas, **declaracion) -> dict:
    agente = await publicar(c, **{"presupuesto_documentos": 2, **declaracion})
    r = await c.put(f"/api/v1/agentes/{agente['id']}/indice", json={"fichas": fichas})
    assert r.status_code == 200, r.text
    return agente


async def _consultar(c, agente_id, consulta="contrato", **cuerpo) -> dict:
    r = await c.post(
        f"/api/v1/agentes/{agente_id}/consulta", json={"consulta": consulta, **cuerpo}, headers=CONSULTA
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _ampliar(c, consulta_id, texto="contrato", esperado=200, **cuerpo):
    r = await c.post(
        f"/api/v1/agentes/consultas/{consulta_id}/ampliacion",
        json={"texto": texto, **cuerpo},
        headers=CONSULTA,
    )
    assert r.status_code == esperado, r.text
    return r.json()


def _nombres(respuesta) -> list[str]:
    return [d["url"].rsplit("/", 1)[-1] for d in respuesta["documentos"]]


class TestLosDocumentos:

    @pytest.mark.asyncio
    async def test_no_repite_lo_ya_ofrecido(self, http):
        c, _ = http
        agente = await _agente(c, CONTRATOS)
        madre = await _consultar(c, agente["id"])
        assert _nombres(madre) == ["c1", "c2"]
        assert _nombres(await _ampliar(c, madre["consulta_id"])) == ["c3", "c4"]

    @pytest.mark.asyncio
    async def test_ni_lo_de_las_ampliaciones_anteriores(self, http):
        c, _ = http
        agente = await _agente(c, CONTRATOS)
        madre = await _consultar(c, agente["id"])
        primera = await _ampliar(c, madre["consulta_id"])
        # Da igual desde cuál se amplíe: la conversación es la misma.
        assert _nombres(await _ampliar(c, primera["consulta_id"])) == ["c5", "c6"]

    @pytest.mark.asyncio
    async def test_busca_con_su_texto_y_no_con_la_pregunta(self, http):
        c, _ = http
        agente = await _agente(c, CONTRATOS + VIAJES)
        madre = await _consultar(c, agente["id"], "contrato")
        assert _nombres(await _ampliar(c, madre["consulta_id"], "viaje")) == ["v1", "v2"]

    @pytest.mark.asyncio
    async def test_aplica_las_reservas_por_capa(self, http):
        c, _ = http
        ley = [_ficha(f"l{n}", "ley " + "matricula " * n, capa="LCSP") for n in range(1, 4)]
        agente = await _agente(c, CONTRATOS + ley, reservas=[{"capa": "LCSP", "plazas": 1}])
        madre = await _consultar(c, agente["id"])
        assert sorted(_nombres(madre)) == ["c1", "l1"]
        assert sorted(_nombres(await _ampliar(c, madre["consulta_id"]))) == ["c2", "l2"]

    @pytest.mark.asyncio
    async def test_con_sus_datos_filtra(self, http):
        c, _ = http
        tipo = {
            "etiqueta": "Tipo de contrato",
            "tipo": "opciones",
            "opciones": ["Servicios", "Suministros"],
            "columna": "Tipo de contrato",
        }
        fichas = [
            _ficha("s1", "contrato", **{"Tipo de contrato": "Servicios"}),
            _ficha("u1", "contrato matricula", **{"Tipo de contrato": "Suministros"}),
            _ficha("u2", "contrato matricula matricula", **{"Tipo de contrato": "Suministros"}),
        ]
        agente = await _agente(c, fichas, datos_consulta=[tipo], presupuesto_documentos=1)
        madre = await _consultar(c, agente["id"], datos={"tipo_de_contrato": "Suministros"})
        assert _nombres(madre) == ["u1"]
        ampliada = await _ampliar(c, madre["consulta_id"], datos={"tipo_de_contrato": "Servicios"})
        assert _nombres(ampliada) == ["s1"]

    @pytest.mark.asyncio
    async def test_un_dato_que_no_vale_es_422(self, http):
        c, _ = http
        tipo = {"etiqueta": "Tipo de contrato", "tipo": "opciones", "opciones": ["Servicios", "Suministros"], "obligatorio": True}
        agente = await _agente(c, CONTRATOS, datos_consulta=[tipo])
        madre = await _consultar(c, agente["id"], datos={"tipo_de_contrato": "Servicios"})
        await _ampliar(c, madre["consulta_id"], datos={"tipo_de_contrato": "Obras"}, esperado=422)

    @pytest.mark.asyncio
    async def test_cuando_no_queda_nada_lo_dice(self, http):
        c, _ = http
        agente = await _agente(c, CONTRATOS[:2])
        madre = await _consultar(c, agente["id"])
        ampliada = await _ampliar(c, madre["consulta_id"])
        assert ampliada["documentos"] == []


class TestLoQueSePega:

    @pytest.mark.asyncio
    async def test_el_texto_y_los_enlaces_sin_el_prompt_del_agente(self, http):
        c, _ = http
        agente = await _agente(c, CONTRATOS)
        madre = await _consultar(c, agente["id"])
        prompt = (await _ampliar(c, madre["consulta_id"], "la justificación del contrato"))["prompt"]
        assert "la justificación del contrato" in prompt
        assert "https://drive.google.com/file/d/c3" in prompt
        assert "Eres el asistente de contratación." not in prompt
        assert "https://drive.google.com/file/d/c1" not in prompt

    @pytest.mark.asyncio
    async def test_en_la_lengua_de_quien_pregunta(self, http):
        c, _ = http
        agente = await _agente(c, CONTRATOS)
        madre = await _consultar(c, agente["id"])
        prompt = (await _ampliar(c, madre["consulta_id"], lengua="ca"))["prompt"]
        assert "Documents addicionals" in prompt


class TestElRegistro:

    @pytest.mark.asyncio
    async def test_sólo_la_amplía_quien_la_hizo(self, http):
        c, quien = http
        agente = await _agente(c, CONTRATOS)
        madre = await _consultar(c, agente["id"])
        quien.actual = persona()
        await _ampliar(c, madre["consulta_id"], esperado=404)

    @pytest.mark.asyncio
    async def test_queda_ligada_a_la_primera_consulta(self, http, db_session):
        from server.app.modules.agents_hub.database.operational_models import HubAgenteConsulta

        c, _ = http
        agente = await _agente(c, CONTRATOS)
        madre = await _consultar(c, agente["id"])
        primera = await _ampliar(c, madre["consulta_id"], "precisa el objeto")
        segunda = await _ampliar(c, primera["consulta_id"])
        db_session.expire_all()
        filas = {
            str(f.id): f
            for f in (await db_session.execute(select(HubAgenteConsulta))).scalars()
        }
        assert filas[madre["consulta_id"]].consulta_madre_id is None
        assert str(filas[primera["consulta_id"]].consulta_madre_id) == madre["consulta_id"]
        assert str(filas[segunda["consulta_id"]].consulta_madre_id) == madre["consulta_id"]
        # En validación se guarda lo que se pidió, como la pregunta de la consulta.
        assert filas[primera["consulta_id"]].pregunta == "precisa el objeto"
        assert filas[primera["consulta_id"]].modo == "validacion"

    @pytest.mark.asyncio
    async def test_deja_su_fila_en_el_registro_de_actividad(self, http, db_session):
        from server.app.modules.agents_hub.database.operational_models import HubActividadIA

        c, _ = http
        agente = await _agente(c, CONTRATOS)
        madre = await _consultar(c, agente["id"])
        await _ampliar(c, madre["consulta_id"])
        assert (await db_session.execute(select(func.count()).select_from(HubActividadIA))).scalar() == 2

    @pytest.mark.asyncio
    async def test_la_respuesta_se_guarda_en_la_ampliacion(self, http):
        c, _ = http
        agente = await _agente(c, CONTRATOS)
        madre = await _consultar(c, agente["id"])
        ampliada = await _ampliar(c, madre["consulta_id"])
        r = await c.post(
            f"/api/v1/agentes/consultas/{ampliada['consulta_id']}/respuesta",
            json={"texto": "Con los nuevos documentos…", "fuentes": []},
            headers=CONSULTA,
        )
        assert r.status_code == 204, r.text

    @pytest.mark.asyncio
    async def test_con_la_sesion_de_los_routers_que_expira_al_commitear(self, http, db_url):
        """La verificación en vivo dio 500: la respuesta se construía tras el commit, y la sesión de
        los routers (`api/deps.get_session`) expira los objetos al commitear. `db_session` no."""
        from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

        from server.app.api.deps import get_session

        c, _ = http
        agente = await _agente(c, CONTRATOS)
        madre = await _consultar(c, agente["id"])
        engine = create_async_engine(db_url)

        async def _como_la_de_los_routers():
            async with AsyncSession(engine) as sesion:
                yield sesion

        c._transport.app.dependency_overrides[get_session] = _como_la_de_los_routers
        try:
            assert _nombres(await _ampliar(c, madre["consulta_id"])) == ["c3", "c4"]
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_las_conversaciones_la_muestran_con_su_madre(self, http):
        c, quien = http
        agente = await _agente(c, CONTRATOS)
        quien.actual = persona()
        madre = await _consultar(c, agente["id"])
        ampliada = await _ampliar(c, madre["consulta_id"])
        from server.tests.modules.agentes._comun import AUTORA

        quien.actual = AUTORA
        r = await c.get(f"/api/v1/agentes/{agente['id']}/conversaciones")
        assert r.status_code == 200, r.text
        por_id = {f["id"]: f for f in r.json()}
        assert por_id[ampliada["consulta_id"]]["consulta_madre_id"] == madre["consulta_id"]
        assert por_id[madre["consulta_id"]]["consulta_madre_id"] is None
