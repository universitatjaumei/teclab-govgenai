"""DataTransformationNode — aplica bloques DATA_TRANSFORM en orden topológico (9R.5.8).

Se ejecuta entre DeterministicExtractionNode y DataQualityCheckNode.
Itera sobre los bloques DATA_TRANSFORM del spec, resuelve el DataFrame
de origen desde state.blocks/block_outputs, y aplica las operaciones
via ETLService.

Estado de bloque resultante:
  - mode=deterministic: status draft → extracted (las ops son reproducibles)
  - mode=ai:            status draft → extracted (la IA solo elige ops, no las ejecuta)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd

from server.app.modules.redaccion.contracts.runtime import ExtractionWarning, WorkspaceState
from server.app.modules.redaccion.services.transformation.etl_service import (
    ETLService,
    ETLServiceResult,
)


def _df_de_contenido(contenido: dict) -> pd.DataFrame | None:
    """Un DataFrame del contenido de un bloque, en cualquiera de las dos formas.

    `rows` es lo que deja una transformación (lista de diccionarios) y `tables` lo que deja
    una extracción (cabeceras y filas). Sin la segunda, encadenar extracción → transformación
    no funcionaba.
    """
    filas = contenido.get("rows")
    if isinstance(filas, list) and filas:
        return pd.DataFrame(filas)

    tablas = contenido.get("tables")
    if isinstance(tablas, list) and tablas:
        tabla = tablas[0] or {}
        cabeceras = tabla.get("headers") or []
        datos = tabla.get("rows") or []
        if cabeceras and datos:
            return pd.DataFrame(datos, columns=cabeceras)
    return None


def _tabla_de(nombre: str, df: pd.DataFrame) -> dict:
    return {
        "name": nombre,
        "headers": [str(c) for c in df.columns],
        # Lo vacío, como texto vacío. Con pandas 2 `astype(str)` lo convertía en «nan», que
        # salía tal cual en la tabla; con pandas 3 sigue siendo `NaN`, que JSONB no admite.
        "rows": df.astype(str).where(df.notna(), "").values.tolist(),
        "source_page": None,
    }


class DataTransformationNode:
    """Nodo del DraftingCoreGraph que procesa bloques DATA_TRANSFORM."""

    def __init__(
        self,
        llm_service: Any = None,
        model_name: str = "",
        system_prompt: str | None = None,
    ) -> None:
        self._llm = llm_service
        self._model_name = model_name
        self._system_prompt = system_prompt

    async def __call__(self, state: WorkspaceState) -> dict:
        if state.spec is None:
            return {}

        updated_blocks = dict(state.blocks)
        new_block_outputs = dict(state.block_outputs)
        new_warnings = list(state.warnings)
        now = datetime.now(timezone.utc)

        for block_contract in state.spec.blocks:
            if block_contract.kind != "DATA_TRANSFORM":
                continue

            block_id = block_contract.id
            if block_id not in updated_blocks:
                continue

            cfg = block_contract.config
            source_id = cfg.source_block_ref.block_id
            source_df = self._resolve_df(source_id, updated_blocks, new_block_outputs)

            def _resolver(bid: str) -> pd.DataFrame:
                return self._resolve_df(bid, updated_blocks, new_block_outputs)

            svc = ETLService(
                llm=self._llm,
                model_name=self._model_name,
                system_prompt=self._system_prompt,
            )
            try:
                if cfg.mode == "deterministic":
                    result: ETLServiceResult = await svc.run(
                        df=source_df,
                        mode="deterministic",
                        operations=list(cfg.operations or []),
                        joinable_resolver=_resolver,
                    )
                else:
                    result = await svc.run(
                        df=source_df,
                        mode="ai",
                        nl_instruction=cfg.nl_instruction,
                        joinable_resolver=_resolver,
                        # Issue #170 — sin esto el prompt salía con los datos personales dentro
                        # aunque el modo fuera `replace`, y nada lo decía.
                        anonymization_context=state.anonymization_context,
                    )
            except Exception as exc:
                new_warnings.append(
                    ExtractionWarning(
                        block_id=block_id,
                        message=str(exc),
                        kind="extraction_error",
                    )
                )
                updated_blocks[block_id] = updated_blocks[block_id].model_copy(update={
                    "status": "failed",
                    "failure_kind": "script_failed",
                    "last_error_message": str(exc)[:500],
                    "last_updated_by": "system",
                    "updated_at": now,
                })
                continue

            rows = result.dataframe.to_dict(orient="records")
            content = {
                "rows": rows,
                # PRO.4 — la tabla, en la forma que el informe sabe pintar. El contenido era
                # sólo `rows`, y el renderizador de PRO.3 busca `tables`: la tabla
                # transformada no salía ni en la vista previa ni en el documento final.
                "tables": [_tabla_de(block_contract.title, result.dataframe)],
                "operations_applied": [op.model_dump() for op in result.operations_applied],
                "model_used": result.model_used,
                "mode": cfg.mode,
            }
            new_block_outputs[block_id] = content
            updated_blocks[block_id] = updated_blocks[block_id].model_copy(update={
                "content": content,
                "status": "extracted",
                "last_updated_by": "system",
                "updated_at": now,
            })

        return {
            "blocks": updated_blocks,
            "block_outputs": new_block_outputs,
            "warnings": new_warnings,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_df(
        block_id: str,
        blocks: dict,
        block_outputs: dict,
    ) -> pd.DataFrame:
        """El DataFrame de origen, venga de una extracción o de otra transformación.

        PRO.4 — sólo buscaba `content["rows"]`, y el contenido de una **extracción** es
        `{tables, metrics, free_text}`: sin `rows`. O sea que un bloque de transformación
        colgado de un bloque de extracción —el caso normal, y el único que tiene sentido—
        recibía un DataFrame vacío y «transformaba» la nada sin decir nada.
        """
        block_state = blocks.get(block_id)
        for contenido in (
            block_state.content if block_state else None,
            block_outputs.get(block_id),
        ):
            if not isinstance(contenido, dict):
                continue
            df = _df_de_contenido(contenido)
            if df is not None:
                return df
        return pd.DataFrame()
