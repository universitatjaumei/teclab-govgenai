"""Un 404 y un timeout no dicen lo mismo, y el informe no puede confundirlos (RAS.3).

Un 404 es una respuesta: el enlace apunta a algo que ya no está, y eso es información útil para
depurar el portal. Un 500 o un `timeout` es un fallo del que **no se puede concluir nada** sobre la
página: puede estar perfecta y ser la red. Los dos producían el mismo `crawl_error` **crítico**.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pytest

from server.app.modules.curation.deterministic_detector import DeterministicQualityDetector


@dataclass
class _Pagina:
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    url: str = "https://www.uji.es/centres/escola-doctorat/vieja"
    markdown_content: str | None = None
    token_count: int | None = None
    status: str = "error"
    error_message: str | None = None
    canonical_url: str | None = None
    sitemap_lastmod: datetime | None = None
    http_last_modified: datetime | None = None
    content_year: int | None = None
    first_seen_at: datetime | None = None
    render_signals: list[dict] | None = None
    error_kind: str | None = None
    error_attempts: int | None = None


class _Repo:
    def __init__(self) -> None:
        self.guardados: list[Any] = []

    async def upsert(self, finding: Any) -> Any:
        self.guardados.append(finding)
        return finding


class _Sesion:
    def __init__(self, paginas: list[_Pagina]) -> None:
        self._paginas = paginas

    async def execute(self, stmt: Any) -> Any:
        hint = getattr(stmt, "_model_hint", "page")
        filas = self._paginas if hint == "page" else []

        class _R:
            def scalars(self_inner) -> Any:
                return self_inner

            def all(self_inner) -> list:
                return filas

        return _R()


async def _analizar(pagina: _Pagina) -> list[Any]:
    detector = DeterministicQualityDetector(
        session=_Sesion([pagina]),
        finding_repo=_Repo(),
        now_fn=lambda: datetime(2026, 8, 18, tzinfo=timezone.utc),
    )
    return await detector.analyze(uuid.uuid4())


@pytest.mark.asyncio
async def test_un_404_dice_que_el_contenido_ya_no_esta():
    hallazgos = await _analizar(_Pagina(
        error_message="404 Not Found", error_kind="not_found", error_attempts=1
    ))

    error = next(h for h in hallazgos if h.finding_type == "crawl_error")
    assert error.signal["kind"] == "not_found"
    assert error.severity == "warning"


@pytest.mark.asyncio
async def test_un_fallo_de_red_no_afirma_nada_de_la_pagina_y_dice_los_intentos():
    hallazgos = await _analizar(_Pagina(
        error_message="se agotó el tiempo de espera", error_kind="transient", error_attempts=3
    ))

    error = next(h for h in hallazgos if h.finding_type == "crawl_error")
    assert error.signal["kind"] == "transient"
    assert error.signal["attempts"] == 3
    assert error.severity == "info", (
        "un fallo de red no puede ser crítico: no dice nada de la página"
    )


@pytest.mark.asyncio
async def test_sin_clasificar_el_error_se_sigue_avisando_pero_sin_inventar_la_causa():
    """Las páginas rastreadas antes de RAS.3 no tienen la clasificación: no se les atribuye una."""
    hallazgos = await _analizar(_Pagina(error_message="algo pasó", error_kind=None))

    error = next(h for h in hallazgos if h.finding_type == "crawl_error")
    assert error.signal.get("kind") in (None, "unknown")
