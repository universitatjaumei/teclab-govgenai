# RAG: relación de sustitución de código propio por dependencias maduras

> **Fecha**: 2026-07-24
> **Estado**: Aceptado — vista transversal del Bloque RAG e ingesta. **Su parte de Docling quedó
> revertida**: EXT.3 retiró Docling del servidor el 2026-08-11 y `AGENTS.md` prohíbe
> reintroducirlo, así que donde este documento recomienda «consolidar parsers en Docling» manda
> [`DECISION_EXTRACCION_Y_DESPLIEGUE.md`](DECISION_EXTRACCION_Y_DESPLIEGUE.md). El resto sigue en
> pie.
> **Fuentes**: código real (`server/app/modules/agents_hub/`), `pyproject.toml`,
> `docs/COMPARATIVA_RAG_LAMB.md`, `docs/DECISION_OPENWEBUI_CARCASA_CHAT.md` (§6),
> `planificacion/Plan_TDD_Fase1.md` (Bloque RAG, Bloque ING).
> **Finalidad**: aplicar la lente de mantenibilidad de la decisión OWUI a la capa RAG —
> distinguir qué código *reinventa* lo que una librería madura ya hace (sustituir), qué es un
> hueco (añadir dep), qué ya está bien apoyado (no tocar) y qué es diferencial de gobernanza (no
> sustituir nunca). No es un plan nuevo: **mapea a los prompts del Bloque RAG/ING ya aprobados.**

---

## Principio

La UX de chat se externaliza a OWUI porque es *commodity*; la recuperación/ingesta se **queda en
el perímetro** porque es portadora de gobernanza (P6/P7/P8/P9), según
`DECISION_OPENWEBUI_CARCASA_CHAT.md` §6. El alivio de mantenimiento del RAG **no** viene de mover
nada a OWUI, sino de **apoyar las primitivas en librerías maduras dentro del backend**, dejando
intacta la capa de gobernanza tejida en el SQL.

**Cuatro cubos** (regla de clasificación):

| Cubo | Qué significa | Acción |
|---|---|---|
| ✅ **Ya apoyado** | Envoltorio fino sobre una lib madura | No tocar |
| ♻️ **Reinventado** | Código propio que una lib hace mejor | **Sustituir** |
| ➕ **Hueco** | Falta una capacidad; la dep ya existe o es estándar | **Añadir** |
| 🔒 **Diferencial** | Lleva gobernanza; va tejido con el SQL | **No sustituir** |

**Anti-patrón explícito.** No migrar a un framework RAG completo (LlamaIndex/Haystack como
orquestador): el contrato de citas (P6), el filtro `superseded` (P9), el aislamiento
`owner_id`/`is_temporary` y la frontera edge-cloud (P8) están tejidos en el SQL de `retriever.py`;
un framework obligaría a re-implementar la gobernanza dentro de su abstracción. Se usan librerías
**como piezas puntuales** (splitters, cross-encoder, parsers), nunca como orquestador.

---

## Mapa maestro

| Componente | Fichero | Cubo | Dependencia madura | Prompt del plan |
|---|---|---|---|---|
| Parser PDF | `ingestion/docling_processor.py` (retirado en EXT.3) | ↩️ Revertido | `docling` (instalada) | — |
| Parser multi-formato (DOCX/PPTX/XLSX) | disperso (`pymupdf`,`pdfplumber`,`openpyxl`,`odfpy`) | ♻️ Consolidar | `docling` (multi-formato v2) | Bloque **ING** |
| Parser audio/YouTube | inexistente | ➕ Hueco (opcional) | `MarkItDown` + `faster-whisper`/`yt-dlp` | Bloque **ING** (nicho) |
| Scrapers web | `ingestion/spider*.py`, `spiders/` | 🔒/baja prioridad | `trafilatura`/`Crawl4AI` (si molesta) | — (degradado a nicho) |
| Chunker markdown | `ingestion/chunker.py` | ✅ Ya apoyado | `langchain-text-splitters` (instalada) | — |
| Contextual chunking | inexistente | ➕ Hueco | (texto embebido enriquecido, sin dep nueva) | **RAG.7** |
| Parent-child chunking | inexistente | ➕ Hueco | `ParentDocumentRetriever` (langchain) | **RAG.8** |
| Embeddings | `agents_hub/services/embedding_service.py` | ✅ Ya apoyado | `sentence-transformers` (bge-m3, local) | RAG.9 (metadato) |
| Índice vectorial (ANN) | `retriever.py::vector_search` | ➕ Hueco (falta índice) | `pgvector` HNSW (migración) | **RAG.3** |
| Búsqueda léxica | `retriever.py::keyword_search` (**`ILIKE`**) | ♻️ **Reinventado** | Postgres FTS `tsvector`+GIN | **RAG.4** |
| Fusión híbrida (RRF) | `retriever.py::hybrid_search` | ✅ Correcto (~20 líneas) | — (no aporta dep) | — |
| Reranker | inexistente | ➕ **Hueco** | `sentence-transformers` CrossEncoder (bge-reranker-v2-m3) | **RAG.6** |

---

## Detalle por componente

### Parsers

- **PDF — revertido.** `docling_processor.py` delegaba en Docling; EXT.3 lo retiró con él.
- **Multi-formato — consolidar en Docling (Bloque ING).** Docling v2 cubre DOCX/PPTX/XLSX/HTML →
  markdown, que es tu unidad canónica (`HubDocument` markdown). En vez de mantener cuatro parsers
  sueltos (`pymupdf`+`pdfplumber`+`openpyxl`+`odfpy`), extender el `docling_processor` a esos
  formatos. **Criterio**: un único punto de conversión → markdown por formato; los parsers sueltos
  quedan solo donde Docling no llega.
- **Audio/YouTube — hueco opcional.** Solo si el caso de uso lo pide (LAMB lo tiene): `MarkItDown`
  + `faster-whisper`/`yt-dlp`. No prioritario.
- 🔒 **No sustituir**: `hasher.py` (dedup SHA-256 + carreras con savepoints) e
  `ingestion/quality/*` (auditoría de corpus P9). Son diferencial; ninguna lib los da con tu
  contrato.

### Chunkers

- **Markdown — no tocar.** `chunker.py` ya es un envoltorio fino sobre `MarkdownHeaderTextSplitter`
  + `RecursiveCharacterTextSplitter`. ✅ No hay nada que "reemplazar".
- **Contextual (RAG.7) y parent-child (RAG.8) — añadir.** Son *variantes* que faltan, no
  reescrituras. Parent-child encaja con `ParentDocumentRetriever` de langchain o con refs
  padre/hijo en `HubDocumentChunk`. Contextual retrieval no necesita dep: es enriquecer el texto
  embebido con headers/título antes de embeder (exige re-embedding, ya contemplado en RAG.9).

### Índice y búsqueda léxica — *el reemplazo real*

- **`vector_search` — añadir índice HNSW (RAG.3).** El SQL (`cosine_distance`, pgvector) es
  correcto; falta el índice ANN. Es una **migración Alembic**
  (`CREATE INDEX ... USING hnsw (embedding vector_cosine_ops)`), no una dependencia nueva. El gate
  de RAG.1 ya contempla la tolerancia ANN.
- ♻️ **`keyword_search` — SUSTITUIR `ILIKE` por FTS nativo (RAG.4).** Hoy es
  `content.ilike("%palabra%")` por palabra con `score=1.0`: no es búsqueda léxica, es un `LIKE` sin
  ranking. Sustituir por `tsvector` + índice GIN + `ts_rank_cd`. Cero infraestructura nueva
  (Postgres nativo, alineado con P2 frugalidad y P10 no-lock-in). Alternativa si se exige BM25
  real: extensión `pg_search`/ParadeDB. **Criterio (RAG.4)**: recall@5/MRR ≥ baseline con cifras
  en el cierre.
- **`hybrid_search` (RRF) — no tocar.** RRF con k=60 es estándar, ~20 líneas y correcto. Una dep
  aquí no mejora nada.

### Reranker — *hueco, y la dep ya está instalada (RAG.6)*

- ➕ **Añadir cross-encoder local.** `sentence-transformers` ya está en `pyproject.toml`; usar
  `CrossEncoder("BAAI/bge-reranker-v2-m3")` sobre el top-N de `hybrid_search` antes de recortar a
  top-k. Mismo proveedor que el embedder `bge-m3`, corre **local en el edge** (P8/P2). Activa el
  flag muerto `reranker_enabled` de `HubChatbot` (regla "sin flags muertos" del bloque).
- **Encaje concreto**: `hybrid_search(top_k=N grande)` → `CrossEncoder.predict(pares (query,
  chunk))` → reordenar → recortar a top-k → mapear a `sources` (contrato P6 intacto).

---

## Lo que NUNCA se sustituye (perímetro de gobernanza)

Filtro `superseded` (P9) y aislamiento `owner_id`/`is_temporary` en `retriever.py`; el mapeo
`SearchResult` → `sources` (contrato de citas, P6); `embedding_service` local (P8);
`ingestion/quality/*` (auditoría de corpus, P9); `hasher.py` (dedup). Sustituir cualquiera de
estos sería la Opción B descartada en la decisión OWUI.

---

## Relación con el plan y estado

Esta relación **no añade trabajo**: reencuadra el Bloque RAG/ING ya aprobado bajo la lente
"dependencia madura vs. código propio". Correspondencia:

- RAG.3 = HNSW · RAG.4 = tsvector sustituye ILIKE · RAG.6 = reranker BGE · RAG.7/8 = chunking ·
  RAG.9 = metadato/re-embedding · Bloque ING = consolidación de parsers en Docling.

**Regla de esfuerzo**: el 80 % del valor está en **RAG.4** (sustituir `ILIKE`→FTS) y **RAG.6**
(añadir reranker, dep ya presente). El resto ya está apoyado o es *enhancement* opcional. Ninguna
mejora se cierra sin comparar recall@k/MRR contra la baseline de RAG.1 (regla dura del bloque).

## Documentos relacionados

- `docs/DECISION_OPENWEBUI_CARCASA_CHAT.md` §6 — por qué RAG/ingesta se queda en el perímetro.
- `docs/COMPARATIVA_RAG_LAMB.md` — origen de las mejoras (contra LAMB).
- `planificacion/Plan_TDD_Fase1.md` — Bloque RAG (RAG.1–RAG.14) y Bloque ING (detalle verbatim de cada prompt).
- `MARCO_GOBERNANZA_IA.md` — P2, P6, P7, P8, P9, P10 citados aquí.
