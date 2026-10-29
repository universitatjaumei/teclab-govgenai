"""Las organizaciones: leerlas, darlas de alta, cambiarlas y borrarlas. Deploy: cloud (#274).

Vivía en los handlers de `hub_organizaciones_router`. Ahí queda lo que es HTTP —quién puede
cambiar el partner, el 409 de una organización con datos—; lo que toca la base está aquí, y lo
que es del cliente —sus sitios, informes, agentes, léxico y el corpus de sus chatbots— se pide a
`DatosDelCliente` (#298).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import delete as sql_delete
from sqlalchemy import func, select

from server.app.core.auth.tenancy import scope_query_to_orgs
from server.app.core.datos_del_cliente import CorpusRetirado, DatosDelCliente
from server.app.modules.agents_hub.database.config_models import HubChatbot, HubOrganizacion

_cuantos_chatbots = (
    select(func.count(HubChatbot.id))
    .where(HubChatbot.organizacion_id == HubOrganizacion.id)
    .correlate(HubOrganizacion)
    .scalar_subquery()
)


async def listar(session, principal) -> list[tuple[HubOrganizacion, int]]:
    """Las que el principal puede ver, cada una con cuántos chatbots tiene.

    SEC.8.1: la organización ES la entidad, así que se acota por su propia clave y no por una
    columna `organizacion_id` que aquí no existe.
    """
    consulta = scope_query_to_orgs(
        select(HubOrganizacion, _cuantos_chatbots.label("chatbot_count")),
        principal,
        HubOrganizacion,
        columna="id",
    ).order_by(HubOrganizacion.created_at.desc())
    return [(organizacion, cuantos) for organizacion, cuantos in (await session.execute(consulta)).all()]


async def organizacion_o_404(session, organizacion_id: uuid.UUID) -> HubOrganizacion:
    """La organización, o 404. **La frontera la pone quien llama**, con `assert_org_access`: así
    el router muestra la capa de tenencia que el guardarraíl de SEC.2 le exige."""
    organizacion = await session.get(HubOrganizacion, organizacion_id)
    if not organizacion:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Organización not found"
        )
    return organizacion


async def crear(session, organizacion: HubOrganizacion) -> HubOrganizacion:
    session.add(organizacion)
    await session.commit()
    await session.refresh(organizacion)
    return organizacion


async def actualizar(
    session, organizacion: HubOrganizacion, cambios: dict[str, Any]
) -> HubOrganizacion:
    for campo, valor in cambios.items():
        setattr(organizacion, campo, valor)
    organizacion.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(organizacion)
    return organizacion


async def borrar(
    session, organizacion_id: uuid.UUID, datos: DatosDelCliente
) -> tuple[int, CorpusRetirado]:
    """Borra la organización y purga el corpus de sus chatbots. (chatbots, lo retirado).

    #252 — la cascada llega a los chatbots y no a su corpus, que no cuelga de ellos por clave
    foránea. Mismo camino que borrar un chatbot (PIL.2) y en la misma transacción. Las
    interacciones se quedan, como al borrar un chatbot. Quien llama comprueba antes, con
    `DatosDelCliente.lo_que_impide_borrar`, que no le quedan datos.
    """
    chatbots = list(
        (
            await session.execute(
                select(HubChatbot.id).where(HubChatbot.organizacion_id == organizacion_id)
            )
        )
        .scalars()
        .all()
    )
    retirado = await datos.purgar_corpus(chatbots)
    await session.execute(sql_delete(HubOrganizacion).where(HubOrganizacion.id == organizacion_id))
    await session.commit()
    await datos.borrar_fuentes(chatbots)
    return len(chatbots), retirado
