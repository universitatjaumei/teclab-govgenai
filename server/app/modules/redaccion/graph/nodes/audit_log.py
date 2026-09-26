"""AuditLogNode — cierra el grafo emitiendo DraftingRunManifest y actualizando el trace (9R.6.5/9R.6.6)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from server.app.modules.redaccion.contracts.manifest import (
    AIBlockSummary,
    DraftingRunManifest,
    FailedBlockInfo,
)
from server.app.modules.redaccion.contracts.runtime import WorkspaceState
from server.app.modules.redaccion.database.models import HubRunManifest
from server.app.modules.redaccion.services.anonymization.run_context import (
    AnonymizationSummary,
    RunAnonymizationContext,
)

_KINDS_DE_IA = frozenset({"AI_ASSISTED_TEXT", "AI_SUMMARY", "AI_REWRITE"})


class AuditLogNode:
    """Persiste el DraftingRunManifest e instrumenta el span raíz de Langfuse.

    Puede ejecutarse incluso si el workspace está en estado 'error':
    cualquier ejecución del grafo deja un manifest persistido.
    """

    def __init__(self, manifest_repo: Any, tracing_service: Any) -> None:
        self._repo = manifest_repo
        self._tracing = tracing_service

    async def __call__(self, state: WorkspaceState) -> dict:
        span = self._tracing.open_trace(
            "redaccion.run",
            workspace_id=str(state.workspace_id),
            template_version_id=str(state.template_version_id),
        )

        manifest_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        # Recopilar aprobaciones de los bloques
        approvals = [
            b.approval
            for b in state.blocks.values()
            if b.approval is not None
        ]

        # Recopilar bloques fallidos para trazabilidad
        failed_blocks = [
            FailedBlockInfo(
                block_id=b.block_id,
                failure_kind=b.failure_kind,
                last_error_message=b.last_error_message,
                retry_attempts=b.retry_attempts,
            )
            for b in state.blocks.values()
            if b.status == "failed" and b.failure_kind is not None
        ]

        # SEG.1 — `ai_blocks` estaba declarado en el contrato del manifiesto y este nodo lo
        # dejaba vacío: el modelo y la versión de instrucciones de cada apartado vivían sólo en
        # el bloque y no llegaban a la evidencia de la ejecución, que es donde los busca quien
        # audita el informe. Con ellos viaja el alcance del contexto.
        ai_blocks = [
            AIBlockSummary(
                block_id=b.block_id,
                kind=b.kind,
                status=b.status,
                model_used=(b.content or {}).get("model_used"),
                prompt_version=(b.content or {}).get("prompt_version"),
                context_scope=(b.content or {}).get("context_scope"),
                context_block_ids=(b.content or {}).get("context_block_ids") or [],
            )
            for b in state.blocks.values()
            if b.kind in _KINDS_DE_IA
        ]

        manifest = DraftingRunManifest(
            id=manifest_id,
            workspace_id=state.workspace_id,
            template_version_id=state.template_version_id,
            report_profile=state.report_profile,
            ai_blocks=ai_blocks,
            warnings=list(state.warnings),
            user_approvals=approvals,
            failed_blocks=failed_blocks,
            final_document_hash=state.final_document_hash,
            status_at_close=state.status,
            # Issue #98 — el resumen de anonimizacion SE ESCRIBE aqui, que es lo que faltaba.
            # El campo admite `None` por defecto en el contrato, asi que olvidarlo no daba
            # error: daba un `null` persistido y un 404 en `GET /anonymization-summary`, o sea
            # una pantalla diciendo «no se ha ejecutado ningun analisis todavia» aunque se
            # hubieran sustituido datos personales. Medido antes de arreglarlo: 0 de 35
            # manifiestos lo traian. Lo unico que lo rellenaba era un test que construia el
            # manifiesto a mano, y eso demuestra el contrato, no el cableado.
            #
            # `None` cuando no hay contexto, y no un resumen con `total_spans: 0`: eso
            # afirmaria que se miro y no habia nada, que es distinto de «no se miro» — y de
            # las dos maneras de equivocarse es la que tranquiliza.
            anonymization_summary=(
                AnonymizationSummary.from_context(state.anonymization_context)
                if isinstance(state.anonymization_context, RunAnonymizationContext)
                else None
            ),
            created_at=now,
        )

        # Persistir en BD
        orm = HubRunManifest(
            id=manifest_id,
            workspace_id=state.workspace_id,
            template_version_id=state.template_version_id,
            report_profile=state.report_profile,
            payload_json=manifest.model_dump(mode="json"),
            final_document_hash=state.final_document_hash,
            created_at=now,
        )
        await self._repo.save(orm)

        span.set_attribute("run_manifest_id", str(manifest_id))
        span.end()

        return {"run_manifest_id": manifest_id}
