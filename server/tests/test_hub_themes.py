"""Tests para el sistema de temas (hub_themes_router)."""
import pytest


from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from server.app.core.auth.models import UserInfo
from server.app.api.deps import get_current_user

# SEC.2: el chat y la ingesta exigen que el principal gestione la organizacion del
# chatbot. Estos tests prueban otra cosa, asi que doble y token comparten organizacion;
# la tenencia tiene su propio gate en `tests/api/test_tenant_isolation.py`.
ORG_PRUEBA = "00000000-0000-0000-0000-00000000dead"


@pytest.fixture
def sample_theme_config():
    return {
        "name": "test-theme",
        "version": "1.0.0",
        "colors": {
            "primary": "#ff0000",
            "primaryHover": "#cc0000",
            "primaryLight": "#ffcccc",
            "secondary": "#00ff00",
            "background": "#ffffff",
            "surface": "#f0f0f0",
            "text": "#000000",
            "textSecondary": "#666666",
            "border": "#cccccc",
            "error": "#ff0000",
            "success": "#00ff00",
            "warning": "#ffff00",
            "botMessage": "#e0e0e0",
            "botMessageText": "#000000",
            "userMessage": "#0066cc",
            "userMessageText": "#ffffff",
        },
        "typography": {
            "fontFamily": "'Arial', sans-serif",
            "fontSize": "16px",
            "fontSizeSmall": "14px",
            "fontSizeLarge": "18px",
            "fontWeight": 400,
            "fontWeightBold": 700,
            "lineHeight": 1.6,
        },
        "spacing": {
            "xs": "4px",
            "sm": "8px",
            "md": "16px",
            "lg": "24px",
            "xl": "32px",
        },
    }


@pytest.fixture
def test_app():
    from server.app.routers.hub_themes_router import router
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    return app


class TestThemeValidation:
    """Tests para validación del modelo ThemeConfig."""

    def test_valid_theme_passes_validation(self, sample_theme_config):
        from server.app.routers.hub_themes_router import ThemeConfig

        theme = ThemeConfig(**sample_theme_config)
        assert theme.name == "test-theme"
        assert theme.colors.primary == "#ff0000"

    def test_invalid_theme_name_fails(self):
        from server.app.routers.hub_themes_router import ThemeConfig
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ThemeConfig(name="", version="1.0.0")

    def test_extra_fields_allowed(self, sample_theme_config):
        from server.app.routers.hub_themes_router import ThemeConfig

        sample_theme_config["customField"] = "custom-value"
        theme = ThemeConfig(**sample_theme_config)
        assert theme.name == "test-theme"


class TestThemeAPI:
    """Tests de integración para los endpoints de la API de temas."""

    @pytest.mark.asyncio
    async def test_get_presets(self, test_app):
        async with AsyncClient(
            transport=ASGITransport(app=test_app), base_url="http://test"
        ) as client:
            response = await client.get("/api/v1/hub/themes/presets")

        assert response.status_code == 200
        presets = response.json()
        assert len(presets) >= 3
        preset_names = [p["name"] for p in presets]
        assert "default" in preset_names
        assert "dark" in preset_names

    @pytest.mark.asyncio
    async def test_create_theme_requires_auth(self, test_app, sample_theme_config):
        async with AsyncClient(
            transport=ASGITransport(app=test_app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/hub/themes",
                json={
                            "name": "new-theme",
                            "config": sample_theme_config,
                            # SEC.2: un tema sin organizacion es de plataforma y solo
                            # lo crea un superadmin. Este test crea uno de organizacion.
                            "organizacion_id": ORG_PRUEBA,
                        },
            )

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_create_theme_success(self, test_app, sample_theme_config, tmp_path):
        def mock_user():
            return UserInfo(user_id="test-user", email="test@example.com", role="admin", organizacion_ids=(ORG_PRUEBA,))

        test_app.dependency_overrides[get_current_user] = mock_user

        # SEC.8.6: el tema se escribe en la BD, no en `THEMES_DIR`, así que lo que hay
        # que doblar es la sesión.
        from unittest.mock import AsyncMock, MagicMock

        from server.app.api.deps import get_session

        sesion = MagicMock()
        sesion.add = MagicMock()
        sesion.commit = AsyncMock()
        sesion.refresh = AsyncMock()

        async def _sesion():
            yield sesion

        test_app.dependency_overrides[get_session] = _sesion

        try:
            async with AsyncClient(
                transport=ASGITransport(app=test_app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/v1/hub/themes",
                    json={
                        "name": "new-theme",
                        "config": sample_theme_config,
                        # SEC.2: un tema sin organizacion es de plataforma y solo
                        # lo crea un superadmin. Este test crea uno de organizacion.
                        "organizacion_id": ORG_PRUEBA,
                    },
                )
        finally:
            test_app.dependency_overrides.clear()

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "new-theme"
        assert "id" in data


# SEC.8.6: `TestThemeStorage` probaba `_save_theme`/`_load_theme` sobre ficheros con
# `THEMES_DIR` parcheado a un `tmp_path`. Ese almacén ya no existe —los temas son filas—, y
# la persistencia se prueba ahora contra Postgres real en
# `tests/modules/agents_hub/integration/test_theme_persistence.py`, que es donde puede
# comprobarse de verdad. Probarlo con un directorio temporal era, precisamente, la razón por
# la que el fallo de Cloud Run no lo cazaba ningún test: en el test siempre había disco.
