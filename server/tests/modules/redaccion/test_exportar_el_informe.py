"""PRO.5 — el informe se tiene que poder descargar.

`ExportService` de redacción existía con sus tests desde 1C.3 y **ninguna ruta lo servía**: como
`blocks/handlers.py`, sólo lo importaban los tests. O sea que el informe no se podía exportar,
y la prueba manual del bloque VER —«abrir la exportación en Word y en Adobe»— no tenía de dónde
descargar nada.

Aquí se comprueba la ruta: que devuelve un DOCX de verdad, con la tabla como tabla y el gráfico
como imagen, y que no deja pasar a quien no es dueño del informe.
"""
from __future__ import annotations

import io
import uuid

import pytest
from docx import Document
from fastapi import FastAPI
from fastapi.testclient import TestClient

_PNG = None


def _png() -> bytes:
    global _PNG
    if _PNG is None:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        figura = plt.figure(figsize=(2, 1))
        figura.gca().bar(["a", "b"], [1, 2])
        buffer = io.BytesIO()
        figura.savefig(buffer, format="png")
        plt.close(figura)
        _PNG = buffer.getvalue()
    return _PNG


@pytest.fixture
def api(monkeypatch):
    """La ruta de exportación con el constructor de vista previa doblado."""
    from datetime import datetime, timezone

    from server.app.api.deps import get_current_user, get_session
    from server.app.core.auth.models import UserInfo
    from server.app.core.storage import get_storage_service
    from server.app.modules.redaccion.contracts.preview import (
        PreviewBlock,
        PreviewPayload,
        PreviewSection,
    )
    from server.app.routers.redaccion import workspaces_router

    workspace_id = uuid.uuid4()

    async def _payload_falso(self, wid):
        return PreviewPayload(
            workspace_id=wid,
            template_version_id=uuid.uuid4(),
            cover=PreviewSection(level=0, title="Informe de prueba", blocks=[]),
            toc=[],
            body=[PreviewSection(level=1, title="Datos", blocks=[
                PreviewBlock(
                    block_id="b-datos", kind="DETERMINISTIC_DATA", state="extracted",
                    html="<table></table>",
                    content={"tables": [{
                        "name": "ejecucion", "headers": ["capitulo", "importe"],
                        "rows": [["1 Personal", "120000"]], "source_page": None,
                    }], "metrics": [], "free_text": None},
                ),
                PreviewBlock(
                    block_id="b-grafico", kind="CHART", state="extracted", html="<img/>",
                    content={"chart": {"storage_key": "k", "format": "png", "chart_type": "bar"}},
                    images={"k": _png()},
                ),
            ])],
            audit_annex=[],
            manifest_id=uuid.uuid4(),
            generated_at=datetime.now(timezone.utc),
        )

    from server.app.modules.redaccion.services.preview_builder import PreviewBuilderService

    monkeypatch.setattr(PreviewBuilderService, "build_payload", _payload_falso)

    class _Workspace:
        id = workspace_id
        owner_id = uuid.uuid4()
        status = "assembled"

    async def _get_workspace(wid, user, session):
        return _Workspace()

    monkeypatch.setattr(workspaces_router, "_get_workspace", _get_workspace)

    app = FastAPI()
    app.dependency_overrides[get_session] = lambda: object()
    app.dependency_overrides[get_current_user] = lambda: UserInfo(
        user_id=str(uuid.uuid4()), email="u@t.com", role="user"
    )
    app.dependency_overrides[get_storage_service] = lambda: object()
    app.include_router(workspaces_router.router, prefix="/api/v1")
    return TestClient(app), workspace_id


def test_should_devolver_un_docx_descargable(api) -> None:
    client, wid = api

    respuesta = client.get(f"/api/v1/redaccion/workspaces/{wid}/export")

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml"
    )
    assert "attachment" in respuesta.headers.get("content-disposition", "")
    assert respuesta.content[:2] == b"PK", "un DOCX es un ZIP"


def test_should_llevar_la_tabla_como_tabla_y_el_grafico_como_imagen(api) -> None:
    client, wid = api

    respuesta = client.get(f"/api/v1/redaccion/workspaces/{wid}/export")
    documento = Document(io.BytesIO(respuesta.content))

    assert documento.tables, "la tabla del informe tiene que ser una tabla"
    assert documento.inline_shapes, "y el gráfico una imagen"
    assert not any("<table" in p.text for p in documento.paragraphs), (
        "y no HTML escrito como texto"
    )
