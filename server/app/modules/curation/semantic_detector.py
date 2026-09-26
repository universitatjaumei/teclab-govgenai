"""Detector semántico site-scoped: clustering + juez LLM (9Q.4).

Deploy: edge.

Segunda pasada selectiva con LLM. Detecta duplicados y contradicciones semánticas
entre páginas del mismo sitio. Respeta HubWebSite.audit_semantic_scope:
- "ingested": solo páginas ya ingeridas (reusa embeddings de chunks, coste 0 de embedding).
- "full": embebe on-demand las páginas activas sin page_embedding y lo persiste.

Reglas de coste: nunca se llama al LLM por el producto cartesiano; solo pares filtrados
por umbral de similitud y deduplicados. 0 pares → 0 llamadas LLM.

El servicio NO persiste hallazgos (eso es del job 9Q.5); devuelve la lista de ContentFinding.
"""
from __future__ import annotations

import json
import math
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Protocol

from sqlalchemy import select

from server.app.modules.agents_hub.database.operational_models import (
    HubCrawledPage,
    HubDocument,
    HubDocumentChunk,
    HubWebSite,
)
from server.app.modules.curation.contracts import ContentFinding
from server.app.core.llm_json import extraer_json as _extract_json

_TEXT_LIMIT = 2000  # chars enviados al juez por documento
_SIGNAL_TEXT_LIMIT = 500  # chars guardados en el signal del hallazgo


class LLMService(Protocol):
    """Mismo contrato que el juez de 9R.6.3."""

    model_name: str

    async def generate(self, prompt: str, context: str) -> str: ...


class EmbeddingService(Protocol):
    async def embed(self, text: str) -> list[float]: ...


def _misma_serie(page_a: Any, page_b: Any) -> bool:
    """¿Son dos versiones del mismo recurso publicado por años o por cursos académicos?

    Reutiliza la identidad de serie del detector determinista para no tener dos ideas distintas de
    qué es «la misma página en otro año» en el mismo módulo.
    """
    from server.app.modules.curation.deterministic_detector import _process_key

    clave_a = _process_key(getattr(page_a, "canonical_url", None), page_a.url)
    clave_b = _process_key(getattr(page_b, "canonical_url", None), page_b.url)
    # `__no_year__…` es la clave de «esta URL no participa en ninguna serie», y es única por página:
    # dos de ellas nunca son la misma serie aunque coincidan por casualidad.
    return clave_a == clave_b and not clave_a.startswith("__no_year__")


def _cosine(a: list[float], b: list[float]) -> float:
    """Similitud coseno, **siempre como `float` de Python**.

    El `float()` no es cosmético: los vectores leídos de pgvector vuelven como `float32` de numpy, y
    la similitud acaba dentro de `signal_json`, donde `json.dumps` no sabe escribirla. Con vectores
    recién embebidos son floats normales y todo va bien, así que el fallo aparecía **sólo en la
    segunda pasada** de un sitio —la primera guardó sus diez hallazgos, la segunda falló al
    guardarlos—. Medido en CUR.7.
    """
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(dot / (na * nb))


def _build_judge_prompt(text_a: str, text_b: str) -> str:
    return (
        "Eres un auditor de contenido web de administración pública. Compara estos dos "
        "fragmentos del MISMO sitio y decide su relación semántica.\n"
        'Responde SOLO con JSON estricto: {"relation": "duplicate"|"contradiction"|"unrelated", '
        '"confidence": <0..1>, "explanation": "<breve>"}.\n'
        "- duplicate: dicen esencialmente lo mismo (redundancia).\n"
        "- contradiction: afirman datos incompatibles sobre el mismo asunto.\n"
        "- unrelated: tratan asuntos distintos.\n"
        # CUR.7 — medido: nueve de once hallazgos de la primera pasada real eran «contradicción»
        # entre dos ediciones del mismo curso archivado. Es el dato del dominio que el usuario dio
        # en CUR.2 —el portal publica por años y todos siguen siendo válidos— y sin decírselo el
        # modelo concluye lo esperable: que dos fechas distintas para el mismo curso se contradicen.
        "\nMuy importante: este portal archiva **ediciones** de un mismo curso, convocatoria o "
        "acuerdo, una por año o curso académico. Dos ediciones distintas NO se contradicen aunque "
        "cambien sus fechas, horarios, horas acreditables o profesorado: cada una describe su "
        "propia edición y todas siguen siendo válidas como archivo. Responde 'contradiction' sólo "
        "si los dos fragmentos afirman datos incompatibles sobre **la misma** edición o sobre un "
        "hecho que no depende del año.\n\n"
        f"--- DOCUMENTO A ---\n{text_a[:_TEXT_LIMIT]}\n\n"
        f"--- DOCUMENTO B ---\n{text_b[:_TEXT_LIMIT]}\n"
    )


class JuezDeContenidoWeb:
    """Adaptador mínimo del modelo al protocolo `LLMService` de este detector (CUR.7).

    Existe porque **el prompt tiene que llegar literal**. El otro adaptador del proyecto que cumple
    este mismo protocolo, `RedactorDeBloques`, trata su primer argumento como el **identificador**
    de una plantilla de prompt y lo sustituye por la instrucción del catálogo: pasarle el prompt del
    juez lo convertiría en «la plantilla de prompt "Eres un auditor de contenido web…" no está en el
    catálogo del módulo», y el modelo recibiría cualquier cosa menos la pregunta. Dos protocolos con
    la misma firma y semánticas distintas: por eso este adaptador es de tres líneas y no se reutiliza
    el de al lado.
    """

    def __init__(self, modelo: Any, model_name: str) -> None:
        self._modelo = modelo
        self.model_name = model_name

    async def generate(self, prompt: str, context: str) -> str:
        contenido = f"{prompt}\n\n{context}" if context else prompt
        respuesta = await self._modelo.ainvoke([{"role": "user", "content": contenido}])
        texto = getattr(respuesta, "content", respuesta)
        return texto if isinstance(texto, str) else str(texto)


class SemanticContradictionDetector:
    """Detecta duplicados/contradicciones semánticas entre páginas de un sitio."""

    def __init__(
        self,
        session: Any,
        llm: LLMService,
        embedding_service: EmbeddingService,
        *,
        similarity_threshold: float = 0.92,
        max_pairs_per_run: int = 200,
        anonymizer: Callable[[str], str] | None = None,
    ) -> None:
        self._session = session
        self._llm = llm
        self._embedding = embedding_service
        self._threshold = similarity_threshold
        self._max_pairs = max_pairs_per_run
        self._anonymizer = anonymizer

    async def analyze(self, site_id: uuid.UUID) -> list[ContentFinding]:
        site = await self._session.get(HubWebSite, site_id)
        if site is None:
            return []

        scope = getattr(site, "audit_semantic_scope", "ingested")
        if scope == "full":
            page_vecs = await self._gather_full(site_id)
        else:
            page_vecs = await self._gather_ingested(site_id)

        pairs = self._candidate_pairs(page_vecs)
        if not pairs:
            return []

        now = datetime.now(timezone.utc)
        findings: list[ContentFinding] = []
        for page_a, page_b, similarity in pairs:
            text_a = page_a.markdown_content or ""
            text_b = page_b.markdown_content or ""
            if self._anonymizer is not None:
                text_a = self._anonymizer(text_a)
                text_b = self._anonymizer(text_b)

            verdict = await self._judge(text_a, text_b)
            finding = self._to_finding(page_a, page_b, similarity, verdict, now)
            if finding is not None:
                findings.append(finding)
        return findings

    # ── Cobertura ────────────────────────────────────────────────────────

    async def _gather_ingested(self, site_id: uuid.UUID) -> list[tuple[Any, list[float]]]:
        """Páginas con HubDocument ingerido; reusa el embedding del chunk representativo.

        Coste 0 de embedding: nunca invoca embedding_service.
        """
        pages = await self._fetch_pages(site_id, only_active=False)
        if not pages:
            return []
        pages_by_id = {p.id: p for p in pages}

        docs = await self._fetch_documents(list(pages_by_id.keys()))
        # primer documento por página (contenido idéntico entre chatbots)
        first_doc_by_page: dict[uuid.UUID, Any] = {}
        for doc in docs:
            if doc.crawled_page_id in pages_by_id and doc.crawled_page_id not in first_doc_by_page:
                first_doc_by_page[doc.crawled_page_id] = doc

        doc_ids = [d.id for d in first_doc_by_page.values()]
        chunks = await self._fetch_chunks(doc_ids)
        chunks_by_doc: dict[uuid.UUID, list[Any]] = {}
        for ch in chunks:
            if ch.embedding is not None:
                chunks_by_doc.setdefault(ch.document_id, []).append(ch)

        result: list[tuple[Any, list[float]]] = []
        for page_id, doc in first_doc_by_page.items():
            doc_chunks = chunks_by_doc.get(doc.id, [])
            if not doc_chunks:
                continue
            representative = max(doc_chunks, key=lambda c: len(c.content or ""))
            result.append((pages_by_id[page_id], list(representative.embedding)))
        return result

    async def _gather_full(self, site_id: uuid.UUID) -> list[tuple[Any, list[float]]]:
        """Todas las páginas activas; embebe on-demand las que no tengan page_embedding."""
        pages = await self._fetch_pages(site_id, only_active=True)
        result: list[tuple[Any, list[float]]] = []
        for page in pages:
            if page.page_embedding is None:
                if not (page.markdown_content and page.markdown_content.strip()):
                    continue
                vector = await self._embedding.embed(page.markdown_content)
                page.page_embedding = vector
                await self._session.flush()
            result.append((page, list(page.page_embedding)))
        return result

    # ── Clustering + control de coste ────────────────────────────────────

    def _candidate_pairs(
        self, page_vecs: list[tuple[Any, list[float]]]
    ) -> list[tuple[Any, Any, float]]:
        pairs: list[tuple[Any, Any, float]] = []
        for i in range(len(page_vecs)):
            page_a, vec_a = page_vecs[i]
            for j in range(i + 1, len(page_vecs)):
                page_b, vec_b = page_vecs[j]
                # Misma canonical → es supersesión (9Q.3), no se juzga aquí.
                if (
                    page_a.canonical_url
                    and page_b.canonical_url
                    and page_a.canonical_url == page_b.canonical_url
                ):
                    continue
                # Dos ediciones de la misma serie tampoco: el determinista ya las agrupa como
                # `version_series`, y pagar una llamada al modelo para que diga «contradicción»
                # sobre el mismo curso en dos años es gasto y ruido a la vez. Medido: los diez
                # primeros hallazgos reales del detector eran justo eso (CUR.7).
                if _misma_serie(page_a, page_b):
                    continue
                similarity = _cosine(vec_a, vec_b)
                if similarity >= self._threshold:
                    pairs.append((page_a, page_b, similarity))

        pairs.sort(key=lambda t: t[2], reverse=True)
        return pairs[: self._max_pairs]

    # ── Juez LLM ─────────────────────────────────────────────────────────

    async def _judge(self, text_a: str, text_b: str) -> dict[str, Any]:
        prompt = _build_judge_prompt(text_a, text_b)
        raw = await self._llm.generate(prompt, "")
        try:
            data = json.loads(_extract_json(raw))
        except (ValueError, TypeError):
            return {"relation": "unrelated", "confidence": 0.0, "explanation": ""}
        return data

    def _to_finding(
        self,
        page_a: Any,
        page_b: Any,
        similarity: float,
        verdict: dict[str, Any],
        now: datetime,
    ) -> ContentFinding | None:
        relation = verdict.get("relation")
        if relation not in ("duplicate", "contradiction"):
            return None
        severity = "critical" if relation == "contradiction" else "warning"
        confidence = float(verdict.get("confidence", 0.0))
        return ContentFinding(
            id=uuid.uuid4(),
            site_id=page_a.site_id,
            finding_type=relation,  # type: ignore[arg-type]
            severity=severity,  # type: ignore[arg-type]
            confidence=confidence,
            detected_at=now,
            page_id=page_a.id,
            related_page_id=page_b.id,
            source_url=page_a.url,
            signal={
                # `float()` antes de redondear: `round` sobre un `float32` de numpy devuelve otro
                # `float32`, y esto va a un JSONB.
                "similarity": round(float(similarity), 4),
                "explanation": verdict.get("explanation", ""),
                "text_a": (page_a.markdown_content or "")[:_SIGNAL_TEXT_LIMIT],
                "text_b": (page_b.markdown_content or "")[:_SIGNAL_TEXT_LIMIT],
                "related_url": page_b.url,
            },
        )

    # ── Acceso a datos (statements etiquetados para fakes y claridad) ─────

    async def _fetch_pages(self, site_id: uuid.UUID, *, only_active: bool) -> list:
        # recorrido-acotado: igual que el detector determinista, compara unas paginas con
        # otras y necesita el conjunto del sitio. 352 en el mayor (issue #159).
        stmt = select(HubCrawledPage).where(HubCrawledPage.site_id == site_id)
        if only_active:
            stmt = stmt.where(HubCrawledPage.status == "active")
        stmt._model_hint = "page"  # type: ignore[attr-defined]
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def _fetch_documents(self, page_ids: list[uuid.UUID]) -> list:
        if not page_ids:
            return []
        stmt = select(HubDocument).where(HubDocument.crawled_page_id.in_(page_ids))
        stmt._model_hint = "document"  # type: ignore[attr-defined]
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def _fetch_chunks(self, doc_ids: list[uuid.UUID]) -> list:
        if not doc_ids:
            return []
        # recorrido-acotado: los fragmentos de los documentos que el sitio tiene ingeridos,
        # para comparar su contenido con el del portal. Acotado por `doc_ids`, que sale de
        # las paginas del sitio. **Este es el unico de los declarados que toca la tabla
        # grande**: si un sitio llegara a tener cientos de documentos ingeridos, hay que
        # lotearlo por documento (issue #159).
        stmt = select(HubDocumentChunk).where(HubDocumentChunk.document_id.in_(doc_ids))
        stmt._model_hint = "chunk"  # type: ignore[attr-defined]
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
