"""HIB.B — al usuario sólo le llegan los tokens de la respuesta.

Dos defectos encadenados, los dos visibles en el piloto.

**El primero.** `on_chat_model_stream` emitía los tokens de **cualquier** llamada al modelo. En
el grafo hay tres nodos que llaman al LLM —`rewrite_query` (RAG.10), `reformular` (RES.2) y
`generate_answer`—, y en el modo agéntico también el selector, que corre dentro de `retrieve`.
Así que quien preguntaba veía la consulta reformulada, o el razonamiento del selector, como si
fueran la respuesta. Reproducido el 2026-08-26: pregunta sobre conservación de expedientes →
respuesta `plazo de conservación expedientes contratación menor`, con
`fallback_reason = quality_gate`.

Antes de RES.2 casi no se notaba porque el reescritor apenas corría: `necesita_reescritura`
exigía dos turnos previos. RES.2 lo puso en el camino del 28 % de las consultas de Normativa, y
HIB.C lo pondrá en casi todos los turnos no iniciales.

**El segundo.** El mensaje de rendición sólo se emitía `if fallback_answer and not
collected_tokens`, así que cuando algo ya había dejado tokens **nunca se mostraba**.

**La lista de nodos no se escribe a mano.** Se deriva de `_FINAL_NODES`, que ya es la fuente de
verdad de «qué nodos producen la respuesta» y que el manejador del estado final ya usa. Quien
añada un nodo que genere la respuesta tiene que declararlo ahí o el estado final se rompe, y el
filtro del stream lo sigue automáticamente. Una lista aparte divergiría en el primer cambio,
que es el argumento de P1 del marco de gobernanza.

**Por qué un evento de descarte y no retener los tokens.** El contrato de citas corre *dentro*
de `generate_answer`, después de generar, así que sus tokens ya han salido cuando rechaza.
Retenerlos hasta validar costaría el streaming en TODAS las respuestas: medido en HIB.I, el
primer token pasaría de 780 ms a 2.140 ms. El contrato rechaza en torno al 4 % de las consultas
(1 de 25 en la tanda del 2026-08-26). Decisión del usuario del 2026-08-26: se conserva el
streaming y se añade el evento.

Deploy: edge
"""
from __future__ import annotations

from pathlib import Path

import pytest

FUENTE = Path("app/modules/agents_hub/services/turno_de_chat.py")


@pytest.fixture(scope="module")
def texto() -> str:
    return FUENTE.read_text(encoding="utf-8")


def _bloque_del_stream(texto: str) -> str:
    """El cuerpo de la rama `on_chat_model_stream`, hasta el `elif` siguiente."""
    desde = texto.index('elif kind == "on_chat_model_stream":')
    resto = texto[desde + 10 :]
    hasta = resto.index("elif kind ==")
    return resto[:hasta]


class TestLaListaDeNodosSeDerivaDelGrafo:

    def test_should_derive_the_allowed_nodes_from_the_final_nodes(self, texto: str):
        """`_FINAL_NODES` es la única fuente de verdad de quién produce la respuesta."""
        from server.app.modules.agents_hub.services.turno_de_chat import _FINAL_NODES

        assert "generate_answer" in _FINAL_NODES
        # El filtro del stream lee esa constante, no una lista propia.
        assert "_FINAL_NODES" in _bloque_del_stream(texto)

    def test_should_fail_when_a_generating_node_is_not_declared(self):
        """Guardarraíl: si alguien añade un nodo que genera la respuesta y no lo declara en
        `_FINAL_NODES`, este test lo caza.

        Se comprueba contra el grafo real: los nodos que escriben `answer` en el estado.
        """
        from server.app.modules.agents_hub.services.turno_de_chat import _FINAL_NODES

        fuente_grafo = Path(
            "app/modules/agents_hub/agent/public_graphs/core/core_graph.py"
        ).read_text(encoding="utf-8")

        declarados = set(_FINAL_NODES)
        # Nodos del grafo, tal como se registran.
        import re

        nodos = set(re.findall(r'graph\.add_node\("([a-z_]+)"', fuente_grafo))
        # Los que devuelven `"answer":` en su cuerpo son los que producen la respuesta.
        productores = {
            n
            for n in nodos
            if re.search(
                rf'def {n}_node\(state.*?\n(.*?)(?=\n        async def |\n        def |\Z)',
                fuente_grafo,
                re.S,
            )
            and '"answer"' in (
                re.search(
                    rf'def {n}_node\(state.*?\n(.*?)(?=\n        async def |\n        def |\Z)',
                    fuente_grafo,
                    re.S,
                ).group(1)
            )
        }

        sin_declarar = productores - declarados
        assert not sin_declarar, (
            f"Nodos que producen la respuesta y no están en _FINAL_NODES: {sin_declarar}. "
            "Sus tokens no llegarían al usuario, o llegarían los de otro."
        )

    def test_should_not_stream_tokens_from_the_rewrite_model(self, texto: str):
        """Los tres nodos que llaman al modelo y NO son la respuesta.

        El bloque se delimita por el `elif` siguiente y no por un número de caracteres: la
        primera versión de este test cortaba a 900 y el comentario que explica la decisión
        empujó la comprobación fuera de la ventana.
        """
        bloque = _bloque_del_stream(texto)

        assert "langgraph_node" in bloque
        # Y el filtro descarta, no sólo mira.
        assert "continue" in bloque


class TestElMensajeDeRendicionSeEmiteSiempre:

    def test_should_emit_the_no_answer_message_even_if_other_nodes_streamed(
        self, texto: str
    ):
        """La condición `and not collected_tokens` es el defecto: se va."""
        assert "if fallback_answer and not collected_tokens" not in texto
        assert "if fallback_answer:" in texto

    def test_should_send_a_discard_event_before_the_rendition(self, texto: str):
        """El widget no puede retirar lo ya pintado sin que se le diga."""
        assert '_sse("discard"' in texto

    def test_should_store_what_the_user_saw(self, texto: str):
        """`assistant_message` guardaba la reformulación: guardaba algo que el usuario no
        vio, y entonces la revisión juzga una respuesta que nadie recibió."""
        indice_descarte = texto.index('_sse("discard"')
        indice_mensaje = texto.index("assistant_message = ")
        assert indice_descarte < indice_mensaje, (
            "El descarte tiene que vaciar `collected_tokens` ANTES de componer "
            "`assistant_message`, o se guarda lo que se acaba de retirar"
        )
