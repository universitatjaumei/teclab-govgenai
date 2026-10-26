"""Extracción de señales baratas de actualidad durante el crawl (9Q.2).

Deploy: edge.

Señales: Last-Modified/ETag (cabeceras HTTP), <link rel="canonical">,
año de contenido (path > texto) y mapa url→lastmod del sitemap.xml.
Todas toleran ausencia o malformación devolviendo None / {}.
"""
from __future__ import annotations

import logging

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Awaitable, Callable
from urllib.parse import urljoin

_log = logging.getLogger(__name__)

_CANONICAL_RE = re.compile(
    r'<link\b[^>]*\brel=["\']canonical["\'][^>]*\bhref=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_PATH_YEAR_RE = re.compile(r"/((?:19|20)\d{2})(?:/|$)")
_TEXT_YEAR_RE = re.compile(r"\b((?:19|20)\d{2})\b")
_MIN_YEAR = 1990


class CrawlSignalExtractor:
    """Extrae señales de frescura de una página rastreada. Sin estado, sin BD."""

    def extract_from_headers(self, headers: dict) -> dict:
        """Devuelve {http_last_modified, http_etag} desde cabeceras HTTP.

        Last-Modified se parsea según RFC 7231 (formato IMF-fixdate).
        Tolerante a ausencia o malformación.
        """
        lower = {k.lower(): v for k, v in headers.items()}

        last_modified: datetime | None = None
        raw_lm = lower.get("last-modified")
        if raw_lm:
            try:
                parsed = parsedate_to_datetime(raw_lm)
                if parsed is not None:
                    last_modified = (
                        parsed
                        if parsed.tzinfo is not None
                        else parsed.replace(tzinfo=timezone.utc)
                    )
            except (TypeError, ValueError):
                last_modified = None

        return {
            "http_last_modified": last_modified,
            "http_etag": lower.get("etag"),
        }

    def extract_canonical(self, html: str) -> str | None:
        """Devuelve el href del primer <link rel="canonical">, o None."""
        match = _CANONICAL_RE.search(html)
        return match.group(1).strip() if match else None

    def extract_content_year(self, url: str, text: str) -> int | None:
        """Año de contenido. Prioridad: año en el path > año más reciente plausible en texto.

        Años plausibles: [1990, año_actual + 1]. Fuera de rango → ignorados.
        """
        path_match = _PATH_YEAR_RE.search(url)
        if path_match:
            year = int(path_match.group(1))
            if self._is_plausible(year):
                return year

        candidates = [
            int(m) for m in _TEXT_YEAR_RE.findall(text) if self._is_plausible(int(m))
        ]
        return max(candidates) if candidates else None

    @staticmethod
    def _is_plausible(year: int) -> bool:
        current = datetime.now(timezone.utc).year
        return _MIN_YEAR <= year <= current + 1

    async def fetch_sitemap(
        self,
        url: str,
        fetch_fn: Callable[[str], Awaitable[str]],
    ) -> dict[str, datetime | None]:
        """Descarga y parsea un sitemap.xml una sola vez; mapea url→lastmod.

        - `url` puede ser un sitemap (.xml) o la base del sitio (se deriva /sitemap.xml).
        - Soporta sitemap index (<sitemapindex>): recorre cada sitemap hijo.
        - Falla en silencio ({}) si no se puede descargar o parsear.
        """
        sitemap_url = url if url.endswith(".xml") else urljoin(url + "/", "sitemap.xml")
        try:
            return await self._parse_sitemap(sitemap_url, fetch_fn, depth=0)
        except Exception:  # noqa: BLE001 — sin sitemap legible, el rastreo sigue por enlaces
            return {}

    async def _parse_sitemap(
        self,
        sitemap_url: str,
        fetch_fn: Callable[[str], Awaitable[str]],
        depth: int,
    ) -> dict[str, datetime | None]:
        if depth > 2:
            return {}

        body = await fetch_fn(sitemap_url)
        root = ET.fromstring(body)
        tag = _local_name(root.tag)

        result: dict[str, datetime | None] = {}

        if tag == "sitemapindex":
            for sitemap in root:
                loc = _child_text(sitemap, "loc")
                if not loc:
                    continue
                try:
                    result.update(await self._parse_sitemap(loc, fetch_fn, depth + 1))
                except Exception:  # noqa: BLE001 — un sitemap hijo roto no invalida los demás
                    _log.debug("Sitemap hijo %s ilegible; se sigue con el resto", loc, exc_info=True)
                    continue
            return result

        # urlset
        for url_el in root:
            loc = _child_text(url_el, "loc")
            if not loc:
                continue
            result[loc] = _parse_lastmod(_child_text(url_el, "lastmod"))
        return result


def _local_name(tag: str) -> str:
    """Tag sin namespace: '{ns}urlset' → 'urlset'."""
    return tag.rsplit("}", 1)[-1]


def _child_text(element: ET.Element, name: str) -> str | None:
    for child in element:
        if _local_name(child.tag) == name and child.text:
            return child.text.strip()
    return None


def _parse_lastmod(value: str | None) -> datetime | None:
    """Parsea un lastmod W3C (fecha o fecha-hora ISO 8601). None si falta/inválido."""
    if not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
