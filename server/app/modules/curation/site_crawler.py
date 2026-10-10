"""Crawl de sitio entero + diff de sitemap (9Q.2).

Deploy: edge.

Orquesta el rastreo de un HubWebSite: une las URLs descubiertas por el spider con
las del sitemap, hace upsert de cada página con sus señales de frescura y calcula el
diff (nuevas / cambiadas / desaparecidas). El cloud orquesta, el edge ejecuta.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Protocol

from server.app.modules.agents_hub.services.language_detector import detect_language
from server.app.modules.agents_hub.database.operational_models import HubWebSite
from server.app.modules.agents_hub.ingestion.hasher import hash_content
from server.app.modules.agents_hub.ingestion.markdown_utils import (
    estimate_tokens,
    extract_title_from_markdown,
)
from server.app.modules.curation.contenido_web import (
    texto_de_contenido,
    fecha_y_responsable,
    parece_html,
    titulo_de,
)
from server.app.modules.curation.cortesia import RutaProhibidaPorRobots, clasificar_fallo
from server.app.modules.curation.plantilla_del_sitio import bloques_repetidos, sin_bloques
from server.app.modules.curation.sondeo_dinamico import senales_de_dinamismo


_log = logging.getLogger(__name__)

#: Lo que se guarda de la cola para reanudar. Con URLs de ~120 caracteres, cinco mil son unos
#: 600 KB de JSON en la fila del sitio: suficiente para un apartado y acotado para un portal.
_MAX_COLA_GUARDADA = 5_000
_MAX_VISITADAS_GUARDADAS = 20_000


@dataclass
class SiteCrawlSummary:
    """Resultado de un crawl de sitio. Insumo del job de calidad (9Q.5)."""

    pages_new: int = 0
    pages_changed: int = 0
    pages_gone: int = 0
    pages_error: int = 0
    pages_total: int = 0
    errors: list[str] = field(default_factory=list)
    #: El rastreo no vio el sitio entero (RAS.1). Mientras sea `True`, **no se declaran bajas**:
    #: una página no visitada no es una página desaparecida.
    truncated: bool = False
    stop_reason: str | None = None
    pages_pending: int = 0
    #: URLs que el `robots.txt` del sitio excluye. No son errores.
    pages_forbidden: int = 0
    #: CUR.3 — cuánta plantilla se ha quitado y a cuántas páginas. Es la cifra que dice si el
    #: recorte está haciendo algo, y sin ella no se puede juzgar si merece la pena.
    boilerplate_blocks: int = 0
    boilerplate_chars_removed: int = 0
    pages_trimmed: int = 0
    #: Páginas donde el recorte se lo habría llevado todo y se conservó el original.
    pages_trim_reverted: int = 0
    # IDs de páginas del diff — usados por SiteQualityAnalysisJob para auto-ingesta (9Q.5)
    new_page_ids: list[uuid.UUID] = field(default_factory=list)
    changed_page_ids: list[uuid.UUID] = field(default_factory=list)
    gone_page_ids: list[uuid.UUID] = field(default_factory=list)
    #: DIN.2 — qué ámbito cubrió esta pasada: la sección, o el sitio entero. El job y el diario
    #: de DIN.6 tienen que poder decirlo, y la auto-retirada de DIN.4 decide con ello.
    section_id: uuid.UUID | None = None

    @property
    def ambito(self) -> str:
        return "sitio" if self.section_id is None else str(self.section_id)


class _AmbitoDesconocido(RuntimeError):
    """Se ha pedido rastrear una sección que no existe, o que no es de este sitio."""


def _lo_que_queda_pendiente(prev: Any, prev_hash: str | None, content_hash: str) -> str | None:
    """Qué tendrá que hacer el job con esta página, o `None` si esta pasada no cambia nada.

    Una página nueva que cambia antes de procesarse **sigue siendo nueva**: como «cambiada», el job
    la buscaría en el corpus, no la encontraría y la daría por hecha, y la auto-ingesta de lo nuevo
    no la vería nunca.
    """
    if prev is None:
        return "nueva"
    if prev_hash != content_hash:
        return "nueva" if getattr(prev, "pendiente", None) == "nueva" else "cambiada"
    return None


@dataclass
class _FuenteDelAmbito:
    """El sitio tal y como lo ve el spider en esta pasada (DIN.2).

    El ámbito viaja **dentro de `config_json`**, que es el camino que ya recorre
    `url_regex_filter`: así el protocolo del spider no cambia y el filtro de la sección se
    aplica **además** del del sitio —la valla del dominio es del sitio; el apartado, de la
    sección—. Los criterios son los efectivos de DIN.1, así que un apartado puede recortar la
    plantilla con otro selector que su portal.
    """

    id: uuid.UUID
    root_url: str
    sitemap_url: str | None
    config_json: dict[str, Any]
    crawl_frontier: dict[str, Any] | None


@dataclass
class _Ambito:
    """Los parámetros resueltos de la pasada y, si la hay, la sección a la que pertenecen."""

    efectivos: Any
    seccion: Any | None

    @property
    def section_id(self) -> uuid.UUID | None:
        return self.efectivos.section_id

    @property
    def es_sitio_entero(self) -> bool:
        return self.efectivos.es_sitio_entero

    def en_ambito(self, url: str) -> bool:
        return self.efectivos.en_ambito(url)


class _Spider(Protocol):
    async def crawl(self, source: Any) -> Any: ...
    async def _fetch(self, url: str) -> tuple[str, dict]: ...


class _SignalExtractor(Protocol):
    def extract_from_headers(self, headers: dict) -> dict: ...
    def extract_canonical(self, html: str) -> str | None: ...
    def extract_content_year(self, url: str, text: str) -> int | None: ...
    async def fetch_sitemap(self, url: str, fetch_fn: Any) -> dict: ...


class _PageRepo(Protocol):
    async def upsert(self, *, site_id: uuid.UUID, url: str, **fields: Any) -> Any: ...
    async def list_by_site(self, site_id: uuid.UUID, status: str | None = ...) -> list: ...
    async def mark_gone(self, page_ids: list[uuid.UUID]) -> int: ...


class SiteCrawler:
    """Rastrea un sitio completo y materializa el diff sobre HubCrawledPage."""

    def __init__(
        self,
        session: Any,
        spider: _Spider,
        signal_extractor: _SignalExtractor,
        page_repo: _PageRepo,
        confirmar: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._session = session
        self._spider = spider
        self._signals = signal_extractor
        self._pages = page_repo
        # #247 — confirmar cada página al guardarla. La transacción no es del rastreador sino de
        # quien le da la sesión, así que se la pasa quien la abre (el despachador); sin ella, el
        # rastreo entero sigue siendo una sola transacción, que es lo que usan los tests unitarios.
        self._confirmar = confirmar

    async def _confirmar_lo_guardado(self) -> None:
        if self._confirmar is not None:
            await self._confirmar()

    async def crawl_site(
        self, site_id: uuid.UUID, section_id: uuid.UUID | None = None
    ) -> SiteCrawlSummary:
        """Rastrea un ámbito del sitio: una sección, o el sitio entero si no se dice otra cosa.

        **El censo se acota al ámbito rastreado** (DIN.2). Mientras el sitio *era* el apartado,
        comparar lo visto contra todas sus páginas era correcto; con varias secciones de
        cadencias distintas, una pasada completa de `/eventos` declararía baja el resto del
        portal — y con la auto-retirada de DIN.4 encima, eso vacía corpus.
        """
        site = await self._session.get(HubWebSite, site_id)
        if site is None:
            return SiteCrawlSummary(errors=[f"site {site_id} not found"])

        try:
            fuente, parametros = await self._ambito(site, section_id)
        except _AmbitoDesconocido as exc:
            # No se degrada a «el sitio entero»: eso sería una pasada de sección que declara
            # baja el portal.
            return SiteCrawlSummary(errors=[str(exc)])

        now = datetime.now(timezone.utc)

        # 1. Conjunto de URLs objetivo: unión(sitemap, enlaces descubiertos por el spider).
        try:
            target_urls, sitemap_map, recorrido = await self._discover_urls(fuente)
        except Exception as exc:  # fallo global del crawl → el sitio queda en error
            site.status = "error"
            site.error_message = str(exc)
            await self._session.flush()
            return SiteCrawlSummary(errors=[str(exc)], section_id=parametros.section_id)

        # El recorrido ve de paso lo que no es del ámbito —la raíz nunca lleva filtro y el menú
        # de cada página enlaza al portal entero—, y fuera del ámbito no se declara **nada**: ni
        # baja ni cambio.
        target_urls = {u for u in target_urls if parametros.en_ambito(u)}

        # Estado previo para el diff, **acotado**: las páginas del sitio que casan el ámbito que
        # se ha rastreado. Fuera de él, esta pasada no ha mirado y no puede concluir.
        existing_pages = [
            p
            for p in await self._pages.list_by_site(site_id, status="active")
            if parametros.en_ambito(p.url)
        ]
        existing_by_url = {p.url: p for p in existing_pages}

        summary = SiteCrawlSummary(
            pages_total=len(target_urls), section_id=parametros.section_id
        )
        # El recorrido del spider ya puede venir truncado por páginas o por presupuesto de
        # tiempo (RAS.1). Eso viaja hasta aquí porque cambia lo que se puede concluir.
        summary.truncated = getattr(recorrido, "stop_reason", None) is not None
        summary.stop_reason = getattr(recorrido, "stop_reason", None)
        summary.pages_pending = getattr(recorrido, "pages_skipped", 0) if summary.truncated else 0
        summary.pages_forbidden = getattr(recorrido, "urls_prohibidas", 0)
        seen_urls: set[str] = set()

        # 2. Por cada URL: fetch + señales + upsert. Un fallo de página no aborta el crawl.
        for url in sorted(target_urls):
            seen_urls.add(url)
            try:
                body, headers = await self._spider._fetch(url)
            except RutaProhibidaPorRobots:
                # El servidor ha dicho que no. No es un error de la página, así que no se
                # registra como tal: contarlo como error la acusaría de estar rota.
                summary.pages_forbidden += 1
                seen_urls.discard(url)
                summary.truncated = True
                summary.stop_reason = summary.stop_reason or "robots"
                continue
            except Exception as exc:
                # RAS.3 — un 404 y un `timeout` no dicen lo mismo: el primero es una respuesta
                # («esto ya no está», información útil) y el segundo un fallo del que no se
                # puede concluir nada sobre la página. Los dos producían el mismo hallazgo
                # crítico, así que un rastreo con mala red llenaba el informe de acusaciones.
                causa = getattr(exc, "causa", exc)
                await self._pages.upsert(
                    site_id=site_id,
                    url=url,
                    status="error",
                    error_message=str(exc),
                    error_kind=clasificar_fallo(causa),
                    error_attempts=getattr(exc, "intentos", 1),
                    last_crawled_at=now,
                )
                await self._confirmar_lo_guardado()
                summary.pages_error += 1
                continue

            content_hash = hash_content(body)
            prev = existing_by_url.get(url)
            # Capturar el hash previo ANTES del upsert: el repo puede devolver el
            # mismo objeto identity-mapped y mutarlo, invalidando la comparación.
            prev_hash = prev.content_hash if prev is not None else None
            pendiente = _lo_que_queda_pendiente(prev, prev_hash, content_hash)

            try:
                upserted = await self._pages.upsert(
                    site_id=site_id,
                    url=url,
                    last_crawled_at=now,
                    status="active",
                    error_message=None,
                    sitemap_lastmod=sitemap_map.get(url),
                    **self._page_fields(url, body, headers, fuente),
                    content_hash=content_hash,
                    **({"pendiente": pendiente} if pendiente else {}),
                )
                await self._confirmar_lo_guardado()
            except Exception as exc:  # noqa: BLE001
                # Guardar una página tampoco puede tumbar el rastreo. Ocurrió en el rastreo real:
                # un PDF servido como si fuera página trajo bytes nulos, Postgres rechazó la fila
                # y el sitio quedó en error **con cero páginas**. Segunda cara del mismo patrón
                # que el enlace roto, esta vez en la escritura.
                _log.warning("No se pudo guardar %s: %s", url, exc)
                summary.pages_error += 1
                summary.errors.append(f"{url}: {exc}"[:500])
                continue

            # 3. Diff de sitemap: alta / cambio.
            if prev is None:
                summary.pages_new += 1
                summary.new_page_ids.append(upserted.id)
            elif prev_hash != content_hash:
                summary.pages_changed += 1
                summary.changed_page_ids.append(upserted.id)

        # 2.bis. Las páginas que el recorrido no pudo leer. Antes ni llegaban aquí: la excepción
        # tumbaba el rastreo entero. Se registran con su causa —un 404 es contenido que ya no
        # está, y eso es lo que hay que depurar— y se cuentan como vistas para que no se sumen
        # además como bajas.
        for fallo in getattr(recorrido, "fallos", None) or []:
            url = fallo.get("url", "")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            await self._pages.upsert(
                site_id=site_id,
                url=url,
                status="error",
                error_message=fallo.get("message", ""),
                error_kind=fallo.get("kind"),
                error_attempts=fallo.get("attempts", 1),
                last_crawled_at=now,
            )
            await self._confirmar_lo_guardado()
            summary.pages_error += 1

        # 2.ter. La plantilla que ningún selector declara, reconocida por repetición (CUR.3): una
        # línea que sale igual en casi todas las páginas del sitio es menú, no contenido. Se hace
        # aquí, con todas las páginas leídas, porque es lo único que permite verlo.
        await self._quitar_la_plantilla_repetida(fuente, summary)
        await self._confirmar_lo_guardado()

        # 3. Diff de sitemap: bajas (páginas activas que ya no aparecen).
        #
        # Sólo si el rastreo vio el sitio entero. Con un rastreo truncado —por `max_pages`, por
        # presupuesto de tiempo o porque el `robots.txt` excluye parte— «no apareció» significa
        # «no se llegó a mirar», y una baja no es un contador: es la señal de «esto ya no está»
        # que alimenta los hallazgos y las decisiones de retirada del corpus.
        if not summary.truncated:
            gone_ids = [p.id for p in existing_pages if p.url not in seen_urls]
            if gone_ids:
                summary.pages_gone = await self._pages.mark_gone(gone_ids)
                summary.gone_page_ids = gone_ids

        # 3.bis. Lo que sigue pendiente de una pasada anterior (#247): el job no llegó a
        # procesarlo —un reinicio, o una puerta de calidad que lo detuvo— y esta pasada ya no lo ve
        # cambiar. Se entrega igual, porque la marca sólo la quita el job.
        self._entregar_lo_pendiente(existing_pages, summary)

        # 4. Cierre del ámbito, guardando la cola si quedó algo por ver (RAS.3).
        site.status = "active"
        site.error_message = None
        if parametros.es_sitio_entero:
            site.last_crawled_at = now
            site.crawl_frontier = self._cola_a_guardar(recorrido, summary)
        else:
            # El reloj de la sección es suyo; el del sitio **no se toca**: diciendo que se vio
            # todo cuando sólo se vio un apartado, el resto del portal se quedaría sin rastrear.
            #
            # Y la cola tampoco: vive en la fila del sitio y es de un recorrido del sitio
            # entero. Si una pasada de `/jornadas` la escribiera, la siguiente de `/eventos`
            # arrancaría por la mitad del recorrido ajeno y —con el censo acotado— creería haber
            # visto su ámbito sin haberlo visto. Una sección es pequeña por definición: si se
            # trunca, la siguiente pasada empieza de nuevo.
            parametros.seccion.last_crawled_at = now
        await self._session.flush()

        return summary

    @staticmethod
    def _entregar_lo_pendiente(paginas: list, summary: SiteCrawlSummary) -> None:
        bajas = set(summary.gone_page_ids)
        for pagina in paginas:
            if getattr(pagina, "status", None) != "active" or pagina.id in bajas:
                continue
            pendiente = getattr(pagina, "pendiente", None)
            if pendiente == "nueva" and pagina.id not in summary.new_page_ids:
                summary.new_page_ids.append(pagina.id)
            elif pendiente == "cambiada" and pagina.id not in summary.changed_page_ids:
                summary.changed_page_ids.append(pagina.id)

    async def _ambito(
        self, site: HubWebSite, section_id: uuid.UUID | None
    ) -> tuple[Any, _Ambito]:
        """La fuente con la que se rastrea y los parámetros efectivos del ámbito (DIN.2)."""
        from server.app.modules.agents_hub.database.operational_models import HubWebSection
        from server.app.modules.curation.secciones import parametros_efectivos

        seccion = None
        if section_id is not None:
            seccion = await self._session.get(HubWebSection, section_id)
            if seccion is None or seccion.site_id != site.id:
                raise _AmbitoDesconocido(
                    f"la sección {section_id} no es de el sitio {site.id}"
                )

        efectivos = parametros_efectivos(site, seccion)
        fuente = _FuenteDelAmbito(
            id=site.id,
            root_url=site.root_url,
            sitemap_url=site.sitemap_url,
            config_json=efectivos.config_de_rastreo(),
            # Una pasada de sección no reanuda la cola del sitio ni la escribe: ver el cierre.
            # Se lee con `getattr` igual que la lee el spider: la cola es de RAS.3 y hay dobles
            # de sitio anteriores a ella.
            crawl_frontier=getattr(site, "crawl_frontier", None) if seccion is None else None,
        )
        return fuente, _Ambito(efectivos=efectivos, seccion=seccion)

    async def _quitar_la_plantilla_repetida(
        self, site: Any, summary: SiteCrawlSummary
    ) -> None:
        """Quita de cada página las líneas que se repiten en casi todas las del sitio (CUR.3).

        Los selectores declarados sólo llegan hasta donde alguien los escribió. Esto no necesita
        saber nada del portal: si una línea sale igual en el 60 % de sus páginas, es plantilla.

        Se apoya en las páginas ya guardadas —incluidas las de rastreos anteriores— porque la
        repetición es una propiedad **del sitio**, no de una ejecución.
        """
        umbral = float((getattr(site, "config_json", None) or {}).get(
            "boilerplate_repeat_threshold", 0.6
        ))

        paginas = [
            p
            for p in await self._pages.list_by_site(site.id, status="active")
            if getattr(p, "markdown_content", None)
        ]
        if not paginas:
            return

        bloques = bloques_repetidos([p.markdown_content for p in paginas], umbral=umbral)
        if not bloques:
            return
        summary.boilerplate_blocks = len(bloques)

        for pagina in paginas:
            limpio, aviso = sin_bloques(pagina.markdown_content, bloques)
            if aviso:
                summary.pages_trim_reverted += 1
                continue
            if limpio == pagina.markdown_content:
                continue

            summary.boilerplate_chars_removed += len(pagina.markdown_content) - len(limpio)
            summary.pages_trimmed += 1
            await self._pages.upsert(
                site_id=site.id,
                url=pagina.url,
                markdown_content=limpio,
                token_count=estimate_tokens(limpio),
            )

    @staticmethod
    def _cola_a_guardar(recorrido: Any, summary: SiteCrawlSummary) -> dict[str, Any] | None:
        """La cola pendiente que hay que guardar, o `None` si no hay nada que reanudar.

        Se acota lo que se persiste —una cola de cien mil URLs no cabe en una fila— y **se dice**
        cuánto se ha dejado fuera: un tope silencioso haría que la reanudación pareciera completa.
        """
        pendientes = list(getattr(recorrido, "frontier", None) or [])
        if not pendientes:
            return None

        visitadas = list(getattr(recorrido, "visited", None) or [])
        recortadas = max(0, len(pendientes) - _MAX_COLA_GUARDADA)
        if recortadas:
            summary.errors.append(
                f"la cola pendiente se ha guardado recortada: {recortadas} URLs quedan fuera "
                f"de la reanudación"
            )

        return {
            "pending": [[u, d] for u, d in pendientes[:_MAX_COLA_GUARDADA]],
            "visited": visitadas[:_MAX_VISITADAS_GUARDADAS],
            "dropped": recortadas,
        }

    async def _discover_urls(
        self, site: _FuenteDelAmbito
    ) -> tuple[set[str], dict[str, datetime | None], Any]:
        """Unión de URLs del spider y del sitemap; el mapa de lastmod y el recorrido en bruto."""
        crawl_result = await self._spider.crawl(site)
        discovered = set(crawl_result.crawled_urls)

        async def _fetch_text(u: str) -> str:
            body, _headers = await self._spider._fetch(u)
            return body

        sitemap_map = await self._signals.fetch_sitemap(
            site.sitemap_url or site.root_url, _fetch_text
        )
        return discovered | set(sitemap_map.keys()), sitemap_map, crawl_result

    def _page_fields(
        self, url: str, body: str, headers: dict, site: Any = None
    ) -> dict[str, Any]:
        """Campos de contenido + señales para el upsert de una página.

        RAS.2 — de una página HTML se guarda **su texto**, no su marcado: con el marcado dentro,
        `token_count` medía plantillas (51 KB de HTML para 4 KB de texto en el portal real), el
        umbral de `thin` era inalcanzable y a la ingesta del asistente llegaban `<div>`. La
        evidencia de que la página necesita un navegador se guarda aquí porque el detector corre
        después y ya no tiene el HTML.
        """
        header_signals = self._signals.extract_from_headers(headers)
        declared_canonical = self._signals.extract_canonical(body)

        config = (getattr(site, "config_json", None) or {}) if site is not None else {}

        es_html = parece_html(body)
        # CUR.3 — de una página HTML se guarda su **contenido**, no su plantilla: cada página del
        # portal lleva el menú completo, y al corpus entraba con el contenido.
        if es_html:
            contenido, aviso_de_recorte = texto_de_contenido(
                body,
                config.get("content_selector"),
                config.get("boilerplate_selectors") or [],
            )
            if aviso_de_recorte:
                _log.info("Recorte de plantilla en %s: %s", url, aviso_de_recorte)
        else:
            contenido = body
        titulo = titulo_de(body) if es_html else extract_title_from_markdown(body)
        senales = [s.como_dict() for s in senales_de_dinamismo(body)] if es_html else []

        # CUR.1 — la fecha y la unidad responsable que publica la propia página, si el sitio declara
        # dónde están. El marcado es de cada portal, así que viene de su configuración.
        publicada, responsable = (
            fecha_y_responsable(
                body,
                config.get("content_date_selector"),
                config.get("content_date_format") or "%d/%m/%Y",
            )
            if es_html
            else (None, None)
        )

        return {
            "content_published_at": publicada,
            "content_owner": responsable,
            "markdown_content": contenido,
            "title": titulo,
            "token_count": estimate_tokens(contenido),
            "language": detect_language(contenido),
            "render_signals": senales,
            "http_last_modified": header_signals["http_last_modified"],
            "http_etag": header_signals["http_etag"],
            "declared_canonical_url": declared_canonical,
            "canonical_url": declared_canonical or url,
            "content_year": self._signals.extract_content_year(url, body),
        }
