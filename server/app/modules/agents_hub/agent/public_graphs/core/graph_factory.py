"""GraphFactory — punto de integración: config → perfil → CoreGraph.

Flujo:
  1. get_effective_public_graph_config(chatbot_id, session) → PublicGraphConfig
  2. registry.get_profile(cfg.profile) → ProfileFactory
  3. ProfileFactory(cfg, deps, llm) → CoreGraph

Deploy: edge
"""
from __future__ import annotations

import uuid
from typing import Any

from server.app.modules.agents_hub.agent.public_graphs.core.config_resolver import (
    get_effective_public_graph_config,
)
from server.app.modules.agents_hub.agent.public_graphs.core.core_graph import CoreGraph
from server.app.modules.agents_hub.agent.public_graphs.registry import (
    GraphProfileRegistry,
    _default_registry,
)


class GraphFactory:
    """Resuelve la config efectiva, selecciona el perfil del registry y crea CoreGraph."""

    def __init__(self, registry: GraphProfileRegistry | None = None) -> None:
        self._registry = registry if registry is not None else _default_registry

    async def build(
        self,
        chatbot_id: uuid.UUID,
        deps: Any,
        llm: Any = None,
    ) -> CoreGraph:
        cfg = await get_effective_public_graph_config(chatbot_id, deps.session)
        profile_factory = self._registry.get_profile(cfg.profile)
        grafo = profile_factory(cfg, deps, llm)
        # PLG.2 — las sobreescrituras por eje se aplican AQUÍ, en la misma capa que `rewrite_llm`
        # y el bucle agéntico, y por el mismo motivo: son decisiones de composición que dependen
        # de la cascada. Ni las factorías de perfil ni `CoreGraph` saben que existen, que es lo
        # que permite que un perfil de un paquete se beneficie de ellas sin hacer nada.
        _aplicar_sobreescrituras(grafo, cfg, deps, llm)
        # RAG.10: el LLM de reescritura se asigna aquí y no se pasa por las tres factorías
        # de perfil. Es una decisión de composición que depende de la cascada —igual que el
        # AgenticLoop— y añadirlo a sus firmas obligaría a los tres perfiles a conocer algo
        # que ninguno usa. Si el modelo no se puede construir, la reescritura simplemente no
        # está disponible: el chat no puede caerse por una optimización de recuperación.
        if getattr(cfg, "query_rewriting_enabled", False):
            grafo.rewrite_llm = await _resolver_llm_de_reescritura(cfg, deps)
        return grafo


def _aplicar_sobreescrituras(grafo: CoreGraph, cfg: Any, deps: Any, llm: Any) -> None:
    """Sustituye en el grafo los ejes cuyo nombre resuelto difiera del que montó el perfil.

    Sólo se toca lo que cambia: si la composición resuelta coincide con la del perfil —el caso
    normal— no se instancia nada y el grafo sale exactamente igual que antes de PLG.2.

    **Un nombre no registrado revienta aquí, en alto.** No se cae al defecto en silencio, y ésa es
    la lección de los perfiles sin configurar (hallazgo I5): un asistente que responde «no
    encuentro información» con el corpus cargado cuesta días de encontrar, mientras que un error
    con el eje, el nombre y el chatbot se arregla en un minuto.
    """
    from server.app.modules.agents_hub.agent.public_graphs.strategies.registry import (
        ATRIBUTO_DE_EJE,
        EjeDeEstrategia,
        UnknownStrategyError,
        get_strategy,
    )

    resueltas = getattr(cfg, "estrategias", None) or {}
    for eje_txt, nombre in resueltas.items():
        try:
            eje = EjeDeEstrategia(eje_txt)
        except ValueError:
            raise RuntimeError(
                f"El chatbot {getattr(cfg, 'chatbot_id', '?')} tiene configurado el eje de "
                f"estrategia '{eje_txt}', que no existe."
            ) from None

        atributo = ATRIBUTO_DE_EJE[eje]
        montada = getattr(grafo, atributo, None)
        if nombre == COMPOSICION_PUBLIC_KB_RICH.get(eje_txt) and montada is not None:
            # El perfil ya montó ésta. Se evita instanciarla dos veces, que además de gastar
            # cambiaría la identidad del objeto y rompería los tests de regresión por `type()`.
            continue
        try:
            factoria = get_strategy(eje, nombre)
        except UnknownStrategyError as exc:
            raise RuntimeError(
                f"El chatbot {getattr(cfg, 'chatbot_id', '?')} pide la estrategia "
                f"'{eje_txt}.{nombre}', que no está registrada. {exc}"
            ) from exc
        setattr(grafo, atributo, factoria(cfg, deps, llm))


# ---------------------------------------------------------------------------
# Registro de perfiles en el registry por defecto
# ---------------------------------------------------------------------------


async def _resolver_llm_de_reescritura(cfg: Any, deps: Any):
    """Modelo de reescritura, o None si no se puede construir (RAG.10).

    Devolver None en vez de propagar es lo mismo que hacen los tres fallbacks del
    reescritor, y por el mismo motivo: la conversación no se cae porque falte un modelo
    auxiliar. Aquí sí es correcto tragarse el error —no es el patrón «fallback silencioso»
    que el proyecto prohíbe, porque no se degrada a otro modelo: se apaga el paso entero y
    se busca con lo que escribió el usuario, que es el comportamiento por defecto.
    """
    import logging

    from server.app.modules.agents_hub.services.config_provider import LocalConfigProvider
    from server.app.modules.agents_hub.services.model_factory import get_rewrite_model

    try:
        return await get_rewrite_model(
            cfg.chatbot_id,
            LocalConfigProvider(deps.session),
            rewrite_llm_config_id=getattr(cfg, "rewrite_llm_config_id", None),
        )
    except Exception as fallo:  # noqa: BLE001
        logging.getLogger(__name__).warning(
            "Reescritura no disponible para %s: %s", cfg.chatbot_id, fallo
        )
        return None


def build_agentic_loop_if_needed(cfg: Any, deps: Any):
    """AgenticLoop sólo en MD_AGENT_SELECTOR y sólo si hay LLM al que hacer bind_tools.

    Vive aquí, en el punto de integración, porque es una decisión de composición: el
    CoreGraph no debe conocer el retrieval_mode (RAG.2).
    """
    if cfg.retrieval_mode != "MD_AGENT_SELECTOR":
        return None

    from server.app.modules.agents_hub.agent.public_graphs.strategies.agentic_loop import (
        AgenticLoop,
    )
    from server.app.modules.agents_hub.services.retrieval.agentic_strategy import (
        AgenticRetrievalStrategy,
    )

    estrategia = AgenticRetrievalStrategy(deps.session)
    return AgenticLoop(
        reader=_ReaderDesdeEstrategia(estrategia),
        tools=estrategia.get_agent_tools(),
        searcher=_buscador_de_fragmentos(cfg, deps),
        relevance_scorer=_puntuador_de_relevancia(deps),
    )


def _puntuador_de_relevancia(deps: Any):
    """La nota real de un documento que el agente leyó, o None si no hay con qué medirla.

    HIB.E: la evidencia del agéntico salía con `score=1.0` fija, así que el quality gate del
    CoreGraph no podía rechazar nada con ningún umbral. Se puntúa con la **similitud coseno**
    entre la consulta y el fragmento más parecido del documento, que es la misma magnitud que
    HIB.J puso a leer al gate en la rama vectorial: si fueran escalas distintas, un umbral de
    0,50 significaría una cosa en el RAG y otra aquí, y la comparación entre los dos asistentes
    no querría decir nada.

    Se mide contra los FRAGMENTOS y no contra el documento entero porque el documento entero no
    tiene vector —el agéntico lee `markdown_content`, no fragmentos— y porque un artículo que
    contesta bien la consulta dentro de una ley de 279.425 tokens quedaría diluido en cualquier
    promedio del documento.
    """
    embedder = getattr(deps, "embedder", None)
    session = getattr(deps, "session", None)
    if embedder is None or session is None:
        return None

    async def puntua(query: str, document_id: str) -> float:
        import uuid as _uuid

        from sqlalchemy import select

        from server.app.modules.agents_hub.database.operational_models import (
            HubDocumentChunk,
        )
        from server.app.modules.agents_hub.services.embedding_service import PURPOSE_QUERY

        # `PURPOSE_QUERY` explícito aunque ya sea el defecto de `embed`: Vertex distingue
        # RETRIEVAL_QUERY de RETRIEVAL_DOCUMENT, y esta nota tiene que salir en la misma
        # escala que la del gate vectorial. Escrito, un cambio del defecto no la desplaza en
        # silencio respecto a `VectorRetrievalStrategy`, que embebe la consulta igual.
        vector = await embedder.embed(query, purpose=PURPOSE_QUERY)
        distancia = HubDocumentChunk.embedding.cosine_distance(vector)
        stmt = (
            select(distancia)
            .where(HubDocumentChunk.document_id == _uuid.UUID(document_id))
            .order_by(distancia)
            .limit(1)
        )
        mejor = (await session.execute(stmt)).scalar()
        if mejor is None:
            # Un documento sin fragmentos: el agéntico puede leerlo igual, pero no hay con qué
            # puntuarlo. Se propaga como no medible en vez de fabricar un 0, que lo rechazaría.
            raise ValueError(f"el documento {document_id} no tiene fragmentos que puntuar")
        return 1.0 - float(mejor)

    return puntua


def _buscador_de_fragmentos(cfg: Any, deps: Any):
    """Búsqueda vectorial para el `search_knowledge` del agente, o None si no hay embedder.

    Es lo que permite el híbrido que pide el corpus de Gerencia: el agente **lee entera** la
    normativa propia —la más larga son 51.032 tokens— y **busca fragmentos** en la externa,
    donde la Ley de Contratos sola son 279.425 y las 22 normas externas suman 1.745.337.

    Sin embedder no se monta y el tool se lo dice al modelo: un asistente sin embeddings
    sigue funcionando con índice y lectura, que es como funcionaba hasta ahora.
    """
    embedder = getattr(deps, "embedder", None)
    if embedder is None:
        return None

    from server.app.modules.agents_hub.services.retrieval.vector_strategy import (
        VectorRetrievalStrategy,
    )

    return _BuscadorVectorial(
        VectorRetrievalStrategy(
            session=deps.session,
            embedding_service=embedder,
            # RAG.15 — el mismo error que en `rag_vector_pipeline`: aquí iba
            # `min_retrieval_results`, que es el suelo del gate de calidad y no la anchura de la
            # recuperación. Arreglar sólo uno de los dos habría dejado este decidiendo cuántos
            # fragmentos lee otro perfil de grafo, y el síntoma sería el mismo sin la causa a la
            # vista. Lo vigila un test que recorre el árbol.
            top_k=getattr(cfg, "retrieval_top_k", None)
            or getattr(cfg, "min_retrieval_results", 5)
            or 5,
            # HIB.J — igual que en `rag_vector_pipeline`: `None` lo deriva la estrategia.
            candidate_k=getattr(cfg, "candidate_k", None),
        )
    )


class _BuscadorVectorial:
    """Adapta VectorRetrievalStrategy al protocolo FragmentSearcher del AgenticLoop."""

    def __init__(self, estrategia: Any) -> None:
        self._estrategia = estrategia

    async def search(self, query: str, chatbot_id: str, language: str | None = None) -> list:  # noqa: ARG002 — se recibe y no se usa, como en el pipeline RAG (ver docstring)
        """`language` se recibe y **no se usa**, igual que hace el pipeline RAG.

        Filtrar por él dejaba la búsqueda vacía siempre: los chunks del corpus llevan `val`
        y `es`, y el grafo resuelve la lengua de la conversación como `ca`. Ningún fragmento
        coincidía, así que el agente repetía `search_knowledge` hasta agotar las iteraciones
        y respondía en blanco. La búsqueda vectorial cruza idiomas por sí sola —los
        embeddings son multilingües— y la política de lengua actúa al redactar.
        """
        from server.app.modules.agents_hub.agent.public_graphs.strategies.rag_vector_pipeline import (
            _source_to_evidence,
        )

        contexto = await self._estrategia.get_context(
            query=query,
            chatbot_id=uuid.UUID(chatbot_id) if isinstance(chatbot_id, str) else chatbot_id,
        )
        return [_source_to_evidence(s) for s in contexto.sources]


class _ReaderDesdeEstrategia:
    """Adapta AgenticRetrievalStrategy al protocolo DocumentReader del AgenticLoop."""

    def __init__(self, estrategia: Any) -> None:
        self._estrategia = estrategia

    @property
    def last_index_level(self) -> str | None:
        """Escalón del último índice servido; el loop lo sella en la evidencia (VIS.2)."""
        return getattr(self._estrategia, "last_index_level", None)

    async def list_index(
        self,
        chatbot_id: str,
        language: str | None,
        submateries: list[str] | None = None,
    ) -> str:
        from server.app.modules.agents_hub.agent.tools.list_documents import list_documents

        return await list_documents(chatbot_id, self._estrategia, language, submateries)

    async def read(self, document_id: Any) -> dict | None:
        return await self._estrategia.read(document_id)


def _politica_de_lengua(cfg: Any):
    """La política que pide `cfg.language_mode` (LANG.1).

    Hasta aquí la factoría montaba **siempre** `DefaultLanguagePolicy`, mientras
    `language_mode` viajaba por toda la cascada —plataforma → organización → chatbot →
    configuración efectiva— sin que nadie lo consumiera. El mando existía y no estaba conectado
    a nada.

    Se resuelve **componiendo otra política**, no metiendo condicionales en el CoreGraph: los
    tres modos son el mismo grafo con una estrategia distinta, que es el argumento de
    «framework, no generador». Un despliegue monolingüe es configuración, no otro grafo.

    Un valor desconocido cae a la política de siempre en vez de reventar: el rechazo es trabajo
    del router (422 con los modos enumerados), y un chatbot que ya tuviera un valor raro en la
    columna `String(20)` libre debe seguir contestando como contestaba.
    """
    from server.app.core.language_mode import MODO_SIN_POLITICA, lengua_fijada
    from server.app.modules.agents_hub.agent.public_graphs.profiles.public_kb_rich import (
        DefaultLanguagePolicy,
    )
    from server.app.modules.agents_hub.agent.public_graphs.strategies.protocols import (
        FixedLanguagePolicy,
        NeutralLanguagePolicy,
    )

    modo = getattr(cfg, "language_mode", None)
    if modo == MODO_SIN_POLITICA:
        # `NeutralLanguagePolicy` ya existía con este comportamiento exacto —`detect` a `None`,
        # sin segunda búsqueda, passthrough, sin aviso— y no la usaba nadie. El plan pedía una
        # clase nueva; duplicarla serían dos cuerpos iguales que pueden divergir.
        return NeutralLanguagePolicy()
    lengua = lengua_fijada(modo)
    if lengua is not None:
        return FixedLanguagePolicy(lengua)
    return DefaultLanguagePolicy()


#: PLG.2 — la composición por defecto del perfil operativo, **por nombre**.
#:
#: Antes la factoría importaba las cuatro clases y las instanciaba. Ahora declara qué estrategia
#: quiere en cada eje y el registro la construye, que es lo que permite que una estrategia
#: aportada por un paquete instalado ocupe uno de estos ejes sin tocar este fichero. Las clases no
#: se han movido ni renombrado: lo que cambia es quién las instancia.
COMPOSICION_PUBLIC_KB_RICH: dict[str, str] = {
    "retrieval": "single_source",
    "merge": "passthrough",
    "template": "generic",
    "language": "default",
}


def _make_public_kb_rich(cfg: Any, deps: Any, llm: Any = None) -> CoreGraph:
    from server.app.modules.agents_hub.agent.public_graphs.strategies.registry import (
        ATRIBUTO_DE_EJE,
        EjeDeEstrategia,
        get_strategy,
    )

    composicion = dict(COMPOSICION_PUBLIC_KB_RICH)
    montadas = {
        ATRIBUTO_DE_EJE[EjeDeEstrategia(eje)]: get_strategy(eje, nombre)(cfg, deps, llm)
        for eje, nombre in composicion.items()
    }

    return CoreGraph(
        **montadas,
        cfg=cfg,
        deps=deps,
        llm=llm,
        agentic_loop=build_agentic_loop_if_needed(cfg, deps),
    )


#: Perfiles registrados como seleccionables cuya factoría **no está implementada**: se ofrecen
#: en la lista, pero no hay dónde declarar los chatbots de los que dependen. Sus factorías
#: lanzan `NotImplementedError` en vez de construir un grafo que recuperaría vacío en silencio
#: (hallazgo I5 de `docs/AUDITORIA_PRE_DEPLOY.md`).
#:
#: Es la fuente única de verdad de esa distinción: el contrato de perfiles
#: (`tests/public_graphs/test_profile_contract.py`) exige compilar y ejecutar a todo perfil que
#: NO esté aquí. Implementar uno se cierra sacándolo de este conjunto, y entonces el contrato
#: pasa a exigírselo.
#: Desde PLG.1 son cadenas: el enum se retiró porque un perfil aportado por un paquete instalado
#: no cabe en un enum del núcleo.
PERFILES_SIN_CONFIGURAR: frozenset[str] = frozenset(
    {
        "PUBLIC_PORTAL_AGGREGATOR",
        "PUBLIC_PORTAL_ROUTER",
    }
)

_SIN_CONFIGURAR = (
    "El perfil de grafo '{perfil}' está registrado pero **no está configurado**: {falta}. "
    "Tal como está, la recuperación no devolvería nada y el asistente respondería que no "
    "encuentra información, sin ningún error a la vista.\n"
    "Usa PUBLIC_KB_RICH, que es el perfil operativo, o implementa la configuración de este "
    "antes de seleccionarlo."
)


def _make_public_portal_aggregator(cfg: Any, deps: Any, llm: Any = None) -> CoreGraph:
    """Perfil sin configurar: agrega dos chatbots cuyos identificadores nadie fija.

    Hallazgo I5 de `docs/AUDITORIA_PRE_DEPLOY.md`. Estaba registrado como seleccionable con
    `uuid.UUID(int=0)` en los dos identificadores, así que la recuperación consultaba un
    chatbot inexistente y devolvía vacío **en silencio**: sin traza, sin log y con el corpus
    perfectamente cargado. Quien lo eligiera no tendría forma de averiguar por qué su
    asistente no encuentra nada.

    Falla en alto en vez de construirse. Implementarlo es una funcionalidad con su propio
    alcance —hacen falta campos de configuración para los dos chatbots de origen—; lo que no
    puede seguir es que se ofrezca como si funcionara.
    """
    raise NotImplementedError(
        _SIN_CONFIGURAR.format(
            perfil="PUBLIC_PORTAL_AGGREGATOR",
            falta=(
                "no hay dónde declarar de qué dos chatbots agrega (procedimientos y "
                "normativa)"
            ),
        )
    )


def _make_public_portal_router(cfg: Any, deps: Any, llm: Any = None) -> CoreGraph:
    """Perfil sin configurar: enruta a chatbots hijos que nadie declara.

    Mismo caso que el agregador de arriba: `child_chatbot_ids=[]` produce una lista de
    candidatos vacía y, con ella, una respuesta de «no encuentro información» indistinguible
    de un corpus mal cargado.
    """
    raise NotImplementedError(
        _SIN_CONFIGURAR.format(
            perfil="PUBLIC_PORTAL_ROUTER",
            falta="no hay dónde declarar la lista de chatbots hijos a los que enruta",
        )
    )


# PLG.1 — **aquí ya no se registra nada**, y es el punto entero del bloque.
#
# Hasta ahora, importar este módulo registraba los tres perfiles del núcleo por código. Desde
# PLG.1 el núcleo entra **por el mismo camino que un tercero**: los declara como *entry points*
# del grupo `govgenai.graph_profiles` en `server/pyproject.toml`, y los registra el cargador
# (`public_graphs/plugins.py`) al arrancar.
#
# El argumento no es de simetría. Con dos caminos, el motor puede acabar dependiendo de algo que
# sólo el registro por código proporciona —un orden, un objeto, un atajo— y **eso no se nota hasta
# que llega el primer tercero**, cuando ya está en el diseño. Con uno solo, el núcleo es el primer
# usuario de la API pública y cualquier carencia sale a la primera.
#
# Consecuencia práctica para quien lea un test rojo: si `list_profiles()` sale vacío, lo que falta
# es la llamada a `plugins.descubrir_todo()` — está en el *lifespan* de la app y en el `conftest`
# de la suite, y **no** se dispara al importar este módulo.
