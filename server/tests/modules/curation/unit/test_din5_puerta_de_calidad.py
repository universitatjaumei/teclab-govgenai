"""DIN.5 — la puerta de calidad delante de la ingesta automática.

El paso 4 del job ingería cualquier página nueva que casara la regla **sin mirar los hallazgos
que el propio job acababa de calcular dos pasos antes**. Una página vacía, una que necesita un
navegador para leerse (el sondeo de RAS.2 existe justo para detectarlas) o una que falló al
descargarse entraban al corpus igual, y el asistente las citaría.

El criterio es una frase: **la automatización no puede tener menos criterio que el curador al que
sustituye en el camino feliz.** Quien cura mira los hallazgos antes de publicar; esto hace lo
mismo.

Dos cosas que no son obvias y que estos tests fijan:

* **La reingesta también pasa por la puerta**, y ahí importa más: reemplazar texto bueno del
  corpus por una extracción vacía es peor que no actualizar. La versión buena se conserva.
* **La página bloqueada sigue siendo candidata.** No se marca ni se recuerda nada: resuelto el
  hallazgo, la pasada siguiente la ingiere sola. Un estado «bloqueada» sería un tercer sitio
  donde vive la verdad, y habría que limpiarlo a mano.

Y los tipos bloqueantes se cruzan con el registro del detector, porque nombrarlos de memoria es
cómo se deja la puerta abierta en silencio: un tipo mal escrito no casa nada y todo pasa.
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import pytest


# ──────────────────────────── Dobles ────────────────────────────


@dataclass
class _Pagina:
    url: str
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    status: str = "active"
    markdown_content: str | None = "Contenido."
    title: str | None = "Título"
    superseded: bool = False
    quality_score: float | None = None
    pendiente: str | None = None


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
    root_url: str = "https://www.uji.es"


@dataclass
class _Seleccion:
    chatbot_id: uuid.UUID
    site_id: uuid.UUID
    rule_type: str = "path_prefix"
    rule_value: str | None = "/"
    section_id: uuid.UUID | None = None
    auto_ingest_new: bool = True
    id: uuid.UUID = field(default_factory=uuid.uuid4)


@dataclass
class _Hallazgo:
    finding_type: str
    page_id: uuid.UUID
    severity: str = "critical"
    status: str = "new"
    related_page_id: uuid.UUID | None = None
    signal: dict = field(default_factory=dict)


@dataclass
class _ResumenDeRastreo:
    pages_new: int = 0
    pages_changed: int = 0
    pages_gone: int = 0
    pages_error: int = 0
    pages_total: int = 0
    errors: list = field(default_factory=list)
    new_page_ids: list = field(default_factory=list)
    changed_page_ids: list = field(default_factory=list)
    gone_page_ids: list = field(default_factory=list)
    section_id: uuid.UUID | None = None


class _Rastreador:
    def __init__(self, resumen: _ResumenDeRastreo) -> None:
        self._resumen = resumen

    async def crawl_site(
        self, site_id: uuid.UUID, section_id: uuid.UUID | None = None
    ) -> Any:
        return self._resumen


class _Detector:
    """Devuelve los hallazgos que se le den, como los devolvería el determinista."""

    _is_semantic = False
    finding_types = frozenset({"empty", "thin", "needs_javascript", "crawl_error", "stale"})

    def __init__(self, hallazgos: list) -> None:
        self._hallazgos = hallazgos

    async def analyze(self, site_id: uuid.UUID) -> list:
        return list(self._hallazgos)


class _RepoDeSelecciones:
    def __init__(self, selecciones: list[_Seleccion]) -> None:
        self._selecciones = selecciones

    async def list_by_site(self, site_id: uuid.UUID) -> list:
        return [s for s in self._selecciones if s.site_id == site_id]

    async def secciones_de(self, selections: list) -> dict:
        return {}

    def matches(self, selection: Any, page_url: str, *, secciones: dict | None = None) -> bool:
        from urllib.parse import urlparse

        if selection.rule_type == "path_prefix" and selection.rule_value:
            return urlparse(page_url).path.startswith(selection.rule_value)
        return False


class _Watcher:
    def __init__(self) -> None:
        self.ingeridas: list[tuple[str, uuid.UUID]] = []

    async def process_source(self, source_url: str, chatbot_id: uuid.UUID, **kw: Any) -> Any:
        self.ingeridas.append((source_url, chatbot_id))
        return (object(), 1)


class _RepoDeHallazgos:
    def __init__(self) -> None:
        self.hallazgos: list = []

    async def upsert(self, hallazgo: Any) -> Any:
        self.hallazgos.append(hallazgo)
        return hallazgo

    def de_tipo(self, tipo: str) -> list:
        return [h for h in self.hallazgos if h.finding_type == tipo]


class _Sesion:
    def __init__(
        self,
        sitio: _Sitio,
        paginas: list[_Pagina],
        secciones: list[_Seccion] | None = None,
        documentos: list | None = None,
    ) -> None:
        self._sitio = sitio
        self._paginas = {p.id: p for p in paginas}
        self._secciones = {s.id: s for s in (secciones or [])}
        self._documentos = documentos or []

    async def get(self, modelo: Any, ident: Any) -> Any:
        nombre = getattr(modelo, "__name__", "")
        if nombre == "HubWebSection":
            return self._secciones.get(ident)
        if nombre == "HubWebSite":
            return self._sitio if ident == self._sitio.id else None
        return self._paginas.get(ident)

    async def execute(self, stmt: Any) -> Any:
        try:
            entidad = stmt.column_descriptions[0]["entity"].__name__
        except Exception:  # noqa: BLE001
            entidad = ""
        if entidad == "HubDocument":
            filas: list = list(self._documentos)
        elif entidad == "HubCrawledPage":
            filas = list(self._paginas.values())
        else:
            filas = []

        class _R:
            def scalars(self_inner) -> Any:  # noqa: N805
                return self_inner

            def all(self_inner) -> list:  # noqa: N805
                return filas

        return _R()

    async def flush(self) -> None:
        return None

    # #247 — el job confirma a mitad de pasada (la nota antes de reingerir, cada página al
    # procesarla), no sólo al final.
    async def commit(self) -> None:
        return None


@dataclass
class _Documento:
    chatbot_id: uuid.UUID
    crawled_page_id: uuid.UUID
    id: uuid.UUID = field(default_factory=uuid.uuid4)


def _da_el_watcher(watcher: Any) -> Any:
    async def _fabrica(_session: Any, _chatbot_id: Any) -> Any:
        return watcher

    return _fabrica


def _job(
    *,
    sesion: _Sesion,
    resumen: _ResumenDeRastreo,
    hallazgos_del_detector: list,
    selecciones: list[_Seleccion],
    watcher: _Watcher,
    repo_de_hallazgos: _RepoDeHallazgos,
):
    from server.app.modules.curation.quality_job import SiteQualityAnalysisJob

    @asynccontextmanager
    async def _factoria():
        yield sesion

    return SiteQualityAnalysisJob(
        session_factory=_factoria,
        site_crawler=_Rastreador(resumen),
        detectors=[_Detector(hallazgos_del_detector)],
        watcher=None,
        selection_repo=_RepoDeSelecciones(selecciones),
        watcher_factory=_da_el_watcher(watcher),
        finding_repo=repo_de_hallazgos,
    )


# ──────────────────────────── Páginas nuevas ────────────────────────────


class TestLaPuertaDelanteDeLaAutoIngesta:

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "tipo", ["empty", "needs_javascript", "crawl_error", "thin"]
    )
    async def test_should_not_ingest_a_new_page_with_a_blocking_finding(self, tipo):
        """Los cuatro tipos de legibilidad: si el job acaba de decir que la página no se puede
        leer, meterla al corpus es meter ruido que el asistente citará."""
        sitio = _Sitio()
        seccion = _Seccion(site_id=sitio.id)
        nueva = _Pagina(url="https://www.uji.es/jornadas/nueva")
        sesion = _Sesion(sitio, [nueva], [seccion])
        watcher = _Watcher()
        avisos = _RepoDeHallazgos()

        resumen = await _job(
            sesion=sesion,
            resumen=_ResumenDeRastreo(
                new_page_ids=[nueva.id], pages_new=1, section_id=seccion.id
            ),
            hallazgos_del_detector=[_Hallazgo(finding_type=tipo, page_id=nueva.id)],
            selecciones=[_Seleccion(chatbot_id=uuid.uuid4(), site_id=sitio.id)],
            watcher=watcher,
            repo_de_hallazgos=avisos,
        ).run_for_site(sitio.id, section_id=seccion.id)

        assert watcher.ingeridas == []
        assert resumen.pages_blocked_by_findings == 1
        detenida = avisos.de_tipo("auto_ingesta_detenida")
        assert len(detenida) == 1
        # El motivo, porque el curador tiene que ver POR QUÉ no entró.
        assert detenida[0].signal["motivos"] == [tipo]
        assert detenida[0].page_id == nueva.id

    @pytest.mark.asyncio
    async def test_should_ingest_a_clean_new_page(self):
        """**El camino bueno**, que es lo que impide que la puerta se cierre de más: una página
        sin hallazgos entra igual que antes."""
        sitio = _Sitio()
        nueva = _Pagina(url="https://www.uji.es/jornadas/nueva")
        sesion = _Sesion(sitio, [nueva])
        watcher = _Watcher()
        chatbot = uuid.uuid4()

        resumen = await _job(
            sesion=sesion,
            resumen=_ResumenDeRastreo(new_page_ids=[nueva.id], pages_new=1),
            hallazgos_del_detector=[],
            selecciones=[_Seleccion(chatbot_id=chatbot, site_id=sitio.id)],
            watcher=watcher,
            repo_de_hallazgos=_RepoDeHallazgos(),
        ).run_for_site(sitio.id)

        assert watcher.ingeridas == [(nueva.url, chatbot)]
        assert resumen.documents_auto_ingested == 1
        assert resumen.pages_blocked_by_findings == 0

    @pytest.mark.asyncio
    async def test_should_ingest_a_page_whose_findings_are_not_blocking(self):
        """`stale` dice que la página es vieja, no que no se pueda leer. Bloquear por eso dejaría
        fuera del corpus medio portal, que es justo lo que CUR.1 vino a corregir."""
        sitio = _Sitio()
        nueva = _Pagina(url="https://www.uji.es/jornadas/nueva")
        sesion = _Sesion(sitio, [nueva])
        watcher = _Watcher()

        resumen = await _job(
            sesion=sesion,
            resumen=_ResumenDeRastreo(new_page_ids=[nueva.id], pages_new=1),
            hallazgos_del_detector=[
                _Hallazgo(finding_type="stale", page_id=nueva.id, severity="warning")
            ],
            selecciones=[_Seleccion(chatbot_id=uuid.uuid4(), site_id=sitio.id)],
            watcher=watcher,
            repo_de_hallazgos=_RepoDeHallazgos(),
        ).run_for_site(sitio.id)

        assert len(watcher.ingeridas) == 1
        assert resumen.pages_blocked_by_findings == 0

    @pytest.mark.asyncio
    async def test_should_ingest_on_the_next_pass_once_the_finding_is_gone(self):
        """La página bloqueada **sigue siendo candidata**: no se marca nada, así que resuelto el
        hallazgo la pasada siguiente la ingiere sola, sin ninguna acción extra."""
        sitio = _Sitio()
        nueva = _Pagina(url="https://www.uji.es/jornadas/nueva")
        watcher = _Watcher()
        seleccion = _Seleccion(chatbot_id=uuid.uuid4(), site_id=sitio.id)

        primera = await _job(
            sesion=_Sesion(sitio, [nueva]),
            resumen=_ResumenDeRastreo(new_page_ids=[nueva.id], pages_new=1),
            hallazgos_del_detector=[_Hallazgo(finding_type="empty", page_id=nueva.id)],
            selecciones=[seleccion],
            watcher=watcher,
            repo_de_hallazgos=_RepoDeHallazgos(),
        ).run_for_site(sitio.id)

        segunda = await _job(
            sesion=_Sesion(sitio, [nueva]),
            resumen=_ResumenDeRastreo(new_page_ids=[nueva.id], pages_new=1),
            hallazgos_del_detector=[],
            selecciones=[seleccion],
            watcher=watcher,
            repo_de_hallazgos=_RepoDeHallazgos(),
        ).run_for_site(sitio.id)

        assert primera.documents_auto_ingested == 0
        assert segunda.documents_auto_ingested == 1
        assert len(watcher.ingeridas) == 1


# ──────────────────────────── Páginas que cambiaron ────────────────────────────


class TestLaPuertaDelanteDeLaReingesta:

    @pytest.mark.asyncio
    async def test_should_not_reingest_a_changed_page_that_is_now_unreadable(self):
        """**Aquí la puerta importa más que en la ingesta.** La página ya está en el corpus con
        texto bueno: reemplazarlo por una extracción vacía es peor que no actualizar. Se conserva
        la versión buena y queda el motivo."""
        sitio = _Sitio()
        cambiada = _Pagina(url="https://www.uji.es/jornadas/cambiada")
        chatbot = uuid.uuid4()
        sesion = _Sesion(
            sitio,
            [cambiada],
            documentos=[_Documento(chatbot_id=chatbot, crawled_page_id=cambiada.id)],
        )
        watcher = _Watcher()
        avisos = _RepoDeHallazgos()

        resumen = await _job(
            sesion=sesion,
            resumen=_ResumenDeRastreo(changed_page_ids=[cambiada.id], pages_changed=1),
            hallazgos_del_detector=[
                _Hallazgo(finding_type="needs_javascript", page_id=cambiada.id)
            ],
            selecciones=[],
            watcher=watcher,
            repo_de_hallazgos=avisos,
        ).run_for_site(sitio.id)

        assert watcher.ingeridas == []
        assert resumen.documents_reingested == 0
        assert resumen.pages_blocked_by_findings == 1
        assert avisos.de_tipo("auto_ingesta_detenida")
        # Y no se avisa de una actualización que no ha ocurrido.
        assert avisos.de_tipo("content_updated") == []

    @pytest.mark.asyncio
    async def test_should_reingest_a_changed_page_that_reads_fine(self):
        sitio = _Sitio()
        cambiada = _Pagina(url="https://www.uji.es/jornadas/cambiada")
        chatbot = uuid.uuid4()
        sesion = _Sesion(
            sitio,
            [cambiada],
            documentos=[_Documento(chatbot_id=chatbot, crawled_page_id=cambiada.id)],
        )
        watcher = _Watcher()

        resumen = await _job(
            sesion=sesion,
            resumen=_ResumenDeRastreo(changed_page_ids=[cambiada.id], pages_changed=1),
            hallazgos_del_detector=[],
            selecciones=[],
            watcher=watcher,
            repo_de_hallazgos=_RepoDeHallazgos(),
        ).run_for_site(sitio.id)

        assert watcher.ingeridas == [(cambiada.url, chatbot)]
        assert resumen.documents_reingested == 1


# ──────────────────────────── El criterio es dato ────────────────────────────


class TestLosTiposBloqueantesSonCriterio:

    @pytest.mark.asyncio
    async def test_should_honour_the_types_declared_by_the_site(self):
        """Un portal puede decidir que `stale` también detiene la automatización."""
        sitio = _Sitio(config_json={"tipos_bloqueantes": ["stale"]})
        nueva = _Pagina(url="https://www.uji.es/jornadas/nueva")
        sesion = _Sesion(sitio, [nueva])
        watcher = _Watcher()

        resumen = await _job(
            sesion=sesion,
            resumen=_ResumenDeRastreo(new_page_ids=[nueva.id], pages_new=1),
            hallazgos_del_detector=[
                _Hallazgo(finding_type="stale", page_id=nueva.id, severity="warning")
            ],
            selecciones=[_Seleccion(chatbot_id=uuid.uuid4(), site_id=sitio.id)],
            watcher=watcher,
            repo_de_hallazgos=_RepoDeHallazgos(),
        ).run_for_site(sitio.id)

        assert watcher.ingeridas == []
        assert resumen.pages_blocked_by_findings == 1

    @pytest.mark.asyncio
    async def test_should_let_a_section_be_stricter_than_its_portal(self):
        """El apartado que alimenta al asistente puede ser más exigente que el portal entero:
        es la herencia de DIN.1 aplicada a un criterio de juicio más."""
        sitio = _Sitio(config_json={"tipos_bloqueantes": ["empty"]})
        seccion = _Seccion(
            site_id=sitio.id, criteria_json={"tipos_bloqueantes": ["empty", "stale"]}
        )
        nueva = _Pagina(url="https://www.uji.es/jornadas/nueva")
        sesion = _Sesion(sitio, [nueva], [seccion])
        watcher = _Watcher()

        resumen = await _job(
            sesion=sesion,
            resumen=_ResumenDeRastreo(
                new_page_ids=[nueva.id], pages_new=1, section_id=seccion.id
            ),
            hallazgos_del_detector=[
                _Hallazgo(finding_type="stale", page_id=nueva.id, severity="warning")
            ],
            selecciones=[_Seleccion(chatbot_id=uuid.uuid4(), site_id=sitio.id)],
            watcher=watcher,
            repo_de_hallazgos=_RepoDeHallazgos(),
        ).run_for_site(sitio.id, section_id=seccion.id)

        assert watcher.ingeridas == []
        assert resumen.pages_blocked_by_findings == 1

    @pytest.mark.asyncio
    async def test_should_let_a_section_be_laxer_than_its_portal(self):
        """Y al revés: la sección manda, aunque sea para relajar. Nulo hereda; una lista puesta
        sustituye, porque un criterio que sólo pudiera endurecerse no sería configurable."""
        sitio = _Sitio(config_json={"tipos_bloqueantes": ["empty", "thin"]})
        seccion = _Seccion(site_id=sitio.id, criteria_json={"tipos_bloqueantes": ["empty"]})
        nueva = _Pagina(url="https://www.uji.es/jornadas/nueva")
        sesion = _Sesion(sitio, [nueva], [seccion])
        watcher = _Watcher()

        resumen = await _job(
            sesion=sesion,
            resumen=_ResumenDeRastreo(
                new_page_ids=[nueva.id], pages_new=1, section_id=seccion.id
            ),
            hallazgos_del_detector=[
                _Hallazgo(finding_type="thin", page_id=nueva.id, severity="warning")
            ],
            selecciones=[_Seleccion(chatbot_id=uuid.uuid4(), site_id=sitio.id)],
            watcher=watcher,
            repo_de_hallazgos=_RepoDeHallazgos(),
        ).run_for_site(sitio.id, section_id=seccion.id)

        assert len(watcher.ingeridas) == 1
        assert resumen.pages_blocked_by_findings == 0


class TestLosTiposExistenDeVerdad:
    """**El test que impide dejar la puerta abierta en silencio.**

    Los tipos bloqueantes son cadenas. Una mal escrita —o un renombrado del detector— no casa
    ningún hallazgo, la puerta no se cierra nunca y **no hay ningún síntoma**: la automatización
    sigue ingiriendo y todo parece bien.
    """

    def test_should_only_name_types_the_detectors_can_emit(self):
        from server.app.modules.curation.quality_job import (
            TIPOS_BLOQUEANTES_POR_DEFECTO,
        )
        from server.app.modules.curation.site_crawler_dispatcher import (
            DeterministicDetectorDispatcher,
            SemanticDetectorDispatcher,
        )

        emitibles = (
            DeterministicDetectorDispatcher.finding_types
            | SemanticDetectorDispatcher.finding_types
        )
        inventados = set(TIPOS_BLOQUEANTES_POR_DEFECTO) - set(emitibles)

        assert inventados == set(), (
            f"tipos bloqueantes que ningún detector emite: {sorted(inventados)}"
        )

    def test_should_be_a_type_the_contract_admits(self):
        """Y el aviso que la puerta escribe tiene que ser un `FindingType` válido: si no, el
        `ContentFinding` reventaría al construirse y el motivo se perdería."""
        from server.app.modules.curation.contracts import FindingType

        assert "auto_ingesta_detenida" in FindingType.__args__


# ──────────────────────────── #247: la marca de pendiente ────────────────────────────


class TestLaMarcaDePendienteSoloLaQuitaLoProcesado:
    """El rastreo deja en la página lo que el job tiene que hacer con ella; el job la quita sólo
    cuando lo ha hecho. Lo que una puerta detiene **sigue pendiente**: así la pasada siguiente lo
    vuelve a recibir, que es lo que el docstring de DIN.5 prometía y el rastreo no cumplía —una
    página dejaba de ser «nueva» en la pasada siguiente y la auto-ingesta no la veía nunca—."""

    @pytest.mark.asyncio
    async def test_should_clear_a_new_page_once_ingested(self):
        sitio = _Sitio()
        nueva = _Pagina(url="https://www.uji.es/jornadas/nueva", pendiente="nueva")

        await _job(
            sesion=_Sesion(sitio, [nueva]),
            resumen=_ResumenDeRastreo(new_page_ids=[nueva.id], pages_new=1),
            hallazgos_del_detector=[],
            selecciones=[_Seleccion(chatbot_id=uuid.uuid4(), site_id=sitio.id)],
            watcher=_Watcher(),
            repo_de_hallazgos=_RepoDeHallazgos(),
        ).run_for_site(sitio.id)

        assert nueva.pendiente is None

    @pytest.mark.asyncio
    async def test_should_keep_a_new_page_pending_when_the_gate_stops_it(self):
        sitio = _Sitio()
        nueva = _Pagina(url="https://www.uji.es/jornadas/nueva", pendiente="nueva")

        await _job(
            sesion=_Sesion(sitio, [nueva]),
            resumen=_ResumenDeRastreo(new_page_ids=[nueva.id], pages_new=1),
            hallazgos_del_detector=[_Hallazgo(finding_type="empty", page_id=nueva.id)],
            selecciones=[_Seleccion(chatbot_id=uuid.uuid4(), site_id=sitio.id)],
            watcher=_Watcher(),
            repo_de_hallazgos=_RepoDeHallazgos(),
        ).run_for_site(sitio.id)

        assert nueva.pendiente == "nueva"

    @pytest.mark.asyncio
    async def test_should_clear_a_new_page_when_no_selection_ingests_automatically(self):
        """Si no, una selección automática creada meses después ingeriría de golpe todo lo que
        fue nuevo alguna vez, y eso no lo ha aprobado nadie."""
        sitio = _Sitio()
        nueva = _Pagina(url="https://www.uji.es/jornadas/nueva", pendiente="nueva")

        await _job(
            sesion=_Sesion(sitio, [nueva]),
            resumen=_ResumenDeRastreo(new_page_ids=[nueva.id], pages_new=1),
            hallazgos_del_detector=[],
            selecciones=[],
            watcher=_Watcher(),
            repo_de_hallazgos=_RepoDeHallazgos(),
        ).run_for_site(sitio.id)

        assert nueva.pendiente is None

    @pytest.mark.asyncio
    async def test_should_keep_a_changed_page_pending_when_the_gate_stops_it(self):
        sitio = _Sitio()
        cambiada = _Pagina(url="https://www.uji.es/jornadas/cambiada", pendiente="cambiada")
        chatbot = uuid.uuid4()

        await _job(
            sesion=_Sesion(
                sitio,
                [cambiada],
                documentos=[_Documento(chatbot_id=chatbot, crawled_page_id=cambiada.id)],
            ),
            resumen=_ResumenDeRastreo(changed_page_ids=[cambiada.id], pages_changed=1),
            hallazgos_del_detector=[
                _Hallazgo(finding_type="needs_javascript", page_id=cambiada.id)
            ],
            selecciones=[],
            watcher=_Watcher(),
            repo_de_hallazgos=_RepoDeHallazgos(),
        ).run_for_site(sitio.id)

        assert cambiada.pendiente == "cambiada"
