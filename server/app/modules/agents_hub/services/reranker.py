"""Reranking de candidatos detrás de protocolo (RAG.6a). Deploy: edge.

Un reranker es un cross-encoder: en vez de comparar dos vectores calculados por separado,
lee consulta y candidato **juntos** y puntúa cuán bien responde el uno al otro. Por eso
mejora sobre la fusión híbrida, y por eso cuesta más: no se puede precalcular.

**Este módulo es RAG.6a: el mecanismo.** El adaptador contra el Ranking API de Vertex y la
medición de si el valenciano está entre sus 25 idiomas son RAG.6b, que va después del
despliegue porque ese servicio lo habilita D.0. Ver
`docs/DECISION_MODELOS_EMBEDDING_RERANKER.md`.

Tres reglas heredadas de lo aprendido en los prompts anteriores:

- **Sin fallback silencioso** (CLAUDE.md). Si el flag está encendido y el proveedor no se
  sabe hablar, error explícito. Degradar al híbrido sin avisar dejaría al admin creyendo que
  el reranker actúa cuando no lo hace, que es peor que no tenerlo.
- **El proveedor es configuración**, no una constante: fila de `HubLLMConfig` con
  `purpose='rerank'`, y el adaptador se elige por `provider_type` igual que en MOD.2.
- **Los scores salen en [0,1]**. El packer de RAG.5 corta por score y el quality gate
  promedia: si el reranker devolviera logits crudos, esos dos controles decidirían sobre
  números incomparables con el resto del sistema.
"""
from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.modules.agents_hub.database.config_models import HubLLMConfig, HubProvider

PURPOSE_RERANK = "rerank"
PROVIDER_TYPE_VERTEX_RANKING = "discovery_engine"

# El Ranking API es global: no tiene réplica regional propia como Vertex AI, y pedirle una
# región devuelve 404. Verificado el 2026-08-24 contra `uji-teclab`.
LOCATION_RANKING = "global"
RANKING_CONFIG = "default_ranking_config"
MODELO_RANKING_POR_DEFECTO = "semantic-ranker-default-004"
SCOPE_CLOUD = "https://www.googleapis.com/auth/cloud-platform"

# El pool que se le ofrece al reranker. Con `top_k` candidatos no habría nada que reordenar:
# el reranker solo puede mejorar lo que le llega.
POOL_MINIMO = 30
POOL_FACTOR = 3


@dataclass(frozen=True)
class RerankResult:
    """Posición del candidato en la lista de entrada y su score en [0,1]."""

    index: int
    score: float


@runtime_checkable
class Reranker(Protocol):
    async def rerank(
        self, query: str, candidates: list[str], top_k: int
    ) -> list[RerankResult]: ...


class RerankerNotConfigured(Exception):
    """El reranking está activado pero no hay ningún modelo configurado."""


class RerankerProviderNotSupported(Exception):
    """El `provider_type` configurado no tiene adaptador de reranking."""


def normalize_score(raw: float) -> float:
    """Sigmoide: lleva el logit de un cross-encoder a [0,1] de forma monótona.

    Monótona importa más que la forma exacta: el orden que decide el reranker se conserva, y
    el número queda en la misma escala que el resto del sistema.
    """
    return 1.0 / (1.0 + math.exp(-raw))


def pool_size(top_k: int) -> int:
    """Cuántos candidatos pedirle al híbrido cuando hay reranker."""
    return max(POOL_MINIMO, top_k * POOL_FACTOR)


class LocalReranker:
    """Cross-encoder BGE-reranker-v2-m3 en local. **Opción de edge, no del despliegue principal.**

    El import de `sentence_transformers` es perezoso a propósito: así el contenedor de cloud
    puede dejar de empaquetarlo cuando los embeddings sean por API, y este módulo no lo
    arrastra por el mero hecho de existir.
    """

    MODEL_NAME = "BAAI/bge-reranker-v2-m3"

    def __init__(self, model_name: str | None = None) -> None:
        self._model_name = model_name or self.MODEL_NAME
        self._model = None

    @property
    def model_name(self) -> str:
        return self._model_name

    def _get_model(self):
        if self._model is None:
            from server.app.modules.agents_hub.services.embedding_service import (
                FALTA_EL_EXTRA,
            )

            try:
                from sentence_transformers import CrossEncoder
            except ImportError as falta:
                raise RuntimeError(
                    FALTA_EL_EXTRA.format(para="el reranker local")
                ) from falta

            self._model = CrossEncoder(self._model_name)
        return self._model

    async def rerank(
        self, query: str, candidates: list[str], top_k: int
    ) -> list[RerankResult]:
        import asyncio

        def _puntuar() -> list[float]:
            return [
                float(v)
                for v in self._get_model().predict([(query, c) for c in candidates])
            ]

        crudos = await asyncio.to_thread(_puntuar)
        puntuados = sorted(
            (RerankResult(index=i, score=normalize_score(v)) for i, v in enumerate(crudos)),
            key=lambda r: r.score,
            reverse=True,
        )
        return puntuados[:top_k]


class VertexRankingReranker:
    """Ranking API de Vertex (Discovery Engine). **El reranker del despliegue.**

    Autentica con **ADC**, igual que `VertexEmbeddingService`: no hay clave que repartir ni
    rotar. Habla por `httpx.AsyncClient` y no por el cliente de `google-cloud-discoveryengine`
    porque ese es síncrono, y envolverlo en un hilo para cumplir la regla de asincronía total
    de `AGENTS.md` añadiría una dependencia de ~100 MB para acabar haciendo un POST.

    **Sus scores ya vienen en [0,1] y NO se normalizan.** Es la diferencia de contrato con
    `LocalReranker`, cuyo cross-encoder devuelve logits y sí necesita la sigmoide. Medido el
    2026-08-24: 0,7944 / 0,0504 / 0,01 sobre tres candidatos en valenciano. Pasar eso por
    `normalize_score` convertiría el 0,01 en 0,502 y el packer de RAG.5 vería un candidato
    irrelevante como mediano.
    """

    def __init__(
        self,
        model_name: str | None = None,
        project: str | None = None,
        credenciales: Any = None,
        cliente_factory: Any = None,
    ) -> None:
        import os

        self._model_name = model_name or MODELO_RANKING_POR_DEFECTO
        self._project = project if project is not None else os.getenv(
            "GOOGLE_CLOUD_PROJECT", ""
        )
        if not self._project:
            raise RuntimeError(
                "El Ranking API de Vertex necesita saber contra qué proyecto habla, y "
                "GOOGLE_CLOUD_PROJECT no está definida. Ponla en el entorno y autentícate "
                "con:\n    gcloud auth application-default login\n"
                "No hace falta ninguna clave de API: usa las credenciales por defecto de la "
                "aplicación (ADC)."
            )
        self._credenciales = credenciales
        self._cliente_factory = cliente_factory

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def url(self) -> str:
        return (
            "https://discoveryengine.googleapis.com/v1/projects/"
            f"{self._project}/locations/{LOCATION_RANKING}/rankingConfigs/"
            f"{RANKING_CONFIG}:rank"
        )

    def _token(self) -> str:
        if self._credenciales is None:
            import google.auth

            self._credenciales, _ = google.auth.default(scopes=[SCOPE_CLOUD])
        if not getattr(self._credenciales, "valid", False):
            from google.auth.transport.requests import Request

            self._credenciales.refresh(Request())
        return self._credenciales.token

    def _cliente(self):
        if self._cliente_factory is not None:
            return self._cliente_factory()
        import httpx

        return httpx.AsyncClient(timeout=20.0)

    async def rerank(
        self, query: str, candidates: list[str], top_k: int
    ) -> list[RerankResult]:
        # Sin candidatos no hay nada que reordenar, y el API rechaza la petición vacía:
        # llamar sería pagar una consulta para no obtener nada.
        if not candidates:
            return []

        cuerpo = {
            "model": self._model_name,
            "topN": top_k,
            "query": query,
            # El id es la posición en la lista de entrada: es lo que permite devolver
            # índices del protocolo después de que el API reordene.
            "records": [
                {"id": str(i), "content": texto} for i, texto in enumerate(candidates)
            ],
        }
        cabeceras = {"Authorization": f"Bearer {self._token()}"}

        async with self._cliente() as cliente:
            respuesta = await cliente.post(self.url, json=cuerpo, headers=cabeceras)
            respuesta.raise_for_status()
            datos = respuesta.json()

        return [
            RerankResult(index=int(registro["id"]), score=float(registro.get("score", 0.0)))
            for registro in datos.get("records", [])
        ][:top_k]


async def resolve_reranker(
    session: AsyncSession,
    chatbot_id: uuid.UUID | None = None,  # noqa: ARG001 — el reranker es la fila de plataforma `purpose=rerank`; no hay nivel de chatbot
    credenciales: Any = None,
) -> Any:
    """Reranker configurado, o excepción explícita. Nunca None.

    Devolver None obligaría a cada llamante a decidir qué hacer, y la decisión cómoda es
    seguir sin reranker — o sea, el fallback silencioso por la puerta de atrás.
    """
    fila = await session.execute(
        select(HubLLMConfig)
        .where(HubLLMConfig.purpose == PURPOSE_RERANK)
        .where(HubLLMConfig.is_default.is_(True))
        .limit(1)
    )
    config = fila.scalars().first()
    if config is None:
        raise RerankerNotConfigured(
            "El reranking está activado pero no hay ninguna configuración con "
            "purpose='rerank' marcada como default. Configúrala en /hub/llm-configs o "
            "desactiva reranker_enabled: seguir sin reranker en silencio haría creer que "
            "está actuando."
        )

    proveedor = await session.get(HubProvider, config.provider)
    tipo = getattr(proveedor, "provider_type", None)

    if tipo == PROVIDER_TYPE_VERTEX_RANKING:
        return VertexRankingReranker(
            model_name=config.model_name, credenciales=credenciales
        )

    if tipo == "local":
        return LocalReranker(model_name=config.model_name)

    raise RerankerProviderNotSupported(
        f"El proveedor '{config.provider}' es de tipo '{tipo}', y no hay adaptador de "
        f"reranking para ese tipo. Los que hay: '{PROVIDER_TYPE_VERTEX_RANKING}' (Ranking "
        "API de Vertex, el del despliegue) y 'local' (cross-encoder BGE, opción de edge)."
    )
