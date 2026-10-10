"""#247 — proponer una página mientras se rastrea su sitio no espera, y la señal no se pierde.

El rastreo era **una transacción**: cada página que tocaba quedaba bloqueada hasta el final, unos
12 minutos en la Escola de Doctorat. Quien marcaba «Per a l'assistent» en una de ellas esperaba el
bloqueo, a los 30 s el `statement_timeout` lo cancelaba y la pantalla decía que no se había podido
guardar.

Confirmar cada página al guardarla quita el bloqueo, pero tenía un precio que la issue no veía: lo
que el job hace después —reingerir lo que cambió, ingerir lo nuevo— dependía de la memoria del
rastreo (`changed_page_ids`, `new_page_ids`). Con la página ya confirmada con su contenido nuevo,
un reinicio a mitad (basta un despliegue) dejaba la copia del corpus vieja **para siempre** y sin
aviso: el rastreo siguiente ya no la ve cambiar. El hueco existía ya antes —el rastreo confirmaba
al final y el job reingería en otra transacción—, sólo que más estrecho.

Por eso la señal vive ahora **en la página** (`pendiente`: `nueva` o `cambiada`), la pone el
rastreo y sólo la quita el job cuando la ha procesado. Decisión del usuario el 2026-10-08.
"""
from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import text

from server.app.modules.curation.site_crawler_dispatcher import SiteCrawlerDispatcher
from server.app.modules.curation.spider import CrawlResult, CrawlStatus

_RAIZ = "https://www.uji.es/centres/escola-doctorat/"
_A = _RAIZ + "a-beques/"
_B = _RAIZ + "b-tesi/"
_C = _RAIZ + "c-nova/"


class _Spider:
    """Sirve un HTML por URL y deja colgar algo de la lectura de una de ellas."""

    def __init__(self, paginas: dict[str, str], al_leer: dict[str, Any] | None = None) -> None:
        self._paginas = paginas
        self._al_leer = al_leer or {}

    async def crawl(self, source: Any) -> CrawlResult:
        return CrawlResult(
            crawled_urls=list(self._paginas),
            pages_crawled=len(self._paginas),
            pages_skipped=0,
            status=CrawlStatus.COMPLETED,
        )

    async def _fetch(self, url: str) -> tuple[str, dict]:
        if url not in self._paginas:
            raise RuntimeError(f"no existe {url}")
        if url in self._al_leer:
            await self._al_leer[url]()
        return self._paginas[url], {}


class _Spiders:
    def __init__(self, spider: _Spider) -> None:
        self._spider = spider

    def get_spider(self, tipo: str) -> _Spider:
        return self._spider


def _html(titulo: str, cuerpo: str) -> str:
    return f"<html><head><title>{titulo}</title></head><body><h1>{titulo}</h1><p>{cuerpo}</p></body></html>"


@pytest.fixture
async def fabrica(db_url: str):
    from server.app.modules.agents_hub.database.connection import (
        create_async_engine,
        create_session_factory,
    )

    motor = create_async_engine(db_url)
    yield create_session_factory(motor)
    await motor.dispose()


@pytest.fixture
async def sitio(fabrica) -> uuid.UUID:
    from server.app.modules.agents_hub.database.config_models import HubOrganizacion
    from server.app.modules.curation.site_repo import WebSiteRepo

    async with fabrica() as s:
        org = uuid.uuid4()
        s.add(HubOrganizacion(id=org, name="UJI", partner_id=f"p-{org.hex[:6]}"))
        await s.flush()
        sitio = await WebSiteRepo(s).create(organizacion_id=org, name="Escola", root_url=_RAIZ)
        await s.commit()
        return sitio.id


async def _pendiente(fabrica, site_id: uuid.UUID) -> dict[str, str | None]:
    from sqlalchemy import select

    from server.app.modules.agents_hub.database.operational_models import HubCrawledPage

    async with fabrica() as s:
        filas = (
            await s.execute(
                select(HubCrawledPage.url, HubCrawledPage.pendiente).where(
                    HubCrawledPage.site_id == site_id
                )
            )
        ).all()
    return {url: pendiente for url, pendiente in filas}


@pytest.mark.asyncio
async def test_proponer_una_pagina_ya_rastreada_no_espera_al_final_del_rastreo(fabrica, sitio):
    resultado: dict[str, Any] = {}

    async def proponer_a_mientras_se_lee_b() -> None:
        # Otra sesión, como la de la petición HTTP. `lock_timeout` corto: si la fila de A sigue
        # bloqueada por el rastreo, esto falla en 2 s en vez de colgar el test.
        async with fabrica() as s:
            try:
                await s.execute(text("SET LOCAL lock_timeout = '2s'"))
                actualizadas = await s.execute(
                    text(
                        "UPDATE hub_crawled_pages SET propuesta_at = now(), "
                        "propuesta_por = 'curadora@uji.es' WHERE url = :url"
                    ),
                    {"url": _A},
                )
                await s.commit()
                # Un 0 aquí no sería «no esperó»: sería que la fila aún no se veía.
                resultado["ok"] = actualizadas.rowcount == 1
            except Exception as exc:  # noqa: BLE001 — lo que se mide es si falla
                resultado["error"] = str(exc)

    paginas = {_A: _html("Beques", "Convocatòria oberta."), _B: _html("Tesi", "Dipòsit de la tesi.")}
    # Una primera pasada para que A ya exista: lo que bloquea es actualizar una fila que otros
    # ven, no insertar una que todavía nadie ve.
    await SiteCrawlerDispatcher(fabrica, spider_factory=_Spiders(_Spider(paginas))).crawl_site(sitio)

    spider = _Spider(paginas, al_leer={_B: proponer_a_mientras_se_lee_b})
    await SiteCrawlerDispatcher(fabrica, spider_factory=_Spiders(spider)).crawl_site(sitio)

    assert resultado.get("ok"), f"la propuesta esperó al rastreo: {resultado.get('error')}"


@pytest.mark.asyncio
async def test_la_senal_de_cambio_sobrevive_a_un_job_que_no_llego_a_procesarla(fabrica, sitio):
    rastrear = SiteCrawlerDispatcher
    primera = _Spider({_A: _html("Beques", "Versió 1."), _B: _html("Tesi", "Igual.")})
    await rastrear(fabrica, spider_factory=_Spiders(primera)).crawl_site(sitio)
    assert set((await _pendiente(fabrica, sitio)).values()) == {"nueva"}

    # Lo que haría el job tras procesarlas: quitar la marca.
    async with fabrica() as s:
        await s.execute(text("UPDATE hub_crawled_pages SET pendiente = NULL"))
        await s.commit()

    # A cambia y aparece C. El job **no llega a correr** (un despliegue a mitad).
    segunda = _Spider(
        {_A: _html("Beques", "Versió 2."), _B: _html("Tesi", "Igual."), _C: _html("Nova", "Hola.")}
    )
    await rastrear(fabrica, spider_factory=_Spiders(segunda)).crawl_site(sitio)
    assert await _pendiente(fabrica, sitio) == {_A: "cambiada", _B: None, _C: "nueva"}

    # La pasada siguiente no ve cambiar nada… y aun así lo entrega, porque sigue pendiente.
    resumen = await rastrear(fabrica, spider_factory=_Spiders(segunda)).crawl_site(sitio)
    paginas = await _ids_por_url(fabrica, sitio)
    assert resumen.pages_changed == 0 and resumen.pages_new == 0
    assert resumen.changed_page_ids == [paginas[_A]]
    assert resumen.new_page_ids == [paginas[_C]]


@pytest.mark.asyncio
async def test_una_pagina_nueva_que_cambia_antes_de_procesarse_sigue_siendo_nueva(fabrica, sitio):
    """Si pasara a «cambiada», el job la buscaría en el corpus, no la encontraría y la daría por
    procesada: la auto-ingesta de lo nuevo no la vería nunca."""
    await SiteCrawlerDispatcher(
        fabrica, spider_factory=_Spiders(_Spider({_A: _html("Beques", "Versió 1.")}))
    ).crawl_site(sitio)
    await SiteCrawlerDispatcher(
        fabrica, spider_factory=_Spiders(_Spider({_A: _html("Beques", "Versió 2.")}))
    ).crawl_site(sitio)

    assert await _pendiente(fabrica, sitio) == {_A: "nueva"}


async def _ids_por_url(fabrica, site_id: uuid.UUID) -> dict[str, uuid.UUID]:
    from sqlalchemy import select

    from server.app.modules.agents_hub.database.operational_models import HubCrawledPage

    async with fabrica() as s:
        filas = (
            await s.execute(
                select(HubCrawledPage.url, HubCrawledPage.id).where(
                    HubCrawledPage.site_id == site_id
                )
            )
        ).all()
    return {url: ident for url, ident in filas}
