"""Sitios, páginas, secciones y selecciones de la curación: lo que leen y escriben. Deploy: edge (#274).

Vivía en los handlers de `hub_sites_router`, que consultaban y confirmaban. Ahí se quedan la
tenencia (`assert_site_org_access`, `assert_chatbot_org_access`) y los códigos de estado; aquí, la
base, sobre los repositorios de `site_repo`.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from server.app.core.auth.tenancy import assert_org_access, scope_query_to_orgs
from server.app.modules.agents_hub.database.operational_models import (
    HubContentFinding,
    HubCorpusSelection,
    HubCrawledPage,
    HubCrawlRun,
    HubWebSite,
)
from server.app.modules.curation.findings_repo import ESTADOS_ABIERTOS
from server.app.modules.curation.selection_contracts import PageView
from server.app.modules.curation.site_repo import (
    CorpusSelectionRepo,
    WebSectionRepo,
    WebSiteRepo,
)

# ──────────────────────── Sitios ────────────────────────


async def crear_sitio(session, **campos: Any) -> HubWebSite:
    sitio = await WebSiteRepo(session).create(**campos)
    await session.commit()
    return sitio


async def listar_sitios(session, principal, organizacion_id: uuid.UUID | None) -> list[HubWebSite]:
    """SEC.8.1: acotado siempre por tenencia; el filtro por organización estrecha dentro."""
    consulta = scope_query_to_orgs(select(HubWebSite), principal, HubWebSite)
    if organizacion_id is not None:
        assert_org_access(principal, organizacion_id)
        consulta = consulta.where(HubWebSite.organizacion_id == organizacion_id)
    return list(
        (await session.execute(consulta.order_by(HubWebSite.created_at.desc()))).scalars().all()
    )


async def actualizar_sitio(session, site_id: uuid.UUID, cambios: dict[str, Any]) -> HubWebSite | None:
    sitio = await WebSiteRepo(session).update(site_id, **cambios)
    if sitio is not None:
        await session.commit()
    return sitio


async def borrar_sitio(session, site_id: uuid.UUID) -> None:
    """Con todas sus páginas, por CASCADE."""
    await WebSiteRepo(session).delete(site_id)
    await session.commit()


# ──────────────────────── Páginas ────────────────────────


async def paginas(
    session, site_id: uuid.UUID, estado: str | None, solo_propuestas: bool
) -> list[PageView]:
    # recorrido-acotado: ver `site_repo.listar_paginas`. Paginar este endpoint cambia un
    # contrato que consume el frontend (issue #159).
    consulta = select(HubCrawledPage).where(HubCrawledPage.site_id == site_id)
    if estado is not None:
        consulta = consulta.where(HubCrawledPage.status == estado)
    if solo_propuestas:
        consulta = consulta.where(HubCrawledPage.propuesta_at.is_not(None))
    filas = (await session.execute(consulta.order_by(HubCrawledPage.url))).scalars().all()
    de_navegacion = await _paginas_de_navegacion(session, site_id)
    return [_vista(pagina, de_navegacion) for pagina in filas]


async def _paginas_de_navegacion(session, site_id: uuid.UUID, page_id: uuid.UUID | None = None) -> set:
    """Los ids de las páginas con un hallazgo `navigation` abierto (#345).

    Abierto y no descartado: descartarlo es decir que el detector se equivocó, y entonces la página
    vuelve a poder proponerse.
    """
    consulta = select(HubContentFinding.page_id).where(
        HubContentFinding.site_id == site_id,
        HubContentFinding.finding_type == "navigation",
        HubContentFinding.status.in_(ESTADOS_ABIERTOS),
    )
    if page_id is not None:
        consulta = consulta.where(HubContentFinding.page_id == page_id)
    return set((await session.execute(consulta)).scalars().all())


def _vista(pagina: HubCrawledPage, de_navegacion: set) -> PageView:
    return PageView.model_validate(pagina).model_copy(
        update={"de_navegacion": pagina.id in de_navegacion}
    )


async def pagina_o_404(session, page_id: uuid.UUID) -> HubCrawledPage:
    pagina = await session.get(HubCrawledPage, page_id)
    if pagina is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page not found")
    return pagina


async def pagina_de_este_sitio(
    session, site_id: uuid.UUID, page_id: uuid.UUID
) -> HubCrawledPage:
    """La página, si es de este sitio. Una ajena es un 404: comprobar sólo el sitio de la ruta y
    no que la página le pertenezca es el hueco de #242."""
    pagina = await session.get(HubCrawledPage, page_id)
    if pagina is None or pagina.site_id != site_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page not found")
    return pagina


async def es_de_la_organizacion(session, page_id: uuid.UUID, organizacion_id: uuid.UUID) -> bool:
    """Si la página es de un sitio de esa organización (#242)."""
    pagina = await session.get(HubCrawledPage, page_id)
    sitio = await session.get(HubWebSite, pagina.site_id) if pagina is not None else None
    return sitio is not None and sitio.organizacion_id == organizacion_id


async def marcar_propuesta(
    session, site_id: uuid.UUID, page_id: uuid.UUID, propuesta_por: str | None
) -> PageView:
    """Propone la página (con `propuesta_por`) o retira la propuesta (con `None`).

    Volver a proponer no cambia quién lo hizo primero. La vista se toma antes del `commit`:
    con una sesión que expira al confirmar, leer después sería una carga perezosa fuera de
    contexto (el 500 de #225).
    """
    pagina = await pagina_de_este_sitio(session, site_id, page_id)
    de_navegacion = await _paginas_de_navegacion(session, site_id, page_id)
    if propuesta_por is None:
        pagina.propuesta_at = None
        pagina.propuesta_por = None
    elif pagina.propuesta_at is not None:
        # Volver a proponer no cambia nada, tampoco en una de navegación propuesta antes de #345:
        # un reintento del cliente no puede convertirse en un 409.
        pass
    elif pagina.id in de_navegacion:
        # #345 — retirar sí se puede siempre: una propuesta anterior no se queda atascada.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Es una página de navegación: su texto son enlaces y el asistente no tendría nada "
                "que citar. Si no lo es, márcala como correcta en la auditoría y podrás proponerla."
            ),
        )
    else:
        pagina.propuesta_at = datetime.now(timezone.utc)
        pagina.propuesta_por = propuesta_por
    vista = _vista(pagina, de_navegacion)
    await session.commit()
    return vista


async def urls_del_sitio(session, site_id: uuid.UUID) -> list[str]:
    """Sólo la columna: el patrón se evalúa en Python, y cientos de filas ORM serían cientos de
    objetos para leer una cadena de cada uno (issue #159)."""
    return list(
        (await session.execute(select(HubCrawledPage.url).where(HubCrawledPage.site_id == site_id)))
        .scalars()
        .all()
    )


# ──────────────────────── Secciones ────────────────────────


async def seccion_de_este_sitio(session, site_id: uuid.UUID, section_id: uuid.UUID) -> Any:
    """La sección, si es de este sitio. Una ajena es un 404, no un cambio."""
    seccion = await WebSectionRepo(session).get(section_id)
    if seccion is None or seccion.site_id != site_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Section not found")
    return seccion


async def secciones(session, site_id: uuid.UUID) -> list[Any]:
    return list(await WebSectionRepo(session).list_by_site(site_id))


async def _sin_homonima(session, nombre: str, operacion: Callable[[], Awaitable[Any]]) -> Any:
    """Ejecuta el alta o la edición traduciendo la colisión de nombre a un 409.

    **Lo destapó la verificación en navegador de DIN.3**: `UniqueConstraint(site_id, name)` hacía
    bien su trabajo —la homónima no se guardaba— y su `IntegrityError` subía sin traducir, así
    que la respuesta era un **500**. En pantalla eso es «algo se ha roto» cuando lo que pasa es
    «ese nombre ya está usado», que es accionable.

    No se pregunta antes si el nombre existe: la restricción de la base es la que decide, y una
    comprobación previa sería una segunda regla que además tiene carrera.
    """
    try:
        resultado = await operacion()
    except IntegrityError as fallo:
        # La transacción queda inutilizable tras el error: sin deshacerla, la siguiente consulta
        # de esta petición fallaría por algo que no tiene nada que ver con la causa.
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ya hay una sección llamada «{nombre}» en este sitio",
        ) from fallo
    await session.commit()
    return resultado


async def crear_seccion(session, site_id: uuid.UUID, **campos: Any) -> Any:
    return await _sin_homonima(
        session,
        campos["name"],
        lambda: WebSectionRepo(session).create(site_id=site_id, **campos),
    )


async def actualizar_seccion(session, section_id: uuid.UUID, cambios: dict[str, Any]) -> Any:
    # Renombrar también puede colisionar, y por la misma restricción.
    return await _sin_homonima(
        session,
        cambios.get("name", ""),
        lambda: WebSectionRepo(session).update(section_id, **cambios),
    )


async def borrar_seccion(session, section_id: uuid.UUID) -> None:
    """Sólo si no tiene selecciones colgando; si las tiene, 409.

    Con `section_id` puesto el patrón efectivo lo manda la sección: borrarla dejaría la selección
    apuntando a un ámbito que no existe, y con la auto-retirada de DIN.4 detrás eso no es un dato
    huérfano, es corpus que se vacía.
    """
    colgando = (
        await session.execute(
            select(HubCorpusSelection).where(HubCorpusSelection.section_id == section_id)
        )
    ).scalars().all()
    if colgando:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"{len(colgando)} selección(es) de corpus apuntan a esta sección: "
                "desactívala en vez de borrarla, o quita antes esas selecciones"
            ),
        )
    await WebSectionRepo(session).delete(section_id)
    await session.commit()


async def pasadas(
    session, site_id: uuid.UUID, section_id: uuid.UUID | None, pagina: int, tamano: int
) -> tuple[int, list[HubCrawlRun]]:
    """El diario de pasadas, paginado. (total, filas).

    **Orden con desempate por `id`** (DET.1): dos pasadas pueden compartir `started_at` al
    microsegundo, y sin desempate paginar devuelve una fila en dos páginas y otra en ninguna.
    """
    base = select(HubCrawlRun).where(HubCrawlRun.site_id == site_id)
    if section_id is not None:
        base = base.where(HubCrawlRun.section_id == section_id)

    total = (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    filas = (
        await session.execute(
            base.order_by(HubCrawlRun.started_at.desc(), HubCrawlRun.id.desc())
            .offset((pagina - 1) * tamano)
            .limit(tamano)
        )
    ).scalars().all()
    return total, list(filas)


# ──────────────────────── Selecciones ────────────────────────


async def crear_seleccion(session, **campos: Any) -> HubCorpusSelection:
    seleccion = await CorpusSelectionRepo(session).create(**campos)
    await session.commit()
    return seleccion


async def selecciones(session, chatbot_id: uuid.UUID) -> list[HubCorpusSelection]:
    return list(
        (
            await session.execute(
                select(HubCorpusSelection)
                .where(HubCorpusSelection.chatbot_id == chatbot_id)
                .order_by(HubCorpusSelection.created_at.desc())
            )
        )
        .scalars()
        .all()
    )


async def borrar_seleccion(session, chatbot_id: uuid.UUID, selection_id: uuid.UUID) -> None:
    seleccion = await session.get(HubCorpusSelection, selection_id)
    if seleccion is None or seleccion.chatbot_id != chatbot_id:
        # #242: el asistente de la ruta pasaba el control y la selección podía ser de otro.
        raise HTTPException(status_code=404, detail="Selección no encontrada en este asistente")
    await CorpusSelectionRepo(session).delete(selection_id)
    await session.commit()
