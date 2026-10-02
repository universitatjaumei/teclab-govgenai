"""Punto de entrada FastAPI standalone del servidor Gov Gen AI.

Registra los routers de la plataforma, repartidos entre `_register_cloud` y `_register_edge`
según `DEPLOY_MODE` (ver `AGENTS.md` §Frontera Edge-Cloud).

**AIS.2 — esta cabecera decía que los routers `automation`/`telemetry` «quedan pendientes de
registrar aquí»**. No están pendientes: se **borraron** en ROL.1 (`6e78b35`), junto con
`AIBrainService`. Es lo primero que lee quien abre el punto de entrada del servidor, y mandaba a
buscar trabajo que ya no existe.
"""

from contextlib import asynccontextmanager
import logging
import os
import traceback
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from server.app.core.cors import politica_cors
from server.app.core.version import version
from server.app.core.security_headers import (
    SecurityHeadersMiddleware,
    urls_de_documentacion,
)
from server.app.api.v1.hub_chat import router as hub_chat_router
from server.app.api.v1.hub_feedback import router as hub_feedback_router
from server.app.api.v1.hub_usage import router as hub_usage_router
from server.app.api.v1.hub_tasks import router as hub_tasks_router
from server.app.api.v1.ingestion import router as ingestion_router
from server.app.api.v1.edge_sync import router as edge_sync_router
from server.app.routers.auth_router import router as auth_router
from server.app.routers.google_auth_router import router as google_auth_router
from server.app.routers.saml_auth_router import router as saml_auth_router
from server.app.routers.pat_router import router as pat_router
from server.app.routers.library_router import router as library_router
from server.app.routers.hub_chatbots_router import router as hub_chatbots_router
from server.app.routers.hub_organizaciones_router import router as hub_organizaciones_router
from server.app.routers.hub_ingestion_router import router as hub_ingestion_router
from server.app.routers.hub_llm_configs_router import router as hub_llm_configs_router
from server.app.routers.hub_prompt_templates_router import router as hub_prompt_templates_router
from server.app.routers.hub_activity_prompts_router import router as hub_activity_prompts_router
from server.app.routers.hub_prompts_catalog_router import router as hub_prompts_catalog_router
from server.app.routers.redaccion.llm_drafts_router import router as llm_drafts_router
from server.app.routers.redaccion.hub_redaccion_router import router as hub_redaccion_router
from server.app.routers.redaccion.workspaces_router import router as redaccion_workspaces_router
from server.app.routers.redaccion.funciones_router import router as redaccion_funciones_router
from server.app.routers.redaccion.funciones_run_router import router as redaccion_funciones_run_router
from server.app.routers.redaccion.scripts_router import router as redaccion_scripts_router
from server.app.routers.redaccion.charts_router import router as redaccion_charts_router
from server.app.routers.redaccion.manifests_router import router as redaccion_manifests_router
from server.app.routers.redaccion.copilot_router import router as redaccion_copilot_router
from server.app.routers.redaccion.anonymization_router import router as redaccion_anonymization_router
from server.app.routers.hub_themes_router import router as hub_themes_router
from server.app.routers.hub_users_router import router as hub_users_router
from server.app.routers.hub_modulos_router import router as hub_modulos_router
from server.app.routers.hub_opciones_router import router as hub_opciones_router
from server.app.routers.actividad_router import router as actividad_router
from server.app.routers.governanca_router import router as governanca_router
from server.app.routers.anonimizacion_router import router as anonimizacion_router
from server.app.routers.verificaciones_router import router as verificaciones_router
from server.app.routers.hub_agents_router import router as hub_agents_router
from server.app.routers.hub_sites_router import router as hub_sites_router
from server.app.routers.hub_content_quality_router import router as hub_content_quality_router
from server.app.routers.hub_test_scenarios_router import router as hub_test_scenarios_router
from server.app.routers.utilidades_router import router as utilidades_router


_log = logging.getLogger("govgenai")


def configurar_logging() -> None:
    """La configuración de logging de la aplicación (AIS.8).

    Hasta aquí **no había ninguna**: el único `basicConfig` del proyecto vivía dentro de un
    script de reingesta, así que en el servidor los mensajes salían por `print` —157 de ellos—
    sin nivel, sin marca de tiempo y sin forma de subir o bajar el detalle. En el piloto eso
    significa que la única observabilidad es la consola, y que un fallo intermitente no deja
    rastro con el que volver.

    **No usa `basicConfig(force=True)`, y la razón la encontró la suite.** `force=True` *elimina*
    los manejadores que ya hubiera, y eso incluye el que instala pytest para capturar registros:
    dos tests se pusieron en rojo —uno afirmando que un arranque fallido deja su causa en el log,
    justo lo que este prompt viene a mejorar—. Un mecanismo de observabilidad que apaga a otro no
    es observabilidad.

    Así que se configura **sin destruir**: se fija el nivel y se le pone el formato a los
    manejadores que haya —los de uvicorn, que llega antes— y sólo se añade uno si no hay ninguno.
    El resultado en producción es el mismo y deja de pisar a nadie.

    El nivel sale de `LOG_LEVEL`. Esta frase decía que estaba «en el compose de producción y
    en `.env.example`», y en `.env.example` **no estaba**: se escribió a la vez que la
    intención y nadie volvió a mirarlo. Ahora sí (issue #42), junto con las otras seis que
    el código leía sin que ningún inventario las declarara.
    """
    nivel = getattr(logging, (os.getenv("LOG_LEVEL") or "INFO").upper(), logging.INFO)
    formato = logging.Formatter("%(asctime)s %(levelname)-8s %(name)s — %(message)s")

    raiz = logging.getLogger()
    raiz.setLevel(nivel)
    if not raiz.handlers:
        manejador = logging.StreamHandler()
        manejador.setFormatter(formato)
        raiz.addHandler(manejador)
    else:
        for manejador in raiz.handlers:
            manejador.setFormatter(formato)


def _start_quality_scheduler():
    """Crea e inicia el scheduler de calidad de contenido web (9Q.5).

    Deploy: edge. Retorna el scheduler o None si está deshabilitado.
    """
    try:
        from server.app.core.config import get_settings
        settings = get_settings()

        if not settings.content_quality_enabled:
            return None

        from server.app.modules.agents_hub.database.connection import (
            create_async_engine,
            create_session_factory,
        )
        from server.app.modules.curation.diario import DiarioDePasadas
        from server.app.modules.curation.quality_job import (
            SiteQualityAnalysisJob,
        )
        from server.app.modules.curation.quality_scheduler import (
            create_quality_scheduler,
        )

        engine = create_async_engine()
        hub_session_factory = create_session_factory(engine)

        # SEC.8.8: el rastreo real. Antes iba un `_NullCrawler` con la promesa de que los
        # componentes reales «se inyectan en producción a través de la configuración de
        # cada entorno» — mecanismo que no existía, así que el botón de rastrear de la
        # interfaz respondía 202 y no hacía nada. El rastreo es la ENTRADA del flujo de
        # curación: sin él no hay páginas que auditar, ni hallazgos, ni candidatas.
        #
        # Los dos detectores se enchufan aquí. El semántico va detrás de su flag —cuesta
        # embeddings y una llamada al modelo por par— y del alcance de cada sitio.
        from server.app.modules.curation.site_crawler_dispatcher import (
            SiteCrawlerDispatcher,
            detectores_de_calidad,
        )

        # RAS.5 — la fábrica de watchers y el repo de hallazgos. Iban a `None`, así que el
        # rastreo detectaba que una página del corpus había cambiado, lo contaba… y el
        # asistente seguía respondiendo con el texto viejo. Ahora la página se reingiere con
        # el modelo de embeddings de **su** chatbot y queda el aviso `content_updated`.
        async def _watcher_para(session: Any, chatbot_id: Any) -> Any:
            from server.app.modules.agents_hub.ingestion.watcher import IngestionWatcher
            from server.app.modules.agents_hub.services.embedding_resolver import (
                resolve_embedding_service,
            )

            return IngestionWatcher(
                session=session,
                embedding_service=await resolve_embedding_service(session, chatbot_id),
            )

        job = SiteQualityAnalysisJob(
            session_factory=hub_session_factory,
            site_crawler=SiteCrawlerDispatcher(hub_session_factory),
            # CUR.7 — los **dos** detectores. Aquí iba sólo el determinista, así que
            # `audit_semantic_scope='full'` y `run_semantic=True` no significaban nada: el
            # semántico existía desde 9Q.4 con sus tests y no lo ejecutaba nadie.
            detectors=detectores_de_calidad(
                hub_session_factory,
                run_semantic=settings.content_quality_semantic_enabled,
            ),
            watcher=None,
            # DIN.4 — el repositorio y el retirador se resuelven **con la sesión de cada
            # pasada**. Aquí iba un repositorio nulo que devolvía lista vacía a todo, y con él
            # la auto-ingesta de 9Q.7 no ha corrido nunca en producción.
            selection_repo=None,
            selection_repo_factory=_repo_de_selecciones,
            retirer_factory=_retirador_del_corpus,
            run_semantic=settings.content_quality_semantic_enabled,
            watcher_factory=_watcher_para,
            finding_repo=_RepoDeHallazgosDelJob(hub_session_factory),
            # DIN.6 — el diario. Con su propia transacción, como el repositorio de avisos: es
            # información sobre algo que ya pasó, y perderla por un rollback del job sería
            # perder justo el rastro del problema.
            run_log=DiarioDePasadas(hub_session_factory),
        )

        scheduler = create_quality_scheduler(
            hub_session_factory,
            job,
            interval_hours=settings.content_quality_interval_hours,
            enabled=settings.content_quality_enabled,
        )
        scheduler.start()
        # Registrar el job en el router de sitios para el endpoint /crawl
        from server.app.routers.hub_sites_router import set_quality_job
        set_quality_job(job)
        from server.app.routers.hub_content_quality_router import set_quality_job as set_cq_job
        set_cq_job(job)
        _log.info(
            "Planificador de calidad de contenido arrancado (cada %sh)",
            settings.content_quality_interval_hours,
        )
        return scheduler
    except Exception:
        # AIS.8 — `exception` y no `print(exc)`. Esto se tragaba el fallo con una línea sin
        # traza: el planificador es lo que mantiene vigilado el corpus, así que arrancar sin él
        # es una degradación silenciosa que sólo se nota semanas después, cuando alguien
        # pregunta por qué no hay hallazgos nuevos.
        _log.exception("El planificador de calidad de contenido no arrancó")
        return None


class _RepoDeHallazgosDelJob:
    """Escribe los avisos del job de calidad en su propia transacción (RAS.5).

    El aviso de que una página del corpus se ha actualizado no puede depender de que la
    transacción del job termine bien: es información sobre algo que **ya pasó** —la página se
    reingirió— y perderla dejaría el corpus cambiado sin rastro en la bandeja.
    """

    def __init__(self, session_factory: Any) -> None:
        self._session_factory = session_factory

    async def upsert(self, finding: Any) -> Any:
        from server.app.modules.curation.findings_repo import ContentFindingRepo

        async with self._session_factory() as session:
            resultado = await ContentFindingRepo(session).upsert(finding)
            await session.commit()
            return resultado


def _repo_de_selecciones(session: Any) -> Any:
    """El repositorio de selecciones de la pasada de calidad (DIN.4).

    **Aquí iba `_NullSelectionRepo`, que devolvía lista vacía a todo.** Era un sustituto puesto
    porque el repositorio real necesita una sesión y el job se construye al arrancar — pero con
    él, el paso de auto-ingesta de 9Q.7 preguntaba «¿qué selecciones tiene este sitio?» y la
    respuesta era siempre «ninguna»: la auto-ingesta de páginas nuevas no ha corrido nunca en
    producción. Con una fábrica, el job resuelve el repositorio con la sesión de cada pasada.
    """
    from server.app.modules.curation.site_repo import CorpusSelectionRepo

    return CorpusSelectionRepo(session)


def _retirador_del_corpus(session: Any) -> Any:
    """Quien sabe retirar del corpus los documentos de una página (DIN.4).

    Es el mismo `CorpusSelectionService` del endpoint manual de retirada, y por eso no hace
    falta un segundo camino: `retire_page` borra documentos y *chunks*, y no necesita watcher
    —retirar no ingiere nada—.
    """
    from server.app.modules.curation.selection_service import CorpusSelectionService
    from server.app.modules.curation.site_repo import (
        CorpusSelectionRepo,
        CrawledPageRepo,
    )

    return CorpusSelectionService(
        session, CrawledPageRepo(session), CorpusSelectionRepo(session), watcher=None
    )


async def _fail_zombie_jobs() -> None:
    """Marca como fallidos los jobs que quedaron en running/pending al reiniciar el servidor."""
    from sqlalchemy import update
    from server.app.modules.agents_hub.database.connection import get_async_session
    from server.app.modules.agents_hub.database.operational_models import HubIngestionJob
    async for session in get_async_session():
        await session.execute(
            update(HubIngestionJob)
            .where(HubIngestionJob.status.in_(["running", "pending"]))
            .values(status="failed", error_message="Job interrumpido (servidor reiniciado)")
        )
        await session.commit()


logger = logging.getLogger(__name__)


def _resumen_del_fallo(exc: BaseException) -> str:
    """La causa de un fallo de arranque, en pocas líneas y apuntando a nuestro código.

    FastAPI fusiona un `lifespan` por cada router incluido, así que con unas cuarenta superficies
    HTTP el traceback llega con ~40 marcos idénticos de `merged_lifespan` **antes** de la
    excepción real. Cualquier captura de log lo corta por el medio y se pierde justo el mensaje
    que importa: en los logs que motivaron esto, la traza terminaba a media palabra y lo único
    legible era «Application startup failed».

    Aquí se descartan los marcos de librería y se conserva la cadena de causas, porque un
    `ImportError` envuelto en otro error no dice nada si se pierde el original.
    """
    lineas: list[str] = []
    actual: BaseException | None = exc
    visitadas: set[int] = set()

    while actual is not None and id(actual) not in visitadas and len(lineas) < 10:
        visitadas.add(id(actual))
        prefijo = "causado por: " if lineas else ""
        lineas.append(f"{prefijo}{type(actual).__name__}: {actual}")

        nuestros = [
            marco
            for marco in traceback.extract_tb(actual.__traceback__)
            if "site-packages" not in marco.filename and "contextlib" not in marco.filename
        ]
        if nuestros:
            ultimo = nuestros[-1]
            fichero = ultimo.filename.replace("\\", "/").split("/")[-1]
            lineas.append(f"    en {fichero}:{ultimo.lineno} ({ultimo.name})")

        actual = actual.__cause__ or actual.__context__

    return "\n".join(lineas)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        async with _arranque(app):
            yield
    except BaseException as exc:
        # Se registra y **se vuelve a lanzar**: tragarse el error dejaría la aplicación en pie
        # y a medio construir, que es peor que no arrancar.
        logger.critical(
            "El arranque ha fallado. Causa:\n%s", _resumen_del_fallo(exc)
        )
        raise


async def _sincronizar_funciones_de_paquete() -> None:
    """Sincroniza `govgenai.funciones` con el catálogo. Falla en alto si un paquete es incoherente.

    Abre su propia sesión, como el resto de pasos del arranque que escriben, y commitea: sin el
    `commit` el trabajo se deshace al cerrar el contexto y el arranque diría «sincronizado» sin
    haber escrito nada — es exactamente el defecto que DIN.7 encontró en el job de calidad.
    """
    from server.app.database.db import AsyncSessionLocal
    from server.app.modules.redaccion.funciones_paquete import sincronizar_paquetes

    async with AsyncSessionLocal() as session:
        resumen = await sincronizar_paquetes(session)
        await session.commit()

    logger.info(
        "Funciones empaquetadas: %s instaladas (%s nuevas, %s versiones nuevas, %s fuera de "
        "servicio)",
        len(resumen.entry_points),
        resumen.funciones_nuevas,
        resumen.versiones_nuevas,
        resumen.versiones_desinstaladas,
    )


@asynccontextmanager
async def _arranque(app: FastAPI):
    # Lo primero, antes de que nada tenga algo que decir: si se configurara después, los
    # mensajes del propio arranque —que son los que más falta hacen cuando algo va mal— se
    # perderían o saldrían con el formato de otro.
    configurar_logging()
    # PLG.1 — descubrir los perfiles, pipelines y estrategias declarados por *entry points*, del
    # núcleo y de cualquier paquete instalado. Va aquí, pronto y **antes de servir**, porque los
    # dos fallos que puede dar —un paquete que no carga, dos que declaran el mismo nombre— son
    # de configuración del entorno: tienen que romper el arranque y no la primera petición.
    #
    # `verificar_perfiles_registrados` construye cada perfil configurable y comprueba que sale un
    # grafo con sus cuatro ejes. Es lo que `tests/public_graphs/test_profile_contract.py` hace
    # con lo que está en el árbol, llevado al arranque para **lo instalado**: un perfil que llega
    # en un paquete no lo cubre ningún test de este repositorio.
    from server.app.modules.agents_hub.agent.public_graphs import plugins

    descubierto = plugins.descubrir_todo()
    logger.info("Descubrimiento por entry points: %s", descubierto)
    plugins.verificar_perfiles_registrados()
    # El esquema NO se crea aquí. Hasta BD.2 (2026-09-04) el arranque hacía `create_all` sobre
    # los tres metadatos, además de lo que Alembic aplica en el despliegue: dos fuentes, y la que
    # nunca borra ganaba — así quedaron 36 tablas de modelos retirados en la base de desarrollo.
    # Alembic es la única fuente: `alembic upgrade head` antes de arrancar, y `alembic check` en
    # CI para que un modelo sin migración se vea en el push. Si la base no está migrada, la
    # primera consulta falla con claridad, que es mejor que una tabla aparecida en silencio.
    await _fail_zombie_jobs()
    from server.app.database.seeds import seed_all

    await seed_all()
    from server.app.modules.agents_hub.database.seeds import seed_hub_defaults

    await seed_hub_defaults()

    # FUN.5 — poner el catálogo de funciones al día con los paquetes instalados. Va **después**
    # de las semillas, porque escribe en la base, y **antes de servir**, porque sus dos fallos
    # —un contrato incoherente, dos paquetes que declaran lo mismo— son de configuración del
    # entorno: tienen que romper el arranque y no la primera plantilla que referencie la función.
    #
    # Y va cableado aquí y no en un script aparte por la lección de DIN.4: una capacidad que el
    # arranque no llama no existe, y allí costó descubrir que la auto-ingesta llevaba meses sin
    # correr en producción.
    await _sincronizar_funciones_de_paquete()

    from server.app.services.model_fetcher import refresh_model_cache
    from server.app.services.pricing_service import update_prices_from_openrouter
    import asyncio

    # Initial refresh at startup (legacy behavior)
    _log.info("Refrescando la caché de modelos de IA")
    await refresh_model_cache()
    _log.info("Actualizando precios de los modelos")
    await update_prices_from_openrouter()

    # Background loop for 24h refresh
    async def periodic_refresh():
        while True:
            await asyncio.sleep(24 * 60 * 60)  # 24 hours
            await refresh_model_cache()
            await update_prices_from_openrouter()

    refresh_task = asyncio.create_task(periodic_refresh())

    # AUT.7 — el barrido de artefactos caducados. Hasta la PR #210 existía y no lo llamaba nada,
    # así que `retencion_dias` prometía un borrado que no ocurría: la descarga daba 404 y el
    # fichero seguía en el almacenamiento. Es la lección de DIN.4 otra vez — una capacidad que el
    # arranque no llama no existe —, y un test mira que esta línea siga aquí.
    from server.app.core.storage import get_storage_service
    from server.app.database.db import AsyncSessionLocal
    from server.app.modules.redaccion.funciones_artefactos import bucle_de_caducados

    caducados_task = asyncio.create_task(
        bucle_de_caducados(AsyncSessionLocal, almacen=get_storage_service())
    )

    # Content quality scheduler (9Q.5) — Deploy: edge
    quality_scheduler = _start_quality_scheduler()

    yield

    refresh_task.cancel()
    caducados_task.cancel()
    if quality_scheduler is not None:
        quality_scheduler.shutdown(wait=False)


# SEC.7: el entorno se lee una vez y decide dos cosas —si se publica la documentación
# interactiva y si se manda HSTS—. `os.getenv` y no `get_settings()` porque esto corre
# en el import del módulo, donde `get_settings()` exigiría ya el JWT_SECRET_KEY.
ENTORNO = os.getenv("ENVIRONMENT", "development")

app = FastAPI(
    title="Gov Gen AI Platform",
    version="1.0.0",
    lifespan=lifespan,
    # En producción, `/docs` y `/openapi.json` publican el mapa entero de la API,
    # rutas de administración incluidas. No oculta ninguna vulnerabilidad: es que no
    # hay razón para servir el índice.
    **urls_de_documentacion(ENTORNO),
)

app.add_middleware(SecurityHeadersMiddleware, entorno=ENTORNO)

# SEC.3: los orígenes salen de la configuración y no del código. En producción no hay
# comodín ni aunque la variable de entorno lo traiga; el porqué está en `core/cors.py`.
app.add_middleware(
    CORSMiddleware,
    **politica_cors(
        entorno=ENTORNO,
        origenes_csv=os.getenv("CORS_ALLOWED_ORIGINS"),
    ),
)

DEPLOY_MODE = os.getenv("DEPLOY_MODE", "all").lower()
if DEPLOY_MODE not in ("cloud", "edge", "all"):
    raise RuntimeError(f"Invalid DEPLOY_MODE: {DEPLOY_MODE}")


def _register_cloud(app: FastAPI) -> None:
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(saml_auth_router, prefix="/api/v1")  # Deploy: cloud
    app.include_router(google_auth_router, prefix="/api/v1")  # Deploy: cloud
    app.include_router(pat_router, prefix="/api/v1")  # Deploy: cloud
    app.include_router(library_router, prefix="/api")
    app.include_router(hub_chatbots_router, prefix="/api/v1")
    app.include_router(hub_organizaciones_router, prefix="/api/v1")
    app.include_router(hub_ingestion_router, prefix="/api/v1")
    app.include_router(hub_llm_configs_router, prefix="/api/v1")
    app.include_router(hub_prompt_templates_router, prefix="/api/v1")
    app.include_router(hub_activity_prompts_router, prefix="/api/v1")  # Deploy: cloud
    app.include_router(hub_prompts_catalog_router, prefix="/api/v1")  # Deploy: cloud
    app.include_router(hub_themes_router, prefix="/api/v1")  # Deploy: cloud
    app.include_router(hub_users_router, prefix="/api/v1")  # Deploy: cloud
    app.include_router(hub_modulos_router, prefix="/api/v1")  # Deploy: cloud
    app.include_router(hub_opciones_router, prefix="/api/v1")  # Deploy: cloud (LANG.2)
    app.include_router(edge_sync_router, prefix="/api/v1")  # servido por cloud


def _register_edge(app: FastAPI) -> None:
    app.include_router(hub_chat_router, prefix="/api/v1")
    app.include_router(hub_feedback_router, prefix="/api/v1")
    app.include_router(actividad_router, prefix="/api/v1")  # Deploy: edge (REG.2)
    app.include_router(governanca_router, prefix="/api/v1")  # Deploy: edge (AUT.6)
    app.include_router(anonimizacion_router, prefix="/api/v1")  # Deploy: edge (REG.3)
    app.include_router(verificaciones_router, prefix="/api/v1")  # Deploy: edge (VAS.1)
    app.include_router(hub_usage_router, prefix="/api/v1")  # Deploy: edge (SEC.4)
    app.include_router(hub_tasks_router, prefix="/api/v1")
    app.include_router(ingestion_router, prefix="/api/v1")
    app.include_router(llm_drafts_router, prefix="/api/v1")  # Deploy: edge
    app.include_router(hub_redaccion_router, prefix="/api/v1")  # Deploy: edge
    app.include_router(redaccion_workspaces_router, prefix="/api/v1")  # Deploy: edge
    app.include_router(redaccion_scripts_router, prefix="/api/v1")  # Deploy: edge
    app.include_router(redaccion_funciones_router, prefix="/api/v1")  # Deploy: edge
    app.include_router(redaccion_funciones_run_router, prefix="/api/v1")  # Deploy: edge
    app.include_router(redaccion_charts_router, prefix="/api/v1")  # Deploy: edge
    app.include_router(redaccion_manifests_router, prefix="/api/v1")  # Deploy: edge
    app.include_router(redaccion_copilot_router, prefix="/api/v1")  # Deploy: edge
    app.include_router(redaccion_anonymization_router, prefix="/api/v1")  # Deploy: edge
    app.include_router(hub_agents_router, prefix="/api/v1")  # Deploy: edge
    app.include_router(hub_sites_router, prefix="/api/v1")  # Deploy: edge
    app.include_router(hub_content_quality_router, prefix="/api/v1")  # Deploy: edge
    app.include_router(hub_test_scenarios_router, prefix="/api/v1")  # Deploy: edge
    app.include_router(utilidades_router, prefix="/api/v1")  # Deploy: edge


if DEPLOY_MODE in ("cloud", "all"):
    _register_cloud(app)
if DEPLOY_MODE in ("edge", "all"):
    _register_edge(app)


@app.get("/health")
async def health() -> dict:
    return {"status": "healthy"}


@app.get("/api/v1/instancia")
async def instancia() -> dict:
    """Metadatos públicos de este despliegue (AIS.6).

    Hoy sólo lleva el **enlace al código fuente que exige el §13 de la AGPL**: quien ejecuta una
    versión modificada del programa y la ofrece por red tiene que dar su fuente a los usuarios de
    **esa** instancia.

    **Público y sin credencial a propósito.** La obligación es frente a quien usa el programa
    remotamente, y eso incluye a la ciudadanía que escribe en el widget embebido —el caso que el
    README señala como el que se olvida—. Un endpoint autenticado dejaría fuera precisamente a
    los usuarios más numerosos. No expone nada sensible: es una URL que quien despliega ha
    decidido publicar.

    **Sale de `SOURCE_URL` y no de una constante** porque el §13 pide el *Corresponding Source*
    de esa versión —el fork, en el commit desplegado—, no el del proyecto de origen. Una URL fija
    al principal haría que cualquier despliegue modificado incumpliera mientras cree que cumple.

    Vacía = sin enlace: quien despliega el código **sin modificar** no queda sujeto a esta
    obligación concreta, así que forzar un valor sería inventarse un requisito.

    **Y `version`**, que es lo que permite preguntarle a un despliegue en marcha qué ejecuta.
    Va aquí y no en `/health` porque `/health` es una sonda de vida —la consume un supervisor que
    sólo mira el código de estado— mientras que este endpoint ya declara ser los metadatos
    públicos de este despliegue, que es justo lo que una versión es. Y por la misma razón que el
    enlace: público y sin credencial, porque quien reporta un fallo desde el widget embebido
    tiene que poder decir en qué versión le pasó.
    """
    return {
        "source_url": (os.getenv("SOURCE_URL") or "").strip() or None,
        "version": version(),
    }
