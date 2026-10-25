"""PRO.6 — el copiloto, cableado y con el índice al primer uso.

`CopilotService` responde sobre la documentación interna con citas y traduce lenguaje natural a
configuración, y estaba **inalcanzable por los dos lados**: el endpoint devolvía 503 con un
stub y su panel colgaba de un layout que ninguna ruta montaba.

Lo medido antes de escribir: `DocsRetriever` indexa `docs/**/*.md` en memoria y sin persistir
—46 ficheros, 465 KB, ~387 fragmentos—, o sea **387 llamadas de embedding por índice**. Pagar
eso al arrancar es un coste que casi nunca se aprovecha, y en modo edge con embeddings locales
retrasa el arranque de la aplicación. Se construye **al primer uso**, y una sola vez.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from server.app.core.auth.models import UserInfo


class _EmbeddingDeMentira:
    """Cuenta llamadas para poder afirmar que el índice se construye una vez."""

    def __init__(self, *, con_lote: bool = False) -> None:
        self.llamadas = 0
        self.lotes = 0
        self._con_lote = con_lote

    async def embed(self, text: str, purpose: str = "query") -> list[float]:
        self.llamadas += 1
        return [float(len(text) % 7), 1.0, 0.5]

    if True:  # el método existe sólo si se pide, para probar las dos ramas
        async def embed_batch(
            self, texts: list[str], purpose: str = "document"
        ) -> list[list[float]]:
            if not self._con_lote:
                raise AttributeError("este doble no admite lotes")
            self.lotes += 1
            self.llamadas += len(texts)
            return [[float(len(t) % 7), 1.0, 0.5] for t in texts]


class _ModeloDeMentira:
    def __init__(self) -> None:
        self.preguntas: list[str] = []

    async def ainvoke(self, messages):
        self.preguntas.append(str(messages)[-200:])

        class _R:
            content = "Según la documentación, el corpus se ingiere en Markdown."

        return _R()


@pytest.fixture
def docs(tmp_path: Path) -> Path:
    (tmp_path / "CONTRATO.md").write_text(
        "# Contrato del corpus\n\nAl corpus solo entra Markdown conforme al contrato.\n",
        encoding="utf-8",
    )
    (tmp_path / "OTRO.md").write_text(
        "# Otro documento\n\nEsto habla de despliegue en una VM.\n", encoding="utf-8"
    )
    return tmp_path


pytestmark = pytest.mark.asyncio


class TestIndiceAlPrimerUso:
    async def test_should_indexar_en_la_primera_pregunta_y_no_en_la_segunda(
        self, docs: Path
    ) -> None:
        from server.app.modules.redaccion.services.copilot.docs_retriever import DocsRetriever

        embedding = _EmbeddingDeMentira()
        retriever = DocsRetriever(embedding_service=embedding, docs_dir=docs)

        assert retriever.chunks == [], "no se indexa al construirlo"

        await retriever.retrieve("¿qué entra al corpus?")
        tras_la_primera = embedding.llamadas
        assert tras_la_primera > 1, "la primera pregunta construye el índice"
        assert retriever.chunks

        await retriever.retrieve("¿y el despliegue?")
        # Sólo la consulta nueva: un embedding más, no el índice entero otra vez.
        assert embedding.llamadas == tras_la_primera + 1

    async def test_should_usar_el_lote_si_el_servicio_lo_admite(self, docs: Path) -> None:
        """387 llamadas de una en una son minutos; en lote, una.

        La primera pregunta del copiloto es la que paga el índice: si tarda cinco minutos,
        nadie la hace dos veces.
        """
        from server.app.modules.redaccion.services.copilot.docs_retriever import DocsRetriever

        embedding = _EmbeddingDeMentira(con_lote=True)
        await DocsRetriever(embedding_service=embedding, docs_dir=docs).retrieve("corpus")

        assert embedding.lotes >= 1

    async def test_should_funcionar_sin_lote(self, docs: Path) -> None:
        from server.app.modules.redaccion.services.copilot.docs_retriever import DocsRetriever

        embedding = _EmbeddingDeMentira(con_lote=False)
        retriever = DocsRetriever(embedding_service=embedding, docs_dir=embedding and docs)
        resultado = await retriever.retrieve("corpus")

        assert resultado, "sin lotes se embebe de uno en uno, pero se indexa igual"

    async def test_should_no_reintentar_el_indice_cuando_no_hay_documentacion(
        self, tmp_path: Path
    ) -> None:
        """Un directorio vacío no puede hacer que cada pregunta lo recorra otra vez."""
        from server.app.modules.redaccion.services.copilot.docs_retriever import DocsRetriever

        embedding = _EmbeddingDeMentira()
        retriever = DocsRetriever(embedding_service=embedding, docs_dir=tmp_path / "no-existe")

        await retriever.retrieve("algo")
        await retriever.retrieve("otra cosa")

        assert retriever.indexado is True


class TestRespuestaConCitas:
    async def test_should_citar_el_fichero_del_que_sale_la_respuesta(self, docs: Path) -> None:
        from server.app.modules.redaccion.services.copilot.copilot_service import CopilotService
        from server.app.modules.redaccion.services.copilot.docs_retriever import DocsRetriever

        servicio = CopilotService(
            llm=_ModeloDeMentira(),
            retriever=DocsRetriever(
                embedding_service=_EmbeddingDeMentira(), docs_dir=docs
            ),
        )

        respuesta = await servicio.answer(question="¿Qué entra al corpus?")

        assert respuesta.answer
        assert respuesta.source_refs, "una respuesta sin cita no se puede comprobar"
        assert any("CONTRATO.md" in s.path for s in respuesta.source_refs)


@pytest.fixture(autouse=True)
def _sin_indice_heredado(monkeypatch):
    """El retriever se conserva entre peticiones: en tests se parte de cero cada vez."""
    from server.app.routers.redaccion import copilot_router

    monkeypatch.setattr(copilot_router, "_retriever", None, raising=False)


class TestElModuloPrefiereNoExcluye:
    """Visto en el navegador: desde un informe, el copiloto decía «no tengo esa información».

    `_infer_module` clasifica como `redaccion` sólo los ficheros cuya **ruta** contiene
    «redaccion» —en `docs/` hay exactamente uno—, y el filtro era estricto, así que preguntar
    desde un informe dejaba fuera toda la documentación general. Por API, sin módulo, la misma
    pregunta se contestaba y citaba el fichero.
    """

    async def test_should_encontrar_la_documentacion_general_desde_un_modulo(
        self, tmp_path: Path
    ) -> None:
        from server.app.modules.redaccion.services.copilot.docs_retriever import DocsRetriever

        (tmp_path / "DECISION_DESPLIEGUE.md").write_text(
            "# Despliegue\n\nEl destino es una VM, no Cloud Run.\n", encoding="utf-8"
        )
        retriever = DocsRetriever(embedding_service=_EmbeddingDeMentira(), docs_dir=tmp_path)

        encontrado = await retriever.retrieve("¿dónde se despliega?", module="redaccion")

        assert encontrado, "un documento general vale para cualquier módulo"
        assert "DECISION_DESPLIEGUE.md" in encontrado[0].source_path

    async def test_should_dejar_fuera_la_documentacion_de_otro_modulo(
        self, tmp_path: Path
    ) -> None:
        from server.app.modules.redaccion.services.copilot.docs_retriever import DocsRetriever

        (tmp_path / "chatbot_cosas.md").write_text("# Chatbots\n\nDe los bots.\n", encoding="utf-8")
        retriever = DocsRetriever(embedding_service=_EmbeddingDeMentira(), docs_dir=tmp_path)

        assert await retriever.retrieve("bots", module="redaccion") == []


#: MT.3 — el `Depends` resuelve el modelo para la organización de quien pregunta. Al llamarlo a
#: mano hay que darle lo que le daría la inyección; un superadministrador no pertenece a ninguna,
#: así que resuelve el nivel de plataforma, que es lo que este fichero comprueba.
_SIN_ORGANIZACION = UserInfo(
    user_id="1", email="root@uji.es", role="superadmin", organizacion_ids=()
)


class TestLaPuertaDelServicio:
    async def test_should_decir_el_503_que_falta_el_modelo(self, monkeypatch) -> None:
        from fastapi import HTTPException

        from server.app.routers.redaccion import copilot_router

        async def _sin_modelo(*_a, **_k):
            raise ValueError("no hay configuración LLM por defecto para tier 1")

        monkeypatch.setattr(copilot_router, "get_model_for_tier", _sin_modelo)
        monkeypatch.setattr(
            copilot_router, "resolve_embedding_service", _sin_fallar, raising=False
        )

        with pytest.raises(HTTPException) as fallo:
            await copilot_router.get_copilot_service(
            session=object(), current_user=_SIN_ORGANIZACION
        )

        assert fallo.value.status_code == 503
        assert "modelo" in str(fallo.value.detail).lower()

    async def test_should_decir_el_503_que_faltan_los_embeddings(self, monkeypatch) -> None:
        from fastapi import HTTPException

        from server.app.routers.redaccion import copilot_router

        async def _modelo(*_a, **_k):
            return _ModeloDeMentira()

        async def _sin_embeddings(*_a, **_k):
            raise ValueError("no hay configuración de embeddings")

        monkeypatch.setattr(copilot_router, "get_model_for_tier", _modelo)
        monkeypatch.setattr(copilot_router, "resolve_embedding_service", _sin_embeddings)

        with pytest.raises(HTTPException) as fallo:
            await copilot_router.get_copilot_service(
            session=object(), current_user=_SIN_ORGANIZACION
        )

        assert fallo.value.status_code == 503
        assert "embedding" in str(fallo.value.detail).lower()

    async def test_should_construir_el_servicio_cuando_estan_los_dos(self, monkeypatch) -> None:
        from server.app.routers.redaccion import copilot_router

        async def _modelo(*_a, **_k):
            return _ModeloDeMentira()

        async def _embeddings(*_a, **_k):
            return _EmbeddingDeMentira()

        monkeypatch.setattr(copilot_router, "get_model_for_tier", _modelo)
        monkeypatch.setattr(copilot_router, "resolve_embedding_service", _embeddings)

        servicio = await copilot_router.get_copilot_service(
            session=object(), current_user=_SIN_ORGANIZACION
        )
        otro = await copilot_router.get_copilot_service(
            session=object(), current_user=_SIN_ORGANIZACION
        )

        assert servicio is not None
        # El servicio se construye cada vez —así un cambio de modelo en el panel tiene efecto
        # sin reiniciar— pero el índice se conserva, que es lo que cuesta.
        assert servicio is not otro
        assert servicio._retriever is otro._retriever


async def _sin_fallar(*_a, **_k):
    return _EmbeddingDeMentira()
