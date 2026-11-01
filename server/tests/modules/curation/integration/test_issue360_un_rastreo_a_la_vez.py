"""#360 — el servidor sabe si un sitio se está rastreando.

El rastreo corre como tarea dentro del proceso web y no dejaba constancia de que estuviera en
marcha. Tres consecuencias: dos rastreos del mismo sitio podían coincidir (a mano, desde otra
pestaña, por otra persona o con el programado); un despliegue lo mataba sin dejar rastro en el
diario; y el panel tenía que deducir el desenlace comparando lo que el sitio traía antes y después.

Ahora el sitio guarda «rastreo en curso desde…». Se reserva con una sola sentencia condicional
—dos peticiones a la vez no pueden ganar las dos—, se libera al terminar aunque falle, y lo que un
reinicio deja marcado se da por interrumpido al arrancar, con su fila en el diario.

Contra Postgres y no con dobles: lo que hay que demostrar es que la reserva es atómica y qué filas
quedan, y un doble de sesión devuelve lo que se le dice.
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

AHORA = datetime(2026, 11, 1, 10, 42, 0, tzinfo=timezone.utc)


async def _sitio(db_session, nombre: str = "Escola de Doctorat"):
    from server.app.modules.curation.site_repo import WebSiteRepo

    sitio = await WebSiteRepo(db_session).create(
        organizacion_id=uuid.uuid4(), name=nombre, root_url="https://www.uji.es"
    )
    await db_session.commit()
    return sitio


def _factoria(db_session):
    @asynccontextmanager
    async def _f():
        yield db_session

    return _f


async def _marca(db_session, site_id):
    from server.app.modules.agents_hub.database.operational_models import HubWebSite

    db_session.expire_all()
    sitio = (
        await db_session.execute(select(HubWebSite).where(HubWebSite.id == site_id))
    ).scalar_one()
    return sitio.rastreo_en_curso_desde


class TestLaReserva:

    @pytest.mark.asyncio
    async def test_el_primero_reserva_y_el_segundo_se_entera_de_desde_cuando(self, db_session):
        from server.app.modules.curation.rastreo_en_curso import reservar

        sitio = await _sitio(db_session)

        assert await reservar(db_session, sitio.id, None, AHORA) is None
        ocupado = await reservar(db_session, sitio.id, None, AHORA + timedelta(minutes=3))

        assert ocupado == AHORA, "el segundo tiene que saber desde cuándo está ocupado"
        assert await _marca(db_session, sitio.id) == AHORA

    @pytest.mark.asyncio
    async def test_dos_reservas_a_la_vez_no_ganan_las_dos(self, db_url):
        """Dos sesiones con su propia transacción, como dos peticiones: una sola gana."""
        import asyncio

        from server.app.modules.agents_hub.database.connection import (
            create_async_engine,
            create_session_factory,
        )
        from server.app.modules.curation.rastreo_en_curso import reservar
        from server.app.modules.curation.site_repo import WebSiteRepo

        motor = create_async_engine(db_url)
        fabrica = create_session_factory(motor)
        try:
            async with fabrica() as s:
                sitio = await WebSiteRepo(s).create(
                    organizacion_id=uuid.uuid4(), name="Portal", root_url="https://www.uji.es"
                )
                await s.commit()

            async def _intento():
                async with fabrica() as s:
                    return await reservar(s, sitio.id, None, AHORA)

            resultados = await asyncio.gather(*[_intento() for _ in range(5)])
        finally:
            await motor.dispose()

        assert sum(1 for r in resultados if r is None) == 1

    @pytest.mark.asyncio
    async def test_liberar_deja_volver_a_rastrear(self, db_session):
        from server.app.modules.curation.rastreo_en_curso import liberar, reservar

        sitio = await _sitio(db_session)
        await reservar(db_session, sitio.id, None, AHORA)

        await liberar(_factoria(db_session), sitio.id)

        assert await _marca(db_session, sitio.id) is None
        assert await reservar(db_session, sitio.id, None, AHORA) is None

    @pytest.mark.asyncio
    async def test_una_marca_caducada_no_bloquea_para_siempre(self, db_session):
        """La red de seguridad: si la marca sobrevivió a todo, al cabo de un día no manda."""
        from server.app.modules.curation.rastreo_en_curso import CADUCIDAD, reservar

        sitio = await _sitio(db_session)
        await reservar(db_session, sitio.id, None, AHORA - CADUCIDAD - timedelta(minutes=1))

        assert await reservar(db_session, sitio.id, None, AHORA) is None


class TestAlArrancar:

    @pytest.mark.asyncio
    async def test_lo_que_un_reinicio_deja_marcado_se_da_por_interrumpido_y_se_anota(
        self, db_session
    ):
        from server.app.modules.agents_hub.database.operational_models import HubCrawlRun
        from server.app.modules.curation.diario import DiarioDePasadas
        from server.app.modules.curation.rastreo_en_curso import (
            interrumpir_los_que_quedaron,
            reservar,
        )

        cortado = await _sitio(db_session, "Cortado por el despliegue")
        tranquilo = await _sitio(db_session, "Sin rastreo")
        # Los ids, antes: `_marca` expira la sesión, y leer un atributo expirado es E/S fuera de
        # contexto asíncrono.
        cortado_id, tranquilo_id = cortado.id, tranquilo.id
        await reservar(db_session, cortado_id, None, AHORA)

        cuantos = await interrumpir_los_que_quedaron(
            _factoria(db_session), DiarioDePasadas(_factoria(db_session)), AHORA + timedelta(minutes=5)
        )

        assert cuantos == 1
        assert await _marca(db_session, cortado_id) is None
        pasadas = (
            await db_session.execute(select(HubCrawlRun).where(HubCrawlRun.site_id == cortado_id))
        ).scalars().all()
        assert len(pasadas) == 1
        assert pasadas[0].started_at == AHORA
        assert pasadas[0].truncated is True
        assert "reinicio" in (pasadas[0].stop_reason or "")
        assert any("no terminó" in e for e in pasadas[0].errors)
        assert not (
            await db_session.execute(select(HubCrawlRun).where(HubCrawlRun.site_id == tranquilo_id))
        ).scalars().all()


class TestElTrabajoLibera:

    @pytest.mark.asyncio
    async def test_libera_aunque_el_rastreo_falle(self, db_session):
        from server.app.modules.curation.quality_job import SiteQualityAnalysisJob
        from server.app.modules.curation.rastreo_en_curso import reservar

        class _RastreadorRoto:
            async def crawl_site(self, site_id, section_id=None):
                raise RuntimeError("el portal no responde")

        sitio = await _sitio(db_session)
        await reservar(db_session, sitio.id, None, AHORA)
        trabajo = SiteQualityAnalysisJob(
            session_factory=_factoria(db_session),
            site_crawler=_RastreadorRoto(),
            detectors=[],
            watcher=None,
            selection_repo=None,
        )

        resumen = await trabajo.run_for_site(sitio.id)

        assert resumen.errors, "el fallo tiene que quedar en el resumen"
        assert await _marca(db_session, sitio.id) is None


class TestElContrato:

    @pytest.mark.asyncio
    async def test_la_vista_del_sitio_dice_desde_cuando_se_rastrea(self, db_session):
        from server.app.modules.curation.rastreo_en_curso import reservar
        from server.app.modules.curation.selection_contracts import SiteView

        sitio = await _sitio(db_session)
        sitio_id = sitio.id
        await reservar(db_session, sitio_id, None, AHORA)

        from server.app.modules.agents_hub.database.operational_models import HubWebSite

        fila = (
            await db_session.execute(
                select(HubWebSite)
                .where(HubWebSite.id == sitio_id)
                .execution_options(populate_existing=True)
            )
        ).scalar_one()
        assert SiteView.model_validate(fila).rastreo_en_curso_desde == AHORA


class TestElPlanificador:
    """Lanzaba una tarea por ámbito: todas las secciones vencidas de un portal a la vez. Con la
    marca, que es del sitio, todas menos una chocarían; ahora van en serie por sitio."""

    async def _montar(self, db_url, con_marca: bool):
        from server.app.modules.agents_hub.database.connection import (
            create_async_engine,
            create_session_factory,
        )
        from server.app.modules.curation.quality_scheduler import AmbitoVencido
        from server.app.modules.curation.rastreo_en_curso import reservar
        from server.app.modules.curation.site_repo import WebSectionRepo, WebSiteRepo

        motor = create_async_engine(db_url)
        fabrica = create_session_factory(motor)
        async with fabrica() as s:
            sitio = await WebSiteRepo(s).create(
                organizacion_id=uuid.uuid4(), name="Portal", root_url="https://www.uji.es"
            )
            becas = await WebSectionRepo(s).create(site_id=sitio.id, name="Becas", pattern="/becas")
            jornadas = await WebSectionRepo(s).create(
                site_id=sitio.id, name="Jornadas", pattern="/jornadas"
            )
            await s.commit()
            if con_marca:
                await reservar(s, sitio.id, None, datetime.now(timezone.utc))
        ambitos = [AmbitoVencido(site=sitio, section=becas), AmbitoVencido(site=sitio, section=jornadas)]
        return motor, fabrica, sitio, ambitos

    @pytest.mark.asyncio
    async def test_las_secciones_de_un_sitio_van_una_detras_de_otra(self, db_url):
        from server.app.modules.curation.quality_scheduler import _rastrear_el_sitio
        from server.app.modules.curation.rastreo_en_curso import liberar

        motor, fabrica, sitio, ambitos = await self._montar(db_url, con_marca=False)
        marcas_vistas: list = []

        class _Trabajo:
            async def run_for_site(self, site_id, section_id=None):
                async with fabrica() as s:
                    marcas_vistas.append(await _marca(s, site_id))
                await liberar(fabrica, site_id)

                class _R:
                    pages_new = pages_marked_superseded = documents_auto_ingested = 0
                    errors: list = []

                return _R()

        try:
            await _rastrear_el_sitio(fabrica, _Trabajo(), ambitos)
        finally:
            await motor.dispose()

        assert len(marcas_vistas) == 2, "las dos secciones se rastrean"
        assert all(m is not None for m in marcas_vistas), "cada una con el sitio reservado"

    @pytest.mark.asyncio
    async def test_si_ya_se_esta_rastreando_se_deja_para_la_pasada_siguiente(self, db_url):
        from server.app.modules.curation.quality_scheduler import _rastrear_el_sitio

        motor, fabrica, sitio, ambitos = await self._montar(db_url, con_marca=True)
        llamadas: list = []

        class _Trabajo:
            async def run_for_site(self, site_id, section_id=None):
                llamadas.append(section_id)

        try:
            await _rastrear_el_sitio(fabrica, _Trabajo(), ambitos)
        finally:
            await motor.dispose()

        assert llamadas == []
