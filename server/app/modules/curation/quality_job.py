"""Job de calidad de contenido web por sitio (9Q.5).

Deploy: edge.

Orquesta por sitio: crawl + detección (determinista + semántica) + consolidación de
flags (superseded/quality_score) + auto-ingesta de páginas nuevas que casan una
HubCorpusSelection con auto_ingest_new=True.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from server.app.modules.curation.reconciliacion import (
    reconciliar_hallazgos,
    tipos_a_reconciliar,
)

logger = logging.getLogger(__name__)

#: DIN.4 — la proporción de bajas del ámbito por encima de la cual no se retira nada. Protege de
#: la clase de rastreo malo que `truncated` **no** capta: el portal que responde 200 con una
#: plantilla vacía, la redirección masiva. Es un criterio de juicio, así que se puede poner por
#: sitio y sobrescribir por sección (DIN.1); esto es el valor si nadie lo dice.
UMBRAL_DE_RETIRADA_MASIVA = 0.30
CLAVE_UMBRAL_DE_RETIRADA = "retirada_masiva_umbral"

#: Lo que se escribe al retirar el aviso de una página que volvió a aparecer. Un `resolved` a
#: secas se leería como «alguien lo arregló»; aquí lo único cierto es que la página está otra vez.
NOTA_DE_PAGINA_QUE_VOLVIO = (
    "Retirado automáticamente: la página ha vuelto a aparecer en el portal."
)

#: DIN.5 — los hallazgos que detienen la ingesta automática. Son los de **legibilidad**: si el
#: propio job acaba de decir que la página no se puede leer, meterla al corpus es meter ruido que
#: el asistente citará. `thin` está dentro porque es como se manifiesta una extracción que se
#: cortó; `stale` no, porque dice que la página es vieja y no que no se pueda leer — bloquear por
#: eso dejaría fuera medio portal, que es justo lo que CUR.1 vino a corregir.
#:
#: Los nombres se cruzan con el registro de los detectores en un test: son cadenas, y una mal
#: escrita no casa ningún hallazgo, no cierra la puerta nunca y **no da ningún síntoma**.
TIPOS_BLOQUEANTES_POR_DEFECTO: frozenset[str] = frozenset({
    "empty", "needs_javascript", "crawl_error", "thin",
})
CLAVE_TIPOS_BLOQUEANTES = "tipos_bloqueantes"

#: DIN.6 — cómo se llama en el diario la pasada que cubrió el sitio entero.
ETIQUETA_DEL_SITIO_ENTERO = "sitio"


# ──────────────────────────── Protocolos ────────────────────────────


class _SiteCrawler(Protocol):
    async def crawl_site(
        self, site_id: uuid.UUID, section_id: uuid.UUID | None = None
    ) -> Any: ...


class _Detector(Protocol):
    _is_semantic: bool
    async def analyze(self, site_id: uuid.UUID) -> list: ...


class _Watcher(Protocol):
    async def process_source(
        self,
        source_url: str,
        chatbot_id: uuid.UUID,
        *,
        prefetched_content: str | None = None,
        title: str | None = None,
        crawled_page_id: uuid.UUID | None = None,
    ) -> Any: ...


class _SelectionRepo(Protocol):
    async def list_by_site(self, site_id: uuid.UUID) -> list: ...
    async def secciones_de(self, selections: list) -> dict: ...
    def matches(
        self, selection: Any, page_url: str, *, secciones: dict | None = None
    ) -> bool: ...


# ──────────────────────────── SiteQualitySummary ────────────────────────────


@dataclass
class SiteQualitySummary:
    pages_new: int = 0
    pages_changed: int = 0
    pages_gone: int = 0
    pages_error: int = 0
    pages_total: int = 0
    findings_by_type: dict[str, int] = field(default_factory=dict)
    pages_marked_superseded: int = 0
    documents_auto_ingested: int = 0
    #: RAS.5 — páginas del corpus que cambiaron en el portal y se han vuelto a ingerir. El rastreo
    #: ya detectaba el cambio y nadie lo propagaba: el asistente seguía citando el texto viejo.
    documents_reingested: int = 0
    #: CUR.9 — hallazgos retirados porque este análisis ya no los emite. Sin esta cifra, «41 nuevos»
    #: y «41 nuevos y 300 retirados» se leerían igual, y son dos noticias muy distintas.
    findings_retired: int = 0
    errors: list[str] = field(default_factory=list)
    #: DIN.2 — qué ámbito cubrió la pasada: la sección, o el sitio entero. El diario de DIN.6 lo
    #: escribe y la auto-retirada de DIN.4 decide con él.
    section_id: uuid.UUID | None = None
    #: DIN.4 — documentos retirados del corpus porque su página desapareció del portal. Hasta
    #: aquí `mark_gone` marcaba la página y ahí moría: un evento borrado seguía en el corpus
    #: respondiendo como si existiera.
    documents_auto_retired: int = 0
    #: DIN.5 — páginas que la automatización **no** metió al corpus porque el propio job acababa
    #: de decir que no se pueden leer. Sin esta cifra, «no entró nada» y «no había nada que
    #: entrar» se leen igual.
    pages_blocked_by_findings: int = 0
    #: DIN.6 — el rastreo no vio el ámbito entero, y por qué (RAS.1). Llegaba hasta el summary
    #: del rastreo y se perdía aquí: sin ello, el diario no puede distinguir «cero bajas» de «no
    #: se han comprobado las bajas», que es la diferencia que RAS.1 existe para marcar.
    truncated: bool = False
    stop_reason: str | None = None

    @property
    def ambito(self) -> str:
        return "sitio" if self.section_id is None else str(self.section_id)


# ──────────────────────────── Heurística de calidad ────────────────────────────


_SEVERITY_PENALTY: dict[str, float] = {
    "critical": 0.5,
    "warning": 0.2,
    "info": 0.1,
}


def _compute_quality_score(findings: list) -> float:
    """Score de calidad [0.0, 1.0] = 1.0 menos penalizaciones acumuladas por hallazgo."""
    score = 1.0
    for f in findings:
        score -= _SEVERITY_PENALTY.get(getattr(f, "severity", "info"), 0.0)
    return max(0.0, score)


# ──────────────────────────── SiteQualityAnalysisJob ────────────────────────────


class SiteQualityAnalysisJob:
    """Orquesta crawl + detección + consolidación + auto-ingesta para un sitio."""

    def __init__(
        self,
        session_factory: Any,
        site_crawler: _SiteCrawler,
        detectors: list[_Detector],
        watcher: _Watcher | None,
        selection_repo: _SelectionRepo,
        *,
        run_semantic: bool = True,
        finding_repo: Any = None,
        watcher_factory: Any = None,
        retirer_factory: Any = None,
        selection_repo_factory: Any = None,
        run_log: Any = None,
    ) -> None:
        self._session_factory = session_factory
        self._site_crawler = site_crawler
        self._detectors = detectors
        self._watcher = watcher
        self._selection_repo = selection_repo
        self._run_semantic = run_semantic
        # Para avisar de las páginas del corpus que se han actualizado (RAS.5). Opcional: sin él
        # la reingesta sigue ocurriendo, pero sin dejar aviso en la bandeja.
        self._finding_repo = finding_repo
        # RAS.5 — el watcher necesita el servicio de embeddings **del chatbot**, así que una única
        # instancia no puede servir a varios: ingerir con otro modelo del que usa su corpus deja
        # vectores incomparables. Con fábrica, cada ingesta usa el suyo. Sin ella se usa el
        # watcher fijo, que es lo que hacen los tests que doblan esta pieza.
        self._watcher_factory = watcher_factory
        # DIN.4 — quien sabe retirar una página del corpus (`CorpusSelectionService`), construido
        # con la sesión de la pasada. Sin él no hay auto-retirada y el resto del job sigue igual.
        self._retirer_factory = retirer_factory
        # DIN.4 — el repositorio de selecciones **con la sesión de la pasada**. Construido al
        # arrancar tendría la sesión de entonces, y por eso el arranque pasaba uno nulo que
        # devolvía lista vacía: con él, la auto-ingesta de 9Q.7 no ha corrido nunca en producción.
        self._selection_repo_factory = selection_repo_factory
        # DIN.6 — el diario de pasadas (`DiarioDePasadas`). Sin él el job funciona igual que
        # antes: la pasada se ejecuta y no deja rastro consultable, que es como estaba.
        self._run_log = run_log

    def _selecciones(self, session: Any) -> Any:
        """El repositorio de selecciones de esta pasada: el de la fábrica, o el fijo."""
        if self._selection_repo_factory is not None:
            return self._selection_repo_factory(session)
        return self._selection_repo

    async def _watcher_para(self, session: Any, chatbot_id: uuid.UUID) -> Any:
        """El watcher que ingiere para ese chatbot, con su servicio de embeddings."""
        if self._watcher_factory is not None:
            return await self._watcher_factory(session, chatbot_id)
        return self._watcher

    async def _reingerir_lo_que_cambio(
        self,
        session: Any,
        site_id: uuid.UUID,
        changed_page_ids: list,
        summary: SiteQualitySummary,
        bloqueantes_por_pagina: dict[uuid.UUID, list[str]] | None = None,
    ) -> None:
        """Vuelve a ingerir las páginas del corpus que han cambiado, y avisa de cada una.

        DIN.5 — **la puerta de calidad importa aquí más que en la ingesta**: la página ya está en
        el corpus con texto bueno, y reemplazarlo por una extracción vacía es peor que no
        actualizar. Se conserva la versión buena y queda el motivo.
        """
        if not changed_page_ids or (self._watcher is None and self._watcher_factory is None):
            return

        from sqlalchemy import select

        from server.app.modules.agents_hub.database.operational_models import (
            HubCrawledPage,
            HubDocument,
        )

        for page_id in changed_page_ids:
            page = await session.get(HubCrawledPage, page_id)
            if page is None:
                continue

            motivos = (bloqueantes_por_pagina or {}).get(page_id)
            if motivos:
                summary.pages_blocked_by_findings += 1
                await self._registrar_hallazgo(
                    site_id,
                    "auto_ingesta_detenida",
                    severity="warning",
                    page_id=page.id,
                    source_url=page.url,
                    signal={"motivos": motivos, "paso": "reingesta"},
                )
                continue

            documentos = (
                await session.execute(
                    select(HubDocument).where(HubDocument.crawled_page_id == page_id)
                )
            ).scalars().all()
            # Un asistente puede tener la página una vez; varios pueden tenerla cada uno.
            chatbots = {doc.chatbot_id for doc in documentos}
            if not chatbots:
                continue

            actualizados = 0
            for chatbot_id in chatbots:
                try:
                    watcher = await self._watcher_para(session, chatbot_id)
                    await watcher.process_source(
                        source_url=page.url,
                        chatbot_id=chatbot_id,
                        prefetched_content=page.markdown_content,
                        title=page.title,
                        crawled_page_id=page.id,
                    )
                    actualizados += 1
                    summary.documents_reingested += 1
                except Exception as exc:  # noqa: BLE001
                    logger.exception(
                        "Reingesta fallida de %s para el chatbot %s", page.url, chatbot_id
                    )
                    summary.errors.append(f"reingesta {page.url}: {exc}")

            if actualizados and self._finding_repo is not None:
                await self._avisar_de_la_actualizacion(site_id, page, actualizados)

    # ──────────────────── DIN.5 — la puerta de calidad ────────────────────

    async def _parametros_del_ambito(
        self, session: Any, site_id: uuid.UUID, section_id: uuid.UUID | None
    ) -> Any:
        """Los criterios efectivos de esta pasada: los del sitio con los de su sección encima.

        Es la cascada de DIN.1, y la usan las dos decisiones automáticas del job: qué detiene la
        ingesta (DIN.5) y cuándo la salvaguarda de retirada dispara (DIN.4).
        """
        from server.app.modules.agents_hub.database.operational_models import (
            HubWebSection,
            HubWebSite,
        )
        from server.app.modules.curation.secciones import parametros_efectivos

        sitio = await session.get(HubWebSite, site_id)
        seccion = (
            await session.get(HubWebSection, section_id) if section_id is not None else None
        )
        return parametros_efectivos(sitio, seccion)

    @staticmethod
    def _bloqueantes_por_pagina(
        hallazgos: list, criterios: dict[str, Any]
    ) -> dict[uuid.UUID, list[str]]:
        """Qué hallazgo bloqueante tiene cada página **en esta pasada**.

        Se leen los hallazgos que el propio job acaba de calcular dos pasos antes, no la base: es
        lo que hay en memoria, y es exactamente lo que el curador vería al revisar esta pasada.

        Los tipos son un criterio de juicio más, heredable sitio→sección (DIN.1): una lista
        puesta **sustituye** al defecto, porque un criterio que sólo pudiera endurecerse no sería
        configurable.
        """
        declarados = criterios.get(CLAVE_TIPOS_BLOQUEANTES)
        bloqueantes = (
            set(declarados) if declarados is not None else set(TIPOS_BLOQUEANTES_POR_DEFECTO)
        )

        por_pagina: dict[uuid.UUID, list[str]] = {}
        for hallazgo in hallazgos:
            tipo = getattr(hallazgo, "finding_type", None)
            page_id = getattr(hallazgo, "page_id", None)
            if page_id is None or tipo not in bloqueantes:
                continue
            if getattr(hallazgo, "status", "new") not in ("new", "confirmed"):
                continue
            if tipo not in por_pagina.setdefault(page_id, []):
                por_pagina[page_id].append(tipo)
        return por_pagina

    # ──────────────────── DIN.4 — retirar lo que desapareció ────────────────────

    async def _retirar_lo_que_desaparecio(
        self,
        session: Any,
        site_id: uuid.UUID,
        section_id: uuid.UUID | None,
        gone_page_ids: list,
        summary: SiteQualitySummary,
    ) -> None:
        """Retira del corpus las páginas desaparecidas, o avisa, según el modo del ámbito.

        Tres reglas, y las tres son sobre no pasarse:

        * **Sólo en modo automático.** Una sección `manual` —o una pasada del sitio entero, que
          es lo que hace quien cura a mano— deja el aviso `page_gone` y no toca el corpus.
        * **Salvaguarda de proporción.** Por encima del umbral del ámbito no se retira nada: es
          la clase de rastreo malo que `truncated` no capta, y sin esto vacía corpus con el
          rastreo en verde. Misma idea que el reconciliador del corpus normativo.
        * **La proporción es del ámbito**, no del sitio: cuatro bajas en un apartado de diez son
          el 40 % del apartado y el 4 % de un portal de cien.
        """
        from server.app.modules.agents_hub.database.operational_models import HubWebSection

        # El aviso de una página que volvió se retira siempre, incluso sin bajas nuevas: es la
        # única pasada que puede saberlo.
        await self._retirar_avisos_de_paginas_que_volvieron(session, site_id)

        if not gone_page_ids:
            return

        seccion = (
            await session.get(HubWebSection, section_id) if section_id is not None else None
        )
        # `mode` de la sección de la pasada, **antes de la salvaguarda**. Sin sección no se
        # automatiza nada: la pasada del sitio entero es la del curador, y ahí una baja es una
        # señal, no un disparador.
        #
        # El orden importa: mirando primero la proporción, un ámbito en `manual` con muchas bajas
        # emitiría `retirada_masiva_detenida` —«la salvaguarda paró una retirada»— cuando no
        # había ninguna retirada que parar. La salvaguarda guarda lo que de verdad retira.
        if seccion is None or getattr(seccion, "mode", "manual") != "automatic":
            await self._avisar_de_las_bajas(session, site_id, gone_page_ids)
            return

        efectivos = await self._parametros_del_ambito(session, site_id, section_id)
        if not await self._la_proporcion_es_creible(
            session, site_id, efectivos, gone_page_ids, summary
        ):
            return

        await self._retirar_de_los_chatbots_que_la_publicaron(
            session, site_id, gone_page_ids, summary
        )

    async def _la_proporcion_es_creible(
        self,
        session: Any,
        site_id: uuid.UUID,
        efectivos: Any,
        gone_page_ids: list,
        summary: SiteQualitySummary,
    ) -> bool:
        """Si las bajas de esta pasada caben en lo que un portal hace de verdad.

        El denominador son las páginas **del ámbito** que había antes de la pasada: las que
        siguen activas más las que esta pasada acaba de dar de baja.
        """
        umbral = float(
            efectivos.criterios.get(CLAVE_UMBRAL_DE_RETIRADA, UMBRAL_DE_RETIRADA_MASIVA)
        )
        activas = await self._paginas_activas_del_ambito(session, site_id, efectivos)
        del_ambito = activas + len(gone_page_ids)
        if del_ambito == 0:
            return False

        proporcion = len(gone_page_ids) / del_ambito
        if proporcion < umbral:
            return True

        summary.errors.append(
            f"retirada detenida: {len(gone_page_ids)} bajas de {del_ambito} páginas del ámbito "
            f"({proporcion:.0%}) superan el umbral del {umbral:.0%}"
        )
        await self._registrar_hallazgo(
            site_id,
            "retirada_masiva_detenida",
            severity="critical",
            signal={
                "bajas": len(gone_page_ids),
                "ambito": del_ambito,
                "proporcion": round(proporcion, 4),
                "umbral": umbral,
                "ambito_id": efectivos.ambito,
            },
        )
        return False

    async def _paginas_activas_del_ambito(
        self, session: Any, site_id: uuid.UUID, efectivos: Any
    ) -> int:
        """Cuántas páginas activas del sitio casan el ámbito de esta pasada."""
        from sqlalchemy import select

        from server.app.modules.agents_hub.database.operational_models import HubCrawledPage

        # Sólo se cuenta, así que **no se piden objetos**: con la URL y el estado basta (issue
        # #159). Traer las páginas enteras para descartarlas en Python es, en pequeño, la forma
        # de consulta que tumbó la VM el 2026-09-24.
        #
        # El estado se filtra aquí y no en el `WHERE` a propósito: los dobles de sesión de los
        # test de DIN.4 no aplican los filtros de la sentencia, así que moverlo a SQL haría que
        # esos test contaran también las páginas retiradas y la salvaguarda de proporción dejara
        # de dispararse — pasarían a medir otra cosa sin decirlo. Con 352 páginas en el sitio
        # mayor, la diferencia entre filtrar aquí o allí no se nota; la de traer objetos, sí.
        filas = (
            await session.execute(
                select(HubCrawledPage.url, HubCrawledPage.status).where(
                    HubCrawledPage.site_id == site_id
                )
            )
        ).all()
        return sum(1 for url, estado in filas if estado == "active" and efectivos.en_ambito(url))

    async def _avisar_de_las_bajas(
        self, session: Any, site_id: uuid.UUID, gone_page_ids: list
    ) -> None:
        """Un `page_gone` por página, para la cola de quien cura."""
        from server.app.modules.agents_hub.database.operational_models import HubCrawledPage

        for page_id in gone_page_ids:
            pagina = await session.get(HubCrawledPage, page_id)
            if pagina is None:
                continue
            await self._registrar_hallazgo(
                site_id,
                "page_gone",
                severity="warning",
                page_id=pagina.id,
                source_url=pagina.url,
                signal={"title": getattr(pagina, "title", None)},
            )

    async def _retirar_de_los_chatbots_que_la_publicaron(
        self,
        session: Any,
        site_id: uuid.UUID,
        gone_page_ids: list,
        summary: SiteQualitySummary,
    ) -> None:
        if self._retirer_factory is None:
            return

        from server.app.modules.agents_hub.database.operational_models import HubCrawledPage

        repo = self._selecciones(session)
        selecciones = await repo.list_by_site(site_id)
        if not selecciones:
            return
        secciones = await repo.secciones_de(selecciones)
        retirador = self._retirer_factory(session)

        for page_id in gone_page_ids:
            pagina = await session.get(HubCrawledPage, page_id)
            if pagina is None:
                continue
            for sel in selecciones:
                if not repo.matches(sel, pagina.url, secciones=secciones):
                    continue
                try:
                    await retirador.retire_page(sel.chatbot_id, pagina.id)
                    summary.documents_auto_retired += 1
                except Exception as exc:  # noqa: BLE001
                    # Media retirada silenciosa dejaría el corpus en un estado que nadie sabría
                    # reconstruir: el resto sigue y el fallo consta.
                    logger.exception(
                        "Auto-retirada fallida de %s para el chatbot %s",
                        pagina.url,
                        sel.chatbot_id,
                    )
                    summary.errors.append(f"retirada {pagina.url}: {exc}")

    async def _retirar_avisos_de_paginas_que_volvieron(
        self, session: Any, site_id: uuid.UUID
    ) -> None:
        """Retira los `page_gone` abiertos cuya página ha vuelto a estar activa.

        **No lo puede hacer la reconciliación de CUR.9**: `page_gone` no lo emite ningún detector,
        así que su tipo nunca entra en `tipos_a_reconciliar`. Y reconciliarlo por sitio desde una
        pasada de sección retiraría los avisos de las otras secciones, que es la misma trampa del
        censo de DIN.2. Mirar el estado de la página no tiene ese problema: una página de otra
        sección sigue en `gone`, así que su aviso no se toca.
        """
        from sqlalchemy import select

        from server.app.modules.agents_hub.database.operational_models import (
            HubContentFinding,
            HubCrawledPage,
        )

        abiertos = (
            await session.execute(
                select(HubContentFinding).where(
                    HubContentFinding.site_id == site_id,
                    HubContentFinding.finding_type == "page_gone",
                    HubContentFinding.status.in_(("new", "confirmed")),
                )
            )
        ).scalars().all()
        if not abiertos:
            return

        retirados = 0
        for aviso in abiertos:
            if getattr(aviso, "finding_type", None) != "page_gone":
                continue
            if getattr(aviso, "status", None) not in ("new", "confirmed"):
                continue
            pagina = await session.get(HubCrawledPage, aviso.page_id)
            if pagina is None or getattr(pagina, "status", None) != "active":
                continue
            aviso.status = "resolved"
            aviso.reviewed_at = datetime.now(timezone.utc)
            aviso.resolution_note = NOTA_DE_PAGINA_QUE_VOLVIO
            retirados += 1

        if retirados:
            await session.flush()

    async def _registrar_hallazgo(
        self,
        site_id: uuid.UUID,
        tipo: str,
        *,
        severity: str,
        page_id: uuid.UUID | None = None,
        source_url: str | None = None,
        signal: dict | None = None,
    ) -> None:
        """Escribe un hallazgo del job. Sin repositorio no se escribe, y el job sigue."""
        if self._finding_repo is None:
            return

        from server.app.modules.curation.contracts import ContentFinding

        try:
            await self._finding_repo.upsert(ContentFinding(
                id=uuid.uuid4(),
                site_id=site_id,
                finding_type=tipo,
                severity=severity,
                confidence=1.0,
                detected_at=datetime.now(timezone.utc),
                page_id=page_id,
                source_url=source_url,
                signal=signal or {},
            ))
        except Exception:  # noqa: BLE001 — el aviso no puede tumbar el job de calidad
            logger.exception("No se pudo registrar el hallazgo %s del sitio %s", tipo, site_id)

    async def _avisar_de_la_actualizacion(
        self, site_id: uuid.UUID, page: Any, chatbots_actualizados: int
    ) -> None:
        from datetime import datetime, timezone

        from server.app.modules.curation.contracts import ContentFinding

        try:
            await self._finding_repo.upsert(ContentFinding(
                id=uuid.uuid4(),
                site_id=site_id,
                finding_type="content_updated",
                severity="info",
                confidence=1.0,
                detected_at=datetime.now(timezone.utc),
                page_id=page.id,
                source_url=page.url,
                signal={
                    "chatbots_actualizados": chatbots_actualizados,
                    "title": page.title,
                },
            ))
        except Exception:  # noqa: BLE001 — el aviso no puede tumbar el job de calidad
            logger.exception("No se pudo registrar el aviso de actualización de %s", page.url)

    async def run_for_site(
        self, site_id: uuid.UUID, section_id: uuid.UUID | None = None
    ) -> SiteQualitySummary:
        """Ejecuta el ciclo completo de calidad para un ámbito del sitio.

        `section_id` acota la pasada a una sección (DIN.2): con él, el censo de bajas se compara
        sólo contra las páginas de ese apartado. Sin él, el ámbito es el sitio entero, que es el
        comportamiento de siempre.

        Nunca propaga excepción: todos los errores se acumulan en summary.errors.
        """
        summary = SiteQualitySummary(section_id=section_id)
        comenzado = datetime.now(timezone.utc)

        # ── 1. CRAWL ──────────────────────────────────────────────────────────
        try:
            crawl_summary = await self._site_crawler.crawl_site(
                site_id, section_id=section_id
            )
            summary.pages_new = crawl_summary.pages_new
            summary.pages_changed = crawl_summary.pages_changed
            summary.pages_gone = crawl_summary.pages_gone
            summary.pages_error = crawl_summary.pages_error
            summary.pages_total = crawl_summary.pages_total
            summary.truncated = bool(getattr(crawl_summary, "truncated", False))
            summary.stop_reason = getattr(crawl_summary, "stop_reason", None)
        except Exception as exc:
            logger.exception("Crawl failed for site %s", site_id)
            summary.errors.append(f"crawl: {exc}")
            # DIN.6 — **una pasada que falla también va al diario**, y es cuando más falta hace:
            # sin esto, «no pasó nada» y «el rastreo revento» se leen igual desde la pantalla.
            await self._anotar_en_el_diario(site_id, section_id, comenzado, summary)
            return summary  # Sin crawl no hay diff para detectar ni consolidar

        # ── 2. DETECCIÓN (cada detector aislado) ──────────────────────────────
        all_findings: list = []
        # CUR.9 — quién ha mirado de verdad y quién no. La reconciliación de abajo sólo puede
        # retirar los tipos de los detectores que **han corrido**: un detector que se saltó, o que
        # falló, no autoriza a retirar nada suyo.
        ejecutados: list = []
        omitidos: list = []
        for detector in self._detectors:
            is_sem = getattr(detector, "_is_semantic", False)
            if is_sem and not self._run_semantic:
                omitidos.append(detector)
                continue
            try:
                findings = await detector.analyze(site_id)
                all_findings.extend(findings)
                ejecutados.append(detector)
            except Exception as exc:
                logger.exception("Detector failed for site %s", site_id)
                summary.errors.append(f"detector: {exc}")
                omitidos.append(detector)

        # Conteo por tipo de hallazgo
        for f in all_findings:
            key = getattr(f, "finding_type", "unknown")
            summary.findings_by_type[key] = summary.findings_by_type.get(key, 0) + 1

        # ── 3. CONSOLIDACIÓN + quality_score ──────────────────────────────────
        async with self._session_factory() as session:
            from server.app.modules.agents_hub.database.operational_models import (
                HubCrawledPage,
            )

            # ── 3.pre. RECONCILIACIÓN (CUR.9) ─────────────────────────────────
            #
            # El detector sólo sabía añadir: afirmaba y nunca dejaba de afirmar. Medido tras CUR.7:
            # 241 hallazgos `stale` guardados donde el detector emitía 207, porque las páginas que
            # pasaron a agruparse como serie dejaron de producir aviso y su fila vieja seguía ahí.
            # Del usuario: «no tiene sentido que haya filas que ya no sean ciertas».
            #
            # Va antes de calcular `quality_score` a propósito: la nota de una página no puede
            # seguir castigada por hallazgos que ya se han retirado.
            try:
                summary.findings_retired = await reconciliar_hallazgos(
                    session,
                    site_id,
                    tipos=tipos_a_reconciliar(ejecutados=ejecutados, omitidos=omitidos),
                    emitidos=all_findings,
                    now=datetime.now(timezone.utc),
                )
            except Exception as exc:  # noqa: BLE001 — retirar de más es peor que no retirar
                logger.exception("Reconciliation failed for site %s", site_id)
                summary.errors.append(f"reconciliation: {exc}")

            # Flags de supersesión sobre HubCrawledPage
            for f in all_findings:
                if (
                    getattr(f, "finding_type", "") == "superseded"
                    and getattr(f, "status", "new") in ("new", "confirmed")
                ):
                    page_id = getattr(f, "page_id", None)
                    if page_id:
                        page = await session.get(HubCrawledPage, page_id)
                        if page is not None and not page.superseded:
                            page.superseded = True
                            page.superseded_by_page_id = getattr(f, "related_page_id", None)
                            summary.pages_marked_superseded += 1

            # quality_score por página
            findings_by_page: dict[uuid.UUID, list] = {}
            for f in all_findings:
                pid = getattr(f, "page_id", None)
                if pid:
                    findings_by_page.setdefault(pid, []).append(f)

            for page_id, page_findings in findings_by_page.items():
                page = await session.get(HubCrawledPage, page_id)
                if page is not None:
                    page.quality_score = _compute_quality_score(page_findings)

            await session.flush()

            # ── 3.bis. REINGESTA DE LO QUE CAMBIÓ (RAS.5) ─────────────────────
            #
            # El rastreo ya detectaba el cambio —compara `content_hash` y llena
            # `changed_page_ids`—, pero nadie lo consumía: una página ya publicada se
            # actualizaba en el portal y el asistente seguía respondiendo con el texto viejo.
            #
            # Se reingiere **sólo donde ya estaba**: actualizar lo que alguien aprobó una vez no
            # es publicar lo que nadie ha aprobado. Y no en silencio: queda el aviso
            # `content_updated` para poder revisar qué cambió.
            # DIN.5 — la puerta de calidad, con los criterios efectivos del ámbito (DIN.1).
            efectivos_del_ambito = await self._parametros_del_ambito(
                session, site_id, section_id
            )
            bloqueadas = self._bloqueantes_por_pagina(
                all_findings, efectivos_del_ambito.criterios
            )

            await self._reingerir_lo_que_cambio(
                session,
                site_id,
                getattr(crawl_summary, "changed_page_ids", []),
                summary,
                bloqueadas,
            )

            # ── 4. AUTO-INGESTA (páginas nuevas del diff) ──────────────────────
            #
            # **La condición era `self._watcher is not None`, y en producción el watcher fijo es
            # `None`**: el arranque pasa una *fábrica* porque cada chatbot ingiere con su propio
            # servicio de embeddings (RAS.5). Con eso, y con el repositorio de selecciones nulo
            # que también pasaba el arranque, este paso no ha corrido nunca fuera de los tests.
            new_page_ids: list[uuid.UUID] = getattr(crawl_summary, "new_page_ids", [])
            repo_de_selecciones = self._selecciones(session)
            if new_page_ids and (
                self._watcher is not None or self._watcher_factory is not None
            ):
                selections = await repo_de_selecciones.list_by_site(site_id)
                auto_sels = [s for s in selections if getattr(s, "auto_ingest_new", False)]

                if auto_sels:
                    # DIN.3 — las secciones a las que apuntan, cargadas antes del bucle.
                    secciones = await repo_de_selecciones.secciones_de(auto_sels)
                    for page_id in new_page_ids:
                        page = await session.get(HubCrawledPage, page_id)
                        if page is None:
                            continue

                        # DIN.5 — la automatización no puede tener menos criterio que el
                        # curador al que sustituye: si el job acaba de decir que esta página no
                        # se puede leer, no entra. **No se marca nada**: sigue siendo candidata,
                        # y resuelto el hallazgo la pasada siguiente la ingiere sola.
                        motivos = bloqueadas.get(page_id)
                        if motivos:
                            summary.pages_blocked_by_findings += 1
                            await self._registrar_hallazgo(
                                site_id,
                                "auto_ingesta_detenida",
                                severity="warning",
                                page_id=page.id,
                                source_url=page.url,
                                signal={"motivos": motivos, "paso": "auto-ingesta"},
                            )
                            continue

                        for sel in auto_sels:
                            if repo_de_selecciones.matches(
                                sel, page.url, secciones=secciones
                            ):
                                try:
                                    watcher = await self._watcher_para(
                                        session, sel.chatbot_id
                                    )
                                    await watcher.process_source(
                                        source_url=page.url,
                                        chatbot_id=sel.chatbot_id,
                                        prefetched_content=page.markdown_content,
                                        title=page.title,
                                        crawled_page_id=page.id,
                                    )
                                    summary.documents_auto_ingested += 1
                                except Exception as exc:
                                    logger.exception(
                                        "Auto-ingest failed for page %s chatbot %s",
                                        page.url,
                                        sel.chatbot_id,
                                    )
                                    summary.errors.append(f"auto-ingest {page.url}: {exc}")

            # ── 5. AUTO-RETIRADA DE LO QUE DESAPARECIÓ (DIN.4) ─────────────────
            #
            # Va **después** de la auto-ingesta a propósito: si una página se movió dentro del
            # apartado, la nueva ya está ingerida cuando se retira la vieja, y el corpus no se
            # queda sin ella ni un momento.
            try:
                await self._retirar_lo_que_desaparecio(
                    session,
                    site_id,
                    section_id,
                    getattr(crawl_summary, "gone_page_ids", []),
                    summary,
                )
            except Exception as exc:  # noqa: BLE001 — retirar de menos es mejor que tumbar
                logger.exception("Auto-retirada fallida en el sitio %s", site_id)
                summary.errors.append(f"auto-retirada: {exc}")

            # ── CONFIRMAR LO QUE ESTA SESIÓN HA ESCRITO ────────────────────────
            #
            # **Aquí no había nada, y el job llevaba desde 9Q.5 escribiendo en el vacío.** La
            # sesión se abría con `async with self._session_factory() as session:` y sólo se le
            # hacía `flush`; al cerrarse, lo pendiente se deshace. Se perdían el `quality_score`
            # y las supersesiones de 9Q.5 — y, desde DIN.4, **la retirada del corpus**: el
            # resumen decía «retirada 1», el diario lo escribía (tiene transacción propia) y el
            # documento seguía ahí. Lo destapó el ciclo real de DIN.7.
            #
            # Retirar mintiendo es peor que no retirar, así que esto no puede volver a faltar:
            # hay un test que comprueba que la sesión se confirma.
            try:
                await session.commit()
            except Exception as exc:  # noqa: BLE001
                logger.exception("No se pudo confirmar la pasada del sitio %s", site_id)
                summary.errors.append(f"commit: {exc}")

        # ── 6. EL DIARIO DE LA PASADA (DIN.6) ──────────────────────────────────
        await self._anotar_en_el_diario(site_id, section_id, comenzado, summary)

        return summary

    async def _anotar_en_el_diario(
        self,
        site_id: uuid.UUID,
        section_id: uuid.UUID | None,
        comenzado: datetime,
        summary: SiteQualitySummary,
    ) -> None:
        """Deja constancia de la pasada. Sin diario, el job funciona igual que antes.

        Fuera de la transacción del job, y sin propagar: el diario cuenta lo que pasó, y un
        fallo al contarlo no puede deshacer lo que ya se hizo ni tumbar la pasada.
        """
        if self._run_log is None:
            return
        try:
            await self._run_log.registrar(
                site_id=site_id,
                section_id=section_id,
                scope_label=await self._etiqueta_del_ambito(site_id, section_id),
                started_at=comenzado,
                finished_at=datetime.now(timezone.utc),
                summary=summary,
            )
        except Exception:  # noqa: BLE001
            logger.exception("No se pudo anotar la pasada del sitio %s en el diario", site_id)

    async def _etiqueta_del_ambito(
        self, site_id: uuid.UUID, section_id: uuid.UUID | None
    ) -> str:
        """El nombre de la sección, o «sitio». Se guarda en texto porque el diario es historia:
        si alguien borra la sección, la fila tiene que seguir diciendo qué cubrió."""
        if section_id is None:
            return ETIQUETA_DEL_SITIO_ENTERO
        from server.app.modules.agents_hub.database.operational_models import HubWebSection

        async with self._session_factory() as session:
            seccion = await session.get(HubWebSection, section_id)
            return getattr(seccion, "name", None) or str(section_id)
