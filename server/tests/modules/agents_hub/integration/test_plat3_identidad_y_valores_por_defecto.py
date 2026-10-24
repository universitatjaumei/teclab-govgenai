"""PLAT.3 — la identidad del inquilino y los valores por defecto de RAG no son lo mismo.

`OrganizacionRead` devolvía en el mismo sitio tres cosas de ámbitos distintos: la identidad de
la organización (`name`, `partner_id`, `is_active`), su tema —muerto, y lo retira PLAT.7— y
**catorce `default_*`** que son configuración de RAG: perfil de grafo, modo de recuperación,
umbral de calidad, troceado, reranker, presupuesto de contexto, reescritura de consulta. Por eso
la pantalla acabó bajo Chatbots: la mayoría de sus campos sí son de Chatbots. Moverla de sitio
sin partirla se llevaría los defaults de RAG fuera de su módulo.

**Y al partirla aparece un defecto real, distinto del que suponía el plan.** El prompt temía que
omitir un campo lo pisara con su valor por defecto. Es lo contrario: el `PATCH` usaba

    body.model_dump(exclude_none=True)

y `exclude_none` descarta también los `null` **explícitos**. Omitir estaba a salvo; lo imposible
era **volver a «heredar»**. Seis campos tienen ese contrato escrito en el propio modelo —
`default_context_token_budget` («None = heredar el default de plataforma»), los tres de
troceado, `default_query_rewriting_enabled` y `rewrite_llm_config_id`—, así que una vez fijado un
valor propio no había forma de devolverlos a heredar por API. `exclude_unset` distingue «no lo
mandé» de «mándalo a null», que es lo que hacía falta.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import server.app.main  # noqa: F401

from server.app.api.deps import get_current_user
from server.app.core.auth.models import UserInfo
from server.app.api.deps import get_session
from server.app.routers.hub_organizaciones_router import router

#: Los campos que son configuración de RAG y **no** identidad del inquilino.
CAMPOS_DE_RAG = (
    "default_public_graph_profile",
    "default_retrieval_mode",
    "default_language_mode",
    "default_quality_threshold",
    "default_min_retrieval_results",
    "default_min_retrieval_score",
    "default_reranker_enabled",
    "default_answer_template",
    "default_context_token_budget",
    "default_chunk_size",
    "default_chunk_overlap",
    "default_chunking_strategy",
    "default_query_rewriting_enabled",
    "rewrite_llm_config_id",
)

#: Los que significan «heredar el defecto de plataforma» cuando valen `None`.
HEREDABLES = (
    "default_context_token_budget",
    "default_chunk_size",
    "default_chunk_overlap",
    "default_chunking_strategy",
    "default_query_rewriting_enabled",
)


def _principal(*organizaciones, role: str = "admin") -> UserInfo:
    return UserInfo(
        user_id="quien-administra",
        email="admin@uji.es",
        role=role,
        organizacion_ids=tuple(str(o) for o in organizaciones),
    )


def _cliente(session, principal: UserInfo) -> AsyncClient:
    async def _sesion():
        yield session

    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: principal
    app.dependency_overrides[get_session] = _sesion
    app.include_router(router, prefix="/api/v1")
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _organizacion(session, **campos):
    from server.app.modules.agents_hub.database.config_models import HubOrganizacion

    fila = HubOrganizacion(
        id=uuid.uuid4(),
        name=campos.pop("name", "Organización de prueba"),
        partner_id=campos.pop("partner_id", "p1"),
        **campos,
    )
    session.add(fila)
    await session.commit()
    return fila


# ───────────────── El defecto: «heredar» era inalcanzable ─────────────────


class TestVolverAHeredarEsPosible:

    @pytest.mark.asyncio
    @pytest.mark.parametrize("campo", HEREDABLES)
    async def test_should_let_a_field_go_back_to_inheriting(self, db_session, campo: str):
        """**El test del prompt.** `exclude_none` descartaba el `null` explícito, así que una
        organización con valor propio se quedaba con él para siempre."""
        valores = {
            "default_context_token_budget": 64000,
            "default_chunk_size": 500,
            "default_chunk_overlap": 50,
            "default_chunking_strategy": "fixed",
            "default_query_rewriting_enabled": True,
        }
        org = await _organizacion(db_session, **{campo: valores[campo]})
        assert getattr(org, campo) is not None

        async with _cliente(db_session, _principal(org.id)) as cliente:
            respuesta = await cliente.patch(
                f"/api/v1/hub/organizaciones/{org.id}/valores-por-defecto",
                json={campo: None},
            )

        assert respuesta.status_code == 200, respuesta.text
        await db_session.refresh(org)
        assert getattr(org, campo) is None, (
            f"{campo} no volvió a heredar: el null explícito se perdió"
        )

    @pytest.mark.asyncio
    async def test_should_still_not_touch_what_was_not_sent(self, db_session):
        """Lo que ya funcionaba sigue funcionando: omitir un campo no lo cambia."""
        org = await _organizacion(db_session, default_chunk_size=500)

        async with _cliente(db_session, _principal(org.id)) as cliente:
            await cliente.patch(
                f"/api/v1/hub/organizaciones/{org.id}/valores-por-defecto",
                json={"default_chunk_overlap": 25},
            )

        await db_session.refresh(org)
        assert org.default_chunk_size == 500
        assert org.default_chunk_overlap == 25


# ───────────────── Cada mitad se guarda sin pisar la otra ─────────────────


class TestLasDosMitadesNoSePisan:

    @pytest.mark.asyncio
    async def test_should_not_alter_any_rag_default_when_saving_identity(self, db_session):
        org = await _organizacion(
            db_session, default_chunk_size=500, default_reranker_enabled=True
        )

        async with _cliente(db_session, _principal(org.id)) as cliente:
            respuesta = await cliente.patch(
                f"/api/v1/hub/organizaciones/{org.id}",
                json={"name": "Nombre nuevo"},
            )

        assert respuesta.status_code == 200, respuesta.text
        await db_session.refresh(org)
        assert org.name == "Nombre nuevo"
        assert org.default_chunk_size == 500
        assert org.default_reranker_enabled is True

    @pytest.mark.asyncio
    async def test_should_not_alter_identity_when_saving_rag_defaults(self, db_session):
        org = await _organizacion(db_session, name="Intacta", partner_id="p-original")

        async with _cliente(db_session, _principal(org.id)) as cliente:
            await cliente.patch(
                f"/api/v1/hub/organizaciones/{org.id}/valores-por-defecto",
                json={"default_reranker_enabled": True},
            )

        await db_session.refresh(org)
        assert org.name == "Intacta"
        assert org.partner_id == "p-original"
        assert org.is_active is True

    @pytest.mark.asyncio
    async def test_should_refuse_a_rag_field_on_the_identity_endpoint(self, db_session):
        """`extra="forbid"`: mandar un campo de RAG aquí es un error de quien llama, y decirlo
        es mejor que ignorarlo — ignorarlo hace creer que se guardó."""
        org = await _organizacion(db_session)

        async with _cliente(db_session, _principal(org.id)) as cliente:
            respuesta = await cliente.patch(
                f"/api/v1/hub/organizaciones/{org.id}",
                json={"name": "X", "default_chunk_size": 999},
            )

        assert respuesta.status_code == 422

    @pytest.mark.asyncio
    async def test_should_refuse_an_identity_field_on_the_defaults_endpoint(self, db_session):
        org = await _organizacion(db_session)

        async with _cliente(db_session, _principal(org.id)) as cliente:
            respuesta = await cliente.patch(
                f"/api/v1/hub/organizaciones/{org.id}/valores-por-defecto",
                json={"name": "X"},
            )

        assert respuesta.status_code == 422


# ───────────────── El contrato de cada mitad ─────────────────


class TestElContratoDeCadaMitad:

    @pytest.mark.asyncio
    async def test_should_keep_the_rag_defaults_out_of_the_identity_payload(self, db_session):
        """La pantalla de identidad no puede tener que devolver catorce campos que no muestra."""
        org = await _organizacion(db_session)

        async with _cliente(db_session, _principal(org.id)) as cliente:
            cuerpo = (await cliente.get("/api/v1/hub/organizaciones")).json()[0]

        for campo in CAMPOS_DE_RAG:
            assert campo not in cuerpo, f"{campo} es de Chatbots y sigue en la identidad"

    @pytest.mark.asyncio
    async def test_should_keep_identity_in_the_identity_payload(self, db_session):
        org = await _organizacion(db_session)

        async with _cliente(db_session, _principal(org.id)) as cliente:
            cuerpo = (await cliente.get("/api/v1/hub/organizaciones")).json()[0]

        assert {"id", "name", "partner_id", "is_active", "chatbot_count"} <= set(cuerpo)

    # `test_should_not_retire_theme_config_yet` vivía aquí y sostenía la línea hasta que
    # existiera el sustituto: retirarlo antes dejaba a la organización sin forma de configurar
    # su tema. PLAT.6 dio la pantalla y **PLAT.7 retiró la columna**, así que el guardarraíl se
    # dio la vuelta y ahora comprueba que no vuelva:
    # `tests/infra/test_plat7_retirada_del_tema_en_json.py`.

    @pytest.mark.asyncio
    async def test_should_serve_every_rag_default_on_its_own_endpoint(self, db_session):
        org = await _organizacion(db_session)

        async with _cliente(db_session, _principal(org.id)) as cliente:
            cuerpo = (
                await cliente.get(
                    f"/api/v1/hub/organizaciones/{org.id}/valores-por-defecto"
                )
            ).json()

        for campo in CAMPOS_DE_RAG:
            assert campo in cuerpo, f"{campo} falta en los valores por defecto"


# ───────────────── SEC.2 sigue en pie en las dos ─────────────────


class TestElAislamientoEntreOrganizaciones:

    @pytest.mark.asyncio
    async def test_should_refuse_reading_the_defaults_of_another_organization(self, db_session):
        ajena = await _organizacion(db_session, name="Ajena")
        propia = await _organizacion(db_session, name="Propia")

        async with _cliente(db_session, _principal(propia.id)) as cliente:
            respuesta = await cliente.get(
                f"/api/v1/hub/organizaciones/{ajena.id}/valores-por-defecto"
            )

        assert respuesta.status_code == 403

    @pytest.mark.asyncio
    async def test_should_refuse_writing_the_defaults_of_another_organization(self, db_session):
        ajena = await _organizacion(db_session, name="Ajena")
        propia = await _organizacion(db_session, name="Propia")

        async with _cliente(db_session, _principal(propia.id)) as cliente:
            respuesta = await cliente.patch(
                f"/api/v1/hub/organizaciones/{ajena.id}/valores-por-defecto",
                json={"default_chunk_size": 999},
            )

        assert respuesta.status_code == 403

    @pytest.mark.asyncio
    async def test_should_let_a_superadmin_through(self, db_session):
        """El comodín de SEC.2: en un superadmin la lista vacía significa «todas»."""
        org = await _organizacion(db_session)

        async with _cliente(db_session, _principal(role="superadmin")) as cliente:
            respuesta = await cliente.get(
                f"/api/v1/hub/organizaciones/{org.id}/valores-por-defecto"
            )

        assert respuesta.status_code == 200
