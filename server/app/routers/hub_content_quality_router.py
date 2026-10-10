"""Router de curación — auditoría de calidad de contenido web (9Q.8, re-etiquetado en CUR.1).

Deploy: edge.
Módulo: curacion — su propio docstring lo dice: «Router de curación». Los huecos que detecta alimentan la cola de revisión de contenido.

Endpoints de cola de revisión de hallazgos, informe por sitio y descarga. Los huecos de
corpus (RAG.14) y las caducidades (SYNC.2) cuelgan de un chatbot, no de un sitio, y viven en
`agents_hub` — ver la nota de frontera en `modules/curation/__init__.py`.
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    Response,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.api.deps import require_module
from server.app.core.auth.models import UserInfo
from server.app.core.auth.tenancy import (
    assert_chatbot_org_access,
    assert_site_org_access,
)
from server.app.modules.agents_hub.database.connection import get_async_session
from server.app.modules.curation.contracts import (
    InvalidFindingTransitionError,
)
from server.app.modules.curation.findings_repo import (
    ContentFindingRepo,
)
from server.app.modules.agents_hub.services.embedding_resolver import (
    resolve_embedding_service,
)
from server.app.modules.curation.report_contracts import (
    WebQualityReport,
)

router = APIRouter(tags=["hub-content-quality"])

# ──────────────────────── Job de calidad inyectable ────────────────────────

_quality_job: Any = None


def set_quality_job(job: Any) -> None:
    global _quality_job
    _quality_job = job


def get_quality_job() -> Any:
    return _quality_job


# ──────────────────────── Dependencias ────────────────────────


def get_findings_repo(
    session: AsyncSession = Depends(get_async_session),
) -> ContentFindingRepo:
    return ContentFindingRepo(session)


def get_report_builder(
    session: AsyncSession = Depends(get_async_session),
) -> Any:
    from server.app.modules.curation.report_builder import (
        WebQualityReportBuilder,
    )
    from server.app.modules.curation.site_repo import (
        WebSiteRepo,
    )

    findings_repo = ContentFindingRepo(session)
    site_repo = WebSiteRepo(session)
    return WebQualityReportBuilder(findings_repo, site_repo)


def get_report_exporter() -> Any:
    from server.app.modules.curation.report_exporter import (
        WebQualityReportExporter,
    )

    return WebQualityReportExporter()


#: La curación se concede por **módulo**, no por rol (2026-10-07). Pedía `admin` y no miraba el
#: módulo, que sólo escondía el menú: para dejar curar a alguien había que hacerle administrador
#: de su organización. La organización la siguen acotando las guardas de `tenancy`.
_de_curacion = require_module("curacion")


async def _de_curacion_y_chatbots(
    user: UserInfo = Depends(require_module("curacion")),
    _chatbots: UserInfo = Depends(require_module("chatbots")),
) -> UserInfo:
    """Lo que toca el corpus de **un chatbot** pide además `chatbots`: con sólo `curacion` no se
    eligen, ingieren ni retiran páginas del asistente de nadie."""
    return user


# ──────────────────────── Cola de revisión ────────────────────────


class _FindingOut(BaseModel):
    """Un hallazgo, tal como lo lee la cola de revisión.

    `page_id` y `signal` no son extras informativos: son lo que hace **revisable** el hallazgo
    (CUR.4). Sin `page_id` la fila no puede abrir el texto guardado de la página que acusa, y sin
    la señal un hallazgo de grupo —la serie por años, el duplicado exacto— sólo enseña una de sus
    URLs y las demás quedan invisibles. La señal se guarda en `signal_json`; el nombre de la
    columna no tiene por qué salir a la API.
    """

    id: uuid.UUID
    site_id: uuid.UUID
    finding_type: str
    severity: str
    status: str
    confidence: float
    source_url: str | None
    page_id: uuid.UUID | None = None
    #: CUR.8 — la segunda página de un hallazgo que habla de dos. «Se muestran una serie de páginas
    #: duplicadas pero solo se menciona una»: sin esto la pantalla no puede ofrecer su texto
    #: guardado, que es con lo que se juzga si el duplicado es cierto.
    related_page_id: uuid.UUID | None = None
    signal: dict[str, Any] = Field(default_factory=dict, validation_alias="signal_json")
    detected_at: Any
    reviewed_at: Any = None

    model_config = {"from_attributes": True}


class _TransitionIn(BaseModel):
    new_status: str
    resolution_note: str | None = None


@router.get(
    "/hub/sites/{site_id}/findings",
    response_model=list[_FindingOut],
    operation_id="listSiteFindings",
)
async def list_site_findings(
    site_id: uuid.UUID,
    finding_status: str | None = Query(default=None, alias="status"),
    finding_type: str | None = Query(default=None, alias="type"),
    current_user: UserInfo = Depends(_de_curacion),
    findings_repo: ContentFindingRepo = Depends(get_findings_repo),
    session: AsyncSession = Depends(get_async_session),
):
    """Lista hallazgos de un sitio (cola de revisión).

    Deploy: edge.
    """
    await assert_site_org_access(session, site_id, current_user)
    return await findings_repo.list_by_site(
        site_id,
        status=finding_status,
        finding_type=finding_type,
    )


@router.patch(
    "/hub/sites/{site_id}/findings/{finding_id}",
    response_model=_FindingOut,
    operation_id="transitionFinding",
)
async def transition_finding(
    site_id: uuid.UUID,
    finding_id: uuid.UUID,
    body: _TransitionIn,
    current_user: UserInfo = Depends(_de_curacion),
    findings_repo: ContentFindingRepo = Depends(get_findings_repo),
    session: AsyncSession = Depends(get_async_session),
):
    """Transiciona el estado de un hallazgo (confirm/dismiss/resolve).

    Deploy: edge. Devuelve 422 si la transición no es válida.
    """
    await assert_site_org_access(session, site_id, current_user)
    hallazgo = await findings_repo.get(finding_id)
    if hallazgo is None or hallazgo.site_id != site_id:
        # #242: el sitio de la ruta pasaba el control y el hallazgo podía ser de otro.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Hallazgo no encontrado en este sitio")
    try:
        updated = await findings_repo.transition(
            finding_id=finding_id,
            new_status=body.new_status,
            reviewed_by=uuid.UUID(current_user.user_id) if _is_uuid(current_user.user_id) else uuid.uuid4(),
            resolution_note=body.resolution_note,
        )
    except InvalidFindingTransitionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    return updated


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except ValueError:
        return False


# ──────────────────────── Informe ────────────────────────


@router.get(
    "/hub/sites/{site_id}/report",
    response_model=WebQualityReport,
    operation_id="getSiteQualityReport",
)
async def get_site_report(
    site_id: uuid.UUID,
    current_user: UserInfo = Depends(_de_curacion),
    builder: Any = Depends(get_report_builder),
    session: AsyncSession = Depends(get_async_session),
):
    """Genera y devuelve el informe de auditoría de calidad de un sitio.

    Deploy: edge.
    """
    await assert_site_org_access(session, site_id, current_user)
    return await builder.build(site_id)


@router.get(
    "/hub/sites/{site_id}/report/export",
    operation_id="exportSiteQualityReport",
)
async def export_site_report(
    site_id: uuid.UUID,
    report_format: str = Query(default="docx", alias="format"),
    current_user: UserInfo = Depends(_de_curacion),
    builder: Any = Depends(get_report_builder),
    exporter: Any = Depends(get_report_exporter),
    session: AsyncSession = Depends(get_async_session),
):
    """Descarga el informe como DOCX o PDF.

    Deploy: edge. Si LibreOffice no está disponible, PDF devuelve DOCX
    (Content-Type: application/vnd.openxmlformats…).
    """
    await assert_site_org_access(session, site_id, current_user)
    report = await builder.build(site_id)

    DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    if report_format.lower() == "pdf":
        data = await exporter.to_pdf(report)
        # `to_pdf` cae a DOCX cuando no hay LibreOffice, y hasta aquí la respuesta seguía
        # diciendo `application/pdf` con extensión `.pdf`: quien lo descargaba se llevaba un
        # ZIP que Adobe no abre y que no dice por qué. El fallback tiene que verse.
        es_pdf = data[:4] == b"%PDF"
        media_type = "application/pdf" if es_pdf else DOCX
        filename = f"informe_calidad_{site_id}." + ("pdf" if es_pdf else "docx")
    else:
        data = await exporter.to_docx(report)
        media_type = DOCX
        filename = f"informe_calidad_{site_id}.docx"

    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ──────────────────────── Disparo de análisis ────────────────────────


@router.post(
    "/hub/sites/{site_id}/analyze",
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="analyzeSite",
)
async def analyze_site(
    site_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    current_user: UserInfo = Depends(_de_curacion),
    quality_job: Any = Depends(get_quality_job),
    session: AsyncSession = Depends(get_async_session),
):
    """Dispara un análisis de calidad completo del sitio en background.

    Deploy: edge. Responde 202 Accepted inmediatamente.
    """
    await assert_site_org_access(session, site_id, current_user)
    if quality_job is not None:
        background_tasks.add_task(quality_job.run_for_site, site_id)
    return {"status": "queued", "site_id": str(site_id)}


class GapAnalysisOut(BaseModel):
    chatbot_id: uuid.UUID
    gaps_found: int
    window_days: int


@router.post(
    "/hub/quality/gaps/analyze",
    response_model=GapAnalysisOut,
    operation_id="analyzeContentGaps",
)
async def analyze_content_gaps(
    chatbot_id: uuid.UUID = Query(..., description="Chatbot cuyas conversaciones se leen"),
    dias: int = Query(30, ge=1, le=365),
    min_cluster: int = Query(3, ge=2, le=100),
    current_user: UserInfo = Depends(_de_curacion_y_chatbots),
    session: AsyncSession = Depends(get_async_session),
):
    """Busca huecos de corpus en las conversaciones que salieron mal (RAG.14).

    Deploy: edge. **Síncrono y no en background**, al revés que el análisis de sitio: aquí
    el trabajo es embeber unas decenas de consultas cortas, no rastrear un sitio entero, y
    quien lo lanza quiere ver el número. Devolverlo en 202 obligaría a inventar un job para
    consultar algo que ya se sabe al terminar.
    """
    from server.app.modules.agents_hub.ingestion.gap_detector import (
        analizar_huecos,
    )

    # Los huecos se calculan LEYENDO las conversaciones del chatbot, que son preguntas de
    # ciudadanos: sin esta comprobación, cualquier admin las agrupaba y las leía.
    await assert_chatbot_org_access(session, chatbot_id, current_user)
    servicio = await resolve_embedding_service(session, chatbot_id)
    encontrados = await analizar_huecos(
        session, chatbot_id, servicio, dias=dias, min_cluster_size=min_cluster
    )
    await session.commit()
    return GapAnalysisOut(
        chatbot_id=chatbot_id, gaps_found=encontrados, window_days=dias
    )


class StaleAnalysisOut(BaseModel):
    chatbot_id: uuid.UUID
    stale_found: int


@router.post(
    "/hub/quality/stale/analyze",
    response_model=StaleAnalysisOut,
    operation_id="analyzeStaleDocuments",
)
async def analyze_stale_documents(
    chatbot_id: uuid.UUID = Query(..., description="Chatbot cuyo corpus se revisa"),
    current_user: UserInfo = Depends(_de_curacion_y_chatbots),
    session: AsyncSession = Depends(get_async_session),
):
    """Busca documentos con la revisión prevista vencida (SYNC.2).

    Deploy: edge. Síncrono: es una comparación de fechas en SQL, sin embeddings ni modelo,
    así que devolver un 202 y un job obligaría a consultar algo que ya se sabe al terminar.
    """
    from server.app.modules.curation.staleness_detector import (
        analizar_caducidad,
    )

    await assert_chatbot_org_access(session, chatbot_id, current_user)
    encontrados = await analizar_caducidad(session, chatbot_id)
    await session.commit()
    return StaleAnalysisOut(chatbot_id=chatbot_id, stale_found=encontrados)


@router.get(
    "/hub/quality/stale",
    response_model=list[dict],
    operation_id="listStaleDocuments",
)
async def list_stale_documents(
    chatbot_id: uuid.UUID = Query(...),
    status_filter: str | None = Query(None, alias="status"),
    current_user: UserInfo = Depends(_de_curacion_y_chatbots),
    session: AsyncSession = Depends(get_async_session),
):
    """Cola de revisión de las caducidades de un chatbot (SYNC.2).

    Tercer tipo de hallazgo que cuelga de un chatbot y no de un sitio, junto a los huecos de
    RAG.14 y las retiradas de SYNC.1. Sin este endpoint, el detector escribiría hallazgos
    que no vería nadie, que es la forma más cara de no hacer nada.
    """
    from server.app.modules.curation.staleness_detector import (
        listar_caducados,
    )

    await assert_chatbot_org_access(session, chatbot_id, current_user)
    filas = await listar_caducados(session, chatbot_id, status=status_filter)
    return [
        {
            "id": str(f.id),
            "chatbot_id": str(f.chatbot_id),
            "severity": f.severity,
            "status": f.status,
            "detected_at": f.detected_at.isoformat(),
            "source_url": f.source_url,
            "id_publicacio": (f.signal_json or {}).get("id_publicacio"),
            "title": (f.signal_json or {}).get("title"),
            "data_revisio_prevista": (f.signal_json or {}).get("data_revisio_prevista"),
            "darrera_actualitzacio": (f.signal_json or {}).get("darrera_actualitzacio"),
            "dies_de_retard": (f.signal_json or {}).get("dies_de_retard", 0),
        }
        for f in filas
    ]


@router.get(
    "/hub/quality/gaps",
    response_model=list[dict],
    operation_id="listContentGaps",
)
async def list_content_gaps(
    chatbot_id: uuid.UUID = Query(...),
    status_filter: str | None = Query(None, alias="status"),
    current_user: UserInfo = Depends(_de_curacion_y_chatbots),
    session: AsyncSession = Depends(get_async_session),
):
    """Cola de revisión de los huecos de un chatbot (RAG.14).

    Endpoint aparte de `/hub/sites/{id}/findings` porque el sujeto es otro: aquel filtra por
    sitio y un hueco no tiene sitio. Sin esto, los hallazgos se escribirían y no los vería
    nadie, que es la forma más cara de no hacer nada.
    """
    from sqlalchemy import select

    from server.app.modules.agents_hub.database.operational_models import HubContentFinding

    await assert_chatbot_org_access(session, chatbot_id, current_user)
    consulta = (
        select(HubContentFinding)
        .where(HubContentFinding.chatbot_id == chatbot_id)
        .where(HubContentFinding.finding_type == "content_gap")
        .order_by(HubContentFinding.detected_at.desc())
    )
    if status_filter:
        consulta = consulta.where(HubContentFinding.status == status_filter)

    filas = (await session.execute(consulta)).scalars().all()
    return [
        {
            "id": str(f.id),
            "chatbot_id": str(f.chatbot_id),
            "severity": f.severity,
            "status": f.status,
            "detected_at": f.detected_at.isoformat(),
            "count": (f.signal_json or {}).get("count", 0),
            "queries": (f.signal_json or {}).get("queries", []),
            "top_terms": (f.signal_json or {}).get("top_terms", []),
            "first_seen": (f.signal_json or {}).get("first_seen"),
            "last_seen": (f.signal_json or {}).get("last_seen"),
        }
        for f in filas
    ]
