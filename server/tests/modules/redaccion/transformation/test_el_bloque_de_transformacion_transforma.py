"""PRO.4 — un bloque DATA_TRANSFORM que de verdad transforma dentro de un informe.

Tres costuras cortadas, y ninguna se veía desde los tests de cada pieza:

1. **El nodo no encontraba los datos de origen.** `_resolve_df` busca `content["rows"]`, y el
   contenido de una extracción es `{tables, metrics, free_text}`: sin `rows`. Un bloque de
   transformación colgado de un bloque de extracción —el caso normal— recibía un DataFrame
   **vacío** y «transformaba» la nada sin decir nada.
2. **El nodo se construía sin modelo.** `DataTransformationNode(llm_service=None)`, porque la
   raíz de composición de VER.1 no le pasó `etl_llm`: el modo determinista funcionaba y el de
   IA fallaba con «ai mode requires an injected llm».
3. **Lo transformado no se veía en el informe.** El contenido era `{rows, operations_applied}`,
   y el renderizador de PRO.3 pinta `tables`: la tabla transformada no salía.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pandas as pd
import pytest

from server.app.modules.redaccion.contracts.runtime import BlockState, WorkspaceState
from server.tests.dobles import modelo_de_chat


def _spec_con_transformacion(mode: str = "deterministic", operations=None, nl=None):
    from server.app.modules.redaccion.contracts.blocks import (
        DataTransformBlock,
        DataTransformBlockConfig,
        DeterministicDataBlock,
    )
    from server.app.modules.redaccion.contracts.block_io import BlockReference
    from server.app.modules.redaccion.contracts.inputs import InputContract, InputSlot
    from server.app.modules.redaccion.contracts.template import (
        AIBlockPolicy,
        ExportPolicy,
        ReportTemplateSpec,
        ReviewPolicy,
    )
    from server.app.modules.redaccion.contracts.ui import ReportUIContract

    return ReportTemplateSpec(
        sections=[],
        blocks=[
            DeterministicDataBlock(id="b-datos", title="Datos", source_pipeline="excel"),
            DataTransformBlock(
                id="b-etl",
                title="Datos limpios",
                config=DataTransformBlockConfig(
                    source_block_ref=BlockReference(block_id="b-datos"),
                    mode=mode,
                    operations=operations or [],
                    nl_instruction=nl,
                ),
            ),
        ],
        input_contract=InputContract(
            required_slots=[InputSlot(slot_id="datos", kind="excel", label={"es": "Datos"})],
        ),
        ui_contract=ReportUIContract(
            wizard_steps=[], dropzones=[], manual_fields=[],
            block_editor_enabled=False, ai_review_panel_enabled=False,
            preview_layout="markdown",
        ),
        ai_block_policy=AIBlockPolicy.ALLOWED,
        review_policy=ReviewPolicy.NONE,
        export_policy=ExportPolicy.DOCX,
    )


def _bloque(block_id: str, kind: str, content=None) -> BlockState:
    return BlockState(
        block_id=block_id,
        kind=kind,
        status="extracted" if content else "draft",
        content=content,
        last_updated_by="system",
        updated_at=datetime.now(timezone.utc),
    )


#: Lo que deja un bloque de extracción: una tabla, sin `rows` en la raíz.
_CONTENIDO_EXTRAIDO = {
    "tables": [{
        "name": "ejecucion",
        "headers": ["capitulo", "importe"],
        "rows": [["1 Personal", "100"], ["2 Corrientes", "200"], ["2 Corrientes", "200"]],
        "source_page": None,
    }],
    "metrics": [],
    "free_text": None,
}


def _estado(spec, contenido_origen=_CONTENIDO_EXTRAIDO):
    return WorkspaceState(
        workspace_id=uuid.uuid4(),
        template_version_id=uuid.uuid4(),
        report_profile="GENERIC_REPORT",
        spec=spec,
        blocks={
            "b-datos": _bloque("b-datos", "DETERMINISTIC_DATA", contenido_origen),
            "b-etl": _bloque("b-etl", "DATA_TRANSFORM"),
        },
        status="extracting",
        inputs={},
        warnings=[],
        block_outputs={},
    )


pytestmark = pytest.mark.asyncio


async def test_should_transformar_la_tabla_del_bloque_de_extraccion() -> None:
    """La costura que faltaba: el origen es una tabla extraída, no un `rows` suelto."""
    from server.app.modules.redaccion.graph.nodes.data_transformation import (
        DataTransformationNode,
    )
    from server.app.modules.redaccion.services.transformation.operations import parse_operations

    ops = parse_operations([{"op": "remove_duplicates", "subset": ["capitulo"]}])
    spec = _spec_con_transformacion(operations=ops)

    salida = await DataTransformationNode()(_estado(spec))

    bloque = salida["blocks"]["b-etl"]
    assert bloque.status == "extracted", bloque.last_error_message
    assert len(bloque.content["rows"]) == 2, "el duplicado tenía que desaparecer"


async def test_should_dejar_lo_transformado_como_tabla_para_el_informe() -> None:
    """PRO.3 pinta `tables`: sin ellas, la tabla transformada no sale en el informe."""
    from server.app.modules.redaccion.graph.nodes.data_transformation import (
        DataTransformationNode,
    )
    from server.app.modules.redaccion.services.preview_builder import _block_content_to_html
    from server.app.modules.redaccion.services.transformation.operations import parse_operations

    ops = parse_operations([{"op": "rename_columns", "mapping": {"capitulo": "seccion"}}])
    salida = await DataTransformationNode()(_estado(_spec_con_transformacion(operations=ops)))

    contenido = salida["blocks"]["b-etl"].content
    tablas = contenido.get("tables") or []
    assert tablas, "el bloque transformado tiene que exponer su tabla"
    assert tablas[0]["headers"] == ["seccion", "importe"]

    html = _block_content_to_html(contenido)
    assert "<table" in html
    assert "seccion" in html


async def test_should_avisar_cuando_el_origen_no_trae_datos() -> None:
    """Transformar la nada en silencio es peor que fallar: el informe saldría vacío."""
    from server.app.modules.redaccion.graph.nodes.data_transformation import (
        DataTransformationNode,
    )
    from server.app.modules.redaccion.services.transformation.operations import parse_operations

    ops = parse_operations([{"op": "drop_columns", "columns": ["importe"]}])
    estado = _estado(_spec_con_transformacion(operations=ops), contenido_origen=None)

    salida = await DataTransformationNode()(estado)

    bloque = salida["blocks"]["b-etl"]
    assert bloque.status == "failed"
    assert any(w.block_id == "b-etl" for w in salida["warnings"])


async def test_should_fallar_con_su_motivo_si_la_columna_no_existe() -> None:
    from server.app.modules.redaccion.graph.nodes.data_transformation import (
        DataTransformationNode,
    )
    from server.app.modules.redaccion.services.transformation.operations import parse_operations

    ops = parse_operations([{"op": "drop_columns", "columns": ["importee"]}])

    salida = await DataTransformationNode()(_estado(_spec_con_transformacion(operations=ops)))

    bloque = salida["blocks"]["b-etl"]
    assert bloque.status == "failed"
    assert "importee" in (bloque.last_error_message or "")


async def test_should_usar_el_modelo_inyectado_en_modo_ia() -> None:
    """El nodo se construía con `llm_service=None` y el modo IA no podía funcionar."""
    from unittest.mock import AsyncMock, MagicMock

    from server.app.modules.redaccion.graph.nodes.data_transformation import (
        DataTransformationNode,
    )

    llm = modelo_de_chat()
    llm.ainvoke = AsyncMock(return_value=MagicMock(content=(
        '{"mode": "operations", "operations": '
        '[{"op": "remove_duplicates", "subset": ["capitulo"]}]}'
    )))

    spec = _spec_con_transformacion(mode="ai", nl="Quita los capítulos repetidos.")
    nodo = DataTransformationNode(llm_service=llm, model_name="modelo-de-nivel-2")

    salida = await nodo(_estado(spec))

    bloque = salida["blocks"]["b-etl"]
    assert bloque.status == "extracted", bloque.last_error_message
    assert bloque.content["model_used"] == "modelo-de-nivel-2"
    assert len(bloque.content["rows"]) == 2
    llm.ainvoke.assert_awaited()


async def test_should_auditar_el_script_del_modo_ia_antes_de_ejecutarlo() -> None:
    """Un script de ETL pasa por el **mismo** auditor que el de extracción.

    Un camino con auditoría y otro sin ella es no tener auditoría.
    """
    from unittest.mock import AsyncMock, MagicMock

    from server.app.modules.redaccion.services.transformation.etl_service import ETLService

    llm = modelo_de_chat()
    # El modelo se salta el catálogo y devuelve un script con una llamada prohibida.
    llm.ainvoke = AsyncMock(return_value=MagicMock(content=(
        "```python\n"
        "def transform(df):\n"
        "    import os\n"
        "    return df\n"
        "```"
    )))

    with pytest.raises(ValueError, match="auditor"):
        await ETLService(llm=llm, model_name="m").run(
            df=pd.DataFrame({"a": [1]}),
            mode="ai",
            nl_instruction="haz lo que quieras",
        )
