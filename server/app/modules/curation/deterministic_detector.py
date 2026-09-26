"""Detector determinista de calidad de contenido web — primera pasada sin LLM (9Q.3).

Deploy: edge.

Detecta sobre todo el sitio: páginas vacías/finas, stale, con error de crawl,
huérfanas (gone + documento aún ingerido) y supersesión temporal por patrón de URL + fecha.
Solo emite hallazgos vía ContentFindingRepo.upsert; NO muta HubCrawledPage.superseded
(eso lo hace el job 9Q.5 al consolidar).
"""
from __future__ import annotations

import re
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlparse

from server.app.modules.curation.contracts import ContentFinding

_YEAR_SEG = re.compile(r"/((?:19|20)\d{2})(?=/|$)")

#: Un curso académico como segmento de ruta: `/23-24/`, `/2023-24/`, `/2023-2024/`. Que los dos
#: números sean consecutivos lo comprueba `_sin_curso`; el patrón solo los localiza.
_CURSO_SEG = re.compile(r"/((?:19|20)?\d{2})-((?:19|20)?\d{2})(?=/|$)")

#: Qué se puede afirmar según la causa del fallo de rastreo (RAS.3). Lo que no se clasificó —las
#: páginas rastreadas antes de esto— conserva la severidad de antes: no se le atribuye una causa.
_SEVERIDAD_DEL_ERROR: dict[str | None, str] = {
    "not_found": "warning",     # el enlace apunta a algo que ya no está: hay que depurarlo
    "client_error": "warning",  # 403, 401: el servidor contesta, pero no sirve la página
    "transient": "info",        # red o servidor caído: no dice nada de la página
}


def _strip_year_segments(path: str) -> str:
    """Quita todos los segmentos de año de un path URL, incluidos los cursos académicos."""
    normalized = _CURSO_SEG.sub(_sin_curso, _YEAR_SEG.sub("", path))
    return normalized.rstrip("/") or "/"


def _sin_curso(coincidencia: re.Match[str]) -> str:
    """Quita `/23-24/` sólo si de verdad es un curso académico: dos años consecutivos.

    Salió con el detector semántico de CUR.7: el archivo de formación transversal publica una página
    por curso —`/23-24/`, `/24-25/`, `/25-26/`— y con la identidad de serie mirando sólo años de
    cuatro cifras, esas páginas no se agrupaban. Resultado: el juez las declaraba «contradicción»
    porque las fechas de impartición no coinciden, que es exactamente el falso positivo que CUR.2
    quitó del detector determinista. Se arregla en la identidad y sirve a los dos.

    La comprobación de consecutivos no es celo: sin ella, `/12-34/` y `/56-78/` agruparían páginas
    que no tienen nada que ver.
    """
    primero, segundo = coincidencia.group(1), coincidencia.group(2)
    inicio = int(primero) % 100
    fin = int(segundo) % 100
    return "" if (inicio + 1) % 100 == fin else coincidencia.group(0)


def _identidad_de_pagina(url: str) -> str:
    """La URL sin los parámetros que sólo son navegación (RAS.5).

    El conmutador de idioma del portal genera variantes de cada página que llevan la URL actual
    dentro (`?urlRedirect=…&url=…`). Sin quitarlas, todas comparten path y el agrupador las tomaba
    por versiones de un mismo recurso: 107 supersesiones falsas sobre una sola página.
    """
    from server.app.modules.curation.spider import url_de_pagina

    return url_de_pagina(url) or url


def _process_key(canonical_url: str | None, url: str) -> str:
    """Clave de proceso para agrupar versiones temporales de un mismo recurso.

    Solo participa en la agrupación si la URL contiene un segmento de año
    explícito (/2023/, /2024/…). URLs sin año reciben una clave única que
    no colisiona con ninguna versión con año del mismo path.
    """
    base = _identidad_de_pagina(canonical_url or url)
    parsed = urlparse(base)
    path = parsed.path
    # Un año de cuatro cifras o un curso académico. Sólo mirar el primero dejaba fuera el archivo
    # de cursos del portal (`/23-24/`), que es una serie tan clara como los acuerdos por año.
    if _strip_year_segments(path) == (path.rstrip("/") or "/"):
        # Sin año en la URL: clave única, no participa en grupos de supersesión.
        #
        # RAS.5 — decía «única» y no lo era: sólo llevaba el path, así que `http://…/normestudi/`
        # y `https://…/normestudi/` —la misma página servida por los dos esquemas— caían en el
        # mismo grupo y una salía «superseded» por la otra. 191 avisos falsos en el primer
        # rastreo real. Con el esquema y el host dentro, dos URLs distintas nunca se agrupan si
        # no comparten un año.
        return f"__no_year__{parsed.scheme}://{parsed.netloc}{path.rstrip('/') or '/'}"
    return _strip_year_segments(path)


def _effective_date(page: Any, now: datetime) -> datetime:
    """La fecha con la que se ordenan las versiones de un grupo.

    **Es una cadena de prioridad, no un `max()`.** Hacía `max()` sobre una lista que mezclaba
    fechas del contenido con `first_seen_at` —cuándo vimos la página por primera vez—, y como esa
    última es de hoy para todo lo recién rastreado, **ganaba siempre**: las nueve versiones de una
    serie salían con la misma fecha y el año dejaba de contar. Se vio ordenando una serie de 2022,
    2023 y 2024 y obteniendo 2022 como «la más reciente».

    `first_seen_at` es el último recurso: sirve cuando no se sabe nada del contenido, y sólo
    entonces.
    """
    if getattr(page, "content_published_at", None):
        return page.content_published_at
    if page.sitemap_lastmod:
        return page.sitemap_lastmod
    if page.http_last_modified:
        return page.http_last_modified
    if page.content_year:
        return datetime(page.content_year, 1, 1, tzinfo=timezone.utc)
    if getattr(page, "first_seen_at", None):
        return page.first_seen_at
    return datetime.min.replace(tzinfo=timezone.utc)


def _content_date(page: Any) -> tuple[datetime | None, str | None]:
    """Fecha de contenido para evaluar `stale`, y **de dónde sale** (RAS.5).

    Un año mencionado en el texto **no es** una fecha de publicación. Medido en el primer rastreo
    real: el portal no declara `Last-Modified`, ni `ETag`, ni publica `sitemap.xml`, así que la
    fecha salía del año más reciente citado en el cuerpo —una página menciona 1925, 2010, 2016,
    2021, 2024 y 2071— y eso marcaba como antiguas **303 de 400 páginas**. Un año en la URL sí es
    una señal del portal: así versiona sus documentos (`/2019/`, `/pext/19-20/`).
    """
    # CUR.1 — la que publica la propia página gana a todas: es la única que dice cuándo se
    # actualizó el contenido, y no cuándo el servidor sirvió el fichero.
    if getattr(page, "content_published_at", None):
        return page.content_published_at, "page_date"
    if page.sitemap_lastmod:
        return page.sitemap_lastmod, "sitemap_lastmod"
    if page.http_last_modified:
        return page.http_last_modified, "http_last_modified"
    if page.content_year and _YEAR_SEG.search(urlparse(page.url or "").path):
        return datetime(page.content_year, 1, 1, tzinfo=timezone.utc), "url_year"
    return None, None


class DeterministicQualityDetector:
    """Emite hallazgos deterministas sobre las páginas de un sitio."""

    def __init__(
        self,
        session: Any,
        *,
        finding_repo: Any,
        thin_token_threshold: int = 120,
        stale_days: int = 365,
        version_series_policy: str = "series",
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self._session = session
        self._repo = finding_repo
        self._thin_threshold = thin_token_threshold
        self._stale_days = stale_days
        # CUR.2.1 — qué significa un grupo de versiones por año **en este sitio**: series todas
        # vigentes, la nueva deroga a la vieja, o el año no significa nada. Lo decide la
        # configuración del sitio, no el código: dependía de cómo publica un portal concreto.
        self._version_series_policy = version_series_policy
        self._now_fn = now_fn or (lambda: datetime.now(timezone.utc))

    async def analyze(self, site_id: uuid.UUID) -> list[ContentFinding]:
        from server.app.modules.agents_hub.database.operational_models import (
            HubCrawledPage,
            HubDocument,
        )
        from sqlalchemy import select

        now = self._now_fn()
        findings: list[ContentFinding] = []

        # recorrido-acotado: el detector COMPARA unas paginas con otras -supersesiones,
        # duplicados, huerfanas-, asi que necesita el conjunto completo del sitio; paginarlo
        # daria resultados distintos segun el lote. El sitio mayor tiene 352 paginas
        # (medido el 2026-09-26). Revisar si alguno pasa de unos pocos miles: entonces esto
        # se procesa por lotes con estado, no se pagina (issue #159).
        stmt = select(HubCrawledPage).where(HubCrawledPage.site_id == site_id)
        stmt._model_hint = "page"  # type: ignore[attr-defined]
        result = await self._session.execute(stmt)
        pages: list = result.scalars().all()

        # Cargar documentos ingeridos cuyo crawled_page_id apunte a páginas gone
        gone_ids = {p.id for p in pages if p.status == "gone"}
        orphan_page_ids: set[uuid.UUID] = set()
        if gone_ids:
            doc_stmt = select(HubDocument).where(HubDocument.crawled_page_id.in_(gone_ids))
            doc_stmt._model_hint = "document"  # type: ignore[attr-defined]
            doc_result = await self._session.execute(doc_stmt)
            for doc in doc_result.scalars().all():
                orphan_page_ids.add(doc.crawled_page_id)

        # CUR.2 — primero los hallazgos **de grupo**, porque son los específicos y se comen a los
        # genéricos: una página que pertenece a una serie anual o a un par de duplicados no vuelve a
        # salir como «desactualizada». Era la queja literal del usuario: «no deberían aparecer en
        # los dos apartados».
        de_grupo = await self._check_grupos(pages, site_id, now)
        # Los ids viajan como texto en la señal —tiene que poder serializarse a JSON—, así que la
        # comparación también. Compararlos con el `UUID` de la página no coincidía nunca y la
        # deduplicación no hacía nada: la misma página seguía saliendo en dos apartados, que era
        # justo lo que había que arreglar.
        paginas_ya_dichas: set[str] = set()
        for f in de_grupo:
            await self._repo.upsert(f)
            findings.append(f)
            paginas_ya_dichas.update(str(p) for p in f.signal.get("page_ids", []))

        for page in pages:
            if str(page.id) in paginas_ya_dichas:
                continue
            page_findings = await self._check_page(page, site_id, now, orphan_page_ids)
            for f in page_findings:
                await self._repo.upsert(f)
                findings.append(f)

        return findings

    async def _check_grupos(
        self, pages: list[Any], site_id: uuid.UUID, now: datetime
    ) -> list[ContentFinding]:
        """Los hallazgos que hablan de **varias** páginas a la vez: series y duplicados."""
        return [
            *await self._check_series_de_versiones(pages, site_id, now),
            *self._check_duplicados_exactos(pages, site_id, now),
        ]

    async def _check_page(
        self,
        page: Any,
        site_id: uuid.UUID,
        now: datetime,
        orphan_page_ids: set[uuid.UUID],
    ) -> list[ContentFinding]:
        results: list[ContentFinding] = []

        # RAS.5 — una página que no se pudo descargar no tiene contenido **porque no se leyó**, y
        # eso ya lo dice `crawl_error`. En el primer rastreo real, los tres 404 salían además como
        # `empty` **crítico**: dos afirmaciones sobre el mismo hecho, y la segunda falsa.
        if page.status == "error":
            return self._otros_hallazgos(page, site_id, now, orphan_page_ids)

        empty = (
            page.markdown_content is None
            or not page.markdown_content.strip()
            or page.token_count == 0
        )

        # RAS.2 — si la página no se pudo leer sin renderizar, ni «vacía» ni «pobre» son
        # afirmaciones sostenibles: las dos hablan de la página, y lo que pasó es que el
        # rastreador no la vio. Lo único cierto es que hace falta un navegador para leerla.
        senales_de_render = list(getattr(page, "render_signals", None) or [])
        if senales_de_render and (
            empty
            or (page.token_count is not None and page.token_count < self._thin_threshold)
        ):
            return [self._finding(
                site_id=site_id,
                finding_type="needs_javascript",
                severity="warning",
                confidence=1.0,
                page_id=page.id,
                source_url=page.url,
                signal={"render_signals": senales_de_render,
                        "token_count": page.token_count},
                now=now,
            )] + self._otros_hallazgos(page, site_id, now, orphan_page_ids)

        if empty:
            results.append(self._finding(
                site_id=site_id,
                finding_type="empty",
                severity="critical",
                confidence=1.0,
                page_id=page.id,
                source_url=page.url,
                signal={},
                now=now,
            ))
        elif page.token_count is not None and page.token_count < self._thin_threshold:
            results.append(self._finding(
                site_id=site_id,
                finding_type="thin",
                severity="warning",
                confidence=1.0,
                page_id=page.id,
                source_url=page.url,
                signal={"token_count": page.token_count, "threshold": self._thin_threshold},
                now=now,
            ))

        results.extend(self._otros_hallazgos(page, site_id, now, orphan_page_ids))
        return results

    def _otros_hallazgos(
        self,
        page: Any,
        site_id: uuid.UUID,
        now: datetime,
        orphan_page_ids: set[uuid.UUID],
    ) -> list[ContentFinding]:
        """Lo que no depende de si la página se pudo leer: error de rastreo, antigüedad, huérfana."""
        results: list[ContentFinding] = []

        if page.status == "error":
            # RAS.3 — la severidad depende de qué se puede concluir. Un 404 es una respuesta del
            # servidor: el enlace apunta a algo que ya no está, y eso hay que depurarlo. Un 5xx o
            # un `timeout` tras varios intentos no dice nada de la página, así que no puede ser
            # crítico ni mezclarse con los hallazgos de contenido.
            clase = getattr(page, "error_kind", None)
            results.append(self._finding(
                site_id=site_id,
                finding_type="crawl_error",
                severity=_SEVERIDAD_DEL_ERROR.get(clase, "critical"),
                confidence=1.0,
                page_id=page.id,
                source_url=page.url,
                signal={
                    "error_message": page.error_message or "",
                    "kind": clase,
                    "attempts": getattr(page, "error_attempts", None),
                },
                now=now,
            ))

        content_date, origen = _content_date(page)
        if content_date is not None:
            age_days = (now - content_date).days
            if age_days > self._stale_days:
                results.append(self._finding(
                    site_id=site_id,
                    finding_type="stale",
                    severity="info",
                    confidence=1.0,
                    page_id=page.id,
                    source_url=page.url,
                    # De dónde sale la fecha: quien revisa tiene que poder distinguir «lo declara
                    # el servidor» de «lo dice la URL», que no valen lo mismo.
                    signal={
                        "date": content_date.isoformat(),
                        "age_days": age_days,
                        "source": origen,
                        # Quién mantiene la página: es lo que hace accionable el hallazgo.
                        "owner": getattr(page, "content_owner", None),
                        # CUR.8 — el umbral con el que se juzgó, para que el hallazgo se explique
                        # solo. Va dentro y no se lee de la configuración al pintar la pantalla:
                        # el criterio es de cada sitio y se puede cambiar, así que leerlo después
                        # daría el criterio de hoy en vez del que produjo este aviso.
                        "threshold": self._stale_days,
                    },
                    now=now,
                ))

        if page.id in orphan_page_ids:
            results.append(self._finding(
                site_id=site_id,
                finding_type="orphan_page",
                severity="warning",
                confidence=1.0,
                page_id=page.id,
                source_url=page.url,
                signal={},
                now=now,
            ))

        return results

    async def _check_series_de_versiones(
        self,
        pages: list[Any],
        site_id: uuid.UUID,
        now: datetime,
    ) -> list[ContentFinding]:
        """Las versiones por año de un mismo recurso: **un hallazgo por grupo** (CUR.2).

        Antes esto emitía un `superseded` por cada versión antigua —«superada por la de 2025»—, y el
        usuario aportó el dato del dominio que lo tumba: el portal publica acuerdos y actas por año y
        **todos siguen vigentes**. Lo único cierto es que la serie existe, así que se dice una vez,
        con severidad informativa y con las URLs y sus fechas dentro para que una persona decida si
        sobran las antiguas.
        """
        groups: dict[str, list] = defaultdict(list)
        for page in pages:
            # RAS.5 — una página que no se pudo leer no entra en ningún grupo: sin fecha de nada, el
            # orden cae en `first_seen_at` —de hace un instante— y quedaría como la más reciente.
            if getattr(page, "status", "active") == "error":
                continue
            key = _process_key(page.canonical_url, page.url)
            if key.startswith("__no_year__"):
                continue
            groups[key].append(page)

        if self._version_series_policy == "off":
            return []

        results: list[ContentFinding] = []
        for key, group in groups.items():
            if len(group) < 2:
                continue
            ordenadas = sorted(group, key=lambda p: _effective_date(p, now), reverse=True)

            if self._version_series_policy == "superseded":
                # En este sitio la nueva deroga a la vieja, así que sí hay algo que retirar y se
                # dice de cada una: es una lista de trabajo, no una advertencia sobre un grupo.
                vigente = ordenadas[0]
                for antigua in ordenadas[1:]:
                    results.append(self._finding(
                        site_id=site_id,
                        finding_type="superseded",
                        severity="warning",
                        confidence=1.0,
                        page_id=antigua.id,
                        related_page_id=vigente.id,
                        source_url=antigua.url,
                        signal={
                            "process_key": key,
                            "superseded_by": vigente.url,
                            "page_ids": [str(antigua.id)],
                            "effective_date_old": _effective_date(antigua, now).isoformat(),
                            "effective_date_new": _effective_date(vigente, now).isoformat(),
                        },
                        now=now,
                    ))
                continue

            results.append(self._finding(
                site_id=site_id,
                finding_type="version_series",
                severity="info",
                confidence=1.0,
                # Sin `page_id`: el hallazgo habla del grupo, no de una página. Las páginas van en
                # la señal, que es lo que permite además no repetirlas en otros apartados.
                source_url=ordenadas[0].url,
                signal={
                    "process_key": key,
                    "count": len(ordenadas),
                    "page_ids": [str(p.id) for p in ordenadas],
                    "versions": [
                        {
                            "url": p.url,
                            "date": _effective_date(p, now).isoformat(),
                            "owner": getattr(p, "content_owner", None),
                        }
                        for p in ordenadas
                    ],
                },
                now=now,
            ))
        return results

    def _check_duplicados_exactos(
        self,
        pages: list[Any],
        site_id: uuid.UUID,
        now: datetime,
    ) -> list[ContentFinding]:
        """Dos URLs distintas con el **mismo contenido**, juntas y con sus fechas (CUR.2).

        Pedido por el usuario: «si hay dos páginas con el mismo contenido, se mostraran las dos url
        con las fechas de las dos como hallazgo». Aquí sí sobra una: es duplicado, no serie. Y se
        compara por `content_hash`, que es un hecho, no por parecido semántico —eso es del detector
        semántico—.
        """
        por_hash: dict[str, list] = defaultdict(list)
        for page in pages:
            if getattr(page, "status", "active") == "error":
                continue
            hash_ = getattr(page, "content_hash", None)
            if not hash_:
                continue
            por_hash[hash_].append(page)

        results: list[ContentFinding] = []
        for hash_, group in por_hash.items():
            if len(group) < 2:
                continue
            ordenadas = sorted(group, key=lambda p: _effective_date(p, now), reverse=True)
            results.append(self._finding(
                site_id=site_id,
                finding_type="duplicate",
                severity="warning",
                confidence=1.0,
                source_url=ordenadas[0].url,
                signal={
                    "content_hash": hash_,
                    "count": len(ordenadas),
                    "page_ids": [str(p.id) for p in ordenadas],
                    "versions": [
                        {
                            "url": p.url,
                            "date": _effective_date(p, now).isoformat(),
                            "owner": getattr(p, "content_owner", None),
                        }
                        for p in ordenadas
                    ],
                },
                now=now,
            ))
        return results

    @staticmethod
    def _finding(
        *,
        site_id: uuid.UUID,
        finding_type: str,
        severity: str,
        confidence: float,
        page_id: uuid.UUID | None = None,
        related_page_id: uuid.UUID | None = None,
        source_url: str | None = None,
        signal: dict,
        now: datetime,
    ) -> ContentFinding:
        return ContentFinding(
            id=uuid.uuid4(),
            site_id=site_id,
            finding_type=finding_type,  # type: ignore[arg-type]
            severity=severity,  # type: ignore[arg-type]
            confidence=confidence,
            detected_at=now,
            page_id=page_id,
            related_page_id=related_page_id,
            source_url=source_url,
            signal=signal,
        )
