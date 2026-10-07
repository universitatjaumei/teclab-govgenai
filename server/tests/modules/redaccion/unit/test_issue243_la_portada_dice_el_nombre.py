"""#243 — la portada del informe dice el nombre de la plantilla, no el identificador interno.

Salió haciendo las capturas del manual: la vista previa encabezaba el informe con
`7150c987-8ee8-4f1e-b219-641d57bcee4f`, y la exportación a Word ponía lo mismo como título del
documento, porque las dos leen `cover.title`.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from server.app.modules.redaccion.services.preview_builder import PreviewBuilderService

NOMBRE = "Informe anual de seguimiento — Doctorado (criterios 1 y 2)"


def _servicio(con_plantillas: bool):
    plantilla_id, version_id, workspace_id = uuid4(), uuid4(), uuid4()
    workspace_repo = AsyncMock()
    workspace_repo.get.return_value = SimpleNamespace(id=workspace_id, template_version_id=version_id)
    block_repo = AsyncMock()
    block_repo.list.return_value = []
    version_repo = AsyncMock()
    version_repo.get.return_value = SimpleNamespace(id=version_id, template_id=plantilla_id, spec_json={})
    manifest_repo = AsyncMock()
    manifest_repo.list.return_value = []
    extra = {}
    if con_plantillas:
        template_repo = AsyncMock()
        template_repo.get.return_value = SimpleNamespace(id=plantilla_id, name=NOMBRE)
        extra["template_repo"] = template_repo
    servicio = PreviewBuilderService(
        workspace_repo=workspace_repo,
        block_repo=block_repo,
        template_version_repo=version_repo,
        manifest_repo=manifest_repo,
        **extra,
    )
    return servicio, workspace_id


@pytest.mark.asyncio
async def test_la_portada_lleva_el_nombre_de_la_plantilla():
    servicio, workspace_id = _servicio(con_plantillas=True)
    payload = await servicio.build_payload(workspace_id)
    assert payload.cover.title == NOMBRE


@pytest.mark.asyncio
async def test_sin_plantilla_que_consultar_no_se_rompe():
    servicio, workspace_id = _servicio(con_plantillas=False)
    payload = await servicio.build_payload(workspace_id)
    assert payload.cover.title


def test_el_router_le_da_las_plantillas():
    """El sitio donde se construye en la aplicación: sin esto, el arreglo sólo vivía en el test."""
    import inspect

    from server.app.routers.redaccion import workspaces_router

    fuente = inspect.getsource(workspaces_router)
    assert "template_repo=ReportTemplateRepo(session)" in fuente
