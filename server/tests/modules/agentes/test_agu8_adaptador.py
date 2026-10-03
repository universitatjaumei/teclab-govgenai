"""#215 — el adaptador del asistente: los selectores son datos que sirve la plataforma.

Gemini cambia su página sin avisar. Si los selectores estuvieran en el código de la extensión,
cada cambio exigiría publicar una versión nueva y esperar a que llegara a todos los navegadores.
Como datos, **se corrige una fila y todas las extensiones se recuperan**.

Lo que fija:
- la extensión lo lee con su token de consulta; un token de otro alcance, no;
- **sólo el superadministrador lo cambia**, con su sesión, y cada cambio es una versión nueva;
- un cambio sin alguno de los selectores que la extensión usa no se guarda;
- la extensión **avisa de qué selector falló**, y la plataforma cuenta los fallos de la versión
  vigente: los de una versión ya corregida no la marcan como rota.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.tests.modules.agentes._comun import persona

CONSULTA = {"X-Prueba-Scopes": "agentes:consulta"}
RUTA = "/api/v1/agentes/asistentes/gemini"


#: El adaptador con el que se distribuye la extensión; la migración siembra una copia literal.
GEMINI = json.loads((Path(__file__).resolve().parents[4] / "extension" / "adaptadores" / "gemini.json").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
async def _gemini_sembrado(db_session):
    from server.app.modules.agents_hub.database.operational_models import HubAsistenteAdaptador

    db_session.add(
        HubAsistenteAdaptador(
            asistente=GEMINI["asistente"],
            nombre=GEMINI["nombre"],
            origen=GEMINI["origen"],
            selectores=GEMINI["selectores"],
        )
    )
    await db_session.commit()


def test_el_adaptador_que_se_distribuye_tiene_los_selectores_que_se_exigen():
    from server.app.routers.agentes_router import SELECTORES_DEL_ADAPTADOR

    assert set(GEMINI["selectores"]) == set(SELECTORES_DEL_ADAPTADOR)


class TestLaExtensionLoLee:

    @pytest.mark.asyncio
    async def test_con_el_token_de_consulta(self, http):
        c, _ = http
        r = await c.get(f"{RUTA}/adaptador", headers=CONSULTA)
        assert r.status_code == 200, r.text
        cuerpo = r.json()
        assert cuerpo["asistente"] == "gemini"
        assert cuerpo["origen"] == "https://gemini.google.com"
        assert cuerpo["version"] == 1
        assert set(cuerpo["selectores"]) == {"cuadro", "respuesta", "texto", "ocupado", "fuentes"}

    @pytest.mark.asyncio
    async def test_con_un_token_de_otro_alcance_no(self, http):
        c, _ = http
        r = await c.get(f"{RUTA}/adaptador", headers={"X-Prueba-Scopes": "agentes:indice"})
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_un_asistente_que_no_existe(self, http):
        c, _ = http
        r = await c.get("/api/v1/agentes/asistentes/otro/adaptador", headers=CONSULTA)
        assert r.status_code == 404


class TestSoloElSuperadministradorLoCambia:

    @pytest.mark.asyncio
    async def test_cada_cambio_es_una_version_y_pone_los_fallos_a_cero(self, http):
        c, quien = http
        await c.post(f"{RUTA}/fallos", json={"version": 1, "selector": "cuadro"}, headers=CONSULTA)
        quien.actual = persona("superadmin", orgs=())
        selectores = (await c.get(f"{RUTA}/adaptador")).json()["selectores"]
        selectores["cuadro"] = "div[role='textbox']"
        r = await c.put(f"{RUTA}/adaptador", json={"selectores": selectores})
        assert r.status_code == 200, r.text
        assert r.json()["version"] == 2
        assert r.json()["fallos_de_la_version"] == 0
        assert (await c.get(f"{RUTA}/adaptador", headers=CONSULTA)).json()["selectores"]["cuadro"] == (
            "div[role='textbox']"
        )

    @pytest.mark.parametrize("role", ["admin", "user"])
    @pytest.mark.asyncio
    async def test_nadie_mas(self, http, role):
        c, quien = http
        quien.actual = persona(role)
        selectores = (await c.get(f"{RUTA}/adaptador", headers=CONSULTA)).json()["selectores"]
        assert (await c.put(f"{RUTA}/adaptador", json={"selectores": selectores})).status_code == 403

    @pytest.mark.asyncio
    async def test_ni_con_un_token(self, http):
        c, quien = http
        quien.actual = persona("superadmin", orgs=())
        selectores = (await c.get(f"{RUTA}/adaptador")).json()["selectores"]
        r = await c.put(f"{RUTA}/adaptador", json={"selectores": selectores}, headers=CONSULTA)
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_sin_un_selector_que_la_extension_usa_no_se_guarda(self, http):
        c, quien = http
        quien.actual = persona("superadmin", orgs=())
        selectores = (await c.get(f"{RUTA}/adaptador")).json()["selectores"]
        del selectores["texto"]
        assert (await c.put(f"{RUTA}/adaptador", json={"selectores": selectores})).status_code == 422
        selectores["texto"] = "   "
        assert (await c.put(f"{RUTA}/adaptador", json={"selectores": selectores})).status_code == 422


class TestLosFallos:

    @pytest.mark.asyncio
    async def test_la_extension_avisa_y_el_superadministrador_lo_ve(self, http):
        c, quien = http
        r = await c.post(f"{RUTA}/fallos", json={"version": 1, "selector": "texto"}, headers=CONSULTA)
        assert r.status_code == 204, r.text
        await c.post(f"{RUTA}/fallos", json={"version": 1, "selector": "insercion"}, headers=CONSULTA)

        quien.actual = persona("superadmin", orgs=())
        [gemini] = (await c.get("/api/v1/agentes/asistentes")).json()
        assert gemini["fallos_de_la_version"] == 2
        assert gemini["ultimo_fallo_selector"] == "insercion"
        assert gemini["rota"] is True

    @pytest.mark.asyncio
    async def test_un_fallo_de_una_version_ya_corregida_no_la_marca_como_rota(self, http):
        c, quien = http
        quien.actual = persona("superadmin", orgs=())
        selectores = (await c.get(f"{RUTA}/adaptador")).json()["selectores"]
        await c.put(f"{RUTA}/adaptador", json={"selectores": selectores})
        # Una extensión que aún tenía la versión 1 en memoria avisa tarde.
        await c.post(f"{RUTA}/fallos", json={"version": 1, "selector": "cuadro"}, headers=CONSULTA)
        [gemini] = (await c.get("/api/v1/agentes/asistentes")).json()
        assert gemini["version"] == 2
        assert gemini["rota"] is False

    @pytest.mark.asyncio
    async def test_solo_se_avisa_de_selectores_que_existen(self, http):
        c, _ = http
        r = await c.post(f"{RUTA}/fallos", json={"version": 1, "selector": "<script>"}, headers=CONSULTA)
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_el_estado_no_lo_ve_cualquiera(self, http):
        c, quien = http
        quien.actual = persona("admin")
        assert (await c.get("/api/v1/agentes/asistentes")).status_code == 403
