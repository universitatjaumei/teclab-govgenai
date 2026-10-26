"""Stub API de sincronización Edge.

Deploy: shared

**APER.2 — exige identidad aunque todavía no haga nada.** Las dos rutas estaban registradas sin
**ninguna** dependencia y respondían 501 a cualquiera. El riesgo no era lo que hacen hoy: era que
`GET /edge/config` está diseñado para servir una instantánea de la configuración del cloud y
**nace abierto si nadie mira** el día que alguien la implemente. Con la guarda puesta ahora, no
hay que acordarse entonces — y acordarse es justo lo que falla.

La credencial **definitiva** es de Fase 3: el plan habla de una `edge_api_key` por nodo, que no
existe. Hasta que exista se exige la identidad que ya hay; quien implemente la sync tendrá que
elegir la credencial a conciencia, con la puerta ya cerrada.
"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from server.app.api.deps import get_current_user

# La guarda va en el router entero: una ruta nueva aquí la hereda en vez de estrenarse abierta.
router = APIRouter(
    prefix="/edge", tags=["edge-sync"], dependencies=[Depends(get_current_user)]
)


class EdgeClientOut(BaseModel):
    id: UUID
    name: str
    partner_id: str
    is_active: bool


class EdgeChatbotOut(BaseModel):
    id: UUID
    client_id: UUID
    llm_config_id: UUID
    name: str
    is_active: bool


class EdgeLLMConfigOut(BaseModel):
    id: UUID
    provider: str
    model_name: str
    temperature: float


class EdgePromptTemplateOut(BaseModel):
    id: UUID
    chatbot_id: UUID
    slug: str
    language: str


class EdgeConfigSnapshot(BaseModel):
    clients: list[EdgeClientOut]
    chatbots: list[EdgeChatbotOut]
    llm_configs: list[EdgeLLMConfigOut]
    prompt_templates: list[EdgePromptTemplateOut]
    generated_at: datetime


class EdgeTelemetryBatch(BaseModel):
    edge_node_id: str
    interactions_count: int
    avg_latency_ms: float
    window_start: datetime
    window_end: datetime


@router.get("/config", response_model=EdgeConfigSnapshot)
async def get_edge_config():
    """Obtiene la configuración cloud para sincronizar al edge."""
    raise HTTPException(501, "Not implemented")


@router.post("/telemetry", status_code=202)
async def ingest_edge_telemetry(body: EdgeTelemetryBatch):  # noqa: ARG001 — el contrato se publica antes que la implementación (501)
    """Ingesta telemetría desde un edge node."""
    raise HTTPException(501, "Not implemented")
