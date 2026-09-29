"""AUT.12 (issue #122) — el plazo máximo de la revisión posterior, fijado por la institución.

**Qué plazo es éste, porque se confunde.** No es el de actualizar dependencias. Es el de
**revisar una versión registrada**: en el nivel 2 una función queda usable en el acto, sin
aprobación previa, y entra en una cola de revisión posterior. El plazo es el compromiso de que
esa espera no sea indefinida.

La §10 de la Instrucció lo pide con estas palabras: un compromiso de plazo máximo «a fin de que
el control no se convierta en un cuello de botella». **O sea que el plazo no protege a la
plataforma, protege a quien registra**: es la promesa de que su trabajo no se queda esperando a
que alguien lo mire.

**Fijado en 30 días naturales el 2026-09-29**, por decisión de la institución que despliega.

**Y avisa, no bloquea.** Superar el plazo marca la versión en la cola y no le hace nada más: ni
se retira, ni se suspende, ni deja de poder usarse. Bloquear al vencer sería convertir la
revisión posterior en aprobación previa por la puerta de atrás — con retardo, pero aprobación
previa —, que es lo que el nivel 2 prohíbe.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest


def _contrato():
    from server.app.modules.redaccion.contracts.funciones import ContratoFuncion

    return ContratoFuncion(
        slots=[],
        parametros=[],
        finalidad="Contar filas del fichero de gastos",
        categorias_datos=["sin_datos_personales"],
    )


async def _version_de_hace(db_session, dias: int, *, organizacion):
    from server.app.modules.redaccion.funciones_service import registrar_version

    funcion, version = await registrar_version(
        db_session,
        nombre=f"Registrada hace {dias} días",
        organizacion_id=organizacion,
        code="result = {}",
        contrato=_contrato(),
        declarada_por=uuid.uuid4(),
    )
    version.created_at = datetime.now(timezone.utc) - timedelta(days=dias)
    db_session.add(version)
    await db_session.flush()
    return funcion, version


def _quien_revisa(organizacion):
    from server.app.core.auth.models import UserInfo

    return UserInfo(
        user_id=str(uuid.uuid4()),
        email="revisa@uji.es",
        role="admin",
        organizacion_ids=[str(organizacion)],
    )


class TestElPlazoQueLaInstitucionFija:

    def test_por_defecto_son_treinta_dias_naturales(self):
        from server.app.modules.redaccion.funciones_acciones import (
            plazo_de_revision_en_dias,
        )

        assert plazo_de_revision_en_dias() == 30

    def test_se_puede_cambiar_sin_tocar_codigo(self, monkeypatch):
        """Lo fija la institución que despliega, no quien desarrolla la plataforma."""
        from server.app.modules.redaccion.funciones_acciones import (
            plazo_de_revision_en_dias,
        )

        monkeypatch.setenv("PLAZO_REVISION_POSTERIOR_DIAS", "15")

        assert plazo_de_revision_en_dias() == 15

    def test_un_valor_ilegible_cae_al_por_defecto_en_vez_de_reventar(self, monkeypatch):
        """Una variable mal escrita no puede dejar la cola sin plazo **ni** tumbar el panel."""
        from server.app.modules.redaccion.funciones_acciones import (
            plazo_de_revision_en_dias,
        )

        monkeypatch.setenv("PLAZO_REVISION_POSTERIOR_DIAS", "quince")

        assert plazo_de_revision_en_dias() == 30


class TestLaColaLoDice:

    @pytest.mark.asyncio
    async def test_una_version_que_pasa_del_plazo_sale_marcada(self, db_session):
        from server.app.routers.redaccion.funciones_router import cola_de_revision

        organizacion = uuid.uuid4()
        await _version_de_hace(db_session, 45, organizacion=organizacion)
        await db_session.commit()

        cola = await cola_de_revision(
            estado="sin_revisar",
            muestra=None,
            principal=_quien_revisa(organizacion),
            session=db_session,
        )

        assert cola[0].fuera_de_plazo is True
        assert cola[0].plazo_en_dias == 30

    @pytest.mark.asyncio
    async def test_una_reciente_no(self, db_session):
        """Sin esto, lo de arriba se cumpliría marcándolo todo y el aviso no diría nada."""
        from server.app.routers.redaccion.funciones_router import cola_de_revision

        organizacion = uuid.uuid4()
        await _version_de_hace(db_session, 3, organizacion=organizacion)
        await db_session.commit()

        cola = await cola_de_revision(
            estado="sin_revisar",
            muestra=None,
            principal=_quien_revisa(organizacion),
            session=db_session,
        )

        assert cola[0].fuera_de_plazo is False

    @pytest.mark.asyncio
    async def test_el_dia_exacto_del_plazo_todavia_no_esta_fuera(self, db_session):
        """Treinta días es el plazo, no el primer día de incumplimiento."""
        from server.app.routers.redaccion.funciones_router import cola_de_revision

        organizacion = uuid.uuid4()
        await _version_de_hace(db_session, 30, organizacion=organizacion)
        await db_session.commit()

        cola = await cola_de_revision(
            estado="sin_revisar",
            muestra=None,
            principal=_quien_revisa(organizacion),
            session=db_session,
        )

        assert cola[0].fuera_de_plazo is False


class TestAvisaPeroNoBloquea:
    """Bloquear al vencer sería aprobación previa con retardo, y el nivel 2 la prohíbe."""

    @pytest.mark.asyncio
    async def test_una_version_fuera_de_plazo_se_sigue_pudiendo_ejecutar(self, db_session):
        from server.app.modules.redaccion.funciones_resolver import ResolvedorDeFuncion

        organizacion = uuid.uuid4()
        funcion, _version = await _version_de_hace(db_session, 90, organizacion=organizacion)
        await db_session.commit()

        ejecutable = await ResolvedorDeFuncion(db_session).resolver(funcion.id, 1)

        assert ejecutable.code == "result = {}"

    @pytest.mark.asyncio
    async def test_y_sigue_ofreciendo_las_mismas_acciones(self, db_session):
        from server.app.routers.redaccion.funciones_router import cola_de_revision

        organizacion = uuid.uuid4()
        await _version_de_hace(db_session, 90, organizacion=organizacion)
        await db_session.commit()

        cola = await cola_de_revision(
            estado="sin_revisar",
            muestra=None,
            principal=_quien_revisa(organizacion),
            session=db_session,
        )

        assert "revisar" in cola[0].acciones_permitidas
