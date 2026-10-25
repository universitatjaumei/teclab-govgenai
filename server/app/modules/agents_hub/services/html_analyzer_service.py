"""Servicio HITL que propone selectores CSS para el contenido de páginas institucionales.

Deploy: cloud
"""
import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from bs4 import BeautifulSoup
from server.app.core.llm_text import texto_de

_HTML_TRUNCATE_CHARS = 10_000
_SAMPLE_MAX_CHARS = 200

_PROMPT_TEMPLATE = (
    "Analiza el siguiente HTML y devuelve SOLO un JSON con selectores CSS para: "
    "content (contenido principal), title (título), date (fecha). "
    "Omite los campos que no encuentres. Solo el JSON, sin texto adicional.\n\n"
    "HTML:\n{html}"
)


class EmptyHtmlError(Exception):
    pass


class LLMServiceProtocol(Protocol):
    async def generate(self, prompt: str) -> str: ...


@dataclass
class AnalysisResult:
    proposed_selectors: dict[str, str | None]
    confidence: float
    sample_extraction: dict[str, str] = field(default_factory=dict)


class HtmlAnalyzerService:
    """Propone selectores CSS para extraer contenido estructurado de HTML institucional."""

    def __init__(self, llm_service: LLMServiceProtocol) -> None:
        self._llm = llm_service

    async def analyze(self, html: str, url_hint: str) -> AnalysisResult:  # noqa: ARG002 — está en el contrato de la API y el prompt aún no lo usa
        if not html or not html.strip():
            raise EmptyHtmlError("El HTML no puede estar vacío.")

        truncated = html[:_HTML_TRUNCATE_CHARS]
        prompt = _PROMPT_TEMPLATE.format(html=truncated)
        response = await self._llm.generate(prompt)

        try:
            raw: dict[str, Any] = json.loads(response)
        except (json.JSONDecodeError, ValueError):
            return AnalysisResult(proposed_selectors={}, confidence=0.0)

        soup = BeautifulSoup(html, "html.parser")
        proposed: dict[str, str | None] = {}
        samples: dict[str, str] = {}
        valid = 0
        total = len(raw)

        for key, selector in raw.items():
            if not isinstance(selector, str):
                proposed[key] = None
                continue
            element = soup.select_one(selector)
            if element:
                proposed[key] = selector
                samples[key] = element.get_text(separator=" ", strip=True)[:_SAMPLE_MAX_CHARS]
                valid += 1
            else:
                proposed[key] = None

        confidence = valid / total if total > 0 else 0.0
        return AnalysisResult(
            proposed_selectors=proposed,
            confidence=confidence,
            sample_extraction=samples,
        )


class LangChainLLMAdapter:
    """Adapta un modelo LangChain chat a LLMServiceProtocol."""

    def __init__(self, model: Any) -> None:
        self._model = model

    async def generate(self, prompt: str) -> str:
        response = await self._model.ainvoke(prompt)
        return texto_de(response)
