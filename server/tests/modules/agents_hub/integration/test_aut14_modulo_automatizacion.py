"""El catálogo de funciones sale de «Informes» a su propio módulo, `automatizacion`.

Decisión del usuario (2026-10-05, opción A): «Informes» se queda con lo que de verdad son
informes —plantillas, workspaces, borradores, y los scripts que quien redacta propone para su
plantilla— y el **catálogo de funciones** pasa a «Automatización»: las funciones, las de origen
externo (los cuadernos que corren fuera), su revisión posterior y la ejecución por API. Una
función externa no produce ningún informe; es automatización gobernada.

**Un módulo y no sólo un rótulo**, porque así se concede por separado a quien redacta y a quien
registra funciones. Se hizo ahora porque no había concesiones de `informes` que migrar.
"""
from __future__ import annotations

import uuid

import pytest

from server.tests.modules.agents_hub.integration.test_plat5_frontera_de_modulos import (
    _catalogo,
    _cliente,
    _conceder,
    _principal,
)


def test_el_modulo_esta_en_el_catalogo():
    from server.app.core.auth.modulos import MODULOS_INICIALES

    assert "automatizacion" in dict(MODULOS_INICIALES)


@pytest.mark.sin_guarda_de_modulos
class TestElCatalogoDeFunciones:

    @pytest.mark.asyncio
    async def test_con_solo_informes_no_se_entra(self, db_session):
        from server.app.routers.redaccion.funciones_router import router

        await _catalogo(db_session)
        principal = _principal(uuid.uuid4())
        await _conceder(db_session, principal.user_id, "informes")
        async with _cliente(db_session, principal, router) as cliente:
            respuesta = await cliente.get("/api/v1/funciones")
        assert respuesta.status_code == 403
        assert respuesta.json()["detail"]["modulo_requerido"] == "automatizacion"

    @pytest.mark.asyncio
    async def test_con_automatizacion_si(self, db_session):
        from server.app.routers.redaccion.funciones_router import router

        await _catalogo(db_session)
        principal = _principal(uuid.uuid4())
        await _conceder(db_session, principal.user_id, "automatizacion")
        async with _cliente(db_session, principal, router) as cliente:
            respuesta = await cliente.get("/api/v1/funciones")
        assert respuesta.status_code == 200, respuesta.text

    @pytest.mark.asyncio
    async def test_ejecutar_por_api_tambien_es_automatizacion(self, db_session):
        from server.app.routers.redaccion.funciones_run_router import router

        await _catalogo(db_session)
        principal = _principal(uuid.uuid4())
        await _conceder(db_session, principal.user_id, "informes")
        async with _cliente(db_session, principal, router) as cliente:
            respuesta = await cliente.post(f"/api/v1/funciones/{uuid.uuid4()}/run", json={})
        assert respuesta.status_code == 403
        assert respuesta.json()["detail"]["modulo_requerido"] == "automatizacion"


@pytest.mark.sin_guarda_de_modulos
class TestLosScriptsSiguenEnInformes:
    """Quien redacta propone el script de su plantilla: es trabajo de informe."""

    @pytest.mark.asyncio
    async def test_con_informes_se_llega_a_los_scripts(self, db_session):
        from server.app.routers.redaccion.scripts_router import router

        await _catalogo(db_session)
        principal = _principal(uuid.uuid4())
        await _conceder(db_session, principal.user_id, "informes")
        async with _cliente(db_session, principal, router) as cliente:
            respuesta = await cliente.get("/api/v1/redaccion/scripts/pending")
        assert respuesta.status_code != 403, respuesta.text
