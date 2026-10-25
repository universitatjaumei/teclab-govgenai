"""CoreGraph — orquestación común de grafos públicos.

Flujo: detect_language → retrieve → merge → quality_gate
         → generate_answer → log → END
         → fallback → END

No contiene lógica específica de dominio ni de retrieval_mode.
Todas las decisiones de dominio están encapsuladas en las estrategias inyectadas.

Deploy: edge
"""
from __future__ import annotations

import uuid
from typing import Any, cast, Literal, TYPE_CHECKING

from typing_extensions import TypedDict

from langgraph.graph import END, StateGraph

from server.app.modules.agents_hub.agent.public_graphs.strategies.protocols import (
    LanguagePolicy,
    MergeStrategy,
    RetrievalOutput,
    RetrievalStrategy,
    TemplateStrategy,
)
from server.app.modules.agents_hub.agent.citation_validator import (
    NO_CITATION_FALLBACK,
    enforce_citation_contract,
)
from server.app.modules.agents_hub.agent.public_graphs.strategies.retrieval_contract import (
    EvidenceItem,
)
from server.app.modules.agents_hub.agent.grounding_check import (
    fuente_desde_evidencia,
    hay_fundamento,
    juez_de_modelo,
)
from server.app.modules.agents_hub.agent.public_graphs.core.query_rewriter import (
    necesita_reescritura,
    reescribir_consulta,
    reformular_al_vocabulario_normativo,
)
from server.app.modules.agents_hub.services.retrieval.vigencia import (
    aviso_para as aviso_de_vigencia,
)
from server.app.core.llm_text import texto_de

if TYPE_CHECKING:
    from server.app.modules.agents_hub.agent.public_graphs.strategies.agentic_loop import (
        AgenticLoop,
    )
    from server.app.modules.agents_hub.agent.public_graphs.core.config_resolver import (
        PublicGraphConfig,
    )
    from server.app.modules.agents_hub.agent.public_graphs.strategies.retrieval_pipeline_protocol import (
        GraphDeps,
    )


class CoreGraphState(TypedDict):
    """Estado interno del CoreGraph."""

    query: str
    chatbot_id: str
    language: str | None
    # RAG.10: turnos previos, ya formateados como 'rol: texto'. Los manda el cliente: la API
    # es sin estado y no hay entidad conversación.
    history: list                  # list[str]
    # La consulta autónoma con la que se BUSCA, cuando la reescritura está encendida y sale
    # bien. None significa «se buscó con lo que escribió el usuario» — y hay que poder
    # distinguirlo, porque es lo que se lee en la traza y en el bypass de RAG.11.
    rewritten_query: str | None
    grounding: dict | None
    # RES.2 — la consulta escrita como la escribiría la norma, cuando la primera pasada no llegó
    # al umbral. Es también la guarda contra bucles: si está puesta, se viene de la segunda
    # pasada y no hay tercera. Tampoco llega a la generación, por lo mismo que la reescritura.
    reformulated_query: str | None
    # Si la respuesta salió de esa segunda pasada. Va en el contrato porque una respuesta
    # rescatada reformulando no se revisa igual que una directa.
    reformulada: bool
    # RAG.11: ejecutar todo el pipeline y pararse ANTES de invocar al modelo.
    debug_bypass: bool
    # RAG.13: compone la MISMA instantánea pero **sin** detener el grafo. Es lo que permite
    # que un escenario guarde a la vez la respuesta y el contexto con el que se produjo,
    # sin recomponerlo desde fuera —recomponerlo daría un contexto parecido, no el mismo—.
    capture_context: bool
    bypass: dict | None            # lo que se envió (o se iba a enviar, si debug_bypass)
    retrieval_output: Any          # RetrievalOutput | None
    merged_items: list             # list[EvidenceItem]
    answer: str | None
    quality_score: float
    # RES.1 — qué fragmento fijó la nota. Con la media no había nada que señalar; con el mejor
    # fragmento sí, y sin este dato depurar una respuesta rechazada pasa de leer un número a
    # reproducir la consulta contra el corpus real.
    quality_source: dict | None
    fallback_used: bool
    translation_warning: bool
    # VIS.5 — en qué lengua está la evidencia que se ha citado. Viaja junto al aviso porque el
    # texto que ve el usuario se redacta con ella: sin este dato, el chat sólo sabía «hay que
    # avisar» y acababa hablando de la lengua de la pregunta.
    context_source_language: str | None
    fallback_reason: str | None     # 'quality_gate' | 'citation' | None (RAG.2)
    sources: list                  # list[EvidenceItem] citables emitidas en el done SSE


class CoreGraph:
    """Orquestador común para todos los grafos públicos.

    Acepta estrategias intercambiables y ejecuta el flujo canónico sin
    conocer el retrieval_mode ni la lógica de dominio del chatbot.
    """

    def __init__(
        self,
        retrieval_strategy: RetrievalStrategy,
        merge_strategy: MergeStrategy,
        template_strategy: TemplateStrategy,
        language_policy: LanguagePolicy,
        cfg: "PublicGraphConfig",
        deps: "GraphDeps",
        llm: Any = None,
        agentic_loop: "AgenticLoop | None" = None,
        rewrite_llm: Any = None,
    ) -> None:
        self.retrieval_strategy = retrieval_strategy
        self.merge_strategy = merge_strategy
        self.template_strategy = template_strategy
        self.language_policy = language_policy
        self.cfg = cfg
        self.deps = deps
        self.llm = llm
        self.agentic_loop = agentic_loop
        # RAG.10: modelo pequeño y rápido para reescribir. Lo resuelve la GraphFactory, que
        # es quien ve la cascada; el nodo solo lo usa. None = no hay reescritura posible,
        # que es lo mismo que tenerla apagada.
        self.rewrite_llm = rewrite_llm

    def compile(self):
        """Compila y devuelve el grafo LangGraph listo para invocar."""
        graph = StateGraph(CoreGraphState)

        async def detect_language_node(state: CoreGraphState) -> dict:
            lang = self.language_policy.detect(state["query"])
            # RES.2: la bandera se normaliza en la entrada para que «no hubo reformulación» sea
            # `False` y no la ausencia de la clave. Quien lee el contrato no debería tener que
            # distinguir esas dos cosas.
            return {"language": lang, "reformulada": False}

        async def rewrite_query_node(state: CoreGraphState) -> dict:
            """Passthrough salvo que el flag esté encendido Y haya conversación previa."""
            historial = list(state.get("history") or [])
            habilitado = getattr(self.cfg, "query_rewriting_enabled", False)
            if self.rewrite_llm is None or not necesita_reescritura(habilitado, historial):
                return {"rewritten_query": None}

            reescrita = await reescribir_consulta(
                state["query"], historial, self.rewrite_llm
            )
            # Si el fallback devolvió la original, no hubo reescritura: dejarla en None
            # evita que la traza y el bypass muestren un paso que no ocurrió.
            return {"rewritten_query": reescrita if reescrita != state["query"] else None}

        async def reformular_node(state: CoreGraphState) -> dict:
            """RES.2 — la consulta escrita como la escribiría la norma, para volver a buscar.

            Se llega aquí **sólo** cuando la primera pasada no superó el umbral, y por eso el
            paso es rentable: normalizar siempre costaría una llamada al modelo en el camino
            crítico de todas las consultas, y esto se paga en el 28% de las de Normativa y el
            71% de las de Gerencia.
            """
            reformulada = await reformular_al_vocabulario_normativo(
                state["query"], self.rewrite_llm
            )
            if reformulada is None:
                # Ni se marca la bandera ni se vuelve a buscar: repetir la búsqueda con lo mismo
                # sería pagar una consulta al corpus para obtener el resultado que ya se tiene.
                return {}
            return {"reformulated_query": reformulada, "reformulada": True}

        def hubo_reformulacion(
            state: CoreGraphState,
        ) -> Literal["retrieve", "fallback"]:
            return "retrieve" if state.get("reformulated_query") else "fallback"

        async def retrieve_node(state: CoreGraphState) -> dict:
            output = await self.retrieval_strategy.retrieve(
                # Se BUSCA con la reescrita o con la reformulada; a partir de aquí nadie más las
                # ve. La reformulación manda sobre la reescritura porque es posterior: se produjo
                # justo porque lo anterior no encontró nada.
                state.get("reformulated_query")
                or state.get("rewritten_query")
                or state["query"],
                state["chatbot_id"],
                self.cfg,
                self.deps,
                # ACT.3: la lengua de la pregunta llega hasta el WHERE. Sin ella la regla de
                # «una version por norma» no se puede aplicar donde tiene que aplicarse, y
                # filtrarla despues del top-k haria que la version descartada hubiera consumido
                # una plaza.
                language=state.get("language"),
            )
            return {"retrieval_output": output}

        async def merge_node(state: CoreGraphState) -> dict:
            raw = state.get("retrieval_output")
            output: RetrievalOutput = raw if raw is not None else RetrievalOutput()
            items: list[EvidenceItem] = self.merge_strategy.merge(output)

            query_language = state.get("language")
            items = self.language_policy.filter_items(query_language, items)

            context_source_language: str | None = None
            if output.buckets:
                context_source_language = output.buckets[0].context_source_language

            translation_warning = self.language_policy.should_warn_translation(
                query_language, context_source_language
            )

            quality_source: dict | None = None
            if not items:
                score = 0.0
            else:
                # RES.1 — la nota es la del MEJOR fragmento, no la media de todos.
                #
                # Con la media, la cola votaba sobre si hay respuesta: cada fragmento flojo que
                # entraba bajaba la nota, así que `retrieval_top_k` —un mando de amplitud—
                # decidía de rebote cuántas preguntas se contestan. Medido el 2026-08-25 sobre
                # las dos baterías reales: con la media, 18 de 25 y 2 de 7; con el mejor, 20 y 4,
                # y **con cualquier anchura** (2, 3, 5 u 8 dan lo mismo). Ése es el punto: que la
                # anchura deje de decidir.
                #
                # El caso que lo retrata: SGE-01 tenía un fragmento de 0,637 con un umbral de
                # 0,50 y se rendía, porque los tres de detrás bajaban la media a 0,371. La
                # evidencia estaba y la enterraba el promedio.
                #
                # Corolario que hay que tener presente: `quality_threshold` pasa a significar
                # «tengo al menos una fuente buena» en vez de «mis fuentes son buenas de media».
                puntuados = [i for i in items if i.score is not None]
                if puntuados:
                    mejor = max(puntuados, key=lambda i: i.score or 0.0)
                    nota = mejor.score or 0.0
                    quality_source = {"title": mejor.title, "score": mejor.score}
                else:
                    nota = 0.5
                # La penalización por número de resultados mide otra cosa —cuántos hay— y se
                # queda: desacoplarla del `top_k` fue justo lo que arregló RAG.15.
                count_ok = len(items) >= self.cfg.min_retrieval_results
                score = nota if count_ok else nota * 0.5

            return {
                "merged_items": items,
                "quality_score": score,
                "quality_source": quality_source,
                "translation_warning": translation_warning,
                # VIS.5 — **qué** lengua, no sólo que hay que avisar. El booleano llegaba hasta
                # el chat y allí el texto se construía con la lengua de la PREGUNTA, que es la
                # que quien pregunta ya conoce; lo que necesita saber es en qué lengua está la
                # norma a la que le lleva el enlace. El dato existía aquí y no viajaba.
                "context_source_language": context_source_language,
            }

        def quality_gate(
            state: CoreGraphState,
        ) -> Literal["generate_answer", "reformular", "fallback"]:
            # RAG.11: en bypass el gate INFORMA pero no desvía. Si desviara, el caso que
            # más interesa depurar —puntuación baja— sería justo el que no enseña ningún
            # prompt, que es lo único que el bypass existe para enseñar. Por lo mismo tampoco
            # dispara la reformulación: el prompt que se quiere ver es el de ESTA consulta.
            if state.get("debug_bypass"):
                return "generate_answer"
            if state["quality_score"] >= self.cfg.quality_threshold:
                return "generate_answer"
            # RES.2 — una segunda pasada, y una sola. La guarda contra bucles es la propia
            # `reformulated_query`: si ya está puesta, se viene de la segunda pasada y no hay
            # tercera. Sin ella esto es un bucle infinito con coste por vuelta.
            if self.rewrite_llm is not None and not state.get("reformulated_query"):
                return "reformular"
            return "fallback"

        async def generate_answer_node(state: CoreGraphState) -> dict:
            items: list[EvidenceItem] = state["merged_items"]
            context = self.template_strategy.build_prompt_context(
                items,
                state.get("language"),
                state["query"],
            )
            instantanea = (
                self._instantanea_de_bypass(state, context, items)
                if state.get("debug_bypass") or state.get("capture_context")
                else None
            )
            if state.get("debug_bypass"):
                return {
                    "bypass": instantanea,
                    "answer": None,
                    "fallback_used": False,
                    "fallback_reason": None,
                    "sources": items,
                }

            if self.llm is None:
                return {
                    "answer": context,
                    "fallback_used": False,
                    "fallback_reason": None,
                    "sources": items,
                    "bypass": instantanea,
                }

            if self.agentic_loop is not None:
                # Modo MD_AGENT_SELECTOR: los items recuperados son el ÍNDICE, y sólo se
                # pueden citar los documentos que el loop lea de verdad.
                citables, answer = await self.agentic_loop.run(
                    llm=self.llm,
                    system=context,
                    query=state["query"],
                    chatbot_id=state["chatbot_id"],
                    language=state.get("language"),
                )
            else:
                response = await self.llm.ainvoke([
                    {"role": "system", "content": context},
                    {"role": "user", "content": state["query"]},
                ])
                answer = texto_de(response)
                citables = items

            # UX.4: el mensaje de «no lo sé» es del chatbot. Esta rama lo ignoraba y
            # devolvía el texto fijo en castellano; el `fallback_node` de abajo sí lo
            # respetaba, así que el mismo asistente contestaba dos cosas distintas según
            # por dónde se rindiera.
            sin_respuesta = (
                getattr(self.cfg, "no_answer_message", None) or NO_CITATION_FALLBACK
            )
            validated = enforce_citation_contract(
                answer,
                citables,
                self.cfg.retrieval_mode,
                no_answer_message=sin_respuesta,
            )
            # Se compara contra el mensaje de rendición, no contra la respuesta original:
            # el contrato ahora también AJUSTA —degrada al documento una cita cuyo ancla no
            # reconoce— y un ajuste no es rendirse. Compararlo con el original contaba esos
            # ajustes como fallback y, peor, se saltaba el aviso de vigencia de abajo.
            incumplio_citas = validated == sin_respuesta
            sin_fundamento = False
            # VIS.3: el aviso de vigencia se AÑADE aquí, después del contrato de citas y
            # sobre la evidencia realmente citable. No es una instrucción al modelo: una
            # instrucción se cumple casi siempre, y «casi siempre» no basta para decir si
            # una norma rige. Si el fallback ya sustituyó la respuesta, no hay nada citado
            # de lo que advertir.
            # HIB.S — el contrato pregunta «¿ha citado?»; esto pregunta «¿lo que cita lo
            # sostiene?». Va DESPUES del contrato y solo si el contrato paso: si la respuesta
            # ya se descarto por no citar, no hay nada que fundamentar.
            #
            # APAGADO por defecto (`grounding_check_enabled`). Una puerta que puede descartar
            # respuestas no se enciende por el hecho de existir, y el interruptor es ademas lo
            # que permite medir la latencia del primer token con y sin ella.
            fundamento = None
            if (
                not incumplio_citas
                and getattr(self.cfg, "grounding_check_enabled", False)
                and self.llm is not None
            ):
                fundamento = await hay_fundamento(
                    texto=validated,
                    fuentes=[fuente_desde_evidencia(i) for i in citables],
                    juez=juez_de_modelo(self.llm),
                )
                if not fundamento.sostenida:
                    validated = sin_respuesta
                    sin_fundamento = True

            if not incumplio_citas and not sin_fundamento:
                aviso = aviso_de_vigencia(citables)
                if aviso:
                    validated = f"{validated}\n\n{aviso}"
            return {
                "answer": validated,
                "fallback_used": incumplio_citas or sin_fundamento,
                # El motivo distingue las dos puertas. Sin eso la traza de HIB.I no permite
                # saber cual rechazo, y toda la medicion de esta rama se basa en contarlas
                # por separado: el contrato acierta 7 de 18 sin falsos positivos, y lo que
                # hay que medir es cuanto suma la comprobacion de fundamento sobre eso.
                "fallback_reason": (
                    "citation" if incumplio_citas
                    else "grounding" if sin_fundamento
                    else None
                ),
                "grounding": (
                    {
                        "juzgadas": fundamento.juzgadas,
                        "con_fundamento": fundamento.con_fundamento,
                        "juez_fallo": fundamento.juez_fallo,
                        # El detalle viaja para que un rechazo se pueda explicar sin repetir
                        # la tanda. Se recorta cada afirmacion, no la lista: cuantas fallaron
                        # es tan informativo como cuales.
                        "detalle": fundamento.detalle,
                    }
                    if fundamento is not None else None
                ),
                "sources": citables,
                "bypass": instantanea,
            }

        async def fallback_node(state: CoreGraphState) -> dict:  # noqa: ARG001 — LangGraph llama a cada nodo con el estado
            # El fallback EMITE el mensaje, no deja answer=None: el endpoint lo manda por
            # SSE como una respuesta normal y el usuario ve una explicación en vez de nada.
            #
            # UX.4: el mensaje es configurable por chatbot. «No lo sé» a secas deja al
            # ciudadano en el mismo sitio en el que estaba; decirle a quién preguntar es el
            # servicio. Y a quién preguntar depende del asistente —Infocampus atiende al
            # público, no al personal de Gerencia—, así que no puede ser una constante.
            return {
                "answer": getattr(self.cfg, "no_answer_message", None) or NO_CITATION_FALLBACK,
                "fallback_used": True,
                "fallback_reason": "quality_gate",
                "sources": [],
            }

        async def log_node(state: CoreGraphState) -> dict:  # noqa: ARG001 — LangGraph llama a cada nodo con el estado
            return {}

        graph.add_node("detect_language", detect_language_node)
        graph.add_node("rewrite_query", rewrite_query_node)
        graph.add_node("retrieve", retrieve_node)
        graph.add_node("merge", merge_node)
        graph.add_node("reformular", reformular_node)
        graph.add_node("generate_answer", generate_answer_node)
        graph.add_node("fallback", fallback_node)
        graph.add_node("log", log_node)

        graph.set_entry_point("detect_language")
        graph.add_edge("detect_language", "rewrite_query")
        graph.add_edge("rewrite_query", "retrieve")
        graph.add_edge("retrieve", "merge")
        graph.add_conditional_edges(
            "merge",
            quality_gate,
            {
                "generate_answer": "generate_answer",
                "reformular": "reformular",
                "fallback": "fallback",
            },
        )
        # RES.2 — la segunda pasada. Si el reformulador no devolvió nada, se va directo al
        # fallback sin volver a buscar, y por eso este nodo también tiene arista condicional.
        graph.add_conditional_edges(
            "reformular",
            hubo_reformulacion,
            {"retrieve": "retrieve", "fallback": "fallback"},
        )
        graph.add_edge("generate_answer", "log")
        graph.add_edge("log", END)
        graph.add_edge("fallback", END)

        return graph.compile()

    def _instantanea_de_bypass(
        self, state: CoreGraphState, context: str, items: list
    ) -> dict:
        """Lo que se iba a enviar al modelo, más el porqué (RAG.11).

        Se serializa aquí y no en el endpoint porque el endpoint no ve la evidencia ni el
        contexto construido: solo el estado final. Y va todo junto a propósito — el valor
        del bypass es leer el prompt y su configuración resuelta **en la misma pantalla**.
        """
        from dataclasses import asdict, is_dataclass

        salida = state.get("retrieval_output")
        debug: dict = {}
        if salida is not None and getattr(salida, "buckets", None):
            for bucket in salida.buckets:
                debug.update(getattr(bucket, "debug", None) or {})

        def _evidencia(item) -> dict:
            # Se aceptan los dos dialectos por el mismo motivo que `_serialize_source` en
            # el endpoint: RAG.2 unificó el contrato en `EvidenceItem`, pero las
            # estrategias de `services/retrieval/` siguen hablando `Source` por debajo.
            identificador = (
                getattr(item, "source_id", None) or getattr(item, "document_id", None)
            )
            return {
                "document_id": str(identificador) if identificador else None,
                "title": getattr(item, "title", None),
                "url": getattr(item, "source_url", None) or getattr(item, "url", None),
                "excerpt": (
                    getattr(item, "content", None) or getattr(item, "excerpt", None)
                ),
                "score": getattr(item, "score", None),
            }

        return {
            "system_prompt": context,
            "messages": [
                {"role": "system", "content": context},
                {"role": "user", "content": state["query"]},
            ],
            "packed_context": {
                "evidencias": [_evidencia(i) for i in items],
                "dropped_count": debug.get("dropped_count", 0),
                "total_tokens": debug.get("total_tokens"),
                "context_token_budget": debug.get("context_token_budget"),
            },
            "sources": [_evidencia(i) for i in items],
            "rewritten_query": state.get("rewritten_query"),
            "resolved_config": (
                {k: str(v) if isinstance(v, uuid.UUID) else v
                 for k, v in asdict(self.cfg).items()}
                if is_dataclass(self.cfg) else {}
            ),
            "quality_gate": {
                "score": state.get("quality_score", 0.0),
                "passed": state.get("quality_score", 0.0) >= self.cfg.quality_threshold,
            },
        }

    async def run(
        self,
        query: str,
        chatbot_id: str,
        history: list[str] | None = None,
        debug_bypass: bool = False,
        capture_context: bool = False,
    ) -> dict:
        """Ejecuta el grafo y devuelve el estado final."""
        compiled = self.compile()
        initial = cast(CoreGraphState, {
            "query": query,
            "chatbot_id": chatbot_id,
            "language": None,
            "history": list(history or []),
            "rewritten_query": None,
            "debug_bypass": debug_bypass,
            "capture_context": capture_context,
            "bypass": None,
            "retrieval_output": None,
            "merged_items": [],
            "answer": None,
            "quality_score": 0.0,
            "fallback_used": False,
            "translation_warning": False,
            "context_source_language": None,
            "fallback_reason": None,
            "sources": [],
        })
        return await compiled.ainvoke(initial)
