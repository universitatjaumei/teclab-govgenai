"""Router de curación — sitios rastreados, selecciones y candidatas (9Q.7, re-etiquetado en CUR.1).

Deploy: edge.
Módulo: curacion — los sitios rastreados son el módulo de curación.

Aquí la tenencia y los códigos de estado; lo que lee y escribe la base, en
`modules/curation/sitios.py` (#274).
"""
from __future__ import annotations

import uuid
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.api.deps import require_module, get_quality_job
from server.app.core.auth.models import UserInfo
from server.app.core.auth.tenancy import (
    assert_chatbot_org_access,
    assert_org_access,
    assert_site_org_access,
    organizacion_unica_de,
)
from server.app.api.deps import get_session
from server.app.modules.curation import sitios
from server.app.modules.curation.selection_contracts import (
    CandidatePageView,
    CrawlConfig,
    CrawlRunView,
    PageContentView,
    PageView,
    PaginaDePasadas,
    PatternTestRequest,
    PatternTestView,
    ReconnaissanceRequest,
    ReconnaissanceView,
    SectionCreate,
    SectionPatch,
    SectionView,
    SelectionCreate,
    SelectionView,
    SiteCreate,
    SitePatch,
    SiteView,
)
from server.app.modules.curation.site_repo import CorpusSelectionRepo, CrawledPageRepo

router = APIRouter(tags=["hub-sites"])

# ──────────────────────── Dependencia de CorpusSelectionService ────────────────────────


async def get_selection_service(
    session: AsyncSession = Depends(get_session),
) -> Any:
    """Crea CorpusSelectionService con dependencias mínimas (sin embedding, sin watcher real).

    Para operaciones que necesiten watcher real (ingest_page), el endpoint
    construye el watcher directamente.
    """
    from server.app.modules.curation.selection_service import (
        CorpusSelectionService,
    )

    page_repo = CrawledPageRepo(session)
    sel_repo = CorpusSelectionRepo(session)
    return CorpusSelectionService(session, page_repo, sel_repo, watcher=None)


async def _servicio_que_puede_ingerir(session: AsyncSession, chatbot_id: uuid.UUID) -> Any:
    """El servicio de selección **con watcher**, que es el único que puede ingerir.

    El embedding lo resuelve la cascada del chatbot: ingerir con otro modelo del que usa su
    corpus dejaría vectores que no se pueden comparar con los que ya hay.
    """
    from server.app.modules.agents_hub.ingestion.watcher import IngestionWatcher
    from server.app.modules.agents_hub.services.embedding_resolver import (
        resolve_embedding_service,
    )
    from server.app.modules.curation.selection_service import CorpusSelectionService

    watcher = IngestionWatcher(
        session=session,
        embedding_service=await resolve_embedding_service(session, chatbot_id),
    )
    return CorpusSelectionService(
        session, CrawledPageRepo(session), CorpusSelectionRepo(session), watcher=watcher
    )


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


# ──────────────────────── Reconocimiento previo (CUR.6) ────────────────────────


def get_servicio_de_reconocimiento() -> Any:
    """El servicio que recorre un sitio sin guardar nada."""
    from server.app.modules.curation.reconocimiento import ReconocimientoDeSitio

    return ReconocimientoDeSitio()


@router.post(
    "/hub/site-reconnaissance",
    response_model=ReconnaissanceView,
    operation_id="reconnoiterSite",
    responses={200: {"content": {"text/csv": {}}, "description": "El sitemap como CSV"}},
)
async def reconnoiter_site(
    body: ReconnaissanceRequest,
    current_user: UserInfo = Depends(_de_curacion),  # noqa: ARG001 — autoriza: se pide por su efecto
    servicio: Any = Depends(get_servicio_de_reconocimiento),
):
    """Cuántas páginas tiene un apartado, y cuánto costaría rastrearlo (CUR.6).

    Deploy: edge.

    No toca la base y no necesita que el sitio exista: la pregunta se hace **antes** de darlo de
    alta, y hasta ahora la única forma de responderla era lanzar el rastreo de verdad y esperar. Del
    usuario: «así se podría valorar la extensión del sitio y si conviene hacerlo todo de golpe o por
    subapartados».

    No hay guarda de organización porque no hay sitio al que aplicarla; lo que se comprueba es el
    rol, porque esto hace que el servidor pida páginas —la misma potestad que crear un sitio—.
    """
    informe = await servicio.reconocer(
        body.root_url,
        max_depth=body.crawl_depth,
        max_pages=body.max_pages,
        respect_robots=body.respect_robots,
        url_regex_filter=body.url_regex_filter,
        # La pausa del sondeo la fija el servicio (va con prisa); ésta es la del rastreo real, que
        # es la que hace que la estimación signifique algo.
        pausa_del_rastreo=body.delay_seconds,
    )

    if body.formato == "csv":
        from server.app.modules.curation.reconocimiento import csv_de_apartados

        cuerpo = csv_de_apartados(list(informe.urls), informe.root_url)
        nombre = f"reconocimiento_{urlparse(informe.root_url).netloc}.csv"
        return Response(
            content=cuerpo,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
        )

    return informe


# ──────────────────────── CRUD de sitios ────────────────────────


@router.post(
    "/hub/sites",
    response_model=SiteView,
    status_code=status.HTTP_201_CREATED,
    operation_id="createSite",
)
async def create_site(
    body: SiteCreate,
    organizacion_id: uuid.UUID | None = Query(default=None),
    current_user: UserInfo = Depends(_de_curacion),
    session: AsyncSession = Depends(get_session),
):
    """Crea un nuevo sitio rastreado.

    Deploy: edge. organizacion_id se provee como query param; no va en el body.

    SEC.8.1: el parámetro lo elige quien llama, así que se valida contra el token. Sin
    organización el sitio quedaría fuera de toda cascada —y de todo listado acotado—, de
    modo que crear uno así queda reservado al superadministrador, igual que los temas de
    plataforma.

    **Sin parámetro, la organización de quien llama si pertenece a una sola** (2026-10-07): quien
    cura con rol `user` no puede leer la lista de organizaciones —es de administración—, así que
    su pantalla no tiene qué mandar, y tampoco hay nada que elegir.
    """
    if organizacion_id is None and not current_user.is_superadmin:
        organizacion_id = organizacion_unica_de(current_user)
    if organizacion_id is None:
        if not current_user.is_superadmin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Indica la organización del sitio",
            )
    else:
        assert_org_access(current_user, organizacion_id)

    return await sitios.crear_sitio(
        session,
        organizacion_id=organizacion_id,
        name=body.name,
        root_url=body.root_url,
        sitemap_url=body.sitemap_url,
        crawl_interval_hours=body.crawl_interval_hours,
        audit_semantic_scope=body.audit_semantic_scope,
        # RAS.5 — la configuración del rastreo se podía leer pero no fijar, así que el filtro por
        # apartado (`url_regex_filter`) era inalcanzable desde la interfaz. Sin ella se guardan
        # los defectos conservadores de RAS.1, no un rastreo sin límites.
        config_json=(body.crawl_config or CrawlConfig()).model_dump(),
    )


@router.get(
    "/hub/sites",
    response_model=list[SiteView],
    operation_id="listSites",
)
async def list_sites(
    organizacion_id: uuid.UUID | None = Query(default=None),
    current_user: UserInfo = Depends(_de_curacion),
    session: AsyncSession = Depends(get_session),
):
    """Lista sitios, opcionalmente filtrados por organizacion_id.

    Deploy: edge. SEC.8.1: el filtro por organización dejó de ser opcional. Antes acotaba
    solo si el cliente pasaba el parámetro —o sea, el filtro lo elegía quien preguntaba— y
    sin parámetro devolvía los sitios de todas las administraciones.
    """
    return await sitios.listar_sitios(session, current_user, organizacion_id)


@router.patch(
    "/hub/sites/{site_id}",
    response_model=SiteView,
    operation_id="patchSite",
)
async def patch_site(
    site_id: uuid.UUID,
    body: SitePatch,
    current_user: UserInfo = Depends(_de_curacion),
    session: AsyncSession = Depends(get_session),
):
    """Actualiza campos de un sitio.

    Deploy: edge.
    """
    await assert_site_org_access(session, site_id, current_user)
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    # La configuración del rastreo se guarda en `config_json`, que es como la lee el spider.
    if "crawl_config" in updates:
        updates["config_json"] = updates.pop("crawl_config")
    site = await sitios.actualizar_sitio(session, site_id, updates)
    if site is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Site not found")
    return site


@router.delete(
    "/hub/sites/{site_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="deleteSite",
)
async def delete_site(
    site_id: uuid.UUID,
    current_user: UserInfo = Depends(_de_curacion),
    session: AsyncSession = Depends(get_session),
):
    """Elimina un sitio y todas sus páginas (CASCADE).

    Deploy: edge.
    """
    await assert_site_org_access(session, site_id, current_user)
    await sitios.borrar_sitio(session, site_id)


# ──────────────────────── Crawl trigger ────────────────────────


@router.post(
    "/hub/sites/{site_id}/crawl",
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="triggerSiteCrawl",
)
async def trigger_crawl(
    site_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    current_user: UserInfo = Depends(_de_curacion),
    session: AsyncSession = Depends(get_session),
    quality_job: Any = Depends(get_quality_job),
):
    """Dispara un crawl + análisis de calidad en background.

    Deploy: edge. Responde 202 Accepted inmediatamente.
    """
    await assert_site_org_access(session, site_id, current_user)

    if quality_job is not None:
        background_tasks.add_task(quality_job.run_for_site, site_id)

    return {"status": "queued", "site_id": str(site_id)}


# ──────────────────────── Páginas del sitio ────────────────────────


@router.get(
    "/hub/sites/{site_id}/pages",
    response_model=list[PageView],
    operation_id="listSitePages",
)
async def list_site_pages(
    site_id: uuid.UUID,
    page_status: str | None = Query(default=None, alias="status"),
    propuestas: bool = Query(default=False),
    current_user: UserInfo = Depends(_de_curacion),
    session: AsyncSession = Depends(get_session),
):
    """Lista las páginas rastreadas de un sitio, opcionalmente filtradas por status.

    Deploy: edge. Con `propuestas`, sólo las propuestas para un asistente (2026-10-08).
    """
    await assert_site_org_access(session, site_id, current_user)
    return await sitios.paginas(session, site_id, page_status, propuestas)


@router.put(
    "/hub/sites/{site_id}/pages/{page_id}/propuesta",
    response_model=PageView,
    operation_id="proponerPagina",
)
async def proponer_pagina(
    site_id: uuid.UUID,
    page_id: uuid.UUID,
    current_user: UserInfo = Depends(_de_curacion),
    session: AsyncSession = Depends(get_session),
):
    """Propone la página para un asistente (2026-10-08).

    Basta el módulo de curación: proponer no publica nada. Quien crea el asistente —con el
    módulo `chatbots`— decide en Publicación. Volver a proponer no cambia quién lo hizo primero.
    """
    await assert_site_org_access(session, site_id, current_user)
    return await sitios.marcar_propuesta(session, site_id, page_id, current_user.email)


@router.delete(
    "/hub/sites/{site_id}/pages/{page_id}/propuesta",
    response_model=PageView,
    operation_id="retirarPropuestaDePagina",
)
async def retirar_propuesta(
    site_id: uuid.UUID,
    page_id: uuid.UUID,
    current_user: UserInfo = Depends(_de_curacion),
    session: AsyncSession = Depends(get_session),
):
    """Quita la propuesta. No toca el corpus: si ya se publicó, eso se retira en Publicación."""
    await assert_site_org_access(session, site_id, current_user)
    return await sitios.marcar_propuesta(session, site_id, page_id, None)


# ──────────────────────── Secciones del sitio (DIN.3) ────────────────────────
#
# El apartado como dato, parametrizable **desde la curación**: es el motivo del bloque DIN.
# Hasta aquí «añadir el apartado de becas» exigía crear un sitio entero con su
# `url_regex_filter`, o sea acceso a la administración de sitios; con esto es un formulario.


def _vista_de_seccion(site: Any, seccion: Any) -> SectionView:
    """La sección con su cadencia resuelta y la bandera de si la hereda.

    Se sirven las dos cifras a propósito: sin la bandera, cambiar la cadencia del sitio parecería
    no hacer nada en las secciones que la heredan.
    """
    from server.app.modules.curation.secciones import parametros_efectivos

    efectivos = parametros_efectivos(site, seccion)
    return SectionView(
        id=seccion.id,
        site_id=seccion.site_id,
        name=seccion.name,
        pattern=seccion.pattern,
        pattern_kind=seccion.pattern_kind,
        crawl_interval_hours=seccion.crawl_interval_hours,
        crawl_interval_hours_effective=efectivos.crawl_interval_hours,
        crawl_interval_inherited=seccion.crawl_interval_hours is None,
        mode=seccion.mode,
        criteria_json=seccion.criteria_json,
        owner=seccion.owner,
        last_crawled_at=seccion.last_crawled_at,
        is_active=seccion.is_active,
        created_at=seccion.created_at,
    )


@router.get(
    "/hub/sites/{site_id}/sections",
    response_model=list[SectionView],
    operation_id="listSiteSections",
)
async def list_site_sections(
    site_id: uuid.UUID,
    current_user: UserInfo = Depends(_de_curacion),
    session: AsyncSession = Depends(get_session),
):
    """Las secciones de un sitio, con su cadencia efectiva (DIN.3).

    Deploy: edge. La tenencia llega por el sitio, como en el resto del módulo.
    """
    site = await assert_site_org_access(session, site_id, current_user)
    return [_vista_de_seccion(site, s) for s in await sitios.secciones(session, site_id)]


@router.post(
    "/hub/sites/{site_id}/sections",
    response_model=SectionView,
    status_code=status.HTTP_201_CREATED,
    operation_id="createSiteSection",
)
async def create_site_section(
    site_id: uuid.UUID,
    body: SectionCreate,
    current_user: UserInfo = Depends(_de_curacion),
    session: AsyncSession = Depends(get_session),
):
    """Da de alta una sección del sitio.

    Deploy: edge. `mode` nace en `manual` a propósito: la primera pasada de un apartado la
    revisa una persona, y sólo después se automatiza («curación una vez, automatización
    después»).
    """
    site = await assert_site_org_access(session, site_id, current_user)
    seccion = await sitios.crear_seccion(
        session,
        site_id,
        name=body.name,
        pattern=body.pattern,
        pattern_kind=body.pattern_kind,
        crawl_interval_hours=body.crawl_interval_hours,
        mode=body.mode,
        criteria_json=body.criteria_json,
        owner=body.owner,
    )
    return _vista_de_seccion(site, seccion)


@router.patch(
    "/hub/sites/{site_id}/sections/{section_id}",
    response_model=SectionView,
    operation_id="patchSiteSection",
)
async def patch_site_section(
    site_id: uuid.UUID,
    section_id: uuid.UUID,
    body: SectionPatch,
    current_user: UserInfo = Depends(_de_curacion),
    session: AsyncSession = Depends(get_session),
):
    """Edita una sección, la activa o la desactiva.

    Deploy: edge. `heredar_cadencia` es lo que devuelve la cadencia al valor del sitio: un nulo
    a secas significaría «no lo toques», y colapsar los dos dejaría imposible volver a heredar.
    """
    site = await assert_site_org_access(session, site_id, current_user)
    await sitios.seccion_de_este_sitio(session, site_id, section_id)

    campos = body.model_dump(exclude_none=True, exclude={"heredar_cadencia"})
    if body.heredar_cadencia:
        campos["crawl_interval_hours"] = None
    seccion = await sitios.actualizar_seccion(session, section_id, campos)
    return _vista_de_seccion(site, seccion)


@router.delete(
    "/hub/sites/{site_id}/sections/{section_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="deleteSiteSection",
)
async def delete_site_section(
    site_id: uuid.UUID,
    section_id: uuid.UUID,
    current_user: UserInfo = Depends(_de_curacion),
    session: AsyncSession = Depends(get_session),
):
    """Borra una sección, **sólo si no tiene selecciones colgando**.

    Deploy: edge. Con `section_id` puesto el patrón efectivo lo manda la sección: borrarla
    dejaría la selección apuntando a un ámbito que no existe, y con la auto-retirada de DIN.4
    detrás eso no es un dato huérfano, es corpus que se vacía. Si las tiene, se desactiva — y el
    mensaje lo dice.
    """
    await assert_site_org_access(session, site_id, current_user)
    await sitios.seccion_de_este_sitio(session, site_id, section_id)
    await sitios.borrar_seccion(session, section_id)


@router.get(
    "/hub/sites/{site_id}/runs",
    response_model=PaginaDePasadas,
    operation_id="listSiteRuns",
)
async def list_site_runs(
    site_id: uuid.UUID,
    section_id: uuid.UUID | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    current_user: UserInfo = Depends(_de_curacion),
    session: AsyncSession = Depends(get_session),
):
    """El diario de las pasadas de un sitio, filtrable por sección (DIN.6).

    Deploy: edge. El `summary` del job se calculaba, se devolvía y se perdía; con DIN.4 y DIN.5
    encima, esto es el único sitio donde se puede ver que la salvaguarda paró una retirada o que
    la puerta de calidad dejó fuera cinco páginas.

    **Orden con desempate por `id`** (DET.1): dos pasadas pueden compartir `started_at` al
    microsegundo, y sin desempate paginar devuelve una fila en dos páginas y otra en ninguna.
    """
    await assert_site_org_access(session, site_id, current_user)
    total, filas = await sitios.pasadas(session, site_id, section_id, page, size)
    return PaginaDePasadas(
        total=total, items=[CrawlRunView.model_validate(f) for f in filas]
    )


@router.post(
    "/hub/sites/{site_id}/sections/test-pattern",
    response_model=PatternTestView,
    operation_id="testSectionPattern",
)
async def test_section_pattern(
    site_id: uuid.UUID,
    body: PatternTestRequest,
    current_user: UserInfo = Depends(_de_curacion),
    session: AsyncSession = Depends(get_session),
):
    """Cuántas páginas **ya rastreadas** casarían este patrón, y una muestra (DIN.3).

    Deploy: edge. No escribe nada. Es lo que evita el regex que compila y no casa nada: hoy eso
    sólo se descubre cuando la pasada siguiente no ingiere nada, y como la ingesta automática es
    silenciosa, se descubre tarde.
    """
    await assert_site_org_access(session, site_id, current_user)

    from server.app.modules.curation.secciones import casa_patron

    # El patrón se evalúa en Python, así que las URL hay que traerlas; los objetos enteros no.
    urls = await sitios.urls_del_sitio(session, site_id)

    casan = [u for u in urls if casa_patron(body.pattern_kind, body.pattern, u)]
    return PatternTestView(matched=len(casan), total=len(urls), sample=casan[:10])


# ──────────────────────── CRUD de selecciones ────────────────────────


@router.post(
    "/hub/chatbots/{chatbot_id}/selections",
    response_model=SelectionView,
    status_code=status.HTTP_201_CREATED,
    operation_id="createSelection",
)
async def create_selection(
    chatbot_id: uuid.UUID,
    body: SelectionCreate,
    current_user: UserInfo = Depends(_de_curacion_y_chatbots),
    session: AsyncSession = Depends(get_session),
):
    """Crea una regla de selección de corpus para un chatbot.

    Deploy: edge.
    """
    await assert_chatbot_org_access(session, chatbot_id, current_user)
    await assert_site_org_access(session, body.site_id, current_user)
    # DIN.3 — apuntar a una sección de OTRO sitio haría que el patrón efectivo no tuviera nada
    # que ver con las páginas de esta selección: se comprueba aquí, no al rastrear.
    if body.section_id is not None:
        await sitios.seccion_de_este_sitio(session, body.site_id, body.section_id)
    return await sitios.crear_seleccion(
        session,
        chatbot_id=chatbot_id,
        site_id=body.site_id,
        rule_type=body.rule_type,
        rule_value=body.rule_value,
        auto_ingest_new=body.auto_ingest_new,
        section_id=body.section_id,
    )


@router.get(
    "/hub/chatbots/{chatbot_id}/selections",
    response_model=list[SelectionView],
    operation_id="listSelections",
)
async def list_selections(
    chatbot_id: uuid.UUID,
    current_user: UserInfo = Depends(_de_curacion_y_chatbots),
    session: AsyncSession = Depends(get_session),
):
    """Lista las selecciones de corpus de un chatbot.

    Deploy: edge.
    """
    await assert_chatbot_org_access(session, chatbot_id, current_user)
    return await sitios.selecciones(session, chatbot_id)


@router.delete(
    "/hub/chatbots/{chatbot_id}/selections/{selection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="deleteSelection",
)
async def delete_selection(
    chatbot_id: uuid.UUID,
    selection_id: uuid.UUID,
    current_user: UserInfo = Depends(_de_curacion_y_chatbots),
    session: AsyncSession = Depends(get_session),
):
    """Elimina una selección de corpus.

    Deploy: edge.
    """
    await assert_chatbot_org_access(session, chatbot_id, current_user)
    await sitios.borrar_seleccion(session, chatbot_id, selection_id)


@router.get(
    "/hub/pages/{page_id}/content",
    response_model=PageContentView,
    operation_id="getPageContent",
)
async def get_page_content(
    page_id: uuid.UUID,
    current_user: UserInfo = Depends(_de_curacion),
    session: AsyncSession = Depends(get_session),
):
    """El texto guardado de una página rastreada: lo que iría al corpus (CUR.4).

    Deploy: edge. El informe de calidad acusaba y no dejaba comprobar —«hay que copiar y pegar»—, y
    no había ninguna pantalla que mostrara el contenido de una página. Hace falta para juzgar si un
    hallazgo es cierto, para decidir si la página merece publicarse y, desde CUR.3, para comprobar
    que el recorte de plantilla no se ha llevado contenido por delante.
    """
    pagina = await sitios.pagina_o_404(session, page_id)

    # El texto de una página es contenido del cliente, así que la guarda de organización va aquí
    # igual que en el resto del módulo.
    await assert_site_org_access(session, pagina.site_id, current_user)

    return PageContentView(
        id=pagina.id,
        url=pagina.url,
        title=pagina.title,
        status=pagina.status,
        # Vacío y no nulo: una página en error no tiene texto, y eso hay que poder verlo sin
        # adivinar si falta el dato o falta el contenido.
        content=pagina.markdown_content or "",
        token_count=pagina.token_count,
        owner=getattr(pagina, "content_owner", None),
        published_at=getattr(pagina, "content_published_at", None),
        render_signals=list(getattr(pagina, "render_signals", None) or []),
    )


# ──────────────────────── Candidatas e ingestión ────────────────────────


@router.get(
    "/hub/sites/{site_id}/candidates",
    response_model=list[CandidatePageView],
    operation_id="listCandidates",
)
async def list_candidates(
    site_id: uuid.UUID,
    chatbot_id: uuid.UUID = Query(...),
    current_user: UserInfo = Depends(_de_curacion),
    svc: Any = Depends(get_selection_service),
    session: AsyncSession = Depends(get_session),
):
    """Páginas candidatas a ingerir: activas, no ingeridas aún para el chatbot.

    Deploy: edge.
    """
    await assert_site_org_access(session, site_id, current_user)
    await assert_chatbot_org_access(session, chatbot_id, current_user)
    return await svc.candidates(site_id, chatbot_id)


@router.post(
    "/hub/chatbots/{chatbot_id}/pages/{page_id}/ingest",
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="ingestPage",
)
async def ingest_page(
    chatbot_id: uuid.UUID,
    page_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    current_user: UserInfo = Depends(_de_curacion_y_chatbots),
    session: AsyncSession = Depends(get_session),
):
    """Ingesta manual de una página concreta en un chatbot (idempotente).

    Deploy: edge. Encola la ingestión en background y responde 202.

    RAS.5 — el servicio inyectado se construye **sin watcher** (lo dice su propio docstring: para
    esta operación había que construirlo aquí, y no se hacía), así que `ingest_page` reventaba con
    `AttributeError` **dentro del `BackgroundTask`**: la respuesta era 202 «queued» y la página no
    llegaba nunca al corpus. Sin esto, la curación termina en una bandeja que no lleva a ningún
    sitio, que es justo el circuito que el módulo existe para cerrar.
    """
    asistente = await assert_chatbot_org_access(session, chatbot_id, current_user)
    if not await sitios.es_de_la_organizacion(session, page_id, asistente.organizacion_id):
        # #242: sin esto, el contenido de una página de otra organización entraba en este corpus.
        raise HTTPException(status_code=404, detail="Página no encontrada para este asistente")
    # #345 — la misma puerta que la propuesta: Publicació enseña también las no propuestas.
    await sitios.rechazar_si_es_de_navegacion(session, page_id)
    servicio = await _servicio_que_puede_ingerir(session, chatbot_id)
    background_tasks.add_task(servicio.ingest_page, chatbot_id, page_id)
    return {"status": "queued", "chatbot_id": str(chatbot_id), "page_id": str(page_id)}


@router.delete(
    "/hub/chatbots/{chatbot_id}/pages/{page_id}",
    operation_id="retirePage",
)
async def retire_page(
    chatbot_id: uuid.UUID,
    page_id: uuid.UUID,
    current_user: UserInfo = Depends(_de_curacion_y_chatbots),
    svc: Any = Depends(get_selection_service),
    session: AsyncSession = Depends(get_session),
):
    """Retira todos los documentos de una página para un chatbot.

    Deploy: edge. Devuelve el número de documentos eliminados.
    """
    await assert_chatbot_org_access(session, chatbot_id, current_user)
    count = await svc.retire_page(chatbot_id, page_id)
    return {"documents_removed": count}
