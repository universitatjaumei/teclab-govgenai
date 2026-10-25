"""El turno de chat del Hub: preparar el grafo, transmitir la respuesta y guardarla (#274).

Vivía entero dentro de `api/v1/hub_chat.py:chat_stream`, 447 líneas con un generador anidado de
236, y era el endpoint más largo de `app/`. El endpoint conserva lo que es de HTTP —quién puede
preguntar, si el chatbot está abierto, el limitador y la cuota— y esto hace el resto: resolver
el embedding y el subagente, construir el grafo, traducir sus eventos a SSE y dejar la
interacción y su consumo guardados en el mismo commit.

El protocolo SSE está en el docstring de `api/v1/hub_chat.py`, que es donde lo busca quien
integra.

Deploy: edge
"""

import json
import logging
import uuid
from dataclasses import dataclass
from time import perf_counter
from typing import Any, AsyncIterator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.core.llm_text import texto_de
from server.app.core.quotas import contabilizar_interaccion
from server.app.modules.agents_hub.agent.public_graphs.core.graph_factory import GraphFactory
from server.app.modules.agents_hub.agent.public_graphs.strategies.retrieval_pipeline_protocol import (
    GraphDeps,
)
from server.app.modules.agents_hub.agent.router_node import build_route_to_subagent_node
from server.app.modules.agents_hub.database.config_models import HubChatbot
from server.app.modules.agents_hub.database.operational_models import HubInteraction
from server.app.modules.agents_hub.evaluation.traza import construye_traza
from server.app.modules.agents_hub.services.config_provider import LocalConfigProvider
from server.app.modules.agents_hub.services.embedding_resolver import (
    resolve_embedding_service,
)
from server.app.modules.agents_hub.services.embedding_space import (
    assert_embedding_space_matches,
)
from server.app.modules.agents_hub.services.model_factory import get_model
from server.app.modules.agents_hub.services.observability import create_callback_handler


class _ChatbotChildrenProvider:
    def __init__(self, db_session: AsyncSession):
        self._session = db_session

    async def get_children(self, parent_id: uuid.UUID):
        result = await self._session.execute(
            select(HubChatbot).where(HubChatbot.parent_chatbot_id == parent_id)
        )
        return list(result.scalars().all())

# Nodos del CoreGraph → mensaje de progreso. RAG.2 cambió los nombres internos de los
# nodos (search_or_skip → retrieve, generate_response → generate_answer) pero NO el
# contrato SSE observable: los tres mensajes que ve el usuario son los mismos, y los nodos
# internos que no tenían mensaje (merge, log, fallback) siguen sin emitir status.
NODE_STATUS_MESSAGES: dict[str, str] = {
    "detect_language":  "Detectando idioma...",
    "retrieve":         "Buscando en la base de conocimiento...",
    "generate_answer":  "Generando respuesta...",
}

#: USR.8 — un fallo después del grafo se le dice al cliente **y** se deja en el log. Sin la
#: traza, «el chat se queda pensando» no se puede diagnosticar: el evento `error` lleva el
#: mensaje, pero no dónde pasó.
logger = logging.getLogger(__name__)

# Nodo del CoreGraph cuyo on_chain_end trae el estado final del que salen las fuentes.
_FINAL_NODES = ("generate_answer", "fallback")


#: Lo único que el cliente recibe cuando el turno falla (issue #147).
#:
#: Antes iba `str(exc)`, y el widget del chatbot es **público**: cualquiera podía provocar un
#: error y leer el mensaje de una excepción de base de datos, una ruta del contenedor o la
#: respuesta cruda del proveedor de modelo. El cliente tiene que saber que hubo un error; cuál,
#: no. El detalle va al registro, que es donde lo necesita quien lo arregla.
#:
#: Es texto fijo a propósito y no un mensaje por chatbot: éste no es el «no tengo información»
#: de UX.4 —que sí es del chatbot y va en su lengua— sino una avería del servicio. Si algún día
#: hay que traducirlo, el sitio es el cliente, que ya sabe en qué lengua está.
MENSAJE_DE_ERROR = "S'ha produït un error en processar la consulta."


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _uso_del_evento(event: dict) -> tuple[int, int]:
    """Tokens de entrada y salida que declara el proveedor, o `(0, 0)`.

    LangChain los expone en `usage_metadata` desde la versión unificada y, en modelos más
    antiguos, dentro de `response_metadata['token_usage']`. Se miran los dos sitios porque el
    proveedor se elige por configuración y no se puede saber aquí cuál responderá.
    """
    salida = (event.get("data") or {}).get("output")
    if salida is None:
        return 0, 0

    uso = getattr(salida, "usage_metadata", None)
    if isinstance(uso, dict) and (uso.get("input_tokens") or uso.get("output_tokens")):
        return int(uso.get("input_tokens") or 0), int(uso.get("output_tokens") or 0)

    metadatos = getattr(salida, "response_metadata", None) or {}
    crudo = metadatos.get("token_usage") or metadatos.get("usage") or {}
    if isinstance(crudo, dict):
        return (
            int(crudo.get("prompt_tokens") or crudo.get("input_tokens") or 0),
            int(crudo.get("completion_tokens") or crudo.get("output_tokens") or 0),
        )
    return 0, 0


def _tokens_estimados(texto: str) -> int:
    """Estimación por longitud cuando el proveedor no declara nada.

    Cuatro caracteres por token: la regla de servilleta habitual para texto latino. No
    pretende ser exacta —por eso lo que se guarda junto al número es `usage_source
    = 'estimated'`—, solo evitar que una cuota se quede a cero porque el proveedor calle.
    """
    return max(1, len(texto or "") // 4) if texto else 0


#: Cómo se llama cada lengua **en la lengua de quien lee el aviso** (VIS.5).
#:
#: Tres tablas y no una: el aviso se le muestra a quien acaba de escribir en su lengua, así que
#: decirle «catalan» en castellano —y encima sin tilde— convierte una advertencia útil en una
#: impertinencia. La lengua de la fuente se nombra dentro de la frase, luego hay que declinarla
#: en cada idioma.
# ACT.2: la clave del valenciano es `val`, la del CORPUS, y `ca` ya no aparece. La versión
# anterior estaba escrita en `ca` en las dos direcciones, así que:
#   · como lengua de la FUENTE nunca acertaba —los documentos llevan `val`— y el nombre salía con
#     el código crudo: «⚠️ La normativa citada está en val»;
#   · como lengua de la PREGUNTA tampoco, en cuanto el detector pasó a normalizar.
# Dos claves para la misma lengua es lo que estaba roto; no se duplican, se traduce en la
# frontera (`services/language_detector.py`).
_NOMBRE_DE_LA_LENGUA: dict[str, dict[str, str]] = {
    "val": {"val": "valencià", "es": "castellà", "en": "anglès", "fr": "francès"},
    "es": {"val": "valenciano", "es": "castellano", "en": "inglés", "fr": "francés"},
    "en": {"val": "Valencian", "es": "Spanish", "en": "English", "fr": "French"},
}

# Issue #17 — el aviso dice además QUÉ SE ESTÁ LEYENDO, no sólo adónde lleva el enlace.
#
# **Al corpus sólo entran originales**: no se sube ni una traducción. Así que cuando la norma que
# responde a la pregunta sólo existe en la otra lengua, lo que lee quien pregunta no es la norma:
# es una traducción que el modelo acaba de hacer, que nadie ha revisado y que no está publicada en
# ningún sitio. «La normativa citada está en castellano» no dice eso, y era todo lo que decía.
#
# Va aquí y no en el aviso permanente de `chat.json` —que ya advierte de que las respuestas no han
# pasado revisión lingüística— porque es **condicional**: un aviso que sale siempre se aprende a
# ignorar, y en las normas que sólo existen en valencià, preguntadas en valencià, no hay ninguna
# traducción de la que avisar. Afirmarlo sería falso.
_PLANTILLA_DEL_AVISO: dict[str, str] = {
    "val": (
        "⚠️ La normativa citada està en {lengua}. La resposta s'ha generat de manera "
        "automatitzada a partir de l'original, sense revisió humana de la traducció. "
        "L'enllaç porta al document original."
    ),
    "es": (
        "⚠️ La normativa citada está en {lengua}. La respuesta se ha generado de forma "
        "automatizada a partir del original, sin revisión humana de la traducción. "
        "El enlace lleva al documento original."
    ),
    "en": (
        "⚠️ The cited regulation is in {lengua}. This answer was generated automatically "
        "from the original, with no human review of the translation. "
        "The link opens the original document."
    ),
}


def _build_translation_warning(
    lengua_de_la_fuente: str | None, lengua_de_la_pregunta: str | None
) -> str | None:
    """El aviso de que la norma citada está en otra lengua (VIS.5).

    **Sale de la lengua de la FUENTE, no de la de la pregunta.** Antes decía «la pregunta se
    detectó en catalán», que no es información: quien ha escrito en valencià ya sabe en qué
    lengua escribe. Lo que necesita saber es que el enlace le lleva a un documento en castellano.

    Y **se emite en las dos direcciones**. La versión anterior devolvía `None` cuando la pregunta
    era en castellano, que es justo el caso más frecuente de este corpus —195 de 290 normas sólo
    existen en valencià—: el grafo decidía que había que avisar y el texto se descartaba después.

    Sin una de las dos lenguas no se avisa: no se puede afirmar que difieran, y un aviso falso
    sobre el idioma de una norma erosiona la confianza en los que sí son ciertos.
    """
    if not lengua_de_la_fuente or not lengua_de_la_pregunta:
        return None
    if lengua_de_la_fuente == lengua_de_la_pregunta:
        return None

    plantilla = _PLANTILLA_DEL_AVISO.get(lengua_de_la_pregunta, _PLANTILLA_DEL_AVISO["es"])
    nombres = _NOMBRE_DE_LA_LENGUA.get(lengua_de_la_pregunta, _NOMBRE_DE_LA_LENGUA["es"])
    return plantilla.format(lengua=nombres.get(lengua_de_la_fuente, lengua_de_la_fuente))


def _es_citable(source) -> bool:
    """Sólo van al done las evidencias con URL: sin URL no hay cita verificable.

    En modo selector eso descarta además las entradas de índice, que llegan sin haber
    sido leídas.
    """
    if getattr(source, "metadata", None) and source.metadata.get("index_entry"):
        return False
    return bool(getattr(source, "source_url", None) or getattr(source, "url", None))


def _source_to_dict(source) -> dict:
    """Serializa una evidencia al shape del evento done.

    RAG.2 unificó el contrato interno en EvidenceItem (source_id / source_url), pero el
    shape JSON que ve el frontend **no cambia**: document_id, title, url, score. Se acepta
    también el dialecto `Source` (document_id/url) porque los tools y las estrategias de
    `services/retrieval/` siguen hablándolo por debajo de los pipelines.
    """
    from server.app.modules.agents_hub.services.retrieval.citations import (
        etiqueta_de_autoridad,
    )

    document_id = getattr(source, "source_id", None) or getattr(source, "document_id", None)
    url = getattr(source, "source_url", None) or getattr(source, "url", None)
    score = getattr(source, "score", None)
    metadata = getattr(source, "metadata", None) or {}

    salida = {
        "document_id": str(document_id),
        "title": source.title,
        "url": url,
        "score": round(score, 3) if score is not None else None,
    }

    # FAQ.2: la autoridad del texto sale en el JSON para que el frontend pueda pintarla
    # distinta. `None` cuando es normativa, así que el shape de CAL.2 no cambia para lo que
    # ya había: se añaden claves, no se alteran las existentes.
    autoridad = etiqueta_de_autoridad(metadata)
    if autoridad:
        salida["authority"] = autoridad
        respaldo = metadata.get("norma_de_respaldo")
        if respaldo:
            salida["backing_url"] = respaldo

    return salida


class RutaNoResuelta(ValueError):
    """El chatbot enrutador no supo a qué subagente mandar la pregunta."""


class SubagenteNoEncontrado(LookupError):
    """El enrutador eligió un subagente que ya no existe."""


@dataclass
class TurnoPreparado:
    """Lo que hace falta para responder, resuelto antes de abrir el flujo SSE.

    `chatbot` es **el que responde**: el subagente cuando el chatbot pedido es un enrutador. Es
    el que se contabiliza, igual que antes de separar esto del endpoint.
    """

    chatbot: Any
    chatbot_id: uuid.UUID
    grafo: Any
    compilado: Any
    estado_inicial: dict
    aviso_de_ruta: str | None


async def preparar_turno(
    session: AsyncSession,
    chatbot: Any,
    *,
    mensaje: str,
    historial: list[tuple[str, str]],
    debug_bypass: bool,
) -> TurnoPreparado:
    """Resuelve embedding, subagente y grafo. Lanza antes de que salga ningún evento.

    `EmbeddingSpaceMismatch` si el corpus está embebido con otro modelo (RAG.9),
    `RutaNoResuelta` si el enrutador no decide, y `SubagenteNoEncontrado` si decide uno que no
    está. El endpoint las traduce a 409, 400 y 404.
    """
    chatbot_id = chatbot.id
    embedding_service = await resolve_embedding_service(session, chatbot_id)

    # RAG.9: parar antes que responder mal. Si el corpus está embebido con otro modelo, la
    # búsqueda vectorial devuelve las fuentes más parecidas *en un espacio que no es el
    # suyo*: normas que no vienen a cuento sosteniendo una respuesta que suena razonable.
    # No hay error que ver, y en un asistente normativo esa es la avería cara.
    await assert_embedding_space_matches(session, chatbot_id, embedding_service)

    config_provider = LocalConfigProvider(session)

    router_status_message: str | None = None
    selected_chatbot_id = chatbot_id
    if getattr(chatbot, "kind", "atomic") == "router":
        router_llm = await get_model(chatbot.id, config_provider)
        router_node = build_route_to_subagent_node(
            embedding_service=embedding_service,
            chatbot_provider=_ChatbotChildrenProvider(session),
            llm_fallback=router_llm,
        )
        try:
            routing = await router_node(
                {
                    "messages": [type("M", (), {"content": mensaje})()],
                    "chatbot_id": str(chatbot.id),
                }
            )
        except ValueError as exc:
            raise RutaNoResuelta(str(exc)) from exc

        selected_chatbot_id = uuid.UUID(str(routing["selected_child_id"]))
        child_result = await session.execute(
            select(HubChatbot).where(HubChatbot.id == selected_chatbot_id)
        )
        child_chatbot = child_result.scalar_one_or_none()
        if child_chatbot is None:
            raise SubagenteNoEncontrado(f"Child chatbot {selected_chatbot_id} not found")
        chatbot = child_chatbot
        router_status_message = f"Materia detectada: {chatbot.name}"

    llm = await get_model(selected_chatbot_id, config_provider)

    # El grafo lo construye la GraphFactory: resuelve la cascada de config
    # (Plataforma → Organización → Chatbot) y selecciona el perfil y el pipeline de
    # retrieval a partir de cfg.retrieval_mode. El endpoint ya no elige estrategia.
    deps = GraphDeps(session=session, embedder=embedding_service, llm=llm)
    core_graph = await GraphFactory().build(selected_chatbot_id, deps, llm)
    compiled = core_graph.compile()

    initial_state = {
        "query": mensaje,
        "chatbot_id": str(selected_chatbot_id),
        "language": None,
        # RAG.10: los turnos previos, ya aplanados a 'rol: texto', que es lo que consume el
        # reescritor. El grafo no necesita objetos de mensaje para esto.
        "history": [f"{rol}: {texto}" for rol, texto in historial],
        "rewritten_query": None,
        "debug_bypass": debug_bypass,
        "bypass": None,
        "retrieval_output": None,
        "merged_items": [],
        "answer": None,
        "quality_score": 0.0,
        "quality_source": None,
        "fallback_used": False,
        "translation_warning": False,
        "reformulated_query": None,
        "reformulada": False,
        "fallback_reason": None,
        "sources": [],
    }


    return TurnoPreparado(
        chatbot=chatbot,
        chatbot_id=selected_chatbot_id,
        grafo=core_graph,
        compilado=compiled,
        estado_inicial=initial_state,
        aviso_de_ruta=router_status_message,
    )


async def inspeccionar(turno: TurnoPreparado) -> dict:
    """El prompt final sin invocar al modelo (RAG.11). No se guarda: es inspección."""
    estado = await turno.compilado.ainvoke(turno.estado_inicial)
    return estado.get("bypass") or {}


async def emitir_turno(
    turno: TurnoPreparado,
    *,
    session: AsyncSession,
    actor: Any,
    mensaje: str,
    numero_de_turno: int,
    ip: str | None,
) -> AsyncIterator[str]:
    """Los eventos SSE del turno, y la interacción guardada con su consumo al final."""
    interaction_id = uuid.uuid4()

    # `user` es `None` en el widget público (SEC.8.5): ahí no hay sesión, solo la
    # credencial de sitio. `actor.subject_id` es lo único identificativo que existe en
    # ese caso -- ya es lo que usa `HubInteraction.user_id` más abajo -- así que es
    # también lo que debe viajar a Langfuse.
    langfuse_handler = create_callback_handler(
        session_id=str(interaction_id), user_id=actor.subject_id
    )
    stream_config = (
        {
            "callbacks": [langfuse_handler],
            "metadata": {
                "langfuse_session_id": str(interaction_id),
                "langfuse_user_id": actor.subject_id,
            },
        }
        if langfuse_handler
        else {}
    )

    uso = {"prompt": 0, "completion": 0, "source": "estimated"}
    # HIB.I — el reloj arranca aquí, antes del primer evento del grafo: la latencia que
    # importa es la que espera quien pregunta, no la del nodo más lento.
    inicio = perf_counter()
    primer_token_ms: int | None = None
    collected_tokens: list[str] = []
    final_sources: list = []
    language_fallback = False
    detected_language = "es"
    # VIS.5 — `None` hasta que el grafo diga en qué lengua está la evidencia. Sin ella no se
    # avisa: no se puede afirmar que difiera de la de la pregunta.
    lengua_de_la_fuente: str | None = None
    # RES.2 — si la respuesta salió de la segunda pasada. Falso mientras nadie lo diga: el
    # nodo `reformular` sólo se ejecuta cuando la primera pasada no llegó al umbral.
    reformulada = False
    fallback_reason: str | None = None
    fallback_answer: str | None = None
    # HIB.I — lo que la traza necesita y hasta ahora no salía de este generador.
    best_score: float | None = None
    gate_passed: bool | None = None
    consulta_reescrita: str | None = None

    try:
        if turno.aviso_de_ruta:
            yield _sse(
                "status",
                {"node": "route_to_subagent", "msg": turno.aviso_de_ruta},
            )

        async for event in turno.compilado.astream_events(turno.estado_inicial, stream_config, version="v2"):
            kind = event["event"]
            name = event.get("name", "")

            if kind == "on_chain_start" and name in NODE_STATUS_MESSAGES:
                yield _sse("status", {"node": name, "msg": NODE_STATUS_MESSAGES[name]})

            elif kind == "on_chat_model_stream":
                # HIB.B — sólo los tokens de los nodos que producen LA RESPUESTA.
                #
                # Antes se emitía cualquier llamada al modelo, y en el grafo hay tres que
                # no son la respuesta: `rewrite_query` (RAG.10), `reformular` (RES.2) y,
                # en el modo agéntico, el selector que corre dentro de `retrieve`. Quien
                # preguntaba veía la consulta reformulada como si fuera la contestación.
                #
                # La lista se DERIVA de `_FINAL_NODES`, que ya es la fuente de verdad de
                # qué nodos producen la respuesta y que el manejador del estado final ya
                # usa: quien añada un nodo generador tiene que declararlo ahí de todos
                # modos. Una lista propia aquí divergiría en el primer cambio.
                nodo = (event.get("metadata") or {}).get("langgraph_node")
                if nodo is not None and nodo not in _FINAL_NODES:
                    continue
                chunk = event.get("data", {}).get("chunk")
                if chunk is not None:
                    # USR.8 — `texto_de` y no `chunk.content` a pelo. Gemini devuelve el
                    # contenido como **lista de bloques** en cuanto la respuesta tiene más
                    # de una parte, y entonces esto guardaba una lista en
                    # `collected_tokens`: el `"".join(...)` de ochenta líneas más abajo
                    # levantaba `TypeError`, y con él se caían el `done`, la interacción y
                    # la contabilidad de la cuota. Medido el 2026-09-03: el asistente
                    # agéntico tenía **0 interacciones** guardadas y 33 el de RAG.
                    #
                    # Es la tercera vez que muerde el mismo problema, y el docstring de
                    # `core/llm_text.py` ya lo decía: quien asume `str` no falla al
                    # recibirlo, falla más tarde y en otro sitio.
                    delta = texto_de(chunk)
                    if delta:
                        if primer_token_ms is None:
                            primer_token_ms = int((perf_counter() - inicio) * 1000)
                        collected_tokens.append(delta)
                        yield _sse("token", {"delta": delta})

            elif kind == "on_chain_end" and name in _FINAL_NODES:
                output = event.get("data", {}).get("output") or {}
                raw_sources = output.get("sources", [])
                final_sources = [
                    _source_to_dict(s) for s in raw_sources if _es_citable(s)
                ]
                fallback_reason = output.get("fallback_reason")
                if output.get("fallback_used"):
                    fallback_answer = output.get("answer")
                # HIB.I — la nota y la decisión de la puerta, tal como quedaron. Se leen
                # del nodo final porque es el único punto donde ya están las dos.
                nota_final = output.get("quality_score")
                if nota_final is not None:
                    best_score = nota_final
                    gate_passed = nota_final >= getattr(
                        turno.grafo.cfg, "quality_threshold", 0.0
                    )
                consulta_reescrita = output.get("rewritten_query") or consulta_reescrita

            elif kind == "on_chain_end" and name == "detect_language":
                output = event.get("data", {}).get("output") or {}
                detected_language = output.get("language") or "es"

            elif kind == "on_chain_end" and name == "merge":
                output = event.get("data", {}).get("output") or {}
                language_fallback = bool(output.get("translation_warning"))
                # VIS.5 — la lengua de la fuente, que es con la que se redacta el aviso.
                lengua_de_la_fuente = output.get("context_source_language")

            elif kind == "on_chain_end" and name == "reformular":
                # RES.2 — el hecho viaja, el texto de producto no se decide aquí. Una
                # respuesta rescatada reformulando no se revisa igual que una directa.
                output = event.get("data", {}).get("output") or {}
                reformulada = bool(output.get("reformulada"))

            elif kind == "on_chat_model_end":
                # SEC.4: el uso real, tal como lo declara el proveedor. Se acumula en
                # vez de asignarse porque un turno puede invocar al modelo más de una
                # vez —reescritura de consulta, selector de agente—, y todo eso lo paga
                # la misma persona.
                entrada, salida = _uso_del_evento(event)
                if entrada or salida:
                    uso["prompt"] += entrada
                    uso["completion"] += salida
                    uso["source"] = "provider"

    except Exception:
        # Issue #147: el detalle va al registro, no al cliente. Este manejador ni siquiera
        # registraba, así que el único que no se enteraba de qué había fallado era quien
        # tenía que arreglarlo.
        logger.exception("El turno de chat falló durante el grafo; el cliente recibe `error`.")
        yield _sse("error", {"message": MENSAJE_DE_ERROR})
        return

    # USR.8 — **todo esto va dentro de su propio `try`**, y no es simetría: guardar la
    # interacción, la traza, la cuota, el commit y el propio `done` estaban fuera de
    # cualquier protección. Un fallo aquí no producía ni un evento de error, así que el
    # cliente se quedaba esperando sin poder distinguirlo de una respuesta lenta — que
    # es exactamente lo que pasó con el `TypeError` del contenido en bloques.
    #
    # Se emite `error` y **no** un `done` con datos inventados: si la interacción no se
    # guardó, decir que sí dejaría al cliente con un `interaction_id` que no existe y
    # una valoración que no se puede anclar a nada.
    try:
        # El fallback y el mensaje del validador de citas no pasan por el stream de tokens
        # del LLM, así que hay que emitirlos aquí para que el usuario vea una respuesta.
        #
        # HIB.B — se emite SIEMPRE que haya rendición, no sólo cuando no llegó nada. La
        # condición `and not collected_tokens` era el segundo defecto: el contrato de citas
        # corre *dentro* de `generate_answer`, después de generar, así que cuando rechaza los
        # tokens ya han salido — y entonces el mensaje de rendición no se mostraba nunca y el
        # usuario se quedaba con la respuesta que el contrato acababa de descartar.
        #
        # Por SSE no se retira lo ya enviado, así que se le dice al cliente que lo descarte.
        # La alternativa —retener los tokens hasta validar— costaría el streaming en todas
        # las respuestas: medido en HIB.I, el primer token pasaría de 780 ms a 2.140 ms, y el
        # contrato rechaza en torno al 4 % de las consultas. Decisión del usuario, 2026-08-26.
        if fallback_answer:
            if collected_tokens:
                yield _sse("discard", {"reason": fallback_reason or "fallback"})
                collected_tokens.clear()
            collected_tokens.append(fallback_answer)
            yield _sse("token", {"delta": fallback_answer})

        # HIB.B — lo que se guarda es lo que el usuario vio. Antes guardaba la reformulación,
        # así que quien revisaba juzgaba una respuesta que nadie recibió.
        assistant_message = "".join(collected_tokens)

        # SEC.4: si el proveedor no declaró uso, se estima por longitud y **se marca**. Una
        # cuota apoyada en una estimación silenciosa no se puede defender ante quien la
        # sufre; con la marca, al menos se sabe qué número se está discutiendo.
        if uso["source"] == "estimated":
            uso["prompt"] = _tokens_estimados(mensaje)
            uso["completion"] = _tokens_estimados(assistant_message)

        total_tokens = uso["prompt"] + uso["completion"]
        interaction = HubInteraction(
            id=interaction_id,
            chatbot_id=turno.chatbot_id,
            user_id=actor.subject_id,
            user_message=mensaje,
            assistant_message=assistant_message,
            run_id=interaction_id,
            fallback_reason=fallback_reason,
            prompt_tokens=uso["prompt"] or None,
            completion_tokens=uso["completion"] or None,
            # HIB.I — la traza de diagnóstico. Con el piloto en marcha ya es tarde para los
            # datos que no se guardaron: sin los identificadores y las puntuaciones de lo
            # recuperado no se puede saber, meses después, si una respuesta mala fue de
            # recuperación o de redacción, ni re-ejecutar una ablación sobre las mismas
            # consultas sin volver a pedir trabajo a los informadores.
            interaction_metadata=construye_traza(
                cfg=turno.grafo.cfg,
                fuentes=final_sources,
                usage_source=uso["source"],
                best_score=best_score,
                gate_passed=gate_passed,
                language=detected_language,
                source_language=lengua_de_la_fuente,
                translation_warning=language_fallback,
                # El turno que se está respondiendo, contando desde 1. Es lo que permite
                # separar «falla la primera pregunta» de «falla el seguimiento», que es
                # justo la distinción que HIB.C viene a arreglar.
                turn_index=numero_de_turno,
                rewritten_query=consulta_reescrita,
                reformulada=reformulada,
                latency_ms=int((perf_counter() - inicio) * 1000),
                first_token_ms=primer_token_ms,
            ),
        )
        session.add(interaction)
        # El consumo va en el MISMO commit que la interacción, no en un segundo write: si
        # se separaran, un fallo entre los dos dejaría respuestas servidas sin contabilizar
        # —o al revés— y la cuota dejaría de cuadrar con lo que el usuario ha recibido.
        await contabilizar_interaccion(
            session,
            actor,
            turno.chatbot,
            total_tokens,
            ip=ip,
        )
        await session.commit()

        translation_warning = (
            _build_translation_warning(lengua_de_la_fuente, detected_language)
            if language_fallback
            else None
        )
        yield _sse(
            "done",
            {
                "interaction_id": str(interaction_id),
                "sources": final_sources,
                "language_fallback": language_fallback,
                "translation_warning": translation_warning,
                "reformulada": reformulada,
            },
        )
    except Exception:
        logger.exception(
            "El turno de chat falló después del grafo; el cliente recibe `error`."
        )
        yield _sse("error", {"message": MENSAJE_DE_ERROR})
        return

