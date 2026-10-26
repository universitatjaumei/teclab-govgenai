"""USR.8 — el flujo del chat siempre termina, y el contenido del modelo siempre es texto.

**Medido en el piloto el 2026-09-03**: el asistente con `retrieval_mode='MD_AGENT_SELECTOR'`
tenía **0 interacciones registradas** mientras los de `RAG` tenían 33, 9 y 1. Todas sus
conversaciones se habían perdido — sin interacción guardada, sin consumo contabilizado y sin
`interaction_id`, o sea sin valoración posible —, y el cliente recibía la respuesta y se quedaba
esperando para siempre porque nunca llegaba el evento `done`.

La causa, del log del servidor:

    hub_chat.py:614  assistant_message = "".join(collected_tokens)
    TypeError: sequence item 0: expected str instance, list found

O sea **la tercera mordida del mismo problema**, y el docstring de `core/llm_text.py` ya la había
anunciado: «Gemini devuelve `content` como lista de bloques en cuanto la respuesta tiene más de
una parte. Quien asume que siempre es `str` no falla al recibirla: **falla más tarde y en otro
sitio**». Aquí falló ochenta líneas después, y con ella se cayó todo lo que venía detrás.

Se arreglan **las dos mitades**, porque son dos defectos distintos:

1. **La causa**: el flujo de tokens normaliza el contenido con `texto_de`, como ya hacen el
   bucle agéntico y redacción. Un `delta` que es una lista además viajaba así al cliente.
2. **El silencio**: todo lo que va después del bucle del grafo —la interacción, la traza, la
   cuota, el commit y el propio `done`— estaba **fuera de cualquier `try`**, así que un fallo
   ahí no producía ni un evento `error`. El cliente no puede distinguir «sigo pensando» de «me
   he muerto», y ésa es la diferencia entre un fallo y un fallo invisible.
"""
from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.app.modules.agents_hub.database.config_models import HubChatbot
from server.tests.dobles import completar_chatbot

ORG_PRUEBA = "00000000-0000-0000-0000-00000000dead"

_JWT_ENV = {
    "JWT_SECRET_KEY": "test-secret-key-that-is-at-least-32-characters-long",
    "JWT_ALGORITHM": "HS256",
    "JWT_EXPIRATION_MINUTES": "60",
}


def _token() -> str:
    import os

    os.environ.update(_JWT_ENV)
    from server.app.core.auth import UserInfo, create_token

    return create_token(
        UserInfo(
            user_id="user-1",
            email="user@test.com",
            role="user",
            organizacion_ids=(ORG_PRUEBA,),
        )
    )


def _chatbot() -> MagicMock:
    cb = MagicMock(spec=HubChatbot)
    cb.organizacion_id = uuid.UUID(ORG_PRUEBA)
    cb.id = uuid.uuid4()
    return completar_chatbot(cb)


def _app(chatbot) -> FastAPI:
    from sqlalchemy.ext.asyncio import AsyncSession

    from server.app.api.v1.hub_chat import router as chat_router
    from server.app.api.deps import get_session

    sesion = AsyncMock(spec=AsyncSession)
    resultado = MagicMock()
    resultado.scalar_one_or_none = MagicMock(return_value=chatbot)
    sesion.execute = AsyncMock(return_value=resultado)
    sesion.get = AsyncMock(return_value=None)
    sesion.add = MagicMock()
    sesion.commit = AsyncMock()

    async def _sesion():
        yield sesion

    app = FastAPI()
    app.dependency_overrides[get_session] = _sesion
    app.include_router(chat_router, prefix="/api/v1")
    return app


def _grafo_que_emite(chunks: list, nodo: str = "generate_answer") -> MagicMock:
    """Un grafo que emite los `chunk` dados como tokens del nodo final.

    `chunk.content` es lo que el proveedor decida: cadena o lista de bloques. Ese es
    justamente el punto del test.
    """
    eventos = [
        {
            "event": "on_chat_model_stream",
            "name": "modelo",
            "metadata": {"langgraph_node": nodo},
            "data": {"chunk": trozo},
        }
        for trozo in chunks
    ] + [
        {
            "event": "on_chain_end",
            "name": nodo,
            # **Sin `quality_score` a propósito.** Con él, el generador lo compara contra
            # `core_graph.cfg.quality_threshold`, que en este andamio es un `MagicMock`, y
            # `0.9 >= MagicMock()` levanta: un rojo del doble que se lee como un fallo del
            # flujo. La nota y la puerta tienen sus tests donde se miden de verdad.
            "data": {"output": {"sources": []}},
        }
    ]

    async def _astream(state, config=None, version="v2"):
        for ev in eventos:
            yield ev

    compilado = MagicMock()
    compilado.astream_events = _astream
    grafo = MagicMock()
    grafo.compile = MagicMock(return_value=compilado)
    return grafo


def _eventos(lineas: list[str]) -> list[tuple[str, dict]]:
    salida: list[tuple[str, dict]] = []
    actual = "message"
    for linea in lineas:
        if linea.startswith("event:"):
            actual = linea.removeprefix("event:").strip()
        elif linea.startswith("data:"):
            salida.append((actual, json.loads(linea.removeprefix("data:").strip())))
            actual = "message"
    return salida


def _conversa(chatbot, grafo, extra_patches=()) -> list[tuple[str, dict]]:
    app = _app(chatbot)
    parches = [
        patch(
            "server.app.modules.agents_hub.services.turno_de_chat.GraphFactory",
            return_value=MagicMock(build=AsyncMock(return_value=grafo)),
        ),
        patch("server.app.modules.agents_hub.services.turno_de_chat.resolve_embedding_service", new_callable=AsyncMock),
        patch("server.app.modules.agents_hub.services.turno_de_chat.get_model", new_callable=AsyncMock),
        *extra_patches,
    ]
    for p in parches:
        p.start()
    try:
        with TestClient(app) as cliente:
            with cliente.stream(
                "POST",
                f"/api/v1/hub/chat/{chatbot.id}",
                json={"message": "Quin es el limit dels contractes menors?"},
                headers={"Authorization": f"Bearer {_token()}"},
            ) as respuesta:
                lineas = list(respuesta.iter_lines())
    finally:
        for p in reversed(parches):
            p.stop()
    return _eventos(lineas)


def _trozo(contenido):
    trozo = MagicMock()
    trozo.content = contenido
    return trozo


class TestElContenidoEnBloques:
    """Lo que de verdad devuelve Gemini cuando la respuesta tiene más de una parte."""

    @patch.dict("os.environ", _JWT_ENV)
    def test_should_finish_the_stream_when_the_content_comes_in_blocks(self):
        """El caso medido: 0 interacciones en el asistente agéntico y ningún `done`."""
        eventos = _conversa(
            _chatbot(),
            _grafo_que_emite([_trozo([{"type": "text", "text": "El límit és de "}])]),
        )

        clases = [e for e, _ in eventos]
        assert "done" in clases, f"el flujo termina sin `done`: {clases}"

    @patch.dict("os.environ", _JWT_ENV)
    def test_should_send_the_delta_as_text_and_not_as_a_list(self):
        """Un `delta` que es una lista llega así al cliente y se pinta como un objeto."""
        eventos = _conversa(
            _chatbot(),
            _grafo_que_emite([_trozo([{"type": "text", "text": "15.000 euros"}])]),
        )

        tokens = [p for e, p in eventos if e == "token"]
        assert tokens, f"no ha llegado ningún token: {[e for e, _ in eventos]}"
        for t in tokens:
            assert isinstance(t["delta"], str), f"el delta no es texto: {t['delta']!r}"
        assert "".join(t["delta"] for t in tokens) == "15.000 euros"

    @patch.dict("os.environ", _JWT_ENV)
    def test_should_keep_working_with_plain_string_content(self):
        """Lo que ya funcionaba tiene que seguir igual: `texto_de` de una cadena es la cadena."""
        eventos = _conversa(_chatbot(), _grafo_que_emite([_trozo("15.000 euros")]))

        tokens = [p for e, p in eventos if e == "token"]
        assert "".join(t["delta"] for t in tokens) == "15.000 euros"
        assert "done" in [e for e, _ in eventos]

    @patch.dict("os.environ", _JWT_ENV)
    def test_should_join_text_blocks_and_ignore_the_rest(self):
        """Un bloque que no es texto —una imagen, una llamada a tool— no se cuela en la respuesta."""
        eventos = _conversa(
            _chatbot(),
            _grafo_que_emite(
                [
                    _trozo(
                        [
                            {"type": "text", "text": "quinze mil"},
                            {"type": "image_url", "image_url": "https://x/y.png"},
                        ]
                    )
                ]
            ),
        )

        tokens = [p for e, p in eventos if e == "token"]
        assert "".join(t["delta"] for t in tokens) == "quinze mil"


class TestElSilencioDespuesDelBucle:
    """La otra mitad: un fallo tras el grafo no puede quedarse sin decir nada.

    Todo lo que va después del bucle —guardar la interacción, la traza, la cuota, el commit—
    estaba fuera de cualquier `try`. Con eso, cualquier fallo ahí deja al cliente esperando y
    sin forma de distinguirlo de una respuesta lenta.
    """

    @patch.dict("os.environ", _JWT_ENV)
    def test_should_emit_an_error_event_when_the_accounting_fails(self):
        eventos = _conversa(
            _chatbot(),
            _grafo_que_emite([_trozo("15.000 euros")]),
            extra_patches=(
                patch(
                    "server.app.modules.agents_hub.services.turno_de_chat.contabilizar_interaccion",
                    new=AsyncMock(side_effect=RuntimeError("la cuota ha reventado")),
                ),
            ),
        )

        clases = [e for e, _ in eventos]
        assert "error" in clases, (
            f"un fallo después del grafo se queda en silencio: {clases}"
        )

    @patch.dict("os.environ", _JWT_ENV)
    def test_should_not_pretend_it_finished_when_it_did_not(self):
        """No se emite `done` con datos inventados: si no se guardó, no se dice que sí."""
        eventos = _conversa(
            _chatbot(),
            _grafo_que_emite([_trozo("15.000 euros")]),
            extra_patches=(
                patch(
                    "server.app.modules.agents_hub.services.turno_de_chat.contabilizar_interaccion",
                    new=AsyncMock(side_effect=RuntimeError("la cuota ha reventado")),
                ),
            ),
        )

        assert "done" not in [e for e, _ in eventos]


class TestNadieMasLeeElContenidoEnBruto:
    """El guardarraíl de la clase de defecto, que es lo que evita la cuarta mordida.

    `core/llm_text.py` existe desde VER.1 porque el problema ya había mordido en dos sitios, y
    este prompt es el tercero. La forma `response.content if hasattr(...) else str(...)` es
    exactamente la suposición que falla, y no falla donde se escribe.
    """

    def test_should_read_a_model_content_only_through_texto_de(self):
        import re
        from pathlib import Path

        raiz = Path(__file__).resolve().parents[4] / "app"
        # La forma exacta que asume `str`: leer `.content` y caer a `str(...)` del objeto.
        sospechosa = re.compile(r"\.content\s+if\s+hasattr\(")

        encontradas = [
            f"{f.relative_to(raiz).as_posix()}:{n}: {linea.strip()}"
            for f in raiz.rglob("*.py")
            for n, linea in enumerate(f.read_text(encoding="utf-8").splitlines(), 1)
            if sospechosa.search(linea)
        ]

        assert not encontradas, (
            "Estos sitios asumen que el `content` del modelo es una cadena. Gemini lo devuelve "
            "como lista de bloques en cuanto la respuesta tiene más de una parte, y el fallo no "
            "aparece aquí sino más tarde y en otro sitio. Usa `core.llm_text.texto_de`.\n"
            + "\n".join(encontradas)
        )


class TestTextoDeDesenvuelveElMensaje:
    """El contrato que USR.8 amplía: `texto_de` acepta el mensaje, no sólo su `content`.

    Antes recibía el `content`, y los ocho sitios de llamada tenían que desenvolverlo ellos. Lo
    hacían con `X.content if hasattr(X, "content") else str(X)`, que protege del caso raro —que
    no llegue un mensaje— y deja pasar el frecuente: que el `content` sea una lista de bloques.
    Con el desenvoltorio dentro, el sitio de llamada no tiene ocasión de equivocarse.
    """

    def test_should_unwrap_the_content_of_a_message(self):
        from server.app.core.llm_text import texto_de

        assert texto_de(_trozo("15.000 euros")) == "15.000 euros"

    def test_should_unwrap_and_join_blocks_of_a_message(self):
        from server.app.core.llm_text import texto_de

        mensaje = _trozo([{"type": "text", "text": "quinze "}, {"type": "text", "text": "mil"}])
        assert texto_de(mensaje) == "quinze mil"

    def test_should_still_accept_a_bare_content(self):
        """Los sitios que ya pasaban el `content` siguen funcionando: ni `str` ni lista lo tienen."""
        from server.app.core.llm_text import texto_de

        assert texto_de("15.000 euros") == "15.000 euros"
        assert texto_de([{"type": "text", "text": "15.000"}]) == "15.000"
