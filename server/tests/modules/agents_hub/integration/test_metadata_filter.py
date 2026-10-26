"""Tests VIS.1 — recuperacion filtrada por ambito, submateria y nivel de acceso.

Contra BD real (fixture `db_session`, BD desechable): el filtro se aplica en SQL con
JOIN a `hub_documents` y con el operador de solapamiento de arrays `&&`, asi que un
fake en memoria no probaria nada de lo que este prompt garantiza.

Regla del bloque VIS: el filtro entra en el WHERE, **antes** del ORDER BY / LIMIT. El
test `should_apply_filter_in_sql_before_limit` es el que muerde si alguien vuelve a
filtrar en Python despues del top_k.
"""
from __future__ import annotations

import uuid

import pytest


# ───────────────────────── Helpers ─────────────────────────


def _emb(i: int) -> list[float]:
    """Vector unitario en la dimension i. Direcciones distintas => coseno distinto."""
    v = [0.0] * 1024
    v[i % 1024] = 1.0
    return v


async def _documento(session, chatbot_id: uuid.UUID, **kwargs):
    from server.app.modules.agents_hub.database.operational_models import HubDocument

    defaults = dict(
        chatbot_id=chatbot_id,
        title=kwargs.pop("title", "Norma de prova"),
        canonical_url=f"https://www.uji.es/{uuid.uuid4().hex[:8]}",
        markdown_content=kwargs.pop("markdown_content", "# Norma\n\nContingut."),
        content_hash=uuid.uuid4().hex + uuid.uuid4().hex,
        language="ca",
        source_kind="publicacio",
    )
    defaults.update(kwargs)
    doc = HubDocument(**defaults)
    session.add(doc)
    await session.flush()
    return doc


async def _chunk(session, chatbot_id: uuid.UUID, doc, content: str, embedding=None, **kwargs):
    from server.app.modules.agents_hub.database.operational_models import HubDocumentChunk

    chunk = HubDocumentChunk(
        chatbot_id=chatbot_id,
        document_id=doc.id if doc is not None else None,
        content=content,
        source_url=doc.canonical_url if doc is not None else "file://pujada.pdf",
        content_hash=uuid.uuid4().hex + uuid.uuid4().hex,
        embedding=embedding if embedding is not None else _emb(0),
        # HIB.U: la agrupacion por documento lee la COLUMNA, con el metadato como
        # repliegue. Quien pase `chunk_metadata` anade sus claves, no lo sustituye:
        # perder `document_id` aqui haria que la cita saliera con el titulo de otro.
        chunk_metadata={
            **({"document_id": str(doc.id)} if doc is not None else {}),
            **(kwargs.pop("chunk_metadata", None) or {}),
        },
        language=kwargs.pop("language", "ca"),
        # RAG.9: la procedencia es NOT NULL. Por defecto, la del servicio local, que es de
        # donde salió todo el corpus real hasta MOD.2; los tests que prueban el desajuste la
        # pisan explícitamente, que es justo lo que se quiere leer en ellos.
        embedding_model=kwargs.pop("embedding_model", "BAAI/bge-m3"),
        embedding_dim=kwargs.pop("embedding_dim", 1024),
        **kwargs,
    )
    session.add(chunk)
    await session.flush()
    return chunk


async def _pagina_superseded(session):
    """HubCrawledPage marcada superseded, con su sitio."""
    from server.app.modules.agents_hub.database.operational_models import (
        HubCrawledPage,
        HubWebSite,
    )

    site = HubWebSite(name="UJI", root_url="https://www.uji.es")
    session.add(site)
    await session.flush()
    page = HubCrawledPage(
        site_id=site.id,
        url=f"https://www.uji.es/{uuid.uuid4().hex[:8]}",
        superseded=True,
    )
    session.add(page)
    await session.flush()
    return page


class _FakeEmbedding:
    def __init__(self, vector: list[float]) -> None:
        self._vector = vector

    async def embed(self, text: str) -> list[float]:
        return self._vector


# ───────────────────────── Contrato del filtro ─────────────────────────


class TestContrato:

    def test_should_default_to_public_when_actor_level_unknown(self):
        """Fail-closed: nivel no determinable => 'public'. Nunca se abre por descuido."""
        from server.app.modules.agents_hub.services.retrieval.metadata_filter import (
            MetadataFilter,
        )

        assert MetadataFilter().max_nivell_acces == "public"
        assert MetadataFilter(max_nivell_acces=None).max_nivell_acces == "public"
        assert MetadataFilter(max_nivell_acces="cap-de-servei").max_nivell_acces == "public"
        assert MetadataFilter.for_actor(nivell_acces=None).max_nivell_acces == "public"
        assert MetadataFilter.for_actor(nivell_acces="intern").max_nivell_acces == "intern"

    def test_should_expose_cumulative_access_levels(self):
        from server.app.modules.agents_hub.services.retrieval.metadata_filter import (
            MetadataFilter,
        )

        assert MetadataFilter(max_nivell_acces="public").nivells_permesos == ("public",)
        assert MetadataFilter(max_nivell_acces="intern").nivells_permesos == (
            "public",
            "intern",
        )
        assert MetadataFilter(max_nivell_acces="restringit").nivells_permesos == (
            "public",
            "intern",
            "restringit",
        )


# ───────────────────────── Filtro en el retriever ─────────────────────────


class TestRetriever:

    @pytest.mark.asyncio
    async def test_should_return_only_chunks_of_requested_ambit(self, db_session):
        from server.app.modules.agents_hub.services.retrieval.metadata_filter import (
            MetadataFilter,
        )
        from server.app.modules.agents_hub.services.retriever import HybridRetriever

        cb = uuid.uuid4()
        doc_personal = await _documento(db_session, cb, ambit_principal="personal")
        doc_academic = await _documento(db_session, cb, ambit_principal="academic")
        await _chunk(db_session, cb, doc_personal, "Indemnitzacions per rao del servei")
        await _chunk(db_session, cb, doc_academic, "Permanencia en els estudis")
        await db_session.commit()

        results = await HybridRetriever(db_session).vector_search(
            _emb(0), cb, top_k=10,
            metadata_filter=MetadataFilter(ambits=("personal",)),
        )

        assert [r.content for r in results] == ["Indemnitzacions per rao del servei"]

    @pytest.mark.asyncio
    async def test_should_include_documents_matching_by_ambits_secundaris(self, db_session):
        from server.app.modules.agents_hub.services.retrieval.metadata_filter import (
            MetadataFilter,
        )
        from server.app.modules.agents_hub.services.retriever import HybridRetriever

        cb = uuid.uuid4()
        doc = await _documento(
            db_session, cb,
            ambit_principal="economic",
            ambits_secundaris=["transversal", "personal"],
        )
        await _chunk(db_session, cb, doc, "Execucio de la despesa")
        await db_session.commit()

        results = await HybridRetriever(db_session).vector_search(
            _emb(0), cb, top_k=10,
            metadata_filter=MetadataFilter(ambits=("personal",)),
        )

        assert [r.content for r in results] == ["Execucio de la despesa"]

    @pytest.mark.asyncio
    async def test_should_match_submateria_in_submateries_internes(self, db_session):
        from server.app.modules.agents_hub.services.retrieval.metadata_filter import (
            MetadataFilter,
        )
        from server.app.modules.agents_hub.services.retriever import HybridRetriever

        cb = uuid.uuid4()
        doc = await _documento(
            db_session, cb,
            submateries=["execucio-de-la-despesa"],
            submateries_internes=["retribucions-i-gratificacions"],
        )
        otro = await _documento(db_session, cb, submateries=["contractacio"])
        await _chunk(db_session, cb, doc, "Gratificacions extraordinaries")
        await _chunk(db_session, cb, otro, "Plecs de contractacio")
        await db_session.commit()

        results = await HybridRetriever(db_session).vector_search(
            _emb(0), cb, top_k=10,
            metadata_filter=MetadataFilter(
                submateries=("retribucions-i-gratificacions",)
            ),
        )

        assert [r.content for r in results] == ["Gratificacions extraordinaries"]

    @pytest.mark.asyncio
    async def test_should_exclude_intern_documents_for_public_actor(self, db_session):
        from server.app.modules.agents_hub.services.retrieval.metadata_filter import (
            MetadataFilter,
        )
        from server.app.modules.agents_hub.services.retriever import HybridRetriever

        cb = uuid.uuid4()
        publico = await _documento(db_session, cb, nivell_acces="public")
        interno = await _documento(db_session, cb, nivell_acces="intern")
        restringido = await _documento(db_session, cb, nivell_acces="restringit")
        await _chunk(db_session, cb, publico, "Text public")
        await _chunk(db_session, cb, interno, "Text intern")
        await _chunk(db_session, cb, restringido, "Text restringit")
        await db_session.commit()

        retriever = HybridRetriever(db_session)
        publicos = await retriever.vector_search(
            _emb(0), cb, top_k=10,
            metadata_filter=MetadataFilter.for_actor(nivell_acces="public"),
        )
        internos = await retriever.vector_search(
            _emb(0), cb, top_k=10,
            metadata_filter=MetadataFilter.for_actor(nivell_acces="intern"),
        )

        assert [r.content for r in publicos] == ["Text public"]
        assert sorted(r.content for r in internos) == ["Text intern", "Text public"]

    @pytest.mark.asyncio
    async def test_should_never_return_us_assistents_no_documents(self, db_session):
        """`us_assistents='no'` no se recupera ni pidiendolo con el filtro mas abierto."""
        from server.app.modules.agents_hub.services.retrieval.metadata_filter import (
            MetadataFilter,
        )
        from server.app.modules.agents_hub.services.retriever import HybridRetriever

        cb = uuid.uuid4()
        excluido = await _documento(db_session, cb, us_assistents="no")
        permitido = await _documento(db_session, cb, us_assistents="restringit")
        await _chunk(db_session, cb, excluido, "Esborrany intern no publicable")
        await _chunk(db_session, cb, permitido, "Norma consultable")
        await db_session.commit()

        retriever = HybridRetriever(db_session)
        abierto = MetadataFilter(
            max_nivell_acces="restringit",
            include_superseded=True,
        )

        vectorial = await retriever.vector_search(_emb(0), cb, top_k=10, metadata_filter=abierto)
        textual = await retriever.keyword_search("norma esborrany", cb, top_k=10, metadata_filter=abierto)

        assert all("Esborrany" not in r.content for r in vectorial)
        assert all("Esborrany" not in r.content for r in textual)
        assert "Norma consultable" in {r.content for r in vectorial}

    @pytest.mark.asyncio
    async def test_should_apply_filter_in_sql_before_limit(self, db_session):
        """El filtro no puede robar plazas del top_k: va en el WHERE, no despues del LIMIT."""
        from server.app.modules.agents_hub.services.retrieval.metadata_filter import (
            MetadataFilter,
        )
        from server.app.modules.agents_hub.services.retriever import HybridRetriever

        cb = uuid.uuid4()
        # 6 documentos del ambito equivocado, todos con similitud maxima frente a la consulta
        ruido = await _documento(db_session, cb, ambit_principal="personal")
        for i in range(6):
            await _chunk(db_session, cb, ruido, f"Soroll {i}", embedding=_emb(0))
        # 2 del ambito buscado, con similitud nula
        buscado = await _documento(db_session, cb, ambit_principal="academic")
        for i in range(2):
            await _chunk(db_session, cb, buscado, f"Rellevant {i}", embedding=_emb(500))
        await db_session.commit()

        retriever = HybridRetriever(db_session)
        sin_filtro = await retriever.vector_search(_emb(0), cb, top_k=2)
        con_filtro = await retriever.vector_search(
            _emb(0), cb, top_k=2,
            metadata_filter=MetadataFilter(ambits=("academic",)),
        )

        assert len(sin_filtro) == 2
        # Si el filtro se aplicara en Python tras el LIMIT, esto seria una lista vacia
        assert len(con_filtro) == 2
        assert all(r.content.startswith("Rellevant") for r in con_filtro)

    @pytest.mark.asyncio
    async def test_should_not_filter_temporary_chunks_by_ambit(self, db_session):
        """Los chunks temporales no tienen documento: los acota owner_id, no la taxonomia."""
        from server.app.modules.agents_hub.services.retrieval.metadata_filter import (
            MetadataFilter,
        )
        from server.app.modules.agents_hub.services.retriever import HybridRetriever

        cb = uuid.uuid4()
        owner = uuid.uuid4()
        await _chunk(
            db_session, cb, None, "Contracte pujat per l'usuari",
            is_temporary=True, owner_id=owner,
        )
        await db_session.commit()

        results = await HybridRetriever(db_session).vector_search(
            _emb(0), cb, top_k=10, owner_id=owner,
            metadata_filter=MetadataFilter(
                ambits=("academic",), submateries=("beques",)
            ),
        )

        assert [r.content for r in results] == ["Contracte pujat per l'usuari"]

    @pytest.mark.asyncio
    async def test_should_return_the_version_of_the_query_language(self, db_session):
        """ACT.3: era `test_should_exclude_non_canonical_versions`, y esa exclusion era el
        defecto —la castellana no volvia nunca—. El invariante que se conserva es que las dos
        versiones de la MISMA norma no ocupan dos plazas del top-k."""
        from server.app.modules.agents_hub.services.retrieval.metadata_filter import (
            MetadataFilter,
        )
        from server.app.modules.agents_hub.services.retriever import HybridRetriever

        cb = uuid.uuid4()
        val = await _documento(db_session, cb, language="val")
        traduccion = await _documento(
            db_session, cb, language="es", versio_idiomatica_de=val.id,
        )
        await _chunk(db_session, cb, val, "Versio valenciana")
        await _chunk(db_session, cb, traduccion, "Version castellana", language="es")
        await db_session.commit()

        retriever = HybridRetriever(db_session)
        en_val = await retriever.vector_search(
            _emb(0), cb, top_k=10, metadata_filter=MetadataFilter(query_language="val")
        )
        en_es = await retriever.vector_search(
            _emb(0), cb, top_k=10, metadata_filter=MetadataFilter(query_language="es")
        )
        sin_lengua = await retriever.vector_search(
            _emb(0), cb, top_k=10, metadata_filter=MetadataFilter()
        )

        assert [r.content for r in en_val] == ["Versio valenciana"]
        assert [r.content for r in en_es] == ["Version castellana"]
        # Sin lengua no hay regla que aplicar: es `language_mode: none`.
        assert len(sin_lengua) == 2

    @pytest.mark.asyncio
    async def test_should_exclude_superseded_in_hybrid_search(self, db_session):
        from server.app.modules.agents_hub.services.retrieval.metadata_filter import (
            MetadataFilter,
        )
        from server.app.modules.agents_hub.services.retriever import HybridRetriever

        cb = uuid.uuid4()
        page = await _pagina_superseded(db_session)
        obsoleto = await _documento(db_session, cb, crawled_page_id=page.id)
        vigente = await _documento(db_session, cb)
        await _chunk(db_session, cb, obsoleto, "Text obsolet")
        await _chunk(db_session, cb, vigente, "Text vigent")
        await db_session.commit()

        retriever = HybridRetriever(db_session)
        results = await retriever.hybrid_search(
            query="Text", query_embedding=_emb(0), chatbot_id=cb, top_k=10,
        )
        con_obsoletos = await retriever.hybrid_search(
            query="Text", query_embedding=_emb(0), chatbot_id=cb, top_k=10,
            metadata_filter=MetadataFilter(include_superseded=True),
        )

        assert [r.content for r in results] == ["Text vigent"]
        assert len(con_obsoletos) == 2


# ───────────────────────── Las otras dos estrategias ─────────────────────────


class TestEstrategias:

    @pytest.mark.asyncio
    async def test_should_apply_filter_in_long_context_strategy(self, db_session):
        from server.app.modules.agents_hub.services.retrieval.long_context_strategy import (
            LongContextRetrievalStrategy,
        )
        from server.app.modules.agents_hub.services.retrieval.metadata_filter import (
            MetadataFilter,
        )

        cb = uuid.uuid4()
        await _documento(db_session, cb, title="Personal", ambit_principal="personal")
        await _documento(db_session, cb, title="Academic", ambit_principal="academic")
        await db_session.commit()

        ctx = await LongContextRetrievalStrategy(
            db_session, metadata_filter=MetadataFilter(ambits=("academic",))
        ).get_context(query="q", chatbot_id=cb)

        assert [s.title for s in ctx.sources] == ["Academic"]

    @pytest.mark.asyncio
    async def test_should_apply_filter_in_agentic_index(self, db_session):
        from server.app.modules.agents_hub.services.retrieval.agentic_strategy import (
            AgenticRetrievalStrategy,
        )
        from server.app.modules.agents_hub.services.retrieval.metadata_filter import (
            MetadataFilter,
        )

        cb = uuid.uuid4()
        await _documento(db_session, cb, title="Personal", ambit_principal="personal")
        await _documento(db_session, cb, title="Academic", ambit_principal="academic")
        await db_session.commit()

        index = await AgenticRetrievalStrategy(
            db_session, metadata_filter=MetadataFilter(ambits=("academic",))
        ).list_index(cb, language=None)

        assert [d["title"] for d in index] == ["Academic"]

    @pytest.mark.asyncio
    async def test_should_exclude_superseded_in_all_three_strategies(self, db_session):
        """Un documento de pagina superseded no se sirve por ninguna de las tres vias."""
        from server.app.modules.agents_hub.services.retrieval.agentic_strategy import (
            AgenticRetrievalStrategy,
        )
        from server.app.modules.agents_hub.services.retrieval.long_context_strategy import (
            LongContextRetrievalStrategy,
        )
        from server.app.modules.agents_hub.services.retrieval.vector_strategy import (
            VectorRetrievalStrategy,
        )

        cb = uuid.uuid4()
        page = await _pagina_superseded(db_session)
        obsoleto = await _documento(db_session, cb, title="Obsolet", crawled_page_id=page.id)
        vigente = await _documento(db_session, cb, title="Vigent")
        await _chunk(db_session, cb, obsoleto, "Text obsolet")
        await _chunk(db_session, cb, vigente, "Text vigent")
        await db_session.commit()

        rag = await VectorRetrievalStrategy(
            db_session, _FakeEmbedding(_emb(0)), top_k=10
        ).get_context(query="Text", chatbot_id=cb)
        largo = await LongContextRetrievalStrategy(db_session).get_context(
            query="Text", chatbot_id=cb
        )
        index = await AgenticRetrievalStrategy(db_session).list_index(cb, language=None)

        assert [s.title for s in rag.sources] == ["Vigent"]
        assert [s.title for s in largo.sources] == ["Vigent"]
        assert [d["title"] for d in index] == ["Vigent"]

    @pytest.mark.asyncio
    async def test_should_apply_filter_in_document_index_provider(self, db_session):
        """El indice del selector es la cuarta via: filtrarlo o el titulo delata el documento."""
        from server.app.modules.agents_hub.agent.public_graphs.strategies.md_agent_selector_pipeline import (
            DocumentIndexProvider,
        )

        cb = uuid.uuid4()
        await _documento(db_session, cb, title="Public", nivell_acces="public")
        await _documento(db_session, cb, title="Intern", nivell_acces="intern")
        await _documento(db_session, cb, title="Exclos", us_assistents="no")
        await db_session.commit()

        class _Deps:
            session = db_session

        items = await DocumentIndexProvider().build_index(str(cb), _Deps())

        assert [i.title for i in items] == ["Public"]

    @pytest.mark.asyncio
    async def test_should_not_leak_intern_documents_through_any_strategy(self, db_session):
        """Criterio de done de VIS.1: un actor 'public' no ve NI UN chunk 'intern'."""
        from server.app.modules.agents_hub.services.retrieval.agentic_strategy import (
            AgenticRetrievalStrategy,
        )
        from server.app.modules.agents_hub.services.retrieval.long_context_strategy import (
            LongContextRetrievalStrategy,
        )
        from server.app.modules.agents_hub.services.retrieval.metadata_filter import (
            MetadataFilter,
        )
        from server.app.modules.agents_hub.services.retrieval.vector_strategy import (
            VectorRetrievalStrategy,
        )

        cb = uuid.uuid4()
        interno = await _documento(db_session, cb, title="Intern", nivell_acces="intern")
        publico = await _documento(db_session, cb, title="Public", nivell_acces="public")
        await _chunk(db_session, cb, interno, "Dades internes de gerencia")
        await _chunk(db_session, cb, publico, "Informacio publica")
        await db_session.commit()

        publico_filtro = MetadataFilter.for_actor(nivell_acces=None)
        rag = await VectorRetrievalStrategy(
            db_session, _FakeEmbedding(_emb(0)), top_k=10,
            metadata_filter=publico_filtro,
        ).get_context(query="Dades", chatbot_id=cb)
        largo = await LongContextRetrievalStrategy(
            db_session, metadata_filter=publico_filtro
        ).get_context(query="Dades", chatbot_id=cb)
        index = await AgenticRetrievalStrategy(
            db_session, metadata_filter=publico_filtro
        ).list_index(cb, language=None)

        assert [s.title for s in rag.sources] == ["Public"]
        assert all("internes" not in s.excerpt for s in rag.sources)
        assert [s.title for s in largo.sources] == ["Public"]
        assert [d["title"] for d in index] == ["Public"]
