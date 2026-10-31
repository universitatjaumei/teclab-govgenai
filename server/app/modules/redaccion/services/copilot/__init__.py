"""Copilot del DrawerHub: RAG sobre docs de módulo + NL→config estructurada.

Deploy: edge — consume LLM + embeddings + factories del módulo redacción.
"""

from .docs_retriever import DocsRetriever, IndexedChunk
from .copilot_service import CopilotService, CopilotTranslator
from .models import (
    CopilotAnswer,
    CopilotTranslateRequest,
    CopilotTranslateResponse,
    CopilotAskRequest,
    SourceRef,
)

__all__ = [
    "CopilotService",
    "CopilotTranslator",
    "CopilotAnswer",
    "CopilotAskRequest",
    "CopilotTranslateRequest",
    "CopilotTranslateResponse",
    "DocsRetriever",
    "IndexedChunk",
    "SourceRef",
]
