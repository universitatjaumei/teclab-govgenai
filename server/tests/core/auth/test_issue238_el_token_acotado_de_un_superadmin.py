"""#238 — un token de superadmin acotado a una organización vale sólo en ésa.

**Cómo salió.** En la revisión independiente de la PR #237. `acota_a_la_organizacion` dejaba
`organizacion_ids=(X,)` pero **conservaba `role="superadmin"`**, y todo lo que mira
`is_superadmin` antes que las organizaciones —`puede_acceder`, `assert_org_access`,
`scope_query_to_orgs`, el catálogo de funciones— dejaba pasar al token a todas. La pantalla de
tokens dice «Acota el token a una organización» y la documentación «acota, nunca amplía»: un
token «acotado» filtrado tenía el radio de uno sin acotar.

**Decisión del usuario (2026-10-07): actúa como administrador de esa organización.** Ni fuera de
ella ni con lo que sólo puede un superadmin, que es lo que se entiende al acotar.

Por el camino real: el token se emite y se valida contra la base, y se usa por HTTP.
"""
from __future__ import annotations

import uuid

import httpx
import pytest
from fastapi import FastAPI
from sqlmodel.ext.asyncio.session import AsyncSession


def _superadmin():
    from server.app.core.auth.models import UserInfo

    return UserInfo(user_id=f"sa-{uuid.uuid4().hex[:8]}", email="sa@uji.es", role="superadmin")


async def _organizacion(db) -> str:
    from server.app.modules.agents_hub.database.config_models import HubOrganizacion

    ident = uuid.uuid4()
    db.session.add(HubOrganizacion(id=ident, name=f"Org {ident.hex[:6]}", partner_id="uji"))
    await db.session.commit()
    return str(ident)


async def _token(db, organizacion_id: str | None, scopes=("actividad:write",)) -> str:
    from server.app.core.auth.pat.service import PatService

    async with AsyncSession(db.engine) as s:
        _fila, plano = await PatService(s).create(
            owner=_superadmin(),
            name="acotado",
            scopes=list(scopes),
            organizacion_id=uuid.UUID(organizacion_id) if organizacion_id else None,
        )
    return plano


async def _principal(db, token: str):
    from server.app.core.auth.pat.service import PatService

    async with AsyncSession(db.engine) as s:
        return (await PatService(s).verify(token)).user_info


class TestElPrincipal:

    @pytest.mark.asyncio
    async def test_actua_como_administrador_de_esa_organizacion(self, db):
        org = await _organizacion(db)
        principal = await _principal(db, await _token(db, org))
        assert principal.role == "admin"
        assert not principal.is_superadmin
        assert principal.organizacion_ids == (org,)

    @pytest.mark.asyncio
    async def test_y_las_comprobaciones_de_organizacion_lo_paran_fuera(self, db):
        from server.app.core.auth.tenancy import puede_acceder

        suya, otra = await _organizacion(db), await _organizacion(db)
        principal = await _principal(db, await _token(db, suya))
        assert puede_acceder(principal, suya)
        assert not puede_acceder(principal, otra)

    @pytest.mark.asyncio
    async def test_sin_organizacion_sigue_siendo_superadmin(self, db):
        """Un token sin acotar vale donde valga su dueño: lo que significan los que ya existen."""
        principal = await _principal(db, await _token(db, None))
        assert principal.is_superadmin
        assert principal.organizacion_ids == ()


def _app(db) -> FastAPI:
    from server.app.api.deps import get_session
    from server.app.modules.agents_hub.database.connection import get_async_session
    from server.app.routers.actividad_router import router

    async def _sesion():
        async with AsyncSession(db.engine) as s:
            yield s

    app = FastAPI()
    app.dependency_overrides[get_session] = _sesion
    app.dependency_overrides[get_async_session] = _sesion
    app.include_router(router, prefix="/api/v1")
    return app


@pytest.mark.asyncio
async def test_por_http_no_lee_el_catalogo_de_otra_organizacion(db):
    """El caso concreto de la revisión: `GET /actividad/categorias?organizacion_id=<otra>`."""
    suya, otra = await _organizacion(db), await _organizacion(db)
    cabeceras = {"Authorization": f"Bearer {await _token(db, suya)}"}
    transporte = httpx.ASGITransport(app=_app(db))
    async with httpx.AsyncClient(transport=transporte, base_url="http://t") as cliente:
        ajena = await cliente.get("/api/v1/actividad/categorias", params={"organizacion_id": otra}, headers=cabeceras)
        propia = await cliente.get("/api/v1/actividad/categorias", headers=cabeceras)
    assert ajena.status_code == 403, ajena.text
    assert propia.status_code == 200, propia.text
