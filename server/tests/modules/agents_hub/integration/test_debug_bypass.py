"""Tests RAG.11 — el prompt final que se habría enviado, sin llamar al LLM.

Para qué sirve: cuando una respuesta sale mal, la pregunta es casi siempre «¿qué contexto
recibió el modelo?». Hoy eso solo se puede contestar leyendo trazas de Langfuse o
reproduciendo la consulta a mano. El bypass ejecuta el pipeline entero —idioma, reescritura,
recuperación, gate, empaquetado— y **se detiene justo antes de invocar**, devolviendo lo que
se iba a mandar. Cero tokens.

Tres decisiones que estos tests fijan:

- **Cero invocaciones al LLM**, comprobado con un espía que cuenta. Un bypass que llama al
  modelo «solo para una cosa» deja de ser gratis y deja de ser inspección.
- **El gate informa, no desvía.** Fuera del bypass, una puntuación baja manda al fallback;
  aquí eso dejaría sin prompt que enseñar justo en el caso que se quiere depurar.
- **No persiste `HubInteraction`.** Es inspección, no conversación, y ensuciaría las
  métricas de uso con consultas de depuración.
"""
from __future__ import annotations

import uuid

import pytest

from server.tests.dobles import completar_chatbot

# SEC.2: el chat y la ingesta exigen que el principal gestione la organizacion del
# chatbot. Estos tests prueban otra cosa, asi que doble y token comparten organizacion;
# la tenencia tiene su propio gate en `tests/api/test_tenant_isolation.py`.
ORG_PRUEBA = "00000000-0000-0000-0000-00000000dead"


class _LLMEspia:
    def __init__(self) -> None:
        self.invocaciones = 0

    async def ainvoke(self, mensajes, **kwargs):
        self.invocaciones += 1

        class _R:
            content = "no deberia haberse llamado"

        return _R()


def _grafo(*, llm, quality_threshold: float = 0.0, items=None):
    from server.app.modules.agents_hub.agent.public_graphs.core.config_resolver import (
        PublicGraphConfig,
    )
    from server.app.modules.agents_hub.agent.public_graphs.core.core_graph import CoreGraph
    from server.app.modules.agents_hub.agent.public_graphs.strategies.protocols import (
        RetrievalOutput,
    )
    from server.app.modules.agents_hub.agent.public_graphs.strategies.retrieval_contract import (
        EvidenceItem,
    )

    evidencias = items if items is not None else [
        EvidenceItem(
            source_id=str(uuid.uuid4()),
            content="L'import de la dieta per dia complet es de 53,34 euros.",
            source_url="https://www.uji.es/REG-020",
            title="Reglament de dietes",
            score=0.9,
        )
    ]

    class _Retrieval:
        async def retrieve(self, query, chatbot_id, cfg, deps, language=None):
            from server.app.modules.agents_hub.agent.public_graphs.strategies.protocols import (
                RetrievalResult,
            )

            return RetrievalOutput(
                buckets=[RetrievalResult(items=evidencias, debug={"dropped_count": 3})]
            )

    class _Merge:
        def merge(self, output):
            return [i for b in output.buckets for i in b.items]

    class _Template:
        def build_prompt_context(self, items, language, query):
            return f"SYSTEM con {len(items)} evidencias"

    class _Language:
        def detect(self, query):
            return "ca"

        def filter_items(self, language, items):
            return items

        def should_warn_translation(self, a, b):
            return False

    cfg = PublicGraphConfig(
        profile="PUBLIC_KB_RICH", retrieval_mode="RAG", language_mode="prefer",
        quality_threshold=quality_threshold, min_retrieval_results=1,
        min_retrieval_score=0.0, reranker_enabled=False, answer_template="generic",
    )
    return CoreGraph(
        retrieval_strategy=_Retrieval(), merge_strategy=_Merge(),
        template_strategy=_Template(), language_policy=_Language(),
        cfg=cfg, deps=object(), llm=llm,
    )


class TestBypassEnElGrafo:

    @pytest.mark.asyncio
    async def test_should_return_final_prompt_without_calling_llm(self):
        llm = _LLMEspia()
        estado = await _grafo(llm=llm).run(
            "quant cobro de dieta?", str(uuid.uuid4()), debug_bypass=True
        )

        assert llm.invocaciones == 0, "el bypass invocó al modelo"
        bypass = estado["bypass"]
        assert bypass["system_prompt"].startswith("SYSTEM con")
        assert [m["role"] for m in bypass["messages"]] == ["system", "user"]
        assert bypass["messages"][1]["content"] == "quant cobro de dieta?"

    @pytest.mark.asyncio
    async def test_should_include_packed_context_and_sources(self):
        estado = await _grafo(llm=_LLMEspia()).run(
            "quant cobro?", str(uuid.uuid4()), debug_bypass=True
        )

        bypass = estado["bypass"]
        assert bypass["packed_context"]["dropped_count"] == 3
        assert len(bypass["packed_context"]["evidencias"]) == 1
        assert bypass["sources"][0]["url"] == "https://www.uji.es/REG-020"

    @pytest.mark.asyncio
    async def test_should_include_resolved_config_snapshot(self):
        """La cascada resuelta, que es la mitad de las veces la explicación del problema."""
        estado = await _grafo(llm=_LLMEspia()).run(
            "quant cobro?", str(uuid.uuid4()), debug_bypass=True
        )

        resuelta = estado["bypass"]["resolved_config"]
        assert resuelta["retrieval_mode"] == "RAG"
        assert resuelta["answer_template"] == "generic"
        assert "context_token_budget" in resuelta

    @pytest.mark.asyncio
    async def test_should_include_rewritten_query_when_rewriting_enabled(self):
        from server.app.modules.agents_hub.agent.public_graphs.core.config_resolver import (
            PublicGraphConfig,
        )

        class _LLMReescritor:
            async def ainvoke(self, mensajes, **kwargs):
                class _R:
                    content = "import de la dieta a l'estranger"

                return _R()

        grafo = _grafo(llm=_LLMEspia())
        grafo.cfg = PublicGraphConfig(
            **{**vars(grafo.cfg), "query_rewriting_enabled": True}
        )
        grafo.rewrite_llm = _LLMReescritor()

        estado = await grafo.run(
            "i si és a l'estranger?", str(uuid.uuid4()),
            history=["usuario: quant cobro de dieta?", "asistente: 53,34 euros."],
            debug_bypass=True,
        )

        assert estado["bypass"]["rewritten_query"] == "import de la dieta a l'estranger"

    @pytest.mark.asyncio
    async def test_should_report_quality_gate_result_without_diverting(self):
        """El gate informa; no manda al fallback. Si desviara, el caso que más interesa
        depurar —puntuación baja— sería justo el que no enseña ningún prompt."""
        grafo = _grafo(llm=_LLMEspia(), quality_threshold=0.99)

        estado = await grafo.run("quant cobro?", str(uuid.uuid4()), debug_bypass=True)

        assert estado["bypass"]["quality_gate"]["passed"] is False
        assert estado["bypass"]["quality_gate"]["score"] < 0.99
        assert estado["bypass"]["system_prompt"], "sin prompt no hay nada que depurar"

    @pytest.mark.asyncio
    async def test_should_behave_normally_when_bypass_is_off(self):
        llm = _LLMEspia()
        estado = await _grafo(llm=llm).run("quant cobro?", str(uuid.uuid4()))

        assert llm.invocaciones == 1
        assert estado.get("bypass") is None


class TestGateDeAcceso:
    """Quién puede pedirlo. El widget público NUNCA, y por eso el gate no es `require_role`
    a secas: hay dos clases de principal —sesión humana y PAT— y cada una se comprueba de
    una manera."""

    def test_should_register_the_new_scope_in_the_catalog(self):
        from server.app.core.auth.pat.scopes import ALL_SCOPES, CHAT_DEBUG

        assert CHAT_DEBUG == "chat:debug"
        assert CHAT_DEBUG in ALL_SCOPES

    def test_should_allow_an_admin_session(self):
        from types import SimpleNamespace

        from server.app.api.v1.hub_chat import puede_depurar

        peticion = SimpleNamespace(state=SimpleNamespace(pat_scopes=None))
        admin = SimpleNamespace(role="admin")

        assert puede_depurar(peticion, admin) is True

    def test_should_reject_a_plain_user_session(self):
        from types import SimpleNamespace

        from server.app.api.v1.hub_chat import puede_depurar

        peticion = SimpleNamespace(state=SimpleNamespace(pat_scopes=None))

        assert puede_depurar(peticion, SimpleNamespace(role="user")) is False

    def test_should_require_the_scope_on_a_pat(self):
        """Un PAT no hereda el permiso de su emisor: lo lleva o no lo lleva."""
        from types import SimpleNamespace

        from server.app.api.v1.hub_chat import puede_depurar

        admin = SimpleNamespace(role="admin")
        con = SimpleNamespace(state=SimpleNamespace(pat_scopes=["chat:test", "chat:debug"]))
        sin = SimpleNamespace(state=SimpleNamespace(pat_scopes=["chat:test"]))

        assert puede_depurar(con, admin) is True
        assert puede_depurar(sin, admin) is False


class TestEndpointDeBypass:

    def _cliente(self, chatbot, rol="admin"):
        # Los campos de configuracion del doble salen del ORM (`tests/dobles.py`):
        # un MagicMock inventa un valor por cada columna nueva, y eso ya rompio
        # estos tests tres veces —SEC.2.1, SEC.4 y SEC.4.1—.
        completar_chatbot(chatbot)

        # SEC.4: y las cuotas. Un `MagicMock(spec=HubChatbot)` inventa un numero
        # para cada columna nueva, asi que sin esto la peticion se va en 429.
        chatbot.user_daily_token_quota = None
        chatbot.chatbot_daily_token_quota = None
        chatbot.anon_ip_daily_token_quota = None
        from unittest.mock import AsyncMock, MagicMock

        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from sqlalchemy.ext.asyncio import AsyncSession

        from server.app.api.deps import get_current_user
        from server.app.api.v1.hub_chat import router as chat_router
        from server.app.core.auth.models import UserInfo
        from server.app.api.deps import get_session

        session = AsyncMock(spec=AsyncSession)
        resultado = MagicMock()
        resultado.scalar_one_or_none = MagicMock(return_value=chatbot)
        session.execute = AsyncMock(return_value=resultado)
        # SEC.4: la organización se lee para la cascada de cuotas; `None` = sin cuotas
        # heredadas. Con el doble por defecto, los límites serían números inventados.
        session.get = AsyncMock(return_value=None)
        session.add = MagicMock()
        session.commit = AsyncMock()

        async def _sesion():
            yield session

        from server.app.api.deps import get_current_user_optional

        principal = UserInfo(
            user_id="u1", email="u@test.com", role=rol, organizacion_ids=(ORG_PRUEBA,)
        )

        app = FastAPI()
        app.dependency_overrides[get_session] = _sesion
        app.dependency_overrides[get_current_user] = lambda: principal
        # SEC.8.5: el chat admite sesión o credencial de sitio, así que depende de la
        # variante opcional; sin doblarla, la petición muere en un 401 antes de llegar al
        # bypass, que es lo que estos tests miden.
        app.dependency_overrides[get_current_user_optional] = lambda: principal
        app.include_router(chat_router, prefix="/api/v1")
        return TestClient(app, raise_server_exceptions=False), session

    def test_should_reject_bypass_for_non_admin_without_scope(self):
        from unittest.mock import MagicMock

        from server.app.modules.agents_hub.database.config_models import HubChatbot

        chatbot = MagicMock(spec=HubChatbot)

        chatbot.organizacion_id = uuid.UUID(ORG_PRUEBA)
        chatbot.id = uuid.uuid4()
        cliente, _ = self._cliente(chatbot, rol="user")

        resp = cliente.post(
            f"/api/v1/hub/chat/{chatbot.id}",
            json={"message": "hola", "debug_bypass": True},
        )

        assert resp.status_code == 403

    def test_should_not_persist_interaction_on_bypass(self):
        from unittest.mock import AsyncMock, MagicMock, patch

        from server.app.modules.agents_hub.database.config_models import HubChatbot
        from server.app.modules.agents_hub.database.operational_models import HubInteraction

        chatbot = MagicMock(spec=HubChatbot)

        chatbot.organizacion_id = uuid.UUID(ORG_PRUEBA)
        chatbot.id = uuid.uuid4()
        cliente, session = self._cliente(chatbot)

        grafo = MagicMock()
        grafo.cfg = MagicMock()
        compilado = MagicMock()
        compilado.ainvoke = AsyncMock(return_value={"bypass": {"system_prompt": "S"}})
        grafo.compile = MagicMock(return_value=compilado)

        with patch(
            "server.app.api.v1.hub_chat.GraphFactory",
            return_value=MagicMock(build=AsyncMock(return_value=grafo)),
        ), patch(
            "server.app.api.v1.hub_chat.resolve_embedding_service", new_callable=AsyncMock
        ), patch(
            "server.app.api.v1.hub_chat.assert_embedding_space_matches",
            new_callable=AsyncMock,
        ), patch("server.app.api.v1.hub_chat.get_model", new_callable=AsyncMock):
            resp = cliente.post(
                f"/api/v1/hub/chat/{chatbot.id}",
                json={"message": "hola", "debug_bypass": True},
            )

        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/json"), (
            "el bypass responde JSON, no SSE: no hay nada que transmitir en trozos"
        )
        assert resp.json()["system_prompt"] == "S"
        persistidas = [
            c.args[0] for c in session.add.call_args_list
            if isinstance(c.args[0], HubInteraction)
        ]
        assert persistidas == [], "el bypass es inspección, no conversación"
