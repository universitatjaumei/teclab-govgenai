"""Escenarios de prueba de un chatbot y su veredicto humano (RAG.13).

Deploy: edge
Módulo: chatbots — los escenarios miden la calidad de un asistente.

Complementa al dataset dorado de RAG.1, no lo duplica: el dorado mide **recuperación** con
métricas automáticas y bloquea el build; esto mide la **respuesta** con juicio humano, que es
lo que ninguna métrica sustituye en un asistente normativo.

**La ejecución va por el pipeline real, LLM incluido.** Un escenario que corriera por un
camino de pruebas mediría ese camino, no el producto — que es justo lo que hace inútil una
batería de pruebas manuales.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select

from server.app.api.deps import require_role
from server.app.core.auth.models import UserInfo
from server.app.core.auth.tenancy import assert_chatbot_org_access
from server.app.modules.agents_hub.agent.public_graphs.core.graph_factory import GraphFactory
from server.app.modules.agents_hub.agent.public_graphs.strategies.retrieval_pipeline_protocol import (
    GraphDeps,
)
from server.app.api.deps import get_session
from server.app.modules.agents_hub.database.operational_models import (
    HubTestRun,
    HubTestScenario,
)
from server.app.modules.agents_hub.services.config_provider import LocalConfigProvider
from server.app.modules.agents_hub.services.embedding_resolver import (
    resolve_embedding_service,
)
from server.app.modules.agents_hub.services.model_factory import get_model

_require_admin = require_role("superadmin", "admin")


async def _guarda_del_chatbot(
    chatbot_id: uuid.UUID,
    user: UserInfo = Depends(_require_admin),
    session=Depends(get_session),
) -> UserInfo:
    """SEC.8.1: todas las rutas de este router cuelgan de `/{chatbot_id}`, así que la
    pertenencia se comprueba **una vez, en el router**, y no endpoint por endpoint.

    Puesta aquí, cubre también el endpoint que alguien añada mañana. Endpoint por endpoint
    era exactamente la forma del agujero: `run_scenario` ejecutaba el grafo completo contra
    cualquier `chatbot_id` —o sea, devolvía el corpus ajeno— porque exigía rol de admin y
    nunca miró de quién era el chatbot.
    """
    await assert_chatbot_org_access(session, chatbot_id, user)
    return user


router = APIRouter(
    prefix="/hub/chatbots",
    tags=["hub-test-scenarios"],
    dependencies=[Depends(_guarda_del_chatbot)],
)

Verdict = Literal["good", "bad", "mixed"]


class ScenarioCreate(BaseModel):
    name: str
    prompt: str
    history: list[str] | None = None
    expectation_note: str | None = None


class ScenarioUpdate(BaseModel):
    name: str | None = None
    prompt: str | None = None
    history: list[str] | None = None
    expectation_note: str | None = None


class ScenarioRead(BaseModel):
    id: uuid.UUID
    chatbot_id: uuid.UUID
    name: str
    prompt: str
    history: list[str] | None
    expectation_note: str | None
    created_by: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RunRead(BaseModel):
    id: uuid.UUID
    scenario_id: uuid.UUID
    executed_at: datetime
    answer: str
    sources: list
    bypass_snapshot: dict | None
    #: VIS.5 — el aviso de lengua tal y como lo vio quien preguntó, o `None` si no hubo. En el
    #: contrato porque quien revisa una respuesta tiene que ver **lo mismo** que el ciudadano:
    #: sin esto, un aviso que dice algo equivocado no aparece en ninguna herramienta de revisión.
    translation_warning: str | None = None
    #: RES.2 — si la respuesta salió de la segunda búsqueda, con la consulta reformulada. Va en el
    #: contrato porque distingue dos situaciones que no se revisan igual: «el corpus no lo tiene»
    #: y «el corpus lo tiene y la pregunta no lo encontraba tal como se hizo».
    reformulada: bool = False
    reformulated_query: str | None = None
    verdict: Verdict | None
    verdict_note: str | None
    verdict_by: str | None

    model_config = {"from_attributes": True}


class VerdictIn(BaseModel):
    verdict: Verdict
    verdict_note: str | None = None


async def _escenario_o_404(
    session, chatbot_id: uuid.UUID, scenario_id: uuid.UUID
) -> HubTestScenario:
    """Siempre acotado por chatbot_id: dos organizaciones comparten tabla.

    Pedir por id sin el filtro devolvería el escenario de otro chatbot con un 200, que es
    la fuga más fácil de escribir y la más difícil de ver leyendo el código.
    """
    fila = await session.execute(
        select(HubTestScenario)
        .where(HubTestScenario.id == scenario_id)
        .where(HubTestScenario.chatbot_id == chatbot_id)
    )
    escenario = fila.scalar_one_or_none()
    if escenario is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Escenario no encontrado"
        )
    return escenario


@router.get("/{chatbot_id}/test-scenarios", response_model=list[ScenarioRead])
async def list_scenarios(
    chatbot_id: uuid.UUID,
    _: UserInfo = Depends(_require_admin),
    session=Depends(get_session),
):
    fila = await session.execute(
        select(HubTestScenario)
        .where(HubTestScenario.chatbot_id == chatbot_id)
        .order_by(HubTestScenario.created_at.desc())
    )
    return list(fila.scalars().all())


@router.post(
    "/{chatbot_id}/test-scenarios",
    response_model=ScenarioRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_scenario(
    chatbot_id: uuid.UUID,
    body: ScenarioCreate,
    user: UserInfo = Depends(_require_admin),
    session=Depends(get_session),
):
    escenario = HubTestScenario(
        chatbot_id=chatbot_id,
        name=body.name,
        prompt=body.prompt,
        history=body.history,
        expectation_note=body.expectation_note,
        created_by=user.email,
    )
    session.add(escenario)
    await session.commit()
    await session.refresh(escenario)
    return escenario


@router.patch(
    "/{chatbot_id}/test-scenarios/{scenario_id}", response_model=ScenarioRead
)
async def update_scenario(
    chatbot_id: uuid.UUID,
    scenario_id: uuid.UUID,
    body: ScenarioUpdate,
    _: UserInfo = Depends(_require_admin),
    session=Depends(get_session),
):
    escenario = await _escenario_o_404(session, chatbot_id, scenario_id)
    for campo, valor in body.model_dump(exclude_none=True).items():
        setattr(escenario, campo, valor)
    escenario.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(escenario)
    return escenario


@router.delete(
    "/{chatbot_id}/test-scenarios/{scenario_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_scenario(
    chatbot_id: uuid.UUID,
    scenario_id: uuid.UUID,
    _: UserInfo = Depends(_require_admin),
    session=Depends(get_session),
):
    escenario = await _escenario_o_404(session, chatbot_id, scenario_id)
    await session.delete(escenario)
    await session.commit()


@router.get(
    "/{chatbot_id}/test-scenarios/{scenario_id}/runs", response_model=list[RunRead]
)
async def list_runs(
    chatbot_id: uuid.UUID,
    scenario_id: uuid.UUID,
    _: UserInfo = Depends(_require_admin),
    session=Depends(get_session),
):
    await _escenario_o_404(session, chatbot_id, scenario_id)
    fila = await session.execute(
        select(HubTestRun)
        .where(HubTestRun.scenario_id == scenario_id)
        .order_by(HubTestRun.executed_at.desc())
    )
    return list(fila.scalars().all())


@router.post(
    "/{chatbot_id}/test-scenarios/{scenario_id}/run",
    response_model=RunRead,
    status_code=status.HTTP_201_CREATED,
)
async def run_scenario(
    chatbot_id: uuid.UUID,
    scenario_id: uuid.UUID,
    capture_context: bool = Query(
        False,
        description=(
            "Adjunta la captura del bypass (RAG.11): prompt final, contexto empaquetado y "
            "configuración resuelta en el momento de la ejecución."
        ),
    ),
    _: UserInfo = Depends(_require_admin),
    session=Depends(get_session),
):
    """Ejecuta el escenario por el CoreGraph completo y guarda respuesta y fuentes.

    `capture_context` **no** convierte esto en un bypass: se sigue invocando al modelo y se
    sigue guardando la respuesta. Lo que añade es la instantánea, y su valor está en que un
    run de hace un mes se pueda explicar cuando la configuración ya no es la misma.
    """
    escenario = await _escenario_o_404(session, chatbot_id, scenario_id)

    embedding_service = await resolve_embedding_service(session, chatbot_id)
    llm = await get_model(chatbot_id, LocalConfigProvider(session))
    deps = GraphDeps(session=session, embedder=embedding_service, llm=llm)
    grafo = await GraphFactory().build(chatbot_id, deps, llm)

    estado = await grafo.compile().ainvoke({
        "query": escenario.prompt,
        "chatbot_id": str(chatbot_id),
        "language": None,
        "history": list(escenario.history or []),
        "rewritten_query": None,
        # El bypass DETIENE el grafo antes del modelo, así que aquí va siempre en False: un
        # escenario tiene que producir respuesta. `capture_context` compone la misma
        # instantánea SIN detenerlo, que es lo que hace que el contexto guardado sea el que
        # de verdad se envió y no uno recompuesto después, parecido pero no el mismo.
        "debug_bypass": False,
        "capture_context": capture_context,
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
        "context_source_language": None,
        "fallback_reason": None,
        "sources": [],
    })

    # VIS.5 — el mismo aviso que vería quien pregunta, redactado igual. Se construye aquí y no
    # se copia el booleano: lo que hay que poder revisar es **el texto**, que es lo que llega al
    # ciudadano; el flag sólo dice que hubo uno.
    from server.app.modules.agents_hub.services.turno_de_chat import _build_translation_warning

    # La lengua de la pregunta la **detecta el grafo** y vive en el estado como `language`; el
    # escenario no la declara, y pedírsela al autor sería pedirle un dato que el sistema ya sabe
    # sacar del propio texto.
    aviso = (
        _build_translation_warning(
            estado.get("context_source_language"), estado.get("language")
        )
        if estado.get("translation_warning")
        else None
    )

    run = HubTestRun(
        scenario_id=escenario.id,
        answer=estado.get("answer") or "",
        sources=[_serializar(s) for s in (estado.get("sources") or [])],
        bypass_snapshot=estado.get("bypass"),
        translation_warning=aviso,
        # RES.2 — quien revisa tiene que saber si la respuesta salió de la primera búsqueda o de
        # la segunda. Una rescatada reformulando dice algo distinto sobre el corpus: que la
        # información estaba y la pregunta no la encontraba tal como se hizo.
        reformulada=bool(estado.get("reformulada")),
        reformulated_query=estado.get("reformulated_query"),
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return run


@router.patch(
    "/{chatbot_id}/test-scenarios/runs/{run_id}/verdict", response_model=RunRead
)
async def set_verdict(
    chatbot_id: uuid.UUID,
    run_id: uuid.UUID,
    body: VerdictIn,
    user: UserInfo = Depends(_require_admin),
    session=Depends(get_session),
):
    """Registra el veredicto humano. Es el dato que no produce ninguna métrica."""
    fila = await session.execute(
        select(HubTestRun)
        .join(HubTestScenario, HubTestScenario.id == HubTestRun.scenario_id)
        .where(HubTestRun.id == run_id)
        .where(HubTestScenario.chatbot_id == chatbot_id)
    )
    run = fila.scalar_one_or_none()
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Ejecución no encontrada"
        )

    run.verdict = body.verdict
    run.verdict_note = body.verdict_note
    run.verdict_by = user.email
    await session.commit()
    await session.refresh(run)
    return run


def _serializar(source) -> dict:
    """Mismo dialecto doble que el endpoint de chat: EvidenceItem o Source."""
    identificador = getattr(source, "source_id", None) or getattr(source, "document_id", None)
    return {
        "document_id": str(identificador) if identificador else None,
        "title": getattr(source, "title", None),
        "url": getattr(source, "source_url", None) or getattr(source, "url", None),
        "score": getattr(source, "score", None),
    }
