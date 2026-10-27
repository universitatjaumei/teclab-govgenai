# Comparativa del diseño RAG: Gov Gen AI Platform vs LAMB

> **Fecha**: 2026-07-15. Es una foto: las rutas de este repositorio que cita son las de esa
> fecha, y algunas ya no existen.
> **Fuentes**: análisis del código real de ambos proyectos — `AI_agents_hub` (este repo) y LAMB (`C:\Users\fabra\Documents\LAMB_MOODLE\lamb`, backend + `lamb-kb-server-stable` + `Documentation/lamb_architecture_v2.md` v2.6).
> **Finalidad**: valorar si el planteamiento RAG de este proyecto es comparable al de LAMB, identificar qué incorporar, y decidir si conviene seguir invirtiendo en RAG frente a la deriva del sector hacia sistemas agénticos.

---

## Veredicto general

**El planteamiento de Gov Gen AI Platform es plenamente comparable, y en varios ejes más avanzado que el de LAMB.** Los dos proyectos están en ligas de sofisticación similares pero han invertido en cosas distintas:

- **LAMB** destaca en extensibilidad por plugins, variedad de formatos de ingesta y trazabilidad de jobs.
- **Gov Gen AI** destaca en estrategia de retrieval multi-modo, higiene de corpus, citación verificable y arquitectura de despliegue (edge/cloud, portabilidad).

Ambos comparten la misma debilidad central: **el retrieval en sí es básico en los dos** (sin reranker, sin BM25 real, sin MMR).

---

## 1. Arquitectura general

| Eje | Gov Gen AI Platform | LAMB |
|---|---|---|
| Topología | Monolito modular FastAPI, con fronteras internas edge/cloud (`DEPLOY_MODE`) | Dos servicios: backend FastAPI (9099) + **KB Server** microservicio (9090, HTTP), más un Library Manager opcional |
| BD vectorial | **pgvector** en PostgreSQL (columna `Vector(1024)`, coseno) | **ChromaDB embebido** (PersistentClient) + SQLite para metadatos |
| Unidad canónica | `HubDocument` (markdown completo, hash, URL canónica) + `HubDocumentChunk` | Colección → ficheros → chunks; el fichero crudo vive en disco local del KB server |
| Config vs datos | Dos `DeclarativeBase` (config sincronizable / operacional edge) + `ConfigProvider` | Registro `kb_registry` en el backend; el KB server es "tonto" respecto a permisos |
| Ficheros | `StorageService` (fsspec → GCS/MinIO/local) | Disco local del KB server, servido por URL pública |

**Lectura.** LAMB ya materializó la separación en microservicio que este proyecto tiene prevista como criterio futuro, pero sobre una base **no escalable horizontalmente**: ChromaDB embebido + SQLite atan el KB server a un nodo, con semáforo de 3 ingestas concurrentes y timeout de 6 minutos por job. La elección pgvector + fsspec es estructuralmente superior para nuestro objetivo, que es **estado gestionado fuera de la máquina** (Cloud SQL + GCS): la aplicación corre hoy en una sola VM, que tampoco escala en horizontal, pero nada de lo que importa vive en ella y por tanto la puerta sigue abierta. La frontera edge/cloud no tiene equivalente en LAMB (lo más parecido — un KB server por organización — es aislamiento físico, no un modelo de despliegue híbrido).

Seguridad: el KB server de LAMB confía en un bearer token estático compartido (con default conocido `0p3n-w3bu!`), pero toda la autorización pasa por un proxy. En Gov Gen AI la autorización usuario↔organización↔chatbot en chat/ingesta está reconocida como pendiente (bloque SEC). Ambos tienen deuda aquí, de tipos distintos.

## 2. Ingesta

**LAMB es claramente más rico:**

- **Formatos**: PDF, DOCX, PPTX, XLSX, HTML, EPUB, CSV, audio (mp3/wav), ZIP, URLs con Firecrawl (render JS, crawling con profundidad) y **transcripciones de YouTube con timestamps** (vía MarkItDown, pymupdf, yt-dlp). Gov Gen AI hoy acepta solo PDF (Docling) y URLs/crawling con spiders propios.
- **Sistema de plugins**: cada plugin de ingesta declara sus parámetros de forma autodescriptiva y la UI genera el formulario dinámicamente, con gobernanza por env var (`DISABLE|SIMPLIFIED|ADVANCED`). Es la filosofía SDUI/contract-first que este proyecto exige para AutomatIA, aplicada a la ingesta RAG.
- **Trazabilidad de jobs**: `FileRegistry` registra progreso granular (`progress_current/total/message` vía callback), timing por etapa y coste LLM de descripciones de imágenes. `HubIngestionJob` solo tiene `pending/running/completed/failed`.
- **Chunking**: además de splitters clásicos, ofrece **parent-child (small-to-big)**, chunking por sección con contexto jerárquico de cabeceras, por página, y temporal para vídeo — configurable por el creador. El `MarkdownChunker` (headers + recursivo, 1000/100 caracteres) es estructural y razonable, pero no configurable por chatbot y sin variante small-to-big.

**A favor de Gov Gen AI:**

- **Idempotencia y deduplicación** (hash SHA-256 con unique constraint, reemplazo por URL+idioma, manejo de carreras con savepoints) — LAMB no tiene ni dedup ni versionado.
- **Subsistema de calidad 9Q**: detección de páginas obsoletas/duplicadas/contradictorias con juez LLM, excluidas del retrieval. No existe en LAMB ni en la mayoría de plataformas RAG.
- **Chunks temporales por usuario** con TTL de 24 h.
- Ninguno de los dos usa cola externa (ambos: BackgroundTasks in-process; LAMB añade ThreadPool+Semaphore; Gov Gen AI añade saneamiento de jobs zombis al arrancar).

## 3. Embeddings

- **LAMB**: configurables **por colección e inmutables tras la creación** (JSON modelo/vendor/endpoint persistido), validados con un embedding de prueba al crear, reconstruidos desde el registro en cada query — consistencia ingesta/consulta garantizada por construcción. Proveedores: Ollama y cualquier endpoint OpenAI-compatible.
- **Gov Gen AI**: BGE-M3 local (1024d) hardcodeado; `GoogleEmbeddingService` (768d) existe pero es **incompatible con el esquema `Vector(1024)`** y no hay cableado de selección, ni versión de modelo registrada en los chunks, ni ruta de re-embedding.

Es el eje donde LAMB tiene el diseño más limpio y este proyecto el riesgo más concreto: cambiar de modelo de embedding hoy no tiene ni metadato ni mecanismo.

## 4. Recuperación

| Capacidad | Gov Gen AI | LAMB |
|---|---|---|
| Vectorial | Coseno pgvector (**sin índice HNSW** — scan exacto) | Coseno ChromaDB (HNSW nativo) |
| Léxica | ILIKE-AND sin ranking, fusionada por **RRF** (k=60, 0.7 vector) | No existe |
| Híbrido | Sí (pata léxica débil) | No — kNN puro |
| Reranker / MMR / umbral | No (`reranker_enabled`/`min_retrieval_score` existen en config pero nadie los consume) | No (threshold post-hoc; `simple_rag` lo fija a 0.0) |
| Query rewriting conversacional | **No** — se busca solo con el último mensaje | **Sí** — `context_aware_rag` reescribe la query con un modelo pequeño usando ~10 mensajes de historial |
| Small-to-big | No | Sí (`parent_child_query` + `hierarchical_ingest`) |
| Modos de retrieval | **3**: RAG / long-context (≤128k) / agéntico (tools list/read), con recomendador automático por tamaño de corpus | 1 (vectorial), con variantes de processor (simple / context-aware / hierarchical / single-file / rubric) |
| Higiene de corpus | Exclusión de chunks `superseded` | No |
| Async | Pipeline async real | `requests` síncrono en pipeline async, colecciones consultadas secuencialmente |

**Lectura.** El diseño tri-modo con recomendador automático es la decisión más distintiva de todo el análisis y LAMB no tiene nada equivalente. El híbrido RRF, aunque con pata léxica pobre, ya supera el kNN puro de LAMB. Pero LAMB tiene dos técnicas que faltan aquí: **query rewriting conversacional** y **parent-child retrieval**. La primera es probablemente el gap de calidad más importante: en conversación real ("¿y el plazo?" tras hablar de una beca), buscar solo con el último mensaje degrada seriamente el recall. Ninguno de los dos controla el presupuesto de tokens del contexto inyectado (Gov Gen AI solo en long-context).

## 5. Integración RAG→LLM y citación

- **LAMB**: pipeline de completions totalmente plugable (connector / prompt processor / RAG processor cargados con importlib), API OpenAI-compatible, y un **connector `bypass` de depuración** que devuelve el prompt final construido sin llamar al LLM. Citación "por prompt" (sección `## Available Sources`, se confía en el LLM). Fuentes muy ricas (URL original, markdown, imágenes, timestamp de YouTube).
- **Gov Gen AI**: grafo LangGraph con detección de idioma, estrategia inyectada y **`enforce_citation_contract`**: si la respuesta no contiene al menos un enlace del conjunto permitido, se sustituye entera por un fallback. Para administración pública, la citación **verificada** post-generación es objetivamente superior a la citación "por confianza" (aunque el guardrail es de grano grueso: una cita válida legitima toda la respuesta). Además: router multi-materia por embeddings, SSE con eventos tipados, tracing Langfuse.

Sombra propia: coexisten **dos sistemas de grafos** (producción `agent/graph.py` y `public_graphs/CoreGraph` con quality gate y cascada de config, testeado pero no cableado a ningún endpoint). Hasta consolidar, el quality gate y la cascada org→chatbot no actúan en producción, y hay flags de admin que no hacen nada.

## 6. Evaluación

Ninguno tiene evaluación cuantitativa real del retrieval. Gov Gen AI: métricas RAGAS aisladas (con fallback léxico crudo) sin datasets ni CI. LAMB: tracing LangSmith y un framework de **test scenarios** donde el educador define prompts que se ejecutan por el pipeline real y se puntúan manualmente — más útil en la práctica hoy, aunque sea evaluación humana.

---

## 7. Qué incorporar de LAMB (priorizado por valor/esfuerzo)

1. **Query rewriting conversacional** (equivalente a `context_aware_rag`): un LLM pequeño reescribe la consulta usando el historial antes de buscar. Encaja como paso previo en `search_or_skip` o como estrategia del CoreGraph. La mejora de calidad de retrieval más barata disponible. Con fallback al último mensaje.
2. **Metadato de modelo de embedding por documento/chunk + configuración inmutable validada al crear el chatbot** (patrón "por colección" de LAMB): registrar `embedding_model` y dimensión, validar con embedding de prueba, reconstruir la config en cada query. Prerrequisito para cualquier migración futura de modelo.
3. **Parent-child chunking (small-to-big)** como opción del chunker: embeber chunks pequeños para precisión y devolver al LLM la sección padre. `MarkdownChunker` ya conserva la jerarquía de headers en metadata. De paso, hacer configurable el chunking por chatbot.
4. **Modo bypass/debug del pipeline**: devolver el prompt final construido (system + contexto + fuentes) sin llamar al LLM. Trivial en el grafo; muy útil para depurar calidad de contexto.
5. **Progreso granular de jobs de ingesta** (patrón `progress_callback` + `processing_stats` JSON): current/total/mensaje y estadísticas por etapa en `HubIngestionJob`. Mejora la UX de admin de cara a ING.0.
6. **Test scenarios por chatbot** (medio plazo): prompts de prueba definidos por el admin, ejecutados por el pipeline completo con veredicto humano. Puente pragmático hasta que la evaluación RAGAS madure; combina con `FeedbackService`/Langfuse.
7. **Ampliar formatos de ingesta vía Docling/MarkItDown** (DOCX, PPTX, HTML subido) cuando toque ING.0 — sin copiar el sistema de plugins entero: el enfoque estrategia + factory ya cumple la misma función con menos superficie.

### Qué NO copiar de LAMB

- ChromaDB embebido + SQLite (pgvector es la elección correcta para la infraestructura objetivo).
- Ficheros en disco local del servidor (StorageService/fsspec es superior).
- El copy-paste de sus RAG processors (~80% duplicado entre variantes) — el patrón Strategy es el diseño limpio de esa idea.
- I/O síncrona (`requests`) dentro del pipeline.
- Token estático compartido entre servicios.

### Donde Gov Gen AI va por delante (no desmontar)

Tri-modo con recomendador automático, `HubDocument` como unidad citable, citación forzada verificable, higiene de corpus 9Q, dedup/idempotencia, frontera edge/cloud, multilingüe de serie y async real.

---

## 8. Mejoras adicionales para reforzar el RAG (más allá de LAMB)

### Calidad de recuperación (el gap más rentable)

1. **Pata léxica real: `tsvector` + índice GIN en `HubDocumentChunk`.** Sustituir el ILIKE-AND por full-text search de Postgres con configuración de idioma (`spanish` nativo; catalán vía Snowball/Hunspell). El RRF ya está montado en `retriever.py` — solo se cambia la rama débil. BM25 captura lo que los embeddings pierden en dominio administrativo: códigos de procedimiento, siglas, nombres de convocatorias, artículos de normativa.
2. **Índice HNSW en pgvector.** Hoy la búsqueda vectorial es scan secuencial. Una migración Alembic (`USING hnsw (embedding vector_cosine_ops)`) lo resuelve antes de que el corpus crezca.
3. **Reranker cross-encoder — activar el flag muerto.** `reranker_enabled` ya existe en `HubChatbot`; darle consumidor. `BAAI/bge-reranker-v2-m3` es la pareja natural de BGE-M3 (mismo multilingüe, mismo proveedor) y encaja en el futuro microservicio de embeddings. Patrón: top-30 híbrido → rerankear → quedarse 8.
4. **Contextual retrieval (enriquecimiento de chunks antes de embeber).** Anteponer a cada chunk una frase de contexto ("Este fragmento pertenece al procedimiento X, sección Z..."). Empezar gratis concatenando los `header_1..3` ya presentes en metadata al texto embebido; escalar a la variante con LLM en la ingesta (coste único, no por consulta).
5. **Presupuesto de tokens del contexto inyectado** en modo RAG: ordenar evidencia por score, cortar en N tokens, deduplicar solapamientos.

### Bucle de calidad

6. **Dataset dorado + CI de regresión de retrieval.** 30–50 preguntas reales por chatbot con los documentos que deberían recuperarse. Métricas puras de recuperación (recall@k, MRR) sin LLM — corren en CI en segundos y validan objetivamente cada mejora antes de desplegarla. RAGAS queda para evaluación periódica de fidelidad, no para CI.
7. **Cerrar el bucle feedback → hueco de contenido.** Clusterizar interacciones mal puntuadas o sin cita (los fallbacks de `enforce_citation_contract` son señal gratuita de "no encontré nada") para detectar qué falta en el corpus. En un chatbot institucional la mayoría de fallos son del corpus, no del retriever.

### Consolidación (deuda que bloquea lo demás)

8. **Unificar los dos grafos y llevar el quality gate a producción.** El umbral de calidad, la cascada de config org→chatbot y las políticas de idioma ya están escritas y testeadas en `public_graphs/` — no actúan porque el endpoint sirve el grafo antiguo. Consolidar desbloquea los puntos 3, 5 y 6 casi sin código nuevo.

Menores: embeber por lotes en el watcher (hoy chunk a chunk); caché semántica de respuestas para consultas repetitivas de portal público.

Deberes ya registrados en PROJECT_STATE que la comparativa confirma como gaps reales: activar o retirar `reranker_enabled`/`min_retrieval_score` de la API admin, y cerrar la autorización multi-tenant (bloque SEC).

---

## 9. ¿Invertir en RAG o derivar hacia agentes?

Estado del debate (verificado julio 2026):

- La consigna viral de principios de 2026 fue "RAG ha muerto", pero el consenso técnico es más matizado: **murió el RAG ingenuo de un solo paso; la recuperación subió de capa**. El patrón dominante es *agent-as-retriever*: la búsqueda se convierte en herramienta y el agente decide cuándo buscar, evalúa la evidencia e itera.
- La economía no acompaña a agentificarlo todo: el RAG agéntico cuesta **3–10× más tokens y 2–5× más latencia** que el pipeline clásico, y la recuperación indexada sigue siendo **hasta 8–82× más barata** que contexto largo para cargas típicas. La recomendación empresarial repetida: no pagar la prima agéntica en el ~80% de consultas que no la necesitan.

### Traducción al caso Gov Gen AI

**El diseño tri-modo ya es la respuesta a esta pregunta.** `MD_AGENT_SELECTOR` con `list_documents`/`read_document` *es* agentic retrieval (el enfoque que Claude Code adoptó al abandonar su vector DB local), `MD_LONG_CONTEXT` cubre el caso donde el corpus cabe en ventana, y el RAG vectorial cubre el volumen barato. Pocos productos tienen las tres vías con selección automática.

**Para el segmento objetivo (chatbot informacional de administración pública), el pipeline governado sigue siendo el caballo de batalla**: alto volumen, consultas mayoritariamente simples, exigencia de latencia y coste bajos, y exigencia regulatoria de trazabilidad y citación — todo favorece un pipeline determinista con guardrails sobre un agente de bucle libre. El movimiento correcto es el **escalado por complejidad**: pipeline RAG por defecto, escalada a modo agéntico cuando el quality gate detecta evidencia insuficiente. El CoreGraph con quality gate + fallback ya tiene el hueco arquitectónico exacto para "si la evidencia no basta → reintentar con estrategia agéntica".

**Inversiones que sobreviven al giro agéntico (invertir aquí):** un agente que llama a `search` como herramienta rinde lo que rinda esa herramienta — índice híbrido, reranker, tsvector y HNSW mejoran ambos mundos. Igual que la calidad del corpus (9Q, dedup, `HubDocument`), la citación verificable, la evaluación con dataset dorado y la multi-tenancy.

**Qué evitar:** orquestación de pipeline cada vez más barroca (multi-hop cableado, GraphRAG, cadenas de reescritura de N pasos) — el terreno que los bucles agénticos sustituyen con menos código. Excepción: el query rewriting conversacional, tan barato y de tanto impacto que compensa aunque a medio plazo un agente lo haga solo.

### En una frase

Invertir en los **cimientos** del RAG (índice híbrido real, reranker, corpus limpio, evaluación) porque son la herramienta que cualquier agente futuro usará; consolidar el grafo para poder escalar de pipeline a agéntico según la consulta; y no invertir en sofisticación de pipeline que un bucle agéntico haría gratis.

### Fuentes externas

- [LlamaIndex — RAG is dead, long live agentic retrieval](https://www.llamaindex.ai/blog/rag-is-dead-long-live-agentic-retrieval)
- [LightOn — Retrieval in the Age of Agents](https://lighton.ai/lighton-blogs/rag-is-dead-long-live-rag-retrieval-in-the-age-of-agents)
- [Forbes — RAG Didn't Die, It Moved Up The Stack](https://www.forbes.com/councils/forbestechcouncil/2026/07/09/rag-didnt-die-it-moved-up-the-stack/)
- [Extend — Agentic RAG vs Traditional RAG](https://www.extend.ai/resources/agentic-rag-vs-traditional-rag)
- [byteiota — RAG vs Long Context 2026](https://byteiota.com/rag-vs-long-context-2026-retrieval-debate/)
- [Squirro — State of RAG 2026](https://squirro.com/squirro-blog/state-of-rag-genai)
- [Sphere — Cost-Honest Comparison](https://www.sphereinc.com/blogs/agentic-rag-vs-traditional-rag-vs-chatgpt)
