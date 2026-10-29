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


# ── Revisión de la PR #316 ────────────────────────────────────────────────────────────────


async def _plantilla_con(session, *refs) -> None:
    """Una versión de plantilla con un bloque por cada `funcion_ref` dado, tal cual."""
    plantilla = HubReportTemplate(
        name=f"Plantilla {uuid.uuid4()}", report_profile="GENERIC_REPORT", owner_kind="platform"
    )
    session.add(plantilla)
    await session.flush()
    session.add(
        HubReportTemplateVersion(
            template_id=plantilla.id, version=1, created_by=uuid.uuid4(),
            spec_json={
                "blocks": [
                    {"id": f"b{n}", "kind": "DETERMINISTIC_DATA", "funcion_ref": ref}
                    for n, ref in enumerate(refs)
                ]
            },
        )
    )
    await session.commit()


@pytest.mark.asyncio
async def test_a_malformed_anchor_does_not_bring_down_the_queue(db_session):
    """Una versión que no es un número —una lista, editada a mano— no puede tumbar la cola de
    todos los revisores: el contador la ignora y sigue."""
    from server.app.modules.redaccion.funciones_catalogo import plantillas_que_las_usan

    a, b = uuid.uuid4(), uuid.uuid4()
    await _plantilla_con(db_session, {"funcion_id": str(a), "version": [1]})
    await _plantilla_con(db_session, {"funcion_id": str(a), "version": {"v": 1}})
    await _plantilla_con(db_session, {"funcion_id": str(b), "version": 1})

    assert await plantillas_que_las_usan(db_session, [a, b]) == {(b, 1): 1}


@pytest.mark.asyncio
async def test_counts_what_the_block_contract_accepts(db_session):
    """El contador lee el ancla con `FuncionRef`, el mismo contrato que valida el bloque: `1.0`
    es la versión 1 (antes `1.0 == 1` contaba), y una versión 0 no es un ancla."""
    from server.app.modules.redaccion.funciones_catalogo import plantillas_que_las_usan

    a = uuid.uuid4()
    await _plantilla_con(db_session, {"funcion_id": str(a), "version": 1.0})
    await _plantilla_con(db_session, {"funcion_id": str(a), "version": 0})

    assert await plantillas_que_las_usan(db_session, [a]) == {(a, 1): 1}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "escrito",
    [
        lambda u: u.hex,
        lambda u: "{" + str(u) + "}",
        lambda u: "urn:uuid:" + str(u),
        lambda u: str(u).upper(),
    ],
    ids=["sin-guiones", "con-llaves", "urn", "mayusculas"],
)
async def test_counts_every_spelling_of_the_id_the_contract_accepts(db_session, escrito):
    """Revisión de la PR #320: `spec_json` se guarda tal como llega, y `FuncionRef` acepta el id
    sin guiones, entre llaves o con `urn:uuid:`. El filtro en SQL sólo veía la forma canónica, así
    que un ancla escrita a mano funcionaba en el bloque y no contaba en la cola de revisión."""
    from server.app.modules.redaccion.funciones_catalogo import plantillas_que_las_usan

    a = uuid.uuid4()
    await _plantilla_con(db_session, {"funcion_id": escrito(a), "version": 2})

    assert await plantillas_que_las_usan(db_session, [a]) == {(a, 2): 1}


@pytest.mark.asyncio
async def test_one_template_counts_once_for_each_pair_it_anchors(db_session):
    """Una plantilla con dos funciones cuenta para las dos; dos bloques con el mismo par, una vez;
    y un ancla a otra versión no cuenta para ésta."""
    from server.app.modules.redaccion.funciones_catalogo import plantillas_que_las_usan

    a, b = uuid.uuid4(), uuid.uuid4()
    await _plantilla_con(
        db_session,
        {"funcion_id": str(a), "version": 1},
        {"funcion_id": str(a), "version": 1},
        {"funcion_id": str(b), "version": 2},
    )

    assert await plantillas_que_las_usan(db_session, [a, b]) == {(a, 1): 1, (b, 2): 1}


@pytest.mark.asyncio
async def test_the_count_is_done_in_the_database(db_session):
    """#317 — la cola traía a Python el `spec_json` entero de cada versión de plantilla que
    mencionara una función de la cola, superadas incluidas. Ahora la base expande los bloques y
    devuelve sólo las anclas: una consulta, y el spec no sale de ella."""
    from server.app.modules.redaccion.funciones_catalogo import plantillas_que_las_usan

    a = uuid.uuid4()
    await _plantilla_con(db_session, {"funcion_id": str(a), "version": 1})

    with _contando(db_session) as sentencias:
        assert await plantillas_que_las_usan(db_session, [a, uuid.uuid4()]) == {(a, 1): 1}

    assert len(sentencias) == 1
    seleccion = sentencias[0].split("FROM", 1)[0]
    assert "spec_json" not in seleccion, sentencias[0]


@pytest.mark.asyncio
async def test_blocks_written_as_an_object_count_too(db_session):
    """`blocks` puede ser una lista o un objeto con los bloques por id; las dos formas cuentan."""
    from server.app.modules.redaccion.funciones_catalogo import plantillas_que_las_usan

    a = uuid.uuid4()
    plantilla = HubReportTemplate(
        name=f"Plantilla {uuid.uuid4()}", report_profile="GENERIC_REPORT", owner_kind="platform"
    )
    db_session.add(plantilla)
    await db_session.flush()
    db_session.add(
        HubReportTemplateVersion(
            template_id=plantilla.id, version=1, created_by=uuid.uuid4(),
            spec_json={
                "blocks": {
                    "b1": {"kind": "DETERMINISTIC_DATA", "funcion_ref": {"funcion_id": str(a), "version": 3}},
                }
            },
        )
    )
    await db_session.commit()

    assert await plantillas_que_las_usan(db_session, [a]) == {(a, 3): 1}


@pytest.mark.asyncio
async def test_mentioning_the_id_outside_an_anchor_does_not_count(db_session):
    """El id en un texto o en otro campo no es un ancla."""
    from server.app.modules.redaccion.funciones_catalogo import plantillas_que_las_usan

    a = uuid.uuid4()
    plantilla = HubReportTemplate(
        name=f"Plantilla {uuid.uuid4()}", report_profile="GENERIC_REPORT", owner_kind="platform"
    )
    db_session.add(plantilla)
    await db_session.flush()
    db_session.add(
        HubReportTemplateVersion(
            template_id=plantilla.id, version=1, created_by=uuid.uuid4(),
            spec_json={"blocks": [{"id": "b1", "kind": "FREE_TEXT", "nota": f"ver {a}", "version": 1}]},
        )
    )
    await db_session.commit()

    assert await plantillas_que_las_usan(db_session, [a]) == {}
