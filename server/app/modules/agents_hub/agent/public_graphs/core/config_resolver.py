"""ConfigResolver: resuelve la configuración efectiva del grafo público.

Cascada: PlatformDefaults → OrgDefaults (HubOrganizacion) → ChatbotOverrides (HubChatbot).
Un campo None en el chatbot o el org indica "heredar del nivel superior".

Deploy: edge
"""
import uuid
from dataclasses import dataclass, field, replace
from typing import Any


@dataclass
class PublicGraphConfig:
    profile: str
    retrieval_mode: str
    language_mode: str
    quality_threshold: float
    # Cuántos resultados hacen falta para **no penalizar** la respuesta en el gate de calidad. Es
    # un suelo, no una anchura — ver `retrieval_top_k` más abajo, que es su pareja y con la que se
    # confundía: mezclarlos hacía que subir el mínimo ampliara la recuperación **y** a la vez
    # hiciera más probable el castigo, porque `len(items) >= min` sólo se cumplía recuperando
    # exactamente todos los que cabían.
    min_retrieval_results: int
    min_retrieval_score: float
    reranker_enabled: bool
    answer_template: str
    chatbot_id: uuid.UUID | None = None
    # PLG.2 — la composición EFECTIVA de estrategias, `{eje: nombre}`, con **los cuatro ejes
    # siempre presentes**. Que siempre estén los cuatro es deliberado: quien la lee —la factoría,
    # la traza, el panel— no tiene que saber de herencia ni tratar el caso «falta la clave». La
    # herencia se resuelve aquí y una sola vez.
    estrategias: dict[str, str] = field(default_factory=dict)
    # RAG.2: el system_prompt del chatbot entra por la cascada porque *es* configuración
    # efectiva del chatbot. Así la TemplateStrategy —única fuente del system prompt— lo
    # recibe por el mismo camino que el resto de la config, sin parámetros paralelos.
    system_prompt: str | None = None
    # UX.4: qué se contesta cuando no hay fundamento suficiente. `None` = el texto genérico
    # de `citation_validator`. Se configura por chatbot porque el destino al que se remite
    # depende de a quién sirve: Infocampus atiende al público, no al personal de gestión.
    no_answer_message: str | None = None
    # VIS.2: presupuesto de contexto para la inyección de documentos. Mismo argumento que
    # el system_prompt para entrar por aquí.
    #
    # El default de plataforma son 128.000 tokens porque el Nivel 2 inyecta documentos
    # ENTEROS (1-3 normas, ~25k).
    #
    # **Decidido por el usuario el 2026-07-31: 128.000 con carácter general.** El prompt de
    # RAG.5 pide un default de plataforma de 4.000 para su empaquetador de chunks; queda
    # anulado. Un mismo valor no puede significar dos cosas según quién lo lea, y bajarlo
    # aquí recortaría MD_LONG_CONTEXT a 4k, o sea lo dejaría inservible. RAG.5 consume este
    # presupuesto tal cual; si su packer necesita cortar antes, es una decisión del packer
    # con su propia constante, no un cambio de este default.
    context_token_budget: int = 128_000
    # VIS.2 (Nivel 0): índice de submaterias del vocabulario de la organización. Se resuelve
    # solo en MD_AGENT_SELECTOR —en RAG serían ~2.300 tokens de prompt que nadie usa— y
    # entra por la cascada porque depende de la organización del chatbot, igual que el resto.
    router_index: str | None = None
    # RAG.8: parámetros de troceado. Viven en la misma cascada que el resto porque son
    # configuración del chatbot, y el watcher los lee en vez de hardcodear los defaults.
    chunk_size: int = 1000
    chunk_overlap: int = 100
    chunking_strategy: str = "structural"
    # HIB.L — techo del padre en `parent_child`, en tokens. Medido: la mediana de los 10.614
    # padres del corpus son 205 tokens y sólo 24 pasan de 8.000, así que este número no
    # recorta el caso normal —acota una cola de preámbulos y artículos-ómnibus—. La sección
    # que no cabe deja al hijo sin padre; no se subdivide ni se trunca.
    #
    # Configurable por chatbot porque Gerencia puede querer subirlo: para una norma estatal
    # el contexto amplio es lo adecuado, y ése fue el argumento con el que el usuario aplazó
    # esta decisión el 2026-08-26.
    parent_max_tokens: int = 8000
    # RAG.10: reescritura de la consulta con el historial antes de recuperar. **False de
    # plataforma**, por el mismo motivo que `reranker_enabled` y `min_retrieval_score`:
    # cuesta una llamada al LLM por turno de seguimiento y su ganancia no se ha medido
    # todavía contra el corpus real. Se enciende por chatbot cuando el gate lo respalde.
    # HIB.Q — **True desde el 2026-08-27**, y el motivo es HIB.C: el widget envía ya los cinco
    # últimos intercambios, así que con el flag apagado un chatbot nuevo recibiría el historial
    # y no lo reescribiría. Llegaría la fontanería y no la función: el seguimiento no
    # funcionaría y no habría ningún error que lo delatara.
    #
    # Aquí y no en la columna del chatbot porque ésta SÍ es nullable, y en la cascada nulo
    # significa heredar. Un chatbot que lo quiera apagado lo pone en False y gana.
    query_rewriting_enabled: bool = True
    grounding_check_enabled: bool = False
    inject_whole_document: bool = False
    # LLM de reescritura, configurable en la organización porque es otro modelo —pequeño y
    # rápido— y no tiene sentido repetirlo en cada chatbot. None = usar el del chatbot con
    # el tope de salida bajado.
    rewrite_llm_config_id: uuid.UUID | None = None
    # RAG.15 — **cuántos fragmentos se recuperan**. No estaba en esta configuración: vivía en
    # `hub_chatbots.retrieval_top_k`, se podía editar desde el panel y **no llegaba hasta aquí**,
    # así que ningún pipeline podía leerlo y los dos que construían la recuperación usaban
    # `min_retrieval_results` en su lugar.
    #
    # Va en el bloque con valor por omisión y no junto a su pareja de arriba por una razón
    # prosaica: un campo obligatorio aquí rompe a todo el que construya la configuración a mano,
    # y hay unos cuantos dobles de test que sólo declaran lo que les interesa. El 8 es el mismo
    # que ya declaraba el modelo, así que nada cambia de valor — sólo empieza a leerse.
    retrieval_top_k: int = 3
    # HIB.J — cuántos FRAGMENTOS se le piden al híbrido, frente a `retrieval_top_k`, que son
    # los DOCUMENTOS que llegan al modelo. `None` = derivarlo de `retrieval_top_k` con
    # `pool_size()`, que es el comportamiento por omisión y el único que hay hoy configurado.
    #
    # Existe como mando propio porque hasta este prompt el pool dependía de si había
    # reranker: apagarlo lo encogía de 30 a 3 sin que nadie lo pidiera, y con ello `top_k`
    # dejaba de significar documentos. Un mando que se puede subir sin tocar el reranker es
    # lo que separa esos dos cambios para siempre.
    candidate_k: int | None = None


_PLATFORM_DEFAULTS = PublicGraphConfig(
    profile="PUBLIC_KB_RICH",
    retrieval_mode="RAG",
    language_mode="prefer",
    # HIB.R — 0,65 y no 0,60. Elegido sobre la curva de las dos columnas del lote de 48: es el
    # unico punto que declina dos negativos mas **sin perder ninguna respuesta buena**. Subir a
    # 0,70 caza cuatro pero cuesta el 7 %, y a 0,72 caza diez y cuesta el 17 %.
    #
    # Y es todo lo que este mando puede comprar barato: los cinco casos de contratacion que el
    # asistente contesta y no deberia puntuan 0,742-0,787 —por encima de casi cualquier
    # respuesta correcta—, asi que ningun umbral los alcanza. El resto del margen esta en
    # comprobar el fundamento de la cita, no aqui.
    quality_threshold=0.65,
    # HIB.S — APAGADA de entrada, a proposito. La comprobacion de fundamento cuesta una llamada
    # por respuesta y puede descartar respuestas buenas; se enciende cuando este medido cuantos
    # de los 11 negativos caza y cuantos de los 30 contestables rechaza indebidamente. Si pasa
    # de 2 de esos 30, no se despliega.
    grounding_check_enabled=False,
    # HIB.T — el artículo, no la norma entera. Los tres asistentes en producción siguen así; el
    # mando existe para el banco de comparación de Gerencia.
    inject_whole_document=False,
    # RAG.15 lo dejó en 8 diciendo que no estaba medido, porque nadie lo leía. HIB.Q lo baja a
    # **3**, que es el valor elegido con el lote delante: con `parent_child` y el pool ya
    # desacoplado del reranker (HIB.J), `top_k = 3` entrega de verdad tres documentos —2,96 de
    # media sobre las 25 consultas, y ninguna con uno solo— mientras que 8 serían ocho
    # documentos enteros.
    #
    # Va también en el defecto de la columna del chatbot: aquí sólo actúa si la fila trae
    # nulo, y esa columna es NOT NULL.
    retrieval_top_k=3,
    min_retrieval_results=2,
    # RAG.5: el umbral está implementado y probado, pero **desactivado por defecto**, y el
    # 0.0 es una decisión con medición detrás. Con el default anterior (0,25) el dataset
    # dorado caía de recall@5 0,960 a 0,720 y MRR 0,861 a 0,693.
    #
    # Ese 0,72 NO prueba que 0,25 sea mal umbral en producción: el corpus de fixture usa un
    # embedding determinista (bolsa de palabras por hash) cuyas similitudes coseno son
    # estructuralmente bajas —una consulta de 6 palabras contra un fragmento de 100 rara vez
    # pasa de 0,25 aunque sea el acierto correcto—, y BGE-M3 tiene otra distribución. Un
    # umbral ABSOLUTO es justo lo que ese corpus no puede calibrar.
    #
    # Así que ni se calibra contra la distribución equivocada ni se deja activo un filtro
    # que recorta un 24 % de recall en lo único medible: se deja el mecanismo listo y la
    # activación pendiente de medir con el corpus real cargado. Decidido con el usuario el
    # 2026-08-01. Lo vigila `test_should_not_lose_golden_hits_with_the_default_threshold`.
    min_retrieval_score=0.0,
    # RAG.6 / decisión del usuario (2026-08-01): **el mecanismo se construye, el interruptor
    # no se enciende**. Con el default en True, en cuanto exista la implementación el
    # reranker se activaría de golpe para todos los chatbots, y eso (a) acopla la
    # disponibilidad del chat a un segundo servicio —el prompt exige error explícito, no
    # fallback—, (b) añade latencia y coste por consulta y (c) no se ha medido que mejore.
    # Es exactamente lo que pasó con min_retrieval_score, activo por defecto y recortando 24
    # puntos de recall sin que nadie lo hubiera comprobado. Se activa por chatbot cuando el
    # gate de RAG.1 lo respalde.
    reranker_enabled=False,
    answer_template="generic",
    context_token_budget=128_000,
)


def _apply_layer(config: PublicGraphConfig, values: dict[str, Any]) -> PublicGraphConfig:
    """Devuelve un nuevo PublicGraphConfig con los campos no-None de values aplicados."""
    overrides = {k: v for k, v in values.items() if v is not None}
    return replace(config, **overrides) if overrides else config


async def get_effective_public_graph_config(
    chatbot_id: uuid.UUID,
    session: Any,
) -> PublicGraphConfig:
    """Resuelve la configuración efectiva del grafo público para un chatbot.

    Aplica cascada: plataforma → organización → chatbot.
    """
    from server.app.modules.agents_hub.database.config_models import HubChatbot, HubOrganizacion

    config = replace(_PLATFORM_DEFAULTS, chatbot_id=chatbot_id)

    chatbot = await session.get(HubChatbot, chatbot_id)
    if chatbot is None:
        return config

    organizacion = await session.get(HubOrganizacion, chatbot.organizacion_id)
    if organizacion is not None:
        config = _apply_layer(config, {
            "profile":               organizacion.default_public_graph_profile,
            "retrieval_mode":        organizacion.default_retrieval_mode,
            "language_mode":         organizacion.default_language_mode,
            "quality_threshold":     organizacion.default_quality_threshold,
            "min_retrieval_results": organizacion.default_min_retrieval_results,
            "min_retrieval_score":   organizacion.default_min_retrieval_score,
            "reranker_enabled":      organizacion.default_reranker_enabled,
            "answer_template":       organizacion.default_answer_template,
            "context_token_budget":  organizacion.default_context_token_budget,
            "chunk_size":            organizacion.default_chunk_size,
            "chunk_overlap":         organizacion.default_chunk_overlap,
            "chunking_strategy":     organizacion.default_chunking_strategy,
            "query_rewriting_enabled": organizacion.default_query_rewriting_enabled,
            "grounding_check_enabled": organizacion.default_grounding_check_enabled,
            "inject_whole_document": organizacion.default_inject_whole_document,
            "rewrite_llm_config_id": organizacion.rewrite_llm_config_id,
        })

    config = _apply_layer(config, {
        "profile":               chatbot.public_graph_profile,
        "retrieval_mode":        chatbot.retrieval_mode,
        "system_prompt":         chatbot.system_prompt,
        "no_answer_message":     chatbot.no_answer_message,
        "language_mode":         chatbot.language_mode,
        "quality_threshold":     chatbot.quality_threshold,
        # RAG.15 — la anchura del chatbot entra por fin en la configuración efectiva. No hay
        # capa de organización para ella porque `hub_organizaciones` no declara
        # `default_retrieval_top_k`: añadirla es una columna nueva y una decisión de producto que
        # este prompt no necesita, así que la cadena es chatbot → plataforma.
        "retrieval_top_k":       chatbot.retrieval_top_k,
        # HIB.J — misma cadena que `retrieval_top_k`: chatbot → plataforma, sin capa de
        # organización, porque `hub_organizaciones` tampoco declara un defecto para esto.
        "candidate_k":           chatbot.candidate_k,
        "min_retrieval_results": chatbot.min_retrieval_results,
        "min_retrieval_score":   chatbot.min_retrieval_score,
        "reranker_enabled":      chatbot.reranker_enabled,
        "answer_template":       chatbot.answer_template,
        "context_token_budget":  chatbot.context_token_budget,
        "chunk_size":            chatbot.chunk_size,
        "chunk_overlap":         chatbot.chunk_overlap,
        "chunking_strategy":     chatbot.chunking_strategy,
        "query_rewriting_enabled": chatbot.query_rewriting_enabled,
        "grounding_check_enabled": chatbot.grounding_check_enabled,
        "inject_whole_document": chatbot.inject_whole_document,
    })

    # PLG.2 — las estrategias se resuelven APARTE y clave a clave, no con `_apply_layer`.
    #
    # `_apply_layer` sustituye el valor entero cuando no es nulo, y aquí eso sería el error: una
    # organización que fija `{"merge": "..."}` borraría el `{"template": "..."}` del chatbot. La
    # herencia de este campo es **por clave**, y por eso no puede pasar por el mismo mecanismo.
    config = replace(
        config,
        estrategias=_resolver_estrategias(
            perfil=config.profile,
            de_organizacion=getattr(organizacion, "default_estrategias", None)
            if organizacion is not None
            else None,
            del_chatbot=chatbot.estrategias,
        ),
    )

    if config.retrieval_mode == "MD_AGENT_SELECTOR":
        config = replace(
            config,
            router_index=await _build_router_index(chatbot.organizacion_id, session),
        )

    return config


def _resolver_estrategias(
    perfil: str,  # noqa: ARG001 — hoy sólo un perfil declara composición y se parte siempre de la suya
    de_organizacion: dict[str, str] | None,
    del_chatbot: dict[str, str] | None,
) -> dict[str, str]:
    """Composición del perfil ← defectos de la organización ← estrategias del chatbot.

    **Fusión clave a clave**, y el resultado trae SIEMPRE los cuatro ejes. Nulo o clave ausente
    significan «hereda»; no hay forma de decir «este eje, ninguno», porque un `CoreGraph` con un
    eje vacío no se puede ejecutar.
    """
    from server.app.modules.agents_hub.agent.public_graphs.core.graph_factory import (
        COMPOSICION_PUBLIC_KB_RICH,
    )

    # Hoy sólo el perfil operativo declara composición; los otros dos lanzan
    # `NotImplementedError` al construirse, así que la suya no llega a usarse. Se parte de la de
    # `PUBLIC_KB_RICH` para que el campo tenga los cuatro ejes en cualquier caso — un perfil de
    # un paquete que no declare composición hereda una válida en vez de un diccionario vacío.
    resuelto = dict(COMPOSICION_PUBLIC_KB_RICH)
    for capa in (de_organizacion, del_chatbot):
        if capa:
            resuelto.update({k: v for k, v in capa.items() if v})
    return resuelto


async def _build_router_index(organizacion_id: uuid.UUID, session: Any) -> str | None:
    """Índice de submaterias del Nivel 0, vía ConfigProvider (nunca el ORM del vocabulario).

    Devuelve None si la organización no tiene vocabulario cargado: el system prompt se
    compone igual y el modo selector degrada al catálogo de documentos, que es el
    comportamiento previo a VIS.2. Un vocabulario vacío no es un error de configuración.
    """
    from server.app.modules.agents_hub.services.config_provider import LocalConfigProvider
    from server.app.modules.agents_hub.services.vocabulary_service import VocabularyService

    servicio = VocabularyService(LocalConfigProvider(session), organizacion_id)
    index = await servicio.build_router_index()
    return index or None
