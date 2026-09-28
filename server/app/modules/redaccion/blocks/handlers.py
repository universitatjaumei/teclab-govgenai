"""El handler del bloque de gráfico. Deploy: edge.

**Queda uno, y es una decisión medida (issue #180).** Este fichero declaraba **once** clases,
una por tipo de bloque, y fuera de sus propios tests sólo ésta tenía consumidor vivo:
`ChartRenderNode._dibujar`. No había registro por `kind`, ni despachador, ni nada que las
recorriera. Lo que ejecuta cada tipo de bloque son los **nodos del grafo**, y quién atiende a
cada uno está en la tabla de `test_issue180_los_handlers_que_nadie_montaba.py`.

**No era un contrato de extensión**, que era la posibilidad que había que descartar antes de
tocar nada: nada registraba handlers y la documentación de extensibilidad sólo mencionaba éste.

Ocho de las diez retiradas eran duplicados de un nodo que hace lo mismo y más. Las otras dos
eran capacidades que nadie había cableado —el texto estático de la plantilla y el apartado de
fuentes—, y se cablearon en los nodos que ya existían antes de retirarlas: eran dos apartados
que no salían en el informe y no daban ningún error, que es exactamente lo que le pasa a una
clase que nadie monta.

La interfaz que queda es la que alguien llama:

  validate(block)                     — verifica integridad estructural
  validate_in_context(block, state)   — verifica dependencias en el workspace
  execute(block, state) -> dict       — produce el content del bloque

`to_manifest`, `uses_ai` y `requires_approval` se van con las otras diez clases: sólo los leían
sus propios tests. El manifiesto de la ejecución lo construye `audit_log` a partir del estado,
no a partir de los handlers.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from server.app.modules.redaccion.contracts.blocks import (
    ChartBlock,
    ChartBlockConfig,
)
from server.app.modules.redaccion.contracts.runtime import WorkspaceState
from server.app.modules.redaccion.services.charts.chart_configuration import ChartConfiguration
from server.app.modules.redaccion.services.charts.deterministic_chart_service import DeterministicChartService
from server.app.modules.redaccion.services.charts.chart_renderer import render_chart_from_script, ChartRenderError


class BlockHandlerValidationError(Exception):
    pass


# ---------------------------------------------------------------------------
# Base helper
# ---------------------------------------------------------------------------

def _base_manifest(block_id: str, kind: str) -> dict[str, Any]:
    return {"block_id": block_id, "kind": kind}


class ChartHandler:
    """Bloque de gráfico. Modo determinista (DeterministicChartService) o IA (ChartFactory)."""

    def __init__(self, llm: Any = None, model_name: str = "", sandbox_client: Any = None) -> None:
        self._llm = llm
        self._model_name = model_name
        self._sandbox_client = sandbox_client  # None → render_chart_from_script uses LocalSandboxClient

    def validate(self, block: ChartBlock) -> None:
        if not block.data_block_ref:
            raise BlockHandlerValidationError(
                f"ChartBlock {block.id!r} requires data_block_ref"
            )

    def validate_in_context(self, block: ChartBlock, state: WorkspaceState) -> None:
        self.validate(block)
        if block.data_block_ref not in state.blocks:
            raise BlockHandlerValidationError(
                f"ChartBlock {block.id!r}: data_block_ref={block.data_block_ref!r} not found in workspace"
            )

    async def execute(self, block: ChartBlock, state: WorkspaceState) -> dict:  # type: ignore[override]
        cfg = block.config or ChartBlockConfig()
        df = self._resolve_data(block, state)

        if cfg.mode == "deterministic":
            chart_config = self._to_chart_config(cfg)
            svc = DeterministicChartService()
            image_bytes = svc.render(df, chart_config)
            return {
                "source_block_id": block.data_block_ref,
                "chart_type": cfg.chart_type,
                "mode": "deterministic",
                "image_bytes": image_bytes,
            }

        # AI mode
        from server.app.modules.redaccion.services.charts.chart_factory import ChartFactory
        factory = ChartFactory(self._llm, self._model_name)
        schema = {"columns": list(df.columns), "dtypes": {c: str(t) for c, t in df.dtypes.items()}}
        # Issue #170 — `execute` recibe el estado entero, contexto incluido, y no se lo pasaba.
        chart_script = await factory.generate_script(
            cfg.nl_prompt or "",
            schema,
            anonymization_context=getattr(state, "anonymization_context", None),
        )
        if not chart_script.audit_result.approved:
            raise ChartRenderError(
                f"Script IA rechazado por auditoría: {chart_script.audit_result.findings}"
            )
        image_bytes = await render_chart_from_script(
            chart_script.code, df,
            output_format=cfg.output_format,
            sandbox_client=self._sandbox_client,
        )
        return {
            "source_block_id": block.data_block_ref,
            "chart_type": cfg.chart_type,
            "mode": "ai",
            "image_bytes": image_bytes,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_data(self, block: ChartBlock, state: WorkspaceState) -> pd.DataFrame:
        """Los datos del bloque de origen, vengan como `rows` o como `tables`.

        PRO.5 — buscaba sólo `rows`, igual que el nodo de transformación antes de PRO.4, así
        que un gráfico colgado de un bloque de **extracción** —que expone `tables`— se quedaba
        sin datos y dibujaba un lienzo vacío.
        """
        from server.app.modules.redaccion.graph.nodes.data_transformation import (
            _df_de_contenido,
        )

        source = state.blocks.get(block.data_block_ref)
        if source is None or not source.content:
            return pd.DataFrame()
        df = _df_de_contenido(source.content)
        return df if df is not None else pd.DataFrame()

    @staticmethod
    def _to_chart_config(cfg: ChartBlockConfig) -> ChartConfiguration:
        return ChartConfiguration(
            chart_type=cfg.chart_type,
            x_column=cfg.x_axis,
            y_column=cfg.y_axis,
            color_column=cfg.color_by,
            label_column=cfg.label_column,
            value_column=cfg.value_column,
            size_column=cfg.size_column,
            aggregation=cfg.aggregation,
            sort=cfg.sort,
            palette=cfg.palette,
            output_format=cfg.output_format,
            # PRO.8 — la presentación se perdía aquí: el bloque no la tenía, y lo que el
            # bloque no tiene el renderizador no puede recibir.
            title=cfg.title,
            x_label=cfg.x_label,
            y_label=cfg.y_label,
            show_values=cfg.show_values,
            show_legend=cfg.show_legend,
            show_grid=cfg.show_grid,
            bins=cfg.bins,
            size=cfg.size,
            style=cfg.style,
            value_format=cfg.value_format,
            number_format=cfg.number_format,
        )


