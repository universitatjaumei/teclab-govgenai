"""#176 — la extensión del navegador se conecta con la cuenta de la persona.

Decisión del usuario (2026-10-03): biblioteca y copiar, y **se inicia sesión desde la extensión**.
«Conectar» abre una página del panel; la persona, ya con su sesión, la confirma, y la plataforma
entrega a la extensión un token que **sólo sirve para consultar** (`agentes:consulta`).

Lo que fija esto:
- el token **sólo se entrega a una extensión reconocida**: la dirección de vuelta tiene que ser la
  de un identificador que el despliegue declara. Si no, cualquier página podría pedir un token
  haciéndose pasar por la extensión y llevárselo en la redirección;
- **lo pide una persona con su sesión**: un token no emite otro;
- **caduca**: vive en el navegador, y una conexión olvidada no debe durar para siempre;
- la persona **ve sus conexiones y las revoca**;
- el token abre el catálogo y la consulta, y **nada de lo que es de quien publica**.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from server.app.core.auth.models import UserInfo
from server.tests.modules.agentes._comun import declaracion, persona, publicar

ID = "abcdefghijklmnopabcdefghijklmnop"
DESTINO = f"https://{ID}.chromiumapp.org/"


@pytest.fixture(autouse=True)
def _extension_declarada(monkeypatch):
    monkeypatch.setenv("AGENTES_EXTENSION_IDS", f"otraextensionotraextensionotraex, {ID}")


class TestElTecho:

    @pytest.mark.asyncio
    async def test_cualquiera_con_la_consulta_puede_emitir_el_alcance_de_consulta(self, db_session):
        from server.app.core.auth.pat.service import PatService

        pat, _ = await PatService(db_session).create(
            owner=persona(), name="ext", scopes=["agentes:consulta"], modulos=["consulta_agentes"]
        )
        assert list(pat.scopes) == ["agentes:consulta"]

    @pytest.mark.asyncio
    async def test_el_modulo_de_consulta_no_abre_el_indice(self, db_session):
        from server.app.core.auth.pat.service import PatForbiddenError, PatService

        with pytest.raises(PatForbiddenError):
            await PatService(db_session).create(
                owner=persona(), name="ext", scopes=["agentes:indice"], modulos=["consulta_agentes"]
            )


class TestConectar:

    @pytest.mark.asyncio
    async def test_entrega_un_token_de_consulta_que_caduca(self, http, db_session):
        from sqlalchemy import select

        from server.app.modules.agents_hub.database.config_models import HubPersonalAccessToken

        c, _ = http
        r = await c.post("/api/v1/agentes/extension/conectar", json={"destino": DESTINO})
        assert r.status_code == 201, r.text
        assert r.json()["token"].startswith("pat_")

        pat = (await db_session.execute(select(HubPersonalAccessToken))).scalar_one()
        assert list(pat.scopes) == ["agentes:consulta"]
        assert pat.expires_at is not None
        caduca = pat.expires_at if pat.expires_at.tzinfo else pat.expires_at.replace(tzinfo=timezone.utc)
        assert timedelta(days=1) < caduca - datetime.now(timezone.utc) <= timedelta(days=90)

    @pytest.mark.parametrize(
        "destino",
        [
            "https://desconocidadesconocidadesconoci.chromiumapp.org/",
            "https://evil.example/",
            f"https://{ID}.chromiumapp.org.evil.example/",
            f"http://{ID}.chromiumapp.org/",
            "",
        ],
    )
    @pytest.mark.asyncio
    async def test_no_entrega_nada_a_un_destino_que_no_es_una_extension_declarada(self, http, destino):
        c, _ = http
        r = await c.post("/api/v1/agentes/extension/conectar", json={"destino": destino})
        assert r.status_code == 400, r.text
        assert "token" not in r.text

    @pytest.mark.asyncio
    async def test_sin_ninguna_extension_declarada_no_se_conecta_ninguna(self, http, monkeypatch):
        monkeypatch.delenv("AGENTES_EXTENSION_IDS")
        c, _ = http
        r = await c.post("/api/v1/agentes/extension/conectar", json={"destino": DESTINO})
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_un_token_no_emite_otro(self, http):
        c, _ = http
        r = await c.post(
            "/api/v1/agentes/extension/conectar",
            json={"destino": DESTINO},
            headers={"X-Prueba-Scopes": "agentes:consulta"},
        )
        assert r.status_code == 403


class TestLasConexiones:

    @pytest.mark.asyncio
    async def test_lista_las_suyas_sin_el_texto_y_las_revoca(self, http):
        c, quien = http
        ajena = (await c.post("/api/v1/agentes/extension/conectar", json={"destino": DESTINO})).json()
        quien.actual = persona()
        await c.post("/api/v1/agentes/extension/conectar", json={"destino": DESTINO})
        # Un token del guion de la misma persona no es una conexión de la extensión.
        await c.post("/api/v1/agentes/tokens", json={"nombre": "guion"})

        listado = (await c.get("/api/v1/agentes/extension/conexiones")).json()
        assert len(listado) == 1
        assert "token" not in listado[0]
        assert listado[0]["caduca_en"] is not None

        # La de otra persona no existe para quien pregunta.
        assert (await c.delete(f"/api/v1/agentes/extension/conexiones/{ajena['id']}")).status_code == 404
        r = await c.delete(f"/api/v1/agentes/extension/conexiones/{listado[0]['id']}")
        assert r.status_code == 204
        assert (await c.get("/api/v1/agentes/extension/conexiones")).json() == []

    @pytest.mark.asyncio
    async def test_una_conexion_caducada_no_se_lista(self, http, db_session):
        from sqlalchemy import update

        from server.app.modules.agents_hub.database.config_models import HubPersonalAccessToken

        c, _ = http
        await c.post("/api/v1/agentes/extension/conectar", json={"destino": DESTINO})
        await db_session.execute(
            update(HubPersonalAccessToken).values(expires_at=datetime.now(timezone.utc) - timedelta(days=1))
        )
        await db_session.commit()
        assert (await c.get("/api/v1/agentes/extension/conexiones")).json() == []


@pytest.mark.asyncio
async def test_el_token_de_la_extension_consulta_y_no_publica_por_el_camino_de_verdad(db_session):
    """Con el token en la cabecera y la autenticación real, no con un principal inyectado."""
    from server.app.api.deps import get_current_user, get_session, modulos_concedidos
    from server.app.modules.agents_hub.database.config_models import HubOrganizacion, HubUser
    from server.app.routers.agentes_router import obtener_embedder, router, router_catalogo
    from server.tests.modules.agentes.test_agu2_indice import EmbebedorFalso

    org = HubOrganizacion(id=uuid.uuid4(), name="Org de prueba", partner_id="prueba")
    db_session.add(org)
    await db_session.flush()
    dueno = HubUser(id=uuid.uuid4(), email="persona@uji.es", role="user", organizacion_id=org.id, origen="manual")
    db_session.add(dueno)
    await db_session.commit()
    principal = UserInfo(
        user_id=str(dueno.id), email=dueno.email, role="user", organizacion_ids=(str(org.id),)
    )

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.include_router(router_catalogo, prefix="/api/v1")

    async def _sesion():
        yield db_session

    app.dependency_overrides[get_session] = _sesion
    app.dependency_overrides[obtener_embedder] = lambda: EmbebedorFalso()
    # Los módulos no son lo que se prueba: la persona tiene los dos.
    app.dependency_overrides[modulos_concedidos] = lambda: ["agentes", "consulta_agentes"]
    app.dependency_overrides[get_current_user] = lambda: principal
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://prueba") as c:
        agente = await publicar(c)
        token = (await c.post("/api/v1/agentes/extension/conectar", json={"destino": DESTINO})).json()["token"]

    del app.dependency_overrides[get_current_user]
    cabecera = {"Authorization": f"Bearer {token}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://prueba") as c:
        r = await c.get("/api/v1/agentes/catalogo", headers=cabecera)
        assert r.status_code == 200, r.text
        assert [a["id"] for a in r.json()] == [agente["id"]]
        r = await c.post(
            f"/api/v1/agentes/{agente['id']}/consulta", json={"consulta": "¿Contrato menor?"}, headers=cabecera
        )
        assert r.status_code == 200, r.text

        assert (await c.post("/api/v1/agentes", json=declaracion(), headers=cabecera)).status_code == 403
        assert (
            await c.post("/api/v1/agentes/extension/conectar", json={"destino": DESTINO}, headers=cabecera)
        ).status_code == 403
        assert (await c.get("/api/v1/agentes/extension/conexiones", headers=cabecera)).status_code == 403


@pytest.mark.asyncio
async def test_el_catalogo_no_se_abre_a_un_token_de_otro_alcance(http):
    c, _ = http
    r = await c.get("/api/v1/agentes/catalogo", headers={"X-Prueba-Scopes": "agentes:indice"})
    assert r.status_code == 403
