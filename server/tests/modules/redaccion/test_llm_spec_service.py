"""9R.4.1 — LLMSpecService: NL → ReportTemplateDraft.

Tests RED → GREEN. El LLM se mockea; no hay acceso a BD.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock
from server.tests.dobles import modelo_de_chat


_MINIMAL_DRAFT_JSON = {
    "proposed_profile": "GENERIC_REPORT",
    "proposed_sections": [
        {"id": "s1", "title": "Introducció", "order": 1, "block_ids": ["b1"]},
    ],
    "proposed_blocks": [
        {"kind": "STATIC_TEXT", "id": "b1", "title": "Text introductori"},
    ],
    "proposed_inputs": {"required_slots": [], "optional_slots": []},
    "rationale": "Plantilla mínima per a test.",
}


def _mock_llm(response_json=None) -> MagicMock:
    if response_json is None:
        response_json = _MINIMAL_DRAFT_JSON
    llm = modelo_de_chat()
    resp = MagicMock()
    resp.content = json.dumps(response_json)
    llm.ainvoke = AsyncMock(return_value=resp)
    return llm


class TestLLMSpecService:
    async def test_llm_spec_service_returns_report_template_draft(self):
        from server.app.modules.redaccion.services.llm_spec_service import LLMSpecService
        from server.app.modules.redaccion.contracts.drafts import ReportTemplateDraft

        service = LLMSpecService(llm=_mock_llm(), model_name="gpt-4o")
        draft = await service.propose_template(
            prompt_nl="Informe anual d'activitats acadèmiques",
            owner_kind="user",
        )
        assert isinstance(draft, ReportTemplateDraft)
        assert draft.proposed_profile == "GENERIC_REPORT"
        assert len(draft.proposed_sections) >= 1
        assert len(draft.proposed_blocks) >= 1

    async def test_llm_spec_service_records_model_used_and_prompt_version(self):
        from server.app.modules.redaccion.services.llm_spec_service import LLMSpecService

        service = LLMSpecService(llm=_mock_llm(), model_name="claude-sonnet-4-6")
        draft = await service.propose_template(
            prompt_nl="Informe de doctorat",
            owner_kind="user",
        )
        assert draft.model_used == "claude-sonnet-4-6"
        assert draft.prompt_version != ""

    def test_llm_spec_service_does_not_persist_anything(self):
        """El módulo no debe importar repos ni sesiones de BD."""
        import inspect
        import server.app.modules.redaccion.services.llm_spec_service as mod

        src = inspect.getsource(mod)
        assert "AsyncSession" not in src
        assert "get_db" not in src
        assert "database.repos" not in src
        assert "database.models" not in src

    async def test_llm_spec_service_respects_owner_kind(self):
        """owner_kind='admin' → el system prompt incluye instrucciones para is_global."""
        from server.app.modules.redaccion.services.llm_spec_service import LLMSpecService

        mock_llm = _mock_llm()
        service = LLMSpecService(llm=mock_llm, model_name="gpt-4o")

        await service.propose_template(
            prompt_nl="Plantilla global per a tota la plataforma",
            owner_kind="admin",
        )

        call_args = mock_llm.ainvoke.call_args
        messages = call_args[0][0]

        # Extract system message content (dict or LangChain message object)
        system_content = ""
        for m in messages:
            if isinstance(m, dict) and m.get("role") == "system":
                system_content = m["content"]
                break
            if hasattr(m, "type") and m.type == "system":
                system_content = m.content
                break

        assert "is_global" in system_content
