"""Una página del corpus que cambia en el portal se actualiza, y queda avisado (RAS.5).

El rastreo **ya detectaba** el cambio: compara el `content_hash` de cada página con el anterior y
llena `changed_page_ids`. El comentario del propio `SiteCrawlSummary` dice que esos ids son «usados
por `SiteQualityAnalysisJob` para auto-ingesta»… y el job recorría **solo `new_page_ids`**. O sea que
una página ya publicada en el corpus se actualizaba en el portal, el rastreo lo veía, lo contaba, y
**el asistente seguía respondiendo con el texto viejo**. Tubería a medio conectar, no decisión.

**Decisión tomada por el usuario el 2026-08-18**: se actualiza sola y queda avisado. El motivo es
que el asistente no puede citar una versión retirada de una página que ya se aprobó una vez; el
aviso —un hallazgo `content_updated`— deja el cambio a la vista para revisarlo después.

El límite de esa decisión también se comprueba aquí: reingerir **no publica nada nuevo**. Sólo
actualiza lo que ese asistente ya tenía; una página que nadie aprobó no entra por esta puerta.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest

from server.app.modules.curation.quality_job import SiteQualityAnalysisJob

_SITIO = uuid.uuid4()
_CHATBOT_CON_LA_PAGINA = uuid.uuid4()
_CHATBOT_SIN_LA_PAGINA = uuid.uuid4()


@dataclass
class _Pagina:
    id: uuid.UUID
    url: str
    markdown_content: str = "Convocatòria de beques, versió nova."
    title: str | None = "Beques de doctorat"
    superseded: bool = False
    superseded_by_page_id: uuid.UUID | None = None
    quality_score: float | None = None
    pendiente: str | None = "cambiada"


@dataclass
class _ResumenDeRastreo:
    pages_new: int = 0
    pages_changed: int = 1
    pages_gone: int = 0
    pages_error: int = 0
    pages_total: int = 1
    new_page_ids: list = field(default_factory=list)
    changed_page_ids: list = field(default_factory=list)
    gone_page_ids: list = field(default_factory=list)


class _Crawler:
    def __init__(self, resumen: _ResumenDeRastreo) -> None:
        self._resumen = resumen

    async def crawl_site(
        self, site_id: uuid.UUID, section_id: uuid.UUID | None = None
    ) -> Any:
        return self._resumen


class _Documento:
    def __init__(self, page_id: uuid.UUID, chatbot_id: uuid.UUID) -> None:
        self.crawled_page_id = page_id
        self.chatbot_id = chatbot_id


class _Sesion:
    """Sesión que sirve la página por id y los documentos del corpus por página."""

    def __init__(self, pagina: _Pagina, documentos: list[_Documento]) -> None:
        self._pagina = pagina
        self._documentos = documentos

    async def __aenter__(self) -> "_Sesion":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def get(self, modelo: Any, ident: Any) -> Any:
        return self._pagina if ident == self._pagina.id else None

    async def execute(self, stmt: Any) -> Any:
        documentos = self._documentos

        class _R:
            def scalars(self_inner) -> Any:  # noqa: N805
                return self_inner

            def all(self_inner) -> list:  # noqa: N805
                return documentos

        return _R()

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        return None


class _Watcher:
    def __init__(self) -> None:
        self.ingestas: list[dict] = []

    async def process_source(self, **kwargs: Any) -> Any:
        self.ingestas.append(kwargs)
        return object(), True


class _RepoDeSelecciones:
    async def list_by_site(self, site_id: uuid.UUID) -> list:
        return []

    def matches(self, selection: Any, page_url: str) -> bool:
        return False


class _RepoDeHallazgos:
    def __init__(self) -> None:
        self.guardados: list[Any] = []

    async def upsert(self, finding: Any) -> Any:
        self.guardados.append(finding)
        return finding


def _job(pagina: _Pagina, documentos: list[_Documento], watcher: _Watcher,
         repo_hallazgos: _RepoDeHallazgos, resumen: _ResumenDeRastreo):
    sesion = _Sesion(pagina, documentos)
    return SiteQualityAnalysisJob(
        session_factory=lambda: sesion,
        site_crawler=_Crawler(resumen),
        detectors=[],
        watcher=watcher,
        selection_repo=_RepoDeSelecciones(),
        finding_repo=repo_hallazgos,
    )


@pytest.mark.asyncio
async def test_la_pagina_que_cambia_se_reingiere_en_el_asistente_que_ya_la_tenia():
    pagina = _Pagina(id=uuid.uuid4(), url="https://www.uji.es/centres/escola-doctorat/beques/")
    watcher = _Watcher()
    resumen = _ResumenDeRastreo(changed_page_ids=[pagina.id])
    job = _job(pagina, [_Documento(pagina.id, _CHATBOT_CON_LA_PAGINA)], watcher,
               _RepoDeHallazgos(), resumen)

    resultado = await job.run_for_site(_SITIO)

    assert len(watcher.ingestas) == 1, "el asistente seguiría citando el texto viejo"
    assert watcher.ingestas[0]["chatbot_id"] == _CHATBOT_CON_LA_PAGINA
    assert watcher.ingestas[0]["crawled_page_id"] == pagina.id
    assert watcher.ingestas[0]["prefetched_content"] == pagina.markdown_content
    assert resultado.documents_reingested == 1


@pytest.mark.asyncio
async def test_reingerir_no_publica_la_pagina_en_asistentes_que_no_la_tenian():
    """Actualizar lo aprobado no es publicar lo que nadie aprobó."""
    pagina = _Pagina(id=uuid.uuid4(), url="https://www.uji.es/centres/escola-doctorat/beques/")
    watcher = _Watcher()
    resumen = _ResumenDeRastreo(changed_page_ids=[pagina.id])
    job = _job(pagina, [_Documento(pagina.id, _CHATBOT_CON_LA_PAGINA)], watcher,
               _RepoDeHallazgos(), resumen)

    await job.run_for_site(_SITIO)

    destinos = {i["chatbot_id"] for i in watcher.ingestas}
    assert _CHATBOT_SIN_LA_PAGINA not in destinos


@pytest.mark.asyncio
async def test_el_cambio_deja_un_aviso_con_la_pagina_y_el_asistente():
    """Se actualiza sola, pero no en silencio: hay que poder revisar qué cambió."""
    pagina = _Pagina(id=uuid.uuid4(), url="https://www.uji.es/centres/escola-doctorat/beques/")
    repo = _RepoDeHallazgos()
    resumen = _ResumenDeRastreo(changed_page_ids=[pagina.id])
    job = _job(pagina, [_Documento(pagina.id, _CHATBOT_CON_LA_PAGINA)], _Watcher(), repo, resumen)

    await job.run_for_site(_SITIO)

    avisos = [f for f in repo.guardados if f.finding_type == "content_updated"]
    assert len(avisos) == 1
    assert avisos[0].severity == "info"
    assert avisos[0].source_url == pagina.url
    assert avisos[0].signal["chatbots_actualizados"] == 1


@pytest.mark.asyncio
async def test_una_pagina_que_cambia_y_no_esta_en_ningun_corpus_no_se_ingiere_ni_avisa():
    """Es una página del portal que a nadie interesa todavía: no hay nada que actualizar."""
    pagina = _Pagina(id=uuid.uuid4(), url="https://www.uji.es/centres/escola-doctorat/otra/")
    watcher = _Watcher()
    repo = _RepoDeHallazgos()
    resumen = _ResumenDeRastreo(changed_page_ids=[pagina.id])
    job = _job(pagina, [], watcher, repo, resumen)

    await job.run_for_site(_SITIO)

    assert watcher.ingestas == []
    assert [f for f in repo.guardados if f.finding_type == "content_updated"] == []


@pytest.mark.asyncio
async def test_si_la_reingesta_falla_el_job_no_revienta_y_lo_dice():
    pagina = _Pagina(id=uuid.uuid4(), url="https://www.uji.es/centres/escola-doctorat/beques/")

    class _WatcherQueFalla(_Watcher):
        async def process_source(self, **kwargs: Any) -> Any:
            raise RuntimeError("el modelo de embeddings no responde")

    resumen = _ResumenDeRastreo(changed_page_ids=[pagina.id])
    job = _job(pagina, [_Documento(pagina.id, _CHATBOT_CON_LA_PAGINA)], _WatcherQueFalla(),
               _RepoDeHallazgos(), resumen)

    resultado = await job.run_for_site(_SITIO)

    assert resultado.documents_reingested == 0
    assert any("reingesta" in e for e in resultado.errors)


@pytest.mark.asyncio
async def test_247_reingerida_deja_de_estar_pendiente():
    pagina = _Pagina(id=uuid.uuid4(), url="https://www.uji.es/centres/escola-doctorat/beques/")
    job = _job(pagina, [_Documento(pagina.id, _CHATBOT_CON_LA_PAGINA)], _Watcher(),
               _RepoDeHallazgos(), _ResumenDeRastreo(changed_page_ids=[pagina.id]))

    await job.run_for_site(_SITIO)

    assert pagina.pendiente is None


@pytest.mark.asyncio
async def test_247_si_la_reingesta_falla_sigue_pendiente_para_la_pasada_siguiente():
    pagina = _Pagina(id=uuid.uuid4(), url="https://www.uji.es/centres/escola-doctorat/beques/")

    class _WatcherQueFalla(_Watcher):
        async def process_source(self, **kwargs: Any) -> Any:
            raise RuntimeError("el modelo de embeddings no responde")

    job = _job(pagina, [_Documento(pagina.id, _CHATBOT_CON_LA_PAGINA)], _WatcherQueFalla(),
               _RepoDeHallazgos(), _ResumenDeRastreo(changed_page_ids=[pagina.id]))

    await job.run_for_site(_SITIO)

    assert pagina.pendiente == "cambiada"


@pytest.mark.asyncio
async def test_247_una_cambiada_que_no_esta_en_ningun_corpus_no_queda_pendiente():
    pagina = _Pagina(id=uuid.uuid4(), url="https://www.uji.es/centres/escola-doctorat/otra/")
    job = _job(pagina, [], _Watcher(), _RepoDeHallazgos(),
               _ResumenDeRastreo(changed_page_ids=[pagina.id]))

    await job.run_for_site(_SITIO)

    assert pagina.pendiente is None


def test_content_updated_es_un_tipo_de_hallazgo_del_contrato():
    from typing import get_args

    from server.app.modules.curation.contracts import FindingType

    assert "content_updated" in get_args(FindingType)
