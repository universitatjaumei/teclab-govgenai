"""El login de superadministrador paga bcrypt también cuando el correo no existe.

`login_admin` y `login_usuario` comparan siempre la contraseña —contra el hash guardado o contra un
hash señuelo—, porque si no, el caso «no existe» responde sin hacer bcrypt y el tiempo de respuesta
dice qué correos son de una cuenta. `login_superadmin` cortaba antes, y de las tres es la que más
interesa enumerar. Con espía y no con cronómetro, como el test de `login_usuario`.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _sesion(cuenta=None):
    session = MagicMock()
    resultado = MagicMock()
    resultado.first = MagicMock(return_value=cuenta)
    resultado.one_or_none = MagicMock(return_value=cuenta)
    session.exec = AsyncMock(return_value=resultado)
    session.add = MagicMock()
    session.commit = AsyncMock()
    return session


@pytest.fixture(autouse=True)
def _sin_cupo_gastado():
    from server.app.core.rate_limit import limitador

    limitador.reiniciar()
    yield
    limitador.reiniciar()


def _login(session):
    from server.app.api.deps import get_session
    from server.app.routers.auth_router import router

    async def _dep():
        yield session

    app = FastAPI()
    app.dependency_overrides[get_session] = _dep
    app.include_router(router, prefix="/api/v1")
    return TestClient(app, raise_server_exceptions=False).post(
        "/api/v1/auth/superadmin/login", json={"email": "nadie@uji.es", "password": "x" * 16}
    )


def test_should_hash_even_when_the_superadmin_does_not_exist(monkeypatch):
    import server.app.routers.auth_router as modulo

    llamadas: list = []
    real = modulo.verify_password

    def _espia(plano, hash_):
        llamadas.append(hash_)
        return real(plano, hash_)

    monkeypatch.setattr(modulo, "verify_password", _espia)

    respuesta = _login(_sesion(None))

    assert respuesta.status_code == 401, respuesta.text
    assert len(llamadas) == 1, "no se ha comparado contra el hash señuelo"
