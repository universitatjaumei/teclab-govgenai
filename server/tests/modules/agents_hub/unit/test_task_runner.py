"""Tests para el orquestador de tareas y sÃ­ntesis (Prompt 4.9)."""
import pytest
from unittest.mock import AsyncMock, patch


class TestTaskRunner:

    @pytest.mark.asyncio
    async def test_task_data_integration(self) -> None:
        """El agente combina un dato numÃ©rico de Oracle con texto del PDF del usuario."""
        from server.app.modules.agents_hub.agent.task_runner import TaskRunner

        runner = TaskRunner(
            retriever=AsyncMock(hybrid_search=AsyncMock(return_value=[])),
            embedding_service=AsyncMock(embed=AsyncMock(return_value=[0.1] * 1024), embed_batch=None),
        )

        oracle_data = {"gasto_total": 15000.0, "fecha_fin": "2025-12-31"}
        user_evidence = "El proyecto ha cumplido todos los objetivos establecidos."
        normativa_context = "Los gastos elegibles no pueden superar 20.000 euros."

        with patch.object(runner, '_generate_draft', new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = (
                "## Informe\n\n"
                f"Gasto total: {oracle_data['gasto_total']} â‚¬\n\n"
                f"JustificaciÃ³n: {user_evidence}"
            )

            draft = await runner.synthesize(
                oracle_data=oracle_data,
                user_evidence=user_evidence,
                normativa_context=normativa_context,
            )

        assert "15000" in draft or "15.000" in draft or "gasto" in draft.lower()
        assert "justificaciÃ³n" in draft.lower() or user_evidence[:20] in draft

    @pytest.mark.asyncio
    async def test_gap_detection(self) -> None:
        """El agente no genera el informe si falta un campo obligatorio."""
        from server.app.modules.agents_hub.agent.task_runner import TaskRunner, MissingFieldError

        runner = TaskRunner(
            retriever=AsyncMock(hybrid_search=AsyncMock(return_value=[])),
            embedding_service=AsyncMock(embed=AsyncMock(return_value=[0.1] * 1024), embed_batch=None),
        )

        # Falta el campo 'fecha_fin' requerido por la normativa
        oracle_data = {"gasto_total": 15000.0}  # sin fecha_fin
        required_fields = ["gasto_total", "fecha_fin"]

        with pytest.raises(MissingFieldError) as exc_info:
            await runner.synthesize(
                oracle_data=oracle_data,
                user_evidence="Evidencia del usuario.",
                normativa_context="Normativa de prueba.",
                required_fields=required_fields,
            )

        assert "fecha_fin" in str(exc_info.value)
