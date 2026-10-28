"""Tests TDD para el router de LLM configs (Prompt 9E.1).

Deploy: cloud
"""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.app.modules.agents_hub.database.config_models import HubChatbot, HubLLMConfig
from server.app.api.deps import get_session
from server.tests.dobles import modelo_de_chat

_JWT_ENV = {
    "JWT_SECRET_KEY": "test-secret-key-that-is-at-least-32-characters-long",
    "JWT_ALGORITHM": "HS256",
    "JWT_EXPIRATION_MINUTES": "60",
}


def _make_token(role: str = "superadmin") -> str:
    """SEC.9.2 — el rol por omisión pasa a superadministrador.

    Estos tests manejan configuración **de plataforma** (`organizacion_id=None`), que es la que
    heredan todas las organizaciones. Desde SEC.9.2 escribir ahí es del superadministrador: un
    administrador que no nombra organización escribe en la suya, y con un claim vacío —como
    tenía esta fixture— no hay «la suya», así que recibe un 400 pidiéndosela.

    El aislamiento por organización de este router lo cubre
    `tests/api/test_llm_configs_isolation.py`; aquí se prueba el CRUD y el relevo de defectos.
    """
    import os
    os.environ.update(_JWT_ENV)
    from server.app.core.auth import UserInfo, create_token
    return create_token(UserInfo(user_id="root-1", email="root@test.com", role=role))


def _make_config(**kwargs) -> HubLLMConfig:
    defaults = dict(
        id=uuid.uuid4(),
        provider="google",
        model_name="gemini-2.0-flash",
        temperature=0.1,
        top_p=1.0,
        max_tokens=12000,
        api_key_secret_name=None,
        tier=1,
        label="Flash",
        is_default=True,
        purpose="chat",  # MOD.1: la tabla ya no es implicitamente de chat
        output_dimensionality=None,
        # MT.2 — nulo = de la plataforma. Hay que asignarlo aunque el doble lleve `spec`: el
        # `spec` protege de nombrar un atributo que no existe, no de olvidarse de darle valor
        # a uno que sí — y sin valor devuelve un MagicMock, que revienta la validación de la
        # respuesta con un `uuid_type` difícil de leer.
        organizacion_id=None,
    )
    defaults.update(kwargs)
    m = MagicMock(spec=HubLLMConfig)
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


def _build_app(session_mock) -> FastAPI:
    from server.app.routers.hub_llm_configs_router import router

    async def _override():
        yield session_mock

    app = FastAPI()
    app.dependency_overrides[get_session] = _override
    app.include_router(router, prefix="/api/v1")
    return app


class TestLLMConfigsRouter:

    def test_should_list_llm_configs(self):
        cfg = _make_config()
        session = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = [cfg]
        session.execute = AsyncMock(return_value=result)

        client = TestClient(_build_app(session))
        resp = client.get(
            "/api/v1/hub/llm-configs",
            headers={"Authorization": f"Bearer {_make_token()}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["label"] == "Flash"

    def test_should_create_llm_config_with_tier(self):
        session = AsyncMock()
        # No existing default for tier 1
        no_default = MagicMock()
        no_default.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=no_default)
        session.add = MagicMock()
        session.commit = AsyncMock()
        session.refresh = AsyncMock(side_effect=lambda obj: setattr(obj, "id", uuid.uuid4()))

        client = TestClient(_build_app(session))
        resp = client.post(
            "/api/v1/hub/llm-configs",
            json={
                "provider": "openai",
                "model_name": "gpt-4o-mini",
                "tier": 1,
                "label": "Mini",
                "is_default": True,
            },
            headers={"Authorization": f"Bearer {_make_token()}"},
        )
        assert resp.status_code == 201

    def test_should_relieve_the_previous_default_for_same_tier(self):
        """FIX.1 cambió el contrato: promover releva a la anterior, ya no da 409.

        El 409 convertía «quiero que esta sea la de por defecto» en dos peticiones y,
        entre la una y la otra, un momento sin ninguna. En la BD de desarrollo llegaron
        a convivir dos configuraciones tier 1 marcadas por defecto.
        """
        existing = _make_config(id=uuid.uuid4(), tier=1, is_default=True)
        session = AsyncMock()
        dup_result = MagicMock()
        dup_result.scalar_one_or_none.return_value = existing
        dup_result.scalars.return_value.all.return_value = [existing]
        session.execute = AsyncMock(return_value=dup_result)
        # La BD asigna el id al hacer flush; sin esto el 500 de validacion de respuesta
        # taparia lo que este test comprueba.
        session.refresh = AsyncMock(
            side_effect=lambda obj: setattr(obj, "id", uuid.uuid4())
        )

        client = TestClient(_build_app(session))
        resp = client.post(
            "/api/v1/hub/llm-configs",
            json={
                "provider": "openai",
                "model_name": "gpt-4o",
                "tier": 1,
                "label": "GPT",
                "is_default": True,
            },
            headers={"Authorization": f"Bearer {_make_token()}"},
        )
        assert resp.status_code == 201, resp.text
        assert existing.is_default is False

    def test_should_delete_config_not_in_use(self):
        cfg = _make_config()
        session = AsyncMock()
        session.get = AsyncMock(return_value=cfg)
        # No chatbots use this config
        no_chatbots = MagicMock()
        no_chatbots.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=no_chatbots)
        session.delete = AsyncMock()
        session.commit = AsyncMock()

        client = TestClient(_build_app(session))
        resp = client.delete(
            f"/api/v1/hub/llm-configs/{cfg.id}",
            headers={"Authorization": f"Bearer {_make_token()}"},
        )
        assert resp.status_code == 204

    def test_should_block_delete_config_in_use(self):
        cfg = _make_config()
        chatbot = MagicMock(spec=HubChatbot)
        session = AsyncMock()
        session.get = AsyncMock(return_value=cfg)
        in_use = MagicMock()
        in_use.scalar_one_or_none.return_value = chatbot
        session.execute = AsyncMock(return_value=in_use)

        client = TestClient(_build_app(session))
        resp = client.delete(
            f"/api/v1/hub/llm-configs/{cfg.id}",
            headers={"Authorization": f"Bearer {_make_token()}"},
        )
        assert resp.status_code == 409

    def test_should_return_latency_on_test_connection(self):
        cfg = _make_config()
        session = AsyncMock()
        session.scalar = AsyncMock(return_value=cfg)

        mock_llm = modelo_de_chat()
        mock_llm.ainvoke = AsyncMock(return_value=MagicMock(content="ok"))

        with patch(
            "server.app.routers.hub_llm_configs_router._build_model",
            return_value=mock_llm,
        ):
            client = TestClient(_build_app(session))
            resp = client.post(
                f"/api/v1/hub/llm-configs/{cfg.id}/test",
                headers={"Authorization": f"Bearer {_make_token()}"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "latency_ms" in body

    def test_should_get_model_for_tier_returns_default(self):
        import os
        os.environ.update(_JWT_ENV)
        from server.app.modules.agents_hub.services.model_factory import get_model_for_tier

        cfg = _make_config(tier=1, is_default=True)
        config_provider = AsyncMock()
        config_provider.get_llm_config_for_tier = AsyncMock(return_value=cfg)

        # `asyncio.run` y no `get_event_loop().run_until_complete()`: el segundo reutiliza
        # el bucle que haya dejado el test anterior, así que este test pasaba o fallaba
        # según lo que se hubiera ejecutado antes en el mismo proceso. Lo destapó un test
        # nuevo que usa `asyncio.gather` con su propio motor; el fallo era de aquí, no de
        # allí. Es la clase de acoplamiento invisible que TST.1 vino a perseguir.
        import asyncio
        with patch(
            "server.app.modules.agents_hub.services.model_factory._build_model",
            return_value=MagicMock(),
        ) as mock_build:
            asyncio.run(get_model_for_tier(1, config_provider, organizacion_id=None))
            mock_build.assert_called_once_with(cfg)
