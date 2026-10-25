"""VER.4 — `POST /run` contra una sesión real, no mockeada.

Al pulsar «Generar informe» en la pantalla nueva, el endpoint daba **500** con
`MissingGreenlet`: `run_workspace` leía `workspace.status` para el evento de auditoría
**después** de que `start_run` hiciera `commit()`, y con `expire_on_commit` eso dispara una
recarga perezosa síncrona sobre una `AsyncSession` de asyncpg.

Es el mismo patrón que tumbó `create_template` y ocho endpoints de `scripts_router` el
2026-08-14, y por la misma razón no lo cazaba nada: los tests de este endpoint mockean la
sesión con `AsyncMock`, que no reproduce `expire_on_commit`.

Consecuencia real: el 202 nunca llegaba, así que **la tarea de fondo no se encolaba** y el
workspace se quedaba en `drafting` para siempre. Justo lo que VER.1 quiso evitar, entrando
por otra puerta.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from server.app.core.auth.models import UserInfo
from server.app.modules.redaccion.database.models import (
    HubReportTemplate,
    HubReportTemplateVersion,
    HubWorkspace,
)
from server.app.routers.redaccion._actor import user_to_uuid
from server.app.modules.redaccion.services.workspace_run_service import WorkspaceRunService
from server.app.routers.redaccion.workspaces_router import run_workspace

_USUARIO = UserInfo(user_id="1", email="admin@example.local", role="superadmin")


class _Tareas:
    def __init__(self) -> None:
        self.encoladas: list = []

    def add_task(self, funcion, *args, **kwargs) -> None:
        self.encoladas.append((funcion, args))


async def _workspace(session, spec: dict | None = None, inputs: dict | None = None) -> uuid.UUID:
    plantilla = HubReportTemplate(
        name=f"Plantilla {uuid.uuid4().hex[:6]}",
        report_profile="GENERIC_REPORT",
        owner_kind="platform",
    )
    session.add(plantilla)
    await session.flush()

    version = HubReportTemplateVersion(
        template_id=plantilla.id, version=1, spec_json=spec or {}, created_by=uuid.uuid4()
    )
    session.add(version)
    await session.flush()

    workspace = HubWorkspace(
        template_version_id=version.id,
        owner_id=user_to_uuid(_USUARIO.user_id),
        status="draft",
        inputs_json=inputs or {},
    )
    session.add(workspace)
    await session.flush()
    return workspace.id


def _spec_con_slot_obligatorio() -> dict:
    """La forma real de la plantilla que el usuario ejecutó (leída de su `spec_json`)."""
    return {
        "input_contract": {
            "required_slots": [
                {
                    "slot_id": "datos",
                    "kind": "markdown",
                    "label": {"es": "Informe resumen", "ca": "Informe resum", "en": "Summary"},
                }
            ],
            "optional_slots": [],
        }
    }


@pytest.mark.asyncio
async def test_should_approve_a_block_without_a_500(db_url):
    """Las cuatro transiciones —aprobar, rechazar, regenerar, editar— construían la respuesta
    leyendo el bloque **después** del commit, así que devolvían 500 con `MissingGreenlet`: la
    revisión entera era inutilizable. Tercera aparición del mismo patrón en el módulo, y
    tampoco la cazaba nada porque los tests de estos endpoints mockean la sesión.
    """
    from server.app.modules.redaccion.database.models import HubWorkspaceBlock
    from server.app.routers.redaccion.workspaces_router import approve_block

    engine = create_async_engine(db_url)
    try:
        async with AsyncSession(engine) as session:
            workspace_id = await _workspace(session)
            session.add(HubWorkspaceBlock(
                workspace_id=workspace_id,
                block_id="b_resumen",
                kind="AI_ASSISTED_TEXT",
                status="needs_review",
                content_json={"text": "Redactado."},
            ))
            await session.commit()

            salida = await approve_block(
                workspace_id=workspace_id,
                block_id="b_resumen",
                user=_USUARIO,
                session=session,
            )

            assert salida.status == "approved"
            assert salida.content == {"text": "Redactado."}
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_should_actually_persist_the_uploaded_input(db_url):
    """La subida devolvía 200 con la ruta del fichero y `inputs_json` se quedaba **vacío**.

    Mutar el JSONB en sitio y reasignar el mismo objeto no marca la columna como sucia, así
    que SQLAlchemy no emitía UPDATE. Visto en VER.4: la extracción no encontraba el Excel
    que se acababa de subir, y el informe salía sin datos.
    """
    from server.app.routers.redaccion.workspaces_router import upload_workspace_input

    class _FicheroFalso:
        """`read_within_limit` lee por trozos hasta recibir vacío: si siempre devuelve algo,
        cree que el fichero no acaba nunca y lo rechaza por tamaño."""

        filename = "datos.xlsx"

        def __init__(self) -> None:
            self._pendiente = b"contenido"

        async def read(self, *_args, **_kwargs):
            trozo, self._pendiente = self._pendiente, b""
            return trozo

    class _Almacen:
        async def put(self, *_args, **_kwargs):
            return None

    engine = create_async_engine(db_url)
    try:
        async with AsyncSession(engine) as session:
            workspace_id = await _workspace(session)
            await session.commit()

            await upload_workspace_input(
                workspace_id=workspace_id,
                slot_id="datos_excel",
                file=_FicheroFalso(),
                user=_USUARIO,
                session=session,
                storage=_Almacen(),  # type: ignore[arg-type]
            )

            workspace = await session.get(HubWorkspace, workspace_id)
            await session.refresh(workspace)
            assert "datos_excel" in (workspace.inputs_json or {}), (
                "la subida no llegó a la base: el informe se generará sin datos"
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_should_accept_the_run_and_queue_the_generation_against_a_real_session(db_url):
    engine = create_async_engine(db_url)
    try:
        async with AsyncSession(engine) as session:
            workspace_id = await _workspace(session)
            await session.commit()

            tareas = _Tareas()
            salida = await run_workspace(
                workspace_id=workspace_id,
                background_tasks=tareas,
                user=_USUARIO,
                session=session,
                svc=WorkspaceRunService(session=session),
            )

            assert salida.status == "queued"
            assert tareas.encoladas, "sin tarea encolada el informe no se genera nunca"

            workspace = await session.get(HubWorkspace, workspace_id)
            await session.refresh(workspace)
            assert workspace.status == "drafting"
    finally:
        await engine.dispose()


# ─────────────────────────── INF.1 — no ejecutar sin datos ───────────────────────────
#
# En las pruebas humanas del 2026-08-20 el informe se ejecutó **sin fichero**: el usuario pulsó
# el botón que lanza `run` sin pasar por la subida, el endpoint respondió 202, y el diagnóstico
# quedó en tres warnings que sólo se ven volviendo atrás con el navegador. La cascada completa:
# `Required input slot missing: 'datos'` → las dos tablas sin datos → los dos bloques de IA que
# se apoyan en ellas en error → informe bloqueado.
#
# La validación **ya existe** (`WorkspaceRunService.validate_inputs`) y el endpoint la llamaba
# con `validate=False`. Encenderla convierte un fallo silencioso a mitad del grafo en un 422 con
# el nombre del slot que falta, que es lo que la pantalla puede señalar en el campo.


@pytest.mark.asyncio
async def test_should_refuse_to_run_when_a_required_slot_is_missing(db_url):
    """Un `run` sin el slot obligatorio satisfecho responde 422 y dice **cuál** falta."""
    from fastapi import HTTPException

    engine = create_async_engine(db_url)
    try:
        async with AsyncSession(engine) as session:
            workspace_id = await _workspace(session, spec=_spec_con_slot_obligatorio())
            await session.commit()

            tareas = _Tareas()
            with pytest.raises(HTTPException) as fallo:
                await run_workspace(
                    workspace_id=workspace_id,
                    background_tasks=tareas,
                    user=_USUARIO,
                    session=session,
                    svc=WorkspaceRunService(session=session),
                )

            assert fallo.value.status_code == 422
            assert "datos" in str(fallo.value.detail), (
                "el 422 tiene que nombrar el slot que falta: es lo que la pantalla señala"
            )
            assert not tareas.encoladas, (
                "no se encola un grafo condenado a fallar por falta de datos"
            )

            workspace = await session.get(HubWorkspace, workspace_id)
            await session.refresh(workspace)
            assert workspace.status == "draft", (
                "un run rechazado no deja el workspace en 'drafting': ahí se queda colgado"
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_should_run_when_the_required_slot_is_satisfied(db_url):
    """Con el slot subido, el mismo workspace arranca. La guarda no puede cerrar el caso bueno."""
    engine = create_async_engine(db_url)
    try:
        async with AsyncSession(engine) as session:
            workspace_id = await _workspace(
                session,
                spec=_spec_con_slot_obligatorio(),
                inputs={"datos": {"path": "ws/datos.md", "filename": "informe.md"}},
            )
            await session.commit()

            tareas = _Tareas()
            salida = await run_workspace(
                workspace_id=workspace_id,
                background_tasks=tareas,
                user=_USUARIO,
                session=session,
                svc=WorkspaceRunService(session=session),
            )

            assert salida.status == "queued"
            assert tareas.encoladas
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_should_still_run_a_template_without_required_slots(db_url):
    """Una plantilla que no pide nada sigue ejecutándose: la guarda mira el contrato, no adivina."""
    engine = create_async_engine(db_url)
    try:
        async with AsyncSession(engine) as session:
            workspace_id = await _workspace(
                session,
                spec={"input_contract": {"required_slots": [], "optional_slots": []}},
            )
            await session.commit()

            tareas = _Tareas()
            salida = await run_workspace(
                workspace_id=workspace_id,
                background_tasks=tareas,
                user=_USUARIO,
                session=session,
                svc=WorkspaceRunService(session=session),
            )

            assert salida.status == "queued"
            assert tareas.encoladas
    finally:
        await engine.dispose()
