"""Resolución del servicio de embeddings desde la configuración (MOD.2). Deploy: shared.

Hasta aquí el servicio se elegía con un `import`: `get_embedding_service()` devolvía el local
incondicionalmente y `GoogleEmbeddingService` llevaba meses siendo código inalcanzable. Con
esto, un despliegue que por requisito regulatorio no pueda sacar el dato configura BGE-M3
local y otro configura Google: **misma imagen, distinta fila de configuración**.

**El adaptador se elige por `HubProvider.provider_type`**, que es el mismo mecanismo que
`model_factory` usa para el chat. Consecuencia deliberada: añadir un modelo o cambiar de
proveedor dentro de un tipo ya soportado es un UPDATE; solo un **tipo** de proveedor nuevo
—un protocolo que nadie habla aún— exige escribir un adaptador. Esa frontera es irreducible.

**Sin fallback silencioso** (CLAUDE.md): si el proveedor configurado no se sabe hablar, error
explícito. Degradar a local sin avisar dejaría medio corpus en un espacio vectorial y medio
en otro, y el coseno entre ambos no da error: da resultados malos.

**Sin configuración, local.** Así los tests y el desarrollo no salen a la red por accidente,
y una clave que falta no se convierte en una factura ni en un fallo a mitad de una ingesta.
"""
from __future__ import annotations

import uuid
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.modules.agents_hub.database.config_models import (
    HubChatbot,
    HubLLMConfig,
    HubProvider,
)
from server.app.modules.agents_hub.services.embedding_service import (
    DIMENSION_PLATAFORMA,
    GoogleEmbeddingService,
    LocalEmbeddingService,
    VertexEmbeddingService,
    get_embedding_service,
)

PURPOSE_EMBEDDING = "embedding"


class EmbeddingProviderNotSupported(Exception):
    """El `provider_type` configurado no tiene adaptador de embeddings."""


async def _config_de_embeddings(
    session: AsyncSession, chatbot_id: uuid.UUID | None
) -> HubLLMConfig | None:
    """Configuración efectiva de embeddings, con la misma cascada que el resto.

    Chatbot → organización → plataforma. Hoy la override por chatbot y por organización no
    tiene columna propia —no se ha pedido—, así que la cascada se reduce al default de
    plataforma: la fila `purpose='embedding'` marcada `is_default`. El punto de extensión
    queda aquí, que es donde se buscará cuando haga falta.
    """
    if chatbot_id is not None:
        await session.get(HubChatbot, chatbot_id)  # valida que el chatbot existe

    fila = await session.execute(
        select(HubLLMConfig)
        .where(HubLLMConfig.purpose == PURPOSE_EMBEDDING)
        .where(HubLLMConfig.is_default.is_(True))
        .limit(1)
    )
    return fila.scalars().first()


async def resolve_embedding_service(
    session: AsyncSession,
    chatbot_id: uuid.UUID | None = None,
    client_factory: Callable[..., Any] | None = None,
) -> Any:
    """Servicio de embeddings que toca usar, según la configuración vigente.

    `client_factory` existe para los tests: permite construir el adaptador sin cliente real
    y sin red. En producción va a None y cada adaptador crea el suyo.
    """
    config = await _config_de_embeddings(session, chatbot_id)
    if config is None:
        return get_embedding_service()

    proveedor = await session.get(HubProvider, config.provider)
    tipo = getattr(proveedor, "provider_type", None)

    if tipo == "google_vertexai":
        return VertexEmbeddingService(
            model_name=config.model_name,
            output_dimensionality=config.output_dimensionality or DIMENSION_PLATAFORMA,
            client=client_factory() if client_factory else None,
            # #370 — la misma región que el chat de este proveedor; nula = la del entorno.
            location=getattr(proveedor, "location", None),
        )

    if tipo == "google_genai":
        return GoogleEmbeddingService(
            model_name=config.model_name,
            output_dimensionality=config.output_dimensionality or DIMENSION_PLATAFORMA,
            client=client_factory() if client_factory else None,
        )

    if tipo == "local":
        return LocalEmbeddingService()

    raise EmbeddingProviderNotSupported(
        f"El proveedor '{config.provider}' es de tipo '{tipo}', y no hay adaptador de "
        "embeddings para ese tipo. Configura un proveedor soportado "
        "('google_vertexai', 'google_genai' o 'local') o añade el adaptador: degradar a "
        "local en silencio dejaría el corpus repartido entre dos espacios vectoriales "
        "incompatibles."
    )
