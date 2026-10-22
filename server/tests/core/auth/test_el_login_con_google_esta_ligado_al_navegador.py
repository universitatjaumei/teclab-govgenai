"""El `state` del login con Google vale sólo en el navegador que empezó el login.

El `state` era un JWT firmado que sólo probaba «lo emitimos nosotros hace menos de diez
minutos»: no estaba ligado a nadie. Cualquiera podía pedir uno en `/login`, completar el login
con **su** cuenta y mandar a otra persona el enlace de vuelta con su `code` y ese `state`: la
víctima acababa con la sesión del atacante (*login CSRF*). Y el `nonce` del `state` no se
enviaba a Google ni se comprobaba en el ID token.

Ahora `/login` deja una cookie aleatoria `HttpOnly` y `SameSite=Lax` cuya huella va dentro del
`state`, y la vuelta sólo se acepta con esa cookie. El `nonce` viaja a Google y tiene que volver
en el ID token.
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("TESTING", "1")

_LOGIN = "/api/v1/auth/google/login"
_CALLBACK = "/api/v1/auth/google/callback"
_COOKIE = "govgenai_google_vinculo"

_CLAIMS_BUENAS = {
    "email": "persona@uji.es",
    "email_verified": True,
    "hd": "uji.es",
    "name": "Una Persona",
    "sub": "1234567890",
}


@pytest.fixture
def configurado(monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "cliente-de-prueba.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "secreto-de-prueba")
    monkeypatch.setenv("GOOGLE_OAUTH_ALLOWED_DOMAIN", "uji.es")
    monkeypatch.setenv("GOOGLE_OAUTH_REDIRECT_URI", "https://normativa.uji.es/api/v1/auth/google/callback")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key-at-least-32-characters-long")


def _cliente() -> TestClient:
    from server.app.main import app

    return TestClient(app, raise_server_exceptions=False)


def _empezar(cliente) -> tuple[str, str]:
    """`(state, nonce)` del login, dejando la cookie en `cliente`."""
    resp = cliente.get(_LOGIN, follow_redirects=False)
    q = parse_qs(urlparse(resp.headers["location"]).query)
    return q["state"][0], q.get("nonce", [""])[0]


def _con_claims(claims: dict):
    return patch("server.app.core.auth.google_oidc.canjear_codigo", new=AsyncMock(return_value=claims))


class TestElInicioLigaElNavegador:

    def test_should_set_an_httponly_lax_cookie(self, configurado):
        resp = _cliente().get(_LOGIN, follow_redirects=False)

        cabecera = resp.headers.get("set-cookie", "")
        assert cabecera.startswith(f"{_COOKIE}="), cabecera
        assert "httponly" in cabecera.lower()
        assert "samesite=lax" in cabecera.lower()

    def test_should_send_the_nonce_to_google(self, configurado):
        state, nonce = _empezar(_cliente())

        assert nonce, "Google no recibe `nonce`, así que no lo puede devolver en el ID token"
        assert pyjwt.decode(state, options={"verify_signature": False})["nonce"] == nonce


class TestLaVueltaSinElNavegadorNoVale:

    def test_should_refuse_a_valid_state_from_another_browser(self, configurado):
        """El caso del ataque: el `state` es bueno, pero lo empezó otro."""
        state, nonce = _empezar(_cliente())
        otro = _cliente()

        with _con_claims({**_CLAIMS_BUENAS, "nonce": nonce}):
            resp = otro.get(_CALLBACK, params={"code": "x", "state": state}, follow_redirects=False)

        assert resp.status_code == 400, resp.status_code
        assert "token" not in resp.headers.get("location", "")


class TestElNonceTieneQueVolver:

    @pytest.mark.parametrize("nonce_devuelto", ["otro", None], ids=["distinto", "ausente"])
    def test_should_refuse_an_id_token_without_our_nonce(self, configurado, nonce_devuelto):
        cliente = _cliente()
        state, _ = _empezar(cliente)
        claims = dict(_CLAIMS_BUENAS)
        if nonce_devuelto:
            claims["nonce"] = nonce_devuelto

        with _con_claims(claims):
            resp = cliente.get(_CALLBACK, params={"code": "x", "state": state}, follow_redirects=False)

        assert resp.status_code == 401, resp.status_code
