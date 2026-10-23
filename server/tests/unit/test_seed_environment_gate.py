"""SEC — el sembrado de datos de DESARROLLO no debe correr fuera de `development`.

`seed_multitenancy_defaults()` corre en el `lifespan` en cada arranque y siembra el
SuperAdmin de desarrollo (`fabra@uji.es` / `admin1234`, credencial pública en el repo)
más admin/cliente/licencia de prueba. En producción eso crea una cuenta con credencial
conocida y acceso a todos los tenants. La provisión de producción la hace
`server.app.scripts.bootstrap`, que toma la credencial de SUPERADMIN_EMAIL/PASSWORD.

Estos tests no tocan la BD: comprueban la decisión del gate antes de abrir sesión.
"""
from __future__ import annotations

import pytest

from server.app.database import seeds


class _Sentinela(Exception):
    """Marca que la ejecución llegó a abrir sesión (o sea, el gate dejó pasar)."""


def _prohibir_sesion(*_args, **_kwargs):
    raise AssertionError(
        "fuera de 'development' no debe abrirse una sesión para sembrar datos de desarrollo"
    )


async def test_should_not_seed_dev_data_outside_development(monkeypatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setattr(seeds, "AsyncSessionLocal", _prohibir_sesion)

    # No debe lanzar: simplemente se omite el sembrado de desarrollo.
    await seeds.seed_multitenancy_defaults()


async def test_should_seed_dev_data_in_development(monkeypatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "development")

    abrio_sesion = {"valor": False}

    def _espia(*_args):
        abrio_sesion["valor"] = True
        raise _Sentinela  # cortamos antes de tocar la BD real

    monkeypatch.setattr(seeds, "AsyncSessionLocal", _espia)

    with pytest.raises(_Sentinela):
        await seeds.seed_multitenancy_defaults()

    assert abrio_sesion["valor"], "en desarrollo debe abrir sesión y sembrar"
