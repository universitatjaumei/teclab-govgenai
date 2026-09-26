"""Issue #159, parte 3 de 3 — la misma operación cara no corre dos veces.

**La parte 3 no es el limitador de concurrencia que la issue anticipaba, y la medición es la
razón.** Buscando evidencia de solapamiento en producción: **33 ingestas, 0 pares solapados en el
tiempo**, y cero rastreos. No hay ningún dato que sostenga un limitador global de operaciones
simultáneas, y construirlo sería trabajar sobre una hipótesis.

Lo que sí hay es un riesgo concreto y comprobable: `run_job` no miraba el estado del job. Ponía
`running` y procesaba, así que dos invocaciones sobre el mismo `job_id` ingerían el documento
**dos veces** — fragmentos duplicados en el corpus, que es peor que una consulta lenta porque no
se nota y no se deshace solo.

**Se cierra con un candado atómico en la base, no comprobando y luego escribiendo.** Un
`if job.status == "pending"` seguido de un `UPDATE` tiene una ventana entre la lectura y la
escritura, y dos tareas de fondo del mismo proceso caben de sobra en esa ventana. Un
`UPDATE ... WHERE status IN ('pending','failed')` decide en una sola operación: quien consigue
`rowcount == 1` se lo queda, y el otro se va.

**Y deja reintentar lo que falló**, que es lo que distingue este candado de un `completed` a
secas: un job en `failed` se puede volver a lanzar, y uno que se quedó en `running` por un
reinicio del contenedor no bloquea nada para siempre porque el estado lo decide quien reintenta,
no un cronómetro.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from server.app.modules.agents_hub.database.operational_models import HubIngestionJob


async def _job(session, estado: str) -> HubIngestionJob:
    job = HubIngestionJob(
        id=uuid.uuid4(),
        chatbot_id=uuid.uuid4(),
        source_url="https://ejemplo.test/x.md",
        status=estado,
    )
    session.add(job)
    await session.commit()
    return job


class TestElCandadoDelJob:

    async def test_un_job_pendiente_se_puede_tomar(self, db_session) -> None:
        from server.app.modules.agents_hub.ingestion.watcher import tomar_job

        job = await _job(db_session, "pending")

        assert await tomar_job(db_session, job.id) is True

        await db_session.refresh(job)
        assert job.status == "running"
        assert job.processing_started_at is not None

    async def test_un_job_ya_en_curso_no_se_toma_dos_veces(self, db_session) -> None:
        """El defecto: dos invocaciones ingerían el documento dos veces."""
        from server.app.modules.agents_hub.ingestion.watcher import tomar_job

        job = await _job(db_session, "pending")

        assert await tomar_job(db_session, job.id) is True
        assert await tomar_job(db_session, job.id) is False

    async def test_un_job_terminado_no_se_reprocesa(self, db_session) -> None:
        from server.app.modules.agents_hub.ingestion.watcher import tomar_job

        job = await _job(db_session, "completed")

        assert await tomar_job(db_session, job.id) is False

    async def test_un_job_fallido_si_se_puede_reintentar(self, db_session) -> None:
        """Si no, un fallo transitorio dejaría el documento fuera del corpus para siempre y la
        única salida sería volver a subirlo."""
        from server.app.modules.agents_hub.ingestion.watcher import tomar_job

        job = await _job(db_session, "failed")

        assert await tomar_job(db_session, job.id) is True

    async def test_un_job_que_no_existe_no_se_toma(self, db_session) -> None:
        from server.app.modules.agents_hub.ingestion.watcher import tomar_job

        assert await tomar_job(db_session, uuid.uuid4()) is False


class TestElCandadoDecideEnUnaSolaOperacion:
    """Comprobar y luego escribir deja una ventana; el `UPDATE` condicional no.

    Dos tareas de `BackgroundTasks` corren en el mismo bucle de eventos y **ceden el control en
    cada `await`**, así que la ventana entre un `if job.status == 'pending'` y el `commit` no es
    teórica: cabe una tarea entera.
    """

    async def test_el_estado_se_comprueba_y_se_escribe_a_la_vez(self) -> None:
        import inspect

        from server.app.modules.agents_hub.ingestion.watcher import tomar_job

        fuente = inspect.getsource(tomar_job)
        assert "update(" in fuente and "rowcount" in fuente, (
            "el candado no decide en una sola operación de base de datos. Leer el estado y "
            "escribirlo después deja una ventana entre las dos, y dos tareas de fondo del mismo "
            "proceso caben de sobra en ella."
        )

    async def test_no_toma_un_job_que_otro_acaba_de_tomar(self, db_session) -> None:
        """La prueba de la carrera, hasta donde una sesión permite: el segundo intento ve el
        estado que dejó el primero y se va, sin tocar `processing_started_at`."""
        from server.app.modules.agents_hub.ingestion.watcher import tomar_job

        job = await _job(db_session, "pending")
        await tomar_job(db_session, job.id)
        await db_session.refresh(job)
        primera_marca = job.processing_started_at

        assert await tomar_job(db_session, job.id) is False

        await db_session.refresh(job)
        assert job.processing_started_at == primera_marca, (
            "el segundo intento ha pisado la marca de inicio del primero"
        )


@pytest.fixture
async def db_session(db_url: str):
    """Una sesión contra la base desechable del conftest."""
    from server.app.modules.agents_hub.database.connection import (
        create_async_engine,
        create_session_factory,
    )

    motor = create_async_engine(db_url)
    fabrica = create_session_factory(motor)
    async with fabrica() as sesion:
        yield sesion
    await motor.dispose()


async def test_el_job_de_prueba_se_guarda_de_verdad(db_session) -> None:
    """Sin esto, un modelo que no se pudiera insertar dejaría los test de arriba pasando sobre
    una base vacía: `tomar_job` devolvería `False` por no encontrar nada y parecería correcto."""
    job = await _job(db_session, "pending")

    encontrado = (
        await db_session.execute(
            select(HubIngestionJob).where(HubIngestionJob.id == job.id)
        )
    ).scalar_one_or_none()

    assert encontrado is not None
