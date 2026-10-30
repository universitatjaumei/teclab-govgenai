"""#345 — una página de navegación no es contenido escaso.

Un usuario de la OPAQ auditó el apartado de la Escola de Doctorat y encontró 30 páginas en
«Escassa», muchas de ellas **nodos de navegación**: páginas con enlaces y sin texto propio, como
`/escola-doctorat/info-general/organitzacio/`. Una página así no es un defecto que corregir, es
estructura del portal; mezclada con las escasas de verdad, la cola se llena de ruido.

Bajar `thin_min_tokens` no lo arregla: esconde también las escasas de verdad. Y la jerarquía de las
URL tampoco: medido el 30-10 en producción, **ninguna** de las páginas de navegación del ejemplo
tenía páginas rastreadas bajo su ruta —enlazan a otras ramas del portal o a PDF—. Lo que las
distingue es lo que dice el usuario: que su texto son enlaces. El rastreo guarda el texto visible
sin las etiquetas, así que se guardan aparte los textos de los enlaces de la zona de contenido, y el
detector separa las líneas que son enlace de las que son texto propio.

**Calibrado con las 32 páginas «Escassa» de ese rastreo**, con el HTML del portal: las de
navegación tienen 0–6 tokens de texto propio y 4–8 líneas de enlace; las escasas de verdad —fichas
de curso con «Nom:», «Hores:» sin rellenar, páginas de vídeo, un contacto— 24 o más. De ahí los
valores por omisión: navegación con 20 tokens propios como mucho y 2 líneas de enlace como poco.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any

import pytest

from server.app.modules.curation.contenido_web import contenido_y_enlaces
from server.app.modules.curation.deterministic_detector import DeterministicQualityDetector

_AHORA = datetime(2026, 10, 30, tzinfo=timezone.utc)

#: Lo que queda guardado de `/comissio/Objectius/` tras quitar la plantilla, y sus enlaces.
_OBJECTIUS = "Objectius\nCursos 23/24-24/25\nCursos 25/26-26/27\nPresentació\nProgrames\nNormativa"
_ENLACES_DE_OBJECTIUS = [
    "Cursos 23/24-24/25", "Cursos 25/26-26/27", "Presentació", "Programes", "Normativa",
]

#: Una ficha de curso sin rellenar: es escasa de verdad, y tiene que seguir diciéndose.
_FICHA = (
    "Carrera investigadora\nNom: Carrera investigadora.\nHores:\nDates d'impartició:\n"
    "Idiomes d'impartició:\nPlaces oferides:\nTaxa: gratuït\nObjectiu:\nProfessorat:\n"
    "Accés als continguts\nDescarrega fitxa informativa\nVicerectorat d'Investigació\n"
    "Presentació\nProgrames"
)
_ENLACES_DE_LA_FICHA = [
    "Accés als continguts", "Descarrega fitxa informativa", "Presentació", "Programes",
]


@dataclass
class _Pagina:
    url: str
    markdown_content: str | None
    token_count: int | None
    textos_de_enlace: list[str] | None = None
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    status: str = "active"
    error_message: str | None = None
    error_kind: str | None = None
    error_attempts: int | None = None
    canonical_url: str | None = None
    sitemap_lastmod: datetime | None = None
    http_last_modified: datetime | None = None
    content_year: int | None = None
    content_published_at: datetime | None = None
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


async def _hallazgos(pagina: _Pagina, **criterios: Any) -> dict[str, Any]:
    detector = DeterministicQualityDetector(
        session=_Sesion([pagina]), finding_repo=_Repo(), now_fn=lambda: _AHORA, **criterios
    )
    return {h.finding_type: h for h in await detector.analyze(uuid.uuid4())}


def _objectius(**cambios: Any) -> _Pagina:
    return replace(_Pagina(
        url="https://www.uji.es/estudis/centres/escola-doctorat/base/info-general/organitzacio/"
        "escola/comissio/Objectius/",
        markdown_content=_OBJECTIUS, token_count=24, textos_de_enlace=_ENLACES_DE_OBJECTIUS,
    ), **cambios)


class TestLaNavegacionNoEsEscasa:

    @pytest.mark.asyncio
    async def test_una_pagina_cuyo_texto_son_enlaces_es_de_navegacion(self) -> None:
        hallazgos = await _hallazgos(_objectius())

        assert "thin" not in hallazgos
        navegacion = hallazgos["navigation"]
        assert navegacion.severity == "info", "no es un defecto: es estructura del portal"
        assert navegacion.signal["enlaces"] == 5

    @pytest.mark.asyncio
    async def test_una_ficha_vacia_sigue_siendo_escasa(self) -> None:
        """También tiene enlaces, pero su texto propio son los campos de la ficha."""
        hallazgos = await _hallazgos(_Pagina(
            url="https://www.uji.es/x/carrera/", markdown_content=_FICHA, token_count=75,
            textos_de_enlace=_ENLACES_DE_LA_FICHA,
        ))

        assert "thin" in hallazgos
        assert "navigation" not in hallazgos

    @pytest.mark.asyncio
    async def test_sin_textos_de_enlace_medidos_no_se_afirma_nada_nuevo(self) -> None:
        """Las páginas rastreadas antes de #345: hasta el siguiente rastreo, siguen como estaban."""
        hallazgos = await _hallazgos(_objectius(textos_de_enlace=None))

        assert "thin" in hallazgos
        assert "navigation" not in hallazgos

    @pytest.mark.asyncio
    async def test_una_pagina_que_no_es_escasa_no_se_mira(self) -> None:
        """Navegación es una forma de ser escasa: una página con texto de sobra no lo es."""
        hallazgos = await _hallazgos(_objectius(token_count=500))

        assert "navigation" not in hallazgos

    @pytest.mark.asyncio
    async def test_los_umbrales_son_de_cada_sitio(self) -> None:
        exigente = await _hallazgos(_objectius(), nav_max_texto_propio=0)
        mas_enlaces = await _hallazgos(_objectius(), nav_min_enlaces=6)

        assert set(exigente) & {"thin", "navigation"} == {"thin"}
        assert set(mas_enlaces) & {"thin", "navigation"} == {"thin"}


class TestElJuicioDeQuienCuraSeConserva:

    @pytest.mark.asyncio
    async def test_si_ya_descarto_la_escasa_la_de_navegacion_nace_descartada(self) -> None:
        """Revisión de la PR #347: las páginas cuya `thin` había descartado el usuario de la OPAQ
        volvían a la cola como `navigation` nueva, bloqueaban la ingesta y no se podían proponer."""
        pagina = _objectius()

        class _SesionConDescartes(_Sesion):
            async def execute(self, stmt: Any) -> Any:
                if getattr(stmt, "_model_hint", "page") != "finding":
                    return await super().execute(stmt)

                class _R:
                    def scalars(self_inner) -> Any:
                        return self_inner

                    def all(self_inner) -> list:
                        return [pagina.id]

                return _R()

        detector = DeterministicQualityDetector(
            session=_SesionConDescartes([pagina]), finding_repo=_Repo(), now_fn=lambda: _AHORA
        )
        [hallazgo] = await detector.analyze(uuid.uuid4())

        assert hallazgo.finding_type == "navigation"
        assert hallazgo.status == "dismissed"

    @pytest.mark.asyncio
    async def test_sin_descarte_previo_nace_nueva(self) -> None:
        assert (await _hallazgos(_objectius()))["navigation"].status == "new"


class TestLosTextosDeEnlace:

    def test_salen_de_la_zona_de_contenido_y_sin_la_plantilla(self) -> None:
        html = (
            "<html><body><div class='mainMenu'><a href='/a'>Menú</a></div><main>"
            "<div class='breadcrumb'><a href='/'>Inici</a></div><h1>Organització</h1>"
            "<ul><li><a href='/c'>La Comissió  Acadèmica</a></li><li><a href='/d'> </a></li></ul>"
            "</main></body></html>"
        )

        _texto, _aviso, enlaces = contenido_y_enlaces(html, "main", [".breadcrumb", ".mainMenu"])

        assert enlaces == ["La Comissió Acadèmica"]

    @pytest.mark.asyncio
    async def test_una_tarjeta_enlazada_casa_linea_a_linea(self) -> None:
        """Revisión de la PR #347: un enlace con un título y una descripción dentro son dos líneas
        del texto; con el texto del enlace en una sola cadena no casaban, y una rejilla de
        tarjetas —la página de navegación más corriente— seguía saliendo como escasa."""
        html = (
            "<main><h1>Beques</h1>"
            "<a href='/a'><h3>Predoctorals</h3><p>Convocatòries obertes</p></a>"
            "<a href='/b'><h3>Mobilitat</h3><p>Estades a l'estranger</p></a></main>"
        )
        texto, _aviso, enlaces = contenido_y_enlaces(html, "main", [])

        hallazgos = await _hallazgos(_Pagina(
            url="https://www.uji.es/beques/", markdown_content=texto, token_count=20,
            textos_de_enlace=enlaces,
        ))

        assert "navigation" in hallazgos


class TestLoQueArrastraElTipoNuevo:

    def test_la_navegacion_no_entra_sola_al_corpus(self) -> None:
        """`thin` detenía la ingesta automática de estas páginas; al dejar de serlo, la detiene
        `navigation`. Sin esto, una sección en modo automático las metería en el corpus."""
        from server.app.modules.curation.quality_job import TIPOS_BLOQUEANTES_POR_DEFECTO

        assert "navigation" in TIPOS_BLOQUEANTES_POR_DEFECTO

    def test_la_reconciliacion_sabe_que_lo_emite_el_determinista(self) -> None:
        from server.app.modules.curation.site_crawler_dispatcher import (
            DeterministicDetectorDispatcher,
        )

        assert "navigation" in DeterministicDetectorDispatcher.finding_types

    def test_el_informe_tiene_su_recomendacion(self) -> None:
        from server.app.modules.curation.report_builder import _make_recommendation

        assert "'navigation'" not in _make_recommendation("navigation", 3)


class TestLoQueVioCopilotEnLaPR347:

    def test_un_ancla_sin_href_no_es_un_enlace(self) -> None:
        """`<a name="contacte">` marca un punto de la página, no lleva a ningún sitio: contarlo
        descontaba texto propio y podía esconder una escasa de verdad."""
        html = "<main><h2><a name='c'>Contacte</a></h2><p><a href='/x'>Seu</a></p></main>"

        _texto, _aviso, enlaces = contenido_y_enlaces(html, "main", [])

        assert enlaces == ["Seu"]

    def test_los_bytes_nulos_no_llegan_a_los_textos_de_enlace(self) -> None:
        """JSONB rechaza `\x00`, y con él la página entera. Los enlaces pasan por `texto_visible`,
        que ya lo quita."""
        _texto, _aviso, enlaces = contenido_y_enlaces("<main><a href='/x'>Se\x00u</a></main>", "main", [])

        assert enlaces == ["Seu"]

    @pytest.mark.asyncio
    async def test_varios_enlaces_en_una_misma_linea_tambien_son_navegacion(self) -> None:
        """Dos enlaces dentro de un `<p>` son una sola línea del texto, que no casa con ninguno de
        los dos. La clasificación dependía de la maquetación y no del contenido."""
        html = (
            "<main><h1>Organització</h1><p><a href='/a'>La Comissió Acadèmica</a> · "
            "<a href='/b'>La Comissió de Qualitat</a></p></main>"
        )
        texto, _aviso, enlaces = contenido_y_enlaces(html, "main", [])

        hallazgos = await _hallazgos(_Pagina(
            url="https://www.uji.es/org/", markdown_content=texto, token_count=20,
            textos_de_enlace=enlaces,
        ))

        assert "navigation" in hallazgos

    @pytest.mark.asyncio
    async def test_una_frase_con_un_enlace_dentro_sigue_siendo_texto_propio(self) -> None:
        """Quitar el texto del enlace de la línea deja el resto como texto propio: una ficha con
        frases que enlazan algo no se convierte en navegación."""
        html = (
            "<main><h1>Beca</h1><p>La sol·licitud es presenta a la <a href='/s'>Seu</a> abans del "
            "30 de setembre, amb el formulari i el currículum, i es resol en dos mesos des de la "
            "data de tancament de la convocatòria.</p><p><a href='/b'>Bases</a></p></main>"
        )
        texto, _aviso, enlaces = contenido_y_enlaces(html, "main", [])

        hallazgos = await _hallazgos(_Pagina(
            url="https://www.uji.es/beca/", markdown_content=texto, token_count=60,
            textos_de_enlace=enlaces,
        ))

        assert "thin" in hallazgos
