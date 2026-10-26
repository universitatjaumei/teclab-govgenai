"""DIN.1 — la sección como dato, y qué parámetro gana cuando hay dos.

Hoy un apartado se expresa **creando un `HubWebSite` entero** con su `url_regex_filter`. Es la
decisión de RAS.5 y tenía una buena razón —cada apartado tiene un responsable distinto—, pero
duplica `root_url`, sitemap y criterios de juicio, y hace que «añadir el apartado de becas» sea
trabajo de quien administra sitios en vez de trabajo de quien cura.

Estos tests fijan las dos piezas que consumen los seis prompts siguientes del bloque:

* **`parametros_efectivos(site, section)`** — función pura: entra dato, sale dato, sin sesión de
  BD. `None` en la sección **hereda** del sitio, la misma semántica que `core/ambito.py` da a
  `heredable`; y los criterios se funden **clave a clave**, porque un override de `stale_days` no
  puede borrar el umbral de retirada que sólo está puesto en el sitio (con `dict | dict` mal
  hecho, sí lo borra).
* **`casa(section, url)`** — la pertenencia de una página a una sección **se deriva del patrón**,
  no se almacena: los patrones se editan, y una columna `section_id` en `hub_crawled_pages`
  habría que reescribirla en cada edición.

Y la validación del patrón **al guardar**: es la lección de `CrawlConfig` en RAS.5 —un regex que
no compila rompería todos los rastreos de la sección y el fallo saldría lejos del formulario
donde se escribió—.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest

from server.app.modules.curation.secciones import (
    PatronInvalido,
    casa,
    casa_patron,
    parametros_efectivos,
    validar_patron,
)


# ──────────────────────────── Dobles de dato ────────────────────────────
#
# Dataclasses y no mocks: `parametros_efectivos` es pura y lo único que necesita de un sitio o de
# una sección son sus campos. Un mock aquí no probaría nada más y esconderían un atributo mal
# escrito.


@dataclass
class _Sitio:
    crawl_interval_hours: int = 24
    config_json: dict[str, Any] = field(default_factory=dict)
    id: uuid.UUID = field(default_factory=uuid.uuid4)


@dataclass
class _Seccion:
    name: str = "Jornadas"
    pattern: str = "/jornadas"
    pattern_kind: str = "path_prefix"
    crawl_interval_hours: int | None = None
    criteria_json: dict[str, Any] | None = None
    mode: str = "manual"
    id: uuid.UUID = field(default_factory=uuid.uuid4)


# ──────────────────────────── Herencia ────────────────────────────


class TestNuloHereda:
    """La regla dura nº 4 del bloque: nulo hereda. Un sitio **sin secciones** se comporta
    exactamente como hoy; no es un *shim*, es la herencia."""

    def test_should_inherit_interval_and_criteria_when_the_section_leaves_them_empty(self):
        sitio = _Sitio(crawl_interval_hours=72, config_json={"stale_days": 500})
        seccion = _Seccion(crawl_interval_hours=None, criteria_json=None)

        efectivos = parametros_efectivos(sitio, seccion)

        assert efectivos.crawl_interval_hours == 72
        assert efectivos.criterios["stale_days"] == 500

    def test_should_prefer_the_section_value_when_it_is_set(self):
        sitio = _Sitio(crawl_interval_hours=72, config_json={"stale_days": 500})
        seccion = _Seccion(crawl_interval_hours=6, criteria_json={"stale_days": 30})

        efectivos = parametros_efectivos(sitio, seccion)

        assert efectivos.crawl_interval_hours == 6
        assert efectivos.criterios["stale_days"] == 30

    def test_should_merge_criteria_key_by_key(self):
        """**El test que un `dict | dict` mal hecho rompe.** La sección sólo dice `stale_days`;
        el umbral de retirada, que únicamente está en el sitio, tiene que sobrevivir."""
        sitio = _Sitio(
            config_json={
                "stale_days": 500,
                "retirada_masiva_umbral": 0.3,
                "thin_min_tokens": 120,
            }
        )
        seccion = _Seccion(criteria_json={"stale_days": 30})

        criterios = parametros_efectivos(sitio, seccion).criterios

        assert criterios == {
            "stale_days": 30,
            "retirada_masiva_umbral": 0.3,
            "thin_min_tokens": 120,
        }

    def test_should_treat_a_null_inside_the_criteria_as_inherit_too(self):
        """`None` dentro de `criteria_json` es heredar, igual que `None` en la columna: es lo que
        permite vaciar un override desde la pantalla sin dejar la clave en nulo para siempre.
        `0` y `""` son «lo quiero así», como en `core/ambito.py`."""
        sitio = _Sitio(config_json={"stale_days": 500, "thin_min_tokens": 120})
        seccion = _Seccion(criteria_json={"stale_days": None, "thin_min_tokens": 0})

        criterios = parametros_efectivos(sitio, seccion).criterios

        assert criterios["stale_days"] == 500
        assert criterios["thin_min_tokens"] == 0

    def test_should_be_the_whole_site_when_there_is_no_section(self):
        """El comportamiento de hoy, y el que DIN.2 tiene que conservar: sin sección, el ámbito
        es el sitio entero y los parámetros son los del sitio."""
        sitio = _Sitio(crawl_interval_hours=12, config_json={"stale_days": 400})

        efectivos = parametros_efectivos(sitio, None)

        assert efectivos.crawl_interval_hours == 12
        assert efectivos.criterios == {"stale_days": 400}
        assert efectivos.pattern is None
        assert efectivos.section_id is None
        assert efectivos.es_sitio_entero is True
        assert efectivos.ambito == "sitio"

    def test_should_carry_the_resolved_pattern_and_the_scope_identity(self):
        """El ámbito viaja resuelto porque el summary de DIN.2 y el diario de DIN.6 tienen que
        poder decir qué cubrió la pasada."""
        seccion = _Seccion(pattern="/eventos", pattern_kind="path_prefix")

        efectivos = parametros_efectivos(_Sitio(), seccion)

        assert efectivos.pattern == "/eventos"
        assert efectivos.pattern_kind == "path_prefix"
        assert efectivos.section_id == seccion.id
        assert efectivos.es_sitio_entero is False
        assert efectivos.ambito == str(seccion.id)


# ──────────────────────────── Pertenencia por patrón ────────────────────────────


class TestCasa:
    """La pertenencia se **deriva**, y con las dos clases de patrón."""

    @pytest.mark.parametrize(
        ("url", "esperado"),
        [
            ("https://www.uji.es/jornadas/2026", True),
            ("https://www.uji.es/jornadas", True),
            ("https://www.uji.es/eventos/2026", False),
            ("https://www.uji.es/noticias", False),
            # El prefijo es del **path**, no de la URL: si se comparase la cadena entera,
            # ninguna URL real empezaría por «/jornadas» y la sección no casaría nada.
            ("https://otro.example/jornadas/x", True),
        ],
    )
    def test_should_match_by_path_prefix(self, url, esperado):
        seccion = _Seccion(pattern="/jornadas", pattern_kind="path_prefix")

        assert casa(seccion, url) is esperado

    @pytest.mark.parametrize(
        ("url", "esperado"),
        [
            ("https://www.uji.es/jornades/2026/inici", True),
            ("https://www.uji.es/va/jornades/2026", True),
            ("https://www.uji.es/base/calendari", False),
        ],
    )
    def test_should_match_by_regex(self, url, esperado):
        seccion = _Seccion(pattern=r"/jornades/\d{4}", pattern_kind="regex")

        assert casa(seccion, url) is esperado

    def test_should_not_match_anything_without_a_scope(self):
        """Sin sección no hay patrón que evaluar: la pregunta la contesta el ámbito del sitio."""
        assert casa(None, "https://www.uji.es/jornadas") is False

    def test_should_be_the_same_comparator_the_selection_repo_uses(self):
        """No hay un segundo comparador. `CorpusSelectionRepo.matches` delega aquí para
        `path_prefix`, así que una regla de selección y una sección con el mismo prefijo tienen
        que decidir igual — si no, la pantalla y el rastreo discreparían sobre qué entra."""
        from server.app.modules.curation.site_repo import CorpusSelectionRepo

        @dataclass
        class _Sel:
            rule_type: str = "path_prefix"
            rule_value: str | None = "/jornadas"

        repo = CorpusSelectionRepo.__new__(CorpusSelectionRepo)
        for url in (
            "https://www.uji.es/jornadas/2026",
            "https://www.uji.es/eventos/2026",
        ):
            assert repo.matches(_Sel(), url) is casa_patron(
                "path_prefix", "/jornadas", url
            )


# ──────────────────────────── Validación al guardar ────────────────────────────


class TestElPatronSeValidaAlGuardar:
    """La lección de `CrawlConfig` en RAS.5: un patrón inválido rompería **todos** los rastreos
    de la sección, y el fallo saldría lejos del formulario donde se escribió."""

    def test_should_refuse_a_regex_that_does_not_compile_saying_which_and_why(self):
        with pytest.raises(PatronInvalido) as fallo:
            validar_patron("regex", "/jornades/[2026")

        mensaje = str(fallo.value)
        assert "/jornades/[2026" in mensaje
        assert "unterminated" in mensaje or "carácter" in mensaje or "set" in mensaje

    def test_should_accept_a_regex_that_compiles(self):
        assert validar_patron("regex", r"/jornades/\d{4}") == r"/jornades/\d{4}"

    def test_should_refuse_an_empty_pattern(self):
        """Una sección sin patrón no delimita nada: su ámbito sería el sitio entero con otro
        nombre, y con la auto-retirada de DIN.4 encima eso es exactamente la trampa del bloque."""
        with pytest.raises(PatronInvalido):
            validar_patron("path_prefix", "   ")

    def test_should_refuse_a_pattern_kind_that_no_comparator_understands(self):
        """El criterio de VER.8 con las reglas de selección: un tipo que `casa()` no entiende es
        una sección que no puede casar nunca, y en pantalla se vería activa y vacía."""
        with pytest.raises(PatronInvalido) as fallo:
            validar_patron("url_prefix", "https://www.uji.es/jornadas")

        assert "url_prefix" in str(fallo.value)

    def test_should_be_rejected_by_the_repo_before_writing(self):
        """«Al guardar» es literal: el repositorio no escribe una sección con patrón inválido."""
        from server.app.modules.curation.site_repo import WebSectionRepo

        class _SesionQueNoDeberiaEscribir:
            def add(self, _obj: Any) -> None:  # pragma: no cover — el test falla si se llama
                raise AssertionError("no se puede escribir una sección con patrón inválido")

        repo = WebSectionRepo(_SesionQueNoDeberiaEscribir())

        import asyncio

        with pytest.raises(PatronInvalido):
            asyncio.run(
                repo.create(
                    site_id=uuid.uuid4(),
                    name="Jornadas",
                    pattern="/jornades/[2026",
                    pattern_kind="regex",
                )
            )


# ──────────────────────────── Lo que declara el modelo ────────────────────────────


class TestElModelo:
    """Lo comprobable sin base de datos: que el esquema declara lo que el bloque necesita. Las
    dos restricciones (la unicidad y el `CheckConstraint`) las prueba Postgres en
    `integration/test_din1_secciones_en_la_base.py`."""

    def test_should_default_mode_to_manual(self):
        """A PROPÓSITO, al contrario que `auto_ingest_new` (que nació con default `True`): una
        sección nueva **no automatiza** hasta que alguien lo dice. Es el principio del bloque,
        «curación una vez, automatización después»."""
        from server.app.modules.agents_hub.database.operational_models import HubWebSection

        assert HubWebSection.__table__.c.mode.default.arg == "manual"

    def test_should_let_every_inheritable_parameter_be_null(self):
        from server.app.modules.agents_hub.database.operational_models import HubWebSection

        columnas = HubWebSection.__table__.c
        assert columnas.crawl_interval_hours.nullable is True
        assert columnas.criteria_json.nullable is True
        assert columnas.owner.nullable is True
        assert columnas.last_crawled_at.nullable is True

    def test_should_reach_its_organizacion_through_the_site(self):
        """La sección no tiene `organizacion_id`: llega a su organización por el sitio, y eso es
        lo que dice su fila en `docs/MULTITENENCIA.md`."""
        from server.app.modules.agents_hub.database.operational_models import HubWebSection

        columnas = HubWebSection.__table__.c
        assert "organizacion_id" not in columnas
        fk = next(iter(columnas.site_id.foreign_keys))
        assert fk.column.table.name == "hub_web_sites"
        assert fk.ondelete == "CASCADE"
