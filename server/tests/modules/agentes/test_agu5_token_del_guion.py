"""#174 — el token del guion: lo emite quien publica, sólo sirve para cargar el índice.

Decisión del usuario (2026-10-03): la unidad es autónoma. Quien tiene el módulo `agentes` puede
emitir un token con **un solo alcance**, `agentes:indice`, sin pasar por un administrador. El
token abre la puerta y nada más: qué agente puede cargar lo sigue decidiendo `cargar_indice`.

Y un token se pega en las propiedades del guion, que ve cualquiera que pueda editarlo: tiene que
poder **revocarse** desde la misma pantalla.

El último test va por el camino de verdad, con el token en la cabecera: es lo que los demás tests
no ven al sobrescribir la autenticación, y por donde se coló el defecto de VAS.2.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from server.app.core.auth.models import UserInfo
from server.tests.modules.agentes._comun import FICHAS, declaracion, persona, publicar


def _usuario(role="user") -> UserInfo:
    return UserInfo(user_id=str(uuid.uuid4()), email="u@uji.es", role=role, organizacion_ids=())


class TestElTecho:

    @pytest.mark.asyncio
    async def test_quien_publica_puede_emitir_el_token_del_indice(self, db_session):
        from server.app.core.auth.pat.service import PatService

        pat, token = await PatService(db_session).create(
            owner=_usuario(), name="guion", scopes=["agentes:indice"], modulos=["agentes"]
        )
        assert token.startswith("pat_")
        assert list(pat.scopes) == ["agentes:indice"]

    @pytest.mark.asyncio
    async def test_sin_el_modulo_no(self, db_session):
        from server.app.core.auth.pat.service import PatForbiddenError, PatService

        with pytest.raises(PatForbiddenError):
            await PatService(db_session).create(
                owner=_usuario(), name="guion", scopes=["agentes:indice"], modulos=["informes"]
            )

    @pytest.mark.asyncio
    async def test_el_modulo_no_abre_otros_alcances(self, db_session):
        from server.app.core.auth.pat.service import PatForbiddenError, PatService

        with pytest.raises(PatForbiddenError):
            await PatService(db_session).create(
                owner=_usuario(),
                name="guion",
                scopes=["agentes:indice", "actividad:write"],
                modulos=["agentes"],
            )

    @pytest.mark.asyncio
    async def test_el_admin_sigue_como_estaba(self, db_session):
        from server.app.core.auth.pat.service import PatService

        _, token = await PatService(db_session).create(
            owner=_usuario("admin"), name="registro", scopes=["actividad:write"]
        )
        assert token.startswith("pat_")


class TestLaPantallaDelToken:

    @pytest.mark.asyncio
    async def test_se_emite_con_un_solo_alcance_y_el_texto_se_ve_una_vez(self, http):
        c, _ = http
        r = await c.post("/api/v1/agentes/tokens", json={"nombre": "Guion de Contratación"})
        assert r.status_code == 201, r.text
        cuerpo = r.json()
        assert cuerpo["token"].startswith("pat_")
        assert cuerpo["nombre"] == "Guion de Contratación"

        listado = (await c.get("/api/v1/agentes/tokens")).json()
        assert [t["id"] for t in listado] == [cuerpo["id"]]
        assert "token" not in listado[0]

    @pytest.mark.asyncio
    async def test_solo_lista_los_suyos_y_solo_los_del_indice(self, http, db_session):
        from server.app.core.auth.pat.service import PatService

        c, quien = http
        # Un token del mismo dueño con más alcances que el del índice: no es «del guion».
        mismo_dueno_admin = UserInfo(
            user_id=quien.actual.user_id, email="u@uji.es", role="admin", organizacion_ids=()
        )
        await PatService(db_session).create(
            owner=mismo_dueno_admin, name="otro alcance", scopes=["agentes:indice", "actividad:write"]
        )
        await c.post("/api/v1/agentes/tokens", json={"nombre": "mío"})
        quien.actual = persona()
        await c.post("/api/v1/agentes/tokens", json={"nombre": "de otra persona"})
        assert [t["nombre"] for t in (await c.get("/api/v1/agentes/tokens")).json()] == ["de otra persona"]

    @pytest.mark.asyncio
    async def test_se_revoca_y_deja_de_listarse(self, http):
        c, _ = http
        token = (await c.post("/api/v1/agentes/tokens", json={"nombre": "guion"})).json()
        r = await c.delete(f"/api/v1/agentes/tokens/{token['id']}")
        assert r.status_code == 204
        assert (await c.get("/api/v1/agentes/tokens")).json() == []

    @pytest.mark.asyncio
    async def test_el_de_otra_persona_no_se_revoca(self, http):
        c, quien = http
        ajeno = (await c.post("/api/v1/agentes/tokens", json={"nombre": "ajeno"})).json()
        quien.actual = persona()
        assert (await c.delete(f"/api/v1/agentes/tokens/{ajeno['id']}")).status_code == 404


@pytest.mark.asyncio
async def test_el_token_emitido_carga_el_indice_por_el_camino_de_verdad(db_session):
    """Con el token en la cabecera y la autenticación real, no con un principal inyectado."""
    from server.app.api.deps import get_session
    from server.app.core.auth.pat.service import PatService
    from server.app.modules.agents_hub.database.config_models import HubOrganizacion, HubUser
    from server.app.routers.agentes_router import obtener_embedder, router
    from server.tests.modules.agentes.test_agu2_indice import EmbebedorFalso

    org = HubOrganizacion(id=uuid.uuid4(), name="Org de prueba", partner_id="prueba")
    db_session.add(org)
    await db_session.flush()
    dueno = HubUser(id=uuid.uuid4(), email="unidad@uji.es", role="user", organizacion_id=org.id, origen="manual")
    db_session.add(dueno)
    await db_session.commit()
    principal = UserInfo(
        user_id=str(dueno.id), email=dueno.email, role="user", organizacion_ids=(str(org.id),)
    )

    # Publica con su sesión (inyectada) y emite el token...
    from server.app.api.deps import get_current_user

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    async def _sesion():
        yield db_session

    app.dependency_overrides[get_session] = _sesion
    app.dependency_overrides[obtener_embedder] = lambda: EmbebedorFalso()
    app.dependency_overrides[get_current_user] = lambda: principal
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://prueba") as c:
        agente = await publicar(c)
    _, token = await PatService(db_session).create(
        owner=principal, name="guion", scopes=["agentes:indice"], modulos=["agentes"]
    )

    # ...y el guion carga con el token, sin nada inyectado en la autenticación.
    del app.dependency_overrides[get_current_user]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://prueba") as c:
        r = await c.put(
            f"/api/v1/agentes/{agente['id']}/indice",
            json={"fichas": FICHAS, "documentos_en_carpeta": 2},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200, r.text
        r = await c.get(
            "/api/v1/agentes/prompt-de-resumen", headers={"Authorization": f"Bearer {token}"}
        )
        assert r.status_code == 200, r.text
        # El mismo token no sirve para otra cosa: ni publicar, ni retirar, ni emitir más tokens.
        # Vive en las propiedades del guion, que ve cualquiera que pueda editarlo.
        cabecera = {"Authorization": f"Bearer {token}"}
        assert (await c.post("/api/v1/agentes", json=declaracion(), headers=cabecera)).status_code == 403
        assert (await c.post(f"/api/v1/agentes/{agente['id']}/retirar", headers=cabecera)).status_code == 403
        assert (
            await c.post("/api/v1/agentes/tokens", json={"nombre": "otro"}, headers=cabecera)
        ).status_code == 403


class TestElGuionLoSirveLaPlataforma:
    """Uno, versionado y con su huella: las unidades lo instancian, no escriben el suyo (#174)."""

    @pytest.mark.asyncio
    async def test_da_el_codigo_el_manifiesto_la_version_y_la_huella(self, http):
        import hashlib
        import json
        from pathlib import Path

        c, _ = http
        r = await c.get("/api/v1/agentes/guion")
        assert r.status_code == 200, r.text
        cuerpo = r.json()
        fuente = (
            Path(__file__).resolve().parents[3]
            / "app" / "modules" / "agentes" / "guion" / "indice_desde_drive.gs"
        )
        assert cuerpo["codigo"] == fuente.read_text(encoding="utf-8")
        assert cuerpo["sha256"] == hashlib.sha256(fuente.read_bytes()).hexdigest()
        assert cuerpo["version"] == "indice-v2"
        manifiesto = json.loads(cuerpo["manifiesto"])
        assert "https://www.googleapis.com/auth/drive.readonly" in manifiesto["oauthScopes"]

    @pytest.mark.asyncio
    async def test_no_pide_mas_permisos_de_drive_que_leer(self, http):
        """El guion lee la carpeta; si pidiera escribir en todo Drive, nadie debería instalarlo."""
        import json

        c, _ = http
        manifiesto = json.loads((await c.get("/api/v1/agentes/guion")).json()["manifiesto"])
        assert "https://www.googleapis.com/auth/drive" not in manifiesto["oauthScopes"]
