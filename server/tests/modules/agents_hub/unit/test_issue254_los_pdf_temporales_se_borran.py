"""#254 — los PDF temporales del chat se borran, porque ahora algo llama a la limpieza.

Los PDF que alguien sube como contexto de su consulta se guardan como fragmentos con
`is_temporary=True`. Para borrarlos existía `cleanup_temporary_chunks` (24 h), probada en
`test_user_upload.py`, pero **no la llamaba nadie**: se quedaban para siempre. Es la forma de
defecto de DIN.4 y de AUT.7 —una capacidad que el arranque no llama no existe—, así que lo que se
prueba aquí no es que la función borre, sino **que corre**.

Mismo mecanismo que el barrido de artefactos de funciones (`bucle_de_caducados`): un bucle que
lanza el arranque, cada seis horas, y que no se para porque falle una pasada.
"""
from __future__ import annotations

import ast
import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


def test_el_arranque_lo_pone_en_marcha():
    main = Path(__file__).resolve().parents[4] / "app" / "main.py"
    arbol = ast.parse(main.read_text(encoding="utf-8"))
    arranque = next(
        n for n in ast.walk(arbol) if isinstance(n, ast.AsyncFunctionDef) and n.name == "_arranque"
    )
    llamadas = {
        n.func.id if isinstance(n.func, ast.Name) else getattr(n.func, "attr", "")
        for n in ast.walk(arranque)
        if isinstance(n, ast.Call)
    }
    assert "bucle_de_temporales" in llamadas


@pytest.mark.asyncio
async def test_un_fallo_de_una_pasada_no_para_el_bucle(monkeypatch):
    from server.app.modules.agents_hub.ingestion import watcher

    pasadas = []

    async def _pasada_que_falla(*args, **kwargs):
        pasadas.append(1)
        raise RuntimeError("la base no responde")

    async def _sleep_que_corta(_segundos):
        raise asyncio.CancelledError

    monkeypatch.setattr(watcher, "una_pasada_de_temporales", _pasada_que_falla)
    monkeypatch.setattr(watcher.asyncio, "sleep", _sleep_que_corta)

    with pytest.raises(asyncio.CancelledError):
        await watcher.bucle_de_temporales(object())

    assert pasadas == [1]


@pytest.mark.asyncio
async def test_una_pasada_borra_lo_caducado_con_su_propia_sesion(db_url):
    """La pasada abre su sesión desde la factoría, como la del barrido de artefactos: el bucle
    vive más que cualquier petición."""
    from sqlalchemy import select

    from server.app.modules.agents_hub.database.connection import (
        create_async_engine,
        create_session_factory,
    )
    from server.app.modules.agents_hub.database.operational_models import HubDocumentChunk
    from server.app.modules.agents_hub.ingestion.watcher import una_pasada_de_temporales

    motor = create_async_engine(db_url)
    factoria = create_session_factory(motor)
    chatbot_id = uuid.uuid4()
    hace = datetime.now(timezone.utc)

    def _temporal(creado) -> HubDocumentChunk:
        return HubDocumentChunk(
            id=uuid.uuid4(),
            chatbot_id=chatbot_id,
            content="Texto.",
            source_url="file://pujada.pdf",
            content_hash=uuid.uuid4().hex,
            language="val",
            embedding_model="de-prueba",
            embedding_dim=1024,
            is_temporary=True,
            created_at=creado,
        )

    try:
        async with factoria() as sesion:
            sesion.add_all([_temporal(hace - timedelta(hours=25)), _temporal(hace)])
            await sesion.commit()

        borrados = await una_pasada_de_temporales(factoria)

        async with factoria() as sesion:
            quedan = (
                await sesion.execute(
                    select(HubDocumentChunk.id).where(HubDocumentChunk.chatbot_id == chatbot_id)
                )
            ).scalars().all()
        assert borrados >= 1
        assert len(quedan) == 1
    finally:
        await motor.dispose()
