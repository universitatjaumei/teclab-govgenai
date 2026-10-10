"""DIN.6 — el diario de la automatización, donde trabaja el curador.

El `summary` del job se calculaba, se devolvía y **se perdía**. Con DIN.4 y DIN.5 encima eso deja
de ser una molestia: el diario es el único sitio donde se puede ver que la salvaguarda paró una
retirada entera o que la puerta de calidad dejó cinco páginas fuera. La confianza en una
automatización se construye pudiendo auditarla barata — si quien cura no ve lo que hizo, la
apagará al primer susto, y tendrá razón.

Dos decisiones que estos tests fijan y que no son evidentes:

* **Una pasada que falla también se anota**, y es cuando más falta hace: sin ello, «no pasó nada»
  y «el rastreo revento» se leen igual desde la pantalla.
* **La retención es por ámbito, no por sitio.** Si fuera por sitio, la sección que se rastrea
  cada seis horas se llevaría todas las filas y borraría la historia de la que se mira una vez a
  la semana.
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import pytest


@dataclass
class _Resumen:
    pages_total: int = 0
    pages_new: int = 0
    pages_changed: int = 0
    pages_gone: int = 0
    pages_error: int = 0
    documents_auto_ingested: int = 0
    documents_reingested: int = 0
    documents_auto_retired: int = 0
    pages_blocked_by_findings: int = 0
    findings_retired: int = 0
    truncated: bool = False
    stop_reason: str | None = None
    errors: list = field(default_factory=list)
    section_id: uuid.UUID | None = None


@dataclass
class _ResumenDeRastreo:
    pages_new: int = 0
    pages_changed: int = 0
    pages_gone: int = 0
    pages_error: int = 0
    pages_total: int = 0
    truncated: bool = False
    stop_reason: str | None = None
    errors: list = field(default_factory=list)
    new_page_ids: list = field(default_factory=list)
    changed_page_ids: list = field(default_factory=list)
    gone_page_ids: list = field(default_factory=list)
    section_id: uuid.UUID | None = None


class _Rastreador:
    def __init__(self, resumen: Any = None, revienta: Exception | None = None) -> None:
        self._resumen = resumen or _ResumenDeRastreo()
        self._revienta = revienta

    async def crawl_site(
        self, site_id: uuid.UUID, section_id: uuid.UUID | None = None
    ) -> Any:
        if self._revienta:
            raise self._revienta
        return self._resumen


class _Diario:
    def __init__(self) -> None:
        self.anotadas: list[dict] = []

    async def registrar(self, **kw: Any) -> Any:
        self.anotadas.append(kw)
        return kw


class _DiarioQueRevienta:
    async def registrar(self, **kw: Any) -> Any:
        raise RuntimeError("la base no responde")


@dataclass
class _Seccion:
    site_id: uuid.UUID
    name: str = "Jornadas"
    pattern: str = "/jornadas"
    pattern_kind: str = "path_prefix"
    mode: str = "manual"
    crawl_interval_hours: int | None = None
    criteria_json: dict | None = None
    is_active: bool = True
    id: uuid.UUID = field(default_factory=uuid.uuid4)


@dataclass
class _Sitio:
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    config_json: dict = field(default_factory=dict)
    crawl_interval_hours: int = 24


class _Sesion:
    def __init__(self, sitio: _Sitio, secciones: list[_Seccion] | None = None) -> None:
        self._sitio = sitio
        self._secciones = {s.id: s for s in (secciones or [])}

    async def get(self, modelo: Any, ident: Any) -> Any:
        nombre = getattr(modelo, "__name__", "")
        if nombre == "HubWebSection":
            return self._secciones.get(ident)
        if nombre == "HubWebSite":
            return self._sitio if ident == self._sitio.id else None
        return None

    async def execute(self, stmt: Any) -> Any:
        class _R:
            def scalars(self_inner) -> Any:  # noqa: N805
                return self_inner

            def all(self_inner) -> list:  # noqa: N805
                return []

        return _R()

    async def flush(self) -> None:
        return None

    # #247 — el job confirma a mitad de pasada (la nota antes de reingerir, cada página al
    # procesarla), no sólo al final.
    async def commit(self) -> None:
        return None


class _RepoDeSelecciones:
    async def list_by_site(self, site_id: uuid.UUID) -> list:
        return []

    async def secciones_de(self, selections: list) -> dict:
        return {}

    def matches(self, selection: Any, page_url: str, *, secciones: dict | None = None) -> bool:
        return False


def _job(*, sesion: _Sesion, rastreador: _Rastreador, diario: Any):
    from server.app.modules.curation.quality_job import SiteQualityAnalysisJob

    @asynccontextmanager
    async def _factoria():
        yield sesion

    return SiteQualityAnalysisJob(
        session_factory=_factoria,
        site_crawler=rastreador,
        detectors=[],
        watcher=None,
        selection_repo=_RepoDeSelecciones(),
        run_log=diario,
    )


# ──────────────────────────── Lo que anota el job ────────────────────────────


class TestElJobAnotaLaPasada:

    @pytest.mark.asyncio
    async def test_should_write_the_counters_and_the_scope(self):
        sitio = _Sitio()
        seccion = _Seccion(site_id=sitio.id, name="Jornadas")
        diario = _Diario()

        await _job(
            sesion=_Sesion(sitio, [seccion]),
            rastreador=_Rastreador(
                _ResumenDeRastreo(
                    pages_total=14,
                    pages_new=2,
                    pages_changed=1,
                    pages_gone=0,
                    section_id=seccion.id,
                )
            ),
            diario=diario,
        ).run_for_site(sitio.id, section_id=seccion.id)

        assert len(diario.anotadas) == 1
        anotada = diario.anotadas[0]
        assert anotada["site_id"] == sitio.id
        assert anotada["section_id"] == seccion.id
        # El nombre, no el identificador: es lo que quien cura reconoce.
        assert anotada["scope_label"] == "Jornadas"
        assert anotada["summary"].pages_new == 2
        assert anotada["summary"].pages_total == 14
        assert anotada["finished_at"] >= anotada["started_at"]

    @pytest.mark.asyncio
    async def test_should_call_a_whole_site_pass_by_its_name(self):
        from server.app.modules.curation.quality_job import ETIQUETA_DEL_SITIO_ENTERO

        sitio = _Sitio()
        diario = _Diario()

        await _job(
            sesion=_Sesion(sitio), rastreador=_Rastreador(), diario=diario
        ).run_for_site(sitio.id)

        assert diario.anotadas[0]["section_id"] is None
        assert diario.anotadas[0]["scope_label"] == ETIQUETA_DEL_SITIO_ENTERO

    @pytest.mark.asyncio
    async def test_should_write_a_pass_whose_crawl_blew_up(self):
        """**Es cuando más falta hace.** Sin esto, «no pasó nada» y «el rastreo reventó» se leen
        igual desde la pantalla, y quien cura no tiene por dónde empezar."""
        sitio = _Sitio()
        diario = _Diario()

        resumen = await _job(
            sesion=_Sesion(sitio),
            rastreador=_Rastreador(revienta=RuntimeError("Connection refused")),
            diario=diario,
        ).run_for_site(sitio.id)

        assert len(diario.anotadas) == 1
        assert any("Connection refused" in e for e in resumen.errors)
        assert any("Connection refused" in e for e in diario.anotadas[0]["summary"].errors)

    @pytest.mark.asyncio
    async def test_should_carry_whether_the_pass_was_truncated(self):
        """«Cero bajas» y «no se han comprobado las bajas» son dos noticias muy distintas
        (RAS.1), y el diario tiene que poder distinguirlas."""
        sitio = _Sitio()
        diario = _Diario()

        await _job(
            sesion=_Sesion(sitio),
            rastreador=_Rastreador(
                _ResumenDeRastreo(truncated=True, stop_reason="max_pages")
            ),
            diario=diario,
        ).run_for_site(sitio.id)

        assert diario.anotadas[0]["summary"].truncated is True
        assert diario.anotadas[0]["summary"].stop_reason == "max_pages"

    @pytest.mark.asyncio
    async def test_should_not_let_the_diary_take_down_the_pass(self):
        """El diario cuenta lo que pasó: un fallo al contarlo no puede deshacer lo hecho."""
        sitio = _Sitio()

        resumen = await _job(
            sesion=_Sesion(sitio),
            rastreador=_Rastreador(_ResumenDeRastreo(pages_new=3)),
            diario=_DiarioQueRevienta(),
        ).run_for_site(sitio.id)

        assert resumen.pages_new == 3

    @pytest.mark.asyncio
    async def test_should_run_exactly_as_before_without_a_diary(self):
        from server.app.modules.curation.quality_job import SiteQualityAnalysisJob

        sitio = _Sitio()

        @asynccontextmanager
        async def _factoria():
            yield _Sesion(sitio)

        job = SiteQualityAnalysisJob(
            session_factory=_factoria,
            site_crawler=_Rastreador(_ResumenDeRastreo(pages_new=1)),
            detectors=[],
            watcher=None,
            selection_repo=_RepoDeSelecciones(),
        )

        resumen = await job.run_for_site(sitio.id)

        assert resumen.pages_new == 1
