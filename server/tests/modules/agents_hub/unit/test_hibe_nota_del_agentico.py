"""HIB.E — la nota del agéntico es real, y con ella su puerta de calidad existe por primera vez.

`agentic_loop.py` ponía `score=1.0` en cada documento leído. El *quality gate* del CoreGraph
compara la mejor nota contra `quality_threshold`, así que el agéntico **contestaba siempre** con
cualquier umbral: su 7 de 7 frente al 6 de 7 del RAG no medía recuperación, medía la ausencia de
filtro. El umbral está en 0,50 desde antes de que hiciera nada, así que no se hereda: se elige.

La nota que entra es **similitud coseno**, la misma magnitud que HIB.J puso a leer al gate en la
rama vectorial. Sin eso los dos chatbots no son comparables: un 0,50 significaría una cosa en uno
y otra en el otro, y la comparación RAG contra agéntico es justamente lo que hay que decidir.
"""
import uuid

import pytest

from server.app.modules.agents_hub.agent.public_graphs.strategies.agentic_loop import (
    AgenticLoop,
)


class _ReaderFalso:
    """Un lector con la firma real. Sin `spec` un `MagicMock` habría dejado pasar cualquier
    nombre de método y el test verde con el código roto."""

    last_index_level = 1

    def __init__(self, documento: dict | None = None) -> None:
        self._documento = documento

    async def list_index(self, chatbot_id, language, submateries=None) -> str:
        return "1. Reglament de permanencia (id: ...)"

    async def read(self, document_id: uuid.UUID) -> dict | None:
        return self._documento


def _documento() -> dict:
    return {
        "markdown_content": "Article 4. Permanencia en primer curs. Cal superar el 20 %...",
        "url": "https://www.uji.es/norma/permanencia",
        "title": "Reglament de permanencia",
        "language": "val",
        "token_count": 120,
    }


def _llamada_de_lectura(doc_id: str) -> dict:
    return {"name": "read_document", "args": {"document_id": doc_id}, "id": "call-1"}


@pytest.mark.asyncio
class TestLaNotaQueLlegaAlaPuerta:

    async def test_should_carry_the_real_score_into_the_evidence_item(self):
        doc_id = str(uuid.uuid4())
        vistas = []

        async def puntuador(query: str, document_id: str) -> float:
            vistas.append((query, document_id))
            return 0.73

        bucle = AgenticLoop(
            reader=_ReaderFalso(_documento()),
            tools=[],
            relevance_scorer=puntuador,
        )
        leidas: list = []
        await bucle._ejecutar(
            _llamada_de_lectura(doc_id), "cb", None, leidas, query="Quants credits?"
        )

        assert len(leidas) == 1
        assert leidas[0].score == pytest.approx(0.73)
        assert vistas == [("Quants credits?", doc_id)]

    async def test_should_say_so_in_the_metadata_when_there_is_no_scorer(self):
        """Sin puntuador la nota sigue siendo 1.0 —no hay con qué calcularla— pero queda
        MARCADO. Una nota inventada que no se distingue de una medida es lo que hizo que el
        agéntico pareciera mejor que el RAG durante todo un informe."""
        bucle = AgenticLoop(reader=_ReaderFalso(_documento()), tools=[])
        leidas: list = []
        await bucle._ejecutar(
            _llamada_de_lectura(str(uuid.uuid4())), "cb", None, leidas, query="x"
        )

        assert leidas[0].score == 1.0
        assert leidas[0].metadata["score_sin_medir"] is True

    async def test_should_not_let_a_broken_scorer_take_down_the_answer(self):
        """Si el puntuador falla —sin embedder, la API caída— el agente responde con la nota
        sin medir y lo dice. Rendirse porque no se pudo puntuar sería cambiar un fallo de
        instrumentación por un fallo de servicio."""

        async def puntuador(query: str, document_id: str) -> float:
            raise RuntimeError("embedder no disponible")

        bucle = AgenticLoop(
            reader=_ReaderFalso(_documento()), tools=[], relevance_scorer=puntuador
        )
        leidas: list = []
        await bucle._ejecutar(
            _llamada_de_lectura(str(uuid.uuid4())), "cb", None, leidas, query="x"
        )

        assert leidas[0].score == 1.0
        assert leidas[0].metadata["score_sin_medir"] is True

    async def test_should_keep_the_index_fallback_level_and_the_truncation_flag(self):
        """La nota nueva no puede haberse llevado por delante lo que VIS.2 dejó en el
        metadato: sin `index_fallback_level` el retroceso escalonado no se puede medir."""

        async def puntuador(query: str, document_id: str) -> float:
            return 0.5

        bucle = AgenticLoop(
            reader=_ReaderFalso(_documento()), tools=[], relevance_scorer=puntuador
        )
        leidas: list = []
        await bucle._ejecutar(
            _llamada_de_lectura(str(uuid.uuid4())), "cb", None, leidas, query="x"
        )

        assert leidas[0].metadata["index_fallback_level"] == 1
        assert leidas[0].metadata["lectura_truncada"] is False


@pytest.mark.asyncio
class TestElPuntuadorDevuelveUnNumeroDeVerdad:
    """Por qué hacía falta ejercitar el camino BUENO, y no sólo el malo.

    `_puntuador_de_relevancia` usaba `PURPOSE_QUERY` sin importarlo. Cada llamada lanzaba
    `NameError`, y el `except Exception` de `_puntua` —puesto a propósito para que un puntuador
    roto no tumbara la respuesta— lo tragaba y devolvía la nota sin medir. **El arreglo de HIB.E
    estuvo inerte**, con el único síntoma de un `score_sin_medir=True` que nadie miraba.

    Lo cazó `ruff`, no un test. Y la lección no es «pasa el linter», porque el linter no ve un
    `KeyError` ni un campo renombrado: es que **una guarda defensiva convierte un fallo de
    programación en un comportamiento degradado silencioso**, y donde hay una guarda así hace
    falta un test que compruebe que el camino bueno **produce el número**, no sólo que el malo no
    explota. Los tres tests de arriba comprobaban lo segundo.
    """

    async def test_should_return_a_cosine_and_not_swallow_a_programming_error(self):
        class _Embedder:
            async def embed(self, texto, purpose=None):
                return [0.1] * 1024

        class _Resultado:
            def scalar(self):
                return 0.26  # distancia coseno

        class _Sesion:
            async def execute(self, stmt):
                return _Resultado()

        class _Deps:
            embedder = _Embedder()
            session = _Sesion()

        from server.app.modules.agents_hub.agent.public_graphs.core.graph_factory import (
            _puntuador_de_relevancia,
        )

        puntua = _puntuador_de_relevancia(_Deps())
        assert puntua is not None
        # Si faltara un import, esto lanzaría NameError aquí —donde se ve— en vez de quedar
        # tragado por el `except` del bucle agéntico.
        assert await puntua("Quants credits?", str(uuid.uuid4())) == pytest.approx(0.74)

    async def test_should_refuse_to_score_a_document_without_chunks(self):
        """Un documento sin fragmentos no se puede puntuar. Se propaga como no medible en vez
        de fabricar un 0, que lo rechazaría en la puerta."""
        class _Resultado:
            def scalar(self):
                return None

        class _Deps:
            class embedder:
                @staticmethod
                async def embed(texto, purpose=None):
                    return [0.1] * 1024

            class session:
                @staticmethod
                async def execute(stmt):
                    return _Resultado()

        from server.app.modules.agents_hub.agent.public_graphs.core.graph_factory import (
            _puntuador_de_relevancia,
        )

        puntua = _puntuador_de_relevancia(_Deps())
        with pytest.raises(ValueError, match="no tiene fragmentos"):
            await puntua("x", str(uuid.uuid4()))
