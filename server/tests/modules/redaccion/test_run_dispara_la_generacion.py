"""VER.1 — `POST /run` tiene que disparar la generación, no solo cambiar el estado.

El endpoint transicionaba el workspace a `drafting` y devolvía un `run_id` sintético. El
grafo no se ejecutaba nunca, así que el workspace se quedaba en `drafting` para siempre y en
el panel eso se lee como «va lento».
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from server.app.core.auth.models import UserInfo
from server.app.routers.redaccion.workspaces_router import run_workspace


class _Tareas:
    """Doble de `BackgroundTasks` que se queda con lo que le encolan."""

    def __init__(self) -> None:
        self.encoladas: list[tuple] = []

    def add_task(self, funcion, *args, **kwargs) -> None:
        self.encoladas.append((funcion, args, kwargs))


@pytest.mark.asyncio
async def test_should_queue_the_generation_for_the_workspace():
    workspace_id = uuid.uuid4()

    workspace = MagicMock()
    workspace.status = "draft"
    session = AsyncMock()
    session.get = AsyncMock(return_value=workspace)
    session.add = MagicMock()

    resultado = MagicMock()
    resultado.run_id = uuid.uuid4()
    resultado.status = "queued"

    tareas = _Tareas()

    import server.app.routers.redaccion.workspaces_router as router_modulo

    async def _propietario(*_args, **_kwargs):
        return workspace

    original = router_modulo._get_workspace
    router_modulo._get_workspace = _propietario
    try:
        salida = await run_workspace(
            workspace_id=workspace_id,
            background_tasks=tareas,
            user=UserInfo(user_id="1", email="admin@example.local", role="superadmin"),
            session=session,
            svc=MagicMock(start_run=AsyncMock(return_value=resultado)),
        )
    finally:
        router_modulo._get_workspace = original

    assert salida.status == "queued"
    assert tareas.encoladas, "el endpoint responde 202 y no encola nada: el informe no se genera"
    funcion, args, _ = tareas.encoladas[0]
    assert funcion is router_modulo.generar_borrador_en_segundo_plano
    assert args == (workspace_id,)
