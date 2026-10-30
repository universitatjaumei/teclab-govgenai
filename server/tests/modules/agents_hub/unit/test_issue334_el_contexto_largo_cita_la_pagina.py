"""#334 — el contexto largo y el agéntico citan la misma URL que el vectorial.

Las tres estrategias que entregan documentos enteros construían la URL de la evidencia con
`canonical_url` tal cual, y el vectorial con `url_de_cita` (PUB.3, #14, #157). Con el sitio
publicado configurado, el vectorial enlazaba la página del documento y el contexto largo su
PDF oficial; y un documento cuyo `canonical_url` es el nombre del fichero —`…_merits_docents.md`—
llegaba al modelo como si fuera una dirección, y el modelo la enlazaba: `….md#faq-4`.

Medido sobre un corpus de 23 documentos y 25 preguntas de prueba: cinco enlaces a `.md` en el
contexto largo, ninguno en el vectorial sobre el mismo corpus.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from server.app.modules.agents_hub.services.retrieval.citations import BASE_DEL_SITIO

SITIO = "https://normativa.example.org"
PDF = "https://example.org/oficial/reglament.pdf"


def _documento(canonical_url: str = PDF, relative_path: str | None = "val_Reglament.md"):
    return SimpleNamespace(
        id=uuid.uuid4(),
        title="Reglament",
        canonical_url=canonical_url,
        doc_metadata={"relative_path": relative_path} if relative_path else {},
        source_kind="corpus",
        markdown_content="## Article 1 {#art-1}\nText",
        language="ca",
        token_count=100,
        submateries=[],
        estat_vigencia=None,
        created_at=None,
    )


def _sesion(documentos: list) -> AsyncMock:
    resultado = MagicMock()
    resultado.scalars.return_value.all.return_value = documentos
    sesion = AsyncMock()
    sesion.execute = AsyncMock(return_value=resultado)
    sesion.get = AsyncMock(return_value=documentos[0] if documentos else None)
    return sesion


@pytest.fixture
def con_sitio(monkeypatch):
    monkeypatch.setenv(BASE_DEL_SITIO, SITIO)


async def _url_del_contexto_largo(documento) -> str:
    from server.app.modules.agents_hub.services.retrieval.long_context_strategy import (
        LongContextRetrievalStrategy,
    )

    sesion = _sesion([documento])
    sesion.get = AsyncMock(return_value=SimpleNamespace(use_prompt_caching=False, cache_ttl=3600))
    ctx = await LongContextRetrievalStrategy(sesion).get_context("p", uuid.uuid4())
    return ctx.sources[0].url


@pytest.mark.asyncio
async def test_el_contexto_largo_cita_la_pagina_del_sitio(con_sitio) -> None:
    assert await _url_del_contexto_largo(_documento()) == f"{SITIO}/html/val_Reglament.html"


@pytest.mark.asyncio
async def test_el_contexto_largo_no_entrega_un_nombre_de_fichero_como_url(monkeypatch) -> None:
    """Sin sitio publicado, un `canonical_url` que no es una dirección no se entrega (#14)."""
    monkeypatch.delenv(BASE_DEL_SITIO, raising=False)

    url = await _url_del_contexto_largo(_documento(canonical_url="val_Respostes_OPAQ.md"))

    assert url == ""


@pytest.mark.asyncio
async def test_el_indice_del_agentico_cita_la_pagina_del_sitio(con_sitio) -> None:
    from server.app.modules.agents_hub.services.retrieval.agentic_strategy import (
        AgenticRetrievalStrategy,
    )
    from server.app.modules.agents_hub.services.retrieval.metadata_filter import MetadataFilter

    fichas = await AgenticRetrievalStrategy(_sesion([_documento()]))._fichas(
        uuid.uuid4(), None, MetadataFilter()
    )

    assert fichas[0]["url"] == f"{SITIO}/html/val_Reglament.html"


@pytest.mark.asyncio
async def test_lo_que_lee_el_agentico_cita_la_pagina_del_sitio(con_sitio, monkeypatch) -> None:
    from server.app.modules.agents_hub.services.retrieval.agentic_strategy import (
        AgenticRetrievalStrategy,
    )

    estrategia = AgenticRetrievalStrategy(_sesion([_documento()]))
    monkeypatch.setattr(estrategia, "_variant_id", AsyncMock(return_value=None))

    leido = await estrategia.read(uuid.uuid4())

    assert leido is not None
    assert leido["url"] == f"{SITIO}/html/val_Reglament.html"


@pytest.mark.asyncio
async def test_el_indice_del_selector_cita_la_pagina_del_sitio(con_sitio) -> None:
    from server.app.modules.agents_hub.agent.public_graphs.strategies import (
        md_agent_selector_pipeline as modulo,
    )

    item = modulo._a_evidencia(_documento(), {})

    assert item.source_url == f"{SITIO}/html/val_Reglament.html"
