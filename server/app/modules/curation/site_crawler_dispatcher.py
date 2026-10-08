"""Despachador de rastreo: del `site_id` al `SiteCrawler` que le corresponde (SEC.8.8).

Deploy: edge.

`SiteCrawler` recibe **un** spider ya construido, pero cuál es el correcto depende del
`spider_type` de cada sitio, que solo se sabe leyendo el sitio. Faltaba justo esa pieza: sin
ella no había forma de ir del `site_id` que llega por la ruta al rastreo, y por eso el
arranque cableaba un crawler nulo que respondía «no spider configured» a todo.

**Esto no ingiere nada al corpus.** El rastreo llena la bandeja del curador —páginas
descubiertas, cambiadas, desaparecidas— y ahí se queda; publicar al corpus sigue siendo una
decisión por candidata, según `docs/DECISION_CURACION_SEPARADA.md`. Una página nueva es una
señal para quien cura, no un disparador.

**Sobre la sesión**: el despachador abre la suya y confirma **cada página al guardarla**. Un
rastreo dura minutos y toca cientos de filas; colgarlo de la sesión de la petición que lo encoló la
mantendría abierta todo ese tiempo. Y confirmar sólo al final (como hasta #247) dejaba bloqueada
cada página tocada hasta entonces: proponerla para un asistente esperaba 30 s y daba 500. Lo que el
job tiene que hacer después con cada página queda en la propia fila (`pendiente`), no en la memoria
del rastreo, para que un reinicio a mitad no lo pierda.

**Pendiente de Deploy**: hoy el rastreo se encola con `BackgroundTasks`, o sea dentro del
proceso web. En un entorno que escala a cero —Cloud Run— la instancia puede morir a mitad y
el rastreo desaparece sin dejar rastro. Para ese despliegue hace falta un ejecutor de
trabajos duradero; en local, en Docker y en un edge con contenedor persistente esto funciona
tal cual. Se decidió así a propósito: separar la ejecución, no la aplicación.
"""
from __future__ import annotations

import uuid
from typing import Any

from server.app.modules.agents_hub.database.operational_models import HubWebSite
from server.app.modules.curation.signal_extractor import CrawlSignalExtractor
from server.app.modules.curation.site_crawler import SiteCrawler, SiteCrawlSummary
from server.app.modules.curation.site_repo import CrawledPageRepo
from server.app.modules.curation.spider_factory import SpiderFactory

_SPIDER_POR_DEFECTO = "generic"


class SiteCrawlerDispatcher:
    """Resuelve el spider de cada sitio y ejecuta su rastreo.

    Cumple el mismo protocolo que consume `SiteQualityAnalysisJob`
    —`crawl_site(site_id, section_id)`—, así que sustituir el crawler nulo por este no toca el
    job. `section_id` acota la pasada a una sección del sitio (DIN.2).
    """

    def __init__(self, session_factory: Any, spider_factory: Any | None = None) -> None:
        self._session_factory = session_factory
        self._spiders = spider_factory or SpiderFactory()

    async def crawl_site(
        self, site_id: uuid.UUID, section_id: uuid.UUID | None = None
    ) -> SiteCrawlSummary:
        async with self._session_factory() as session:
            site = await session.get(HubWebSite, site_id)
            if site is None:
                return SiteCrawlSummary(errors=[f"site {site_id} not found"])

            tipo = getattr(site, "spider_type", None) or _SPIDER_POR_DEFECTO
            try:
                spider = self._spiders.get_spider(tipo)
            except ValueError as exc:
                # Un tipo desconocido NO cae al genérico: rastrear el DOGV con el spider
                # equivocado produce páginas mal extraídas que alguien tendría que revisar
                # a mano después, y el coste de eso es mayor que el de no rastrear.
                return SiteCrawlSummary(errors=[str(exc)])

            crawler = SiteCrawler(
                session=session,
                spider=spider,
                signal_extractor=CrawlSignalExtractor(),
                page_repo=CrawledPageRepo(session),
                confirmar=session.commit,
            )
            resumen = await crawler.crawl_site(site_id, section_id=section_id)
            await session.commit()
            return resumen


class DeterministicDetectorDispatcher:
    """El detector determinista, con sesión propia por ejecución (SEC.8.8).

    `DeterministicQualityDetector` se construye con una sesión y un repositorio, así que no
    puede instanciarse una sola vez al arrancar: la sesión de entonces no serviría para el
    rastreo de dentro de seis horas. Este adaptador cumple el protocolo que el job consume
    —`analyze(site_id)`— y resuelve las dependencias en cada pasada, igual que el
    despachador de rastreo de arriba.
    """

    #: CUR.9 — lo que este detector puede afirmar, y por tanto lo que puede dejar de afirmar. La
    #: reconciliación sólo retira los tipos de los detectores que han corrido.
    #: `duplicate` está aquí **y** en el semántico: el determinista lo emite por `content_hash`
    #: exacto (CUR.2) y el otro por significado. Ese solape es lo que hace que un tipo compartido
    #: sólo se reconcilie cuando los dos han pasado.
    finding_types = frozenset({
        "empty", "thin", "stale", "crawl_error", "orphan_page",
        "needs_javascript", "superseded", "version_series", "duplicate",
    })

    def __init__(self, session_factory: Any) -> None:
        self._session_factory = session_factory

    async def analyze(self, site_id: uuid.UUID) -> list:
        from server.app.modules.curation.deterministic_detector import (
            DeterministicQualityDetector,
        )
        from server.app.modules.curation.findings_repo import ContentFindingRepo

        async with self._session_factory() as session:
            # CUR.2.1 — los criterios de juicio son **de cada sitio**, y por tanto de cada
            # organización. Aquí se construía el detector con los valores por defecto del
            # constructor y nadie le pasaba nada, así que todas las organizaciones compartían
            # umbral de antigüedad y la misma idea de qué significa una serie por años. Un portal
            # de normativa y uno de noticias no envejecen igual.
            sitio = await session.get(HubWebSite, site_id)
            criterios = (getattr(sitio, "config_json", None) or {}) if sitio else {}

            detector = DeterministicQualityDetector(
                session,
                finding_repo=ContentFindingRepo(session),
                thin_token_threshold=criterios.get("thin_min_tokens", 120),
                stale_days=criterios.get("stale_days", 365),
                version_series_policy=criterios.get("version_series_policy", "series"),
            )
            hallazgos = await detector.analyze(site_id)
            await session.commit()
            return hallazgos


class SemanticDetectorDispatcher:
    """El detector semántico, ejecutado de verdad (CUR.7).

    `SemanticContradictionDetector` existe desde 9Q.4 con sus tests y **nadie lo ejecutaba**: el
    job del arranque se construía con `detectors=[determinista]`, así que un sitio guardado con
    `audit_semantic_scope='full'` no cambiaba nada. Tercera vez que aparece este patrón en el
    proyecto —el watcher de RAS.5, el bloque `TABLE` de SEG.5— y siempre igual: la capacidad
    construida detrás de una puerta que nadie abrió.

    Dos cosas que hay que hacer aquí porque no las hace nadie más:

    * **Persistir.** El detector devuelve hallazgos y no los guarda —lo dice su docstring: «eso es
      del job»— y el job **no los guarda**: cuenta, marca supersesiones y calcula `quality_score`.
      Sin este `upsert`, el detector llamaría al LLM y sus hallazgos morirían con la sesión.
    * **Resolver el modelo y los embeddings por sesión**, igual que el despachador determinista:
      una instancia creada al arrancar tendría la sesión de entonces.

    El nivel de modelo es el **1**. `docs/NIVELES_DE_MODELO.md` reserva el 3 para «juzgar código
    ajeno»; esto juzga **contenido**, que es lo que el nivel 1 ya hace en la ingesta.
    """

    _is_semantic = True

    #: CUR.9 — lo que juzga el modelo. `duplicate` lo comparte con el determinista.
    finding_types = frozenset({"duplicate", "contradiction"})

    def __init__(
        self,
        session_factory: Any,
        *,
        llm_factory: Any = None,
        embedding_factory: Any = None,
        finding_repo_factory: Any = None,
        detector_factory: Any = None,
    ) -> None:
        self._session_factory = session_factory
        self._llm_factory = llm_factory
        self._embedding_factory = embedding_factory
        self._finding_repo_factory = finding_repo_factory
        self._detector_factory = detector_factory

    async def analyze(self, site_id: uuid.UUID) -> list:
        async with self._session_factory() as session:
            sitio = await session.get(HubWebSite, site_id)
            if sitio is None:
                return []

            # `off` lo decide quien cura, y tiene que costar cero: sin llamadas al modelo y sin
            # embeber nada. Comprobarlo aquí y no dentro del detector evita construir el modelo.
            alcance = getattr(sitio, "audit_semantic_scope", "ingested")
            if alcance == "off":
                return []

            criterios = getattr(sitio, "config_json", None) or {}
            llm = await self._resolver_llm(session, sitio)
            embedding = await self._resolver_embeddings(session, sitio)

            detector = (self._detector_factory or self._detector_de_verdad)(
                session,
                llm,
                embedding,
                similarity_threshold=criterios.get("semantic_similarity_threshold", 0.92),
                max_pairs_per_run=criterios.get("semantic_max_pairs", 200),
            )
            hallazgos = await detector.analyze(site_id)

            repo = (self._finding_repo_factory or self._repo_de_verdad)(session)
            for hallazgo in hallazgos:
                await repo.upsert(hallazgo)
            await session.commit()
            return hallazgos

    # -- dependencias reales, resueltas por ejecución ------------------------

    @staticmethod
    def _detector_de_verdad(*args: Any, **kw: Any) -> Any:
        from server.app.modules.curation.semantic_detector import (
            SemanticContradictionDetector,
        )

        return SemanticContradictionDetector(*args, **kw)

    @staticmethod
    def _repo_de_verdad(session: Any) -> Any:
        from server.app.modules.curation.findings_repo import ContentFindingRepo

        return ContentFindingRepo(session)

    async def _resolver_llm(self, session: Any, sitio: Any = None) -> Any:
        """MT.3 — el modelo se resuelve para la organización **del sitio**, que es quien paga
        el rastreo. `HubWebSite.organizacion_id` la tiene, así que este llamador no espera a
        nadie."""
        if self._llm_factory is not None:
            resultado = self._llm_factory(session)
            return await resultado if hasattr(resultado, "__await__") else resultado

        from server.app.modules.agents_hub.services.config_provider import (
            LocalConfigProvider,
        )
        from server.app.modules.agents_hub.services.model_factory import get_model_for_tier
        from server.app.modules.curation.semantic_detector import JuezDeContenidoWeb

        modelo = await get_model_for_tier(
            1,
            LocalConfigProvider(session),
            organizacion_id=getattr(sitio, "organizacion_id", None),
        )
        nombre = getattr(modelo, "model_name", None) or getattr(modelo, "model", "desconocido")
        # `JuezDeContenidoWeb` y no `RedactorDeBloques`: cumplen el mismo protocolo con semánticas
        # distintas —el segundo entiende su primer argumento como el **id** de una plantilla— y
        # usarlo aquí mandaría al modelo «esa plantilla no está en el catálogo» en vez del prompt.
        return JuezDeContenidoWeb(modelo, str(nombre))

    async def _resolver_embeddings(self, session: Any, sitio: Any) -> Any:
        if self._embedding_factory is not None:
            resultado = self._embedding_factory(session, sitio)
            return await resultado if hasattr(resultado, "__await__") else resultado

        from server.app.modules.agents_hub.services.embedding_resolver import (
            resolve_embedding_service,
        )

        # Por el chatbot que tenga corpus de este sitio, y por la plataforma cuando no lo haya:
        # comparar con un modelo distinto del que embebió el corpus da distancias sin sentido.
        chatbot_id = await self._chatbot_con_corpus_del_sitio(session, sitio.id)
        return await resolve_embedding_service(session, chatbot_id)

    @staticmethod
    async def _chatbot_con_corpus_del_sitio(session: Any, site_id: uuid.UUID) -> uuid.UUID | None:
        from sqlalchemy import select

        from server.app.modules.agents_hub.database.operational_models import (
            HubCrawledPage,
            HubDocument,
        )

        stmt = (
            select(HubDocument.chatbot_id)
            .join(HubCrawledPage, HubCrawledPage.id == HubDocument.crawled_page_id)
            .where(HubCrawledPage.site_id == site_id)
            .limit(1)
        )
        resultado = await session.execute(stmt)
        return resultado.scalars().first()


def detectores_de_calidad(session_factory: Any, *, run_semantic: bool = True) -> list:
    """Los detectores que el job ejecuta en cada pasada.

    Existe para que el arranque no vuelva a construir la lista a mano: así estaba, y así se quedó
    con un solo detector durante todo el bloque 9Q en adelante. Apagar el semántico **quita la
    pieza** en vez de dejarla dentro confiando en un `if` de más adentro.
    """
    detectores: list = [DeterministicDetectorDispatcher(session_factory)]
    if run_semantic:
        detectores.append(SemanticDetectorDispatcher(session_factory))
    return detectores
