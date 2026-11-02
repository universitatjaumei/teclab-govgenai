"""Tests del system prompt — reapuntados en RAG.2 a la TemplateStrategy.

`agent/prompts.py` (`build_system_prompt`, `format_sources_block`) se retiró con el grafo
antiguo y su contenido se absorbió en `GenericAnswerTemplateStrategy`, que pasa a ser la
única fuente del system prompt. Las aserciones de comportamiento son las mismas: reglas de
cita presentes, directiva de idioma, mención de tools en modo selector, bloque de fuentes
con título y URL, y ausencia de sección de documentos cuando no hay evidencia.
"""
from server.app.modules.agents_hub.agent.public_graphs.profiles.public_kb_rich import (
    GenericAnswerTemplateStrategy,
)
from server.app.modules.agents_hub.agent.public_graphs.strategies.retrieval_contract import (
    EvidenceItem,
)


def _make_item(title: str, url: str) -> EvidenceItem:
    return EvidenceItem(
        source_id="doc-1",
        content="Contenido de ejemplo del documento.",
        source_url=url,
        title=title,
        score=1.0,
    )


class TestSystemPrompt:

    def test_includes_citation_rules(self):
        prompt = GenericAnswerTemplateStrategy(
            base_system_prompt="Eres un asistente."
        ).build_prompt_context([], "es", "consulta")

        assert "REGLAS DE CITA" in prompt
        assert "[titulo del documento](url)" in prompt

    def test_includes_language_directive(self):
        prompt = GenericAnswerTemplateStrategy(
            base_system_prompt="Eres un asistente."
        ).build_prompt_context([], "val", "consulta")

        # #363: en `prefer` decide el modelo con la lengua de la pregunta, y la detectada desempata.
        assert "Responde en la lengua en que está escrita la pregunta" in prompt
        assert "Si no está clara, responde en valenciano." in prompt

    def test_includes_the_base_prompt_of_the_chatbot(self):
        prompt = GenericAnswerTemplateStrategy(
            base_system_prompt="Eres el asistente de la UJI."
        ).build_prompt_context([], "es", "consulta")

        assert "Eres el asistente de la UJI." in prompt

    def test_agentic_mode_mentions_tools(self):
        prompt = GenericAnswerTemplateStrategy(
            base_system_prompt="Base.", retrieval_mode="MD_AGENT_SELECTOR"
        ).build_prompt_context([], "es", "consulta")

        assert "list_documents" in prompt
        assert "read_document" in prompt

    def test_includes_sources_block_with_title_and_url(self):
        items = [
            _make_item("Reglament del Claustre", "https://ej.es/claustre"),
            _make_item("Estatuts", "https://ej.es/estatuts"),
        ]

        prompt = GenericAnswerTemplateStrategy(
            base_system_prompt="Base."
        ).build_prompt_context(items, "ca", "consulta")

        assert "DOCUMENTOS DISPONIBLES:" in prompt
        assert "Reglament del Claustre" in prompt
        assert "https://ej.es/claustre" in prompt
        assert "Estatuts" in prompt
        assert "https://ej.es/estatuts" in prompt
        assert "Contenido de ejemplo del documento." in prompt

    def test_does_not_include_documents_section_without_evidence(self):
        prompt = GenericAnswerTemplateStrategy(
            base_system_prompt="Base."
        ).build_prompt_context([], "es", "consulta")

        assert "DOCUMENTOS DISPONIBLES:" not in prompt
        assert "No hay evidencias disponibles" in prompt

    def test_agentic_mode_does_not_dump_the_index_as_sources_block(self):
        """En modo selector el prompt instruye a leer con tools; no vuelca el índice como
        si fueran fuentes citables."""
        items = [_make_item("Entrada de índice", "https://ej.es/x")]

        prompt = GenericAnswerTemplateStrategy(
            base_system_prompt="Base.", retrieval_mode="MD_AGENT_SELECTOR"
        ).build_prompt_context(items, "es", "consulta")

        assert "DOCUMENTOS DISPONIBLES:" not in prompt
