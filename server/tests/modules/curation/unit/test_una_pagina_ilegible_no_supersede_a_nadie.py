"""Una página que no se pudo leer no puede ser «la versión vigente» (RAS.5).

Último hallazgo falso del rastreo real, y el más sutil. El agrupador de supersesión ordena las
versiones de un mismo recurso por su fecha efectiva, y cuando una página no tiene ninguna fecha usa
`first_seen_at` —cuándo la vimos por primera vez—. Una página que **falló al descargarse** no tiene
fecha de nada… y su `first_seen_at` es de hace un instante, así que quedaba como la más nueva del
grupo y declaraba superadas a todas las demás.

Se vio en el informe: ocho avisos «superseded», todos con `superseded_by` apuntando a
`/normativa/acordacded/2017/`, que en ese rastreo había fallado por un problema de red local. O sea
que el acuerdo de 2017 «superaba» a los de 2023, 2024 y 2025.

De una página ilegible no se puede concluir nada sobre su contenido, y eso incluye si es la vigente.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pytest

from server.app.modules.curation.deterministic_detector import DeterministicQualityDetector

_AHORA = datetime(2026, 8, 18, tzinfo=timezone.utc)
_BASE = "https://www.uji.es/centres/escola-doctorat/base/escola/normativa/acordacded"


@dataclass
class _Pagina:
    url: str
    content_year: int | None = None
    status: str = "active"
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    markdown_content: str | None = "Acord del consell. " * 40
    token_count: int | None = 300
    error_message: str | None = None
    error_kind: str | None = None
    error_attempts: int | None = None
    canonical_url: str | None = None
    sitemap_lastmod: datetime | None = None
    http_last_modified: datetime | None = None
    first_seen_at: datetime | None = _AHORA
    render_signals: list[dict] | None = None


class _Repo:
    async def upsert(self, finding: Any) -> Any:
        return finding


class _Sesion:
    def __init__(self, paginas: list[_Pagina]) -> None:
        self._paginas = paginas

    async def execute(self, stmt: Any) -> Any:
        filas = self._paginas if getattr(stmt, "_model_hint", "page") == "page" else []

        class _R:
            def scalars(self_inner) -> Any:
                return self_inner

            def all(self_inner) -> list:
                return filas

        return _R()


async def _hallazgos(paginas: list[_Pagina]) -> list[Any]:
    detector = DeterministicQualityDetector(
        session=_Sesion(paginas), finding_repo=_Repo(), now_fn=lambda: _AHORA
    )
    return await detector.analyze(uuid.uuid4())


@pytest.mark.asyncio
async def test_una_pagina_que_fallo_al_descargarse_no_supersede_a_las_demas():
    paginas = [
        _Pagina(url=f"{_BASE}/2017/", content_year=None, status="error",
                error_kind="transient", markdown_content=None, token_count=None),
        _Pagina(url=f"{_BASE}/2024/", content_year=2024),
        _Pagina(url=f"{_BASE}/2025/", content_year=2025),
    ]

    supersesiones = [h for h in await _hallazgos(paginas) if h.finding_type == "superseded"]

    assert all("2017" not in (h.signal.get("superseded_by") or "") for h in supersesiones), (
        "el acuerdo de 2017, que ni se pudo descargar, declaraba superados los de 2024 y 2025"
    )


@pytest.mark.asyncio
async def test_entre_las_que_si_se_leyeron_el_grupo_sigue_detectandose():
    """El arreglo no puede desactivar el hallazgo: es el que el módulo existe para dar.

    Desde CUR.2 el grupo por años se dice como **serie** y no como supersesión, porque en este
    portal las versiones antiguas siguen vigentes.
    """
    paginas = [
        _Pagina(url=f"{_BASE}/2024/", content_year=2024),
        _Pagina(url=f"{_BASE}/2025/", content_year=2025),
    ]

    series = [h for h in await _hallazgos(paginas) if h.finding_type == "version_series"]

    assert len(series) == 1
    assert series[0].signal["versions"][0]["url"].endswith("/2025/")


@pytest.mark.asyncio
async def test_un_grupo_donde_solo_queda_una_legible_no_produce_aviso():
    paginas = [
        _Pagina(url=f"{_BASE}/2024/", content_year=2024, status="error",
                error_kind="not_found", markdown_content=None, token_count=None),
        _Pagina(url=f"{_BASE}/2025/", content_year=2025),
    ]

    assert [h for h in await _hallazgos(paginas) if h.finding_type == "superseded"] == []
