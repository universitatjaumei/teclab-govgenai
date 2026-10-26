"""El asistente de Gerencia: leer entera la normativa propia, buscar en la externa.

La normativa **propia** de la Universidad cabe entera en el contexto documento a documento
—la más larga son 51.032 tokens—, así que el agente puede leerla completa y citar el
artículo exacto. Las normas **externas** no: las 22 del corpus de Gerencia suman 1.745.337
tokens y la Ley de Contratos sola son 279.425. Medido sobre la base del piloto.

De ahí las dos piezas de este módulo:

1. **El agente puede buscar fragmentos** (`search_knowledge`), que es la única forma de
   traerse un artículo de la LCSP sin volcar la ley entera.
2. **`read_document` no vuelca lo que no cabe**: por encima del límite devuelve el
   principio y remite a la búsqueda, en vez de meter 279.425 tokens en la conversación.

Y antes que nada, el bug que lo bloqueaba todo: los tools declaraban sus **dependencias
inyectadas** (`index`, `reader`, `retriever`) como parámetros, así que `bind_tools` moría
con `SchemaError` y el modo `MD_AGENT_SELECTOR` no llegaba a ejecutar ni una vuelta. No
salía en los tests porque todos construían el loop con `tools=[]`.
"""
from __future__ import annotations

import uuid

import pytest


def _tools():
    from server.app.modules.agents_hub.services.retrieval.agentic_strategy import (
        AgenticRetrievalStrategy,
    )

    return AgenticRetrievalStrategy(session=None).get_agent_tools()


def _esquema(nombre: str) -> dict:
    from langchain_core.utils.function_calling import convert_to_openai_tool

    for herramienta in _tools():
        esquema = convert_to_openai_tool(herramienta)
        if esquema["function"]["name"] == nombre:
            return esquema["function"]
    raise AssertionError(f"El toolset no declara {nombre}: {[t.name for t in _tools()]}")


class TestLoQueVeElModelo:

    def test_should_be_bindable_by_the_model(self):
        """`bind_tools` moría con `SchemaError` y el modo agente no arrancaba nunca."""
        from langchain_core.utils.function_calling import convert_to_openai_tool

        for herramienta in _tools():
            convert_to_openai_tool(herramienta)

    @pytest.mark.parametrize(
        ("nombre", "inyectado"),
        [
            ("list_documents", "index"),
            ("read_document", "reader"),
            ("search_knowledge", "retriever"),
        ],
    )
    def test_should_not_ask_the_model_for_injected_dependencies(self, nombre, inyectado):
        """Un `reader` en el esquema es un objeto que el modelo tendría que inventarse."""
        propiedades = _esquema(nombre)["parameters"].get("properties", {})

        assert inyectado not in propiedades, f"{nombre} pide {inyectado} al modelo"

    @pytest.mark.parametrize("nombre", ["list_documents", "read_document", "search_knowledge"])
    def test_should_not_ask_the_model_for_the_chatbot_id(self, nombre):
        """El chatbot lo pone el loop. Pedírselo al modelo es ruido y un id filtrado."""
        propiedades = _esquema(nombre)["parameters"].get("properties", {})

        assert "chatbot_id" not in propiedades

    def test_should_offer_fragment_search_to_the_agent(self):
        """Sin esto, la única forma de consultar la LCSP es cargarla entera."""
        assert "search_knowledge" in {t.name for t in _tools()}

    def test_should_keep_asking_the_model_for_what_only_it_knows(self):
        """El recorte del esquema no puede llevarse por delante los argumentos reales."""
        assert "document_id" in _esquema("read_document")["parameters"]["properties"]
        assert "query" in _esquema("search_knowledge")["parameters"]["properties"]
        assert "submateries" in _esquema("list_documents")["parameters"]["properties"]


# ───────────────────────── El loop ─────────────────────────


class _RespuestaLLM:
    def __init__(self, content="", tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


class _FakeLLM:
    def __init__(self, respuestas):
        self._respuestas = list(respuestas)
        self.vistos: list[list] = []

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, mensajes):
        self.vistos.append(list(mensajes))
        return self._respuestas.pop(0)


class _Reader:
    last_index_level = "global"

    def __init__(self, markdown="Article 1. Text.", token_count=100):
        self._markdown = markdown
        self._token_count = token_count

    async def list_index(self, chatbot_id, language, submateries=None):
        return "Documentos disponibles: ..."

    async def read(self, document_id):
        return {
            "title": "Llei 9/2017",
            "url": "https://boe.es/l9",
            "markdown_content": self._markdown,
            "language": "es",
            "token_count": self._token_count,
        }


def _loop(reader, searcher=None):
    from server.app.modules.agents_hub.agent.public_graphs.strategies.agentic_loop import (
        AgenticLoop,
    )

    return AgenticLoop(reader=reader, tools=[], searcher=searcher)


class TestBusquedaDeFragmentos:

    @pytest.mark.asyncio
    async def test_should_run_the_search_and_keep_what_it_found_as_evidence(self):
        from server.app.modules.agents_hub.agent.public_graphs.strategies.retrieval_contract import (
            EvidenceItem,
        )

        class _Buscador:
            def __init__(self):
                self.consultas = []

            async def search(self, query, chatbot_id, language=None):
                self.consultas.append(query)
                return [
                    EvidenceItem(
                        source_id="doc-lcsp",
                        content="Article 118. Contractes menors...",
                        source_url="https://boe.es/l9#a118",
                        title="Llei 9/2017",
                        language="es",
                        score=0.8,
                        metadata={},
                    )
                ]

        buscador = _Buscador()
        llm = _FakeLLM([
            _RespuestaLLM(tool_calls=[
                {"id": "1", "name": "search_knowledge", "args": {"query": "contracte menor"}}
            ]),
            _RespuestaLLM(content="Segons l'article 118..."),
        ])

        evidencias, _ = await _loop(_Reader(), buscador).run(
            llm=llm, system="sys", query="contracte menor?", chatbot_id=str(uuid.uuid4()),
        )

        assert buscador.consultas == ["contracte menor"]
        assert [e.source_url for e in evidencias] == ["https://boe.es/l9#a118"]

    @pytest.mark.asyncio
    async def test_should_say_search_is_unavailable_instead_of_failing(self):
        """Un chatbot sin embeddings no puede buscar fragmentos. El modelo tiene que
        enterarse por la respuesta del tool, no por una excepción a mitad del turno."""
        llm = _FakeLLM([
            _RespuestaLLM(tool_calls=[
                {"id": "1", "name": "search_knowledge", "args": {"query": "x"}}
            ]),
            _RespuestaLLM(content="fi"),
        ])

        evidencias, texto = await _loop(_Reader(), searcher=None).run(
            llm=llm, system="sys", query="q", chatbot_id=str(uuid.uuid4()),
        )

        assert evidencias == []
        assert texto == "fi"


class TestElHistorialQueVeElModelo:

    @pytest.mark.asyncio
    async def test_should_keep_the_tool_calls_in_the_assistant_turn(self):
        """Sin los `tool_calls` en el turno del asistente, el proveedor no puede casar el
        `ToolMessage` que viene detrás: el modelo no ve el resultado y **vuelve a pedir la
        misma tool** hasta agotar las iteraciones. Visto en vivo contra el corpus de
        Gerencia: diez `search_knowledge` idénticas y una respuesta en blanco.
        """
        llm = _FakeLLM([
            _RespuestaLLM(tool_calls=[
                {"id": "abc", "name": "search_knowledge", "args": {"query": "q"}}
            ]),
            _RespuestaLLM(content="fi"),
        ])

        class _Buscador:
            async def search(self, query, chatbot_id, language=None):
                return []

        await _loop(_Reader(), _Buscador()).run(
            llm=llm, system="sys", query="q", chatbot_id=str(uuid.uuid4()),
        )

        segunda_vuelta = llm.vistos[1]
        turno_asistente = segunda_vuelta[-2]
        assert getattr(turno_asistente, "tool_calls", None), (
            "el turno del asistente llega sin tool_calls y el ToolMessage queda huerfano"
        )


class TestLaRespuestaQueSaleDelBucle:

    @pytest.mark.asyncio
    async def test_should_return_text_when_the_model_answers_in_blocks(self):
        """Gemini devuelve `content` como **lista de bloques** en cuanto hay más de una
        parte. El bucle la devolvía tal cual y el validador de citas moría con
        `TypeError: expected string or bytes-like object, got 'list'`, así que la respuesta
        no llegaba nunca. Visto en vivo contra el corpus de Gerencia.
        """
        llm = _FakeLLM([
            _RespuestaLLM(content=[
                {"type": "text", "text": "Segons l'article 118 "},
                {"type": "text", "text": "de la Llei 9/2017."},
            ])
        ])

        _, texto = await _loop(_Reader()).run(
            llm=llm, system="sys", query="q", chatbot_id=str(uuid.uuid4()),
        )

        assert texto == "Segons l'article 118 de la Llei 9/2017."


class TestLecturaDeNormasLargas:

    @pytest.mark.asyncio
    async def test_should_not_dump_a_norm_that_does_not_fit(self):
        from server.app.modules.agents_hub.agent.public_graphs.strategies.agentic_loop import (
            LIMITE_LECTURA_TOKENS,
        )

        enorme = "Article 1. " * 200_000
        llm = _FakeLLM([
            _RespuestaLLM(tool_calls=[
                {"id": "1", "name": "read_document", "args": {"document_id": str(uuid.uuid4())}}
            ]),
            _RespuestaLLM(content="fi"),
        ])

        reader = _Reader(markdown=enorme, token_count=LIMITE_LECTURA_TOKENS * 4)
        evidencias, _ = await _loop(reader).run(
            llm=llm, system="sys", query="q", chatbot_id=str(uuid.uuid4()),
        )

        # La evidencia sigue existiendo —el modelo miró el documento— pero el texto que
        # entra en la conversación no puede ser la ley entera.
        assert len(evidencias) == 1
        assert evidencias[0].metadata.get("lectura_truncada") is True

    @pytest.mark.asyncio
    async def test_should_tell_the_model_to_search_inside_it_instead(self):
        """Truncar sin decir cómo seguir deja al modelo respondiendo con el índice de la
        ley. La salida del tool tiene que nombrar la alternativa."""
        from server.app.modules.agents_hub.agent.public_graphs.strategies.agentic_loop import (
            AgenticLoop,
            LIMITE_LECTURA_TOKENS,
        )

        reader = _Reader(markdown="x" * 5_000, token_count=LIMITE_LECTURA_TOKENS + 1)
        loop = AgenticLoop(reader=reader, tools=[])

        salida = await loop._ejecutar(
            {"id": "1", "name": "read_document", "args": {"document_id": str(uuid.uuid4())}},
            chatbot_id=str(uuid.uuid4()),
            language=None,
            leidas=[],
        )

        assert "search_knowledge" in salida

    @pytest.mark.asyncio
    async def test_should_keep_reading_our_own_regulations_whole(self):
        """La normativa propia cabe: la más larga del corpus son 51.032 tokens."""
        from server.app.modules.agents_hub.agent.public_graphs.strategies.agentic_loop import (
            AgenticLoop,
        )

        reader = _Reader(markdown="Article 1. Objecte.", token_count=51_032)
        loop = AgenticLoop(reader=reader, tools=[])

        salida = await loop._ejecutar(
            {"id": "1", "name": "read_document", "args": {"document_id": str(uuid.uuid4())}},
            chatbot_id=str(uuid.uuid4()),
            language=None,
            leidas=[],
        )

        assert salida == "Article 1. Objecte."


# ───────────────────────── El cableado ─────────────────────────


class _Cfg:
    retrieval_mode = "MD_AGENT_SELECTOR"
    min_retrieval_results = 5


class _Deps:
    def __init__(self, embedder=None):
        self.session = None
        self.embedder = embedder


class TestCableado:

    def test_should_wire_the_search_when_the_chatbot_has_embeddings(self):
        from server.app.modules.agents_hub.agent.public_graphs.core.graph_factory import (
            build_agentic_loop_if_needed,
        )

        loop = build_agentic_loop_if_needed(_Cfg(), _Deps(embedder=object()))

        assert loop._searcher is not None

    def test_should_leave_the_search_off_when_there_is_no_embedder(self):
        """Sin embeddings el asistente sigue funcionando con índice y lectura, que es como
        funcionaba hasta ahora. Montar un buscador que no puede buscar sería peor."""
        from server.app.modules.agents_hub.agent.public_graphs.core.graph_factory import (
            build_agentic_loop_if_needed,
        )

        loop = build_agentic_loop_if_needed(_Cfg(), _Deps(embedder=None))

        assert loop._searcher is None

    @pytest.mark.asyncio
    async def test_should_not_narrow_the_search_by_language(self):
        """Filtrar por idioma dejaba la búsqueda **vacía siempre**.

        Los chunks del corpus llevan `val` y `es`; el grafo resuelve la lengua de la
        conversación como `ca`. Ningún fragmento coincide, así que el agente pedía
        `search_knowledge` una y otra vez hasta agotar las iteraciones y respondía en
        blanco. Visto en vivo contra el corpus de Gerencia.

        El pipeline RAG de producción tampoco filtra por idioma, y por esto mismo.
        """
        from server.app.modules.agents_hub.agent.public_graphs.core.graph_factory import (
            _BuscadorVectorial,
        )

        class _Estrategia:
            def __init__(self):
                self.recibido = {}

            async def get_context(self, query, chatbot_id, language=None):
                self.recibido = {"language": language}
                return type("Ctx", (), {"sources": []})()

        estrategia = _Estrategia()
        await _BuscadorVectorial(estrategia).search("q", str(uuid.uuid4()), language="ca")

        assert estrategia.recibido["language"] is None


class TestInstruccionAlModelo:

    def test_should_tell_the_model_when_to_search_instead_of_reading(self):
        """El modelo no puede adivinar que hay normas que no caben."""
        from server.app.modules.agents_hub.agent.public_graphs.profiles.public_kb_rich import (
            _INSTRUCCION_TOOLS,
        )

        assert "search_knowledge" in _INSTRUCCION_TOOLS

    def test_should_name_the_read_argument_as_the_schema_declares_it(self):
        """La instrucción decía `read_document(id=...)` y el esquema pide `document_id`."""
        from server.app.modules.agents_hub.agent.public_graphs.profiles.public_kb_rich import (
            _INSTRUCCION_TOOLS,
        )

        assert "read_document(id=" not in _INSTRUCCION_TOOLS
