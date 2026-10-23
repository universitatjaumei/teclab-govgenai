"""MT.16 (adelantado a SEC.9.7) — Dos organizaciones, y ninguna ve nada de la otra.

**Por qué este test se adelanta de la fase 2 del Bloque MT.** El piloto arranca con **una sola
organización**, así que el aislamiento —que es la promesa central de la arquitectura y la razón de
que exista la jerarquía Plataforma → Organización → Chatbot— **no se ejercita en producción**. Sin
este fichero, todo lo que SEC.9 acaba de cerrar queda comprobado endpoint por endpoint y con
dobles, y nadie ha visto nunca a dos administradores reales sobre una base real no viéndose.

Es también el único test del bloque que puede fallar por una razón que los demás no ven: los
endpoints se comprueban aquí **juntos**, sobre las **mismas** filas, con credenciales distintas. Un
`WHERE` correcto en cada sitio y un dato sembrado en el sitio equivocado dan verde doce veces por
separado y rojo aquí.

Lo que se siembra, dos veces —una por organización—: un modelo de LLM, un asistente, un sitio de
curación y un override de prompt de actividad. Lo que se comprueba: que el administrador de A
recibe 403 o listado vacío sobre **todo** lo de B, que el superadministrador ve las dos, y que la
credencial pública del widget de A no alcanza nada de B.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from server.app.core.auth.models import UserInfo
from server.app.modules.agents_hub.database.config_models import (
    HubActivityPrompt,
    HubChatbot,
    HubLLMConfig,
    HubOrganizacion,
)
from server.app.modules.agents_hub.database.operational_models import HubWebSite


def _uid() -> str:
    return uuid.uuid4().hex[:8]


class Mundo:
    """Las filas de una organización, para poder hablar de «las de A» y «las de B»."""

    def __init__(self, organizacion, llm, chatbot, sitio):
        self.organizacion = organizacion
        self.llm = llm
        self.chatbot = chatbot
        self.sitio = sitio

    @property
    def admin(self) -> UserInfo:
        return UserInfo(
            user_id=f"admin-{self.organizacion.id}",
            email=f"admin-{_uid()}@example.org",
            role="admin",
            organizacion_ids=(str(self.organizacion.id),),
        )


def _superadmin() -> UserInfo:
    return UserInfo(user_id="root", email="root@example.org", role="superadmin")


async def _proveedor_compartido(session) -> str:
    """El catálogo de proveedores es **de plataforma a propósito** (MT.2): Google es Google en
    todos los municipios. Lo que se separa es la credencial, no el tipo. Así que las dos
    organizaciones comparten esta fila, y eso es correcto — no es una fuga."""
    from server.app.modules.agents_hub.database.config_models import HubProvider

    provider_id = f"prov-{_uid()}"
    session.add(
        HubProvider(id=provider_id, name="Proveedor", provider_type="google_genai")
    )
    await session.commit()
    return provider_id


async def _sembrar(session, etiqueta: str, provider_id: str) -> Mundo:
    organizacion = HubOrganizacion(name=f"{etiqueta} {_uid()}", partner_id=f"p-{_uid()}")
    session.add(organizacion)
    await session.commit()
    await session.refresh(organizacion)

    llm = HubLLMConfig(
        organizacion_id=organizacion.id,
        provider=provider_id,
        model_name="gemini-2.5-flash",
        temperature=0.1,
        top_p=1.0,
        max_tokens=1000,
        tier=1,
        purpose="chat",
        label=f"Modelo de {etiqueta}",
        is_default=False,
    )
    session.add(llm)
    await session.commit()
    await session.refresh(llm)

    chatbot = HubChatbot(
        organizacion_id=organizacion.id,
        llm_config_id=llm.id,
        name=f"Asistente de {etiqueta}",
        system_prompt=f"Secreto de {etiqueta}",
        sources=[],
    )
    sitio = HubWebSite(
        organizacion_id=organizacion.id,
        name=f"Portal de {etiqueta}",
        root_url=f"https://{etiqueta.lower()}.example.org/",
    )
    session.add(chatbot)
    session.add(sitio)
    await session.commit()
    await session.refresh(chatbot)
    await session.refresh(sitio)

    return Mundo(organizacion, llm, chatbot, sitio)


def _app(session, principal: UserInfo):
    """Una app con **todas** las superficies acotadas a la vez.

    Juntas y no una por test: lo que este fichero busca es precisamente el fallo que sólo
    aparece cuando los mismos datos se piden desde varios routers con la misma credencial.
    """
    from fastapi import FastAPI

    from server.app.api.deps import (
        get_current_user,
        get_current_user_optional,
        get_session,
        modulos_concedidos,
    )
    from server.app.routers.hub_activity_prompts_router import (
        router as activity_prompts_router,
    )
    from server.app.routers.hub_chatbots_router import router as chatbots_router
    from server.app.routers.hub_llm_configs_router import router as llm_configs_router
    from server.app.routers.hub_sites_router import router as sites_router

    async def _sesion():
        yield session

    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: principal
    app.dependency_overrides[get_current_user_optional] = lambda: principal
    app.dependency_overrides[get_session] = _sesion
    app.dependency_overrides[get_session] = _sesion
    # La frontera de módulos tiene su propio test (PLAT.5). Aquí se concede todo a propósito:
    # lo que se mide es la de **organización**, y un 403 por módulo la taparía.
    app.dependency_overrides[modulos_concedidos] = lambda: [
        "plataforma",
        "chatbots",
        "curacion",
        "informes",
    ]
    for router in (chatbots_router, llm_configs_router, activity_prompts_router, sites_router):
        app.include_router(router, prefix="/api/v1")
    return app


def _cliente(session, principal: UserInfo):
    """Cliente **asíncrono** y no `TestClient`.

    `TestClient` es síncrono: monta la app en su propio bucle de eventos a través de un portal
    de anyio, y la sesión de base de datos de la fixture vive en el bucle de pytest-asyncio.
    Mezclarlos da un `got Future attached to a different loop` que no se parece en nada a su
    causa. Con `ASGITransport` la petición corre en el mismo bucle que la sesión, que es lo que
    permite sembrar con el ORM y leer por HTTP en el mismo test.
    """
    import httpx

    app = _app(session, principal)
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


async def _pedir(session, principal: UserInfo, metodo: str, url: str, **kwargs):
    """Una petición, con su cliente abierto y cerrado. Evita repetir el `async with`."""
    async with _cliente(session, principal) as cliente:
        return await cliente.request(metodo, url, **kwargs)


@pytest.fixture
async def dos_mundos(db_session):
    provider_id = await _proveedor_compartido(db_session)
    a = await _sembrar(db_session, "Onda", provider_id)
    b = await _sembrar(db_session, "Nules", provider_id)
    return a, b


class TestNingunaVeNadaDeLaOtra:

    @pytest.mark.asyncio
    async def test_should_not_list_the_other_organisations_assistants(self, dos_mundos, db_session):
        a, b = dos_mundos
        respuesta = await _pedir(db_session, a.admin, "GET", "/api/v1/hub/chatbots")

        assert respuesta.status_code == 200
        cuerpo = respuesta.text
        assert a.chatbot.name in cuerpo
        assert b.chatbot.name not in cuerpo
        # El prompt de sistema es el activo que más duele: es cómo trabaja el otro.
        assert "Secreto de Nules" not in cuerpo

    @pytest.mark.asyncio
    async def test_should_forbid_reading_the_other_organisations_assistant(
        self, dos_mundos, db_session
    ):
        a, b = dos_mundos
        respuesta = await _pedir(
            db_session, a.admin, "GET", f"/api/v1/hub/chatbots/{b.chatbot.id}/corpus-stats"
        )
        assert respuesta.status_code == 403

    @pytest.mark.asyncio
    async def test_should_not_list_the_other_organisations_models(self, dos_mundos, db_session):
        a, b = dos_mundos
        respuesta = await _pedir(db_session, a.admin, "GET", "/api/v1/hub/llm-configs")

        assert respuesta.status_code == 200
        assert a.llm.label in respuesta.text
        assert b.llm.label not in respuesta.text

    @pytest.mark.asyncio
    async def test_should_forbid_touching_the_other_organisations_model(
        self, dos_mundos, db_session
    ):
        a, b = dos_mundos
        ruta = f"/api/v1/hub/llm-configs/{b.llm.id}"

        async with _cliente(db_session, a.admin) as cliente:
            patch = await cliente.patch(ruta, json={"label": "Secuestrado"})
            delete = await cliente.delete(ruta)
            probar = await cliente.post(f"{ruta}/test")

        assert patch.status_code == 403
        assert delete.status_code == 403
        assert probar.status_code == 403

        # Y no ha cambiado nada: el 403 llega antes de tocar la fila.
        await db_session.refresh(b.llm)
        assert b.llm.label != "Secuestrado"

    @pytest.mark.asyncio
    async def test_should_not_list_the_other_organisations_sites(self, dos_mundos, db_session):
        a, b = dos_mundos
        respuesta = await _pedir(db_session, a.admin, "GET", "/api/v1/hub/sites")

        assert respuesta.status_code == 200
        assert b.sitio.name not in respuesta.text

    @pytest.mark.asyncio
    async def test_should_not_take_the_other_organisations_activity_prompt(
        self, dos_mundos, db_session
    ):
        """El caso que MT.6 dejó a medias y cerró SEC.9.3: el override es de su organización."""
        from server.app.modules.redaccion.services.actividades_llm import ActividadLLM

        a, b = dos_mundos
        actividad = str(next(iter(ActividadLLM)))
        db_session.add(
            HubActivityPrompt(
                id=uuid.uuid4(),
                activity=actividad,
                organizacion_id=b.organizacion.id,
                template_text="EL PROMPT DE NULES",
                override_tier=3,
            )
        )
        await db_session.commit()

        respuesta = await _pedir(db_session, a.admin, "GET", "/api/v1/hub/activity-prompts")

        assert respuesta.status_code == 200
        assert "EL PROMPT DE NULES" not in respuesta.text

    @pytest.mark.asyncio
    async def test_should_not_overwrite_the_other_organisations_activity_prompt(
        self, dos_mundos, db_session
    ):
        from server.app.modules.redaccion.services.actividades_llm import ActividadLLM

        a, b = dos_mundos
        actividad = str(next(iter(ActividadLLM)))
        de_b = HubActivityPrompt(
            id=uuid.uuid4(),
            activity=actividad,
            organizacion_id=b.organizacion.id,
            template_text="EL PROMPT DE NULES",
            override_tier=3,
        )
        db_session.add(de_b)
        await db_session.commit()

        respuesta = await _pedir(
            db_session,
            a.admin,
            "PUT",
            f"/api/v1/hub/activity-prompts/{actividad}",
            json={"override_tier": 1, "template_text": ""},
        )

        assert respuesta.status_code == 200
        await db_session.refresh(de_b)
        assert de_b.template_text == "EL PROMPT DE NULES"
        assert de_b.override_tier == 3


class TestElSuperadministradorVeLasDos:
    """No es una excepción al aislamiento: es el permiso correcto. Lo que falta es la *vista*,
    y eso es MT.8. Se fija aquí para que nadie lo «arregle» convirtiéndolo en un 403."""

    @pytest.mark.asyncio
    async def test_should_let_the_superadmin_see_both_organisations(self, dos_mundos, db_session):
        a, b = dos_mundos
        respuesta = await _pedir(db_session, _superadmin(), "GET", "/api/v1/hub/chatbots")

        assert respuesta.status_code == 200
        assert a.chatbot.name in respuesta.text
        assert b.chatbot.name in respuesta.text


class TestElVisitanteAnonimoNoCruza:

    @pytest.mark.asyncio
    async def test_should_not_let_the_widget_of_one_org_reach_the_other(
        self, dos_mundos, db_session
    ):
        """La credencial de sitio se ata al asistente de la ruta (SEC.8.5), así que la de A no
        abre el de B. Se comprueba sobre el resolvedor y no sobre el endpoint de chat, que
        arrastraría el grafo entero: lo que decide es la comparación de `chatbot_id`."""
        from server.app.core.auth.widget_key import (
            actor_anonimo_de_widget,
            generar_clave,
            hash_de_clave,
        )
        from server.app.modules.agents_hub.database.config_models import HubWidgetKey

        a, b = dos_mundos
        clave = generar_clave()
        db_session.add(
            HubWidgetKey(
                chatbot_id=a.chatbot.id,
                key_hash=hash_de_clave(clave),
                name="widget de Onda",
            )
        )
        await db_session.commit()

        from server.app.core.auth.widget_key import resolver_widget_key

        resuelta = await resolver_widget_key(db_session, clave)
        assert resuelta is not None
        # Atada al asistente de A: comparada con el de B, no vale.
        assert str(resuelta.chatbot_id) == str(a.chatbot.id)
        assert str(resuelta.chatbot_id) != str(b.chatbot.id)

        # Y el actor que produce no lleva organizaciones, así que no puede escalar por identidad.
        actor = actor_anonimo_de_widget(a.chatbot.id)
        assert actor.organizacion_ids == ()
        assert actor.role == "anonymous"


class TestElDatoSembradoEstaDondeDice:
    """Guardarraíl del propio test: si el sembrado no separa las organizaciones, todo lo de
    arriba pasa sin comprobar nada. Es el modo de fallo de un test de aislamiento."""

    @pytest.mark.asyncio
    async def test_should_seed_two_distinct_organisations(self, dos_mundos, db_session):
        a, b = dos_mundos
        assert a.organizacion.id != b.organizacion.id

        filas = (
            (await db_session.execute(select(HubChatbot).where(
                HubChatbot.organizacion_id.in_([a.organizacion.id, b.organizacion.id])
            ))).scalars().all()
        )
        por_organizacion = {str(f.organizacion_id) for f in filas}
        assert por_organizacion == {str(a.organizacion.id), str(b.organizacion.id)}
