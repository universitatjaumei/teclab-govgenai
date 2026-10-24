"""#269 — `ENVIRONMENT` admite una lista cerrada de valores, y uno desconocido no arranca.

Todas las puertas de producción comparan con la cadena literal `production`: el secreto JWT de
ejemplo, `SANDBOX_MODE=local`, `TESTING=1`, CORS sin `*`, HSTS y el apagado de `/docs`. Con
`prod` o `staging` se desactivaban todas **en silencio**, porque sólo se avisaba si la variable
faltaba. Es la misma forma que `IDENTITY_ROLE_AUTHORITY`: un valor que no se entiende no se
interpreta.
"""
from __future__ import annotations

import pytest

from server.app.core.config import ENTORNOS, get_settings


@pytest.fixture(autouse=True)
def _secreto(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "x" * 40)


@pytest.mark.parametrize("valor", ["prod", "staging", "Production", "produccion", ""])
def test_un_valor_desconocido_no_arranca(monkeypatch, valor):
    monkeypatch.setenv("ENVIRONMENT", valor)

    with pytest.raises(RuntimeError, match="ENVIRONMENT"):
        get_settings()


def test_desarrollo_arranca(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")

    assert get_settings().environment == "development"


def test_la_lista_es_la_que_usan_las_puertas():
    """Sanidad: las puertas comparan con `production`, así que tiene que estar en la lista."""
    assert set(ENTORNOS) == {"development", "production"}
