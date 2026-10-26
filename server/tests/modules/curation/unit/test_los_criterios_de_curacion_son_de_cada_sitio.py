"""Los criterios de curación son de cada sitio, no del código (CUR.2.1).

Pregunta del usuario al revisar el bloque: la aplicación se instala en la UJI pero está diseñada
multiorganización, y varios ajustes de curación estaban entrando **en el código** a partir de cómo es
un portal concreto.

Comprobado: el aislamiento de datos sí es por organización —cada sitio cuelga de `organizacion_id` y
los routers lo verifican—, y todo lo del rastreo ya era configuración del sitio. Pero **los criterios
de juicio eran globales**:

* `stale_days=365` y `thin_token_threshold=120` los ponía el constructor y **nadie los pasaba**: el
  despachador construía el detector con los valores por defecto.
* CUR.2 fijó globalmente que una serie por años **no** supersede. Para la UJI es cierto, porque lo
  dijo quien conoce el contenido; para un portal que versiona convocatorias es falso. Una suposición
  global cambiada por otra.

Es la misma regla que el proyecto ya aplica al vocabulario del corpus: **el criterio es dato, no
código**. Y la prueba de que la multiorganización es real es la última de este fichero: dos sitios
con criterios distintos, sobre páginas idénticas, dan hallazgos distintos.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pytest

from server.app.modules.curation.deterministic_detector import DeterministicQualityDetector
from server.app.modules.curation.selection_contracts import CrawlConfig

_AHORA = datetime(2026, 8, 19, tzinfo=timezone.utc)


@dataclass
class _Pagina:
    url: str
    content_year: int | None = None
    content_published_at: datetime | None = None
    content_hash: str | None = None
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    markdown_content: str | None = "Contenido. " * 30
    token_count: int | None = 300
    status: str = "active"
    error_message: str | None = None
    error_kind: str | None = None
    error_attempts: int | None = None
    canonical_url: str | None = None
    sitemap_lastmod: datetime | None = None
    http_last_modified: datetime | None = None
    content_owner: str | None = None
    first_seen_at: datetime | None = None
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


async def _tipos(paginas: list[_Pagina], **criterios: Any) -> list[str]:
    detector = DeterministicQualityDetector(
        session=_Sesion(paginas), finding_repo=_Repo(), now_fn=lambda: _AHORA, **criterios
    )
    return [h.finding_type for h in await detector.analyze(uuid.uuid4())]


# ---------------------------------------------------------------------------
# El contrato: los criterios se declaran por sitio
# ---------------------------------------------------------------------------


def test_el_sitio_declara_sus_umbrales_y_su_politica_de_series():
    config = CrawlConfig(
        stale_days=1095, thin_min_tokens=40, version_series_policy="superseded"
    )

    assert config.stale_days == 1095
    assert config.thin_min_tokens == 40
    assert config.version_series_policy == "superseded"


def test_los_defectos_son_los_de_hoy_para_no_cambiarle_el_criterio_a_nadie():
    config = CrawlConfig()

    assert config.stale_days == 365
    assert config.thin_min_tokens == 120
    assert config.version_series_policy == "series"


def test_una_politica_de_series_inventada_se_rechaza_al_guardarla():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        CrawlConfig(version_series_policy="lo_que_sea")


# ---------------------------------------------------------------------------
# El detector los respeta
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_un_portal_de_normativa_puede_pedir_tres_anos_de_margen():
    """Una norma de hace dos años no está «desactualizada»; una noticia sí."""
    pagina = _Pagina(
        url="https://ejemplo.org/norma/",
        content_published_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
    )

    assert "stale" in await _tipos([pagina], stale_days=365)
    assert "stale" not in await _tipos([pagina], stale_days=1095)


@pytest.mark.asyncio
async def test_un_portal_con_fichas_cortas_puede_bajar_el_umbral_de_pobreza():
    pagina = _Pagina(url="https://ejemplo.org/ficha/", markdown_content="Ficha breve.",
                     token_count=60)

    assert "thin" in await _tipos([pagina], thin_token_threshold=120)
    assert "thin" not in await _tipos([pagina], thin_token_threshold=40)


@pytest.mark.asyncio
async def test_un_portal_donde_la_version_nueva_si_deroga_a_la_vieja():
    """La UJI publica series que siguen vigentes; otro portal versiona convocatorias. El código no
    puede decidir eso por las dos."""
    paginas = [
        _Pagina(url="https://ejemplo.org/convocatoria/2024/", content_year=2024),
        _Pagina(url="https://ejemplo.org/convocatoria/2025/", content_year=2025),
    ]

    como_serie = await _tipos(paginas, version_series_policy="series")
    como_supersesion = await _tipos(paginas, version_series_policy="superseded")

    assert "version_series" in como_serie
    assert "superseded" not in como_serie
    assert "superseded" in como_supersesion
    assert "version_series" not in como_supersesion


@pytest.mark.asyncio
async def test_un_portal_puede_apagar_el_agrupado_por_anos():
    """Si el año de la URL no significa nada en ese sitio, el hallazgo es sólo ruido."""
    paginas = [
        _Pagina(url="https://ejemplo.org/x/2024/", content_year=2024),
        _Pagina(url="https://ejemplo.org/x/2025/", content_year=2025),
    ]

    tipos = await _tipos(paginas, version_series_policy="off")

    assert "version_series" not in tipos
    assert "superseded" not in tipos


# ---------------------------------------------------------------------------
# La prueba de que la multiorganización es real
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dos_sitios_con_criterios_distintos_dan_hallazgos_distintos():
    """Las mismas páginas, dos organizaciones, dos criterios: dos informes. Es lo que separa
    «configurable» de «adaptado a un cliente»."""
    paginas = [
        _Pagina(
            url="https://ejemplo.org/acord/2023/",
            content_year=2023,
            content_published_at=datetime(2023, 5, 1, tzinfo=timezone.utc),
        ),
        _Pagina(
            url="https://ejemplo.org/acord/2024/",
            content_year=2024,
            content_published_at=datetime(2024, 5, 1, tzinfo=timezone.utc),
        ),
    ]

    como_la_uji = await _tipos(paginas, stale_days=365, version_series_policy="series")
    otra_casa = await _tipos(paginas, stale_days=1460, version_series_policy="off")

    # En la UJI: un aviso de serie, y ninguna de las dos páginas marcada por antigüedad, porque el
    # hallazgo de grupo se come al genérico.
    assert como_la_uji == ["version_series"]
    # En la otra casa, con cuatro años de margen y sin agrupar por años: nada que revisar.
    assert otra_casa == []


# ---------------------------------------------------------------------------
# Y lo que NO se puede desactivar por configuración
# ---------------------------------------------------------------------------


def test_lo_que_no_es_criterio_sino_honestidad_no_es_configurable():
    """La cortesía y «no acusar de lo que no se pudo leer» no son preferencias de un portal: valen
    para cualquiera y no deben poder apagarse desde la configuración de curación."""
    campos = set(CrawlConfig.model_fields)

    for nunca in ("emit_empty_for_errors", "accuse_unreadable", "skip_retry_classification"):
        assert nunca not in campos


@pytest.mark.asyncio
async def test_una_pagina_con_error_nunca_se_acusa_por_mucho_que_se_configure():
    pagina = _Pagina(
        url="https://ejemplo.org/roto/", markdown_content=None, token_count=None,
        status="error", error_kind="not_found",
    )

    tipos = await _tipos([pagina], stale_days=1, thin_token_threshold=100_000)

    assert "empty" not in tipos
    assert "thin" not in tipos
    assert "crawl_error" in tipos
