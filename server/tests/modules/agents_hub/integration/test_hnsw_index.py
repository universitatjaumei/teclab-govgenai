"""Tests RAG.3 — índice HNSW en pgvector para la búsqueda vectorial.

Sin índice ANN, cada consulta recorre todos los chunks del chatbot y calcula la distancia
coseno de uno en uno: con el corpus completo eso es un escaneo secuencial por pregunta.

Los índices se declaran **en el ORM y en la migración**. Solo en la migración no valdría: las
BD de test se construyen con `create_all` desde el metadata del ORM, así que el índice no
existiría donde se prueba — y esa desalineación ORM/migración es la que costó el fallo de
subida de documentos que arregló ING.0.2.
"""
from __future__ import annotations

import math
import os
import subprocess
import sys
import uuid
from pathlib import Path

import psycopg2
import pytest
from sqlalchemy import text

from server.tests.modules.agents_hub.integration.test_metadata_filter import (
    _chunk,
    _documento,
)

_SERVER_ROOT = Path(__file__).parent.parent.parent.parent.parent

INDICE_CHUNKS = "ix_hub_document_chunks_embedding_hnsw"
INDICE_PAGINAS = "ix_hub_crawled_pages_embedding_hnsw"
# `down_revision` de e2n3o4p5q6r7 (RAG.3). Explícito para que el test siga probando lo suyo
# cuando se apilen migraciones nuevas encima.
REVISION_ANTES_DE_HNSW = "d1m2n3o4p5q6"


def _vector(*componentes: tuple[int, float]) -> list[float]:
    v = [0.0] * 1024
    for indice, valor in componentes:
        v[indice] = valor
    return v


def _coseno(a: list[float], b: list[float]) -> float:
    producto = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return producto / (na * nb) if na and nb else 0.0


class TestIndiceDeclarado:

    @pytest.mark.asyncio
    async def test_should_create_hnsw_index_on_chunk_embeddings(self, db_session):
        """El índice existe en la BD construida desde el metadata del ORM."""
        filas = (await db_session.execute(text(
            "select indexname, indexdef from pg_indexes "
            "where tablename = 'hub_document_chunks'"
        ))).all()

        definiciones = {nombre: definicion for nombre, definicion in filas}
        assert INDICE_CHUNKS in definiciones
        assert "USING hnsw" in definiciones[INDICE_CHUNKS]
        assert "vector_cosine_ops" in definiciones[INDICE_CHUNKS]

    @pytest.mark.asyncio
    async def test_should_create_hnsw_index_on_page_embeddings(self, db_session):
        """`page_embedding` la usa el detector semántico de 9Q, que compara por coseno."""
        filas = (await db_session.execute(text(
            "select indexname, indexdef from pg_indexes "
            "where tablename = 'hub_crawled_pages'"
        ))).all()

        definiciones = {nombre: definicion for nombre, definicion in filas}
        assert INDICE_PAGINAS in definiciones
        assert "USING hnsw" in definiciones[INDICE_PAGINAS]

    @pytest.mark.asyncio
    async def test_should_use_hnsw_index_in_query_plan(self, db_session):
        """El plan usa el índice cuando el escaneo secuencial no es una opción.

        Se desactiva `enable_seqscan` a propósito: sobre una tabla de tres filas el planner
        prefiere legítimamente el escaneo secuencial, y lo que este test comprueba es que el
        índice es **usable** por la consulta de `retriever.py` (ORDER BY distancia + LIMIT),
        no qué decide el planner con un corpus de juguete.
        """
        cb = uuid.uuid4()
        doc = await _documento(db_session, cb)
        for i in range(3):
            await _chunk(db_session, cb, doc, f"Text {i}", embedding=_vector((i, 1.0)))
        await db_session.commit()

        consulta = _vector((0, 1.0))
        await db_session.execute(text("set local enable_seqscan = off"))
        plan = "\n".join(
            fila[0] for fila in (await db_session.execute(text(
                "explain select id from hub_document_chunks "
                f"order by embedding <=> '{consulta}' limit 3"
            ))).all()
        )

        assert "hnsw" in plan.lower(), plan


class TestEquivalenciaConElEscaneoExacto:

    @pytest.mark.asyncio
    async def test_should_return_same_top_k_as_exact_scan_on_small_corpus(self, db_session):
        """ANN y exacto coinciden en el corpus de fixture: el índice no cambia la respuesta."""
        from server.app.modules.agents_hub.services.retriever import HybridRetriever

        cb = uuid.uuid4()
        doc = await _documento(db_session, cb)
        vectores = {
            "Text A": _vector((0, 1.0), (1, 0.10)),
            "Text B": _vector((0, 1.0), (1, 0.60)),
            "Text C": _vector((1, 1.0)),
            "Text D": _vector((2, 1.0), (0, 0.30)),
            "Text E": _vector((3, 1.0)),
        }
        for contenido, vector in vectores.items():
            await _chunk(db_session, cb, doc, contenido, embedding=vector)
        await db_session.commit()

        consulta = _vector((0, 1.0), (1, 0.20))
        recuperados = await HybridRetriever(db_session).vector_search(consulta, cb, top_k=3)

        exactos = sorted(
            vectores, key=lambda c: _coseno(consulta, vectores[c]), reverse=True
        )[:3]

        assert [r.content for r in recuperados] == exactos


class TestMigracion:

    def test_should_apply_and_rollback_migration_cleanly(self, fresh_database: str) -> None:
        """La migración crea los dos índices y el downgrade los retira sin residuos.

        Se baja a la revisión ANTERIOR a la de HNSW por su id, no con `-1`: con `-1` el test
        daba por hecho que esta migración era la cabeza, y se rompió en cuanto RAG.4 añadió
        la suya encima —bajaba una revisión que no tenía nada que ver con estos índices—.
        """
        _alembic(fresh_database, "upgrade", "head")
        assert _indices(fresh_database) == {INDICE_CHUNKS, INDICE_PAGINAS}

        _alembic(fresh_database, "downgrade", REVISION_ANTES_DE_HNSW)
        assert _indices(fresh_database) == set()

        _alembic(fresh_database, "upgrade", "head")
        assert _indices(fresh_database) == {INDICE_CHUNKS, INDICE_PAGINAS}


def _alembic(database_url: str, *args: str) -> None:
    resultado = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=_SERVER_ROOT,
        env={**os.environ, "DATABASE_URL_SYNC": database_url},
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert resultado.returncode == 0, f"alembic {args}:\n{resultado.stderr}"


def _indices(database_url: str) -> set[str]:
    conn = psycopg2.connect(database_url.replace("postgresql+psycopg2", "postgresql"))
    try:
        with conn.cursor() as cur:
            cur.execute(
                "select indexname from pg_indexes where indexname = any(%s)",
                ([INDICE_CHUNKS, INDICE_PAGINAS],),
            )
            return {fila[0] for fila in cur.fetchall()}
    finally:
        conn.close()
