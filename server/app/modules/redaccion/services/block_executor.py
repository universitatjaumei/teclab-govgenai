"""BlockExecutor — política centralizada de retry para nodos del DraftingCoreGraph (9R.6.6).

Regla: BlockExecutor es la ÚNICA superficie con política de retry.
Los nodos del grafo NO implementan su propio retry; delegan en BlockExecutor.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Callable

from pydantic import BaseModel

from server.app.modules.redaccion.contracts.runtime import (
    BlockState,
    FailureKind,
    ReportTemplateSpec,
    WorkspaceState,
)


# ---------------------------------------------------------------------------
# Excepciones de control de flujo
# ---------------------------------------------------------------------------

class LLMTimeoutError(Exception):
    """Error de timeout o red al invocar el LLM. Retriable."""


class ScriptRuntimeError(Exception):
    """Error en tiempo de ejecución de un AdminScript. No retriable."""


class ASTValidationError(Exception):
    """Error de validación AST (detección de código inseguro). No retriable."""


# ---------------------------------------------------------------------------
# Mapeo excepción → failure_kind y retriable
# ---------------------------------------------------------------------------

_RETRIABLE = (LLMTimeoutError, asyncio.TimeoutError, TimeoutError)

_FAILURE_KIND_MAP: list[tuple[type, FailureKind]] = [
    (LLMTimeoutError, "ai_failed"),
    (asyncio.TimeoutError, "ai_failed"),
    (TimeoutError, "ai_failed"),
    (ScriptRuntimeError, "script_failed"),
    (ASTValidationError, "script_failed"),
]


def _failure_kind_from_exc(exc: Exception, default: FailureKind) -> FailureKind:
    for exc_type, kind in _FAILURE_KIND_MAP:
        if isinstance(exc, exc_type):
            return kind
    return default


# ---------------------------------------------------------------------------
# NodeResult
# ---------------------------------------------------------------------------

class NodeResult(BaseModel):
    status: str  # "success" | "failed"
    failure_kind: FailureKind | None = None
    last_error: str | None = None
    retry_attempts: int = 0
    output: Any | None = None


# ---------------------------------------------------------------------------
# BlockExecutor
# ---------------------------------------------------------------------------

class BlockExecutor:
    """Encapsula la política de retry para ejecución de funciones de nodo por bloque.

    - LLM timeouts y errores de red: 1 retry con backoff configurable.
    - AST validation errors y ScriptRuntimeError: NO retry (bug determinista).
    - Emite span Langfuse error en cada intento fallido.
    """

    def __init__(
        self,
        tracing: Any,
        retry_delay_seconds: float = 2.0,
    ) -> None:
        self._tracing = tracing
        self._delay = retry_delay_seconds

    async def execute(
        self,
        node_fn: Callable,
        block: Any,
        state: WorkspaceState,
        failure_kind: FailureKind = "extraction_failed",
    ) -> NodeResult:
        span = self._tracing.node_span(
            f"block_executor.{getattr(block, 'id', 'unknown')}"
        )
        attempts = 0
        last_exc: Exception | None = None

        for attempt in range(2):  # max 2 attempts
            try:
                output = await node_fn(block, state)
                span.end()
                return NodeResult(
                    status="success",
                    retry_attempts=attempts,
                    output=output,
                )
            except Exception as exc:  # noqa: BLE001 — se reintenta y el último fallo va al resultado
                attempts += 1
                last_exc = exc
                span.add_event(
                    "error",
                    attempt=attempt + 1,
                    type=type(exc).__name__,
                    message=str(exc),
                )
                # Determine if this exception is retriable
                if not isinstance(exc, _RETRIABLE):
                    break  # no retry for deterministic errors
                if attempt == 0:
                    await asyncio.sleep(self._delay)
                # else: second attempt exhausted

        span.end()
        assert last_exc is not None, "sólo se llega aquí tras un fallo"
        actual_kind = _failure_kind_from_exc(last_exc, failure_kind)
        return NodeResult(
            status="failed",
            failure_kind=actual_kind,
            last_error=str(last_exc),
            retry_attempts=attempts - 1,  # retries = attempts - first try
        )


# ---------------------------------------------------------------------------
# Propagación de fallos por dependencia
# ---------------------------------------------------------------------------

def propagate_dependency_failures(
    spec: ReportTemplateSpec,
    blocks: dict[str, BlockState],
) -> dict[str, BlockState]:
    """Marca como failed(validation_failed) todos los bloques cuyas dependencias fallaron.

    Propagación en cascada: si A falla y B depende de A, B falla; si C depende de B, C también.
    """
    updated = dict(blocks)
    failed_ids = {bid for bid, bs in updated.items() if bs.status == "failed"}
    if not failed_ids:
        return updated

    # Iteramos hasta que no haya nuevos fallos (cascada)
    changed = True
    while changed:
        changed = False
        for block_contract in spec.blocks:
            bid = block_contract.id
            bstate = updated.get(bid)
            if bstate is None or bstate.status == "failed":
                continue
            for dep in block_contract.depends_on:
                if dep.block_id in failed_ids:
                    updated[bid] = bstate.model_copy(update={
                        "status": "failed",
                        "failure_kind": "validation_failed",
                        "last_error_message": f"dependency_failed:{dep.block_id}",
                        "last_updated_by": "system",
                        "updated_at": datetime.now(timezone.utc),
                    })
                    failed_ids.add(bid)
                    changed = True
                    break

    return updated
