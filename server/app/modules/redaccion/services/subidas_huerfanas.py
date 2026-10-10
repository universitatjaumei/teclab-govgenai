"""Lo subido para propuestas de script que ya no lo necesitan (#258). Deploy: edge.

Lo subido vive en `test-data/uploads/{propuesta}/` y se borra al anonimizar y al cerrar la
propuesta (#251), **después** del commit. Si ese borrado falló, aquí se recoge: las carpetas de
propuestas que no existen o están cerradas —registradas, aprobadas, rechazadas—.

**Las de propuestas abiertas no se tocan**, aunque lleven meses abandonadas: borrarlas exige un
plazo de conservación, y los plazos son decisión pendiente (#162).
"""
from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.core.storage import StorageService
from server.app.modules.redaccion.database.models import HubScriptProposal

_log = logging.getLogger(__name__)

#: Los estados en que la propuesta ya no necesita lo subido.
CERRADAS = frozenset({"registrada", "approved", "rejected"})


async def barrer_subidas_huerfanas(session: AsyncSession, storage: StorageService) -> int:
    """Borra lo subido de propuestas que no existen o están cerradas. Devuelve cuántas carpetas."""
    candidatos: dict[uuid.UUID, str] = {}
    for nombre in await storage.listar("test-data/uploads/"):
        try:
            candidatos[uuid.UUID(nombre)] = nombre
        except ValueError:
            continue
    if not candidatos:
        return 0
    filas = (
        await session.execute(
            select(HubScriptProposal.id, HubScriptProposal.status).where(
                HubScriptProposal.id.in_(list(candidatos))
            )
        )
    ).all()
    estados = {propuesta_id: status for propuesta_id, status in filas}
    huerfanas = [
        nombre
        for propuesta_id, nombre in candidatos.items()
        if propuesta_id not in estados or estados[propuesta_id] in CERRADAS
    ]
    for nombre in huerfanas:
        await storage.delete_prefix(f"test-data/uploads/{nombre}/")
    if huerfanas:
        _log.info("Subidas de propuestas cerradas o inexistentes borradas: %d", len(huerfanas))
    return len(huerfanas)
