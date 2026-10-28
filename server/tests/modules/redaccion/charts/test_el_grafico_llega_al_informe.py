"""PRO.5 — un bloque CHART tiene que aparecer en el informe y en la exportación.

`chart_factory`, `DeterministicChartService`, `render_chart_from_script` y `ChartHandler`
existen y están probados… y **nada los llamaba en la generación de un informe**: `handlers.py`
sólo lo importan los tests, y el grafo no tenía nodo de gráficos. Un bloque CHART en una
plantilla no dibujaba nada: ni imagen, ni error, ni aviso.

Y dos cosas más que aparecieron al recorrerlo:

- `ChartHandler._resolve_data` buscaba `content["rows"]`, igual que el nodo de transformación
  antes de PRO.4: un gráfico sobre un bloque de **extracción** se quedaba sin datos.
- La exportación a DOCX vuelca `block.html` **como párrafo de texto**, así que desde PRO.3 el
  documento llevaba `<table>…</table>` escrito a mano dentro. Una tabla tiene que ser una
  tabla y un gráfico una imagen.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from server.app.modules.redaccion.contracts.runtime import BlockState, WorkspaceState
from server.tests.dobles import modelo_de_chat

_CONTENIDO_EXTRAIDO = {
    "tables": [{
        "name": "ejecucion",
        "headers": ["capitulo", "importe"],
        "rows": [["1 Personal", "120000"], ["2 Corrientes", "45000"], ["6 Inversiones", "60000"]],
        "source_page": None,
    }],
    "metrics": [],
    "free_text": None,
}


def _spec_con_grafico(mode: str = "deterministic"):
    from server.app.modules.redaccion.contracts.blocks import (
        ChartBlock,
        ChartBlockConfig,
        DeterministicDataBlock,
    )
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
            ChartBlock(
                id="b-grafico",
                title="Crédito por capítulo",
                data_block_ref="b-datos",
                config=ChartBlockConfig(
                    mode=mode,
                    chart_type="bar",
                    x_axis="capitulo",
                    y_axis="importe",
                    nl_prompt="Dibuja el importe por capítulo." if mode == "ai" else None,
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


def _estado(spec, contenido=_CONTENIDO_EXTRAIDO):
    def _bloque(bid: str, kind: str, content=None) -> BlockState:
        return BlockState(
            block_id=bid,
            kind=kind,
            status="extracted" if content else "draft",
            content=content,
            last_updated_by="system",
            updated_at=datetime.now(timezone.utc),
        )

    return WorkspaceState(
        workspace_id=uuid.uuid4(),
        template_version_id=uuid.uuid4(),
        report_profile="GENERIC_REPORT",
        spec=spec,
        blocks={
            "b-datos": _bloque("b-datos", "DETERMINISTIC_DATA", contenido),
            "b-grafico": _bloque("b-grafico", "CHART"),
        },
        status="extracting",
        inputs={},
        warnings=[],
        block_outputs={},
    )


class _AlmacenEnMemoria:
    def __init__(self) -> None:
        self.guardado: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes) -> None:
        self.guardado[key] = data

    async def get(self, key: str) -> bytes:
        return self.guardado[key]


pytestmark = pytest.mark.asyncio


async def test_should_dibujar_el_grafico_del_bloque_y_guardarlo_en_el_almacen() -> None:
    from server.app.modules.redaccion.graph.nodes.chart_render import ChartRenderNode

    almacen = _AlmacenEnMemoria()
    salida = await ChartRenderNode(storage_service=almacen)(_estado(_spec_con_grafico()))

    bloque = salida["blocks"]["b-grafico"]
    assert bloque.status == "extracted", bloque.last_error_message
    grafico = bloque.content["chart"]
    assert grafico["format"] == "png"
    assert grafico["storage_key"], "la imagen va al almacén, no dentro de la base de datos"
    # PNG de verdad: la firma son ocho bytes conocidos.
    assert almacen.guardado[grafico["storage_key"]][:8] == b"\x89PNG\r\n\x1a\n"


async def test_should_leer_los_datos_de_una_tabla_extraida() -> None:
    """El gráfico cuelga de un bloque de extracción, que expone `tables` y no `rows`."""
    from server.app.modules.redaccion.blocks.handlers import ChartHandler

    spec = _spec_con_grafico()
    bloque_grafico = next(b for b in spec.blocks if b.id == "b-grafico")
    df = ChartHandler()._resolve_data(bloque_grafico, _estado(spec))

    assert list(df.columns) == ["capitulo", "importe"]
    assert len(df) == 3


async def test_should_fallar_con_su_motivo_sin_datos() -> None:
    """Un gráfico de una tabla vacía no es un gráfico: es una imagen que engaña."""
    from server.app.modules.redaccion.graph.nodes.chart_render import ChartRenderNode

    salida = await ChartRenderNode(storage_service=_AlmacenEnMemoria())(
        _estado(_spec_con_grafico(), contenido=None)
    )

    bloque = salida["blocks"]["b-grafico"]
    assert bloque.status == "failed"
    assert any(w.block_id == "b-grafico" for w in salida["warnings"])


async def test_should_rechazar_el_script_de_ia_que_no_pasa_la_auditoria() -> None:
    """El modo por script pasa por el **mismo** auditor que la extracción y el ETL."""
    from unittest.mock import AsyncMock, MagicMock

    from server.app.modules.redaccion.graph.nodes.chart_render import ChartRenderNode

    llm = modelo_de_chat()
    llm.ainvoke = AsyncMock(return_value=MagicMock(content=(
        "```python\nimport os\nplt.plot([1,2])\n```"
    )))

    salida = await ChartRenderNode(
        storage_service=_AlmacenEnMemoria(), llm_service=llm, model_name="m"
    )(_estado(_spec_con_grafico(mode="ai")))

    bloque = salida["blocks"]["b-grafico"]
    assert bloque.status == "failed"
    assert "auditor" in (bloque.last_error_message or "").lower()


async def test_should_pintar_el_grafico_en_la_vista_previa() -> None:
    """La imagen viaja al HTML como data URI: la vista de impresión tiene que ser autónoma."""
    from server.app.modules.redaccion.services.preview_builder import _block_content_to_html

    html = _block_content_to_html(
        {"chart": {"storage_key": "k", "format": "png", "chart_type": "bar"}},
        imagenes={"k": b"\x89PNG\r\n\x1a\nfalso"},
    )

    assert "<img" in html
    assert "data:image/png;base64," in html


@pytest.mark.filterwarnings("ignore::pytest.PytestWarning")
class TestExportacion:
    """Estos no son asíncronos; el `pytestmark` del módulo no les aplica."""

    def test_should_escribir_una_tabla_como_tabla_y_no_como_html(self) -> None:
        """El DOCX metía `<table>…</table>` como párrafo de texto desde PRO.3."""
        import io

        from docx import Document

        from server.app.modules.redaccion.services.export_service import ExportService

        payload = _payload_con(
            {"tables": [{
                "name": "t", "headers": ["a", "b"], "rows": [["1", "2"]], "source_page": None,
            }], "metrics": [], "free_text": None}
        )

        doc = Document(io.BytesIO(ExportService()._payload_to_docx(payload)))

        assert doc.tables, "la tabla del informe tiene que ser una tabla del documento"
        textos = [p.text for p in doc.paragraphs]
        assert not any("<table" in t for t in textos), "y no HTML escrito a mano"

    def test_should_incrustar_el_grafico_como_imagen(self) -> None:
        import io

        from docx import Document

        from server.app.modules.redaccion.services.export_service import ExportService

        png = _png_minimo()
        payload = _payload_con(
            {"chart": {"storage_key": "k", "format": "png", "chart_type": "bar"}},
            imagenes={"k": png},
        )

        bytes_docx = ExportService()._payload_to_docx(payload)
        doc = Document(io.BytesIO(bytes_docx))

        assert doc.inline_shapes, "el gráfico tiene que entrar como imagen"


def _payload_con(contenido: dict, imagenes: dict[str, bytes] | None = None):
    from server.app.modules.redaccion.contracts.preview import (
        PreviewBlock,
        PreviewPayload,
        PreviewSection,
    )
    from server.app.modules.redaccion.services.preview_builder import _block_content_to_html

    return PreviewPayload(
        workspace_id=uuid.uuid4(),
        template_version_id=uuid.uuid4(),
        cover=PreviewSection(level=0, title="Informe", blocks=[]),
        toc=[],
        body=[PreviewSection(
            level=1,
            title="Principal",
            blocks=[PreviewBlock(
                block_id=str(uuid.uuid4()),
                kind="CHART" if "chart" in contenido else "DETERMINISTIC_DATA",
                state="extracted",
                html=_block_content_to_html(contenido, imagenes=imagenes),
                content=contenido,
                images=imagenes or {},
            )],
        )],
        audit_annex=[],
        manifest_id=uuid.uuid4(),
        generated_at=datetime.now(timezone.utc),
    )


def _png_minimo() -> bytes:
    import io

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figura = plt.figure(figsize=(1, 1))
    buffer = io.BytesIO()
    figura.savefig(buffer, format="png")
    plt.close(figura)
    return buffer.getvalue()
