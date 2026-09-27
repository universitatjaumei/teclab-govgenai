"""Tests de integración — metadatos del corpus contra BD real (Prompt ING.0.2).

Usa la fixture `db_session` del conftest de este directorio: BD desechable por test.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import func, select, text


async def _documento(session, **kwargs):
    from server.app.modules.agents_hub.database.operational_models import HubDocument

    defaults = dict(
        chatbot_id=kwargs.pop("chatbot_id", uuid.uuid4()),
        title="Reglament de prova",
        canonical_url=f"https://www.uji.es/{uuid.uuid4().hex[:8]}",
        markdown_content="# Reglament",
        content_hash=uuid.uuid4().hex + uuid.uuid4().hex,
        language="ca",
        source_kind="publicacio",
    )
    defaults.update(kwargs)
    doc = HubDocument(**defaults)
    session.add(doc)
    await session.flush()
    return doc


class TestPersistencia:

    @pytest.mark.asyncio
    async def test_should_default_new_document_to_public_and_canonical(self, db_session):
        doc = await _documento(db_session)
        await db_session.commit()
        await db_session.refresh(doc)

        assert doc.nivell_acces == "public"
        assert doc.us_assistents == "si"
        assert doc.content_class == "generic"
        assert doc.submateries == []
        assert doc.doc_metadata == {}

    @pytest.mark.asyncio
    async def test_should_persist_and_read_back_submateries_array(self, db_session):
        doc = await _documento(
            db_session,
            ambit_principal="administracio",
            ambits_secundaris=["transversal"],
            submateries=["indemnitzacions-i-dietes", "execucio-de-la-despesa"],
            submateries_internes=["retribucions-i-gratificacions"],
        )
        await db_session.commit()
        await db_session.refresh(doc)

        assert doc.submateries == ["indemnitzacions-i-dietes", "execucio-de-la-despesa"]
        assert doc.submateries_internes == ["retribucions-i-gratificacions"]
        assert doc.ambits_secundaris == ["transversal"]

    @pytest.mark.asyncio
    async def test_should_persist_arbitrary_schema_fields_in_doc_metadata(self, db_session):
        """Los 56 campos del esquema que no se filtran viven aquí."""
        payload = {
            "rang": "reglament",
            "aplica_a": ["PDI", "PTGAS"],
            "resum_router": "Regula les indemnitzacions per raó del servei.",
            "preguntes_tipus": ["quant cobro de dieta per anar a Madrid?"],
            "termes_bilingues": ["despesa/gasto", "dieta"],
            "tipus_font": "normativa",
            "deroga": ["REG-011"],
            "url_oficial": "https://www.uji.es/norma",
        }
        doc = await _documento(db_session, doc_metadata=payload)
        await db_session.commit()
        await db_session.refresh(doc)

        assert doc.doc_metadata["preguntes_tipus"][0].startswith("quant cobro")
        assert doc.doc_metadata["deroga"] == ["REG-011"]

    @pytest.mark.asyncio
    async def test_persiste_bloque_de_vigencia_y_revision(self, db_session):
        ahora = datetime.now(timezone.utc)
        doc = await _documento(
            db_session,
            content_class="regulation",
            estat_vigencia="vigent",
            vigencia_validada_el=ahora,
            revisat_per="Secretaria General",
            revisat_el=ahora,
            data_revisio_prevista=date(2027, 1, 1),
            id_publicacio="REG-020",
            last_seen_at=ahora,
        )
        await db_session.commit()
        await db_session.refresh(doc)

        assert doc.id_publicacio == "REG-020"
        assert doc.estat_vigencia == "vigent"
        assert doc.data_revisio_prevista == date(2027, 1, 1)

    @pytest.mark.asyncio
    async def test_rechaza_nivell_acces_fuera_de_la_enumeracion(self, db_session):
        with pytest.raises(Exception):
            await _documento(db_session, nivell_acces="inventado")
            await db_session.commit()

    @pytest.mark.asyncio
    async def test_acepta_cualquier_codigo_de_submateria(self, db_session):
        """El vocabulario se valida en la capa de contrato (ING.0.3), no con un CHECK:
        tiene que poder cambiar sin migración."""
        doc = await _documento(db_session, submateries=["submateria-que-no-existe-aun"])
        await db_session.commit()
        assert doc.submateries == ["submateria-que-no-existe-aun"]


class TestForeignKeyDeChunks:

    async def _chunk(self, session, chatbot_id, document_id, **kw):
        from server.app.modules.agents_hub.database.operational_models import (
            HubDocumentChunk,
        )

        chunk = HubDocumentChunk(
            chatbot_id=chatbot_id,
            document_id=document_id,
            content="Text del fragment",
            source_url="https://www.uji.es/norma",
            content_hash=uuid.uuid4().hex,
            language="ca",
            embedding_model=kw.pop("embedding_model", "BAAI/bge-m3"),
            embedding_dim=kw.pop("embedding_dim", 1024),
            **kw,
        )
        session.add(chunk)
        await session.flush()
        return chunk

    @pytest.mark.asyncio
    async def test_should_reject_chunk_with_dangling_document_id(self, db_session):
        chatbot_id = uuid.uuid4()
        with pytest.raises(Exception):
            await self._chunk(db_session, chatbot_id, uuid.uuid4())

    @pytest.mark.asyncio
    async def test_should_cascade_chunk_deletion_when_document_deleted(self, db_session):
        from server.app.modules.agents_hub.database.operational_models import (
            HubDocumentChunk,
        )

        chatbot_id = uuid.uuid4()
        doc = await _documento(db_session, chatbot_id=chatbot_id)
        await self._chunk(db_session, chatbot_id, doc.id)
        await self._chunk(db_session, chatbot_id, doc.id)
        await db_session.commit()

        await db_session.delete(doc)
        await db_session.commit()

        total = await db_session.scalar(
            select(func.count()).select_from(HubDocumentChunk)
        )
        assert total == 0

    @pytest.mark.asyncio
    async def test_should_allow_null_document_id_for_temporary_chunks(self, db_session):
        chatbot_id = uuid.uuid4()
        chunk = await self._chunk(
            db_session, chatbot_id, None, is_temporary=True, owner_id=uuid.uuid4()
        )
        await db_session.commit()
        assert chunk.document_id is None


class TestIndicesEnBd:

    @pytest.mark.asyncio
    async def test_should_have_gin_index_on_submateries(self, db_session):
        rows = await db_session.execute(
            text(
                "select indexname, indexdef from pg_indexes "
                "where tablename = 'hub_documents'"
            )
        )
        defs = {name: definicion for name, definicion in rows.all()}
        gin_submateries = [
            d for d in defs.values() if "gin" in d.lower() and "submateries" in d
        ]
        assert gin_submateries, f"sin indice GIN sobre submateries: {defs}"

    @pytest.mark.asyncio
    async def test_overlap_operator_funciona_sobre_el_array(self, db_session):
        """El operador && es el que usará VIS.1 para filtrar por submateria."""
        from server.app.modules.agents_hub.database.operational_models import HubDocument

        chatbot_id = uuid.uuid4()
        await _documento(
            db_session, chatbot_id=chatbot_id, submateries=["dietes", "convenis"]
        )
        await _documento(db_session, chatbot_id=chatbot_id, submateries=["avaluacio"])
        await db_session.commit()

        encontrados = await db_session.execute(
            select(HubDocument.id).where(
                HubDocument.chatbot_id == chatbot_id,
                HubDocument.submateries.overlap(["convenis", "inexistente"]),
            )
        )
        assert len(encontrados.all()) == 1


class TestReclasificacion:
    """La deuda que ING.0.1 dejó: el barrido de documentos al sustituir un término.

    **El ámbito es obligatorio desde la revisión de la PR #178**: `chatbot_ids` no tiene valor
    por omisión, porque el que tenía —`chatbot_id=None`— hacía que el barrido cruzara la frontera
    entre organizaciones. Estos tests lo pasan explícito, que es justo lo que se quería forzar.
    """

    @pytest.mark.asyncio
    async def test_should_replace_submateria_in_both_arrays(self, db_session):
        from server.app.modules.agents_hub.services.corpus_reclassifier import (
            reclassify_documents,
        )

        chatbot_id = uuid.uuid4()
        doc = await _documento(
            db_session,
            chatbot_id=chatbot_id,
            submateries=["rrhh-ptgas", "convenis"],
            submateries_internes=["rrhh-ptgas"],
        )
        await db_session.commit()

        tocados = await reclassify_documents(
            db_session,
            "submateria",
            "rrhh-ptgas",
            "rrhh-ptgas-condicions",
            chatbot_ids=[chatbot_id],
        )
        await db_session.commit()
        await db_session.refresh(doc)

        assert tocados == 1
        assert doc.submateries == ["rrhh-ptgas-condicions", "convenis"]
        assert doc.submateries_internes == ["rrhh-ptgas-condicions"]

    @pytest.mark.asyncio
    async def test_should_replace_ambit_principal_and_secundaris(self, db_session):
        from server.app.modules.agents_hub.services.corpus_reclassifier import (
            reclassify_documents,
        )

        chatbot_id = uuid.uuid4()
        doc = await _documento(
            db_session,
            chatbot_id=chatbot_id,
            ambit_principal="administracio",
            ambits_secundaris=["administracio"],
        )
        await db_session.commit()

        tocados = await reclassify_documents(
            db_session, "ambit", "administracio", "gerencia", chatbot_ids=[chatbot_id]
        )
        await db_session.commit()
        await db_session.refresh(doc)

        assert tocados == 1
        assert doc.ambit_principal == "gerencia"
        assert doc.ambits_secundaris == ["gerencia"]

    @pytest.mark.asyncio
    async def test_should_scope_to_chatbot_when_given(self, db_session):
        from server.app.modules.agents_hub.services.corpus_reclassifier import (
            reclassify_documents,
        )

        uno, otro = uuid.uuid4(), uuid.uuid4()
        mio = await _documento(db_session, chatbot_id=uno, submateries=["vieja"])
        ajeno = await _documento(db_session, chatbot_id=otro, submateries=["vieja"])
        await db_session.commit()

        tocados = await reclassify_documents(
            db_session, "submateria", "vieja", "nueva", chatbot_ids=[uno]
        )
        await db_session.commit()
        await db_session.refresh(mio)
        await db_session.refresh(ajeno)

        assert tocados == 1
        assert mio.submateries == ["nueva"]
        assert ajeno.submateries == ["vieja"]

    @pytest.mark.asyncio
    async def test_should_not_touch_chunks(self, db_session):
        """Reclasificar cuesta un UPDATE. Si toca chunks, hay re-embedding y la
        promesa de vocabulario revisable se rompe (CLAUDE.md §5)."""
        from server.app.modules.agents_hub.database.operational_models import (
            HubDocumentChunk,
        )
        from server.app.modules.agents_hub.services.corpus_reclassifier import (
            reclassify_documents,
        )

        chatbot_id = uuid.uuid4()
        doc = await _documento(db_session, chatbot_id=chatbot_id, submateries=["vieja"])
        chunk = HubDocumentChunk(
            chatbot_id=chatbot_id,
            document_id=doc.id,
            content="Text",
            source_url="https://www.uji.es/x",
            content_hash=uuid.uuid4().hex,
            language="ca",
            embedding=[0.5] * 1024,
            embedding_model="BAAI/bge-m3",
            embedding_dim=1024,
        )
        db_session.add(chunk)
        await db_session.commit()
        antes = chunk.content_hash

        await reclassify_documents(
            db_session, "submateria", "vieja", "nueva", chatbot_ids=[chatbot_id]
        )
        await db_session.commit()
        await db_session.refresh(chunk)

        assert chunk.content_hash == antes
        assert chunk.embedding is not None
        total = await db_session.scalar(
            select(func.count()).select_from(HubDocumentChunk)
        )
        assert total == 1

    @pytest.mark.asyncio
    async def test_should_be_idempotent(self, db_session):
        from server.app.modules.agents_hub.services.corpus_reclassifier import (
            reclassify_documents,
        )

        chatbot_id = uuid.uuid4()
        await _documento(db_session, chatbot_id=chatbot_id, submateries=["vieja"])
        await db_session.commit()

        primera = await reclassify_documents(
            db_session, "submateria", "vieja", "nueva", chatbot_ids=[chatbot_id]
        )
        await db_session.commit()
        segunda = await reclassify_documents(
            db_session, "submateria", "vieja", "nueva", chatbot_ids=[chatbot_id]
        )
        await db_session.commit()

        assert primera == 1
        assert segunda == 0

    @pytest.mark.asyncio
    async def test_should_reject_unknown_axis(self, db_session):
        from server.app.modules.agents_hub.services.corpus_reclassifier import (
            reclassify_documents,
        )

        with pytest.raises(ValueError):
            await reclassify_documents(
                db_session, "rang", "a", "b", chatbot_ids=[uuid.uuid4()]
            )
