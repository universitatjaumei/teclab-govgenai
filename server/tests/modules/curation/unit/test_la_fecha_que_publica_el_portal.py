"""La fecha y la unidad responsable que el portal ya publica (CUR.1).

`stale` se apoyaba en el año más reciente **citado en el texto** —303 de 400 páginas marcadas en el
primer rastreo real— y desde RAS.5 sólo en un año dentro de la URL. Pero el portal **publica la
fecha**, y estaba ahí desde el principio. Medido en
`https://www.uji.es/centres/escola-doctorat/base/doctorands/`:

    <div class="clockBarDate">
      <span>24/09/2025</span> | <span>Escola de Doctorat</span>
    </div>

Con esa fecha, «desactualizada» deja de ser una conjetura. Y la unidad responsable es justo lo que
hace accionable un informe de calidad: dice **a quién escribir**.

El selector va **en la configuración del sitio**, no en el código: el marcado es de este portal, y
hardcodearlo sería acoplar el módulo a un cliente, igual que hardcodear su URL.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from server.app.modules.curation.contenido_web import fecha_y_responsable

#: El marcado real del portal, recortado a lo que importa.
_PAGINA = (
    '<html><body><h1>Alumnat de doctorat</h1>'
    '<div class="bgGreyClaro"><div class="wrap"><div class="clockBar">'
    '<div class="dateSocialContainer"><div class="clockBarDate margin-right-1">'
    "<span>24/09/2025</span> | <span>Escola de Doctorat</span>"
    '</div><div class="social-links">Compartir</div></div>'
    "</div></div></div>"
    "<p>Contenido de la pagina.</p></body></html>"
)

_SELECTOR = ".clockBarDate"


def test_extrae_la_fecha_que_publica_la_pagina():
    fecha, _responsable = fecha_y_responsable(_PAGINA, _SELECTOR, "%d/%m/%Y")

    assert fecha == datetime(2025, 9, 24, tzinfo=timezone.utc)


def test_extrae_la_unidad_responsable_que_va_al_lado():
    """Es lo que convierte un hallazgo en algo accionable: dice a quién escribir."""
    _fecha, responsable = fecha_y_responsable(_PAGINA, _SELECTOR, "%d/%m/%Y")

    assert responsable == "Escola de Doctorat"


def test_sin_selector_configurado_no_se_inventa_nada():
    """El comportamiento por defecto no cambia: un sitio que no lo declara sigue como estaba."""
    assert fecha_y_responsable(_PAGINA, None, "%d/%m/%Y") == (None, None)


def test_un_selector_que_no_encuentra_nada_no_revienta():
    fecha, responsable = fecha_y_responsable(_PAGINA, ".noExisteEsteBloque", "%d/%m/%Y")

    assert (fecha, responsable) == (None, None)


def test_un_selector_invalido_tampoco_revienta():
    """Un selector mal escrito no puede tumbar el rastreo de un sitio entero."""
    assert fecha_y_responsable(_PAGINA, "((((", "%d/%m/%Y") == (None, None)


def test_una_fecha_en_otro_formato_se_lee_con_el_formato_declarado():
    html = '<html><body><div class="fecha"><span>2025-09-24</span></div></body></html>'

    fecha, _ = fecha_y_responsable(html, ".fecha", "%Y-%m-%d")

    assert fecha == datetime(2025, 9, 24, tzinfo=timezone.utc)


def test_un_texto_que_no_es_fecha_no_se_fuerza():
    html = '<html><body><div class="clockBarDate"><span>Sin fecha</span></div></body></html>'

    fecha, _ = fecha_y_responsable(html, ".clockBarDate", "%d/%m/%Y")

    assert fecha is None


def test_una_fecha_imposible_se_descarta_en_vez_de_desplazar_el_ano():
    """`31/02/2025` no existe; aceptarla daría una antigüedad inventada."""
    html = '<html><body><div class="clockBarDate"><span>31/02/2025</span></div></body></html>'

    fecha, _ = fecha_y_responsable(html, ".clockBarDate", "%d/%m/%Y")

    assert fecha is None


def test_la_fecha_sale_aunque_no_haya_responsable():
    html = '<html><body><div class="clockBarDate"><span>24/09/2025</span></div></body></html>'

    fecha, responsable = fecha_y_responsable(html, ".clockBarDate", "%d/%m/%Y")

    assert fecha == datetime(2025, 9, 24, tzinfo=timezone.utc)
    assert responsable is None


# ---------------------------------------------------------------------------
# El contrato de configuración
# ---------------------------------------------------------------------------


def test_el_sitio_puede_declarar_su_selector_de_fecha():
    from server.app.modules.curation.selection_contracts import CrawlConfig

    config = CrawlConfig(content_date_selector=".clockBarDate", content_date_format="%d/%m/%Y")

    assert config.content_date_selector == ".clockBarDate"
    assert config.content_date_format == "%d/%m/%Y"


def test_por_defecto_ningun_sitio_declara_selector():
    """El marcado es de un portal concreto: el defecto no puede ser el de la UJI."""
    from server.app.modules.curation.selection_contracts import CrawlConfig

    assert CrawlConfig().content_date_selector is None


def test_un_formato_de_fecha_absurdo_se_rechaza_al_guardarlo():
    """Si no, el fallo sale en cada página del rastreo y lejos del formulario."""
    import pytest
    from pydantic import ValidationError

    from server.app.modules.curation.selection_contracts import CrawlConfig

    with pytest.raises(ValidationError):
        CrawlConfig(content_date_selector=".x", content_date_format="no es un formato")


# ---------------------------------------------------------------------------
# Lo que el detector hace con ella
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stale_usa_la_fecha_de_la_pagina_y_lo_dice():
    import uuid
    from dataclasses import dataclass, field
    from typing import Any

    from server.app.modules.curation.deterministic_detector import (
        DeterministicQualityDetector,
    )

    ahora = datetime(2026, 8, 19, tzinfo=timezone.utc)

    @dataclass
    class _Pagina:
        url: str = "https://www.uji.es/centres/escola-doctorat/base/doctorands/"
        id: uuid.UUID = field(default_factory=uuid.uuid4)
        markdown_content: str | None = "Contenido suficiente. " * 30
        token_count: int | None = 300
        status: str = "active"
        error_message: str | None = None
        error_kind: str | None = None
        error_attempts: int | None = None
        canonical_url: str | None = None
        sitemap_lastmod: datetime | None = None
        http_last_modified: datetime | None = None
        content_year: int | None = None
        content_published_at: datetime | None = datetime(2024, 1, 15, tzinfo=timezone.utc)
        content_owner: str | None = "Escola de Doctorat"
        first_seen_at: datetime | None = None
        render_signals: list[dict] | None = None

    class _Repo:
        async def upsert(self, finding: Any) -> Any:
            return finding

    class _Sesion:
        def __init__(self, paginas: list) -> None:
            self._paginas = paginas

        async def execute(self, stmt: Any) -> Any:
            filas = self._paginas if getattr(stmt, "_model_hint", "page") == "page" else []

            class _R:
                def scalars(self_inner) -> Any:
                    return self_inner

                def all(self_inner) -> list:
                    return filas

            return _R()

    detector = DeterministicQualityDetector(
        session=_Sesion([_Pagina()]), finding_repo=_Repo(), now_fn=lambda: ahora
    )

    hallazgos = await detector.analyze(uuid.uuid4())

    stale = next(h for h in hallazgos if h.finding_type == "stale")
    assert stale.signal["source"] == "page_date"
    assert stale.signal["date"].startswith("2024-01-15")
    assert stale.signal["owner"] == "Escola de Doctorat"
