"""#230 (defecto encontrado verificando) — un token se puede emitir para una sola organización.

**Cómo salió.** Probando en vivo el hook de Claude Code, el registro respondió
`ORGANIZACION_INDETERMINADA`: `POST /api/v1/actividad` necesita que el token pertenezca a una
organización, y el token lo había emitido un superadministrador, que las ve todas. La columna
`hub_personal_access_tokens.organizacion_id` existe desde MT.5 y el principal ya la respeta
(`acota_a_la_organizacion`), pero **nada la rellenaba**: `PatCreateRequest` no tenía el campo y
Pydantic descartaba en silencio el que se mandara.

Lo que fija este fichero, por HTTP:
- el token se emite con `organizacion_id` y lo devuelve, también en el listado;
- **acota, nunca amplía**: quien no es superadmin sólo puede declarar una organización suya;
- una organización que no existe es un 422 claro, no un 500 de clave foránea.
"""
from __future__ import annotations

import uuid

import httpx
import pytest
from fastapi import FastAPI


def _app(db):
    from server.app.api.deps import get_session
    from server.app.routers.pat_router import router
    from sqlmodel.ext.asyncio.session import AsyncSession

    async def _override_session():
        async with AsyncSession(db.engine) as s:
            yield s

    app = FastAPI()
    app.dependency_overrides[get_session] = _override_session
    app.include_router(router, prefix="/api/v1")
    return app


def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")


def _headers(role: str, orgs: tuple[str, ...] = ()):
    from server.app.core.auth import create_token
    from server.app.core.auth.models import UserInfo

    usuario = UserInfo(
        user_id=f"{role}-{uuid.uuid4().hex[:8]}",
        email=f"{role}.{uuid.uuid4().hex[:6]}@uji.es",
        role=role,
        organizacion_ids=orgs,
    )
    return {"Authorization": f"Bearer {create_token(usuario)}"}


async def _organizacion(db) -> str:
    from server.app.modules.agents_hub.database.config_models import HubOrganizacion

    ident = uuid.uuid4()
    org = HubOrganizacion(id=ident, name=f"Org {uuid.uuid4().hex[:6]}", partner_id="uji")
    db.session.add(org)
    await db.session.commit()
    return str(ident)


@pytest.mark.asyncio
async def test_un_superadmin_emite_un_token_para_una_organizacion(db):
    org = await _organizacion(db)
    cabeceras = _headers("superadmin")
    async with _client(_app(db)) as client:
        creado = await client.post(
            "/api/v1/auth/pats",
            json={"name": "hook", "scopes": ["actividad:write"], "organizacion_id": org},
            headers=cabeceras,
        )
        assert creado.status_code == 201, creado.text
        assert creado.json()["organizacion_id"] == org

        listado = await client.get("/api/v1/auth/pats", headers=cabeceras)
    fila = next(p for p in listado.json() if p["id"] == creado.json()["id"])
    assert fila["organizacion_id"] == org


@pytest.mark.asyncio
async def test_y_el_token_queda_acotado_a_ella(db):
    from server.app.core.auth.pat.service import PatService
    from sqlmodel.ext.asyncio.session import AsyncSession

    org = await _organizacion(db)
    async with _client(_app(db)) as client:
        creado = await client.post(
            "/api/v1/auth/pats",
            json={"name": "hook", "scopes": ["actividad:write"], "organizacion_id": org},
            headers=_headers("superadmin"),
        )
    async with AsyncSession(db.engine) as s:
        principal = await PatService(s).verify(creado.json()["token"])
    assert tuple(principal.user_info.organizacion_ids) == (org,)


@pytest.mark.asyncio
async def test_un_admin_no_declara_una_organizacion_ajena(db):
    suya, ajena = await _organizacion(db), await _organizacion(db)
    async with _client(_app(db)) as client:
        resp = await client.post(
            "/api/v1/auth/pats",
            json={"name": "hook", "scopes": ["actividad:write"], "organizacion_id": ajena},
            headers=_headers("admin", (suya,)),
        )
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["code"] == "PAT_FORBIDDEN"


@pytest.mark.asyncio
async def test_un_admin_si_declara_la_suya(db):
    suya = await _organizacion(db)
    async with _client(_app(db)) as client:
        resp = await client.post(
            "/api/v1/auth/pats",
            json={"name": "hook", "scopes": ["actividad:write"], "organizacion_id": suya},
            headers=_headers("admin", (suya,)),
        )
    assert resp.status_code == 201, resp.text
    assert resp.json()["organizacion_id"] == suya


@pytest.mark.asyncio
async def test_una_organizacion_que_no_existe_es_un_422(db):
    async with _client(_app(db)) as client:
        resp = await client.post(
            "/api/v1/auth/pats",
            json={"name": "hook", "scopes": ["actividad:write"], "organizacion_id": str(uuid.uuid4())},
            headers=_headers("superadmin"),
        )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["code"] == "ORGANIZACION_DESCONOCIDA"


@pytest.mark.asyncio
async def test_sin_organizacion_sigue_como_antes(db):
    async with _client(_app(db)) as client:
        resp = await client.post(
            "/api/v1/auth/pats",
            json={"name": "mcp", "scopes": ["chatbots:read"]},
            headers=_headers("superadmin"),
        )
    assert resp.status_code == 201, resp.text
    assert resp.json()["organizacion_id"] is None


# --- Lo que la pantalla ofrece lo dice el servidor -------------------------------------------
#
# La página de tokens tenía cinco alcances escritos a mano desde AUTH.3, y los diez que llegaron
# después nunca aparecieron: no se podía emitir ni el `actividad:write` que necesita este hook ni
# el `agentes:consulta` del canario (#215). Ahora el servidor dice qué puede elegir quien emite.


@pytest.mark.asyncio
async def test_las_opciones_de_un_superadmin_son_todos_los_alcances_y_todas_las_organizaciones(db):
    from server.app.core.auth.pat.scopes import ALL_SCOPES

    org = await _organizacion(db)
    async with _client(_app(db)) as client:
        resp = await client.get("/api/v1/auth/pats/opciones", headers=_headers("superadmin"))
    assert resp.status_code == 200, resp.text
    cuerpo = resp.json()
    assert cuerpo["scopes"] == sorted(ALL_SCOPES)
    assert org in {o["id"] for o in cuerpo["organizaciones"]}
    assert all(o["nombre"] for o in cuerpo["organizaciones"])


@pytest.mark.asyncio
async def test_las_de_un_admin_son_su_techo_y_sus_organizaciones(db):
    suya, ajena = await _organizacion(db), await _organizacion(db)
    async with _client(_app(db)) as client:
        resp = await client.get("/api/v1/auth/pats/opciones", headers=_headers("admin", (suya,)))
    cuerpo = resp.json()
    assert "actividad:write" in cuerpo["scopes"]
    assert "chatbots:write" not in cuerpo["scopes"]
    assert [o["id"] for o in cuerpo["organizaciones"]] == [suya]
    assert ajena not in {o["id"] for o in cuerpo["organizaciones"]}
