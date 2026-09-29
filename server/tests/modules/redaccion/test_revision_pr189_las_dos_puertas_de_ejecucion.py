"""Los once hallazgos de la revisión de la PR #189, y sobre todo los dos que importaban.

**La garantía central del hito tenía dos puertas abiertas.** «Se registra, no se ejecuta» se hizo
cumplir en el endpoint de ejecución y en ningún sitio más, y había otras dos entradas:

1. **El resolutor.** `ResolvedorDeFuncion` trataba todo lo que no fuera `paquete` como código de
   sandbox, así que una plantilla que anclara un cuaderno externo lo ejecutaba dentro.
2. **La adopción.** `acciones_permitidas` ofrecía `adoptar_version` para cualquier función
   registrada de la casa, y adoptar es justamente anclarla en una plantilla.

**Y una tercera por la que entraba código sin filtro a algo que sí se ejecuta**: el endpoint de
registro aceptaba un `funcion_id` de quien fuera, sin comprobar de quién era ni de qué origen, así
que se le podía añadir una versión con **auditoría informativa** a una función de autoservicio.

Ninguna de las tres la vieron mis tests, y la razón es la misma en las tres: probé lo que el
código hace y no lo que el código **impide**. Un test que comprueba que registrar funciona no dice
nada sobre quién más puede registrar.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

CUADERNO = '{"cells": [{"cell_type": "code", "source": ["x = 1"]}]}'


def _contrato(finalidad: str = "Extraer las subvenciones nominativas"):
    from server.app.modules.redaccion.contracts.funciones import ContratoFuncion

    return ContratoFuncion(
        slots=[],
        parametros=[],
        finalidad=finalidad,
        categorias_datos=["sin_datos_personales"],
    )


async def _externa(db_session, *, organizacion=None):
    from server.app.modules.redaccion.funciones_service import registrar_version

    return await registrar_version(
        db_session,
        nombre="Cuaderno del presupuesto",
        organizacion_id=organizacion or uuid.uuid4(),
        code=CUADERNO,
        contrato=_contrato(),
        declarada_por=uuid.uuid4(),
        origen="externa",
        entorno_ejecucion="el equipo de la persona",
    )


class TestElResolutorSeNiega:
    """Puerta 1: una plantilla que la ancle no puede ejecutarla."""

    @pytest.mark.asyncio
    async def test_una_plantilla_no_puede_ejecutar_un_cuaderno_externo(self, db_session):
        from server.app.modules.redaccion.funciones_resolver import (
            FuncionNoEjecutable,
            ResolvedorDeFuncion,
        )

        funcion, _version = await _externa(db_session)
        await db_session.commit()

        with pytest.raises(FuncionNoEjecutable, match="origen externo"):
            await ResolvedorDeFuncion(db_session).resolver(funcion.id, 1)

    @pytest.mark.asyncio
    async def test_y_dice_donde_si_corre(self, db_session):
        """El dato que el registro guarda justamente para poder decirlo."""
        from server.app.modules.redaccion.funciones_resolver import (
            FuncionNoEjecutable,
            ResolvedorDeFuncion,
        )

        funcion, _version = await _externa(db_session)
        await db_session.commit()

        with pytest.raises(FuncionNoEjecutable) as fallo:
            await ResolvedorDeFuncion(db_session).resolver(funcion.id, 1)

        assert "el equipo de la persona" in str(fallo.value)

    @pytest.mark.asyncio
    async def test_una_de_autoservicio_sigue_resolviendo(self, db_session):
        """Sin esto, lo de arriba se cumpliría rompiendo el catálogo entero."""
        from server.app.modules.redaccion.funciones_resolver import ResolvedorDeFuncion
        from server.app.modules.redaccion.funciones_service import registrar_version

        funcion, _version = await registrar_version(
            db_session,
            nombre="De la casa",
            organizacion_id=uuid.uuid4(),
            code="result = {'free_text': 'ok'}",
            contrato=_contrato(),
            declarada_por=uuid.uuid4(),
        )
        await db_session.commit()

        ejecutable = await ResolvedorDeFuncion(db_session).resolver(funcion.id, 1)

        assert ejecutable.code == "result = {'free_text': 'ok'}"


class TestNoSeOfreceAdoptarla:
    """Puerta 2: adoptar es anclarla en una plantilla, y una plantilla la ejecuta."""

    def _principal(self, organizacion, autora):
        return SimpleNamespace(
            user_id=str(autora),
            organizacion_ids=(str(organizacion),),
            is_superadmin=False,
            is_admin=True,
        )

    def _funcion(self, origen, organizacion, autora):
        return SimpleNamespace(
            origen=origen,
            organizacion_id=organizacion,
            creada_por=autora,
            publicada_en=None,
            promocion_solicitada_en=None,
        )

    def test_una_externa_no_se_adopta(self):
        from server.app.modules.redaccion.funciones_acciones import acciones_permitidas

        organizacion, autora = uuid.uuid4(), uuid.uuid4()

        acciones = acciones_permitidas(
            self._funcion("externa", organizacion, autora),
            SimpleNamespace(estado="registrada"),
            principal=self._principal(organizacion, autora),
        )

        assert "adoptar_version" not in acciones

    def test_una_de_autoservicio_si(self):
        """Sin esto, lo de arriba se cumpliría quitando el botón a todo el mundo."""
        from server.app.modules.redaccion.funciones_acciones import acciones_permitidas

        organizacion, autora = uuid.uuid4(), uuid.uuid4()

        acciones = acciones_permitidas(
            self._funcion("autoservicio", organizacion, autora),
            SimpleNamespace(estado="registrada"),
            principal=self._principal(organizacion, autora),
        )

        assert "adoptar_version" in acciones

    def test_una_externa_si_se_versiona_y_se_retira(self):
        """Lo que no puede es ejecutarse; lo demás sigue siendo una función del catálogo."""
        from server.app.modules.redaccion.funciones_acciones import acciones_permitidas

        organizacion, autora = uuid.uuid4(), uuid.uuid4()

        acciones = acciones_permitidas(
            self._funcion("externa", organizacion, autora),
            SimpleNamespace(estado="registrada"),
            principal=self._principal(organizacion, autora),
        )

        assert "versionar" in acciones
        assert "retirar" in acciones


class TestQuienPuedeAnadirleUnaVersion:
    """Puerta 3: el `funcion_id` venía de quien llamaba y nadie lo autorizaba."""

    def _cuerpo(self, funcion_id=None):
        from server.app.routers.redaccion.funciones_router import (
            RegistrarExternaRequest,
        )

        return RegistrarExternaRequest(
            nombre="Otra versión",
            fichero=CUADERNO,
            finalidad="Extraer subvenciones",
            categorias_datos=["sin_datos_personales"],
            entorno_ejecucion="un cuaderno en la nube",
            funcion_id=funcion_id,
        )

    def _principal(self, organizacion):
        from server.app.core.auth.models import UserInfo

        return UserInfo(
            user_id=str(uuid.uuid4()),
            email="alguien@uji.es",
            role="admin",
            organizacion_ids=[str(organizacion)],
        )

    @pytest.mark.asyncio
    async def test_no_se_le_anade_una_version_a_la_funcion_de_otra_organizacion(
        self, db_session
    ):
        from fastapi import HTTPException

        from server.app.routers.redaccion.funciones_router import (
            registrar_funcion_externa,
        )

        ajena, _version = await _externa(db_session, organizacion=uuid.uuid4())
        await db_session.commit()

        with pytest.raises(HTTPException) as fallo:
            await registrar_funcion_externa(
                self._cuerpo(funcion_id=ajena.id),
                principal=self._principal(uuid.uuid4()),
                session=db_session,
            )

        # 404 y no 403: decir «existe pero no es tuya» ya es decir que existe.
        assert fallo.value.status_code == 404

    @pytest.mark.asyncio
    async def test_no_se_cuela_codigo_informativo_en_algo_que_si_se_ejecuta(
        self, db_session
    ):
        """El peor de los tres: la auditoría informativa vale porque el código corre fuera.

        Añadida a una función de autoservicio, metería código sin filtro en el sandbox.
        """
        from fastapi import HTTPException

        from server.app.modules.redaccion.funciones_service import registrar_version
        from server.app.routers.redaccion.funciones_router import (
            registrar_funcion_externa,
        )

        organizacion = uuid.uuid4()
        ejecutable, _version = await registrar_version(
            db_session,
            nombre="Corre en el sandbox",
            organizacion_id=organizacion,
            code="result = {}",
            contrato=_contrato(),
            declarada_por=uuid.uuid4(),
        )
        await db_session.commit()

        with pytest.raises(HTTPException) as fallo:
            await registrar_funcion_externa(
                self._cuerpo(funcion_id=ejecutable.id),
                principal=self._principal(organizacion),
                session=db_session,
            )

        assert fallo.value.status_code == 409
        assert fallo.value.detail["code"] == "ORIGEN_DISTINTO"

    @pytest.mark.asyncio
    async def test_a_la_propia_si(self, db_session):
        """Sin esto, lo de arriba se cumpliría impidiendo versionar nada."""
        from server.app.routers.redaccion.funciones_router import (
            registrar_funcion_externa,
        )

        organizacion = uuid.uuid4()
        mia, _version = await _externa(db_session, organizacion=organizacion)
        await db_session.commit()

        vista = await registrar_funcion_externa(
            self._cuerpo(funcion_id=mia.id),
            principal=self._principal(organizacion),
            session=db_session,
        )

        assert sorted(v.version for v in vista.versiones) == [1, 2]


class TestLoQueElContratoPromete:

    def test_autoria_solo_admite_los_dos_valores_que_documenta(self):
        """El comentario prometía `persona | ia` y el tipo aceptaba cualquier cadena: una de más
        de 20 caracteres fallaba como 500 al escribir, y no como 422 de contrato."""
        from pydantic import ValidationError

        from server.app.routers.redaccion.funciones_router import (
            RegistrarExternaRequest,
        )

        with pytest.raises(ValidationError):
            RegistrarExternaRequest(
                nombre="x",
                fichero=CUADERNO,
                finalidad="y",
                categorias_datos=["sin_datos_personales"],
                entorno_ejecucion="z",
                autoria="una cadena larguísima que no cabe en la columna",
            )
