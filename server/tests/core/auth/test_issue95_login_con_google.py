"""Entrar con la cuenta institucional de Google, y sólo con ella (issue #95).

**Lo que este fichero protege es una decisión de autorización, no una comodidad.** Sin comprobar
el *claim* `hd` en el servidor, **cualquier cuenta de Google del mundo entra**: es el fallo
clásico de esta integración, y convierte un login en una puerta abierta.

La comprobación va en el servidor **aunque** la pantalla de consentimiento de Google esté en
«Interna». Eso es configuración de una consola que alguien puede cambiar, y una decisión de
autorización no se delega a una casilla — es la misma regla que el hallazgo A1 dejó en
`login_admin`: no basta con que el correo exista.

**Y el dominio no se lee del correo.** Se lee de `hd`. El test
`test_un_correo_de_uji_con_otro_dominio_de_organizacion_no_entra` es el que caza la
implementación perezosa: comprobar que el correo termina en `@uji.es` **no** es comprobar que la
cuenta pertenece a la organización.

**Apagado significa 404, no 403.** Es la convención que ya usa `/user/login`: un 403 confirmaría
que la ruta está ahí, apagada, y eso es información que no hace falta dar.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("TESTING", "1")

_LOGIN = "/api/v1/auth/google/login"
_CALLBACK = "/api/v1/auth/google/callback"

#: Lo que devolvería Google para una cuenta buena de la organización.
_CLAIMS_BUENAS = {
    "email": "persona@uji.es",
    "email_verified": True,
    "hd": "uji.es",
    "name": "Una Persona",
    "sub": "1234567890",
}


@pytest.fixture
def cliente():
    from server.app.main import app

    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def configurado(monkeypatch):
    """Las tres piezas puestas, que es lo que enciende el login.

    Con `monkeypatch.setenv`, como el resto de los tests de autenticación de este directorio:
    `get_settings()` **no cachea** —lee el entorno en cada llamada—, así que no hay nada que
    invalidar y deshacerlo a mano sería reinventar el `monkeypatch`.
    """
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "cliente-de-prueba.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "secreto-de-prueba")
    monkeypatch.setenv("GOOGLE_OAUTH_ALLOWED_DOMAIN", "uji.es")
    monkeypatch.setenv(
        "GOOGLE_OAUTH_REDIRECT_URI", "https://normativa.uji.es/api/v1/auth/google/callback"
    )
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key-at-least-32-characters-long")


@pytest.fixture
def sin_configurar(monkeypatch):
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("GOOGLE_OAUTH_ALLOWED_DOMAIN", raising=False)
    monkeypatch.delenv("GOOGLE_OAUTH_REDIRECT_URI", raising=False)


class TestSinConfigurar:
    def test_la_ruta_no_existe_si_el_login_no_esta_configurado(
        self, cliente, sin_configurar
    ) -> None:
        """404 y no 403: un 403 confirmaría que está ahí, apagada."""
        assert cliente.get(_LOGIN, follow_redirects=False).status_code == 404


class TestElInicio:
    def test_lleva_a_google_con_lo_que_google_necesita(self, cliente, configurado) -> None:
        resp = cliente.get(_LOGIN, follow_redirects=False)

        assert resp.status_code in (302, 307), resp.status_code
        destino = urlparse(resp.headers["location"])
        assert destino.netloc.endswith("google.com"), destino.netloc

        q = parse_qs(destino.query)
        assert q["response_type"] == ["code"], "flujo de código de autorización, no implícito"
        assert q["client_id"] == ["cliente-de-prueba.apps.googleusercontent.com"]
        # **El declarado, tal cual.** No se compara el final sino el valor entero: Google
        # exige coincidencia carácter a carácter, y derivarlo daría `http://` porque esta
        # aplicación no honra las cabeceras del proxy.
        assert q["redirect_uri"] == [
            "https://normativa.uji.es/api/v1/auth/google/callback"
        ], q["redirect_uri"]
        for ambito in ("openid", "email", "profile"):
            assert ambito in q["scope"][0], f"falta el ámbito {ambito}"
        assert q["state"][0], "sin `state` no hay defensa contra CSRF"
        # Pista para que Google enseñe directamente las cuentas de la organización. Es una
        # comodidad, **no** la autorización: ésa se comprueba en la callback.
        assert q.get("hd") == ["uji.es"]

    def test_no_pide_ningun_ambito_mas(self, cliente, configurado) -> None:
        """Cualquier ámbito sensible cambiaría el régimen de verificación de Google.

        No necesitamos nada de Google salvo la identidad, y pedir de más es pedir permiso para
        algo que no vamos a usar.
        """
        q = parse_qs(urlparse(cliente.get(_LOGIN, follow_redirects=False).headers["location"]).query)
        assert sorted(q["scope"][0].split()) == ["email", "openid", "profile"]


def _con_claims(claims: dict):
    """Sustituye el canje del código por unas claims dadas.

    El canje es el único trozo que habla con Google, así que es la costura: los tests no salen
    a la red y la comprobación del dominio se prueba de verdad.
    """
    return patch(
        "server.app.core.auth.google_oidc.canjear_codigo",
        new=AsyncMock(return_value=claims),
    )


def _state_valido(cliente) -> str:
    resp = cliente.get(_LOGIN, follow_redirects=False)
    return parse_qs(urlparse(resp.headers["location"]).query)["state"][0]


def _con_nonce(claims: dict, state: str) -> dict:
    """Las claims con el `nonce` de este login, que el ID token tiene que devolver.

    Sin él la vuelta se rechaza antes de mirar el dominio, y estos tests dejarían de probar el
    dominio para probar el `nonce` (`test_el_login_con_google_esta_ligado_al_navegador.py`).
    """
    import jwt as pyjwt

    return {**claims, "nonce": pyjwt.decode(state, options={"verify_signature": False})["nonce"]}


class TestElDominioEsLaAutorizacion:
    def test_una_cuenta_de_otro_dominio_no_entra(self, cliente, configurado) -> None:
        """El caso que, sin la comprobación, deja entrar a cualquiera."""
        state = _state_valido(cliente)
        ajenas = {**_CLAIMS_BUENAS, "email": "cualquiera@gmail.com", "hd": "gmail.com"}

        with _con_claims(_con_nonce(ajenas, state)):
            resp = cliente.get(
                _CALLBACK, params={"code": "x", "state": state}, follow_redirects=False
            )

        assert resp.status_code == 403, resp.status_code
        assert "token" not in resp.headers.get("location", "")

    def test_una_cuenta_sin_hd_no_entra(self, cliente, configurado) -> None:
        """Una cuenta personal de Google no trae `hd`. Ausente es rechazo, no «cualquiera»."""
        state = _state_valido(cliente)
        sin_hd = {k: v for k, v in _CLAIMS_BUENAS.items() if k != "hd"}

        with _con_claims(_con_nonce(sin_hd, state)):
            resp = cliente.get(
                _CALLBACK, params={"code": "x", "state": state}, follow_redirects=False
            )

        assert resp.status_code == 403, resp.status_code

    def test_un_correo_de_uji_con_otro_dominio_de_organizacion_no_entra(
        self, cliente, configurado
    ) -> None:
        """**El test que caza la implementación perezosa.**

        Si el código comprueba «el correo termina en @uji.es» en vez de `hd`, esto pasa y no
        debería: el correo de una cuenta puede terminar en el dominio sin que la cuenta
        pertenezca a la organización.
        """
        state = _state_valido(cliente)
        disfrazada = {**_CLAIMS_BUENAS, "email": "persona@uji.es", "hd": "otra-org.example"}

        with _con_claims(_con_nonce(disfrazada, state)):
            resp = cliente.get(
                _CALLBACK, params={"code": "x", "state": state}, follow_redirects=False
            )

        assert resp.status_code == 403, (
            "ha entrado una cuenta cuyo dominio de organización no es el nuestro: la "
            "comprobación está mirando el correo y no `hd`"
        )

    def test_un_correo_sin_verificar_no_entra(self, cliente, configurado) -> None:
        state = _state_valido(cliente)

        with _con_claims(_con_nonce({**_CLAIMS_BUENAS, "email_verified": False}, state)):
            resp = cliente.get(
                _CALLBACK, params={"code": "x", "state": state}, follow_redirects=False
            )

        assert resp.status_code == 403, resp.status_code


class TestElState:
    def test_un_state_que_no_cuadra_no_emite_token(self, cliente, configurado) -> None:
        with _con_claims(_CLAIMS_BUENAS):
            resp = cliente.get(
                _CALLBACK,
                params={"code": "x", "state": "inventado"},
                follow_redirects=False,
            )

        assert resp.status_code in (400, 403), resp.status_code

    def test_sin_state_tampoco(self, cliente, configurado) -> None:
        with _con_claims(_CLAIMS_BUENAS):
            resp = cliente.get(_CALLBACK, params={"code": "x"}, follow_redirects=False)

        assert resp.status_code in (400, 403, 422), resp.status_code


class TestElTokenEsParaEsteCliente:
    """`aud` e `iss`, comprobados **porque** la firma no se verifica.

    Lo señaló la revisión automática de la PR #101, y su diagnóstico era **falso**: decía que
    PyJWT rechazaría el token por no pasar `audience`, y que eso rompería producción. Medido con
    PyJWT 2.14.0: con `verify_signature` en `False`, PyJWT **apaga también** el resto de
    comprobaciones, así que decodificaba sin levantar. El login habría funcionado.

    Pero el remedio que proponía es correcto por otra razón. Si la exención de la firma se apoya
    en «este token vino de Google para nosotros», comprobar que el propio token lo dice es barato
    y cierra el hueco de que algún día llegue por otra vía. En el camino bueno no puede fallar:
    Google pone nuestro `client_id` en `aud` por construcción.
    """

    _CLIENTE = "cliente-de-prueba.apps.googleusercontent.com"

    def _token(self, **cambios) -> str:
        import jwt as pyjwt

        claims = {
            "aud": self._CLIENTE,
            "iss": "https://accounts.google.com",
            "email": "persona@uji.es",
            "email_verified": True,
            "hd": "uji.es",
            **cambios,
        }
        return pyjwt.encode(claims, "una-clave-de-al-menos-32-caracteres-para-hs256", algorithm="HS256")

    def test_un_token_para_otro_cliente_no_vale(self) -> None:
        from server.app.core.auth.google_oidc import ErrorDeIdentidad, claims_del_id_token

        with pytest.raises(ErrorDeIdentidad):
            claims_del_id_token(self._token(aud="otro-cliente"), client_id=self._CLIENTE)

    def test_un_token_de_otro_emisor_no_vale(self) -> None:
        from server.app.core.auth.google_oidc import ErrorDeIdentidad, claims_del_id_token

        with pytest.raises(ErrorDeIdentidad):
            claims_del_id_token(
                self._token(iss="https://accounts.example.org"), client_id=self._CLIENTE
            )

    def test_los_dos_emisores_de_google_valen(self) -> None:
        """Google emite `iss` con y sin esquema. Fijar sólo uno rechazaría tokens buenos."""
        from server.app.core.auth.google_oidc import claims_del_id_token

        for emisor in ("https://accounts.google.com", "accounts.google.com"):
            claims = claims_del_id_token(self._token(iss=emisor), client_id=self._CLIENTE)
            assert claims["email"] == "persona@uji.es"

    def test_el_camino_bueno_pasa(self) -> None:
        from server.app.core.auth.google_oidc import claims_del_id_token

        claims = claims_del_id_token(self._token(), client_id=self._CLIENTE)
        assert claims["hd"] == "uji.es"
