"""Protocolo RetrievalPipeline para grafos públicos.

Cada implementación concreta (RAG, MD_LONG_CONTEXT, MD_AGENT_SELECTOR)
debe cumplir este contrato. El CoreGraph usa exclusivamente este protocolo,
sin depender de ninguna implementación específica.

Deploy: edge
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from server.app.modules.agents_hub.agent.public_graphs.core.config_resolver import (
        PublicGraphConfig,
    )
    from server.app.modules.agents_hub.agent.public_graphs.strategies.retrieval_contract import (
        RetrievalResult,
    )


@dataclass
class GraphDeps:
    """Dependencias de ejecución inyectadas en cada pipeline.

    session: sesión async de SQLAlchemy (para consultar documentos y chunks).
    embedder: servicio de embedding (protocolo EmbeddingService).
    llm: modelo de lenguaje opcional (requerido por MD_AGENT_SELECTOR).
    """

    session: Any
    embedder: Any
    llm: Any = None


@runtime_checkable
class RetrievalPipeline(Protocol):
    """Contrato que deben cumplir todas las implementaciones de pipeline de retrieval.

    **`runtime_checkable` desde PLG.1**, para que el cargador de *entry points* pueda rechazar
    con `issubclass` un pipeline aportado por un paquete que no cumpla el contrato — **al
    descubrir, no en la primera petición**. Sin esto, un plugin mal escrito arranca el servidor
    sin quejarse y revienta delante de un usuario.

    El límite, dicho para que nadie lea de aquí una garantía que no da: `runtime_checkable`
    comprueba **que los métodos existan**, no sus firmas ni sus tipos. Caza el error frecuente
    —el objeto equivocado, la clase sin `run`— y no un `run` con otra signatura. Para eso está el
    contrato de pipelines de la suite, que sí lo ejecuta.
    """

    async def run(
        self,
        query: str,
        chatbot_id: str,
        cfg: "PublicGraphConfig",
        deps: GraphDeps,
        language: str | None = None,
    ) -> "RetrievalResult": ...
