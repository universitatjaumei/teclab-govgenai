"""Modelos ORM operacionales para agents_hub."""

import uuid
from datetime import date, datetime, timezone
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from server.app.core.ambito import Ambito, declarar
from server.app.modules.agents_hub.database.base import HubOperationalBase


class HubWebSite(HubOperationalBase):
    """Sitio web rastreado. Unidad de crawl + auditoría; propiedad de la organización, no del chatbot."""

    __tablename__ = "hub_web_sites"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organizacion_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    root_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    sitemap_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    spider_type: Mapped[str] = mapped_column(String(50), nullable=False, default="generic")
    config_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    crawl_interval_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=24)
    # RAS.3 — la cola pendiente de una ejecución interrumpida, con lo ya visitado. Vivía sólo en
    # memoria: un corte en la página 8.000 obligaba a empezar de cero, y con la pausa de cortesía
    # eso son horas de peticiones repetidas contra el mismo servidor.
    crawl_frontier: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    audit_semantic_scope: Mapped[str] = mapped_column(
        String(20), nullable=False, default="ingested"
    )
    last_crawled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class HubWebSection(HubOperationalBase):
    """Sección o bloque dentro de un sitio: el apartado como **dato** (DIN.1).

    Hasta aquí un apartado se expresaba creando un `HubWebSite` entero con su
    `url_regex_filter` (RAS.5). Tenía una razón —cada apartado tiene un responsable
    distinto, que aquí es la columna `owner`— pero duplicaba `root_url`, sitemap,
    cortesía y criterios de juicio, y hacía que «añadir el apartado de becas» fuera un
    alta técnica en vez de un formulario de quien cura.

    Los campos están en inglés como los de `HubWebSite`, para leerse como su vecina.
    Llega a su organización **por el sitio**: no tiene `organizacion_id`, y eso es lo
    que dice su fila en `docs/MULTITENENCIA.md`.

    **Nulo hereda**: `crawl_interval_hours` y `criteria_json` vacíos valen los del
    sitio; lo resuelve `curation/secciones.parametros_efectivos`. `mode` lleva
    `CheckConstraint` —dos valores estables con consumidor en el código— y
    `criteria_json` no: son vocabulario que crecerá, como los criterios de sitio de
    CUR.2.1.
    """

    __tablename__ = "hub_web_sections"
    __table_args__ = (
        UniqueConstraint("site_id", "name", name="uq_section_site_name"),
        CheckConstraint(
            "pattern_kind IN ('path_prefix', 'regex')", name="ck_section_pattern_kind"
        ),
        CheckConstraint("mode IN ('manual', 'automatic')", name="ck_section_mode"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    site_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hub_web_sites.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    #: El nombre que le da quien cura: «Jornadas», «Eventos».
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    #: Lo que delimita la sección. Se valida al guardar (`secciones.validar_patron`): un regex
    #: que no compila rompería todos los rastreos y el fallo saldría lejos del formulario.
    pattern: Mapped[str] = mapped_column(String(2048), nullable=False)
    pattern_kind: Mapped[str] = mapped_column(
        String(20), nullable=False, default="path_prefix"
    )
    #: NULL = hereda la cadencia del sitio.
    crawl_interval_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: El defecto es `manual` **a propósito**, al contrario que `auto_ingest_new` (que nació
    #: con default `True`): una sección nueva no automatiza hasta que alguien lo dice. Es el
    #: principio del bloque, «curación una vez, automatización después».
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    #: Overrides de criterios de juicio sobre los del sitio; NULL = hereda. Se funden **clave a
    #: clave**: un override de `stale_days` no puede borrar el umbral de retirada del sitio.
    criteria_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    #: Responsable del apartado: la razón original de RAS.5 para partir por sitios, que aquí es
    #: un campo y no una tabla nueva.
    owner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    #: La sección tiene su propio reloj: es lo que permite cadencias distintas en un mismo sitio.
    last_crawled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class HubCrawlRun(HubOperationalBase):
    """El diario de una pasada de curación: qué ámbito cubrió y qué hizo (DIN.6).

    El `summary` del job se calculaba, se devolvía y **se perdía**. La confianza en una
    automatización se construye pudiendo auditarla barata: si quien cura no ve lo que
    hizo, la apagará al primer susto — y tendrá razón.

    **Por qué una tabla nueva y no `hub_ingestion_jobs`** (el prompt pedía comprobarlo
    antes): aquélla es de **un documento** —`chatbot_id` NOT NULL, `source_url`,
    `chunks_processed`— y una pasada no tiene chatbot (puede tocar varios, o ninguno) ni
    una URL; lo que tiene es un sitio, una sección y un diff. Encajarla ahí exigiría un
    `chatbot_id` inventado y un `source_url` que no es una URL, y el listado de trabajos
    de ingesta pasaría a mezclar dos cosas que nadie querría ver juntas.

    `section_id` es `SET NULL` y va con `scope_label` al lado a propósito: **el diario es
    historia**, y una historia que se reescribe cuando alguien borra una sección no sirve
    para auditar nada. Con la etiqueta, la fila sigue diciendo qué cubrió.
    """

    __tablename__ = "hub_crawl_runs"
    __table_args__ = (
        Index("ix_hub_crawl_runs_site_started", "site_id", "started_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    site_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hub_web_sites.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    section_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hub_web_sections.id", ondelete="SET NULL", name="fk_run_section"),
        nullable=True,
        index=True,
    )
    #: Qué cubrió la pasada, en texto: el nombre de la sección, o «sitio». Sobrevive al borrado
    #: de la sección, que es lo que hace que el diario siga siendo historia.
    scope_label: Mapped[str] = mapped_column(String(255), nullable=False)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    pages_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pages_new: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pages_changed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pages_gone: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pages_error: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    documents_auto_ingested: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    documents_reingested: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    documents_auto_retired: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pages_blocked_by_findings: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    findings_retired: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    #: El rastreo no vio el ámbito entero, y por qué (RAS.1). Mientras sea cierto no hay bajas.
    truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    stop_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    #: Los errores de la pasada, tal cual. Un contador diría cuántos y no cuáles.
    errors: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class HubCrawledPage(HubOperationalBase):
    """Página rastreada de un sitio. Acumula señales de frescura y flags de higiene."""

    __tablename__ = "hub_crawled_pages"
    __table_args__ = (
        UniqueConstraint("site_id", "url", name="uq_page_site_url"),
        # HNSW sobre el embedding de pagina (RAG.3): lo consulta por coseno el detector
        # semantico de 9Q. Declarado tambien en la migracion; ambos sitios, o la BD de los
        # tests (create_all) no lo tendria.
        Index(
            "ix_hub_crawled_pages_embedding_hnsw",
            "page_embedding",
            postgresql_using="hnsw",
            postgresql_ops={"page_embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    site_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hub_web_sites.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    canonical_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    markdown_content: Mapped[str | None] = mapped_column(Text, nullable=True)

    # RAS.2 — por qué esta página no se puede leer sin renderizar, si es el caso. La evidencia se
    # recoge al rastrear (es el único momento en que existe el HTML) y la lee el detector, que
    # corre después: con señales, la página se avisa como `needs_javascript` en vez de acusarla
    # de estar vacía. Lista vacía = se leyó bien.
    render_signals: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB, nullable=True, default=list
    )

    # CUR.1 — la fecha que la propia página publica y la unidad que la mantiene. El portal las sirve
    # en el HTML y las estábamos ignorando: `stale` adivinaba la antigüedad del año más reciente
    # citado en el texto y marcaba tres de cada cuatro páginas. Con esto, «desactualizada» es un
    # dato, y el responsable es lo que hace accionable el informe: dice a quién escribir.
    content_published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    content_owner: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # embedding de página para auditoría semántica en modo "full" (9Q.4).
    # Misma dimensión que HubDocumentChunk.embedding (BGE-M3 = 1024) para que cruce coseno.
    # None = sin embedding (no auditada en modo full todavía).
    page_embedding: Mapped[list[float] | None] = mapped_column(Vector(1024), nullable=True)

    # señales de actualidad (las pobla 9Q.2)
    http_last_modified: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    http_etag: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sitemap_lastmod: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    declared_canonical_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    content_year: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # flags de higiene (los consolida 9Q.5)
    superseded: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True
    )
    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    superseded_by_page_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    last_crawled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # RAS.3 — de qué fallo se trata y cuántas veces se intentó. Un 404 es una respuesta («esto ya
    # no está») y un timeout es un fallo del que no se concluye nada sobre la página; sin
    # distinguirlos, los dos salían como hallazgo crítico y un rastreo con mala red se llenaba de
    # acusaciones falsas.
    error_kind: Mapped[str | None] = mapped_column(String(20), nullable=True)
    error_attempts: Mapped[int | None] = mapped_column(Integer, nullable=True)


class HubCorpusSelection(HubOperationalBase):
    """Selección N:M chatbot→sitio. La regla decide qué páginas alimentan el corpus."""

    __tablename__ = "hub_corpus_selections"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    chatbot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    site_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hub_web_sites.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rule_type: Mapped[str] = mapped_column(String(20), nullable=False)
    rule_value: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    #: DIN.3 — apunta a una sección del sitio en vez de repetir su patrón. **Cuando está puesto,
    #: el patrón efectivo es el de la sección y `rule_value` se ignora**: dos sitios de verdad de
    #: la misma regla —el patrón de la sección y este valor— divergirían en cuanto alguien
    #: editara uno. Nulo = la regla vale por sí misma, que es el camino de siempre.
    #: `RESTRICT` y no `CASCADE`: borrar una sección no puede llevarse por delante la selección
    #: que apunta a ella. Con la auto-retirada de DIN.4 detrás, perder la selección no es perder
    #: una fila: es dejar de mantener lo que ya está en el corpus.
    section_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hub_web_sections.id", ondelete="RESTRICT", name="fk_selection_section"),
        nullable=True,
        index=True,
    )
    auto_ingest_new: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class HubDocument(HubOperationalBase):
    """Documento citable. Unidad atomica del corpus de un chatbot.

    Metadatos del corpus normativo (ING.0.2). **Regla que decide el esquema**: una
    columna de primer nivel SOLO si algo la filtra, la ordena o la usa como puerta;
    todo lo demas va a `doc_metadata` JSONB. Sin esa disciplina los 56 campos del
    esquema de metadatos (`vocabulari/esquema_metadades.yaml`) acabarian aqui.

    Los codigos de vocabulario (`ambit_principal`, `submateries`) **no llevan
    CheckConstraint**: son dato revisable y se validan en la capa de contrato
    (ING.0.3) contra `HubVocabularyTerm`. Ver CLAUDE.md §5. `nivell_acces`,
    `us_assistents` y `content_class` si lo llevan: son enumeraciones estables con
    consumidor (filtrado fail-closed de VIS.1).

    `source_kind` expresa el origen y sus valores documentados son
    'crawler' | 'upload' | 'publicacio' | 'boe'. No hay columna `origen` aparte:
    duplicar el eje seria deuda.
    """

    __tablename__ = "hub_documents"
    __table_args__ = (
        UniqueConstraint("chatbot_id", "content_hash", name="uq_document_chatbot_hash"),
        CheckConstraint(
            "nivell_acces IN ('public', 'intern', 'restringit')",
            name="ck_document_nivell_acces",
        ),
        CheckConstraint(
            "us_assistents IN ('si', 'restringit', 'no')",
            name="ck_document_us_assistents",
        ),
        CheckConstraint(
            "content_class IN ('regulation', 'faq', 'generic')",
            name="ck_document_content_class",
        ),
        Index("ix_hub_documents_chatbot_ambit", "chatbot_id", "ambit_principal"),
        Index("ix_hub_documents_chatbot_nivell", "chatbot_id", "nivell_acces"),
        Index(
            "ix_hub_documents_submateries",
            "submateries",
            postgresql_using="gin",
        ),
        Index(
            "ix_hub_documents_submateries_internes",
            "submateries_internes",
            postgresql_using="gin",
        ),
        Index(
            "ix_hub_documents_doc_metadata",
            "doc_metadata",
            postgresql_using="gin",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    chatbot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    canonical_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    markdown_content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    language: Mapped[str] = mapped_column(String(10), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    crawled_page_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hub_crawled_pages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # --- Clasificacion (ING.0.2). Vocabulario validado en ING.0.3, no con CHECK ---
    content_class: Mapped[str] = mapped_column(
        String(20), nullable=False, default="generic"
    )
    ambit_principal: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # ARRAY del dialecto PostgreSQL y no el genérico: VIS.1 filtra con el operador de
    # solapamiento `&&` (`.overlap()`), que solo expone el tipo del dialecto.
    ambits_secundaris: Mapped[list[str]] = mapped_column(
        PG_ARRAY(String), nullable=False, default=list
    )
    submateries: Mapped[list[str]] = mapped_column(
        PG_ARRAY(String), nullable=False, default=list
    )
    submateries_internes: Mapped[list[str]] = mapped_column(
        PG_ARRAY(String), nullable=False, default=list
    )
    # --- Acceso y uso. nivell_acces se impone en la capa de recuperacion (VIS.1) ---
    nivell_acces: Mapped[str] = mapped_column(
        String(20), nullable=False, default="public"
    )
    us_assistents: Mapped[str] = mapped_column(
        String(20), nullable=False, default="si"
    )
    # --- Version idiomatica: el EMPAREJAMIENTO, no una jerarquia (ACT.3) ---
    #
    # `canonica` se retiro el 2026-08-28. Las dos versiones publicadas de una norma son
    # OFICIALES —la traduccion la publica Secretaria General o el organo que dicto la
    # resolucion— asi que no hay una que valga mas, y el campo invitaba a leer lo contrario.
    # Lo que la recuperacion necesita es saber que dos documentos son la MISMA norma, y eso
    # es `versio_idiomatica_de`. La direccion en que se declara es un detalle de escritura:
    # `metadata_filter` resuelve la hermana en los dos sentidos.
    versio_idiomatica_de: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hub_documents.id", ondelete="SET NULL"),
        nullable=True,
    )
    # --- Vigencia. vigencia_validada_el NULL => el asistente ADVIERTE (VIS.3) ---
    estat_vigencia: Mapped[str | None] = mapped_column(String(20), nullable=True)
    vigencia_validada_el: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Quién firmó esa comprobación (REV.6). Columna propia y **no `revisat_per`**: ese campo
    # viene del frontmatter del corpus y es la revisión humana del *contenido*, obligatoria
    # para `content_class: regulation`. Escribir ahí al que valida la vigencia destruiría un
    # dato que el contrato exige, y la pantalla pasaría a enseñar a quien pulsó el botón en
    # lugar del revisor declarado.
    vigencia_validada_per: Mapped[str | None] = mapped_column(String(255), nullable=True)
    revisat_per: Mapped[str | None] = mapped_column(String(255), nullable=True)
    revisat_el: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    data_revisio_prevista: Mapped[date | None] = mapped_column(Date, nullable=True)
    # --- Sincronizacion con el registro de publicacion (SYNC.1) ---
    id_publicacio: Mapped[str | None] = mapped_column(
        String(80), nullable=True, index=True
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # --- El resto del esquema de 56 campos ---
    doc_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class HubDocumentChunk(HubOperationalBase):
    """Fragmento de documento con embedding vectorial."""

    __tablename__ = "hub_document_chunks"
    __table_args__ = (
        # Indice ANN de la busqueda vectorial (RAG.3). Sin el, cada consulta calcula la
        # distancia coseno contra todos los chunks del chatbot: un escaneo secuencial por
        # pregunta. `vector_cosine_ops` porque `retriever.py` ordena por `cosine_distance`;
        # un opclass distinto dejaria el indice inservible para esa consulta.
        Index(
            "ix_hub_document_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        # Indice de la rama lexica del hibrido (RAG.4).
        Index("ix_hub_document_chunks_tsv", "tsv", postgresql_using="gin"),
        # RAG.9: la guarda de espacio vectorial corre en CADA consulta de chat, y su pregunta
        # —"que pares (modelo, dimension) hay en este chatbot"— es un DISTINCT sobre todos los
        # chunks del chatbot. Con este indice es un recorrido solo-indice de entradas
        # estrechas; sin el, el caso bueno (no hay desajuste) obliga a leer el heap entero
        # por pregunta, que es la forma mas cara posible de responder "no pasa nada".
        # PIL.1 añade `embedding_task_type` a la tripleta que la guarda pregunta. Si se
        # quedara fuera del indice, el DISTINCT volveria al heap y la guarda dejaria de ser
        # barata justo despues de haberla hecho mas estricta.
        Index(
            "ix_hub_document_chunks_embedding_space",
            "chatbot_id",
            "embedding_model",
            "embedding_dim",
            "embedding_task_type",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    chatbot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    # FK añadida en ING.0.2: VIS.1 filtra los chunks por los metadatos de su documento
    # mediante JOIN. Nullable porque los chunks temporales de subida de usuario no
    # tienen documento (los acota owner_id).
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hub_documents.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1024), nullable=True)
    chunk_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    language: Mapped[str] = mapped_column(String(10), nullable=False)
    # --- Parent-child, small-to-big (RAG.8) ---
    # La seccion estructural completa a la que pertenece este fragmento. Se busca con el
    # hijo —vector mas especifico, se encuentra mejor— y se responde con el padre, que trae
    # el contexto que al hijo le falta. NULL con la estrategia 'structural'.
    # Columna directa y no JOIN: el padre ya existe como texto y duplicarlo cuesta menos que
    # una tabla de secciones que habria que mantener sincronizada con el troceado.
    parent_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    # --- Procedencia del vector (MOD.1, obligatoria desde RAG.9) ---
    # Con que modelo y a que dimension se genero `embedding`. Misma dimension NO significa
    # mismo espacio vectorial: el coseno entre vectores de dos modelos distintos no da error,
    # da resultados malos. Sin esto, cambiar de modelo es una averia silenciosa.
    # NOT NULL tras el backfill de RAG.9: mientras existieron filas sin procedencia habia que
    # tratarlas como desconocidas, y "desconocido" es el hueco por el que se cuela justo la
    # averia que la columna vino a impedir. Rellenables => obligatorias.
    embedding_model: Mapped[str] = mapped_column(String(255), nullable=False)
    embedding_dim: Mapped[int] = mapped_column(Integer, nullable=False)
    # PIL.1. Nullable a propósito: el modelo local no distingue propósito y `None` es su
    # declaración honesta, no un dato que falte. Lo que NO puede pasar es que un corpus
    # embebido como consulta se sirva como documento sin que nadie lo note — de eso se
    # ocupa `assert_embedding_space_matches`, que compara la tripleta completa.
    embedding_task_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # El texto que SE EMBEBIO, que desde RAG.7 no es `content`: lleva delante titulo y
    # jerarquia. Se guarda para que re-embeber sea fiel — reconstruirlo desde `content`
    # produciria vectores que la ingesta nunca genero, y la incoherencia no daria error.
    # NULL en los chunks anteriores a RAG.9: no se puede reconstruir, asi que la CLI de
    # re-embedding los cuenta aparte y remite a `recalculate-corpus`, que si re-trocea.
    embedding_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # --- Rama lexica del hibrido (RAG.4) ---
    # Puente bilingue del dominio ('despesa/gasto'), copiado del documento en la ingesta.
    # Se DENORMALIZA aqui porque una columna generada solo puede referirse a su propia fila,
    # y los terminos viven en hub_documents.doc_metadata. Refrescarlos cuando cambien es un
    # UPDATE con JOIN, no un re-embedding: el invariante de CLAUDE.md §5 se conserva.
    # Aqui va SOLO el puente lexico; la taxonomia (ambit/submateries) no entra jamas.
    bilingual_terms: Mapped[str | None] = mapped_column(Text, nullable=True)
    # `simple` para todo lo que no sea castellano: PostgreSQL core no trae stemmer catalan,
    # asi que en catalan se busca por forma exacta. Un diccionario Snowball catalan seria
    # mejora de despliegue, no de codigo.
    tsv: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector("
            "CASE WHEN language = 'es' THEN 'spanish'::regconfig "
            "ELSE 'simple'::regconfig END, "
            "coalesce(content, '') || ' ' || coalesce(bilingual_terms, ''))",
            persisted=True,
        ),
        nullable=True,
    )
    is_temporary: Mapped[bool] = mapped_column(Boolean, default=False)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class HubInteraction(HubOperationalBase):
    """Conversación usuario–asistente."""

    __tablename__ = "hub_interactions"
    __table_args__ = (
        # REV.1: mismos tres valores que `ck_test_run_verdict`, a propósito. Dos vocabularios
        # distintos para la misma idea acaban divergiendo, y entonces un informe que cruce
        # escenarios de prueba con conversaciones reales deja de poder escribirse.
        # Admite NULL porque NULL es "sin revisar", no valor inválido.
        CheckConstraint(
            "review_verdict IS NULL OR review_verdict IN ('good', 'bad', 'mixed')",
            name="ck_interaction_review_verdict",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    chatbot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    user_message: Mapped[str] = mapped_column(Text, nullable=False)
    assistant_message: Mapped[str] = mapped_column(Text, nullable=False)
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    feedback_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    feedback_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 'quality_gate' | 'citation' | NULL. NULL = la respuesta salió del camino normal.
    # RAG.14 lo consume para detectar huecos de corpus. Sin CheckConstraint: los motivos
    # son un vocabulario que crecerá (reranker, presupuesto de tokens...) y una restricción
    # en la BD obligaría a una migración por cada motivo nuevo.
    fallback_reason: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    # SEC.4: consumo real de la interacción. **Nullable a propósito**: las interacciones
    # anteriores a este prompt no tienen el dato y no se inventa. Un cero significaría «no
    # gastó nada», que es una afirmación distinta de «no lo sabemos».
    #
    # De dónde salió el número se anota en `interaction_metadata.usage_source`
    # ('provider' | 'estimated'): una cuota apoyada en una estimación silenciosa es una
    # cuota que no se puede defender ante quien la sufre.
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # El chat no la rellena, y es deliberado: la tabla de precios (`ModelPricing`, que
    # alimenta OpenRouter) vive en la BD de plataforma, y el chat es **edge**. Convertir
    # tokens en euros es asunto de facturación —cloud—, que ya tiene `calculate_cost`. La
    # columna queda porque las cuotas se miden en tokens pero se justifican en dinero, y el
    # día que facturación lo calcule tiene dónde escribirlo sin migrar otra vez.
    cost_estimated: Mapped[float | None] = mapped_column(Float, nullable=True)
    interaction_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    # --- Veredicto de quien revisa (REV.1) ---
    # Distinto de `feedback_score`/`feedback_text`, que son la valoración del USUARIO FINAL.
    # Esto es lo que dice quien audita: si la respuesta era adecuada y, sobre todo, por qué
    # no lo era — que es lo único que permite reformular la FAQ que la produjo.
    #
    # NULL = sin revisar, y es el estado por defecto: es lo que alimenta la cola. Un texto
    # 'pending' sería un veredicto más, y habría que acordarse de excluirlo en cada consulta.
    review_verdict: Mapped[str | None] = mapped_column(String(10), nullable=True, index=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    review_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # --- La solución, no sólo el veredicto (HIB.H) ---
    # Con el veredicto solo, cada conversación revisada vale una vez: la siguiente ablación
    # exige volver a pedir juicio humano sobre las mismas preguntas, y por eso las ablaciones
    # no se hacían. Con la fuente esperada estructurada, `escenario_metricas.py` calcula sola
    # si el documento esperado entró en lo recuperado, si el ancla abre el artículo correcto y
    # si un negativo se rechazó como debía.
    #
    # Misma forma que `expected_sources` de `HubTestScenario` y del contrato de HIB.G,
    # validada por el mismo modelo Pydantic: dos formas para la misma idea divergen, y con
    # ellas se cae el instrumental que cruza conversaciones reales con escenarios de prueba.
    #
    # **NULL es «no anotado», no lista vacía.** Una lista vacía afirmaría que el informador
    # miró y decidió que no hay fuente esperada, que es otra cosa. La diferencia es el
    # denominador de «cuántas están anotadas».
    review_expected_sources: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    review_reference_answer: Mapped[str | None] = mapped_column(Text, nullable=True)


class HubUsageCounter(HubOperationalBase):
    """Consumo acumulado por sujeto y ventana (SEC.4).

    **Vive en `HubOperationalBase` y no colgado del chatbot**, y no es un detalle: es dato de
    consumo del cliente final, no configuración, así que no se sincroniza al cloud. Un
    contador en `HubChatbot` rompería la frontera edge/cloud en cuanto la sync API empezara
    a copiar configuración.

    `window_key` es la ventana en texto —`'2026-08-02'` (día), `'2026-08'` (mes), `'total'`
    (acumulado, que reutiliza SEC.4.1)—. En texto y no como fecha porque las tres conviven
    en la misma columna y la clave única las distingue sin tabla aparte ni nulos.

    Se actualiza con un UPSERT atómico, nunca leyendo-modificando-escribiendo: el chat es
    concurrente y dos respuestas simultáneas del mismo usuario se pisarían los contadores,
    que es exactamente el hueco por el que se cuela quien quiera saltarse una cuota.
    """

    __tablename__ = "hub_usage_counters"
    __table_args__ = (
        UniqueConstraint(
            "subject_type", "subject_id", "window_key", name="uq_usage_counter_subject_window"
        ),
        CheckConstraint(
            "subject_type IN ('user', 'chatbot', 'organizacion', 'ip')",
            name="ck_usage_counter_subject_type",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    subject_type: Mapped[str] = mapped_column(String(20), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(255), nullable=False)
    window_key: Mapped[str] = mapped_column(String(20), nullable=False)
    tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class HubIngestionJob(HubOperationalBase):
    """Job de ingestión de documentos."""

    __tablename__ = "hub_ingestion_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    chatbot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(50), default="pending")
    source_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String(500), nullable=True)
    canonical_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    chunks_processed: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # --- Progreso y estadisticas por etapa (RAG.12) ---
    # `status` solo distingue pending/running/completed/failed, y una conversion de Docling
    # sobre un PDF largo tarda minutos: desde fuera, un job trabajando y un job colgado son
    # indistinguibles. Esto es estado CONSULTABLE, no mas log.
    progress_current: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # NULL mientras no se sabe: el total de fragmentos no existe hasta despues de trocear.
    progress_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    progress_message: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # n_chunks, total_chars, n_batches, embedding_model, stage_ms{} y —si revento—
    # failed_stage. Se escribe TAMBIEN al fallar: es cuando mas falta hace saber por donde
    # iba, y lo acumulado vive en memoria, asi que sobrevive al rollback del manejador.
    processing_stats: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    processing_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    processing_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class HubContentFinding(HubOperationalBase):
    """Hallazgo de calidad: sobre una pagina/sitio (9Q) o sobre un chatbot (RAG.14)."""

    __tablename__ = "hub_content_findings"
    __table_args__ = (
        UniqueConstraint(
            "site_id", "finding_type", "page_id", "related_page_id",
            name="uq_finding_dedup",
        ),
        # RAG.14: un hallazgo tiene UN sujeto, y ahora hay dos clases. Los de 9Q auditan
        # paginas y cuelgan de un sitio; los huecos de corpus nacen de conversaciones y
        # cuelgan de un chatbot — forzarles un sitio seria inventarle un sitio web a una
        # pregunta. Nullable NO significa opcional: sin sujeto, el hallazgo no se puede
        # revisar, y por eso el CHECK exige exactamente uno de los dos.
        CheckConstraint(
            "(site_id IS NULL) <> (chatbot_id IS NULL)",
            name="ck_finding_tiene_un_sujeto",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    site_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hub_web_sites.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    # RAG.14: sujeto alternativo al sitio, para los hallazgos que salen del uso y no de una
    # auditoria de paginas. Sin FK a hub_chatbots: es config (cloud) y esta tabla es
    # operacional (edge), y CLAUDE.md prohibe cruzar las dos bases.
    chatbot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    finding_type: Mapped[str] = mapped_column(String(40), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    page_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hub_crawled_pages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    related_page_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    signal_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="new", index=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("status", "new")
        super().__init__(**kwargs)


class HubTestScenario(HubOperationalBase):
    """Consulta guardada para probar un chatbot a mano, con lo que se espera de ella (RAG.13).

    Que exista esto y el dataset dorado de RAG.1 no es duplicidad: el dorado mide
    RECUPERACION con metricas automaticas y bloquea el build; esto mide la RESPUESTA con
    juicio humano, que es lo que ninguna metrica sustituye en un asistente normativo. Uno
    dice si el documento correcto sale entre los cinco primeros; el otro, si lo que se le
    contesta a una persona vale.

    Operacional y no de configuracion: son las pruebas del cliente sobre su propio corpus,
    asi que viven en el edge y no se sincronizan al cloud.
    """

    __tablename__ = "hub_test_scenarios"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    chatbot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    # Turnos previos en el formato 'rol: texto' que consume el grafo (RAG.10). NULL = el
    # escenario es de un solo turno, que es el caso normal.
    history: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    # Que se espera de la respuesta, en prosa. NO se comprueba automaticamente a proposito:
    # convertirlo en una asercion exigiria un criterio de igualdad entre respuestas de un
    # LLM, y ese criterio es el problema, no la solucion. Es la nota que lee quien juzga.
    expectation_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # HIB.H — lo mismo que la nota anterior dice en prosa, en forma comprobable: documento y
    # ancla del artículo, en `required` y `acceptable`. **Se añade, no sustituye**: la nota
    # sigue siendo lo que lee quien juzga y su valor —el motivo del fallo— no cabe en un
    # identificador. Misma forma que `HubInteraction.review_expected_sources`.
    expected_sources: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    runs: Mapped[list["HubTestRun"]] = relationship(
        back_populates="scenario", cascade="all, delete-orphan"
    )


class HubTestRun(HubOperationalBase):
    """Una ejecucion de un escenario y el veredicto humano que recibio (RAG.13)."""

    __tablename__ = "hub_test_runs"
    __table_args__ = (
        # Tres valores estables con consumidor en la UI: CHECK si, mismo criterio que
        # `purpose` en MOD.1 y al contrario que el vocabulario de ambitos (CLAUDE.md §5).
        # Admite NULL porque NULL es "sin juzgar todavia", no valor invalido.
        CheckConstraint(
            "verdict IS NULL OR verdict IN ('good', 'bad', 'mixed')",
            name="ck_test_run_verdict",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    scenario_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hub_test_scenarios.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    sources: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # Captura del bypass de RAG.11, solo si se pidio: el prompt final, el contexto empaquetado
    # y la configuracion resuelta EN EL MOMENTO de la ejecucion. Sin esto, un run de hace un
    # mes no se puede explicar, porque la configuracion ya no es la misma.
    bypass_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # VIS.5 — el aviso de lengua que se le dio (o no) a quien preguntó, tal cual.
    #
    # Se guarda porque **la pantalla de escenarios y el lote son las dos herramientas con las que
    # se mira si el asistente responde bien**, y el aviso no llegaba a ninguna de las dos: el
    # defecto —avisar de la lengua de la pregunta en vez de la de la norma, y callarse justo en
    # el caso más frecuente— era invisible desde ahí. Un texto que se le muestra al ciudadano y
    # que ninguna herramienta de revisión enseña es un texto que nadie revisa.
    translation_warning: Mapped[str | None] = mapped_column(Text, nullable=True)
    # RES.2 — si la respuesta salió de la segunda búsqueda y con qué consulta. Se guarda por el
    # mismo motivo que el aviso de lengua: distingue dos cosas que quien revisa necesita
    # distinguir —«el corpus no lo tiene» y «el corpus lo tiene y la pregunta no lo encontraba tal
    # como se hizo»— y sin el dato las dos se leen igual. Además es la materia prima de RES.3: el
    # par (lo que escribió la persona, la consulta que funcionó) ya viene validado por haber
    # funcionado.
    reformulada: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reformulated_query: Mapped[str | None] = mapped_column(Text, nullable=True)
    verdict: Mapped[str | None] = mapped_column(String(10), nullable=True)
    verdict_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    verdict_by: Mapped[str | None] = mapped_column(String(255), nullable=True)

    scenario: Mapped["HubTestScenario"] = relationship(back_populates="runs")


class HubLexiconPair(HubOperationalBase):
    """Par léxico: cómo lo dice una persona y cómo lo dice la norma (RES.3).

    Existe porque la recuperación falla por vocabulario, no por corpus. Medido el 2026-08-25:
    «quiero tramitar una compra de un equipo de 6.500 euros» puntúa 0,126 contra un corpus que
    llama a eso «expedients de contractes menors», y no comparten ni una palabra clave — así que
    ni el vector se parece ni la rama léxica tiene de dónde agarrarse. La misma consulta escrita
    con los términos de la norma puntúa 0,640.

    **Es OPERACIONAL, y estuvo mal puesta.** Nació en `HubConfigBase`, por analogía con
    `hub_vocabulary_terms` —que también es vocabulario revisable—, y el guardarraíl de la frontera
    edge-cloud lo rechazó con razón: `termino_de_usuario` **es literalmente lo que escribió una
    persona**. `HubConfigBase` se sincroniza cloud→edge, así que ponerla ahí obligaba a que el
    texto de las preguntas del cliente existiera en el cloud, que es exactamente lo que el modo
    edge+cloud está montado para evitar. El vocabulario institucional (ámbitos, submaterias) no
    contiene texto de nadie; esto sí.

    Consecuencia práctica: se cura **en el edge**, por quien administra ese asistente, y no viaja.
    En un despliegue con varios edge cada uno aprende de sus propios usuarios, que además es lo
    correcto: el vocabulario de los usuarios de un cliente es dato de ese cliente.

    Por eso tampoco declara `__ambito__` —ningún modelo operacional lo hace, y MT.1 recorre sólo
    `HubConfigBase`— ni lleva FK a `hub_organizaciones`: los modelos operacionales referencian por
    id sin FK, para que las dos bases sigan siendo separables. El acotado por organización lo
    garantizan el código y su test.

    **El candidato no lo inventa nadie.** Lo produce RES.2 cada vez que una reformulación rescata
    una pregunta: el par llega ya validado por el hecho de haber funcionado, y a la persona sólo
    se le pide aprobar o rechazar. Ésa es la diferencia con el intento anterior —pedir a los
    servicios que redactaran lotes de preguntas y respuestas en hojas Excel—, que fracasó porque
    pedía inventar en frío.

    **Se proyecta sobre `bilingual_terms`, que alimenta el `tsvector` como columna generada.** O
    sea: aplicar un par aprobado es un `UPDATE` y el índice se regenera solo, sin recalcular
    ningún embedding. Y la proyección es **derivada**: se puede reconstruir entera desde esta
    tabla, así que quitar un término cuesta lo mismo que ponerlo. Sin esa propiedad, en seis meses
    nadie sabe de dónde salió un término y «reclasificar» vuelve a ser «reindexar».

    Misma forma revisable que `HubVocabularyTerm` (`vigent`, `substituit_per_codi`) y por lo
    mismo: renombrar y fusionar sin migración. Y sin `Enum` ni `CheckConstraint` sobre los
    términos, que son dato y están para revisarse.
    """

    __tablename__ = "hub_lexicon_pairs"

    __table_args__ = (
        UniqueConstraint(
            "organizacion_id",
            "document_id",
            "termino_de_usuario",
            name="uq_lexicon_org_doc_termino",
        ),
        # Estados con consumidor en el código y valores estables: aquí sí va CheckConstraint.
        # Lo que no puede llevarlo son los términos.
        CheckConstraint(
            "estado IN ('propuesto', 'aprobado', 'rechazado')",
            name="ck_lexicon_estado",
        ),
        CheckConstraint(
            "origen IN ('reformulacion', 'manual')", name="ck_lexicon_origen"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    #: Sin FK, como el resto de los modelos operacionales: las dos bases tienen que poder vivir
    #: separadas. El acotado lo hace el código, y hay un test que lo comprueba.
    organizacion_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    #: El documento que respondió. El par se ancla a él y no a la consulta, porque la proyección
    #: escribe sobre los trozos de ESE documento: así se sabe siempre qué quitar al rechazarlo.
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    #: Lo que escribió la persona. Texto libre a propósito: es lenguaje real, no un código.
    termino_de_usuario: Mapped[str] = mapped_column(Text, nullable=False)
    #: La consulta que sí encontró el documento.
    termino_normativo: Mapped[str] = mapped_column(Text, nullable=False)
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="propuesto")
    origen: Mapped[str] = mapped_column(String(20), nullable=False, default="reformulacion")
    vigent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    substituit_per_codi: Mapped[str | None] = mapped_column(String(80), nullable=True)
    revisado_por: Mapped[str | None] = mapped_column(String(255), nullable=True)
    revisado_el: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class HubActividadIA(HubOperationalBase):
    """Un uso de IA ocurrido **fuera** de la plataforma, declarado por la herramienta que lo hizo.

    **Es registro de gobernanza**: sirve a la conservación de registros del AI Act y al registro
    de actividades de tratamiento del RGPD. Contesta «qué IA se usó aquí, quién, para qué y sobre
    qué categorías de datos» cuando el uso ocurrió en un asistente de escritorio, un agente de
    código o una integración propia, y no en esta plataforma.

    **No se confunde con `hub_interactions`, y por eso es una tabla nueva.** Aquélla registra las
    conversaciones **internas** y tiene otra forma —mensajes, valoraciones, veredictos— porque
    sirve a otra cosa: medir y mejorar los asistentes propios. Sobrecargarla con eventos externos
    obligaría a que la mitad de sus columnas fueran nulas en la mitad de sus filas, y a que
    cualquier consulta tuviera que acordarse de distinguir las dos poblaciones.

    **Metadatos sí, payloads no.** No hay ninguna columna de contenido. Si un caso exige poder
    cotejar lo que se procesó, va `payload_hash`. Un registro que existe para dar cuenta del
    tratamiento de datos personales no puede ser, además, un segundo sitio donde vivan.

    Sin FK a `hub_organizaciones` y sin `__ambito__`, como el resto de los modelos operacionales:
    las dos bases declarativas tienen que poder vivir separadas cuando el despliegue parte cloud y
    edge. El acotado por organización lo hacen el código y su test.
    """

    __tablename__ = "hub_actividad_ia"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    #: Sin FK, como el resto de los modelos operacionales.
    organizacion_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )

    #: Cuándo ocurrió el uso, **según quien lo declara**. Indexado porque la lectura del registro
    #: filtra por rango de fechas.
    ocurrido_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    #: Cuándo lo recibimos nosotros. Lo pone la **base de datos**, no el proceso que inserta: es
    #: la única marca de tiempo del registro que no la elige quien registra, y es la que vale
    #: cuando hay que demostrar cuándo se supo algo.
    registrado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    #: Identificador opaco de la persona en la herramienta externa: para dar cuenta de un
    #: tratamiento basta poder correlacionar, no identificar desde el registro.
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    #: Indexada porque es el filtro principal de la lectura: «qué se hizo con esta herramienta».
    herramienta: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    agente: Mapped[str | None] = mapped_column(String(255), nullable=True)
    #: El único texto libre, y el que da sentido al registro: sin finalidad, saber que alguien usó
    #: una IA no informa de nada.
    finalidad: Mapped[str] = mapped_column(String(500), nullable=False)
    modelo_usado: Mapped[str | None] = mapped_column(String(100), nullable=True)

    #: JSONB y **sin `CheckConstraint`**: las categorías son vocabulario revisable, no estructura.
    #: Misma regla que el vocabulario del corpus, y por lo mismo — una categoría nueva no puede
    #: costar una migración.
    categorias_datos: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    #: SHA-256 del contenido procesado, si el caso lo exige. Nunca el contenido.
    payload_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: AUT.5 — SHA-256 del **programa** que se ejecutó, si está en el catálogo como función de
    #: origen externo. Es `HubFuncionVersion.code_sha256`, y es lo que permite cruzar «qué
    #: cuadernos existen» con «cuándo corrieron». Indexado porque ése es justamente el cruce.
    funcion_sha256: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )


class HubAgenteUnidad(HubOperationalBase):
    """Un agente que publica una unidad de la organización (#172).

    Un agente es un prompt, una carpeta de documentos, un índice y un colectivo, **y ninguna de
    las cuatro es código**. Lo ejecuta el asistente general de la organización; la plataforma lo
    cataloga, lo acota y registra su uso.

    **En el lado operacional, como el catálogo de funciones**: el prompt y la declaración son
    texto escrito por una persona de la organización, el criterio que mandó aquí a
    `hub_funcion_versiones` y a `hub_lexicon_pairs`. Sin FK a `hub_organizaciones`, como el resto.

    **La unidad es texto declarado**, no una tabla (decisión del usuario, 2026-10-02): la
    plataforma no tiene unidades, y crearlas para esto sería una pantalla más que mantener sin
    que nada la consuma. Publica quien tenga el módulo `agentes`.
    """

    __tablename__ = "hub_agentes_unidad"
    __ambito__ = Ambito.ORGANIZACION
    __table_args__ = (
        CheckConstraint("modo_registro IN ('validacion', 'incidencias')", name="ck_agente_unidad_modo_registro"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organizacion_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    unidad: Mapped[str] = mapped_column(String(200), nullable=False)
    #: Quien lo publicó. Es quien lo versiona y lo retira, y quien **no** puede revisarlo.
    creado_por: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    #: #174 — cuándo llegó el índice por última vez, **también si no traía cambios**: un guion que
    #: corre y no encuentra nada nuevo está vivo, y uno que no corre está parado.
    indice_actualizado_en: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: `guion` (por API, lo normal) u `hoja` (subida a mano). Sólo el guion promete ir a diario,
    #: así que sólo él puede quedarse parado.
    indice_origen: Mapped[str | None] = mapped_column(String(10), nullable=True)
    #: Cuántos documentos encontró el guion en la carpeta, para contarlos contra las fichas.
    documentos_en_carpeta: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: #216 — qué se guarda de sus conversaciones: `validacion` (todo: pregunta y respuesta) o
    #: `incidencias` (sólo lo que quien lo usa informa como inadecuado). Empieza en validación:
    #: primero se comprueba que funciona (decisión del usuario, 2026-10-03). Es del agente y no de
    #: la versión: cambiarlo no cambia lo que se ofrece.
    modo_registro: Mapped[str] = mapped_column(
        String(12), nullable=False, default="validacion", server_default="validacion"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class HubAgenteUnidadVersion(HubOperationalBase):
    """Una versión de un agente: su prompt y su declaración. **La que se ofrece es la última.**

    Corregir es versionar: una versión registrada no se edita, como en FUN, porque lo que se
    revisó tiene que seguir siendo lo que se revisó. Revisar y suspender actúan sobre la última.

    **El colectivo no es un nivel de acceso.** `nivell_acces` dice cuánto se protege un
    documento; esto dice **quién** usa el agente. Grano grueso: toda la organización, o una
    lista de grupos del IdP —que sólo llegan por SAML; con Google no hay ninguno—.
    """

    __tablename__ = "hub_agente_unidad_versiones"
    __ambito__ = declarar(Ambito.DERIVADA, via="agente_id")
    __table_args__ = (
        UniqueConstraint("agente_id", "version", name="uq_agente_unidad_version"),
        # Estructura, no vocabulario: cada valor tiene código que lo aplica (CLAUDE.md §5).
        CheckConstraint(
            "estado IN ('registrada', 'suspendida', 'retirada')",
            name="ck_agente_unidad_version_estado",
        ),
        CheckConstraint(
            "colectivo IN ('organizacion', 'grupos')",
            name="ck_agente_unidad_version_colectivo",
        ),
        CheckConstraint(
            "autoria_prompt IN ('persona', 'ia')",
            name="ck_agente_unidad_version_autoria_prompt",
        ),
        CheckConstraint(
            "adjunto IN ('no', 'opcional', 'obligatorio')",
            name="ck_agente_unidad_version_adjunto",
        ),
        CheckConstraint(
            "lengua_respuesta IN ('pregunta', 'es', 'ca')",
            name="ck_agente_unidad_version_lengua_respuesta",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    agente_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hub_agentes_unidad.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    estado: Mapped[str] = mapped_column(String(20), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    #: Dónde están los documentos. **La plataforma no guarda ni uno**: los autoriza el almacén.
    carpeta_url: Mapped[str] = mapped_column(String(2048), nullable=False)

    # ── La declaración: sin ella no se publica ─────────────────────────────────────
    finalidad: Mapped[str] = mapped_column(Text, nullable=False)
    responsable: Mapped[str] = mapped_column(String(255), nullable=False)
    colectivo: Mapped[str] = mapped_column(String(20), nullable=False)
    grupos: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    #: Cuándo dice la unidad que lo volverá a mirar. **Vencida avisa, no oculta.**
    revision_prevista_en: Mapped[date] = mapped_column(Date, nullable=False)
    #: #173 — cuántos documentos puede devolver una consulta como mucho. Lo declara el agente
    #: (decisión del usuario): uno de pocos documentos largos puede quedarse corto a propósito.
    presupuesto_documentos: Mapped[int] = mapped_column(
        Integer, nullable=False, default=5, server_default="5"
    )
    #: #175, #218 — si quien consulta adjunta un documento propio en el asistente general: `no`,
    #: `opcional` (lo dice quien pregunta, en cada consulta) u `obligatorio` (un agente de
    #: revisión). Cambia el prompt —los enlaces son el criterio y el adjunto el objeto— y la
    #: plataforma no ve el adjunto nunca. Lo declara la unidad, que sabe para qué es su agente.
    adjunto: Mapped[str] = mapped_column(String(12), nullable=False, default="no", server_default="no")
    #: #218 — en qué lengua se responde: `pregunta` (la de la pregunta), `es` o `ca` (siempre en
    #: castellano o en valenciano: pliegos, resoluciones). **Es una declaración y no texto del
    #: prompt**: la instrucción la añade la plataforma al componer, como la abstención.
    lengua_respuesta: Mapped[str] = mapped_column(
        String(10), nullable=False, default="pregunta", server_default="pregunta"
    )
    #: #213 — si el prompt se redactó con ayuda de IA (el asistente de propuestas), como
    #: `autoria` en el catálogo de funciones. **Lo declara quien publica**: la plataforma propone,
    #: pero no puede saber cuánto se editó después.
    autoria_prompt: Mapped[str] = mapped_column(
        String(10), nullable=False, default="persona", server_default="persona"
    )
    declarada_por: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    declarada_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # ── La revisión posterior ─────────────────────────────────────────────────────
    revisada_por: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    revisada_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revision_resultado: Mapped[str | None] = mapped_column(String(20), nullable=True)
    revision_nota: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── La suspensión: con motivo, que se conserva al reactivar ──────────────────
    suspendida_por: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    suspendida_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    motivo_suspension: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class HubAgenteFicha(HubOperationalBase):
    """Una ficha del índice de un agente: **un documento, no un fragmento** (#173).

    El asistente general lee el documento entero —medido el 2026-09-27: un PDF de 750 páginas,
    capítulo a partir de la 450—, así que el índice apunta a documentos. Sin troceado, sin
    anclas, sin contrato de formato: tres órdenes de magnitud menos que el corpus normativo.

    **La plataforma no guarda el documento**: guarda la ficha y la URL. El documento lo autoriza
    el almacén de la organización, que es la segunda puerta.

    **El vector es del título y el resumen, y de nada más** (regla 5 de AGENTS.md): los
    metadatos y la vigencia cambian, y cambiarlos no puede obligar a re-embeber. Por eso hay dos
    huellas: `huella` dice si la ficha cambió y `huella_embebida` si cambió lo que se embebe.
    """

    __tablename__ = "hub_agente_fichas"
    __ambito__ = declarar(Ambito.DERIVADA, via="agente_id")
    __table_args__ = (UniqueConstraint("agente_id", "url", name="uq_agente_ficha_url"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    agente_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hub_agentes_unidad.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    titulo: Mapped[str] = mapped_column(String(500), nullable=False)
    resumen: Mapped[str] = mapped_column(Text, nullable=False)
    #: Declarada por la unidad. **Lo no vigente no se selecciona**, y el filtro va en el `WHERE`.
    vigente: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    #: Vencida avisa, no oculta: el mismo criterio que la del agente.
    revision_prevista_en: Mapped[date | None] = mapped_column(Date, nullable=True)
    metadatos: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    #: Con qué se hizo el resumen (#174): sin esto, un resumen malo no se puede rastrear.
    version_prompt_resumen: Mapped[str | None] = mapped_column(String(100), nullable=True)
    modelo_resumen: Mapped[str | None] = mapped_column(String(100), nullable=True)

    huella: Mapped[str] = mapped_column(String(64), nullable=False)
    huella_embebida: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(1024), nullable=False)
    #: De dónde salió el vector: comparar vectores de dos modelos da un orden sin sentido y no
    #: da error, así que la selección lo comprueba.
    embedding_model: Mapped[str] = mapped_column(String(100), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class HubAgenteConsulta(HubOperationalBase):
    """Una consulta a un agente de unidad (#175) y, según el modo del agente, su conversación (#216).

    El registro de actividad dice quién usó qué agente, cuándo y para qué; esto añade **qué
    documentos se ofrecieron y con qué puntuación**, que su contrato no tiene dónde poner.

    **#216 — la conversación**, como las de los chatbots (`hub_interactions`): son conversaciones de
    trabajo sobre documentos de la organización, quien las tiene sabe que se registran, y prevalece
    la calidad de las respuestas (decisión del usuario, 2026-10-03). En `validacion` se guarda la
    pregunta al consultar y la respuesta que la extensión leyó en el asistente; en `incidencias`,
    sólo lo que quien lo usa informa como inadecuado. `modo` es el del agente **cuando se
    consultó**: dice por qué hay, o no hay, contenido.

    Lo que sigue sin poder saberse: la respuesta es la que leyó la extensión en la página del
    asistente. Si la persona la editó, la regeneró o siguió conversando, eso no llega.
    """

    __tablename__ = "hub_agente_consultas"
    __ambito__ = declarar(Ambito.DERIVADA, via="agente_id")
    __table_args__ = (
        CheckConstraint("modo IN ('validacion', 'incidencias')", name="ck_agente_consulta_modo"),
        CheckConstraint("puntuacion IS NULL OR puntuacion IN (-1, 1)", name="ck_agente_consulta_puntuacion"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    agente_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hub_agentes_unidad.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    #: El mismo identificador opaco que lleva el registro de actividad.
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    ocurrido_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    #: `[{url, score}]`, en el orden en que se ofrecieron.
    documentos: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    #: La fila del registro de actividad que corresponde a esta consulta.
    actividad_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    #: #216 — el modo del agente al consultar. Las anteriores no guardaron nada: `incidencias`.
    modo: Mapped[str] = mapped_column(String(12), nullable=False, server_default="incidencias")
    pregunta: Mapped[str | None] = mapped_column(Text, nullable=True)
    respuesta: Mapped[str | None] = mapped_column(Text, nullable=True)
    respuesta_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Por qué la extensión no pudo leer la respuesta: cuenta la cobertura de la captura.
    respuesta_no_capturada: Mapped[str | None] = mapped_column(String(20), nullable=True)
    #: Las fuentes que citó el asistente, si las mostró.
    fuentes: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    #: 1 o -1, como `feedback_score` de los chatbots. -1 con su motivo es un informe.
    puntuacion: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Un código de `modules/agentes/registro.MOTIVOS`. Sin restricción en la base: es un
    #: vocabulario que puede crecer, como `fallback_reason` de las conversaciones.
    motivo: Mapped[str | None] = mapped_column(String(40), nullable=True)
    comentario: Mapped[str | None] = mapped_column(Text, nullable=True)
    valorada_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class HubAsistenteAdaptador(HubOperationalBase):
    """Cómo encuentra la extensión del navegador las piezas de la página de un asistente (#215).

    **Los selectores son datos y no código**: el asistente —Gemini— cambia su página sin avisar, y
    con los selectores dentro de la extensión cada cambio exigiría publicarla de nuevo y esperar a
    que llegara a todos los navegadores. Aquí se corrige la fila y cada cambio es una `version`.

    La extensión avisa de **qué selector** dejó de casar; se cuentan los fallos de la versión
    vigente, de modo que uno que llega tarde de una versión ya corregida no la marca como rota.

    De la instalación entera, sin organización: la página de Gemini es la misma para todas. En el
    lado operacional, junto a los agentes que la usan y donde la extensión avisa.
    """

    __tablename__ = "hub_asistente_adaptadores"

    asistente: Mapped[str] = mapped_column(String(40), primary_key=True)
    nombre: Mapped[str] = mapped_column(String(80), nullable=False)
    #: El origen donde actúa la extensión, p. ej. `https://gemini.google.com`.
    origen: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    #: `{cuadro, respuesta, texto, ocupado, fuentes}`: lo que lee `extension/asistente.js`.
    selectores: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False)
    actualizado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    actualizado_por: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fallos_de_la_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    ultimo_fallo_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ultimo_fallo_selector: Mapped[str | None] = mapped_column(String(40), nullable=True)
