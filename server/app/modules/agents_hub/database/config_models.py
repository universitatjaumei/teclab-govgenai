"""Modelos ORM de configuración para agents_hub."""

import uuid
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import false as sa_false
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from server.app.core.ambito import Ambito, declarar
from server.app.modules.agents_hub.database.base import HubConfigBase


class HubProvider(HubConfigBase):
    """Proveedor dinámico de LLMs (Google, OpenRouter, LMStudio, etc.)."""

    __tablename__ = "hub_providers"

    # MT.2 — **sigue siendo de plataforma, y es una decisión**: al mirar las cuatro filas
    # reales resulta que esta tabla es un catálogo de **tipos** (Google, Vertex, Ollama,
    # OpenRouter) y ninguna tiene `api_key`. Google es Google en todos los municipios. Lo que
    # se separa por organización es la credencial, y vive en `HubProviderCredential`.
    #
    # `api_key` y `base_url` se quedan aquí como el nivel de plataforma de siempre: quitarlas
    # rompería la cadena que el piloto usa hoy, y MT.2 no cambia comportamiento.
    __ambito__ = Ambito.PLATAFORMA

    id: Mapped[str] = mapped_column(String(50), primary_key=True)  # e.g. google, openrouter, lmstudio
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(50), nullable=False)  # openai_compatible, google_genai, etc
    base_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    api_key: Mapped[str | None] = mapped_column(String(255), nullable=True)

    llm_configs: Mapped[list["HubLLMConfig"]] = relationship(back_populates="provider_rel")


class HubLLMConfig(HubConfigBase):
    """Configuración de un modelo reutilizable: chat, embeddings o reranking.

    `purpose` lo añade MOD.1 (ver `docs/DECISION_MODELOS_EMBEDDING_RERANKER.md`). Hasta
    entonces esta tabla era implícitamente de chat —lo delatan `temperature`, `top_p` y
    `max_tokens`—, y los modelos de embedding se elegían con un `import`, no con
    configuración. Con el propósito explícito se reutiliza todo lo que ya existe:
    proveedores con su `base_url` y su clave, `available-models` y el test de conexión.

    **Lleva CheckConstraint, al contrario que el vocabulario de ámbitos** (CLAUDE.md §5): son
    tres valores estables, cada uno con consumidor en el código, y añadir uno exige escribir
    el código que lo consuma. Mismo criterio que `nivell_acces` en ING.0.2.
    """

    __tablename__ = "hub_llm_configs"

    # MT.2 — heredable: nulo = plataforma, y se hereda. Los siete modelos de hoy quedan a
    # nulo, que es la condición para que el piloto no note la migración.
    __ambito__ = Ambito.HEREDABLE
    __table_args__ = (
        CheckConstraint(
            "purpose IN ('chat', 'embedding', 'rerank')",
            name="ck_llm_config_purpose",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # MT.2 — de quién es este modelo. Nulo = de la plataforma, y lo heredan todas.
    organizacion_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hub_organizaciones.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    provider: Mapped[str] = mapped_column(
        String(50), ForeignKey("hub_providers.id"), nullable=False
    )
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    temperature: Mapped[float] = mapped_column(default=0.1)
    top_p: Mapped[float] = mapped_column(default=1.0)
    max_tokens: Mapped[int] = mapped_column(Integer, default=12000)
    api_key_secret_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tier: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    label: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # --- MOD.1: para qué sirve este modelo ---
    purpose: Mapped[str] = mapped_column(String(20), nullable=False, default="chat")
    # Dimensión pedida al proveedor. None = la que dé por defecto. La plataforma trabaja a
    # 1024 porque es el único valor que sirve a la vez a BGE-M3 en edge (nativo) y a Google
    # en cloud (rango flexible 128-3072): mantenerlo salva la columna Vector(1024), el índice
    # HNSW y el corpus ya cargado cuando se cambia de proveedor.
    output_dimensionality: Mapped[int | None] = mapped_column(Integer, nullable=True)

    chatbots: Mapped[list["HubChatbot"]] = relationship(back_populates="llm_config")
    provider_rel: Mapped["HubProvider"] = relationship(back_populates="llm_configs")


class MetodoDeCredencial(StrEnum):
    """Cómo se obtiene la credencial de un proveedor (MT.2, restringido en SEC.9.4).

    **Lleva `CheckConstraint`, al contrario que el vocabulario del corpus** (CLAUDE.md §5): son
    valores estables, cada uno con su rama en `model_factory`, y añadir uno exige escribir la
    rama que lo consuma — así que el CHECK no estorba a nadie. Mismo criterio que `purpose` en
    esta misma tabla y `nivell_acces` en ING.0.2.

    **SEC.9.4 retiró `clave`**, que guardaba la clave literal en la base de datos. Ninguno de los
    dos que quedan guarda un secreto: uno guarda **el nombre** de la variable donde está, y el
    otro no guarda nada. Así, un volcado, una copia o el payload de la sincronización cloud→edge
    dejan de ser sensibles por construcción, en vez de por acordarse de cifrarlos.

    El coste es el autoservicio del panel —dar de alta una credencial deja de ser un formulario—,
    y su recuperación está anotada en **MT.10** con un `SecretProvider` que guarda el nombre del
    recurso y no el valor. Descartado a propósito: cifrar en reposo, que mueve el secreto al
    entorno del mismo proceso que lo descifra y añade gestión de clave para siempre.
    """

    #: La base guarda **el nombre** de la variable de entorno; el secreto vive fuera.
    VARIABLE_DE_ENTORNO = "variable_de_entorno"
    #: Sin clave: las credenciales del entorno de ejecución (ADC de Vertex).
    ENTORNO_DE_EJECUCION = "entorno_de_ejecucion"


class HubProviderCredential(HubConfigBase):
    """Con qué credencial habla una organización con un proveedor (MT.2).

    Deploy: cloud — es configuración y se sincroniza cloud→edge. Los módulos edge no la
    importan: la leen por `resolver_credencial`.

    Nace de que `hub_providers` tenía una sola `api_key` para toda la instalación. En el modelo
    Diputación→municipios eso significa que el consumo de un ayuntamiento se factura al contrato
    de otro y que sus prompts viajan por ese contrato: coste mal atribuido y protección de datos,
    no incomodidad.

    **Es tabla aparte y no una columna en `hub_providers`, y es una decisión.** Aquella tabla es
    un catálogo de *tipos* con clave primaria de texto (`google`, `vertex`): añadirle
    `organizacion_id` no permitiría dos Googles, y permitirlo exigía cambiar su clave primaria
    con una clave ajena por medio y romper `/providers/{provider_id}`. Lo que tiene que separarse
    es la credencial.

    **`variable_de_entorno` es el método que sirve al despliegue en GCP**: la base guarda el
    nombre (`GOOGLE_API_KEY_ONDA`) y Secret Manager monta el valor. Es la única forma de tener
    credenciales por organización sin meter secretos en la base de datos.
    """

    __tablename__ = "hub_provider_credentials"

    # MT.1/MT.2 — nulo = la credencial de plataforma, y la heredan las organizaciones que no
    # tengan la suya. Es lo que hace que el piloto no note nada: hoy no hay ninguna fila.
    __ambito__ = Ambito.HEREDABLE
    __table_args__ = (
        # SEC.9.4 — sin `clave`: es el CHECK el que impide que el método vuelva por un INSERT a
        # mano cuando ya no hay ni columna donde poner el secreto.
        CheckConstraint(
            "metodo IN ('variable_de_entorno', 'entorno_de_ejecucion')",
            name="ck_provider_credential_metodo",
        ),
        # `NULLS NOT DISTINCT` (Postgres 15+) es lo que hace valer la unicidad **también en el
        # nivel de plataforma**: sin ella, `NULL != NULL` dejaría meter dos filas de plataforma
        # para el mismo proveedor sin protestar — y ése es el caso más probable, porque hoy es
        # el único nivel que existe. Dos filas serían dos respuestas a una pregunta con una
        # sola, y cuál gana lo decidiría el `ORDER BY`.
        UniqueConstraint(
            "provider_id",
            "organizacion_id",
            name="uq_provider_credential_scope",
            postgresql_nulls_not_distinct=True,
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    provider_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("hub_providers.id", ondelete="CASCADE"), nullable=False
    )
    organizacion_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hub_organizaciones.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    metodo: Mapped[str] = mapped_column(String(30), nullable=False)
    # SEC.9.4 — aquí había un `api_key` en texto plano, para `metodo='clave'`. No hay columna
    # que lo sustituya **a propósito**: lo que se guarda es dónde está el secreto, no el secreto.
    #: Sólo con `metodo='variable_de_entorno'`: **el nombre**, nunca el valor.
    secret_env: Mapped[str | None] = mapped_column(String(255), nullable=True)
    #: Cambia la del catálogo. Un municipio con su propio Ollama en su propia red.
    base_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class HubOrganizacion(HubConfigBase):
    """Institución (organización) gestionada por un admin."""

    __tablename__ = "hub_organizaciones"

    # MT.1 — el catálogo de organizaciones es de la plataforma: es el eje sobre el que se
    # acota todo lo demás, no algo acotable.
    __ambito__ = Ambito.PLATAFORMA

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    partner_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # AIS.5 — la política de anonimización de los informes de esta organización.
    #
    # Vive aquí y no en el informe porque el usuario lo dijo así: el modo «depende del contrato
    # con el proveedor LLM y del tipo de datos», y ninguna de las dos cosas es una decisión por
    # informe. Quien crea uno no tiene por qué saber qué permite el contrato de su casa.
    #
    # **Nulo = la organización no lo ha fijado**, y entonces manda el valor del código
    # (`politica.MODO_POR_DEFECTO`, hoy `replace`). Es la misma semántica de `core/ambito.py`
    # para el resto de la configuración heredable, y es lo que hace que el piloto no note nada.
    # Un informe puede **endurecerlo, nunca relajarlo**.
    anonymization_mode: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # --- Defaults del grafo público (cascada hacia chatbots) ---
    default_public_graph_profile: Mapped[str] = mapped_column(String(50), nullable=False, default="PUBLIC_KB_RICH")
    default_retrieval_mode: Mapped[str] = mapped_column(String(30), nullable=False, default="RAG")
    default_language_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="prefer")
    default_quality_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.65)
    default_min_retrieval_results: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    default_min_retrieval_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    default_reranker_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    default_answer_template: Mapped[str] = mapped_column(String(50), nullable=False, default="generic")
    # Nullable a propósito, al revés que sus hermanas: NULL significa «heredar el default
    # de plataforma» (VIS.2). Con un valor no nulo por defecto, subir el presupuesto en la
    # plataforma no llegaría nunca a las organizaciones ya creadas.
    default_context_token_budget: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # --- Troceado (RAG.8). Nullable = heredar del default de plataforma ---
    default_chunk_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    default_chunk_overlap: Mapped[int | None] = mapped_column(Integer, nullable=True)
    default_chunking_strategy: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # PLG.2 — estrategias por defecto de la organización, `{eje: nombre}`. Se fusiona CLAVE A
    # CLAVE con lo que ponga el chatbot: una organización que fija `merge` no pisa el `template`
    # que el chatbot haya elegido. NULL = hereda entera la composición del perfil.
    default_estrategias: Mapped[dict[str, str] | None] = mapped_column(JSONB, nullable=True)
    # --- Reescritura de consulta (RAG.10). NULL = heredar del default de plataforma ---
    # Nullable y no `default=False` como sus hermanas booleanas mas antiguas: con un False
    # no nulo, la organizacion pisaria siempre a la plataforma y encenderlo por organizacion
    # no serviria de nada. Es el mismo motivo por el que context_token_budget es nullable.
    default_query_rewriting_enabled: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True
    )
    # HIB.S — la comprobacion de fundamento de la cita. NULL = heredar de la plataforma, que
    # entra APAGADA: una puerta que puede descartar respuestas no se enciende por existir.
    # Nullable por el mismo motivo que la de arriba, y ademas porque el criterio de cierre del
    # prompt exige medir la latencia del primer token con y sin ella — sin interruptor, esa
    # medicion no se puede hacer.
    default_grounding_check_enabled: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True
    )
    # HIB.T — el artículo o la norma entera. NULL = heredar de la plataforma, que entra en
    # False: los tres asistentes en producción inyectan el artículo.
    default_inject_whole_document: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True
    )
    # Modelo con el que se reescribe: pequeno y rapido, distinto del que responde. Vive en
    # la organizacion porque repetirlo en cada chatbot solo multiplicaria sitios donde
    # olvidarlo. NULL = usar el del chatbot con el tope de salida bajado.
    # `use_alter=True` (BD.2): esta FK y `HubLLMConfig.organizacion_id` forman un ciclo
    # —cada tabla apunta a la otra—, y SQLAlchemy avisaba de que no podía ordenar su creación
    # («may raise an error in a future release»). Con `use_alter`, la FK se añade con un
    # `ALTER TABLE` después de crear las dos tablas. Es la anulable de las dos, así que es la que
    # puede esperar. No cambia el esquema resultante: `alembic check` no lo ve como diferencia.
    rewrite_llm_config_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hub_llm_configs.id", ondelete="SET NULL", use_alter=True),
        nullable=True,
    )
    # --- Cuotas de consumo (SEC.4). Todo en TOKENS ---
    #
    # `NULL` = heredar del nivel de arriba; `0` = **sin límite**. Son dos cosas distintas y
    # confundirlas es el fallo caro: si `0` significara «bloqueado», poner un límite a cero
    # para «quitar la restricción» dejaría al chatbot sin poder responder a nadie. Hay test.
    #
    # Los contadores NO viven aquí: son `HubUsageCounter`, operacionales. Aquí solo está el
    # límite, que es configuración y sí se sincroniza al edge.
    default_user_daily_token_quota: Mapped[int | None] = mapped_column(Integer, nullable=True)
    default_user_monthly_token_quota: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # De la organización entera, no de cada usuario: es el techo de gasto del contrato.
    monthly_token_quota: Mapped[int | None] = mapped_column(Integer, nullable=True)
    default_chatbot_daily_token_quota: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    chatbots: Mapped[list["HubChatbot"]] = relationship(
        back_populates="organizacion", cascade="all, delete-orphan"
    )


class HubVocabularyTerm(HubConfigBase):
    """Término del vocabulario controlado del corpus (ING.0.1).

    Deploy: cloud — es configuración institucional y se sincroniza cloud→edge.
    Los módulos edge NO importan este modelo: leen vía `ConfigProvider.list_vocabulary`.

    **No lleva CheckConstraint sobre `codi` ni sobre `axis`, y es deliberado**: el
    vocabulario de ámbitos y submaterias está pendiente de validación por Secretaría
    General y tiene que poder cambiar sin migración. Un CHECK sería exactamente lo que
    lo impide (CLAUDE.md §5).

    Renombrar o fusionar un término = fila nueva + la vieja con `vigent=False` y
    `substituit_per_codi` apuntando a la nueva. **La cadena de sustituciones ES la
    traza de auditoría**: no hay tabla de historial aparte.
    """

    __tablename__ = "hub_vocabulary_terms"

    # MT.1 — `organizacion_id` NOT NULL desde ING.0.1: cada organización tiene el suyo y no
    # hay vocabulario de plataforma que heredar.
    __ambito__ = Ambito.ORGANIZACION
    __table_args__ = (
        UniqueConstraint(
            "organizacion_id", "axis", "codi", name="uq_vocabulary_org_axis_codi"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organizacion_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hub_organizaciones.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    axis: Mapped[str] = mapped_column(String(20), nullable=False)
    codi: Mapped[str] = mapped_column(String(80), nullable=False)
    nom_primari: Mapped[str] = mapped_column(String(255), nullable=False)
    nom_secundari: Mapped[str | None] = mapped_column(String(255), nullable=True)
    parent_codi: Mapped[str | None] = mapped_column(String(80), nullable=True)
    descripcio_router: Mapped[str | None] = mapped_column(Text, nullable=True)
    ordre: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    vigent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    substituit_per_codi: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class HubChatbot(HubConfigBase):
    """Chatbot RAG asociado a una organización."""

    __tablename__ = "hub_chatbots"

    # MT.1 — un asistente es siempre de una organización.
    __ambito__ = Ambito.ORGANIZACION
    __table_args__ = (
        # PLG.2 — **el CHECK de `retrieval_mode` se retira**, y no es un descuido del criterio de
        # los de abajo sino su aplicación. La regla del proyecto dice que el vocabulario va en
        # dato y la estructura en CHECK, y la prueba de cuál es cuál es ésta: *¿puede llegar un
        # valor nuevo sin escribir código que lo consuma?*
        #
        # Hasta PLG.1 la respuesta era no, y el CHECK era correcto: los tres modos eran una
        # cadena de `if` en la factoría. Desde PLG.1 un pipeline llega **instalando un paquete**,
        # así que el CHECK convertía la funcionalidad entera en imposible: el modo se validaba
        # contra el registro vivo en el router, pasaba, y luego Postgres lo rechazaba al guardar.
        #
        # Lo que sigue validando: `validar_modo()` contra `list_modes()`, que es el registro vivo
        # y sabe lo que el CHECK no puede saber — qué hay instalado.
        #
        # Los tres CHECK que quedan abajo SÍ son estructura, y por eso se quedan: `kind`,
        # `chunking_strategy` y `access_mode` tienen cada uno código que los aplica, y añadir un
        # valor exige escribirlo.
        CheckConstraint(
            "kind IN ('atomic', 'router')",
            name="ck_chatbot_kind",
        ),
        # RAG.8. Admite NULL porque NULL significa «heredar», no «valor inválido»; son dos
        # estrategias estables con consumidor en el chunker, así que CHECK sí (mismo criterio
        # que `nivell_acces` en ING.0.2 y al contrario que el vocabulario de ámbitos).
        CheckConstraint(
            "chunking_strategy IS NULL OR chunking_strategy IN ('structural', 'parent_child')",
            name="ck_chatbot_chunking_strategy",
        ),
        # SEC.2.1. Tres modos, estables y con consumidor en `assert_chatbot_access`: esto
        # es estructura, no vocabulario. Añadir un cuarto exige escribir el código que lo
        # aplique, así que el CHECK no estorba a nadie (criterio de CLAUDE.md §5).
        CheckConstraint(
            "access_mode IN ('public_anon', 'authenticated', 'restricted')",
            name="ck_chatbot_access_mode",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organizacion_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hub_organizaciones.id", ondelete="CASCADE"),
        nullable=False,
    )
    llm_config_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hub_llm_configs.id"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    sources: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    theme_config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    retrieval_mode: Mapped[str] = mapped_column(String(30), nullable=False, default="RAG")
    # HIB.Q — tres, no ocho, y el defecto está AQUÍ y no sólo en la plataforma: `_apply_layer`
    # aplica los valores no nulos de cada capa, así que una columna NOT NULL del chatbot gana
    # siempre al defecto de plataforma. Cambiar sólo `_PLATFORM_DEFAULTS` no habría movido
    # nada para ningún chatbot.
    #
    # Por qué tres: hasta HIB.J este mando daba menos documentos de los que decía —el pool se
    # encogía a `top_k` fragmentos y luego se agrupaba por documento—, y ahora significa ocho
    # documentos **enteros**; con `parent_child` eso es casi el triple del contexto y del coste
    # que se eligió midiendo para Normativa. Sin `server_default` a propósito: un defecto de
    # columna sólo actúa al insertar, así que los chatbots que ya existen no se tocan.
    retrieval_top_k: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    # HIB.J — fragmentos que se le piden al híbrido, frente a `retrieval_top_k`, que son los
    # documentos que llegan al modelo. **Nullable a propósito**: NULL significa «derívalo de
    # `retrieval_top_k`», que es lo que hace `pool_size()`, y no «cero candidatos». Un
    # defecto numérico aquí congelaría el valor de todos los chatbots existentes en el que
    # tuviera el día de la migración.
    candidate_k: Mapped[int | None] = mapped_column(Integer, nullable=True)
    use_prompt_caching: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cache_ttl: Mapped[int] = mapped_column(Integer, nullable=False, default=3600)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="atomic")
    # --- Autorización por chatbot (SEC.2.1) ---
    #
    # `is_active` decía si un chatbot funciona; nada decía **para quién**. Dentro de una
    # organización todos quedaban igual de accesibles, así que un chatbot de gestión
    # interna era tan alcanzable como el público.
    #
    # El default es `authenticated` y no `public_anon` a propósito: un chatbot recién
    # creado no expone su corpus mientras nadie decida lo contrario.
    access_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, default="authenticated", server_default="authenticated"
    )
    # Dos ARRAY y **ninguna tabla de grants**: el atributo de grupo ya llega en el ACS SAML
    # y esto cubre el caso del piloto. Si algún día hace falta granularidad por persona, se
    # añade la tabla entonces; hoy sería infraestructura sin usuario.
    allowed_roles: Mapped[list[str]] = mapped_column(
        ARRAY(String), nullable=False, default=list, server_default="{}"
    )
    allowed_saml_groups: Mapped[list[str]] = mapped_column(
        ARRAY(String), nullable=False, default=list, server_default="{}"
    )
    # --- Vigencia y presupuesto acumulado (SEC.4.1) ---
    #
    # Un chatbot de campaña —plazo de matrícula, convocatoria, alegaciones— tiene que poder
    # caducar solo. Hasta aquí la única palanca era que alguien se acordara de apagarlo.
    #
    # **No hay campo de estado.** Ni `closed_reason` ni voltear `is_active`: el estado se
    # calcula al preguntarlo. Un flag persistido se queda obsoleto y obliga a un job que lo
    # refresque, el consumo acumulado es dato operacional que no puede vivir en una tabla de
    # configuración, e `is_active` seguiría significando dos cosas a la vez —«el admin lo
    # apagó» y «se le pasó el plazo»— en un solo booleano.
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    total_token_budget: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Lo que lee el ciudadano cuando el chatbot no está disponible. Vacío = mensaje genérico
    # del frontend: «el plazo de matrícula terminó el 30 de septiembre» lo escribe quien
    # gestiona el trámite, no un catálogo de errores.
    unavailable_message: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    # UX.4. Qué se contesta cuando NO hay fundamento suficiente, que es distinto de
    # `unavailable_message` —ese es cuando el chatbot está cerrado— y por eso es columna
    # propia y no un segundo significado de la misma. NULL = el texto genérico.
    #
    # Existe porque «no lo sé» a secas deja al ciudadano donde estaba, y a quién hay que
    # remitirlo depende del asistente: Infocampus atiende al público, no a gestión.
    no_answer_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # --- Cuotas de consumo (SEC.4). NULL = heredar de la organización; 0 = sin límite ---
    user_daily_token_quota: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chatbot_daily_token_quota: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Para el widget anónimo (D.1), donde el sujeto no es una persona sino una IP. Sin
    # heredar de la organización: un chatbot público y uno interno no comparten criterio.
    anon_ip_daily_token_quota: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # --- Campos del grafo público (9B.2) ---
    public_graph_profile: Mapped[str] = mapped_column(String(50), nullable=False, default="PUBLIC_KB_RICH")
    # PLG.2 — sobreescritura de estrategias por eje, `{eje: nombre}`. Heredable **clave a
    # clave**: una clave ausente hereda de la organización, y una ausente allí hereda de la
    # composición del perfil. NULL y `{}` significan lo mismo, «hereda todo».
    #
    # JSONB y no cuatro columnas porque los ejes son cuatro hoy y el `StrEnum` puede crecer; y
    # sin CHECK sobre sus valores, que es justo lo que este bloque hace posible: los nombres se
    # validan contra el registro vivo, que sabe qué hay instalado. Un CHECK no puede saberlo.
    estrategias: Mapped[dict[str, str] | None] = mapped_column(JSONB, nullable=True)
    language_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="prefer")
    # RES.1 — se compara contra la puntuación del **mejor** fragmento recuperado, no contra la
    # media de todos. O sea: «¿tengo al menos una fuente buena?», no «¿son buenas de media?».
    # Antes era la media, y eso hacía que ensanchar `retrieval_top_k` bajara la nota y el
    # asistente contestara menos: quien puso un valor antes del 2026-08-25 lo puso con el otro
    # significado, y con el mismo número el filtro es ahora más permisivo.
    quality_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.65)
    min_retrieval_results: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    min_retrieval_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    reranker_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    answer_template: Mapped[str] = mapped_column(String(50), nullable=False, default="generic")
    # Presupuesto de contexto en tokens para la inyección de documentos (VIS.2). NULL =
    # heredar de la organización y, en su defecto, del default de plataforma. Lo consume
    # LongContextRetrievalStrategy para RECORTAR, no para lanzar una excepción.
    context_token_budget: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # --- Troceado (RAG.8). NULL = heredar; el CHECK admite NULL a propósito ---
    chunk_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_overlap: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunking_strategy: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # RAG.10. NULL = heredar; un False no nulo haria que el chatbot pisara siempre a la
    # organizacion y encender la reescritura por organizacion no llegaria a ningun sitio.
    query_rewriting_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # HIB.S — NULL = heredar. El coste de equivocarse no es el mismo en todos los asistentes:
    # un funcionario que recibe un umbral de contratacion equivocado actua sobre el, y un
    # estudiante que recibe una rendicion pregunta en Infocampus.
    grounding_check_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # HIB.T — NULL = heredar. Existe para el tercer asistente de Gerencia, que es el banco con
    # el que se comparan las tres estrategias sobre el mismo lote y el mismo corpus.
    inject_whole_document: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    parent_chatbot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hub_chatbots.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    organizacion: Mapped["HubOrganizacion"] = relationship(back_populates="chatbots")
    llm_config: Mapped["HubLLMConfig"] = relationship(back_populates="chatbots")
    prompt_templates: Mapped[list["HubPromptTemplate"]] = relationship(
        back_populates="chatbot", cascade="all, delete-orphan"
    )


class HubPromptTemplate(HubConfigBase):
    """Prompt parametrizable por chatbot, slug e idioma."""

    __tablename__ = "hub_prompt_templates"

    # MT.1 — no tiene organización: la alcanza por su chatbot, que es lo que acota
    # `/hub/prompts-catalog` desde REV.13.
    __ambito__ = declarar(Ambito.DERIVADA, via="chatbot_id")
    __table_args__ = (
        UniqueConstraint(
            "chatbot_id", "slug", "language", name="uq_prompt_chatbot_slug_lang"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    chatbot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hub_chatbots.id", ondelete="CASCADE"),
        nullable=False,
    )
    slug: Mapped[str] = mapped_column(String(100), nullable=False)  # ej: system_base
    language: Mapped[str] = mapped_column(String(10), nullable=False)  # ca | es | en
    template_text: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    default_tier: Mapped[int | None] = mapped_column(Integer, nullable=True)
    override_tier: Mapped[int | None] = mapped_column(Integer, nullable=True)

    chatbot: Mapped["HubChatbot"] = relationship(back_populates="prompt_templates")


class HubActivityPrompt(HubConfigBase):
    """Override del prompt y del nivel de una **actividad de plataforma** — PRO.2.1.

    `HubPromptTemplate` cuelga de un chatbot (`chatbot_id` NOT NULL), así que sirve a los
    prompts de un asistente y no a los de una actividad del módulo de Informes —escribir un
    script, auditarlo, transformar datos—, que no pertenecen a ningún chatbot.

    **No se resolvió haciendo `chatbot_id` nullable**: en Postgres una restricción unique con
    NULL no colisiona, así que `(chatbot_id, slug, language)` dejaría de ser única justo para
    las filas nuevas —dos overrides de la misma actividad conviviendo—, y la pantalla que
    filtra por chatbot perdería el sentido. Son dos claves distintas y dos audiencias
    distintas.

    Qué actividades existen, con qué nivel corren y qué se les dice lo dice el **código**
    (`modules/redaccion/services/actividades_llm.py`). Esta tabla guarda sólo la excepción:

    - `template_text` vacío o NULL = usa el texto del código. No se copia el texto por
      defecto al abrir la pantalla: copiarlo congelaría el prompt, y mejorarlo en el código
      no llegaría a quien ya lo abrió.
    - `override_tier` NULL = usa el nivel del código.
    """

    __tablename__ = "hub_activity_prompts"

    # MT.6 — heredable: la cadena es organización → plataforma → código, y **el texto del
    # código nunca se copia a una fila**. `activity` era único global, que es defendible para
    # una actividad de plataforma y deja de serlo en cuanto un municipio quiere su redacción.
    __ambito__ = Ambito.HEREDABLE
    __table_args__ = (
        # La organización entra en la clave, con `NULLS NOT DISTINCT` para que la unicidad valga
        # también en el nivel de plataforma —el de todas las filas de hoy—: en Postgres
        # `NULL != NULL`, y dos overrides del mismo ámbito serían dos respuestas a una pregunta
        # con una sola. Es la misma trampa que el docstring de arriba advertía sobre
        # `chatbot_id` nullable, y aquí se evita con la cláusula en vez de con otra tabla.
        UniqueConstraint(
            "activity",
            "organizacion_id",
            name="uq_activity_prompt_scope",
            postgresql_nulls_not_distinct=True,
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # La clave estable de la actividad (`ActividadLLM.value`). Ya no es única por sí sola: la
    # unicidad es por (actividad, organización) desde MT.6.
    activity: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    #: MT.6 — de quién es este override. **Nulo = de la plataforma, y se hereda.**
    organizacion_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hub_organizaciones.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    template_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    override_tier: Mapped[int | None] = mapped_column(Integer, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class HubUser(HubConfigBase):
    """Una persona de la plataforma (IDE.2). Antes `HubSsoUser` / `hub_sso_users`.

    Identidades que no son `SuperAdminAccount` ni `AdminAccount`. Se llamaba «sso» porque su
    único escritor era el ACS de SAML, que la crea o actualiza Just-In-Time tras validar la
    aserción — pero la tabla siempre fue un registro de personas completo (correo único, nombre,
    rol, organización, activo, último acceso), y con el nombre viejo nadie iba a escribir aquí
    una persona dada de alta a mano. `origen` dice quién la creó.

    **El rol no lo pisa el IdP salvo que se le deje** (IDE.1): con
    `IDENTITY_ROLE_AUTHORITY=app` —el defecto— quien entra por SSO no cambia el rol que le puso
    una persona, y quien llega nuevo entra con `SAML_DEFAULT_ROLE`.

    **Sigue habiendo cuatro tablas de identidad** (`SuperAdminAccount` con `admin_id` entero,
    `AdminAccount` con `partner_id` de texto, `ClientAccount`, y esta), y unificarlas no es
    trabajo de este prompt: `user_to_uuid` está en la propiedad de los workspaces de redacción,
    en los PAT y en las concesiones de módulo, y `es_propietario` ya acepta las dos formas en
    que quedó escrita la propiedad (SEC.8.1). Es una migración de datos con riesgo y merece
    bloque propio.
    """

    __tablename__ = "hub_users"

    # MT.1 — `organizacion_id` nullable: nulo es la cuenta que no pertenece a ninguna, o sea
    # nivel plataforma. El filtro que falta lo pone MT.9, en la fase 2.
    __ambito__ = Ambito.HEREDABLE
    __table_args__ = (
        # Dato con dos valores estables, cada uno con consumidor en el código: aquí sí va
        # `CheckConstraint`, mismo criterio que `purpose` en `HubLLMConfig`. Lo que no puede
        # ser un `Enum` es el vocabulario del corpus, que está para revisarse.
        CheckConstraint("origen IN ('sso', 'manual')", name="ck_hub_users_origen"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(
        String(320), unique=True, index=True, nullable=False
    )
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(40), nullable=False, default="user")
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)  # NameID
    idp_entity_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # SEC.2.1. Sin esto, un usuario provisionado por SSO se quedaba con el claim de SEC.2
    # vacío y, por su propia regla, sin acceso a ningún recurso de organización.
    #
    # **Sale de la configuración del IdP (`SAML_ORGANIZACION_ID`), nunca de la aserción**:
    # si viniera de fuera, quien controla el IdP podría declarar a qué organización
    # pertenece cada persona que entra. Nullable porque un despliegue puede no haberla
    # configurado todavía, y ahí lo correcto es no dar acceso a nada.
    organizacion_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hub_organizaciones.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    #: Contraseña de login local (USR.1), mientras el IdP institucional no esté configurado.
    #:
    #: **NULL es «login local deshabilitado»** —entra por SSO, o no entra—, y **jamás «pasa sin
    #: comprobar»**: la lectura contraria es el hallazgo A1 de SEC.1 reabierto por la puerta de
    #: atrás, y por eso `POST /auth/user/login` compara contra un hash señuelo cuando esto es
    #: nulo. Mismo criterio, y mismo motivo, que `AdminAccount.hashed_password`.
    #:
    #: **Ortogonal a `origen`**, que dice quién creó la fila y no cómo entra: una persona puede
    #: tener las dos vías, el ACS no toca esta columna y fijar contraseña no cambia `origen`.
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    #: Si la contraseña de esta persona **la puso otra** y sigue pendiente de cambio (issue #94).
    #:
    #: Es lo que acota a un solo uso el conocimiento de quien la restableció: mientras sea cierto,
    #: el token que se emita no sirve para nada más que cambiarla. Sin esto, quien restablece
    #: conoce una contraseña que vale indefinidamente — que es lo que costó el incidente del
    #: 2026-09-01, con seis cuentas compartiendo secreto y la atribución de las valoraciones
    #: valiendo lo que valiera ese secreto.
    #:
    #: `NOT NULL` con defecto falso, explícito: nulo aquí sería un tercer estado que nadie sabe
    #: leer, y el defecto de servidor es lo que deja las filas que ya existen en «nada pendiente».
    debe_cambiar_contrasena: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    #: Cuándo y quién restableció la contraseña por última vez (issue #94). Sin la traza, un
    #: restablecimiento es indistinguible de un cambio propio y la pregunta «¿quién más ha
    #: conocido esta contraseña?» no tiene respuesta.
    password_reset_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    password_reset_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    #: Quién creó la fila: `sso` (el ACS, Just-In-Time) o `manual` (una persona, IDE.3). El
    #: defecto es `sso` porque el ACS no va a escribirlo en cada entrada, y NULL no vale: la
    #: pantalla de personas distingue las dos procedencias.
    origen: Mapped[str] = mapped_column(
        String(10), nullable=False, default="sso", server_default="sso"
    )
    #: Quién dio el alta, cuando la dio una persona (IDE.3). NULL en las filas que creó el
    #: ACS: no hay a quién atribuirlas, y `origen = 'sso'` ya dice lo que se sabe de ellas.
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class HubPersonalAccessToken(HubConfigBase):
    """Personal Access Token revocable para clientes máquina (AUTH.3).

    Se guarda solo el hash sha256 del token y un prefijo visible para identificarlo
    en la UI; el texto plano se entrega una única vez en la creación.
    """

    __tablename__ = "hub_personal_access_tokens"

    # MT.5 — heredable: nulo = vale donde valga su dueño, que es lo que significan los que ya
    # existen. Acotarlos en la migración habría roto integraciones que funcionan sin avisar.
    __ambito__ = Ambito.HEREDABLE

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    owner_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    owner_email: Mapped[str] = mapped_column(String(320), nullable=False)
    owner_role: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    token_prefix: Mapped[str] = mapped_column(
        String(16), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    #: MT.5 — sobre qué organización puede actuar. **Nulo = donde pueda su dueño**, que es el
    #: comportamiento de SEC.2 y el de los tokens que ya existen. Cuando lo declara, **acota**:
    #: nunca amplía, porque el alcance del dueño se sigue resolviendo en cada validación y un
    #: token que sobreviviera a la retirada de una organización sería una revocación que no
    #: revoca.
    organizacion_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hub_organizaciones.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class HubTheme(HubConfigBase):
    """Tema de identidad visual (SEC.8.6).

    Vivían como ficheros `.json` bajo `data/themes`, ruta relativa al directorio de
    trabajo del proceso. En Cloud Run el contenedor es efímero y hay varias instancias:
    un tema creado en una desaparecía al reciclarse y no existía para las demás. El widget
    lo heredaba —resuelve el contenido desde el puntero `theme_config`— y volvía a quedarse
    sin tema en producción, con el puntero intacto.

    Es **configuración institucional**, no dato operacional del cliente: va en
    `HubConfigBase` y por tanto se sincroniza cloud→edge.

    `organizacion_id` nulo = tema **de plataforma**, que hereda la cascada entera; crearlo
    está reservado al superadministrador (SEC.2).
    """

    __tablename__ = "hub_themes"

    # MT.1 — la cascada que ya funcionaba, y de la que sale el patrón: nulo = plataforma.
    __ambito__ = Ambito.HEREDABLE

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    organizacion_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hub_organizaciones.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    chatbot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hub_chatbots.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class HubWidgetKey(HubConfigBase):
    """Credencial de **sitio** para el widget público (SEC.8.5).

    El widget se incrustaba con `data-token`, y ese token era un JWT de sesión o un PAT
    completo: visible en el HTML de la página y con el rol y las organizaciones de su dueño
    detrás. SEC.2.1 ya había previsto la alternativa —`assert_chatbot_access` con
    `via='widget_api_key'` solo abre chatbots `public_anon`— pero no existía credencial que
    la usara.

    Tres propiedades, y las tres importan:

    - **Identifica un sitio, no a una persona.** No lleva rol ni organizaciones: lo único
      que autoriza es conversar con SU chatbot, y solo si es público.
    - **Vale para un chatbot.** `chatbot_id` no es un filtro que el endpoint aplique: es de
      dónde sale el chatbot, así que no hay forma de apuntarla a otro.
    - **Se guarda con hash**, como los PAT. El plano se enseña una vez al crearla.
    """

    __tablename__ = "hub_widget_keys"

    # MT.1 — la credencial es de un asistente concreto (SEC.8.5).
    __ambito__ = declarar(Ambito.DERIVADA, via="chatbot_id")

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    chatbot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hub_chatbots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class HubPlatformModule(HubConfigBase):
    """El catálogo de módulos de la plataforma, **como dato** (INF.7).

    Vive en tabla y no en un `Enum` de Python ni en un `CheckConstraint`, por la misma regla que
    el vocabulario del corpus: si los módulos fueran código, añadir uno exigiría una migración y
    un despliegue. `vigente` permite retirar uno sin borrar las concesiones que lo citan, que
    son el histórico de quién tuvo acceso a qué.

    En `HubConfigBase` porque es **configuración administrativa**: se decide en el cloud y el
    edge la necesita para saber si quien pide un informe puede pedirlo.
    """

    __tablename__ = "hub_platform_modules"

    # MT.1 — el catálogo de módulos es de la instalación entera.
    __ambito__ = Ambito.PLATAFORMA

    code: Mapped[str] = mapped_column(String(50), primary_key=True)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    vigente: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    #: **De oficio**: lo tiene cualquier persona de la plataforma, sin concesión (UTL, 2026-10-02).
    #: Una marca y no una fila por persona: conceder a cada cuenta obligaría a acordarse en cada
    #: alta —también en las que llegan por Google o SAML—, y la que se olvidara dejaría a alguien
    #: sin el módulo sin que nada lo dijera.
    de_oficio: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=sa_false()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class HubModuleGrant(HubConfigBase):
    """Un módulo concedido a **una persona o a un grupo del IdP** (INF.7, ampliado en IDE.5).

    Con `subject_type = 'usuario'` el sujeto es el id de usuario **normalizado a UUID** con
    `_actor.user_to_uuid`: no hay una tabla de usuarios única —hay `SuperAdminAccount` con
    `admin_id` entero y `AdminAccount` con `partner_id` de texto—, así que la clave estable es la
    que se deriva del claim del token. Ese normalizador existe precisamente por eso.

    Con `subject_type = 'grupo'` el sujeto es el **nombre del grupo tal como lo declara el IdP**
    en el atributo de `SAML_ATTR_GROUPS`. Es la puerta al modelo que quiere el usuario: el ERP
    mete a la persona en un grupo, el IdP lo declara, y la concesión del grupo le da los módulos
    sin que nadie toque nada aquí. La semántica es la de `assert_chatbot_access` —rol **o**
    grupo, lo que case primero— con su regla: sin concesión que case, no hay módulo.

    `subject_id` es `String(255)` y no `String(36)`: estaba dimensionado para un UUID y un
    nombre de grupo institucional no cabe ahí de forma fiable.
    """

    __tablename__ = "hub_module_grants"

    # MT.5 — heredable: **nulo significa «en todas»**, que es lo que significan las
    # concesiones de hoy. Reinterpretarlas en silencio como «en ninguna» le quitaría los
    # permisos a todo el mundo en una migración, y como «en la primera» sería inventárselo.
    __ambito__ = Ambito.HEREDABLE

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subject_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    #: `usuario` | `grupo`. Dato con dos valores estables y consumidor en el código: va con
    #: `CheckConstraint`, mismo criterio que `origen` en `HubUser`.
    subject_type: Mapped[str] = mapped_column(
        String(10), nullable=False, default="usuario", server_default="usuario"
    )
    module_code: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    #: MT.5 — en qué organización vale. **Nulo = en todas**, que es lo que valen las de hoy.
    #: Es un eje perpendicular al de `subject_type`: aquél dice a **quién** se concede y éste
    #: **dónde**, y hacen falta los dos —conceder un módulo a un grupo del IdP se lo concedía
    #: en las veinte organizaciones de una Diputación a la vez—.
    organizacion_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hub_organizaciones.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    #: Quién lo concedió. Un permiso sin autoría no se puede auditar.
    granted_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    __table_args__ = (
        # El tipo entra en la clave: sin él, un grupo cuyo nombre coincidiera con el UUID de
        # una persona no podría convivir con la concesión de esa persona.
        # MT.5 — la organización entra en la clave: la misma persona con el mismo módulo en
        # dos organizaciones son **dos** concesiones legítimas. Con `NULLS NOT DISTINCT`, para
        # que la unicidad valga también en el nivel «en todas» —el de todas las filas de hoy—:
        # en Postgres `NULL != NULL`, así que sin ella dos duplicados idénticos pasarían.
        UniqueConstraint(
            "subject_type",
            "subject_id",
            "module_code",
            "organizacion_id",
            name="uq_grant_subject_type_module",
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint(
            "subject_type IN ('usuario', 'grupo')", name="ck_grant_subject_type"
        ),
    )
