"""PLAT.5 — la frontera de módulos, declarada en el backend.

Solo `hub_llm_configs_router` declaraba su módulo. `hub_organizaciones_router`, `hub_themes_router`
y `pat_router` son `Deploy: cloud` y no declaraban ninguno: los protegía solo el rol, así que un
admin con el módulo de informes concedido y nada más podía llamarlos por API aunque no tuviera
pantalla. La regla de `AGENTS.md` es que el módulo se declara al registrar el router; estos son
de antes de la regla.

**Y no se puede poner a nivel de router y ya.** `require_module` depende de `get_current_user`,
así que sin sesión responde 401 — y hay tres casos donde eso rompería algo que hoy funciona:

1. **El widget público** (`for-chatbot/{id}` y el logotipo) no tiene sesión ninguna. Un `<img>`
   tampoco manda cabecera de autorización. Esos dos no llevan guarda de módulo.
2. **`/hub/themes/resolved` lo consume el panel entero**, incluida la persona que solo tiene
   `informes`: es de donde sale la marca de la cabecera. Exigirle `plataforma` dejaría a media
   plantilla con el logotipo roto.
3. **La lista de organizaciones la consume el módulo Chatbots**: el selector de `ChatbotsPage` y
   el de la pantalla de valores por defecto. Exigirle `plataforma` rompería una pantalla de otro
   módulo. Lo que es administración de plataforma es **crear, renombrar y borrar** una
   organización, no leer las que gestionas.

Y una consecuencia de PLAT.3 que conviene fijar: los valores por defecto de RAG son
configuración del **módulo Chatbots** aplicada a una organización, así que exigen `chatbots` y
no `plataforma` — su pantalla vive en `/hub`, que es coherente.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import server.app.main  # noqa: F401
from server.app.api.deps import get_current_user, get_session
from server.app.core.auth.models import UserInfo


def _principal(*orgs, role: str = "admin") -> UserInfo:
    return UserInfo(
        user_id="quien-pregunta",
        email="admin@uji.es",
        role=role,
        organizacion_ids=tuple(str(o) for o in orgs),
    )


def _cliente(session, principal, router) -> AsyncClient:
    async def _sesion():
        yield session

    app = FastAPI()
    if principal is not None:
        app.dependency_overrides[get_current_user] = lambda: principal
        from server.app.api.deps import get_current_user_optional

        app.dependency_overrides[get_current_user_optional] = lambda: principal
    # Hasta #272 había que doblar dos proveedores —éste y `get_async_session` del Hub, del que
    # dependía `modulos_concedidos`—; sin el segundo, la guarda consultaba la BD del
    # desarrollador y respondía 403. Ahora hay uno.
    app.dependency_overrides[get_session] = _sesion
    app.include_router(router, prefix="/api/v1")
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _catalogo(session) -> None:
    from server.app.core.auth.modulos import MODULOS_INICIALES
    from server.app.modules.agents_hub.database.config_models import HubPlatformModule

    for codigo, etiqueta in MODULOS_INICIALES:
        session.add(HubPlatformModule(code=codigo, label=etiqueta, vigente=True))
    await session.commit()


async def _conceder(session, user_id: str, *modulos: str) -> None:
    from server.app.modules.agents_hub.database.config_models import HubModuleGrant
    from server.app.routers.redaccion._actor import user_to_uuid

    for m in modulos:
        session.add(
            HubModuleGrant(
                subject_id=str(user_to_uuid(user_id)),
                subject_type="usuario",
                module_code=m,
                granted_by="test",
            )
        )
    await session.commit()


async def _organizacion(session, nombre="Org"):
    from server.app.modules.agents_hub.database.config_models import HubOrganizacion

    fila = HubOrganizacion(id=uuid.uuid4(), name=nombre, partner_id="p1")
    session.add(fila)
    await session.commit()
    return fila


@pytest.mark.sin_guarda_de_modulos
class TestLoQueExigePlataforma:

    @pytest.mark.asyncio
    async def test_should_refuse_creating_an_organisation_without_the_module(self, db_session):
        from server.app.routers.hub_organizaciones_router import router

        await _catalogo(db_session)
        principal = _principal()
        await _conceder(db_session, principal.user_id, "chatbots")

        async with _cliente(db_session, principal, router) as cliente:
            respuesta = await cliente.post(
                "/api/v1/hub/organizaciones", json={"name": "Nueva", "partner_id": "p9"}
            )

        assert respuesta.status_code == 403

    @pytest.mark.asyncio
    async def test_should_allow_creating_it_with_the_module(self, db_session):
        from server.app.routers.hub_organizaciones_router import router

        await _catalogo(db_session)
        principal = _principal()
        await _conceder(db_session, principal.user_id, "plataforma")

        async with _cliente(db_session, principal, router) as cliente:
            respuesta = await cliente.post(
                "/api/v1/hub/organizaciones", json={"name": "Nueva", "partner_id": "p9"}
            )

        assert respuesta.status_code == 201, respuesta.text

    @pytest.mark.asyncio
    async def test_should_refuse_listing_personal_access_tokens_without_the_module(
        self, db_session
    ):
        from server.app.routers.pat_router import router

        await _catalogo(db_session)
        principal = _principal()
        await _conceder(db_session, principal.user_id, "informes")

        async with _cliente(db_session, principal, router) as cliente:
            respuesta = await cliente.get("/api/v1/auth/pats")

        assert respuesta.status_code == 403

    @pytest.mark.asyncio
    async def test_should_refuse_listing_themes_without_the_module(self, db_session):
        from server.app.routers.hub_themes_router import router

        await _catalogo(db_session)
        principal = _principal()
        await _conceder(db_session, principal.user_id, "chatbots")

        async with _cliente(db_session, principal, router) as cliente:
            respuesta = await cliente.get("/api/v1/hub/themes")

        assert respuesta.status_code == 403


@pytest.mark.sin_guarda_de_modulos
class TestLoQueNoPuedeLlevarLaGuarda:

    @pytest.mark.asyncio
    async def test_should_serve_the_resolved_theme_to_someone_without_plataforma(
        self, db_session
    ):
        """**La trampa que el prompt anticipaba.** `/resolved` es de donde sale la marca de la
        cabecera del panel: exigirle `plataforma` dejaría a media plantilla sin logotipo."""
        from server.app.routers.hub_themes_router import router

        await _catalogo(db_session)
        principal = _principal()
        await _conceder(db_session, principal.user_id, "informes")

        async with _cliente(db_session, principal, router) as cliente:
            respuesta = await cliente.get("/api/v1/hub/themes/resolved")

        assert respuesta.status_code == 200, respuesta.text

    @pytest.mark.asyncio
    async def test_should_serve_the_logo_without_any_session(self, db_session):
        """Un `<img>` no manda `Authorization`, y en el widget público no hay sesión ninguna."""
        from server.app.routers.hub_themes_router import router

        await _catalogo(db_session)

        async with _cliente(db_session, None, router) as anonimo:
            respuesta = await anonimo.get(f"/api/v1/hub/themes/{uuid.uuid4()}/logo")

        # 404 porque el tema no existe, no 401/403: la puerta está abierta.
        assert respuesta.status_code == 404

    @pytest.mark.asyncio
    async def test_should_let_the_chatbots_module_read_the_organisation_list(self, db_session):
        """El selector de `ChatbotsPage` y el de valores por defecto viven en el módulo
        Chatbots. Administración de plataforma es **crear, renombrar y borrar**, no leer."""
        from server.app.routers.hub_organizaciones_router import router

        await _catalogo(db_session)
        org = await _organizacion(db_session)
        principal = _principal(org.id)
        await _conceder(db_session, principal.user_id, "chatbots")

        async with _cliente(db_session, principal, router) as cliente:
            respuesta = await cliente.get("/api/v1/hub/organizaciones")

        assert respuesta.status_code == 200, respuesta.text

    @pytest.mark.asyncio
    async def test_should_ask_for_chatbots_on_the_rag_defaults_not_plataforma(self, db_session):
        """Consecuencia de PLAT.3: los valores por defecto de RAG son configuración del módulo
        Chatbots aplicada a una organización, y su pantalla vive en `/hub`."""
        from server.app.routers.hub_organizaciones_router import router

        await _catalogo(db_session)
        org = await _organizacion(db_session)
        principal = _principal(org.id)
        await _conceder(db_session, principal.user_id, "chatbots")

        async with _cliente(db_session, principal, router) as cliente:
            respuesta = await cliente.get(
                f"/api/v1/hub/organizaciones/{org.id}/valores-por-defecto"
            )

        assert respuesta.status_code == 200, respuesta.text

    @pytest.mark.asyncio
    async def test_should_refuse_the_rag_defaults_to_someone_without_chatbots(self, db_session):
        from server.app.routers.hub_organizaciones_router import router

        await _catalogo(db_session)
        org = await _organizacion(db_session)
        principal = _principal(org.id)
        await _conceder(db_session, principal.user_id, "informes")

        async with _cliente(db_session, principal, router) as cliente:
            respuesta = await cliente.get(
                f"/api/v1/hub/organizaciones/{org.id}/valores-por-defecto"
            )

        assert respuesta.status_code == 403


class TestElInventarioDeRouters:
    """El entregable del prompt: qué módulo le toca a cada router que no lo declara.

    Se comprueba sobre los docstrings porque es donde `AGENTS.md` manda etiquetarlo, al lado
    de `Deploy:`. Un inventario que viva en el historial y no en el código se desactualiza sin
    que nadie lo note.
    """

    ESPERADO = {
        "hub_organizaciones_router": "plataforma",
        "hub_themes_router": "plataforma",
        "pat_router": "plataforma",
        "hub_llm_configs_router": "plataforma",
        "hub_users_router": "plataforma",
        "hub_modulos_router": "plataforma",
        "hub_chatbots_router": "chatbots",
        "hub_ingestion_router": "chatbots",
        "hub_prompt_templates_router": "chatbots",
        "hub_test_scenarios_router": "chatbots",
        # De curación y no de Chatbots, aunque el nombre no lo diga: su propio
        # docstring empieza con «Router de curación» y los huecos que detecta
        # alimentan la cola de revisión de contenido. Mi inventario lo tenía mal.
        "hub_content_quality_router": "curacion",
        "hub_sites_router": "curacion",
        "hub_activity_prompts_router": "plataforma",
    }

    @pytest.mark.parametrize("modulo", sorted(set(ESPERADO.values())))
    def test_should_label_every_router_with_its_module(self, modulo: str):
        import importlib

        faltan = []
        for nombre, esperado in self.ESPERADO.items():
            if esperado != modulo:
                continue
            mod = importlib.import_module(f"server.app.routers.{nombre}")
            doc = mod.__doc__ or ""
            if f"Módulo: {esperado}" not in doc:
                faltan.append(f"{nombre} (le toca «{esperado}»)")

        assert faltan == [], (
            "estos routers no dicen a qué módulo pertenecen en su docstring, como exige "
            "AGENTS.md al lado de `Deploy:`:\n  " + "\n  ".join(faltan)
        )
