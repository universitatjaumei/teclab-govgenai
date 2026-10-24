"""Tests RAG.13 — escenarios de prueba con veredicto humano.

El hueco que cubre: hoy, comprobar que un cambio del retriever no ha empeorado las
respuestas se hace escribiendo la misma pregunta a mano en el widget y leyendo. No queda
registro, así que no se puede comparar con la vez anterior, y el que revisa no es
necesariamente quien tocó el código.

El dorado de RAG.1 mide **recuperación** con métricas automáticas; esto mide **respuesta**
con juicio humano, que es lo que ninguna métrica sustituye en un asistente normativo. Son
complementarios, no alternativos.

Un detalle que estos tests fijan: **el escenario se ejecuta por el pipeline real, con LLM**.
Un escenario que corriera por un camino de pruebas mediría ese camino, no el producto.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


async def _chatbot(session):
    """Un chatbot nuevo. El nombre es único en la tabla, así que se desambigua aquí:
    los tests de aislamiento necesitan DOS y el helper compartido siempre los llama igual."""
    from server.tests.modules.agents_hub.integration.test_embedding_resolution import (
        _organizacion_y_chatbot,
    )

    _, chatbot = await _organizacion_y_chatbot(session)
    chatbot.name = f"Bot {uuid.uuid4().hex[:8]}"
    await session.flush()
    return chatbot


class TestModeloDeEscenarios:

    @pytest.mark.asyncio
    async def test_should_persist_a_scenario_with_history_and_expectation(self, db_session):
        from server.app.modules.agents_hub.database.operational_models import (
            HubTestScenario,
        )

        chatbot = await _chatbot(db_session)
        escenario = HubTestScenario(
            chatbot_id=chatbot.id,
            name="Dieta a l'estranger",
            prompt="i si és a l'estranger?",
            history=["usuario: quant cobro de dieta?", "asistente: 53,34 euros."],
            expectation_note="Debe citar REG-020 y no inventar cuantía.",
            created_by="admin@uji.es",
        )
        db_session.add(escenario)
        await db_session.commit()
        await db_session.refresh(escenario)

        assert escenario.history[0].startswith("usuario:")
        assert escenario.expectation_note
        assert escenario.created_at is not None

    @pytest.mark.asyncio
    async def test_should_allow_a_scenario_without_history(self, db_session):
        from server.app.modules.agents_hub.database.operational_models import (
            HubTestScenario,
        )

        chatbot = await _chatbot(db_session)
        db_session.add(
            HubTestScenario(chatbot_id=chatbot.id, name="Simple", prompt="quant cobro?")
        )
        await db_session.commit()

    @pytest.mark.asyncio
    async def test_should_cascade_runs_when_the_scenario_is_deleted(self, db_session):
        """Un run sin escenario no dice nada: no se puede saber qué se probaba."""
        from sqlalchemy import func, select

        from server.app.modules.agents_hub.database.operational_models import (
            HubTestRun,
            HubTestScenario,
        )

        chatbot = await _chatbot(db_session)
        escenario = HubTestScenario(chatbot_id=chatbot.id, name="X", prompt="p")
        db_session.add(escenario)
        await db_session.flush()
        db_session.add(HubTestRun(scenario_id=escenario.id, answer="r", sources=[]))
        await db_session.commit()

        await db_session.delete(escenario)
        await db_session.commit()

        quedan = await db_session.scalar(select(func.count()).select_from(HubTestRun))
        assert quedan == 0

    @pytest.mark.asyncio
    async def test_should_reject_an_unknown_verdict(self, db_session):
        """Tres valores estables con consumidor en el código: CHECK sí, igual que
        `purpose` en MOD.1 y al contrario que el vocabulario de ámbitos."""
        from sqlalchemy.exc import IntegrityError

        from server.app.modules.agents_hub.database.operational_models import (
            HubTestRun,
            HubTestScenario,
        )

        chatbot = await _chatbot(db_session)
        escenario = HubTestScenario(chatbot_id=chatbot.id, name="X", prompt="p")
        db_session.add(escenario)
        await db_session.flush()
        db_session.add(
            HubTestRun(scenario_id=escenario.id, answer="r", sources=[], verdict="regular")
        )

        with pytest.raises(IntegrityError):
            await db_session.commit()


class TestEndpoints:

    def _cliente(self, session, rol="admin", *orgs):
        """`AsyncClient` + `ASGITransport`, no `TestClient`.

        `TestClient` levanta su propio event loop, y la fixture `db_session` vive en el de
        pytest-asyncio: mezclarlos da un «Future attached to a different loop» que no tiene
        nada que ver con lo que se prueba. Es la misma razón por la que los E2E de chat
        usan este transporte desde el prompt 6.1.
        """
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        from server.app.api.deps import get_current_user
        from server.app.core.auth.models import UserInfo
        from server.app.api.deps import get_session
        from server.app.routers.hub_test_scenarios_router import router

        async def _sesion():
            yield session

        app = FastAPI()
        app.dependency_overrides[get_session] = _sesion
        # SEC.8.1: el router resuelve el chatbot a su organización antes de nada, así que
        # el actor tiene que gestionarla. Se conceden las organizaciones de los chatbots
        # del test en vez de usar un superadministrador: con el comodín, la guarda no se
        # ejercitaría aquí y el aislamiento POR CHATBOT —que es lo que este fichero mide—
        # quedaría probado sobre un actor que se salta la frontera anterior.
        app.dependency_overrides[get_current_user] = lambda: UserInfo(
            user_id="a1",
            email="admin@uji.es",
            role=rol,
            organizacion_ids=tuple(str(o) for o in orgs),
        )
        app.include_router(router, prefix="/api/v1")
        return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    @pytest.mark.asyncio
    async def test_should_crud_scenarios_scoped_by_chatbot(self, db_session):
        """El aislamiento por chatbot no es cosmético: dos chatbots de organizaciones
        distintas comparten tabla."""
        chatbot_a = await _chatbot(db_session)
        chatbot_b = await _chatbot(db_session)
        await db_session.commit()

        # Las DOS organizaciones: el actor puede llegar a los dos chatbots, así que lo que
        # este test mide sigue siendo el aislamiento por chatbot y no el de organización.
        cliente = self._cliente(
            db_session, "admin", chatbot_a.organizacion_id, chatbot_b.organizacion_id
        )

        creado = await cliente.post(
            f"/api/v1/hub/chatbots/{chatbot_a.id}/test-scenarios",
            json={"name": "Dieta", "prompt": "quant cobro?"},
        )
        assert creado.status_code == 201, creado.text
        assert creado.json()["created_by"] == "admin@uji.es"

        assert len((await cliente.get(
            f"/api/v1/hub/chatbots/{chatbot_a.id}/test-scenarios"
        )).json()) == 1
        assert (await cliente.get(
            f"/api/v1/hub/chatbots/{chatbot_b.id}/test-scenarios"
        )).json() == []

        escenario_id = creado.json()["id"]
        editado = await cliente.patch(
            f"/api/v1/hub/chatbots/{chatbot_a.id}/test-scenarios/{escenario_id}",
            json={"expectation_note": "Debe citar REG-020."},
        )
        assert editado.status_code == 200
        assert editado.json()["expectation_note"] == "Debe citar REG-020."

        # El aislamiento se comprueba también por el camino que más se olvida: pedir el
        # recurso de otro chatbot por su id devuelve 404, no el recurso.
        assert (await cliente.patch(
            f"/api/v1/hub/chatbots/{chatbot_b.id}/test-scenarios/{escenario_id}",
            json={"name": "robado"},
        )).status_code == 404

        assert (await cliente.delete(
            f"/api/v1/hub/chatbots/{chatbot_a.id}/test-scenarios/{escenario_id}"
        )).status_code == 204

    @pytest.mark.asyncio
    async def test_should_reject_access_without_admin_role(self, db_session):
        chatbot = await _chatbot(db_session)
        await db_session.commit()

        cliente = self._cliente(db_session, "user", chatbot.organizacion_id)

        assert (await cliente.get(
            f"/api/v1/hub/chatbots/{chatbot.id}/test-scenarios"
        )).status_code == 403

    @pytest.mark.asyncio
    async def test_should_execute_scenario_through_real_pipeline(self, db_session):
        """Por el CoreGraph completo, LLM incluido. Un camino de pruebas mediría el camino."""
        from server.app.modules.agents_hub.database.operational_models import (
            HubTestScenario,
        )

        chatbot = await _chatbot(db_session)
        escenario = HubTestScenario(
            chatbot_id=chatbot.id, name="Dieta", prompt="quant cobro de dieta?",
            history=["usuario: hola", "asistente: bon dia"],
        )
        db_session.add(escenario)
        await db_session.commit()

        grafo = MagicMock()
        compilado = MagicMock()
        compilado.ainvoke = AsyncMock(return_value={
            "answer": "L'import és de 53,34 euros. [Reglament](https://www.uji.es/REG-020)",
            "sources": [],
            "bypass": None,
        })
        grafo.compile = MagicMock(return_value=compilado)

        cliente = self._cliente(db_session, "admin", chatbot.organizacion_id)
        with patch(
            "server.app.routers.hub_test_scenarios_router.GraphFactory",
            return_value=MagicMock(build=AsyncMock(return_value=grafo)),
        ), patch(
            "server.app.routers.hub_test_scenarios_router.resolve_embedding_service",
            new_callable=AsyncMock,
        ), patch(
            "server.app.routers.hub_test_scenarios_router.get_model", new_callable=AsyncMock
        ):
            resp = await cliente.post(
                f"/api/v1/hub/chatbots/{chatbot.id}/test-scenarios/{escenario.id}/run"
            )

        assert resp.status_code == 201, resp.text
        assert "53,34" in resp.json()["answer"]
        assert resp.json()["verdict"] is None
        assert resp.json()["bypass_snapshot"] is None
        # El historial del escenario llega al grafo: si no, un escenario conversacional
        # probaría otra cosa que la que declara.
        estado = compilado.ainvoke.call_args.args[0]
        assert estado["history"] == ["usuario: hola", "asistente: bon dia"]
        assert estado["debug_bypass"] is False

    @pytest.mark.asyncio
    async def test_should_capture_bypass_snapshot_when_requested(self, db_session):
        """Reutiliza RAG.11: el contexto capturado sale del mismo sitio que el bypass."""
        from server.app.modules.agents_hub.database.operational_models import (
            HubTestScenario,
        )

        chatbot = await _chatbot(db_session)
        escenario = HubTestScenario(chatbot_id=chatbot.id, name="X", prompt="p")
        db_session.add(escenario)
        await db_session.commit()

        grafo = MagicMock()
        compilado = MagicMock()
        compilado.ainvoke = AsyncMock(return_value={
            "answer": "respuesta",
            "sources": [],
            "bypass": {"system_prompt": "SYSTEM", "quality_gate": {"score": 0.8}},
        })
        grafo.compile = MagicMock(return_value=compilado)

        cliente = self._cliente(db_session, "admin", chatbot.organizacion_id)
        with patch(
            "server.app.routers.hub_test_scenarios_router.GraphFactory",
            return_value=MagicMock(build=AsyncMock(return_value=grafo)),
        ), patch(
            "server.app.routers.hub_test_scenarios_router.resolve_embedding_service",
            new_callable=AsyncMock,
        ), patch(
            "server.app.routers.hub_test_scenarios_router.get_model", new_callable=AsyncMock
        ):
            resp = await cliente.post(
                f"/api/v1/hub/chatbots/{chatbot.id}/test-scenarios/{escenario.id}"
                "/run?capture_context=true"
            )

        assert resp.status_code == 201
        assert resp.json()["bypass_snapshot"]["system_prompt"] == "SYSTEM"
        # Sigue habiendo respuesta: capturar el contexto NO convierte esto en un bypass.
        assert resp.json()["answer"] == "respuesta"

    @pytest.mark.asyncio
    async def test_should_record_human_verdict_on_run(self, db_session):
        from server.app.modules.agents_hub.database.operational_models import (
            HubTestRun,
            HubTestScenario,
        )

        chatbot = await _chatbot(db_session)
        escenario = HubTestScenario(chatbot_id=chatbot.id, name="X", prompt="p")
        db_session.add(escenario)
        await db_session.flush()
        run = HubTestRun(scenario_id=escenario.id, answer="r", sources=[])
        db_session.add(run)
        await db_session.commit()

        cliente = self._cliente(db_session, "admin", chatbot.organizacion_id)
        resp = await cliente.patch(
            f"/api/v1/hub/chatbots/{chatbot.id}/test-scenarios/runs/{run.id}/verdict",
            json={"verdict": "mixed", "verdict_note": "Cita bien pero se enrolla."},
        )

        assert resp.status_code == 200
        assert resp.json()["verdict"] == "mixed"
        assert resp.json()["verdict_by"] == "admin@uji.es"

    @pytest.mark.asyncio
    async def test_should_list_runs_newest_first(self, db_session):
        """El historial se lee de arriba abajo: lo último ejecutado va primero."""
        from datetime import datetime, timedelta, timezone

        from server.app.modules.agents_hub.database.operational_models import (
            HubTestRun,
            HubTestScenario,
        )

        chatbot = await _chatbot(db_session)
        escenario = HubTestScenario(chatbot_id=chatbot.id, name="X", prompt="p")
        db_session.add(escenario)
        await db_session.flush()
        ahora = datetime.now(timezone.utc)
        db_session.add_all([
            HubTestRun(scenario_id=escenario.id, answer="vieja", sources=[],
                       executed_at=ahora - timedelta(hours=2)),
            HubTestRun(scenario_id=escenario.id, answer="nueva", sources=[],
                       executed_at=ahora),
        ])
        await db_session.commit()

        cliente = self._cliente(db_session, "admin", chatbot.organizacion_id)
        runs = (await cliente.get(
            f"/api/v1/hub/chatbots/{chatbot.id}/test-scenarios/{escenario.id}/runs"
        )).json()

        assert [r["answer"] for r in runs] == ["nueva", "vieja"]


class TestFronteraEdgeCloud:

    def test_the_router_declares_and_registers_as_edge(self):
        """CLAUDE.md: un router nuevo se etiqueta en su docstring y se registra en la
        función que le toca. Sin esto, el despliegue edge se queda sin la funcionalidad y
        nadie se entera hasta que falla en el cliente."""
        import inspect

        from server.app import main
        from server.app.routers import hub_test_scenarios_router

        assert "Deploy: edge" in (hub_test_scenarios_router.__doc__ or "")
        fuente = inspect.getsource(main._register_edge)
        assert "test_scenarios_router" in fuente
        assert "test_scenarios_router" not in inspect.getsource(main._register_cloud)
