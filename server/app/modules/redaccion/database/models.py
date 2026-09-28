"""Modelos ORM para el módulo de redacción — 9R.1.4.

Todos usan HubOperationalBase (edge). Sin relationship() cross-base.
hub_report_template_versions es append-only: no hay UPDATE en el repo.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column

from server.app.core.ambito import Ambito, declarar
from server.app.modules.agents_hub.database.base import HubOperationalBase


def _now() -> datetime:
    return datetime.now(timezone.utc)


class HubReportTemplate(HubOperationalBase):
    """Plantilla de informe. El campo current_version_id se gestiona a nivel de app.

    **MT.4 — la escalera de elevación completa: usuario → organización → plataforma.** Los dos
    extremos existían desde 9R (`owner_kind` admitía `user`, `platform` y `superadmin`) y faltaba
    el de en medio, que es el que hace falta en cuanto una Diputación despliega para varios
    municipios: una plantilla podía ser de una persona o de todo el mundo, y nada intermedio.

    **`is_global` ya no es columna.** Se calculaba en el router como `owner_kind == "platform"`,
    así que dos sitios guardaban el mismo hecho y podían discrepar sin que nada avisara. Ahora es
    un `hybrid_property`, que sirve igual en Python y en SQL — que es lo que hacía falta, porque
    el listado filtra por él.
    """

    __tablename__ = "hub_report_templates"
    __table_args__ = (
        # MT.4 — coherencia entre las dos columnas, **en la base y no sólo en el modelo**: una
        # plantilla «de organización» que no dice de cuál no la encuentra ninguna consulta ni la
        # excluye ninguna, así que se cuela en los dos lados.
        CheckConstraint(
            "owner_kind <> 'organizacion' OR organizacion_id IS NOT NULL",
            name="ck_report_template_organizacion_coherente",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    report_profile: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    owner_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # MT.4 — el escalón de en medio. Nulo en los demás niveles: una de plataforma no es de
    # ninguna organización, y una personal se identifica por su dueño.
    organizacion_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    # MT.4.2 — de dónde salió esta copia. **`ON DELETE SET NULL` y no CASCADE**: con CASCADE,
    # retirar la plantilla de la Diputación borraría las de los municipios que la adaptaron. La
    # procedencia es una anotación histórica, no una dependencia.
    derivado_de: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hub_report_templates.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    #: Con qué versión del original se bifurcó. Es lo que permite decir «hay una v4 y tienes la v3».
    version_de_origen: Mapped[int | None] = mapped_column(Integer, nullable=True)

    @hybrid_property
    def is_global(self) -> bool:
        """Del nivel de plataforma. **Derivado, no guardado** (MT.4).

        Se conserva el nombre porque está en el contrato y lo consume el frontend; lo que
        desaparece es la columna, que era el mismo hecho escrito dos veces.
        """
        return self.owner_kind == "platform"

    @is_global.expression
    def is_global(cls):  # noqa: N805 - la firma la fija SQLAlchemy
        return cls.owner_kind == "platform"

    # Sin FK a hub_report_template_versions para evitar circularidad; se aplica en app
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    # GUI.1 — retirar una plantilla es archivarla, no borrarla: un informe firmado no puede
    # quedarse sin la plantilla con la que se hizo. Nula = vigente.
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now, onupdate=_now
    )


class HubReportTemplateVersion(HubOperationalBase):
    """Versión de plantilla. Append-only: el repo NO expone método update."""

    __tablename__ = "hub_report_template_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hub_report_templates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    spec_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)


class HubRunManifest(HubOperationalBase):
    """Registro inmutable de una ejecución de redacción."""

    __tablename__ = "hub_run_manifests"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hub_workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    template_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hub_report_template_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    report_profile: Mapped[str] = mapped_column(String(100), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # Completado solo al ensamblar; null mientras el manifest está en curso
    final_document_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )


class HubWorkspace(HubOperationalBase):
    """Workspace de redacción activo.

    status puede ser: draft | ingesting | extracting | drafting | in_review |
                      assembled | exported | error | archived
    parent_workspace_id: apunta al workspace original cuando éste fue migrado a nueva versión.
    archived_reason: razón textual del archivado (ej. "migrated_to_{new_id}").
    """

    __tablename__ = "hub_workspaces"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    template_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hub_report_template_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # MT.4 — de qué organización es este informe. Nulo = de nadie en concreto, que es lo que
    # significan los 29 que ya existen. La rellena quien crea el informe a partir de la
    # organización de la plantilla o de quien lo abre; la pantalla que lo elige es fase 2.
    organizacion_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    inputs_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # Issue #86 — lo que una persona escribe en los campos de los bloques `USER_INPUT`.
    #
    # **Columna propia y no una clave más de `inputs_json`**, que es de ficheros: `uploaded_slots`
    # devuelve sus claves como ficheros ya subidos —así que un texto saldría en la pantalla como
    # un fichero— y el runner valida cada entrada como `InputArtifact`, con lo que además lo
    # registraría como entrada corrupta.
    manual_inputs_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    warnings_json: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    # Sin FK a hub_run_manifests para evitar FK circular; se aplica en app
    run_manifest_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    # Versionado: apunta al workspace original tras una migración (9R.4.4)
    parent_workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hub_workspaces.id", ondelete="SET NULL"),
        nullable=True,
    )
    archived_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Modo NER reversible (13.1): off | detect_only | replace | replace_with_disposition_7.
    anonymization_mode: Mapped[str] = mapped_column(
        String(40), nullable=False, default="replace"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now, onupdate=_now
    )


class HubWorkspaceBlock(HubOperationalBase):
    """Estado de un bloque dentro de un workspace. UNIQUE(workspace_id, block_id)."""

    __tablename__ = "hub_workspace_blocks"
    __table_args__ = (
        UniqueConstraint("workspace_id", "block_id", name="uq_workspace_block"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hub_workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    block_id: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    content_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    citations_json: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    approval_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    failure_kind: Mapped[str | None] = mapped_column(String(50), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now, onupdate=_now
    )


class HubScriptProposal(HubOperationalBase):
    """Propuesta de script de extracción generada por LLM y auditada.

    Estados (9R.5.5 cubre proposed/tested/rejected; los demás llegan en 9R.5.6):
      proposed | tested | pending_review | approved | rejected
    """

    __tablename__ = "hub_script_proposals"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    proposer_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    target_owner_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    target_template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    prompt_nl: Mapped[str] = mapped_column(Text, nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    audit_result_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # PRO.2 — el veredicto del modelo auditor (nivel 3), aparte del resultado determinista.
    # Columna propia y no una clave dentro de `audit_result_json`: son dos cosas con dos
    # autoridades distintas, y mezclarlas invita a que un consumidor lea la opinión del
    # modelo creyendo que lee la auditoría que de verdad bloquea.
    model_review_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    test_data_ref: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    test_data_is_anonymized: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    test_data_anonymization_map: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    test_data_kind: Mapped[str | None] = mapped_column(String(20), nullable=True)
    test_result_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    test_result_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    test_validated_by_proposer_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="proposed", index=True)
    reviewer_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    admin_retest_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    model_used: Mapped[str | None] = mapped_column(String(120), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now, onupdate=_now
    )


class HubFuncion(HubOperationalBase):
    """Una función determinista del catálogo: código con contrato, versionada y compartible (FUN.1).

    **Por qué existe.** El código de un script aprobado se incrustaba copiado en el bloque de cada
    plantilla (`options={"code": …}`), así que dos plantillas que necesitan la misma extracción
    eran dos propuestas, dos aprobaciones y dos copias, y un error en un script usado por N
    plantillas se arreglaba N veces. `HubScriptProposal` es una cola de aprobación con
    `target_template_id`, no un catálogo.

    **Es el canal del nivel 2 de la Instrucció 02/2026**: registrar una función *es* el acto de
    declararla y compartirla dentro del servicio. De ahí que el nivel **se derive** en vez de
    guardarse (`nivel`), que la declaración responsable viva en la versión, y que la aprobación
    humana previa quede sólo para el paso a nivel 3 (`publicada_en`).

    **Dos orígenes, una sola forma.** `autoservicio` es desarrollo ciudadano: el código vive aquí
    y corre en el sandbox. `paquete` es desarrollo corporativo: el código vive en un paquete
    instalado, se descubre por *entry point* y corre en el proceso — la confianza se desplaza a
    quien instala, y eso se dice, no se disimula. Lo que la plataforma centraliza en ambos es la
    revisión, el manifiesto, la trazabilidad y el contrato.

    **Lado edge, y no por comodidad**: `HubFuncionVersion.code` y su declaración son texto escrito
    por una persona de la organización, que es el criterio con el que `hub_lexicon_pairs` acabó en
    el lado operacional (ver `docs/MULTITENENCIA.md`). `__ambito__` se declara igual, porque
    documenta la cascada —nulo = plataforma— aunque el guardarraíl de MT.1 sólo recorra
    `HubConfigBase`.
    """

    __tablename__ = "hub_funciones"
    __ambito__ = Ambito.HEREDABLE

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    descripcion: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: Nulo = de plataforma (nivel 3). La semántica heredable de siempre.
    organizacion_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    #: `autoservicio` | `paquete`. Es **estructura y no vocabulario**: cada valor tiene
    #: consumidor en el código —el resolutor elige sandbox o proceso— y añadir uno exige
    #: escribir ese consumidor. Por eso lleva `CheckConstraint`, al contrario que las
    #: categorías de datos (I4).
    origen: Mapped[str] = mapped_column(
        String(20), nullable=False, default="autoservicio"
    )
    #: Sólo en `paquete`: «distribucion:nombre». Único cuando no es nulo — dos funciones no
    #: pueden reclamar el mismo *entry point*.
    entry_point: Mapped[str | None] = mapped_column(
        String(200), nullable=True, unique=True
    )
    #: Paso a nivel 3. Lo resuelve el superadministrador, con valoración obligatoria: es la
    #: única aprobación humana **previa** del bloque, y es previa porque el nivel 3 lo es.
    promocion_solicitada_por: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    promocion_solicitada_en: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    motivo_promocion: Mapped[str | None] = mapped_column(Text, nullable=True)
    publicada_en: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    publicada_por: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    valoracion_promocion: Mapped[str | None] = mapped_column(Text, nullable=True)
    creada_por: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now, onupdate=_now
    )

    __table_args__ = (
        CheckConstraint(
            "origen IN ('autoservicio', 'paquete')", name="ck_funcion_origen"
        ),
    )

    @hybrid_property
    def nivel(self) -> int:
        """El nivel de la Instrucció 02/2026, **derivado**.

        Nivel 2 es «de mi organización y sin publicar»; nivel 3 es «de alcance superior al
        servicio»: publicada, de paquete, **o sin organización**. Una columna `nivel` sería un
        tercer sitio donde vive el mismo hecho, y podría discrepar de los otros dos — el defecto
        que MT.4 quitó de `is_global`.

        `organizacion_id IS NULL` cuenta como nivel 3 porque es lo que ya significa en las otras
        dos superficies: `consulta_de_catalogo` la sirve a todas las organizaciones y
        `acciones_permitidas` la trata como publicada. Sin esta rama, las cuatro funciones que la
        migración de FUN.3 sacó de plantillas globales se pintaban «Nivel 2» —«de mi organización
        y sin publicar»— encima de algo que ve cualquiera. Lo destapó la pantalla del catálogo.
        """
        if (
            self.origen == "paquete"
            or self.publicada_en is not None
            or self.organizacion_id is None
        ):
            return 3
        return 2

    # `inplace` y no `@nivel.expression` a secas: sin él, SQLAlchemy 2.0 construye un híbrido
    # **nuevo** y lo deja en `_nivel_en_sql`, mientras `nivel` se queda sin expresión SQL — y
    # entonces `select(HubFuncion.nivel)` intenta evaluar el getter de Python contra la clase.
    # Era el caso: la expresión estaba escrita y no la usaba nadie.
    @nivel.inplace.expression
    @classmethod
    def _nivel_en_sql(cls):
        from sqlalchemy import case

        return case(
            (cls.origen == "paquete", 3),
            (cls.publicada_en.isnot(None), 3),
            (cls.organizacion_id.is_(None), 3),
            else_=2,
        )


class HubFuncionVersion(HubOperationalBase):
    """Una versión de una función. **Registrada es inmutable**: corregir es publicar otra (FUN.1).

    Sin esa inmutabilidad, «arreglar una vez» sería «cambiar en silencio informes ya aprobados» y
    el `RunManifest` dejaría de ser reproducible — misma razón que el registro de auditoría.

    Lleva la **declaración responsable** que la Instrucció exige antes de compartir (§8.2:
    finalidad y categorías de datos) y el resultado de la **revisión posterior** (§8.4), que es de
    otra persona y de otro momento: por eso esos campos sí se pueden escribir sobre una versión
    registrada y el código no.

    `categorias_datos` usa el **mismo vocabulario** que el registro de actividad de REG
    (`core/actividad_categorias.py`): un solo vocabulario de categorías en la plataforma, o los
    dos registros no se pueden cruzar en una auditoría.
    """

    __tablename__ = "hub_funcion_versiones"
    __ambito__ = declarar(Ambito.DERIVADA, via="funcion_id")

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    funcion_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hub_funciones.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    #: Ordinal del catálogo, en los dos orígenes: es lo que ancla una plantilla.
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Nulo en `paquete`: ahí el código vive en el paquete y guardarlo aquí sería una copia
    #: que divergiría del `pip install` sin que nada avisara.
    code: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Semver de la distribución instalada. Sólo en `paquete`.
    version_paquete: Mapped[str | None] = mapped_column(String(32), nullable=True)
    contrato_entrada: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    contrato_salida: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    #: Nulo en `paquete`: no hay auditoría AST de un código que no está aquí.
    audit_result_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    #: De lo que **corrió**: el código en autoservicio, la fuente de la función instalada en
    #: paquete. Es lo que el `RunManifest` registra para poder decir qué se ejecutó.
    code_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    #: `draft` | `registrada` | `suspendida` | `retirada` | `no_instalada`. El último sólo en
    #: `paquete`. Estructura con consumidor: el resolutor decide por él si ejecuta o falla.
    estado: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", index=True
    )
    #: La IA la propuso, o la trajo una persona de su equipo (el caso mayoritario de la
    #: Instrucció: un script que ya funcionaba en nivel 1). No hay ninguna rama «si lo escribió
    #: la IA»: los dos caminos pasan por el mismo auditor y el mismo sandbox. Se guarda porque
    #: la revisión posterior quiere verlo.
    autoria: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # ── Declaración responsable (Instrucció §6 regla 3, §8.2) ──
    finalidad: Mapped[str | None] = mapped_column(Text, nullable=True)
    categorias_datos: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    declarada_por: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    declarada_en: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ── Revisión posterior (Instrucció §8.4) ──
    revisada_por: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    revisada_en: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: `conforme` | `correcciones` | `reclasificada` | `suspendida`.
    revision_resultado: Mapped[str | None] = mapped_column(String(20), nullable=True)
    revision_nota: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Suspensión: de quien revisa, y con motivo ──
    suspendida_por: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    suspendida_en: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    motivo_suspension: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )

    __table_args__ = (
        UniqueConstraint("funcion_id", "version", name="uq_funcion_version"),
        CheckConstraint(
            "estado IN ('draft', 'registrada', 'suspendida', 'retirada', 'no_instalada')",
            name="ck_funcion_version_estado",
        ),
    )


class HubWorkspaceAuditEvent(HubOperationalBase):
    """Registro de auditoría de transiciones de bloque y eventos de workspace."""

    __tablename__ = "hub_workspace_audit_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hub_workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    block_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    event: Mapped[str] = mapped_column(String(50), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    actor: Mapped[str] = mapped_column(String(255), nullable=False, default="system")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
