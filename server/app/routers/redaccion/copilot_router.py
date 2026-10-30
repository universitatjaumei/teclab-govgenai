"""Router del Copilot del DrawerHub.

Deploy: edge — el copilot consume LLM + embeddings + factories del módulo redacción.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.api.deps import get_current_user, get_session, require_module
from server.app.core.auth.models import UserInfo
from server.app.core.auth.tenancy import organizacion_unica_de
from server.app.modules.agents_hub.services.config_provider import LocalConfigProvider
from server.app.modules.agents_hub.services.embedding_resolver import (
    resolve_embedding_service,
)
from server.app.modules.agents_hub.services.model_factory import get_model_for_tier
from server.app.modules.redaccion.services.copilot import (
    CopilotAnswer,
    CopilotAskRequest,
    CopilotService,
    CopilotTranslateRequest,
    CopilotTranslateResponse,
)
from server.app.modules.redaccion.services.copilot.copilot_service import ElModeloNoResponde
from server.app.modules.redaccion.services.copilot.docs_retriever import DocsRetriever
from server.app.routers.redaccion._actor import nombre_del_modelo


_log = logging.getLogger(__name__)

router = APIRouter(prefix="/redaccion/copilot", tags=["redaccion-copilot"],
    # INF.7 — el modulo se exige a nivel de router: asi no se puede olvidar en un
    # endpoint nuevo del mismo fichero, que es como se abrieron los agujeros que SEC.8.1
    # tuvo que cerrar uno a uno.
    dependencies=[Depends(require_module("informes"))],
)

#: El **retriever** se conserva entre peticiones, no el servicio entero: es donde vive el
#: índice, y uno nuevo por petición volvería a embeber los ~387 fragmentos de `docs/` en cada
#: pregunta. El servicio sí se construye cada vez, para que cambiar el modelo en el panel tenga
#: efecto sin reiniciar. El índice es de la documentación del proyecto, que no cambia sin un
#: despliegue; si algún día hace falta invalidarlo en caliente, será otro prompt.
_retriever: DocsRetriever | None = None


async def get_copilot_service(
    session: AsyncSession = Depends(get_session),
    current_user: UserInfo = Depends(get_current_user),
) -> CopilotService:
    """El copiloto con su modelo y su servicio de embeddings (PRO.6).

    Era un stub que devolvía 503 siempre, así que el panel no tenía a quién preguntar.

    El 503 dice **cuál de los dos falta**: un modelo y un servicio de embeddings son dos
    configuraciones distintas, en dos pantallas distintas, y «copilot service not configured»
    obliga a mirar el log del servidor para saber cuál mirar.
    """
    global _retriever

    try:
        # MT.3 — el modelo de la organización de quien pregunta.
        modelo = await get_model_for_tier(
            1,
            LocalConfigProvider(session),
            organizacion_id=organizacion_unica_de(current_user),
        )
    except Exception as fallo:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "El copiloto no tiene modelo de conversación configurado (nivel 1). "
                f"Asígnale uno en Modelos IA ({fallo})."
            ),
        ) from fallo

    if _retriever is None:
        try:
            embeddings = await resolve_embedding_service(session)
        except Exception as fallo:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "El copiloto no tiene servicio de embeddings: sin él no puede buscar en "
                    f"la documentación. Configúralo en Modelos IA ({fallo})."
                ),
            ) from fallo
        _retriever = DocsRetriever(embedding_service=embeddings)

    return CopilotService(llm=modelo, retriever=_retriever)


@router.post("/ask", response_model=CopilotAnswer)
async def ask_copilot(
    body: CopilotAskRequest,
    user: UserInfo = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    service: CopilotService = Depends(get_copilot_service),
) -> CopilotAnswer:
    """RAG sobre la documentación interna del módulo activo + síntesis LLM con citas.

    INF.10 — si la pregunta llega con un informe abierto, el copiloto recibe **su estado**:
    apartados, en qué situación está cada uno, qué acciones caben sobre él y qué falta. Sin eso
    respondía solo con la documentación del proyecto, y «no sé dónde aprobar los bloques» no
    tenía respuesta posible. Los avisos van anonimizados; el texto que escribió la IA no va.
    """
    contexto = None
    if body.workspace_id is not None:
        from server.app.modules.redaccion.database.repos import (
            ReportTemplateVersionRepo,
            WorkspaceBlockRepo,
            WorkspaceRepo,
        )
        from server.app.modules.redaccion.services.contexto_del_informe import (
            contexto_del_informe,
        )
        from server.app.routers.redaccion._actor import es_propietario

        workspace = await WorkspaceRepo(session).get(body.workspace_id)
        # El contexto de un informe ajeno no se filtra por una pregunta al copiloto: es la
        # misma comprobación que hace el resto del módulo desde SEC.8.1.
        if workspace is not None and es_propietario(user.user_id, workspace.owner_id):
            contexto = await contexto_del_informe(
                workspace_repo=WorkspaceRepo(session),
                block_repo=WorkspaceBlockRepo(session),
                template_version_repo=ReportTemplateVersionRepo(session),
                workspace_id=body.workspace_id,
            )

    try:
        return await service.answer(
            question=body.question,
            module=body.module,
            top_k=body.top_k,
            contexto_del_informe=contexto,
        )
    except ElModeloNoResponde as fallo:
        # #344 — era un 500 sin explicación. Lo mismo que el 503 de arriba: decir qué mirar.
        # El motivo del proveedor va al registro y no a la pantalla (revisión de la PR #347): lo ve
        # cualquiera con el módulo de Informes, y un SDK puede meter ahí la URL con su clave o la
        # dirección interna del modelo.
        modelo = nombre_del_modelo(fallo.modelo)
        _log.warning("El modelo %s no ha respondido al Copilot: %s", modelo, fallo.motivo)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                f"El modelo «{modelo}» no ha respondido. Si persiste, quien administra la "
                "plataforma tiene que revisar el modelo del nivel 1 en Modelos IA."
            ),
        ) from fallo


@router.post("/translate", response_model=CopilotTranslateResponse)
async def translate_copilot(
    body: CopilotTranslateRequest,
    user: UserInfo = Depends(get_current_user),  # noqa: ARG001 — autoriza: se pide por su efecto
    service: CopilotService = Depends(get_copilot_service),
) -> CopilotTranslateResponse:
    """Traduce instrucción NL a configuración estructurada (chart / ETL / script)."""
    return await service.translate_nl_to_config(
        instruction=body.instruction,
        target_kind=body.target_kind,
        sample_schema=body.sample_schema,
    )
