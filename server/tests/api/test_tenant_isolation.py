"""GATE DE CI — Aislamiento entre organizaciones (Prompt SEC.2, hallazgo A2).

**El agujero**: el JWT no llevaba la organización y los endpoints no filtraban. Cualquier
administrador listaba, editaba y borraba los chatbots de todas las organizaciones, y leía sus
conversaciones — que en un asistente de administración pública contienen preguntas de
ciudadanos, o sea datos personales de terceros.

Este fichero es un **gate**, no una suite de cobertura: si algo de aquí se pone en rojo, hay
acceso horizontal entre organizaciones y no se despliega. Por eso las aserciones son sobre el
comportamiento observable de la frontera —403, listas filtradas, el id del token mandando
sobre el del cuerpo— y no sobre cómo esté implementada por dentro.

El último test no prueba comportamiento: recorre el código y falla si un endpoint lee una
entidad de organización sin pasar por la comprobación. Es el que evita que el agujero vuelva
por un endpoint nuevo que nadie acordó revisar.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from server.app.core.auth.models import UserInfo

# Los routers se importan aquí arriba y no dentro de cada test, aunque el resto del fichero
# use imports perezosos: `hub_chatbots_router` arrastra el chunker y, con él, pyarrow, cuya
# carga nativa revienta el proceso en Windows si ocurre a mitad de la sesión de pytest
# (`Windows fatal exception: access violation`). Importarlo en la recolección lo evita.
from server.app.api.v1.hub_chat import router as chat_router
from server.app.api.v1.hub_feedback import router as feedback_router
from server.app.routers.hub_chatbots_router import router as chatbots_router
from server.app.routers.hub_ingestion_router import router as ingestion_router
from server.app.routers.hub_themes_router import router as themes_router

ORG_A = str(uuid.UUID("00000000-0000-0000-0000-0000000000a1"))
ORG_B = str(uuid.UUID("00000000-0000-0000-0000-0000000000b2"))


def _admin(*orgs: str) -> UserInfo:
    return UserInfo(user_id="admin-1", email="a@uji.es", role="admin", organizacion_ids=orgs)


def _superadmin() -> UserInfo:
    return UserInfo(user_id="root", email="root@uji.es", role="superadmin")


def _user(org: str) -> UserInfo:
    return UserInfo(user_id="u", email="u@uji.es", role="user", organizacion_ids=(org,))


# ───────────────────────── El claim ─────────────────────────


class TestClaimDeOrganizacion:

    def test_should_carry_organizacion_ids_in_user_info(self):
        assert _admin(ORG_A).organizacion_ids == (ORG_A,)

    def test_should_treat_superadmin_empty_list_as_wildcard(self):
        """Vacío en un superadmin es «todas», no «ninguna». Es la única excepción."""
        from server.app.core.auth.tenancy import puede_acceder

        assert _superadmin().organizacion_ids == ()
        assert puede_acceder(_superadmin(), ORG_A) is True

    def test_should_treat_empty_list_as_no_access_for_a_non_superadmin(self):
        """El mismo valor significa lo contrario según el rol, y eso hay que fijarlo.

        Si «vacío = todas» se aplicara a cualquiera, un admin al que se le olvidara poblar el
        claim pasaría a verlo todo — el agujero A2 exactamente, reintroducido por un descuido.
        """
        from server.app.core.auth.tenancy import puede_acceder

        assert puede_acceder(_admin(), ORG_A) is False

    def test_should_survive_a_round_trip_through_the_jwt(self):
        from server.app.core.auth import create_token
        from server.app.core.auth.jwt_handler import decode_token

        token = create_token(_admin(ORG_A, ORG_B))
        recuperado = decode_token(token)

        assert set(recuperado.organizacion_ids) == {ORG_A, ORG_B}
        assert recuperado.role == "admin"

    def test_should_default_to_no_organizations_for_an_old_token(self):
        """Un token emitido antes de SEC.2 no trae el claim: se lee como sin acceso."""
        import jwt as pyjwt

        from server.app.core.config import get_settings
        from server.app.core.auth.jwt_handler import decode_token

        ajustes = get_settings()
        antiguo = pyjwt.encode(
            {"sub": "1", "email": "a@uji.es", "role": "admin", "exp": 9_999_999_999},
            ajustes.jwt_secret_key,
            algorithm=ajustes.jwt_algorithm,
        )
        assert decode_token(antiguo).organizacion_ids == ()


# ───────────────────────── La frontera ─────────────────────────


class TestAssertOrgAccess:

    def test_should_allow_access_to_own_org(self):
        from server.app.core.auth.tenancy import assert_org_access

        assert_org_access(_admin(ORG_A), ORG_A)  # no lanza

    def test_should_forbid_access_to_another_org(self):
        from fastapi import HTTPException

        from server.app.core.auth.tenancy import assert_org_access

        with pytest.raises(HTTPException) as exc:
            assert_org_access(_admin(ORG_A), ORG_B)
        assert exc.value.status_code == 403

    def test_should_allow_superadmin_cross_org_access(self):
        from server.app.core.auth.tenancy import assert_org_access

        assert_org_access(_superadmin(), ORG_B)  # no lanza

    def test_should_forbid_a_user_outside_its_own_org(self):
        from fastapi import HTTPException

        from server.app.core.auth.tenancy import assert_org_access

        with pytest.raises(HTTPException):
            assert_org_access(_user(ORG_A), ORG_B)

    def test_should_accept_uuid_and_string_alike(self):
        """El id llega como UUID desde el ORM y como str desde el token."""
        from server.app.core.auth.tenancy import assert_org_access

        assert_org_access(_admin(ORG_A), uuid.UUID(ORG_A))

    def test_should_forbid_when_the_entity_has_no_org(self):
        """Sin organización no se puede decidir, y no decidir es dejar pasar."""
        from fastapi import HTTPException

        from server.app.core.auth.tenancy import assert_org_access

        with pytest.raises(HTTPException):
            assert_org_access(_admin(ORG_A), None)


class TestScopeQuery:

    def test_should_filter_the_query_by_the_principals_orgs(self):
        from sqlalchemy import select

        from server.app.core.auth.tenancy import scope_query_to_orgs
        from server.app.modules.agents_hub.database.config_models import HubChatbot

        sql = str(
            scope_query_to_orgs(select(HubChatbot), _admin(ORG_A), HubChatbot)
        ).lower()
        assert "organizacion_id in" in sql.replace("\n", " ")

    def test_should_not_filter_for_superadmin(self):
        from sqlalchemy import select

        from server.app.core.auth.tenancy import scope_query_to_orgs
        from server.app.modules.agents_hub.database.config_models import HubChatbot

        original = select(HubChatbot)
        assert str(scope_query_to_orgs(original, _superadmin(), HubChatbot)) == str(original)

    def test_should_produce_an_impossible_filter_for_a_principal_without_orgs(self):
        """Un admin sin organizaciones no ve nada; nunca «no filtres»."""
        from sqlalchemy import select

        from server.app.core.auth.tenancy import scope_query_to_orgs
        from server.app.modules.agents_hub.database.config_models import HubChatbot

        sql = str(scope_query_to_orgs(select(HubChatbot), _admin(), HubChatbot)).lower()
        assert "organizacion_id in" in sql.replace("\n", " ")


# ───────────────────── La frontera vista desde fuera ─────────────────────


def _app_con(router, principal: UserInfo, session, prefijo: str = "/api/v1"):
    """App mínima con un router, la sesión doblada y el principal dado.

    Una app por test en vez de `main.app`: el gate no debería depender de que el registro
    de routers de la aplicación real siga igual mañana, ni arrastrar su middleware.
    """
    from fastapi import FastAPI

    from server.app.api.deps import get_current_user, get_current_user_optional
    from server.app.modules.agents_hub.database.connection import get_async_session

    async def _sesion():
        yield session

    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: principal
    # SEC.8.5: chat y temas admiten sesión o credencial de sitio, así que dependen de la
    # variante opcional. Se sobrescriben las dos para que el gate siga midiendo la
    # frontera de organización y no un 401 por dependencia sin doblar.
    app.dependency_overrides[get_current_user_optional] = lambda: principal
    app.dependency_overrides[get_async_session] = _sesion
    app.include_router(router, prefix=prefijo)
    return app


def _chatbot_de(org: str):
    """Doble de chatbot que solo necesita declarar de quién es."""
    from types import SimpleNamespace

    return SimpleNamespace(id=uuid.uuid4(), organizacion_id=uuid.UUID(org), name="Bot")


def _sesion_que_devuelve(entidad=None, filas: list | None = None):
    from unittest.mock import AsyncMock, MagicMock

    session = MagicMock()
    session.get = AsyncMock(return_value=entidad)
    resultado = MagicMock()
    resultado.scalars.return_value.all.return_value = filas or []
    resultado.scalar_one_or_none = MagicMock(return_value=entidad)
    session.execute = AsyncMock(return_value=resultado)
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return session


class TestLaFronteraEnLosEndpoints:
    """Los 403 tal y como los ve un cliente HTTP.

    Los tests de `assert_org_access` prueban que la regla existe; estos prueban que está
    **en el camino** de cada endpoint, que es lo que falló en A2: la regla nunca fue el
    problema, su ausencia en la ruta sí.
    """

    def test_should_list_only_own_org_chatbots(self):
        """El acotado ocurre en SQL. Se comprueba en la consulta, no en la respuesta:
        un doble de sesión devuelve lo que se le diga, así que afirmar sobre las filas
        probaría el doble y no el endpoint."""
        from fastapi.testclient import TestClient

        session = _sesion_que_devuelve(filas=[])
        cliente = TestClient(_app_con(chatbots_router, _admin(ORG_A), session))

        assert cliente.get("/api/v1/hub/chatbots").status_code == 200

        consulta = session.execute.await_args.args[0]
        # Sin guiones: así es como SQLAlchemy escribe un UUID al fijar el literal.
        sql = str(consulta.compile(compile_kwargs={"literal_binds": True}))
        assert uuid.UUID(ORG_A).hex in sql
        assert uuid.UUID(ORG_B).hex not in sql

    def test_should_not_scope_the_listing_for_a_superadmin(self):
        from fastapi.testclient import TestClient

        session = _sesion_que_devuelve(filas=[])
        cliente = TestClient(_app_con(chatbots_router, _superadmin(), session))
        cliente.get("/api/v1/hub/chatbots")

        consulta = session.execute.await_args.args[0]
        assert "organizacion_id IN" not in str(consulta)

    def test_should_forbid_get_chatbot_of_other_org(self):
        """Sobre `corpus-stats`, que es la lectura de un chatbot concreto que sí existe:
        el router no expone `GET /{chatbot_id}` a secas. Ambos pasan por
        `_get_chatbot_or_404`, así que la frontera es la misma."""
        from fastapi.testclient import TestClient

        ajeno = _chatbot_de(ORG_B)
        cliente = TestClient(
            _app_con(chatbots_router, _admin(ORG_A), _sesion_que_devuelve(ajeno))
        )

        resp = cliente.get(f"/api/v1/hub/chatbots/{ajeno.id}/corpus-stats")
        assert resp.status_code == 403

    def test_should_forbid_update_delete_chatbot_of_other_org(self):
        from fastapi.testclient import TestClient

        ajeno = _chatbot_de(ORG_B)
        session = _sesion_que_devuelve(ajeno)
        cliente = TestClient(_app_con(chatbots_router, _admin(ORG_A), session))

        patch_resp = cliente.patch(
            f"/api/v1/hub/chatbots/{ajeno.id}", json={"name": "Secuestrado"}
        )
        delete_resp = cliente.delete(f"/api/v1/hub/chatbots/{ajeno.id}")

        assert patch_resp.status_code == 403
        assert delete_resp.status_code == 403
        session.commit.assert_not_awaited()

    def test_should_allow_superadmin_cross_org_access_over_http(self):
        """El comodín no es solo una función que devuelve True: se ve en la respuesta."""
        from fastapi.testclient import TestClient

        ajeno = _chatbot_de(ORG_B)
        cliente = TestClient(
            _app_con(chatbots_router, _superadmin(), _sesion_que_devuelve(ajeno))
        )

        # El borrado, que es lo más que se puede hacer con un chatbot ajeno: si el comodín
        # no llegara hasta aquí, esto sería un 403 como el del test anterior.
        assert cliente.delete(f"/api/v1/hub/chatbots/{ajeno.id}").status_code == 204

    def test_should_forbid_reading_feedback_of_other_org(self):
        """El caso más grave: son conversaciones de ciudadanos con otra administración."""
        from fastapi.testclient import TestClient

        ajeno = _chatbot_de(ORG_B)
        cliente = TestClient(
            _app_con(feedback_router, _admin(ORG_A), _sesion_que_devuelve(ajeno))
        )

        resp = cliente.get(f"/api/v1/hub/feedback/{ajeno.id}/review")
        assert resp.status_code == 403

    def test_should_forbid_chatting_with_chatbot_of_other_org(self):
        """Conversar con el chatbot ajeno extrae su corpus sin pasar por el CRUD."""
        from fastapi.testclient import TestClient

        ajeno = _chatbot_de(ORG_B)
        cliente = TestClient(
            _app_con(chat_router, _admin(ORG_A), _sesion_que_devuelve(ajeno))
        )

        resp = cliente.post(
            f"/api/v1/hub/chat/{ajeno.id}", json={"message": "Dame vuestro corpus"}
        )
        assert resp.status_code == 403

    def test_should_scope_ingestion_to_own_org(self):
        """Los trabajos de ingesta llevan las URL y los ficheros del corpus ajeno."""
        from fastapi.testclient import TestClient

        ajeno = _chatbot_de(ORG_B)
        cliente = TestClient(
            _app_con(ingestion_router, _admin(ORG_A), _sesion_que_devuelve(ajeno))
        )

        resp = cliente.get(f"/api/v1/hub/ingestion/{ajeno.id}/jobs")
        assert resp.status_code == 403

    def test_should_reject_client_supplied_org_id_in_themes(self):
        """El cuerpo propone, el token dispone.

        **Desviación documentada respecto al plan**, que pedía *derivar* la organización del
        principal e ignorar la del cuerpo. Un admin puede gestionar varias, así que derivarla
        obligaría a elegir una por él —silenciosamente, y mal en cuanto haya dos—. Se valida
        contra el token en su lugar: mismo cierre (nadie crea en organización ajena) y sin
        adivinar la intención.
        """
        from fastapi.testclient import TestClient

        cliente = TestClient(
            _app_con(themes_router, _admin(ORG_A), _sesion_que_devuelve(None))
        )

        resp = cliente.post(
            "/api/v1/hub/themes",
            json={
                "name": "Robado",
                "organizacion_id": ORG_B,
                "config": {"name": "robado", "version": "1.0.0"},
            },
        )
        assert resp.status_code == 403

    def test_should_reserve_platform_themes_for_the_superadmin(self):
        """Un tema sin organización entra en la cascada de todas: es configuración global."""
        from fastapi.testclient import TestClient

        cliente = TestClient(
            _app_con(themes_router, _admin(ORG_A), _sesion_que_devuelve(None))
        )

        resp = cliente.post(
            "/api/v1/hub/themes",
            json={"name": "Global", "config": {"name": "global", "version": "1.0.0"}},
        )
        assert resp.status_code == 403


# ───────────── SEC.8.1 — los routers que llegaron DESPUÉS de SEC.2 ─────────────


def _entidad_de(org: str, **extra):
    """Doble que sirve a la vez de recurso y de chatbot dueño.

    La sesión doblada devuelve el mismo objeto para el `SELECT` del recurso y para el
    `session.get(HubChatbot, ...)` que hace la comprobación, así que el doble lleva los
    atributos de los dos: `chatbot_id` para poder resolver el dueño y `organizacion_id`
    para que la frontera tenga algo que comparar.
    """
    from types import SimpleNamespace

    identificador = uuid.uuid4()
    campos = {
        "id": identificador,
        "chatbot_id": uuid.uuid4(),
        "site_id": uuid.uuid4(),
        "organizacion_id": uuid.UUID(org),
        "name": "Recurso",
        "user_id": "otro-usuario",
    }
    campos.update(extra)
    return SimpleNamespace(**campos)


class TestFronteraEnLosRoutersPosterioresASEC2:
    """SEC.8.1 — el agujero que dejó el crecimiento del producto.

    SEC.2 aisló los routers que existían entonces. Todo lo que se añadió después
    —escenarios de prueba, curación, plantillas de prompt, organizaciones, exportación de
    tareas— se conformó con exigir rol de admin y nunca resolvió el recurso a su
    organización dueña. Rol no es pertenencia: un admin de la organización A es un admin
    perfectamente válido, y sin esta comprobación opera sobre los datos de la B.
    """

    def test_should_forbid_run_scenario_on_other_org_chatbot(self):
        """El más grave del grupo: ejecutar el grafo ajeno **extrae su corpus**.

        No hace falta pasar por el CRUD de chatbots ni por el chat: basta con lanzar un
        escenario de prueba contra un `chatbot_id` que no es tuyo y leer la respuesta.
        """
        from fastapi.testclient import TestClient

        from server.app.routers.hub_test_scenarios_router import router as escenarios

        ajeno = _entidad_de(ORG_B)
        cliente = TestClient(
            _app_con(escenarios, _admin(ORG_A), _sesion_que_devuelve(ajeno))
        )

        resp = cliente.post(
            f"/api/v1/hub/chatbots/{ajeno.chatbot_id}/test-scenarios/{ajeno.id}/run"
        )
        assert resp.status_code == 403

    def test_should_forbid_listing_scenarios_of_other_org_chatbot(self):
        from fastapi.testclient import TestClient

        from server.app.routers.hub_test_scenarios_router import router as escenarios

        ajeno = _entidad_de(ORG_B)
        cliente = TestClient(
            _app_con(escenarios, _admin(ORG_A), _sesion_que_devuelve(ajeno))
        )

        resp = cliente.get(f"/api/v1/hub/chatbots/{ajeno.chatbot_id}/test-scenarios")
        assert resp.status_code == 403

    def test_should_forbid_delete_of_other_org_organizacion(self):
        """Borrar una organización arrastra sus chatbots por CASCADE: es destrucción
        de datos de otra administración con un solo verbo HTTP."""
        from fastapi.testclient import TestClient

        from server.app.routers.hub_organizaciones_router import router as orgs

        session = _sesion_que_devuelve(_entidad_de(ORG_B, id=uuid.UUID(ORG_B)))
        cliente = TestClient(_app_con(orgs, _admin(ORG_A), session))

        resp = cliente.delete(f"/api/v1/hub/organizaciones/{ORG_B}")
        assert resp.status_code == 403
        session.commit.assert_not_awaited()

    def test_should_forbid_update_of_other_org_organizacion(self):
        from fastapi.testclient import TestClient

        from server.app.routers.hub_organizaciones_router import router as orgs

        session = _sesion_que_devuelve(_entidad_de(ORG_B, id=uuid.UUID(ORG_B)))
        cliente = TestClient(_app_con(orgs, _admin(ORG_A), session))

        resp = cliente.patch(
            f"/api/v1/hub/organizaciones/{ORG_B}", json={"name": "Secuestrada"}
        )
        assert resp.status_code == 403

    def test_should_scope_the_organizaciones_listing(self):
        """El listado se acota en SQL, como el de chatbots: filtrar después de leer
        traería a memoria las organizaciones ajenas igual."""
        from fastapi.testclient import TestClient

        from server.app.routers.hub_organizaciones_router import router as orgs

        session = _sesion_que_devuelve(filas=[])
        session.execute.return_value.all.return_value = []
        cliente = TestClient(_app_con(orgs, _admin(ORG_A), session))

        assert cliente.get("/api/v1/hub/organizaciones").status_code == 200

        consulta = session.execute.await_args.args[0]
        sql = str(consulta.compile(compile_kwargs={"literal_binds": True}))
        assert uuid.UUID(ORG_A).hex in sql
        assert uuid.UUID(ORG_B).hex not in sql

    def test_should_forbid_content_gap_analysis_on_other_org_chatbot(self):
        """Los huecos de corpus se calculan LEYENDO las conversaciones de ciudadanos."""
        from fastapi.testclient import TestClient

        from server.app.routers.hub_content_quality_router import router as calidad

        ajeno = _entidad_de(ORG_B)
        cliente = TestClient(
            _app_con(calidad, _admin(ORG_A), _sesion_que_devuelve(ajeno))
        )

        resp = cliente.post(
            f"/api/v1/hub/quality/gaps/analyze?chatbot_id={ajeno.chatbot_id}"
        )
        assert resp.status_code == 403

    def test_should_forbid_patching_site_of_other_org(self):
        from fastapi.testclient import TestClient

        from server.app.routers.hub_sites_router import router as sitios

        ajeno = _entidad_de(ORG_B)
        cliente = TestClient(
            _app_con(sitios, _admin(ORG_A), _sesion_que_devuelve(ajeno))
        )

        resp = cliente.patch(
            f"/api/v1/hub/sites/{ajeno.id}", json={"name": "Secuestrado"}
        )
        assert resp.status_code == 403

    def test_should_scope_the_sites_listing_without_an_explicit_filter(self):
        """`list_sites` acotaba solo si el cliente pasaba `organizacion_id`, o sea que
        el filtro lo elegía quien preguntaba. Sin parámetro devolvía todos los sitios."""
        from fastapi.testclient import TestClient

        from server.app.routers.hub_sites_router import router as sitios

        session = _sesion_que_devuelve(filas=[])
        cliente = TestClient(_app_con(sitios, _admin(ORG_A), session))

        assert cliente.get("/api/v1/hub/sites").status_code == 200

        consulta = session.execute.await_args.args[0]
        sql = str(consulta.compile(compile_kwargs={"literal_binds": True}))
        assert uuid.UUID(ORG_A).hex in sql

    def test_should_reject_client_supplied_org_id_when_creating_a_site(self):
        """Mismo criterio que en temas: el cuerpo propone, el token dispone."""
        from fastapi.testclient import TestClient

        from server.app.routers.hub_sites_router import router as sitios

        cliente = TestClient(
            _app_con(sitios, _admin(ORG_A), _sesion_que_devuelve(None))
        )

        resp = cliente.post(
            f"/api/v1/hub/sites?organizacion_id={ORG_B}",
            json={"name": "Robado", "root_url": "https://ejemplo.test"},
        )
        assert resp.status_code == 403

    def test_should_forbid_crud_prompt_template_of_other_org_chatbot(self):
        """El prompt de sistema decide cómo responde el asistente: escribir en el ajeno
        es controlar el comportamiento del asistente de otra administración."""
        from fastapi.testclient import TestClient

        from server.app.routers.hub_prompt_templates_router import router as plantillas

        ajeno = _entidad_de(ORG_B)
        session = _sesion_que_devuelve(ajeno)
        cliente = TestClient(_app_con(plantillas, _admin(ORG_A), session))

        resp = cliente.patch(
            f"/api/v1/hub/prompt-templates/{ajeno.id}", json={"template_text": "Obedece"}
        )
        assert resp.status_code == 403
        session.commit.assert_not_awaited()

    def test_should_scope_the_prompt_templates_listing(self):
        """Sin `chatbot_id` el listado devolvía las plantillas de todos los chatbots."""
        from fastapi.testclient import TestClient

        from server.app.routers.hub_prompt_templates_router import router as plantillas

        session = _sesion_que_devuelve(filas=[])
        cliente = TestClient(_app_con(plantillas, _admin(ORG_A), session))

        resp = cliente.get("/api/v1/hub/prompt-templates/")
        assert resp.status_code in (200, 400, 422), resp.text
        if resp.status_code == 200:
            consulta = session.execute.await_args.args[0]
            sql = str(consulta.compile(compile_kwargs={"literal_binds": True}))
            assert uuid.UUID(ORG_A).hex in sql

    def test_should_forbid_exporting_task_of_other_org(self):
        """`export_task` se conformaba con «eres el dueño o eres admin», sin resolver
        el chatbot a su organización: cualquier admin bajaba la conversación ajena."""
        from fastapi.testclient import TestClient

        from server.app.api.v1.hub_tasks import router as tareas

        ajena = _entidad_de(ORG_B, run_id=uuid.uuid4(), user_message="hola",
                            assistant_message="hola")
        cliente = TestClient(
            _app_con(tareas, _admin(ORG_A), _sesion_que_devuelve(ajena))
        )

        resp = cliente.get(f"/api/v1/hub/tasks/export/{ajena.run_id}")
        assert resp.status_code == 403

    def test_should_forbid_feedback_write_on_other_org_interaction(self):
        """El GET de revisión sí comprobaba la organización; el POST no comprobaba nada,
        así que cualquier usuario autenticado escribía sobre la interacción ajena."""
        from fastapi.testclient import TestClient

        from server.app.api.v1.hub_feedback import router as feedback

        ajena = _entidad_de(ORG_B)
        session = _sesion_que_devuelve(ajena)
        cliente = TestClient(_app_con(feedback, _user(ORG_A), session))

        resp = cliente.post(
            f"/api/v1/hub/feedback/{ajena.id}", json={"score": 1, "comment": "malo"}
        )
        assert resp.status_code == 403
        session.commit.assert_not_awaited()


# ───────────────────── El guardarraíl que impide la recaída ─────────────────────


class TestNingunEndpointSeSaltaLaFrontera:
    """Recorre los routers de datos de organización y exige la comprobación.

    Un test de comportamiento cubre los endpoints que existen hoy. Este cubre los que
    alguien escriba mañana, que es por donde volvería A2: nadie recuerda una regla que no
    falla cuando se incumple.
    """

    ROUTERS = (
        "hub_chatbots_router.py",
        "hub_themes_router.py",
        "hub_ingestion_router.py",
        # SEC.9.5 — este vive en `api/v1/hub_feedback.py`, no en `routers/`. El nombre estaba
        # mal escrito y el `continue` de abajo lo saltaba **en silencio**, así que llevaba desde
        # SEC.2 pareciendo vigilado sin estarlo. Ahora se resuelve en los dos directorios, y un
        # nombre que no exista pone el test en rojo en vez de desaparecer.
        "hub_feedback.py",
        # SEC.8.1 — los que llegaron después y se quedaron fuera de la capa.
        "hub_organizaciones_router.py",
        "hub_test_scenarios_router.py",
        "hub_sites_router.py",
        "hub_content_quality_router.py",
        "hub_prompt_templates_router.py",
    )

    # Los dos sitios donde viven routers. `test_router_inventory_is_walked.py` (SEC.9.5) los
    # recorre enteros; esta lista se conserva porque nombra los que manejan datos **de
    # organización**, que es una afirmación más fuerte que «tiene endpoints».
    _DIRECTORIOS = (Path("app/routers"), Path("app/api/v1"))

    def _ruta_de(self, nombre: str) -> Path | None:
        for base in self._DIRECTORIOS:
            if (base / nombre).is_file():
                return base / nombre
        return None

    def test_should_not_watch_a_router_that_does_not_exist(self):
        """Un nombre mal escrito aquí es peor que no tenerlo: parece cubierto y no lo está."""
        inexistentes = [n for n in self.ROUTERS if self._ruta_de(n) is None]
        assert inexistentes == [], f"esta lista nombra ficheros que no existen: {inexistentes}"

    def test_should_import_the_tenancy_layer_in_every_org_scoped_router(self):
        faltan = []
        for nombre in self.ROUTERS:
            ruta = self._ruta_de(nombre)
            assert ruta is not None, f"{nombre} no existe: corrige la lista"
            texto = ruta.read_text(encoding="utf-8")
            if "tenancy" not in texto:
                faltan.append(nombre)
        assert not faltan, (
            "estos routers manejan datos de organización y no pasan por la capa de "
            f"tenencia: {faltan}. Sin ella, un admin ve los datos de otra organización."
        )

    def test_should_not_reintroduce_an_unscoped_chatbot_lookup(self):
        """`_get_chatbot_or_404` es el único punto de entrada, y comprueba la organización."""
        texto = Path("app/routers/hub_chatbots_router.py").read_text(encoding="utf-8")
        assert "assert_org_access" in texto
        assert texto.count("session.get(HubChatbot") <= 1, (
            "hay más de una lectura directa de HubChatbot: la comprobación de organización "
            "vive en `_get_chatbot_or_404` y saltársela es el hallazgo A2"
        )


# ---------------------------------------------------------------------------
# Issue #11 (MT.8) — la organización elegida en la cabecera acota los listados
# ---------------------------------------------------------------------------
#
# Estos tests viven aquí y no en un fichero propio porque este módulo **ya posee esta materia**:
# tiene el andamiaje de tenencia, tiene la frontera de listados y tiene escrita la razón de por
# qué aquí se afirma sobre el SQL y no sobre las filas. `tests/api` no es paquete, así que un
# fichero nuevo obligaría a duplicar ese andamiaje, y dos copias del doble de sesión divergirán.


class TestLaOrganizacionElegidaAcotaElListado:
    """Issue #11 — la frontera está hecha; lo que falta es que la elección de la cabecera llegue.

    **Lo que NO es esto.** La frontera de datos —quién *puede* ver qué— está cerrada y es el
    invariante I5: los tests de arriba la cubren. Esto es la capa de encima: desde REV.10 la
    organización se elige **una vez** en la cabecera, y esa elección tiene que acotar lo que se
    lista.

    **Medido el 2026-09-28.** De las pantallas que listan datos de organización acotaba **una**:
    `SitesPage` de curación. Las demás no, así que un superadministrador con la organización A
    elegida seguía viendo los chatbots de B en el desplegable — y a partir de ahí sus documentos,
    sus escenarios y sus interacciones. Casi ninguna de esas pantallas lista «lo suyo»: listan
    chatbots para elegir uno, y por eso el filtro en este endpoint arregla la mayoría de una vez.

    **El patrón no se decide aquí, ya estaba elegido.** `list_sites` acepta un `organizacion_id`
    opcional, aplica primero `scope_query_to_orgs` —la tenencia, que no se negocia— y después
    `assert_org_access` más el filtro. Se copia tal cual.
    """

    def _sql(self, session) -> str:
        consulta = session.execute.await_args.args[0]
        return str(consulta.compile(compile_kwargs={"literal_binds": True}))

    def test_should_narrow_the_listing_to_the_chosen_organisation(self):
        """El caso que motiva la issue: quien ve varias tiene que poder mirar una."""
        from fastapi.testclient import TestClient

        session = _sesion_que_devuelve(filas=[])
        cliente = TestClient(_app_con(chatbots_router, _superadmin(), session))

        respuesta = cliente.get(f"/api/v1/hub/chatbots?organizacion_id={ORG_A}")

        assert respuesta.status_code == 200, respuesta.text
        assert uuid.UUID(ORG_A).hex in self._sql(session), (
            "la consulta no lleva la organización elegida: el listado saldría con los chatbots "
            "de todas, que es justo lo que el selector promete acotar"
        )

    def test_should_keep_the_filter_optional(self):
        """Opcional a propósito: hay consumidores que listan de todas las organizaciones."""
        from fastapi.testclient import TestClient

        session = _sesion_que_devuelve(filas=[])
        cliente = TestClient(_app_con(chatbots_router, _superadmin(), session))

        assert cliente.get("/api/v1/hub/chatbots").status_code == 200
        assert "organizacion_id IN" not in self._sql(session)

    def test_should_forbid_filtering_by_someone_elses_organisation(self):
        from fastapi.testclient import TestClient

        session = _sesion_que_devuelve(filas=[])
        cliente = TestClient(_app_con(chatbots_router, _admin(ORG_A), session))

        respuesta = cliente.get(f"/api/v1/hub/chatbots?organizacion_id={ORG_B}")

        assert respuesta.status_code == 403, (
            "sin esto el filtro sería una forma de pedir los chatbots de otra organización: "
            "pasar un id ajeno no puede ser una consulta legítima"
        )

    def test_should_scope_by_tenancy_with_and_without_the_filter(self):
        """`scope_query_to_orgs` va **antes** del filtro, no en su lugar."""
        from fastapi.testclient import TestClient

        session = _sesion_que_devuelve(filas=[])
        cliente = TestClient(_app_con(chatbots_router, _admin(ORG_A), session))

        cliente.get(f"/api/v1/hub/chatbots?organizacion_id={ORG_A}")
        sql = self._sql(session)

        assert uuid.UUID(ORG_A).hex in sql
        assert uuid.UUID(ORG_B).hex not in sql
