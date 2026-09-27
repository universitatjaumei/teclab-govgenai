"""Handlers de bloque para el DraftingCoreGraph — 9R.3.1.

Cada handler encapsula el comportamiento de un tipo de bloque:
  validate(block)                     — verifica integridad estructural
  validate_in_context(block, state)   — verifica dependencias en el workspace
  execute(block, state) -> dict       — produce el content del bloque
  to_manifest(block) -> dict          — qué se serializa en DraftingRunManifest
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from server.app.modules.redaccion.contracts.blocks import (
    AIAssistedTextBlock,
    AIRewriteBlock,
    AISummaryBlock,
    ChartBlock,
    ChartBlockConfig,
    CitationBlock,
    DataTransformBlock,
    DeterministicDataBlock,
    ReviewGateBlock,
    StaticTextBlock,
    TableBlock,
    UserInputBlock,
)
from server.app.modules.redaccion.contracts.runtime import WorkspaceState
from server.app.modules.redaccion.services.charts.chart_configuration import ChartConfiguration
from server.app.modules.redaccion.services.charts.deterministic_chart_service import DeterministicChartService
from server.app.modules.redaccion.services.charts.chart_renderer import render_chart_from_script, ChartRenderError
from server.app.modules.redaccion.services.transformation.etl_service import ETLService


class BlockHandlerValidationError(Exception):
    pass


# ---------------------------------------------------------------------------
# Base helper
# ---------------------------------------------------------------------------

def _base_manifest(block_id: str, kind: str) -> dict[str, Any]:
    return {"block_id": block_id, "kind": kind}


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

class StaticTextHandler:
    """Bloque de texto estático definido en la plantilla. No usa IA."""

    uses_ai: bool = False
    requires_approval: bool = False

    def validate(self, block: StaticTextBlock) -> None:
        pass  # siempre válido

    def validate_in_context(self, block: StaticTextBlock, state: WorkspaceState) -> None:
        pass

    def execute(self, block: StaticTextBlock, state: WorkspaceState) -> dict:
        return {"text": block.content}

    def to_manifest(self, block: StaticTextBlock) -> dict:
        return {**_base_manifest(block.id, block.kind), "content_length": len(block.content)}


class UserInputHandler:
    """Bloque de entrada de usuario. No usa IA; el usuario rellena el campo."""

    uses_ai: bool = False
    requires_approval: bool = False

    def validate(self, block: UserInputBlock) -> None:
        pass

    def validate_in_context(self, block: UserInputBlock, state: WorkspaceState) -> None:
        pass

    def execute(self, block: UserInputBlock, state: WorkspaceState) -> dict:
        # El contenido llega del frontend; execute solo devuelve lo que ya tiene el estado
        bs = state.blocks.get(block.id)
        return bs.content or {} if bs else {}

    def to_manifest(self, block: UserInputBlock) -> dict:
        return {**_base_manifest(block.id, block.kind), "field_type": block.field_type}


class DeterministicDataHandler:
    """Bloque de datos extraídos por un pipeline determinista. Delega en ExtractionPipeline."""

    uses_ai: bool = False
    requires_approval: bool = False

    def validate(self, block: DeterministicDataBlock) -> None:
        if not block.source_pipeline:
            raise BlockHandlerValidationError(
                f"DeterministicDataBlock {block.id!r} requires source_pipeline"
            )

    def validate_in_context(self, block: DeterministicDataBlock, state: WorkspaceState) -> None:
        self.validate(block)

    def execute(self, block: DeterministicDataBlock, state: WorkspaceState) -> dict:
        # La ejecución real delega en ExtractionPipelineFactory (implementado en 9R.5)
        return {"pipeline": block.source_pipeline, "rows": []}

    def to_manifest(self, block: DeterministicDataBlock) -> dict:
        return {**_base_manifest(block.id, block.kind), "source_pipeline": block.source_pipeline}


class TableHandler:
    """Bloque de tabla estructurada. Consume el output de un DETERMINISTIC_DATA."""

    uses_ai: bool = False
    requires_approval: bool = False

    def validate(self, block: TableBlock) -> None:
        if not block.data_block_ref:
            raise BlockHandlerValidationError(
                f"TableBlock {block.id!r} requires data_block_ref"
            )

    def validate_in_context(self, block: TableBlock, state: WorkspaceState) -> None:
        self.validate(block)
        if block.data_block_ref not in state.blocks:
            raise BlockHandlerValidationError(
                f"TableBlock {block.id!r}: data_block_ref={block.data_block_ref!r} not found in workspace"
            )

    def execute(self, block: TableBlock, state: WorkspaceState) -> dict:
        source = state.blocks.get(block.data_block_ref)
        return {"source_block_id": block.data_block_ref, "rows": source.content or {} if source else {}}

    def to_manifest(self, block: TableBlock) -> dict:
        return {**_base_manifest(block.id, block.kind), "data_block_ref": block.data_block_ref}


class ChartHandler:
    """Bloque de gráfico. Modo determinista (DeterministicChartService) o IA (ChartFactory)."""

    uses_ai: bool = False
    requires_approval: bool = False

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

    def to_manifest(self, block: ChartBlock) -> dict:
        cfg = block.config or ChartBlockConfig()
        return {
            **_base_manifest(block.id, block.kind),
            "data_block_ref": block.data_block_ref,
            "chart_type": cfg.chart_type,
            "mode": cfg.mode,
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


class DataTransformHandler:
    """Bloque de transformación tabular. Modo determinista o IA (ETLFactory).

    Lee el DataFrame del bloque referenciado por `config.source_block_ref`,
    aplica las operaciones (o las deriva del NL si mode='ai') y devuelve
    las filas transformadas en `content["rows"]` para que ChartHandler u
    otros consumidores puedan encadenar.
    """

    uses_ai: bool = False
    requires_approval: bool = False

    def __init__(self, llm: Any = None, model_name: str = "") -> None:
        self._llm = llm
        self._model_name = model_name

    def validate(self, block: DataTransformBlock) -> None:
        if block.config is None:
            raise BlockHandlerValidationError(
                f"DataTransformBlock {block.id!r} requires config"
            )

    def validate_in_context(self, block: DataTransformBlock, state: WorkspaceState) -> None:
        self.validate(block)
        src_id = block.config.source_block_ref.block_id
        if src_id not in state.blocks:
            raise BlockHandlerValidationError(
                f"DataTransformBlock {block.id!r}: source_block_ref={src_id!r} not found"
            )

    async def execute(self, block: DataTransformBlock, state: WorkspaceState) -> dict:
        cfg = block.config
        source_df = self._resolve_source_df(cfg.source_block_ref.block_id, state)
        resolver = self._make_joinable_resolver(state)

        svc = ETLService(llm=self._llm, model_name=self._model_name)
        if cfg.mode == "deterministic":
            result = await svc.run(
                df=source_df, mode="deterministic",
                operations=list(cfg.operations or []),
                joinable_resolver=resolver,
            )
        else:
            result = await svc.run(
                df=source_df, mode="ai",
                nl_instruction=cfg.nl_instruction,
                joinable_resolver=resolver,
            )

        return {
            "source_block_id": cfg.source_block_ref.block_id,
            "rows": result.dataframe.to_dict(orient="records"),
            "operations_applied": [op.model_dump() for op in result.operations_applied],
            "model_used": result.model_used,
            "mode": cfg.mode,
        }

    def to_manifest(self, block: DataTransformBlock) -> dict:
        cfg = block.config
        ops = list(cfg.operations or [])
        return {
            **_base_manifest(block.id, block.kind),
            "mode": cfg.mode,
            "source_block_id": cfg.source_block_ref.block_id,
            "operations_applied": [op.model_dump() for op in ops],
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_source_df(source_block_id: str, state: WorkspaceState) -> pd.DataFrame:
        block_state = state.blocks.get(source_block_id)
        if block_state and block_state.content:
            rows = block_state.content.get("rows")
            if isinstance(rows, list) and rows:
                return pd.DataFrame(rows)
        # Fallback: block_outputs (poblado por nodos previos del grafo).
        output = state.block_outputs.get(source_block_id) or {}
        rows = output.get("rows") if isinstance(output, dict) else None
        if isinstance(rows, list) and rows:
            return pd.DataFrame(rows)
        return pd.DataFrame()

    def _make_joinable_resolver(self, state: WorkspaceState):
        def _resolve(block_id: str) -> pd.DataFrame:
            return self._resolve_source_df(block_id, state)
        return _resolve


class AIAssistedTextHandler:
    """Bloque de texto asistido por IA. Requiere aprobación HITL antes de ensamblar."""

    uses_ai: bool = True
    requires_approval: bool = True

    def validate(self, block: AIAssistedTextBlock) -> None:
        if not block.review_policy_id:
            raise BlockHandlerValidationError(
                f"AIAssistedTextBlock {block.id!r} requires review_policy_id"
            )

    def validate_in_context(self, block: AIAssistedTextBlock, state: WorkspaceState) -> None:
        self.validate(block)

    def execute(self, block: AIAssistedTextBlock, state: WorkspaceState) -> dict:
        # La generación real la hace AIAssistDraftNode (9R.6.3)
        return {"ai_draft": "", "prompt_template_id": block.ai_prompt_template_id}

    def to_manifest(self, block: AIAssistedTextBlock) -> dict:
        return {
            **_base_manifest(block.id, block.kind),
            "ai_prompt_template_id": block.ai_prompt_template_id,
            "review_policy_id": block.review_policy_id,
        }


class AISummaryHandler:
    """Bloque de resumen generado por IA. Requiere aprobación HITL."""

    uses_ai: bool = True
    requires_approval: bool = True

    def validate(self, block: AISummaryBlock) -> None:
        if not block.review_policy_id:
            raise BlockHandlerValidationError(
                f"AISummaryBlock {block.id!r} requires review_policy_id"
            )

    def validate_in_context(self, block: AISummaryBlock, state: WorkspaceState) -> None:
        self.validate(block)

    def execute(self, block: AISummaryBlock, state: WorkspaceState) -> dict:
        return {"ai_summary": "", "prompt_template_id": block.ai_prompt_template_id}

    def to_manifest(self, block: AISummaryBlock) -> dict:
        return {
            **_base_manifest(block.id, block.kind),
            "ai_prompt_template_id": block.ai_prompt_template_id,
            "review_policy_id": block.review_policy_id,
        }


class AIRewriteHandler:
    """Bloque de reescritura asistida por IA. Requiere aprobación HITL."""

    uses_ai: bool = True
    requires_approval: bool = True

    def validate(self, block: AIRewriteBlock) -> None:
        if not block.review_policy_id:
            raise BlockHandlerValidationError(
                f"AIRewriteBlock {block.id!r} requires review_policy_id"
            )

    def validate_in_context(self, block: AIRewriteBlock, state: WorkspaceState) -> None:
        self.validate(block)

    def execute(self, block: AIRewriteBlock, state: WorkspaceState) -> dict:
        return {"ai_rewrite": "", "prompt_template_id": block.ai_prompt_template_id}

    def to_manifest(self, block: AIRewriteBlock) -> dict:
        return {
            **_base_manifest(block.id, block.kind),
            "ai_prompt_template_id": block.ai_prompt_template_id,
            "review_policy_id": block.review_policy_id,
        }


class CitationBlockHandler:
    """Bloque de citas y fuentes. Agrega referencias de otros bloques."""

    uses_ai: bool = False
    requires_approval: bool = False

    def validate(self, block: CitationBlock) -> None:
        pass

    def validate_in_context(self, block: CitationBlock, state: WorkspaceState) -> None:
        pass

    def execute(self, block: CitationBlock, state: WorkspaceState) -> dict:
        citations = []
        for ref_id in block.source_block_refs:
            bs = state.blocks.get(ref_id)
            if bs and bs.citations:
                citations.extend([c.model_dump() for c in bs.citations])
        return {"citations": citations}

    def to_manifest(self, block: CitationBlock) -> dict:
        return {
            **_base_manifest(block.id, block.kind),
            "source_block_refs": block.source_block_refs,
        }


class ReviewGateHandler:
    """Porta de revisión. Bloquea el ensamblado hasta que todos los depends_on estén approved/locked."""

    uses_ai: bool = False
    requires_approval: bool = True

    def validate(self, block: ReviewGateBlock) -> None:
        if not block.review_policy_id:
            raise BlockHandlerValidationError(
                f"ReviewGateBlock {block.id!r} requires review_policy_id"
            )

    def validate_in_context(self, block: ReviewGateBlock, state: WorkspaceState) -> None:
        self.validate(block)
        for dep_ref in block.depends_on:
            dep_id = dep_ref.block_id
            dep_state = state.blocks.get(dep_id)
            if dep_state is None:
                raise BlockHandlerValidationError(
                    f"ReviewGateBlock {block.id!r}: dependency {dep_id!r} not found"
                )
            if dep_state.status not in ("approved", "locked"):
                raise BlockHandlerValidationError(
                    f"ReviewGateBlock {block.id!r}: dependency {dep_id!r} is not approved "
                    f"(status={dep_state.status!r})"
                )

    def execute(self, block: ReviewGateBlock, state: WorkspaceState) -> dict:
        return {"gate_passed": True, "review_policy_id": block.review_policy_id}

    def to_manifest(self, block: ReviewGateBlock) -> dict:
        return {
            **_base_manifest(block.id, block.kind),
            "review_policy_id": block.review_policy_id,
        }
