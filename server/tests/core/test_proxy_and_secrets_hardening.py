"""Tests SEC.8.4 — la IP de confianza, el secreto de producción y el SAML.

Tres hallazgos que comparten forma: una defensa existente que un detalle deja sin efecto.

- El limitador de fuerza bruta del login acota **por IP**, y la IP salía del primer valor
  de `X-Forwarded-For`. Ese valor lo escribe el cliente: mandando uno distinto en cada
  petición se obtiene un cubo nuevo cada vez y el límite de SEC.4 no llega a aplicarse
  nunca. Detrás de un proxy, la IP real es la que **añade el proxy**, que va al final.
- `JWT_SECRET_KEY` es obligatoria desde SEC.1, pero nada impedía desplegar con el
  `change-me-in-production` que trae el `.env.example`.
- El SP de SAML descargaba la metadata del IdP sin validar el certificado TLS, así que un
  intermediario podía sustituir la clave con la que luego se verifican las aserciones.
"""
from __future__ import annotations

import pytest


def _request_con(cabeceras: dict[str, str], host: str = "10.0.0.9"):
    """Request mínimo: `ip_de` solo mira cabeceras y `client.host`."""
    from types import SimpleNamespace

    return SimpleNamespace(
        headers=cabeceras, client=SimpleNamespace(host=host)
    )


class TestIpDeConfianza:

    def test_should_not_trust_the_leftmost_forwarded_for(self, monkeypatch):
        """Es el valor que escribe el cliente: si manda uno distinto por petición, el
        limitador de login reparte un cubo nuevo cada vez y deja de limitar."""
        from server.app.core import rate_limit

        monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")

        ip = rate_limit.ip_de(
            _request_con({"X-Forwarded-For": "1.2.3.4, 203.0.113.7"})
        )
        assert ip != "1.2.3.4", "se sigue tomando el valor que controla el cliente"
        assert ip == "203.0.113.7"

    def test_should_ignore_a_spoofed_chain_longer_than_the_trusted_hops(self, monkeypatch):
        """Rellenar la cadena con valores falsos no debe desplazar la IP elegida."""
        from server.app.core import rate_limit

        monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")

        primera = rate_limit.ip_de(
            _request_con({"X-Forwarded-For": "9.9.9.9, 203.0.113.7"})
        )
        segunda = rate_limit.ip_de(
            _request_con({"X-Forwarded-For": "8.8.8.8, 7.7.7.7, 203.0.113.7"})
        )
        assert primera == segunda == "203.0.113.7"

    def test_should_fall_back_to_the_socket_when_there_is_no_proxy(self, monkeypatch):
        from server.app.core import rate_limit

        monkeypatch.delenv("TRUSTED_PROXY_HOPS", raising=False)

        assert rate_limit.ip_de(_request_con({}, host="192.0.2.5")) == "192.0.2.5"

    def test_should_ignore_forwarded_for_when_no_proxy_is_declared(self, monkeypatch):
        """Sin proxy declarado la cabecera no es de fiar: la pone quien quiera."""
        from server.app.core import rate_limit

        monkeypatch.setenv("TRUSTED_PROXY_HOPS", "0")

        ip = rate_limit.ip_de(
            _request_con({"X-Forwarded-For": "1.2.3.4"}, host="192.0.2.5")
        )
        assert ip == "192.0.2.5"

    def test_should_ignore_forwarded_for_from_outside_the_proxy_network(self, monkeypatch):
        """Desde la red del sandbox se llega a la API sin pasar por el proxy.

        Ahí la cabecera la escribe un guion, y cambiándola en cada petición el límite de
        fuerza bruta del login no se aplicaría nunca. Sólo se cree si quien la manda es el
        proxy, y el proxy es lo que dice `FORWARDED_ALLOW_IPS`, la misma lista que uvicorn.
        """
        from server.app.core import rate_limit

        monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")
        monkeypatch.setenv("FORWARDED_ALLOW_IPS", "172.28.0.0/24")

        ip = rate_limit.ip_de(_request_con({"X-Forwarded-For": "1.2.3.4"}, host="172.29.0.5"))

        assert ip == "172.29.0.5"

    def test_should_still_trust_the_proxy_network(self, monkeypatch):
        from server.app.core import rate_limit

        monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")
        monkeypatch.setenv("FORWARDED_ALLOW_IPS", "172.28.0.0/24")

        ip = rate_limit.ip_de(_request_con({"X-Forwarded-For": "203.0.113.7"}, host="172.28.0.4"))

        assert ip == "203.0.113.7"


class TestSecretoDeProduccion:

    def test_should_reject_the_placeholder_secret_in_production(self, monkeypatch):
        from server.app.core.config import get_settings

        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("SANDBOX_MODE", "http")
        monkeypatch.setenv("JWT_SECRET_KEY", "change-me-in-production")
        monkeypatch.delenv("TESTING", raising=False)

        with pytest.raises(RuntimeError, match="(?i)jwt_secret_key"):
            get_settings()

    def test_should_reject_a_too_short_secret_in_production(self, monkeypatch):
        from server.app.core.config import get_settings

        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("SANDBOX_MODE", "http")
        monkeypatch.setenv("JWT_SECRET_KEY", "corta")
        monkeypatch.delenv("TESTING", raising=False)

        with pytest.raises(RuntimeError, match="(?i)jwt_secret_key"):
            get_settings()

    def test_should_accept_a_real_secret_in_production(self, monkeypatch):
        from server.app.core.config import get_settings

        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("SANDBOX_MODE", "http")
        monkeypatch.setenv("JWT_SECRET_KEY", "n2Xq7wRz9pL4vT8mK1sYbC6hJ0dF3gA5")
        monkeypatch.delenv("TESTING", raising=False)

        assert get_settings().environment == "production"

    def test_should_not_block_development_with_a_placeholder(self, monkeypatch):
        """La guarda es de producción: en desarrollo el placeholder es lo normal."""
        from server.app.core.config import get_settings

        monkeypatch.setenv("ENVIRONMENT", "development")
        monkeypatch.setenv("JWT_SECRET_KEY", "change-me-in-production")

        assert get_settings().jwt_secret_key == "change-me-in-production"


class TestSamlEndurecido:

    def test_should_require_signed_assertions(self):
        from server.app.core.auth.saml.settings import _security_settings

        assert _security_settings()["wantAssertionsSigned"] is True

    def test_should_reject_unsolicited_responses(self):
        """Aceptar respuestas no solicitadas facilita el replay de una aserción."""
        from server.app.core.auth.saml.settings import _security_settings

        assert (
            _security_settings()["rejectUnsolicitedResponsesWithInResponseTo"] is True
        )

    def test_should_validate_tls_when_fetching_idp_metadata(self):
        """Sin validar el certificado, un intermediario sustituye la clave con la que
        después se verifican todas las aserciones."""
        from pathlib import Path

        fuente = Path("app/core/auth/saml/settings.py").read_text(encoding="utf-8")
        assert "validate_cert=False" not in fuente
