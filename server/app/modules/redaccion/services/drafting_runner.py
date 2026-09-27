"""Raíz de composición del DraftingCoreGraph y persistencia de lo que produce (VER.1).

Deploy: edge.

El grafo ya existía entero —14 nodos, con sus tests— pero **nadie lo ejecutaba**:
`POST /workspaces/{id}/run` cambiaba el estado a `drafting`, devolvía un `run_id` sintético y
ahí acababa. Aquí vive lo que faltaba, que son tres cosas y ninguna es el grafo:

1. **Quién le pasa sus dependencias**: repositorio de versiones, almacenamiento, factoría de
   extracción y modelo. Va aquí y no en el router por la misma razón que
   `build_agentic_loop_if_needed` no vive dentro del CoreGraph del chatbot: es una decisión
   de composición, y meterla en el router ata el módulo a HTTP.
2. **Cómo se convierte un workspace en `WorkspaceState`** y al revés. Hasta hoy nadie
   escribía nunca una fila en `hub_workspace_blocks`, así que un informe generado no existía
   en ningún sitio al terminar la petición.
3. **Qué pasa cuando falla.** Un workspace atascado en `drafting` para siempre es peor que
   uno que dice que falló: el primero se lee como «va lento» y nadie lo mira nunca.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from pydantic import ValidationError

from server.app.modules.redaccion.contracts.runtime import (
    BlockState,
    InputArtifact,
    WorkspaceState,
)
from server.app.modules.redaccion.contracts.template import ReportTemplateSpec
from server.app.modules.redaccion.database.models import HubWorkspace, HubWorkspaceBlock
from server.app.modules.redaccion.services.anonymization.politica import modo_de_ejecucion
from server.app.modules.redaccion.database.repos import (
    ReportTemplateVersionRepo,
    RunManifestRepo,
    WorkspaceRepo,
)

_log = logging.getLogger(__name__)

ESTADO_EN_REVISION = "in_review"
ESTADO_ERROR = "error"


def construir_grafo(
    session: Any,
    llm_service: Any,
    storage_service: Any = None,
    etl_llm: Any = None,
    etl_model_name: str = "",
    etl_system_prompt: str | None = None,
):
    """El `DraftingCoreGraph` con sus dependencias resueltas contra esta sesión.

    **`pii_detector` y `faker_generator` se inyectan desde la issue #170.** Se dejaban fuera, y
    sin ellos `_build_init_anonymization_node` devuelve un no-op declarado: el contexto quedaba en
    `None`, los hooks pre/post-LLM no operaban, y elegir `replace` en la pantalla daba exactamente
    lo mismo que elegir `off`. Sin error y sin aviso — que es peor que no ofrecer la opción.

    Uno por ejecución, y no compartido: un detector que viviera entre informes acumularía en sus
    mapas el PII de todos los que pasaron. Es la misma razón por la que el endpoint público de
    anonimización (REG.3) es *stateless* a propósito.

    `etl_llm` sí se inyecta desde PRO.4: sin él, `DataTransformationNode` se construía con
    `llm_service=None` y un bloque de transformación en modo IA fallaba con «ai mode requires
    an injected llm». Es un modelo distinto del de redacción porque la tarea es distinta:
    transformar datos es **programar**, así que va con el nivel 2.
    """
    from server.app.core.storage import get_storage_service
    from server.app.modules.redaccion.funciones_resolver import ResolvedorDeFuncion
    from server.app.modules.redaccion.graph import core_graph
    from server.app.modules.redaccion.pipelines.factory import build_default_factory
    from server.app.modules.redaccion.services.anonymization.faker_generator import (
        FakerGenerator,
    )
    from server.app.modules.redaccion.services.anonymization.pii_detector import PiiDetector

    return core_graph.build_core_graph(
        template_version_repo=ReportTemplateVersionRepo(session),
        storage_service=storage_service or get_storage_service(),
        extraction_factory=build_default_factory(),
        llm_service=llm_service,
        manifest_repo=RunManifestRepo(session),
        etl_llm=etl_llm,
        etl_model_name=etl_model_name,
        etl_system_prompt=etl_system_prompt,
        # FUN.3 — sin esto, un bloque que referencia una función del catálogo fallaría en alto
        # diciendo que el grafo se construyó sin resolutor. Es mejor que ejecutar nada en
        # silencio, pero es un fallo: el sitio donde se pasa es éste, y hay un test que lo fija.
        resolvedor_de_funciones=ResolvedorDeFuncion(session),
        # El detector no carga el modelo de spaCy hasta que un texto pasa por el NER, así que
        # construirlo aquí no cuesta nada cuando el modo es `off`.
        pii_detector=PiiDetector(),
        faker_generator=FakerGenerator(),
    )


async def resolver_modelo_de_etl(
    session: Any, *, organizacion_id: Any = None
) -> tuple[Any, str, str]:
    """El modelo de la actividad de transformación, con su nivel y su nombre.

    El nivel sale del catálogo de actividades (nivel 2, porque transformar es programar) y la
    biblioteca de prompts puede sobreescribirlo. Si no hay modelo configurado se devuelve
    `None`: **el modo determinista tiene que seguir funcionando sin modelo**, y un informe que
    sólo aplica operaciones declarativas no tiene por qué depender de que haya un LLM.
    """
    from server.app.modules.agents_hub.services.config_provider import LocalConfigProvider
    from server.app.modules.agents_hub.services.model_factory import get_model_for_tier
    from server.app.modules.redaccion.services.actividades_llm import (
        ActividadLLM,
        resolver_actividad,
    )
    from server.app.routers.redaccion._actor import nombre_del_modelo

    proveedor = LocalConfigProvider(session)
    resuelta = await resolver_actividad(ActividadLLM.TRANSFORMACION_ETL, proveedor)
    try:
        modelo = await get_model_for_tier(
            resuelta.tier, proveedor, organizacion_id=organizacion_id
        )
    except Exception as fallo:  # noqa: BLE001
        _log.warning(
            "Sin modelo para el nivel %s: los bloques de transformación en modo IA fallarán "
            "con su motivo, el modo determinista sigue funcionando (%s)",
            resuelta.tier,
            fallo,
        )
        return None, "", resuelta.template_text
    return modelo, nombre_del_modelo(modelo), resuelta.template_text


def _estado_inicial(
    workspace: HubWorkspace,
    spec: ReportTemplateSpec,
    existentes: list[HubWorkspaceBlock] | None = None,
    modo_anonimizacion: str | None = None,
) -> WorkspaceState:
    """El estado con el que arranca el grafo.

    Qué bloques hay lo dice la **plantilla**; en qué estado están, lo que ya haya en la base.
    Esa distinción es lo que hace que reanudar signifique algo: si se arrancara siempre de
    cero, continuar tras aprobar el texto de IA borraría esa aprobación y lo volvería a
    generar, que es justo lo contrario de lo que pide quien pulsa continuar.
    """
    ahora = datetime.now(timezone.utc)
    guardados = {fila.block_id: fila for fila in (existentes or [])}

    def _bloque(contrato) -> BlockState:
        fila = guardados.get(contrato.id)
        if fila is None:
            return BlockState(
                block_id=contrato.id, kind=contrato.kind, status="draft",
                last_updated_by="system", updated_at=ahora,
            )
        return BlockState(
            block_id=fila.block_id,
            kind=fila.kind,
            status=fila.status,
            content=fila.content_json,
            last_updated_by="system",
            updated_at=fila.updated_at or ahora,
            failure_kind=fila.failure_kind,
            last_error_message=fila.last_error_message,
            retry_attempts=fila.retry_attempts,
        )

    return WorkspaceState(
        workspace_id=workspace.id,
        template_version_id=workspace.template_version_id,
        report_profile=_perfil_de(spec),
        inputs=_artefactos_de(workspace),
        blocks={contrato.id: _bloque(contrato) for contrato in spec.blocks},
        status="drafting",
        warnings=[],
        spec=spec,
        # El modo se resuelve al ejecutar contra el suelo de la organización (#170); la
        # columna del informe es lo que se pidió, no necesariamente lo que se aplica.
        anonymization_mode=modo_anonimizacion or workspace.anonymization_mode,
    )


def _artefactos_de(workspace: HubWorkspace) -> dict[str, InputArtifact]:
    """Los ficheros ya subidos, en la forma que el grafo espera.

    Sin esto el grafo arrancaba con `inputs={}` y la extracción determinista no tenía de
    dónde extraer: los bloques de datos se quedaban en `draft` y el de IA respondía —con
    razón— que no tenía con qué redactar. Visto en vivo al subir el Excel en VER.4.
    """
    artefactos: dict[str, InputArtifact] = {}
    for slot_id, entrada in (workspace.inputs_json or {}).items():
        if not isinstance(entrada, dict):
            continue
        try:
            artefactos[slot_id] = InputArtifact.model_validate(entrada)
        except ValidationError:
            # Una entrada corrupta no puede impedir que se genere el resto del informe.
            _log.warning("Input %s del workspace %s no valida", slot_id, workspace.id)
    return artefactos


def _perfil_de(spec: ReportTemplateSpec) -> str:
    """El perfil no viaja en la spec; se deduce del contrato de UI o cae al genérico."""
    return getattr(spec, "report_profile", None) or "GENERIC_REPORT"


async def _persistir_bloques(session: Any, workspace_id: uuid.UUID, estado: Any) -> None:
    """Vuelca los bloques del estado final a `hub_workspace_blocks`, creando o actualizando.

    Se hace por `block_id` y no por clave primaria porque el identificador estable es el de
    la plantilla: una segunda ejecución del mismo workspace tiene que pisar sus bloques, no
    duplicarlos —hay un UNIQUE(workspace_id, block_id) que lo impediría con un 500—.
    """
    existentes = {
        fila.block_id: fila
        for fila in (await session.execute(
            select(HubWorkspaceBlock).where(HubWorkspaceBlock.workspace_id == workspace_id)
        )).scalars().all()
    }

    for block_id, bloque in (estado.blocks or {}).items():
        fila = existentes.get(block_id)
        if fila is None:
            fila = HubWorkspaceBlock(workspace_id=workspace_id, block_id=block_id, kind=bloque.kind)
            session.add(fila)
        fila.kind = bloque.kind
        fila.status = bloque.status
        fila.content_json = bloque.content
        fila.citations_json = (
            [c.model_dump(mode="json") for c in bloque.citations] if bloque.citations else None
        )
        fila.failure_kind = bloque.failure_kind
        fila.last_error_message = bloque.last_error_message
        fila.retry_attempts = bloque.retry_attempts


def _bloques_del(estado: Any) -> dict:
    """El grafo devuelve `WorkspaceState` o un dict, según cómo lo invoque LangGraph."""
    if isinstance(estado, dict):
        return estado
    return estado.model_dump()


async def ejecutar_borrador(
    workspace_id: uuid.UUID,
    session: Any,
    llm_service: Any,
    storage_service: Any = None,
) -> None:
    """Ejecuta el grafo sobre un workspace y persiste lo que salga.

    No lanza: cualquier fallo se convierte en `status='error'` con el motivo en el workspace.
    Corre en segundo plano, y una excepción ahí no llega a ninguna parte —ni a la respuesta,
    que ya se envió, ni a quien mira la pantalla—.
    """
    repo = WorkspaceRepo(session)
    workspace = await repo.get(workspace_id)
    if workspace is None:
        _log.warning("Workspace %s no existe: no hay nada que generar", workspace_id)
        return

    try:
        version = await ReportTemplateVersionRepo(session).get(workspace.template_version_id)
        if version is None:
            raise LookupError(f"Template version not found: {workspace.template_version_id}")

        spec = ReportTemplateSpec.model_validate(version.spec_json)
        existentes = (await session.execute(
            select(HubWorkspaceBlock).where(HubWorkspaceBlock.workspace_id == workspace_id)
        )).scalars().all()

        # MT.3 — sin organización todavía: `hub_workspaces` no la tiene hasta MT.4, y esto
        # corre dentro de la ejecución del borrador, sin actor a mano. `None` = plataforma,
        # que es el comportamiento de siempre.
        etl_llm, etl_model_name, etl_prompt = await resolver_modelo_de_etl(
            session, organizacion_id=None
        )
        grafo = construir_grafo(
            session,
            llm_service,
            storage_service,
            etl_llm=etl_llm,
            etl_model_name=etl_model_name,
            etl_system_prompt=etl_prompt,
        )
        modo = await modo_de_ejecucion(workspace, session)
        final = await grafo.ainvoke(
            _estado_inicial(workspace, spec, list(existentes), modo_anonimizacion=modo.value)
        )

        estado = WorkspaceState.model_validate(_bloques_del(final))
        await _persistir_bloques(session, workspace_id, estado)

        workspace.status = estado.status or ESTADO_EN_REVISION
        workspace.run_manifest_id = estado.run_manifest_id
        workspace.warnings_json = [a.model_dump(mode="json") for a in estado.warnings]
        await session.commit()

    except Exception as fallo:  # noqa: BLE001
        # Se traga a propósito: ver el docstring. Lo que no puede pasar es que el workspace
        # se quede en `drafting` sin que nadie sepa por qué.
        _log.exception("Falló la generación del workspace %s", workspace_id)
        await marcar_error(workspace_id, session, str(fallo))
    finally:
        _limpiar_temporales()


def _limpiar_temporales() -> None:
    """Borra los ficheros que la normalización bajó del almacén para esta ejecución.

    `//tmp` solo está permitido como buffer dentro de una tarea, y esta es la tarea: si no se
    borran, cada informe deja copias de los documentos del cliente en el disco de la máquina.
    """
    import shutil
    import tempfile
    from pathlib import Path

    from server.app.modules.redaccion.graph.nodes.file_normalization import PREFIJO_TEMPORAL

    for carpeta in Path(tempfile.gettempdir()).glob(f"{PREFIJO_TEMPORAL}*"):
        shutil.rmtree(carpeta, ignore_errors=True)


async def marcar_error(workspace_id: uuid.UUID, session: Any, motivo: str) -> None:
    """Deja el workspace en error con el motivo a la vista.

    Vive fuera del `except` porque hay fallos **anteriores** a la ejecución —el modelo que no
    se puede construir es el caso real— y también tienen que acabar aquí: si no, el workspace
    se queda en `drafting` y el motivo solo existe en el log del servidor.
    """
    await session.rollback()
    workspace = await WorkspaceRepo(session).get(workspace_id)
    if workspace is None:
        return
    workspace.status = ESTADO_ERROR
    workspace.warnings_json = list(workspace.warnings_json or []) + [
        {"kind": "run_error", "message": motivo[:500]}
    ]
    await session.commit()
