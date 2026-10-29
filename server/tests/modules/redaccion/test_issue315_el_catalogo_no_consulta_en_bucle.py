"""#315 — el catálogo de funciones y su cola de revisión no consultan una vez por fila.

`GET /funciones` pedía las versiones de cada función por separado, y `GET /funciones/revision`
leía **todas** las versiones de plantilla con un `LIKE` por cada versión de la cola. Lo encontró la
revisión de la PR #314. El test no fija cuántas consultas hay: fija que **no crecen** con el catálogo.
"""
from __future__ import annotations

import uuid
from contextlib import contextmanager

import pytest
from sqlalchemy import event

from server.app.modules.redaccion.database.models import (
    HubReportTemplate,
    HubReportTemplateVersion,
)
from server.tests.modules.redaccion.test_fun4_la_cola_por_la_interfaz import (
    _cola_de_revision,
    _listar_funciones,
    _principal,
    _una_funcion,
)


@contextmanager
def _contando(session):
    sentencias: list[str] = []

    def _anota(_conn, _cursor, sentencia, *_args):
        sentencias.append(sentencia)

    motor = session.bind.sync_engine
    event.listen(motor, "before_cursor_execute", _anota)
    try:
        yield sentencias
    finally:
        event.remove(motor, "before_cursor_execute", _anota)


async def _catalogo_de(session, cuantas: int) -> uuid.UUID:
    organizacion = uuid.uuid4()
    for i in range(cuantas):
        funcion, _ = await _una_funcion(
            session, organizacion=organizacion, autor=uuid.uuid4(), nombre=f"Función {i}"
        )
        plantilla = HubReportTemplate(
            name=f"Usa la {i}", report_profile="GENERIC_REPORT", owner_kind="platform"
        )
        session.add(plantilla)
        await session.flush()
        session.add(
            HubReportTemplateVersion(
                template_id=plantilla.id, version=1, created_by=uuid.uuid4(),
                spec_json={
                    "blocks": [
                        {
                            "id": "b1",
                            "kind": "DETERMINISTIC_DATA",
                            "funcion_ref": {"funcion_id": str(funcion.id), "version": 1},
                        }
                    ]
                },
            )
        )
    await session.commit()
    return organizacion


async def _consultas_al_listar(session, cuantas: int) -> int:
    organizacion = await _catalogo_de(session, cuantas)
    principal = _principal(organizacion=organizacion, admin=True)
    with _contando(session) as sentencias:
        vistas = await _listar_funciones(principal=principal, session=session)
    assert len([v for v in vistas if v.organizacion_id == organizacion]) == cuantas
    return len(sentencias)


async def _consultas_en_la_cola(session, cuantas: int) -> int:
    organizacion = await _catalogo_de(session, cuantas)
    principal = _principal(organizacion=organizacion, admin=True)
    with _contando(session) as sentencias:
        cola = await _cola_de_revision(
            estado="sin_revisar", muestra=None, principal=principal, session=session
        )
    assert len(cola) == cuantas
    assert all(fila.plantillas_que_la_usan == 1 for fila in cola)
    return len(sentencias)


@pytest.mark.asyncio
async def test_should_list_the_catalogue_with_the_same_queries_whatever_its_size(db_session):
    assert await _consultas_al_listar(db_session, 2) == await _consultas_al_listar(db_session, 5)


@pytest.mark.asyncio
async def test_should_count_the_templates_of_the_queue_with_the_same_queries_whatever_its_size(
    db_session,
):
    assert await _consultas_en_la_cola(db_session, 2) == await _consultas_en_la_cola(db_session, 5)
