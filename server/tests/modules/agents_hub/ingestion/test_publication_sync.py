"""Tests TDD — Fuente MCP de publicación sobre el reconciliador de ING.0.5 (Prompt SYNC.1).

**Esto es ETL, no una operación agéntica.** Un script llama a la tool, recibe texto, calcula
hash y escribe: cero tokens de modelo y cero trazas. El token del dataset viaja como
argumento de la tool, así que si esta ruta pasara por un agente con trazas activas el token
acabaría escrito en el almacén de trazas. De ahí que haya un test que vigila los logs y otro
que vigila que nadie construya un modelo.

**Y es una fuente, no un pipeline**: emparejamiento, deltas, poda y salvaguarda de
proporción vienen de ING.0.5 y no se reimplementan. El último bloque de este fichero corre
la suite del reconciliador contra las dos fuentes para que eso deje de ser una promesa.
"""
from __future__ import annotations

import json
import logging
import uuid

import pytest


# ───────────────────────── Dobles ─────────────────────────

TOKEN = "tok-secretisimo-de-dataset"

FRONT_MATTER = """---
id_publicacio: {id}
title: Norma {id}
language: ca
url_oficial: https://www.uji.es/{id}
---

# Norma {id}

##### Article 1. Objecte {{#art-1}}

{body}
"""


def _registro_indice(id_publicacio: str, content_hash: str) -> dict:
    return {
        "id_publicacio": id_publicacio,
        "relative_path": f"{id_publicacio}.md",
        "content_hash": content_hash,
        "metadades": {
            "id_publicacio": id_publicacio,
            "title": f"Norma {id_publicacio}",
            "language": "ca",
            "url_oficial": f"https://www.uji.es/{id_publicacio}",
        },
    }


def _registro_contenido(id_publicacio: str, body: str) -> dict:
    return {
        "id_publicacio": id_publicacio,
        "markdown": FRONT_MATTER.format(id=id_publicacio, body=body),
    }


class _FakeTransport:
    """Sustituye al HTTP del cliente. Registra cada petición JSON-RPC tal cual se envía."""

    def __init__(self, datasets: dict[str, object]) -> None:
        self.datasets = datasets
        self.peticiones: list[dict] = []
        self.texto_crudo: dict[str, str] = {}

    def llamadas_a(self, dataset_code: str) -> int:
        return sum(
            1 for p in self.peticiones
            if p["params"]["arguments"]["dataset_code"] == dataset_code
        )

    async def call(self, payload: dict) -> dict:
        self.peticiones.append(payload)
        code = payload["params"]["arguments"]["dataset_code"]
        if code in self.texto_crudo:
            texto = self.texto_crudo[code]
        else:
            texto = json.dumps(self.datasets[code], ensure_ascii=False)
        return {
            "jsonrpc": "2.0",
            "id": payload["id"],
            "result": {"content": [{"type": "text", "text": texto}]},
        }


def _cliente(datasets: dict[str, object]):
    from server.app.modules.agents_hub.ingestion.corpus.publication_client import (
        PublicationMcpClient,
    )

    transporte = _FakeTransport(datasets)
    cliente = PublicationMcpClient(
        url="https://mcp.uji.es/rpc", token=TOKEN, transport=transporte
    )
    return cliente, transporte


def _fuente(datasets: dict[str, object], *, census: bool = True):
    from server.app.modules.agents_hub.ingestion.corpus.publication_source import (
        PublicationMcpSource,
    )

    cliente, transporte = _cliente(datasets)
    fuente = PublicationMcpSource(
        cliente,
        index_dataset="CORPUS_INDEX",
        content_dataset="CORPUS_CONTENT",
        is_census_declared=census,
    )
    return fuente, transporte


def _datasets(documentos: dict[str, str], hashes: dict[str, str] | None = None) -> dict:
    from server.app.modules.agents_hub.ingestion.corpus.frontmatter import (
        hash_markdown_body,
        parse_frontmatter,
    )

    indice, contenido = [], []
    for id_pub, body in documentos.items():
        markdown = FRONT_MATTER.format(id=id_pub, body=body)
        _, cuerpo = parse_frontmatter(markdown)
        h = (hashes or {}).get(id_pub) or hash_markdown_body(cuerpo)
        indice.append(_registro_indice(id_pub, h))
        contenido.append(_registro_contenido(id_pub, body))
    return {"CORPUS_INDEX": indice, "CORPUS_CONTENT": contenido}


class _FakeEmbedding:
    model_name = "BAAI/bge-m3"
    dimensions = 1024

    async def embed(self, text: str) -> list[float]:
        return [0.1] * 1024


class _FakeChatbotProvider:
    async def get_retrieval_mode(self, chatbot_id: uuid.UUID) -> str:
        return "RAG"


async def _reconciliar(session, fuente, chatbot_id, **kwargs):
    from server.app.modules.agents_hub.ingestion.corpus.reconciler import CorpusReconciler
    from server.app.modules.agents_hub.ingestion.watcher import IngestionWatcher

    reconciler = CorpusReconciler(
        session,
        IngestionWatcher(session, _FakeEmbedding(), chatbot_provider=_FakeChatbotProvider()),
    )
    return await reconciler.reconcile(fuente, chatbot_id, **kwargs)


# ───────────────────────── Cliente ─────────────────────────


class TestClienteMcp:

    @pytest.mark.asyncio
    async def test_should_call_execute_dataset_with_code_and_token(self):
        cliente, transporte = _cliente({"CORPUS_INDEX": []})

        await cliente.execute_dataset("CORPUS_INDEX")

        peticion = transporte.peticiones[0]
        assert peticion["method"] == "tools/call"
        assert peticion["params"]["name"] == "execute_dataset"
        assert peticion["params"]["arguments"] == {
            "dataset_code": "CORPUS_INDEX",
            "token": TOKEN,
        }

    @pytest.mark.asyncio
    async def test_should_never_log_the_dataset_token(self, caplog):
        """El token es argumento de la tool, o sea que acaba en cualquier volcado ingenuo."""
        cliente, _ = _cliente({"CORPUS_INDEX": [], "CORPUS_CONTENT": []})

        with caplog.at_level(logging.DEBUG):
            await cliente.execute_dataset("CORPUS_INDEX")

        assert TOKEN not in caplog.text
        assert "CORPUS_INDEX" in caplog.text, (
            "sin ninguna traza no se puede depurar un sync; lo que no debe salir es el token"
        )

    @pytest.mark.asyncio
    async def test_should_fail_loudly_on_truncated_or_unparseable_index(self):
        """~10 MB rozan los límites de respuesta: un censo truncado despublicaría normas."""
        from server.app.modules.agents_hub.ingestion.corpus.publication_client import (
            PublicationSyncError,
        )

        cliente, transporte = _cliente({"CORPUS_INDEX": []})
        transporte.texto_crudo["CORPUS_INDEX"] = '[{"id_publicacio": "REG-1", "cont'

        with pytest.raises(PublicationSyncError) as exc:
            await cliente.execute_dataset("CORPUS_INDEX")

        assert "CORPUS_INDEX" in str(exc.value)
        assert TOKEN not in str(exc.value)

    @pytest.mark.asyncio
    async def test_should_reject_a_response_that_is_not_a_list_of_records(self):
        from server.app.modules.agents_hub.ingestion.corpus.publication_client import (
            PublicationSyncError,
        )

        cliente, transporte = _cliente({"CORPUS_INDEX": []})
        transporte.texto_crudo["CORPUS_INDEX"] = '{"error": "dataset no disponible"}'

        with pytest.raises(PublicationSyncError):
            await cliente.execute_dataset("CORPUS_INDEX")


# ───────────────────────── Fuente ─────────────────────────


class TestFuenteDePublicacion:

    def test_should_satisfy_the_corpus_source_protocol(self):
        from server.app.modules.agents_hub.ingestion.corpus.source import CorpusSource

        fuente, _ = _fuente(_datasets({"REG-1": "Text."}))

        assert isinstance(fuente, CorpusSource)

    def test_should_report_is_census_true_only_for_full_index(self):
        fuente, _ = _fuente(_datasets({"REG-1": "Text."}), census=True)

        assert fuente.is_census() is True

    def test_should_report_is_census_false_for_delta_dataset(self):
        """Un delta no distingue «retirada» de «no tocada», así que no habilita poda."""
        fuente, _ = _fuente(_datasets({"REG-1": "Text."}), census=False)

        assert fuente.is_census() is False

    @pytest.mark.asyncio
    async def test_should_map_index_entries_to_corpus_document_entries_with_id_publicacio(self):
        fuente, _ = _fuente(_datasets({"REG-1": "Text.", "REG-2": "Text."}))

        entradas = await fuente.list_entries()

        assert [e.id_publicacio for e in entradas] == ["REG-1", "REG-2"]
        assert [e.relative_path for e in entradas] == ["REG-1.md", "REG-2.md"]
        assert entradas[0].source_url == "https://www.uji.es/REG-1"
        # El indice de publicacion declara `language: ca` —asi esta escrito el sitio— y aqui se
        # guarda `val`, que es como escribe esa lengua el corpus. Son la misma, y tener los dos
        # codigos vivos hacia que `prefer` ordenara la norma detras de las demas y que el aviso
        # de traduccion saltara contra una pregunta en valencia. La traduccion esta en
        # `core/lengua_del_corpus.py` y se aplica al construir la entrada.
        assert entradas[0].language == "val"
        assert entradas[0].title == "Norma REG-1"

    @pytest.mark.asyncio
    async def test_should_not_touch_the_content_dataset_while_listing(self):
        """Listar es barato y frecuente; bajar el corpus entero no."""
        fuente, transporte = _fuente(_datasets({"REG-1": "Text."}))

        await fuente.list_entries()

        assert transporte.llamadas_a("CORPUS_CONTENT") == 0

    @pytest.mark.asyncio
    async def test_should_fail_loudly_when_the_body_is_missing_from_the_content_dataset(self):
        from server.app.modules.agents_hub.ingestion.corpus.publication_client import (
            PublicationSyncError,
        )

        datasets = _datasets({"REG-1": "Text."})
        datasets["CORPUS_CONTENT"] = []
        fuente, _ = _fuente(datasets)
        entrada = (await fuente.list_entries())[0]

        with pytest.raises(PublicationSyncError):
            await fuente.read_body(entrada)

    @pytest.mark.asyncio
    async def test_should_strip_frontmatter_from_the_body(self):
        fuente, _ = _fuente(_datasets({"REG-1": "Cos de la norma."}))
        entrada = (await fuente.list_entries())[0]

        cuerpo = await fuente.read_body(entrada)

        assert "id_publicacio:" not in cuerpo
        assert "Cos de la norma." in cuerpo


# ───────────────────────── Coste proporcional al cambio ─────────────────────────


class TestCosteProporcional:

    @pytest.mark.asyncio
    async def test_should_request_content_only_for_changed_documents(self, db_session):
        """El índice trae el hash, así que lo no cambiado no se descarga.

        Es la razón de ser de los dos datasets: sin esto, cada pasada bajaría los ~10 MB
        del corpus entero para descubrir que no ha cambiado nada.
        """
        chatbot_id = uuid.uuid4()
        datasets = _datasets({"REG-1": "Text u.", "REG-2": "Text dos."})

        fuente, transporte = _fuente(datasets)
        await _reconciliar(db_session, fuente, chatbot_id)
        await db_session.commit()
        assert transporte.llamadas_a("CORPUS_CONTENT") == 1, "la primera pasada sí baja todo"

        # Segunda pasada, nada ha cambiado en origen.
        fuente2, transporte2 = _fuente(datasets)
        informe = await _reconciliar(db_session, fuente2, chatbot_id)

        assert informe.omitidos == 2
        assert transporte2.llamadas_a("CORPUS_INDEX") == 1
        assert transporte2.llamadas_a("CORPUS_CONTENT") == 0

    @pytest.mark.asyncio
    async def test_should_download_content_when_a_document_changed(self, db_session):
        chatbot_id = uuid.uuid4()
        fuente, _ = _fuente(_datasets({"REG-1": "Text u.", "REG-2": "Text dos."}))
        await _reconciliar(db_session, fuente, chatbot_id)
        await db_session.commit()

        fuente2, transporte2 = _fuente(
            _datasets({"REG-1": "Text u.", "REG-2": "Text dos, CORREGIT."})
        )
        informe = await _reconciliar(db_session, fuente2, chatbot_id)

        assert informe.reingeridos == 1
        assert informe.omitidos == 1
        assert transporte2.llamadas_a("CORPUS_CONTENT") == 1

    @pytest.mark.asyncio
    async def test_should_not_trust_a_declared_hash_from_another_algorithm(self, db_session):
        """Si el publicador hashea de otra forma, se pierde el ahorro pero NO la corrección.

        El atajo compara el hash declarado con el que guardamos, que es el nuestro. Un
        algoritmo ajeno simplemente nunca casa: se baja el cuerpo y se decide con el hash
        real. Lo que no puede pasar es que un hash extraño haga pasar por «sin cambios» un
        documento que sí cambió.
        """
        chatbot_id = uuid.uuid4()
        fuente, _ = _fuente(_datasets({"REG-1": "Text original."}))
        await _reconciliar(db_session, fuente, chatbot_id)
        await db_session.commit()

        datasets = _datasets(
            {"REG-1": "Text CANVIAT."}, hashes={"REG-1": "hash-de-otro-algoritmo"}
        )
        fuente2, transporte2 = _fuente(datasets)
        informe = await _reconciliar(db_session, fuente2, chatbot_id)

        assert informe.reingeridos == 1
        assert transporte2.llamadas_a("CORPUS_CONTENT") == 1


# ───────────────────────── No es agéntico ─────────────────────────


class TestNoEsAgentico:

    @pytest.mark.asyncio
    async def test_should_not_emit_llm_calls_during_sync(self, db_session, monkeypatch):
        from server.app.modules.agents_hub.services import model_factory

        llamadas: list[str] = []

        async def _espia(*args, **kwargs):
            llamadas.append("get_model")
            raise AssertionError("el sync no puede construir un modelo")

        monkeypatch.setattr(model_factory, "get_model", _espia)
        monkeypatch.setattr(model_factory, "get_model_for_tier", _espia)

        fuente, _ = _fuente(_datasets({"REG-1": "Text."}))
        await _reconciliar(db_session, fuente, uuid.uuid4())

        assert llamadas == []

    def test_should_reuse_reconciler_without_reimplementing_matching(self):
        """El sync no escribe en hub_documents: eso es trabajo del reconciliador.

        Guardarraíl de texto, como los de `tests/infra`. Si un día alguien «arregla» el sync
        tocando documentos directamente, la duplicación de la lógica de emparejamiento y
        poda no la detectaría ningún test funcional: los dos caminos darían el mismo
        resultado hasta el día en que dejaran de darlo.
        """
        from pathlib import Path

        import server.app.modules.agents_hub.ingestion.corpus.publication_source as ps
        import server.app.modules.agents_hub.ingestion.corpus.sync as sync

        for modulo in (ps, sync):
            texto = Path(modulo.__file__).read_text(encoding="utf-8")
            assert "HubDocument" not in texto, (
                f"{modulo.__name__} toca HubDocument directamente; el emparejamiento, los "
                "deltas y la poda son del reconciliador (ING.0.5)"
            )
            # `prune_threshold` NO entra en esta lista: la CLI lo recibe como bandera y lo
            # pasa al reconciliador, que es exactamente lo contrario de reimplementar la
            # poda. Lo que delata una reimplementación es escribir el motivo de retirada o
            # marcar documentos a mano.
            for prohibido in ("MOTIU_RETIRADA", "retirada_de_la_font", "us_assistents ="):
                assert prohibido not in texto, (
                    f"{modulo.__name__} reimplementa poda: eso ya está en el reconciliador"
                )
