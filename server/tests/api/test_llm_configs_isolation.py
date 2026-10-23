"""SEC.9.2 — Los modelos y sus proveedores, acotados a la organización que los usa.

**Dos agujeros, del mismo router** (auditoría del 2026-08-24):

1. `HubProviderOut` declaraba `api_key`, y `GET /providers` devolvía las filas tal cual. Como
   `hub_providers` es de ámbito `plataforma`, **cualquier administrador de cualquier organización
   leía en claro la clave del proveedor LLM de la plataforma** — y con `PATCH` podía cambiarla.
2. MT.2 le dio a `hub_llm_configs` su `organizacion_id`, y el router no se enteró: el listado no
   se acotaba, `create` aceptaba la organización del cuerpo sin comprobarla, y
   `update`/`delete`/`test` resolvían por id sin mirar de quién era la fila. El `test` es el peor
   de los cuatro, porque **gasta la credencial de la otra organización**.

`hub_llm_configs` es `heredable`, así que acotar no es filtrar por las organizaciones del
principal a secas: hay que traer **también** las de plataforma (`organizacion_id IS NULL`), que se
heredan. Un `scope_query_to_orgs` a pelo las esconde y deja el panel vacío — de ahí el `or_`.

Y al revés: **escribir** en el nivel de plataforma es cosa del superadministrador, porque esa fila
la hereda todo el mundo. Un administrador escribe en su organización, y si no se puede saber cuál
es, se le pregunta en vez de decidir por él.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock


from server.app.core.auth.models import UserInfo

ORG_A = str(uuid.UUID("00000000-0000-0000-0000-0000000000a1"))
ORG_B = str(uuid.UUID("00000000-0000-0000-0000-0000000000b2"))


def _admin(*orgs: str) -> UserInfo:
    return UserInfo(
        user_id="admin-1", email="a@example.org", role="admin", organizacion_ids=orgs
    )


def _superadmin() -> UserInfo:
    return UserInfo(user_id="root", email="root@example.org", role="superadmin")


def _config_de(org: str | None):
    """Doble de configuración de modelo que sólo declara de quién es."""
    return SimpleNamespace(
        id=uuid.uuid4(),
        organizacion_id=uuid.UUID(org) if org else None,
        tier=1,
        purpose="chat",
        provider="google",
        provider_rel=None,
        is_default=False,
    )


def _sesion(entidad=None, filas: list | None = None):
    session = MagicMock()
    session.get = AsyncMock(return_value=entidad)
    session.scalar = AsyncMock(return_value=entidad)
    resultado = MagicMock()
    resultado.scalars.return_value.all.return_value = filas or []
    resultado.scalars.return_value.first.return_value = None
    resultado.scalar_one_or_none = MagicMock(return_value=None)
    session.execute = AsyncMock(return_value=resultado)
    session.commit = AsyncMock()
    session.delete = AsyncMock()
    session.add = MagicMock()

    async def _refresh(obj, *_a, **_k):
        # Emula lo que hace la BD al insertar: sin esto la respuesta se valida con `id=None` y
        # el fallo parece del contrato cuando es del doble.
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()

    session.refresh = AsyncMock(side_effect=_refresh)
    return session


def _cliente(principal: UserInfo, session):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from server.app.api.deps import get_current_user, modulos_concedidos
    from server.app.api.deps import get_session
    from server.app.routers.hub_llm_configs_router import router

    async def _sesion_override():
        yield session

    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: principal
    app.dependency_overrides[get_session] = _sesion_override
    app.dependency_overrides[modulos_concedidos] = lambda: ["plataforma"]
    app.include_router(router, prefix="/api/v1")
    return TestClient(app)


def _sql_de(session) -> str:
    consulta = session.execute.await_args.args[0]
    return str(consulta.compile(compile_kwargs={"literal_binds": True}))


class TestLaClaveDelProveedorNoSale:

    def test_should_not_return_provider_api_key(self):
        proveedor = SimpleNamespace(
            id="google",
            name="Google",
            provider_type="google_genai",
            base_url=None,
            api_key="AIza-SECRETO-DE-LA-PLATAFORMA",
        )
        session = _sesion(filas=[proveedor])

        resp = _cliente(_admin(ORG_A), session).get("/api/v1/hub/llm-configs/providers")

        assert resp.status_code == 200
        assert "SECRETO" not in resp.text
        assert "api_key" not in resp.text

    def test_should_reserve_provider_writes_for_the_superadmin(self):
        """Un proveedor es de la plataforma: crearlo, cambiarlo o borrarlo afecta a todas las
        organizaciones, así que no es cosa de un administrador de una."""
        session = _sesion(entidad=SimpleNamespace(id="google", name="G"))
        cliente = _cliente(_admin(ORG_A), session)

        creado = cliente.post(
            "/api/v1/hub/llm-configs/providers",
            json={"id": "otro", "name": "Otro", "provider_type": "google_genai"},
        )
        cambiado = cliente.patch(
            "/api/v1/hub/llm-configs/providers/google", json={"api_key": "secuestrada"}
        )
        borrado = cliente.delete("/api/v1/hub/llm-configs/providers/google")

        assert creado.status_code == 403
        assert cambiado.status_code == 403
        assert borrado.status_code == 403
        session.commit.assert_not_awaited()


class TestElListadoSeAcota:

    def test_should_list_own_org_and_platform_configs(self):
        """Lo propio **y lo heredado**: `hub_llm_configs` es heredable, así que el nivel de
        plataforma (`IS NULL`) tiene que seguir viéndose."""
        session = _sesion(filas=[])

        resp = _cliente(_admin(ORG_A), session).get("/api/v1/hub/llm-configs")

        assert resp.status_code == 200
        sql = _sql_de(session)
        assert uuid.UUID(ORG_A).hex in sql
        assert uuid.UUID(ORG_B).hex not in sql
        assert "IS NULL" in sql.upper()

    def test_should_not_scope_the_listing_for_a_superadmin(self):
        session = _sesion(filas=[])
        _cliente(_superadmin(), session).get("/api/v1/hub/llm-configs")

        assert "organizacion_id IN" not in _sql_de(session)


class TestEscribirEnOtraOrganizacion:

    def test_should_forbid_create_llm_config_for_other_org(self):
        session = _sesion()
        resp = _cliente(_admin(ORG_A), session).post(
            "/api/v1/hub/llm-configs",
            json={
                "organizacion_id": ORG_B,
                "provider": "google",
                "model_name": "gemini-2.5-flash",
            },
        )

        assert resp.status_code == 403
        session.commit.assert_not_awaited()

    def test_should_reserve_platform_level_creation_for_the_superadmin(self):
        """Un administrador que no dice la organización **no** crea configuración de
        plataforma: se le asigna la suya. Nulo lo reserva el superadministrador."""
        session = _sesion()
        resp = _cliente(_admin(ORG_A), session).post(
            "/api/v1/hub/llm-configs",
            json={"provider": "google", "model_name": "gemini-2.5-flash"},
        )

        assert resp.status_code in (200, 201)
        creada = session.add.call_args.args[0]
        assert str(creada.organizacion_id) == ORG_A

    def test_should_ask_which_org_when_the_admin_manages_several(self):
        """Con varias organizaciones no hay «la suya», y elegir por él escribiría en una que
        no ha nombrado. Se pregunta: 400, no un silencio que acaba en plataforma."""
        session = _sesion()
        resp = _cliente(_admin(ORG_A, ORG_B), session).post(
            "/api/v1/hub/llm-configs",
            json={"provider": "google", "model_name": "gemini-2.5-flash"},
        )

        assert resp.status_code == 400
        session.commit.assert_not_awaited()

    def test_should_let_the_superadmin_create_a_platform_config(self):
        session = _sesion()
        resp = _cliente(_superadmin(), session).post(
            "/api/v1/hub/llm-configs",
            json={"provider": "google", "model_name": "gemini-2.5-flash"},
        )

        assert resp.status_code in (200, 201)
        creada = session.add.call_args.args[0]
        assert creada.organizacion_id is None


class TestTocarLaConfiguracionAjena:

    def test_should_forbid_update_of_other_org_config(self):
        ajena = _config_de(ORG_B)
        session = _sesion(entidad=ajena)

        resp = _cliente(_admin(ORG_A), session).patch(
            f"/api/v1/hub/llm-configs/{ajena.id}", json={"label": "Secuestrada"}
        )

        assert resp.status_code == 403
        session.commit.assert_not_awaited()

    def test_should_forbid_delete_of_other_org_config(self):
        ajena = _config_de(ORG_B)
        session = _sesion(entidad=ajena)

        resp = _cliente(_admin(ORG_A), session).delete(
            f"/api/v1/hub/llm-configs/{ajena.id}"
        )

        assert resp.status_code == 403
        session.commit.assert_not_awaited()

    def test_should_forbid_testing_a_config_of_another_org(self):
        """El más caro de los cuatro: probar la conexión **gasta la credencial** de la otra
        organización, y de paso confirma que su clave es válida."""
        ajena = _config_de(ORG_B)
        session = _sesion(entidad=ajena)

        resp = _cliente(_admin(ORG_A), session).post(
            f"/api/v1/hub/llm-configs/{ajena.id}/test"
        )

        assert resp.status_code == 403

    def test_should_forbid_a_non_superadmin_from_touching_a_platform_config(self):
        """Nulo = de la plataforma, y la hereda todo el mundo: cambiarla desde una
        organización cambia el modelo por defecto de las demás."""
        de_plataforma = _config_de(None)
        session = _sesion(entidad=de_plataforma)

        resp = _cliente(_admin(ORG_A), session).patch(
            f"/api/v1/hub/llm-configs/{de_plataforma.id}", json={"label": "Para todos"}
        )

        assert resp.status_code == 403
        session.commit.assert_not_awaited()
