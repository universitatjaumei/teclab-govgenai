"""ChartRenderNode — dibuja los bloques CHART de la plantilla (PRO.5).

Deploy: edge.

`DeterministicChartService`, `ChartFactory`, `render_chart_from_script` y `ChartHandler`
existían con sus tests desde 9R.5.7… y **nadie los llamaba al generar un informe**:
`blocks/handlers.py` sólo lo importan los tests y el grafo no tenía nodo de gráficos. Un
bloque CHART en una plantilla no dibujaba nada: ni imagen, ni error, ni aviso. Este nodo es la
pieza que faltaba, y reutiliza el handler en vez de reimplementarlo.

**La imagen no va en la base de datos.** Un PNG de 30-80 KB por gráfico dentro de `content_json`
hincharía la tabla de bloques y viajaría en cada lectura del workspace. Va a `StorageService`
—con lo que funciona igual en local, en MinIO y en GCS— y el contenido guarda su clave.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from server.app.modules.redaccion.contracts.runtime import ExtractionWarning, WorkspaceState

_log = logging.getLogger(__name__)


class ChartRenderNode:
    """Renderiza cada bloque CHART y deja su imagen en el almacén."""

    def __init__(
        self,
        storage_service: Any = None,
        llm_service: Any = None,
        model_name: str = "",
        sandbox_client: Any = None,
    ) -> None:
        self._storage = storage_service
        self._llm = llm_service
        self._model_name = model_name
        self._sandbox_client = sandbox_client

    async def __call__(self, state: WorkspaceState) -> dict:
        if state.spec is None:
            return {}

        bloques = dict(state.blocks)
        avisos = list(state.warnings)
        ahora = datetime.now(timezone.utc)

        for contrato in state.spec.blocks:
            if contrato.kind != "CHART" or contrato.id not in bloques:
                continue

            try:
                imagen, contenido = await self._dibujar(contrato, state)
            except Exception as fallo:  # noqa: BLE001
                avisos.append(ExtractionWarning(
                    block_id=contrato.id, message=str(fallo), kind="chart_failed",
                ))
                bloques[contrato.id] = bloques[contrato.id].model_copy(update={
                    "status": "failed",
                    "failure_kind": "script_failed",
                    "last_error_message": str(fallo)[:500],
                    "last_updated_by": "system",
                    "updated_at": ahora,
                })
                continue

            clave = f"redaccion/{state.workspace_id}/charts/{contrato.id}.{contenido['format']}"
            await self._guardar(clave, imagen)
            contenido["storage_key"] = clave

            bloques[contrato.id] = bloques[contrato.id].model_copy(update={
                "content": {"chart": contenido},
                "status": "extracted",
                "last_updated_by": "system",
                "updated_at": ahora,
            })

        return {"blocks": bloques, "warnings": avisos}

    async def _dibujar(self, contrato: Any, state: WorkspaceState) -> tuple[bytes, dict]:
        from server.app.modules.redaccion.blocks.handlers import ChartHandler

        handler = ChartHandler(
            llm=self._llm, model_name=self._model_name, sandbox_client=self._sandbox_client
        )
        # Issue #180 — `validate_in_context` comprueba que el bloque de datos al que apunta el
        # grafico exista, y **no lo llamaba nadie**: un `data_block_ref` equivocado no fallaba,
        # dibujaba un lienzo vacio. Aqui lo que lance sale como aviso `chart_failed` y el bloque
        # queda `failed`, que es lo que ya hace el `except` de quien llama.
        handler.validate_in_context(contrato, state)
        resultado = await handler.execute(contrato, state)
        imagen = resultado.pop("image_bytes")
        if not imagen:
            raise ValueError("El servicio de gráficos no devolvió imagen.")
        formato = (contrato.config.output_format if contrato.config else "png") or "png"
        return imagen, {
            "chart_type": resultado.get("chart_type"),
            "mode": resultado.get("mode"),
            "source_block_id": resultado.get("source_block_id"),
            "format": formato,
        }

    async def _guardar(self, clave: str, imagen: bytes) -> None:
        almacen = self._storage
        if almacen is None:
            from server.app.core.storage import get_storage_service

            almacen = get_storage_service()
        await almacen.put(clave, imagen)
