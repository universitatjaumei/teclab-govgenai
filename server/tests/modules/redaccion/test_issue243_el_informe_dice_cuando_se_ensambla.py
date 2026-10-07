"""#243 — cuándo se puede ensamblar un informe lo dice el servidor, no el panel.

Salió haciendo las capturas del manual. El panel de revisión concluía «todos aprobados» cuando
ningún bloque tenía acciones pendientes, y eso también es cierto en dos momentos en que no se
puede ensamblar:

- **antes de generar nada**: un informe recién creado anunciaba «Tots els apartats aprovats —
  a punt per a assemblar»;
- **después de ensamblar**: el botón seguía a la vista y pulsarlo daba un 422 en inglés.

Ahora el informe trae `acciones_permitidas` como cada bloque, y «ensamblar» sólo aparece cuando
está en revisión y no queda nada por revisar.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from server.app.modules.redaccion.services.block_actions import acciones_del_informe


def _bloque(kind="AI_ASSISTED_TEXT", status="approved", block_id="b"):
    return SimpleNamespace(kind=kind, status=status, block_id=block_id)


def test_en_revision_y_todo_aprobado_se_ensambla():
    assert acciones_del_informe("in_review", [_bloque(), _bloque(kind="TABLE", status="ready")]) == ["ensamblar"]


def test_con_algo_pendiente_no():
    assert acciones_del_informe("in_review", [_bloque(), _bloque(status="needs_review", block_id="c")]) == []


@pytest.mark.parametrize("estado", ["draft", "ingesting", "extracting", "drafting"])
def test_antes_de_la_revision_no_aunque_no_haya_nada_pendiente(estado):
    """El caso del informe recién creado: cero valoraciones no es «todas aprobadas»."""
    assert acciones_del_informe(estado, []) == []


@pytest.mark.parametrize("estado", ["assembled", "exported"])
def test_despues_de_ensamblar_no(estado):
    assert acciones_del_informe(estado, [_bloque()]) == []


def test_el_dto_del_informe_lo_lleva():
    from server.app.routers.redaccion.hub_redaccion_router import WorkspaceOut

    assert "acciones_permitidas" in WorkspaceOut.model_fields
