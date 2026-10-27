"""REG.2 — el endpoint que registra actividad, y por qué es sólo para clientes máquina.

`POST /api/v1/actividad` recibe un `ActividadIAEvent` de una herramienta externa y lo persiste.
Dos decisiones del bloque, y las dos se comprueban aquí:

**La organización no viaja en el payload.** Se deriva del dueño del token. Un agente externo no
elige en nombre de qué organización registra, igual que no elige qué datos puede leer: si lo
eligiera, un token de una organización podría escribir en el registro de otra, y el registro
dejaría de servir para dar cuenta de nada.

**La escritura exige un PAT, no una sesión.** `require_scopes` por sí solo **deja pasar una sesión
JWT** —los principales humanos no se filtran por scope— y aquí eso sería un agujero: quien registra
actividad es una máquina, y una sesión de navegador que pudiera escribir en el registro permitiría
fabricar entradas desde el panel. De ahí `require_pat_scopes`, que exige las dos cosas.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import server.app.main  # noqa: F401

from server.app.api.deps import get_current_user
from server.app.core.auth.models import UserInfo

ORG_A = "735a5f55-7020-4c88-a374-c2b641c5b00b"
ORG_B = "00000000-0000-0000-0000-000000000010"


def _evento(**cambios) -> dict:
    base = {
        "ocurrido_en": datetime(2026, 9, 3, 10, 30, tzinfo=timezone.utc).isoformat(),
        "actor": "u-7f3a1c",
        "herramienta": "claude-cowork",
        "agente": "revisor-de-contratos",
        "finalidad": "Revisión previa de un pliego",
        "modelo_usado": "claude-opus-5",
        "categorias_datos": ["datos_identificativos"],
    }
    base.update(cambios)
    return base


def _principal(org: str) -> UserInfo:
    return UserInfo(
        user_id="agente-externo",
        email="integracion@uji.es",
        role="admin",
        organizacion_ids=(org,),
    )


def _cliente(session, org: str = ORG_A, scopes: list[str] | None = None) -> AsyncClient:
    """Cliente cuyo principal es un PAT con los scopes dados.

    `scopes=None` simula una **sesión JWT**: es exactamente cómo la distingue el código, con
    `request.state.pat_scopes` a `None`, así que el test usa el mismo mecanismo que producción y
    no una bandera propia.
    """
    from server.app.api.deps import get_session
    from server.app.routers.actividad_router import router

    async def _sesion():
        yield session

    app = FastAPI()

    @app.middleware("http")
    async def _marca_el_pat(request, call_next):
        request.state.pat_scopes = scopes
        return await call_next(request)

    app.dependency_overrides[get_current_user] = lambda: _principal(org)
    app.dependency_overrides[get_session] = _sesion
    app.include_router(router, prefix="/api/v1")
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ─────────────────────────── El camino bueno ───────────────────────────────

class TestRegistrarUnUso:

    async def test_should_persist_the_event_and_answer_with_its_id(self, db_session):
        async with _cliente(db_session, scopes=["actividad:write"]) as c:
            r = await c.post("/api/v1/actividad", json=_evento())

        assert r.status_code == 201, r.text
        cuerpo = r.json()
        assert uuid.UUID(cuerpo["id"])
        assert cuerpo["registrado_en"], "el cliente necesita saber cuándo quedó registrado"

    async def test_should_take_the_organisation_from_the_token_owner(self, db_session):
        """Lo que impide que un token de una organización escriba en el registro de otra."""
        from sqlalchemy import select

        from server.app.modules.agents_hub.database.operational_models import HubActividadIA

        async with _cliente(db_session, org=ORG_A, scopes=["actividad:write"]) as c:
            await c.post("/api/v1/actividad", json=_evento())

        fila = (await db_session.execute(select(HubActividadIA))).scalars().one()
        assert str(fila.organizacion_id) == ORG_A

    async def test_should_keep_two_tokens_writing_to_their_own_organisation(self, db_session):
        from sqlalchemy import select

        from server.app.modules.agents_hub.database.operational_models import HubActividadIA

        async with _cliente(db_session, org=ORG_A, scopes=["actividad:write"]) as c:
            await c.post("/api/v1/actividad", json=_evento(herramienta="claude-cowork"))
        async with _cliente(db_session, org=ORG_B, scopes=["actividad:write"]) as c:
            await c.post("/api/v1/actividad", json=_evento(herramienta="copilot"))

        filas = (await db_session.execute(select(HubActividadIA))).scalars().all()
        por_org = {str(f.organizacion_id): f.herramienta for f in filas}

        assert por_org == {ORG_A: "claude-cowork", ORG_B: "copilot"}


# ─────────────────────────── Quién puede escribir ──────────────────────────

class TestQuienPuedeEscribir:

    async def test_should_refuse_a_pat_without_the_scope(self, db_session):
        async with _cliente(db_session, scopes=["chatbots:read"]) as c:
            r = await c.post("/api/v1/actividad", json=_evento())

        assert r.status_code == 403, r.text
        assert "actividad:write" in r.text, (
            "el 403 tiene que decir qué scope falta: quien lo recibe tiene que poder pedirlo, "
            "no adivinarlo."
        )

    async def test_should_refuse_a_human_session(self, db_session):
        """Decisión del bloque: la escritura es para clientes máquina.

        `require_scopes` a secas deja pasar una sesión JWT porque los principales humanos no se
        filtran por scope. Aquí eso permitiría fabricar entradas del registro desde el panel, que
        es justo lo que un registro de gobernanza no puede admitir.
        """
        async with _cliente(db_session, scopes=None) as c:
            r = await c.post("/api/v1/actividad", json=_evento())

        assert r.status_code == 403, r.text

    async def test_should_refuse_without_any_credential(self, db_session):
        """Sin sobreescribir el principal: la dependencia de autenticación real responde 401."""
        from server.app.api.deps import get_session
        from server.app.routers.actividad_router import router

        async def _sesion():
            yield db_session

        app = FastAPI()
        app.dependency_overrides[get_session] = _sesion
        app.include_router(router, prefix="/api/v1")

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            r = await c.post("/api/v1/actividad", json=_evento())

        assert r.status_code == 401, r.text


# ─────────────────────────── Lo que el contrato rechaza ────────────────────

class TestElContratoSeAplicaEnElEndpoint:
    """El contrato no sirve de nada si el endpoint no lo hace cumplir."""

    @pytest.mark.parametrize("campo", ["prompt", "payload", "content"])
    async def test_should_reject_a_content_field(self, db_session, campo: str):
        async with _cliente(db_session, scopes=["actividad:write"]) as c:
            r = await c.post("/api/v1/actividad", json=_evento(**{campo: "texto"}))

        assert r.status_code == 422, r.text

    async def test_should_reject_an_organisation_chosen_by_the_caller(self, db_session):
        """`organizacion_id` no es un campo del contrato, y por eso llega 422 y no se ignora.

        Si se ignorara en silencio, quien integra creería que puede elegir la organización y
        estaría escribiendo en otra sin enterarse.
        """
        async with _cliente(db_session, scopes=["actividad:write"]) as c:
            r = await c.post("/api/v1/actividad", json=_evento(organizacion_id=ORG_B))

        assert r.status_code == 422, r.text

    async def test_should_reject_a_naive_timestamp(self, db_session):
        async with _cliente(db_session, scopes=["actividad:write"]) as c:
            r = await c.post(
                "/api/v1/actividad", json=_evento(ocurrido_en="2026-09-03T10:30:00")
            )

        assert r.status_code == 422, r.text


# ─────────────────────────── El catálogo de scopes ─────────────────────────

class TestLosScopesNuevos:

    def test_should_add_both_scopes_to_the_catalogue(self):
        from server.app.core.auth.pat.scopes import (
            ACTIVIDAD_WRITE,
            ALL_SCOPES,
            ANONIMIZACION_USE,
        )

        assert ACTIVIDAD_WRITE == "actividad:write"
        assert ANONIMIZACION_USE == "anonimizacion:use"
        assert {ACTIVIDAD_WRITE, ANONIMIZACION_USE} <= ALL_SCOPES, (
            "un scope que no está en `ALL_SCOPES` no se puede emitir: `validate_scopes` lo "
            "rechaza como desconocido."
        )

    @pytest.mark.parametrize("rol", ["superadmin", "admin"])
    def test_should_let_both_roles_issue_them(self, rol: str):
        """Los dos, a diferencia de `chatbots:write`, que es sólo de superadmin.

        La razón de aquella excepción es que muta un chatbot en producción in-place; registrar
        actividad es añadir metadatos y no muta nada, así que no hay motivo para reservarlo.
        """
        from server.app.core.auth.pat.scopes import (
            ACTIVIDAD_WRITE,
            ANONIMIZACION_USE,
            allowed_scopes_for_role,
        )

        permitidos = allowed_scopes_for_role(rol)
        assert {ACTIVIDAD_WRITE, ANONIMIZACION_USE} <= permitidos


class TestElRouterEsEdgeYEstaRegistrado:

    def test_should_be_declared_as_edge(self):
        """El registro son datos del cliente final: se sirve donde viven."""
        from server.app.routers import actividad_router

        assert "Deploy: edge" in (actividad_router.__doc__ or ""), (
            "el router tiene que declarar su lado de la frontera en el docstring; lo comprueba "
            "también el inventario de routers."
        )

    def test_should_be_registered_in_the_edge_side(self):
        import inspect

        from server.app.main import _register_edge

        assert "actividad_router" in inspect.getsource(_register_edge)

    def test_should_expose_the_endpoint_with_an_explicit_operation_id(self):
        from server.app.main import app
        from server.tests.rutas import operaciones

        rutas = operaciones(app)
        assert "/api/v1/actividad" in rutas
        assert rutas["/api/v1/actividad"], (
            "sin `operation_id` explícito, el cliente generado hereda un nombre ilegible del "
            "nombre de la función y su ruta."
        )
