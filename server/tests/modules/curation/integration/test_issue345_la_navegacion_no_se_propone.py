"""#345 — una página de navegación no se ofrece para el asistente.

Una página cuyo texto son enlaces no tiene nada que citar: proponerla mete en el corpus un índice.
La pantalla de páginas lo sabe por `de_navegacion`, y el servidor se niega a proponerla. Si quien
cura discrepa —marca el hallazgo como correcto, es decir, «no es de navegación»—, vuelve a poder
proponerse: el detector no tiene la última palabra.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException


async def _sitio_con_pagina(session, *, estado_del_hallazgo: str | None = "new"):
    from server.app.modules.agents_hub.database.config_models import HubOrganizacion
    from server.app.modules.agents_hub.database.operational_models import (
        HubContentFinding,
        HubCrawledPage,
    )
    from server.app.modules.curation.site_repo import WebSiteRepo

    org = uuid.uuid4()
    session.add(HubOrganizacion(id=org, name=f"UJI {org.hex[:6]}", partner_id=f"p-{org.hex[:6]}"))
    await session.flush()
    sitio = await WebSiteRepo(session).create(
        organizacion_id=org, name="Escola", root_url="https://www.uji.es/centres/escola-doctorat/"
    )
    pagina = HubCrawledPage(
        site_id=sitio.id, url="https://www.uji.es/centres/escola-doctorat/organitzacio/",
        markdown_content="Organització\nLa Comissió Acadèmica", token_count=8,
        textos_de_enlace=["La Comissió Acadèmica"],
    )
    session.add(pagina)
    await session.flush()
    if estado_del_hallazgo is not None:
        session.add(HubContentFinding(
            site_id=sitio.id, page_id=pagina.id, finding_type="navigation", severity="info",
            confidence=1.0, source_url=pagina.url, signal_json={}, status=estado_del_hallazgo,
            detected_at=datetime.now(timezone.utc),
        ))
    await session.commit()
    return sitio.id, pagina.id


@pytest.mark.asyncio
async def test_la_lista_de_paginas_dice_cuales_son_de_navegacion(db_session) -> None:
    from server.app.modules.curation import sitios

    site_id, page_id = await _sitio_con_pagina(db_session)

    [vista] = await sitios.paginas(db_session, site_id, None, False)

    assert vista.id == page_id
    assert vista.de_navegacion is True


@pytest.mark.asyncio
async def test_una_pagina_de_navegacion_no_se_propone(db_session) -> None:
    from server.app.modules.curation import sitios

    site_id, page_id = await _sitio_con_pagina(db_session)

    with pytest.raises(HTTPException) as fallo:
        await sitios.marcar_propuesta(db_session, site_id, page_id, "curadora@uji.es")

    assert fallo.value.status_code == 409
    assert "navegación" in str(fallo.value.detail)


@pytest.mark.asyncio
async def test_si_quien_cura_dice_que_no_lo_es_se_puede_proponer(db_session) -> None:
    """Descartar el hallazgo es decir que el detector se equivocó."""
    from server.app.modules.curation import sitios

    site_id, page_id = await _sitio_con_pagina(db_session, estado_del_hallazgo="dismissed")

    vista = await sitios.marcar_propuesta(db_session, site_id, page_id, "curadora@uji.es")

    assert vista.propuesta_por == "curadora@uji.es"
    assert vista.de_navegacion is False


@pytest.mark.asyncio
async def test_retirar_la_propuesta_siempre_se_puede(db_session) -> None:
    """Una propuesta hecha antes de #345 no puede quedarse atascada."""
    from server.app.modules.curation import sitios

    site_id, page_id = await _sitio_con_pagina(db_session)

    vista = await sitios.marcar_propuesta(db_session, site_id, page_id, None)

    assert vista.propuesta_at is None
    assert vista.de_navegacion is True


@pytest.mark.asyncio
async def test_volver_a_proponer_una_ya_propuesta_no_es_un_409(db_session) -> None:
    """Revisión de la PR #347: proponer era idempotente, y una página propuesta antes de #345 que
    ahora sale como de navegación convertía un reintento del cliente en un 409."""
    from server.app.modules.agents_hub.database.operational_models import HubCrawledPage
    from server.app.modules.curation import sitios

    site_id, page_id = await _sitio_con_pagina(db_session)
    pagina = await db_session.get(HubCrawledPage, page_id)
    pagina.propuesta_at = datetime.now(timezone.utc)
    pagina.propuesta_por = "primera@uji.es"
    await db_session.commit()

    vista = await sitios.marcar_propuesta(db_session, site_id, page_id, "otra@uji.es")

    assert vista.propuesta_por == "primera@uji.es"
