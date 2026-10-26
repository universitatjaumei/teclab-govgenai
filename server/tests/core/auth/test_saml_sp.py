"""Tests del Service Provider SAML 2.0 (AUTH.1).

Cubren la construcción de settings, el adaptador de request, la metadata del SP, el
redirect de login y el rechazo de respuestas inválidas en el ACS. El happy-path del ACS
(emisión de JWT + provisioning) se prueba en AUTH.2 (``test_saml_identity.py``).

Las fixtures SAML viven en ``conftest.py``.
"""

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient


def _build_client(saml_ctx) -> TestClient:
    """App mínima con el router SAML y get_session sobreescrito (sin BD real)."""
    from server.app.api.deps import get_session
    from server.app.routers.saml_auth_router import router

    async def _dummy_session():
        yield object()

    app = FastAPI()
    app.dependency_overrides[get_session] = _dummy_session
    app.include_router(router, prefix="/api/v1")
    return TestClient(app, base_url=saml_ctx.base_url)


# --------------------------------------------------------------------------- #
# 1. build_saml_settings                                                        #
# --------------------------------------------------------------------------- #
def test_build_saml_settings_from_env(saml_ctx):
    from server.app.core.auth.saml.settings import build_saml_settings

    settings = build_saml_settings()
    assert settings["sp"]["entityId"] == saml_ctx.sp_entity_id
    assert settings["sp"]["assertionConsumerService"]["url"] == saml_ctx.acs_url
    assert settings["idp"]["entityId"] == saml_ctx.idp_entity_id
    assert settings["idp"]["singleSignOnService"]["url"] == saml_ctx.idp_sso_url
    assert settings["idp"]["x509cert"]  # cert extraído de la metadata


def test_build_saml_settings_missing_idp_raises(saml_ctx, monkeypatch):
    from server.app.core.auth.saml.settings import (
        InvalidSamlConfigError,
        build_saml_settings,
    )

    monkeypatch.delenv("SAML_IDP_METADATA_XML", raising=False)
    monkeypatch.delenv("SAML_IDP_METADATA_URL", raising=False)
    with pytest.raises(InvalidSamlConfigError):
        build_saml_settings()


def test_build_saml_settings_sp_only_skips_idp(saml_ctx, monkeypatch):
    from server.app.core.auth.saml.settings import build_saml_settings

    monkeypatch.delenv("SAML_IDP_METADATA_XML", raising=False)
    settings = build_saml_settings(sp_only=True)
    assert settings["sp"]["entityId"] == saml_ctx.sp_entity_id


# --------------------------------------------------------------------------- #
# 2. prepare_saml_request                                                       #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_prepare_saml_request_maps_fields():
    from server.app.core.auth.saml.request_adapter import prepare_saml_request

    class _FakeURL:
        scheme = "https"
        hostname = "govgenai.uji.es"
        port = None
        path = "/api/v1/auth/saml/acs"

    class _FakeRequest:
        method = "POST"
        url = _FakeURL()
        headers = {"host": "govgenai.uji.es"}
        query_params = {}

        async def form(self):
            return {"SAMLResponse": "abc"}

    req = await prepare_saml_request(_FakeRequest())
    assert req["https"] == "on"
    assert req["http_host"] == "govgenai.uji.es"
    assert req["script_name"] == "/api/v1/auth/saml/acs"
    assert req["post_data"]["SAMLResponse"] == "abc"


# --------------------------------------------------------------------------- #
# 3. /metadata                                                                  #
# --------------------------------------------------------------------------- #
def test_metadata_endpoint_returns_valid_xml(saml_ctx):
    client = _build_client(saml_ctx)
    resp = client.get("/api/v1/auth/saml/metadata")
    assert resp.status_code == 200
    assert "application/xml" in resp.headers["content-type"]
    assert "EntityDescriptor" in resp.text
    assert saml_ctx.sp_entity_id in resp.text


# --------------------------------------------------------------------------- #
# 4. /login                                                                     #
# --------------------------------------------------------------------------- #
def test_login_redirects_to_idp_with_samlrequest(saml_ctx):
    client = _build_client(saml_ctx)
    resp = client.get("/api/v1/auth/saml/login", follow_redirects=False)
    assert resp.status_code == 302
    location = resp.headers["location"]
    assert location.startswith(saml_ctx.idp_sso_url)
    assert "SAMLRequest=" in location


# --------------------------------------------------------------------------- #
# 5. /acs — rechazos de validación                                              #
# --------------------------------------------------------------------------- #
def test_acs_tampered_signature_rejected(saml_ctx):
    # Firmado con OTRA clave/cert que NO está en la metadata del IdP de pruebas.
    other_key, other_cert = saml_ctx.gen_keypair()
    saml_response = saml_ctx.make_response(
        sign_key_pem=other_key, sign_cert_pem=other_cert, email="mallory@uji.es"
    )
    client = _build_client(saml_ctx)
    resp = client.post("/api/v1/auth/saml/acs", data={"SAMLResponse": saml_response})
    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "SAML_VALIDATION_FAILED"


def test_acs_validation_errors_do_not_reach_the_client(saml_ctx, monkeypatch):
    """#276 — el motivo de python3-saml puede llevar trozos de la aserción: va al registro.

    La rama del `except` ya lo hacía; la de `get_errors()`, a unas líneas, lo seguía mandando al
    navegador, y el normalizador convertía `reason` en el `message` que se pinta.
    """
    from onelogin.saml2.auth import OneLogin_Saml2_Auth

    monkeypatch.setattr(OneLogin_Saml2_Auth, "process_response", lambda self, request_id=None: None)
    monkeypatch.setattr(OneLogin_Saml2_Auth, "get_errors", lambda self: ["invalid_response"])
    monkeypatch.setattr(
        OneLogin_Saml2_Auth, "get_last_error_reason", lambda self: "<saml:Assertion>secreto</saml:Assertion>"
    )
    client = _build_client(saml_ctx)
    resp = client.post("/api/v1/auth/saml/acs", data={"SAMLResponse": "x"})
    assert resp.status_code == 401
    cuerpo = resp.text
    assert "secreto" not in cuerpo
    assert "invalid_response" not in cuerpo
    assert resp.json()["detail"]["code"] == "SAML_VALIDATION_FAILED"


def test_acs_expired_assertion_rejected(saml_ctx):
    saml_response = saml_ctx.make_response(not_before_off=-1200, not_after_off=-600)
    client = _build_client(saml_ctx)
    resp = client.post("/api/v1/auth/saml/acs", data={"SAMLResponse": saml_response})
    assert resp.status_code == 401


def test_acs_wrong_audience_rejected(saml_ctx):
    saml_response = saml_ctx.make_response(audience="https://attacker.example/sp")
    client = _build_client(saml_ctx)
    resp = client.post("/api/v1/auth/saml/acs", data={"SAMLResponse": saml_response})
    assert resp.status_code == 401


# --------------------------------------------------------------------------- #
# 6. Feature flag                                                               #
# --------------------------------------------------------------------------- #
def test_endpoints_404_when_saml_disabled(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key-at-least-32-characters-long")
    monkeypatch.setenv("SAML_ENABLED", "false")
    from server.app.api.deps import get_session
    from server.app.routers.saml_auth_router import router

    async def _dummy_session():
        yield object()

    app = FastAPI()
    app.dependency_overrides[get_session] = _dummy_session
    app.include_router(router, prefix="/api/v1")
    c = TestClient(app, base_url="http://sp.example.com")
    assert c.get("/api/v1/auth/saml/metadata").status_code == 404
    assert c.get("/api/v1/auth/saml/login", follow_redirects=False).status_code == 404
