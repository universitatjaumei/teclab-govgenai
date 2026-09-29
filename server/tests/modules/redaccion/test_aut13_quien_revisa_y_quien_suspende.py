"""AUT.13 (issue #123) — quién revisa, quién suspende, y por dónde **no** pasa la revisión.

Las tres preguntas que la issue dejaba abiertas se contestaron el 2026-09-29, y las tres se
contestaron **ratificando lo que el código ya hacía**. Eso es exactamente lo que hace falta
fijar con tests: un comportamiento que nadie decidió y un comportamiento decidido se parecen
demasiado desde fuera, y el segundo no se toca sin volver a decidir.

1. **Revisar es del administrador de su organización, y del superadministrador en todas.**
2. **Suspender, igual** — aunque §9 de la Instrucció se lo asigne al Responsable institucional
   de IA. Quien administra la organización es quien puede juzgar el impacto de detener sus
   informes; el superadministrador cubre el nivel institucional.
3. **La revisión de la OIATI se hace fuera de la plataforma**, a partir de la autodeclaración de
   categorías. No hay encaminamiento automático, y sobre todo **no hay espera**: una función que
   no se pudiera usar hasta que la OIATI se pronunciara sería aprobación previa, que es lo que
   el nivel 2 prohíbe.

`test_fun4_revision_posterior.py` ya comprueba el caso central —el administrador de la casa
revisa y suspende—. Aquí van los **bordes**, que son donde una decisión se erosiona sin que
nadie lo note: el administrador de *otra* organización, el administrador que además es el autor,
y la función que declara datos personales.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest


def _version(**kw):
    datos = {
        "id": uuid.uuid4(),
        "version": 1,
        "estado": "registrada",
        "revisada_por": None,
        "revision_resultado": None,
        "motivo_suspension": None,
        "suspendida_por": None,
        "autoria": "ia",
    }
    datos.update(kw)
    return SimpleNamespace(**datos)


def _funcion(**kw):
    datos = {
        "id": uuid.uuid4(),
        "nombre": "Extraer gastos",
        "organizacion_id": uuid.uuid4(),
        "origen": "autoservicio",
        "publicada_en": None,
        "promocion_solicitada_en": None,
        "creada_por": uuid.uuid4(),
    }
    datos.update(kw)
    return SimpleNamespace(**datos)


def _principal(*, rol="admin", organizacion=None, user_id=None):
    from server.app.core.auth.models import UserInfo

    return UserInfo(
        user_id=str(user_id or uuid.uuid4()),
        email="quien@uji.es",
        role=rol,
        organizacion_ids=[str(organizacion)] if organizacion else [],
    )


class TestRevisarEsDeSuOrganizacion:
    """«Administrador de su organización y superadministrador de todas», decidido tal cual."""

    def test_el_administrador_de_la_casa_revisa_y_suspende(self):
        from server.app.modules.redaccion.funciones_acciones import acciones_permitidas

        casa = uuid.uuid4()
        funcion = _funcion(organizacion_id=casa)

        acciones = acciones_permitidas(
            funcion, _version(), principal=_principal(rol="admin", organizacion=casa)
        )

        assert "revisar" in acciones
        assert "suspender" in acciones

    def test_el_administrador_de_OTRA_organizacion_no(self):
        """El borde que sostiene la decisión: sin esto, «de su organización» no dice nada.

        Y el caso no es rebuscado. Una función **publicada** a nivel 3 la ve todo el mundo, así
        que el administrador de otra unidad la tiene delante en su pantalla; lo que no tiene es
        potestad para detenerle los informes a la unidad que la escribió.
        """
        from server.app.modules.redaccion.funciones_acciones import acciones_permitidas

        from datetime import datetime, timezone

        funcion = _funcion(organizacion_id=uuid.uuid4(), publicada_en=datetime.now(timezone.utc))

        acciones = acciones_permitidas(
            funcion,
            _version(),
            principal=_principal(rol="admin", organizacion=uuid.uuid4()),
        )

        assert "revisar" not in acciones
        assert "suspender" not in acciones
        # Verla y usarla sí: es una función de nivel 3, y para eso se promovió.
        assert "adoptar_version" in acciones

    def test_el_superadministrador_revisa_las_de_cualquier_organizacion(self):
        from server.app.modules.redaccion.funciones_acciones import acciones_permitidas

        funcion = _funcion(organizacion_id=uuid.uuid4())

        acciones = acciones_permitidas(
            funcion,
            _version(),
            principal=_principal(rol="superadmin", organizacion=uuid.uuid4()),
        )

        assert "revisar" in acciones
        assert "suspender" in acciones

    def test_ni_el_informador_ni_el_usuario_de_la_casa(self):
        """Estar dentro de la organización no basta: revisar es del rol que administra."""
        from server.app.modules.redaccion.funciones_acciones import acciones_permitidas

        casa = uuid.uuid4()
        funcion = _funcion(organizacion_id=casa)

        for rol in ("user", "informer"):
            acciones = acciones_permitidas(
                funcion, _version(), principal=_principal(rol=rol, organizacion=casa)
            )

            assert "revisar" not in acciones, rol
            assert "suspender" not in acciones, rol


class TestRevisarEsDeOtraPersona:
    """Ser administrador no autoriza a revisarse a uno mismo. Es la otra mitad de la decisión."""

    def test_la_administradora_que_escribio_la_funcion_no_la_revisa(self):
        from server.app.modules.redaccion.funciones_acciones import acciones_permitidas

        casa, quien = uuid.uuid4(), uuid.uuid4()
        funcion = _funcion(organizacion_id=casa, creada_por=quien)

        acciones = acciones_permitidas(
            funcion,
            _version(),
            principal=_principal(rol="admin", organizacion=casa, user_id=quien),
        )

        assert "revisar" not in acciones
        assert "suspender" not in acciones
        # Y sigue pudiendo lo suyo: versionar y retirar son de quien escribe.
        assert "versionar" in acciones
        assert "retirar" in acciones

    def test_tampoco_el_superadministrador_que_la_escribio(self):
        """El rango no es la excepción. Si lo fuera, bastaría con escribir siendo superadmin."""
        from server.app.modules.redaccion.funciones_acciones import acciones_permitidas

        casa, quien = uuid.uuid4(), uuid.uuid4()
        funcion = _funcion(organizacion_id=casa, creada_por=quien)

        acciones = acciones_permitidas(
            funcion,
            _version(),
            principal=_principal(rol="superadmin", organizacion=casa, user_id=quien),
        )

        assert "revisar" not in acciones


class TestLaOIATIRevisaFueraYNadieEspera:
    """Decidido el 2026-09-29: no hay ruta automática a la OIATI, y **no la va a haber**.

    Lo que se comprueba aquí no es que falte una pantalla —eso no se puede comprobar—, sino lo
    único que importa: que **declarar datos personales no añade ninguna puerta**. El día que
    alguien añada un encaminamiento, lo que se colará con él es la espera, y estos tests se
    pondrán rojos antes de que llegue a producción.
    """

    @staticmethod
    def _contrato(categorias):
        from server.app.modules.redaccion.contracts.funciones import ContratoFuncion

        return ContratoFuncion(
            slots=[],
            parametros=[],
            finalidad="Contar filas del fichero de personal",
            categorias_datos=categorias,
        )

    @pytest.mark.asyncio
    async def test_una_funcion_con_datos_personales_se_puede_ejecutar_en_el_acto(
        self, db_session
    ):
        from server.app.modules.redaccion.funciones_resolver import ResolvedorDeFuncion
        from server.app.modules.redaccion.funciones_service import registrar_version

        funcion, _v = await registrar_version(
            db_session,
            nombre="Listado de personal",
            organizacion_id=uuid.uuid4(),
            code="result = {}",
            contrato=self._contrato(["datos_identificativos", "datos_de_contacto"]),
            declarada_por=uuid.uuid4(),
        )
        await db_session.commit()

        ejecutable = await ResolvedorDeFuncion(db_session).resolver(funcion.id, 1)

        assert ejecutable.code == "result = {}"

    @pytest.mark.asyncio
    async def test_y_ofrece_exactamente_las_mismas_acciones_que_una_sin_datos(self, db_session):
        """Sin esto, la comprobación de arriba se cumpliría con una puerta a medio cerrar."""
        from server.app.modules.redaccion.funciones_acciones import acciones_permitidas
        from server.app.modules.redaccion.funciones_service import registrar_version

        casa = uuid.uuid4()
        quien_revisa = _principal(rol="admin", organizacion=casa)

        acciones = []
        for nombre, categorias in (
            ("Con datos", ["datos_identificativos"]),
            ("Sin datos", ["sin_datos_personales"]),
        ):
            funcion, version = await registrar_version(
                db_session,
                nombre=nombre,
                organizacion_id=casa,
                code="result = {}",
                contrato=self._contrato(categorias),
                declarada_por=uuid.uuid4(),
            )
            acciones.append(acciones_permitidas(funcion, version, principal=quien_revisa))

        assert acciones[0] == acciones[1]

    @pytest.mark.asyncio
    async def test_las_categorias_declaradas_se_conservan_para_quien_revise_fuera(
        self, db_session
    ):
        """La plataforma no encamina, pero sí guarda el dato: es lo que la OIATI va a leer.

        Si esto se perdiera, «la revisión se hace fuera» dejaría de ser una decisión y pasaría a
        ser una imposibilidad.
        """
        from server.app.modules.redaccion.funciones_service import registrar_version

        _f, version = await registrar_version(
            db_session,
            nombre="Listado de personal",
            organizacion_id=uuid.uuid4(),
            code="result = {}",
            contrato=self._contrato(["datos_identificativos", "datos_de_salud"]),
            declarada_por=uuid.uuid4(),
        )
        await db_session.flush()

        assert version.categorias_datos == [
            "datos_identificativos",
            "datos_de_salud",
        ]
