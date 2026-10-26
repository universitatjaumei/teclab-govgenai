"""Retriever de documentación interna: indexa Markdown, embebe con BGE-M3, retrieve filtrado por módulo."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from .models import CopilotModule, SourceRef

_log = logging.getLogger(__name__)

#: El propósito con el que se embebe la documentación. Es el mismo valor que usa la ingesta del
#: corpus (`embedding_service.PURPOSE_DOCUMENT`), y se escribe aquí para no importar el módulo
#: de embeddings desde el retriever: lo único que necesita del servicio es su interfaz.
PURPOSE_DOCUMENT = "document"


@dataclass
class IndexedChunk:
    text: str
    source_path: str
    module: CopilotModule
    chunk_idx: int
    embedding: list[float] = field(default_factory=list)

    def to_source_ref(self) -> SourceRef:
        excerpt = self.text.strip().replace("\n", " ")
        if len(excerpt) > 200:
            excerpt = excerpt[:197] + "…"
        return SourceRef(
            path=self.source_path,
            chunk_idx=self.chunk_idx,
            excerpt=excerpt,
            module=self.module,
        )


class DocsRetriever:
    """Indexa Markdown bajo `docs_dir`, embebe chunks y permite retrieve filtrado por módulo.

    Estado en memoria: pensado para docs estables (decenas de archivos). Si crece,
    migrar a pgvector reutilizando `HubDocumentChunk` con namespace 'copilot_docs'.
    """

    def __init__(
        self,
        embedding_service: Any,
        docs_dir: Path | None = None,
        chunk_size: int = 1200,
    ) -> None:
        self._embedding = embedding_service
        self._docs_dir = docs_dir or Path("docs")
        self._chunk_size = chunk_size
        self._chunks: list[IndexedChunk] = []
        # PRO.6 — el índice se construye **al primer uso**, no al arrancar. Medido: 46 ficheros
        # y ~387 fragmentos, o sea 387 embeddings por índice; pagarlos en cada arranque es un
        # coste que casi nunca se aprovecha, y en modo edge con embeddings locales retrasa el
        # arranque. La bandera es propia y no «¿hay fragmentos?»: un `docs/` vacío haría que
        # cada pregunta volviera a recorrerlo.
        self._indexado = False

    @property
    def chunks(self) -> list[IndexedChunk]:
        return list(self._chunks)

    @property
    def indexado(self) -> bool:
        return self._indexado

    async def index(self) -> None:
        """Recorre `docs_dir` recursivo, chunkea cada `.md` y embebe cada fragmento.

        Los fragmentos se embeben **en lote** si el servicio lo admite: de uno en uno son
        cientos de peticiones seguidas, y la primera pregunta del copiloto es la que las paga.
        """
        self._chunks.clear()
        self._indexado = True
        if not self._docs_dir.exists():
            return

        pendientes: list[IndexedChunk] = []
        for md_path in sorted(self._docs_dir.rglob("*.md")):
            module = self._infer_module(md_path)
            for idx, chunk in enumerate(self._chunk_markdown(md_path)):
                if not chunk.strip():
                    continue
                pendientes.append(IndexedChunk(
                    text=chunk,
                    source_path=str(md_path),
                    module=module,
                    chunk_idx=idx,
                    embedding=[],
                ))

        if not pendientes:
            return

        vectores = await self._embeber([c.text for c in pendientes])
        for fragmento, vector in zip(pendientes, vectores, strict=True):
            self._chunks.append(
                IndexedChunk(
                    text=fragmento.text,
                    source_path=fragmento.source_path,
                    module=fragmento.module,
                    chunk_idx=fragmento.chunk_idx,
                    embedding=vector,
                )
            )

    async def _embeber(self, textos: list[str]) -> list[list[float]]:
        en_lote = getattr(self._embedding, "embed_batch", None)
        if en_lote is not None:
            try:
                return list(await en_lote(textos, purpose=PURPOSE_DOCUMENT))
            except (AttributeError, NotImplementedError, TypeError):
                # Un adaptador que declara el método y no lo implementa no puede dejar al
                # copiloto sin índice: se cae a una en una.
                _log.debug("El servicio de embeddings no admitió el lote; una a una")
        return [await self._embedding.embed(t) for t in textos]

    async def retrieve(
        self,
        query: str,
        module: CopilotModule | None = None,
        top_k: int = 4,
    ) -> list[IndexedChunk]:
        """Retrieve por similitud coseno. Si `module` se da, filtra antes de puntuar."""
        if not self._indexado:
            await self.index()
        if not self._chunks:
            return []
        query_emb = await self._embedding.embed(query)
        candidates = [c for c in self._chunks if _entra(c.module, module)]
        scored = [(_cosine(query_emb, c.embedding), c) for c in candidates]
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [chunk for _score, chunk in scored[:top_k]]

    def _chunk_markdown(self, path: Path) -> Iterator[str]:
        """Particiona el archivo por párrafos (doble newline) acumulando hasta `chunk_size`."""
        text = path.read_text(encoding="utf-8")
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        buffer: list[str] = []
        size = 0
        for para in paragraphs:
            if size + len(para) > self._chunk_size and buffer:
                yield "\n\n".join(buffer)
                buffer = [para]
                size = len(para)
            else:
                buffer.append(para)
                size += len(para)
        if buffer:
            yield "\n\n".join(buffer)

    @staticmethod
    def _infer_module(path: Path) -> CopilotModule:
        haystack = str(path).lower()
        if "redaccion" in haystack:
            return "redaccion"
        if "chatbot" in haystack:
            return "chatbots"
        return "general"


def _entra(modulo_del_fragmento: CopilotModule, modulo_pedido: CopilotModule | None) -> bool:
    """El módulo **prefiere**, no excluye — PRO.6.

    Antes era un filtro estricto (`c.module == module`), y `_infer_module` clasifica como
    `redaccion` sólo los ficheros cuya **ruta** contiene «redaccion»: en `docs/` hay
    exactamente uno. Visto en el navegador: preguntado desde un informe, el copiloto contestaba
    «no tengo esa información» a una pregunta cuya respuesta está en `docs/`, mientras que por
    API —sin módulo— la contestaba y citaba el fichero. Un copiloto que no encuentra lo que
    tiene delante no se usa dos veces.

    La documentación general vale para cualquier módulo; la de **otro** módulo se queda fuera,
    que es lo que el filtro pretendía.
    """
    if modulo_pedido is None:
        return True
    return modulo_del_fragmento in (modulo_pedido, "general")


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    mag_a = sum(x * x for x in a) ** 0.5
    mag_b = sum(y * y for y in b) ** 0.5
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)
