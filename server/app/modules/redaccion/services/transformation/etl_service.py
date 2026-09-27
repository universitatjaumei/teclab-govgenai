"""ETLService — orquestador asíncrono que envuelve los dos modos del módulo (9R.5.8).

Capa fina sobre `DeterministicETLService` y `ETLFactory`. La invoca tanto el
`DataTransformHandler` (bloque DATA_TRANSFORM) como cualquier consumidor que
necesite aplicar transformaciones sobre un DataFrame ya en memoria.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import pandas as pd

from server.app.core.sandbox_client import LocalSandboxClient, SandboxClient
from server.app.modules.redaccion.services.transformation.deterministic_etl import (
    DeterministicETLService,
    JoinableResolver,
)
from server.app.modules.redaccion.services.transformation.etl_factory import (
    ETLFactory,
    ETLPlan,
)
from server.app.modules.redaccion.services.transformation.operations import Operation


@dataclass
class ETLServiceResult:
    dataframe: pd.DataFrame
    operations_applied: list[Operation] = field(default_factory=list)
    model_used: str | None = None
    plan: ETLPlan | None = None  # solo en modo ai


class ETLService:
    """Aplica transformaciones (deterministic o ai) sobre un DataFrame."""

    def __init__(
        self,
        llm: Any = None,
        model_name: str = "",
        sandbox_client: SandboxClient | None = None,
        system_prompt: str | None = None,
    ) -> None:
        self._llm = llm
        self._model_name = model_name
        self._sandbox_client: SandboxClient = sandbox_client or LocalSandboxClient()
        # PRO.4 — el prompt del planificador, resuelto por la biblioteca de prompts.
        self._system_prompt = system_prompt

    async def run(
        self,
        *,
        df: pd.DataFrame,
        mode: Literal["deterministic", "ai"],
        operations: list[Operation] | None = None,
        nl_instruction: str | None = None,
        joinable_resolver: JoinableResolver | None = None,
        anonymization_context: Any = None,
    ) -> ETLServiceResult:
        engine = DeterministicETLService(joinable_resolver=joinable_resolver)

        if mode == "deterministic":
            if not operations:
                raise ValueError("operations list is required in deterministic mode")
            transformed = engine.execute(df, operations)
            return ETLServiceResult(
                dataframe=transformed,
                operations_applied=list(operations),
                model_used=None,
            )

        # AI mode
        if self._llm is None:
            raise ValueError("ai mode requires an injected llm")
        if not nl_instruction:
            raise ValueError("nl_instruction is required in ai mode")

        factory = ETLFactory(
            self._llm, model_name=self._model_name, system_prompt=self._system_prompt
        )
        schema = self._schema_of(df)
        # Issue #170 — el contexto viaja hasta aquí. `ETLFactory` tiene los hooks pre/post desde
        # la fase 13 y **no tenía por dónde recibirlo**: la instrucción en lenguaje natural la
        # escribe una persona, así que es justo un sitio donde el dato personal entra a mano.
        plan = await factory.generate_operations_from_nl(
            nl_instruction, schema, anonymization_context=anonymization_context
        )

        if plan.mode == "operations":
            transformed = engine.execute(df, plan.operations)
            return ETLServiceResult(
                dataframe=transformed,
                operations_applied=list(plan.operations),
                model_used=plan.model_used or self._model_name,
                plan=plan,
            )

        # Script fallback: solo se ejecuta si la auditoría lo aprueba.
        if not (plan.script_audit and plan.script_audit.approved):
            raise ValueError(
                "Script de fallback rechazado por la auditoría: "
                f"{plan.script_audit.findings if plan.script_audit else 'sin auditoría'}"
            )
        transformed = await self._execute_fallback_script(plan.script_code or "", df)
        return ETLServiceResult(
            dataframe=transformed,
            operations_applied=[],
            model_used=plan.model_used or self._model_name,
            plan=plan,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _schema_of(df: pd.DataFrame) -> dict[str, Any]:
        return {
            "columns": list(df.columns),
            "dtypes": {c: str(t) for c, t in df.dtypes.items()},
        }

    async def _execute_fallback_script(self, code: str, df: pd.DataFrame) -> pd.DataFrame:
        """Ejecuta el script ETL vía SandboxClient (aislamiento real desde SBX.3)."""
        import io
        csv_in = df.to_csv(index=False)
        csv_out = await self._sandbox_client.execute_etl_script(
            code=code,
            dataframe_csv=csv_in,
        )
        return pd.read_csv(io.StringIO(csv_out))
