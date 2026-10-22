"""Dueños de token que existen de verdad en la base.

Un token personal vale lo que vale **hoy** su dueño: `PatService.verify` comprueba que la persona
existe, está activa y conserva el rol con el que lo emitió. Un test que emite un token a nombre
de un sujeto inventado —`admin-1234`, `sa-…`— y luego lo usa está probando un token sin dueño, que
es justo lo que ahora se rechaza. Este ayudante da un dueño real.
"""
from __future__ import annotations

import uuid

from server.app.core.auth.models import UserInfo


async def persona_real(session, role: str = "admin", organizacion_id=None) -> UserInfo:
    """Crea un `HubUser` activo y devuelve el principal con el que entraría."""
    from server.app.modules.agents_hub.database.config_models import HubUser

    # Los valores se fijan antes del commit: con `expire_on_commit`, leerlos después dispara una
    # recarga síncrona que en una sesión asíncrona revienta (`MissingGreenlet`).
    ident = uuid.uuid4()
    email = f"{role}.{uuid.uuid4().hex[:8]}@uji.es"
    session.add(
        HubUser(
            id=ident,
            email=email,
            role=role,
            organizacion_id=uuid.UUID(str(organizacion_id)) if organizacion_id else None,
        )
    )
    await session.commit()
    return UserInfo(
        user_id=str(ident),
        email=email,
        role=role,
        organizacion_ids=(str(organizacion_id),) if organizacion_id else (),
    )
