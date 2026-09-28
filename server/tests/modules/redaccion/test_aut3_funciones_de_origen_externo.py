"""AUT.3 (issue #114) — registrar un cuaderno que se ejecuta fuera, sin ejecutarlo aquí.

**El problema es de registro, no de ejecución.** Una organización que hace su trabajo con
cuadernos escritos por agentes de código no sabe qué cuadernos circulan, quién los usa ni qué
versión. Las normas de desarrollo ciudadano exigen registrar antes de compartir y prohíben la
distribución informal, y hasta aquí el catálogo sólo admitía lo que él mismo ejecuta
(`autoservicio`) o lo que llega por *entry point* (`paquete`): un cuaderno no tenía dónde
registrarse.

**Registrarlo sin ejecutarlo respeta además la soberanía local.** El código sigue corriendo donde
corría, con las credenciales de quien lo usa. La plataforma no toca el dato; sabe que el cuaderno
existe, de qué versión, para qué se declaró y quién responde de él.

**La auditoría corre, y con perfil informativo.** Un cuaderno que se ejecuta fuera usa red y
disco legítimamente, así que bloquear su registro por eso sería exigirle a un programa de fuera
las reglas del sandbox de dentro. Los hallazgos constan y van a la cola de revisión; no impiden
registrar. Bloquear sería, además, aprobación previa por la puerta de atrás, que es justo lo que
la Instrucció prohíbe en el nivel 2.

**Y suspender una función externa es un aviso, no un cerrojo**, porque la plataforma no puede
impedir que se ejecute fuera. Se dice honestamente en vez de aparentar un control que no existe.
"""

from __future__ import annotations

import json
import uuid

import pytest

CUADERNO = json.dumps(
    {"cells": [{"cell_type": "code", "source": ["import requests\\n"]}]}
)


def _contrato(finalidad: str = "Extraer las subvenciones nominativas del presupuesto"):
    from server.app.modules.redaccion.contracts.funciones import ContratoFuncion

    return ContratoFuncion(
        slots=[],
        parametros=[],
        finalidad=finalidad,
        categorias_datos=["sin_datos_personales"],
    )


class TestElTercerOrigen:

    def test_externa_es_un_origen_conocido(self):
        from server.app.modules.redaccion.funciones_service import (
            datos_de_version_coherentes,
        )

        datos_de_version_coherentes(
            origen="externa",
            code=CUADERNO,
            finalidad="Extraer subvenciones",
            declarada_por=uuid.uuid4(),
            categorias_datos=["sin_datos_personales"],
            entorno_ejecucion="cuaderno en el equipo de la persona",
        )

    def test_exige_decir_donde_se_ejecuta(self):
        """Es el dato que distingue este origen: la plataforma **no** lo ejecuta, así que sin
        saber dónde corre, el registro no dice de qué responde nadie."""
        from server.app.modules.redaccion.funciones_service import (
            FuncionIncoherente,
            datos_de_version_coherentes,
        )

        with pytest.raises(FuncionIncoherente, match="dónde se ejecuta"):
            datos_de_version_coherentes(
                origen="externa",
                code=CUADERNO,
                finalidad="Extraer subvenciones",
                declarada_por=uuid.uuid4(),
                categorias_datos=["sin_datos_personales"],
            )

    def test_exige_el_fichero(self):
        """El hash del fichero es la versión, así que sin fichero no hay nada que versionar."""
        from server.app.modules.redaccion.funciones_service import (
            FuncionIncoherente,
            datos_de_version_coherentes,
        )

        with pytest.raises(FuncionIncoherente, match="fichero"):
            datos_de_version_coherentes(
                origen="externa",
                code=None,
                finalidad="Extraer subvenciones",
                declarada_por=uuid.uuid4(),
                categorias_datos=["sin_datos_personales"],
                entorno_ejecucion="un cuaderno en la nube",
            )

    def test_exige_la_declaracion_responsable(self):
        """La Instrucció la exige **antes de compartir**, y registrar es compartir."""
        from server.app.modules.redaccion.funciones_service import (
            FuncionIncoherente,
            datos_de_version_coherentes,
        )

        with pytest.raises(FuncionIncoherente, match="finalidad"):
            datos_de_version_coherentes(
                origen="externa",
                code=CUADERNO,
                declarada_por=uuid.uuid4(),
                categorias_datos=["sin_datos_personales"],
                entorno_ejecucion="un cuaderno en la nube",
            )

    def test_no_lleva_punto_de_entrada_ni_version_de_paquete(self):
        """Sin esto, «externa» sería un alias de «paquete» con otro nombre."""
        from server.app.modules.redaccion.funciones_service import (
            FuncionIncoherente,
            datos_de_version_coherentes,
        )

        with pytest.raises(FuncionIncoherente):
            datos_de_version_coherentes(
                origen="externa",
                code=CUADERNO,
                finalidad="Extraer subvenciones",
                declarada_por=uuid.uuid4(),
                categorias_datos=["sin_datos_personales"],
                entorno_ejecucion="un cuaderno en la nube",
                entry_point="paquete:funcion",
            )


class TestRegistrarUnCuaderno:

    @pytest.mark.asyncio
    async def test_queda_registrado_con_su_hash_y_donde_corre(self, db_session):
        from server.app.modules.redaccion.funciones_service import (
            registrar_version,
            sha256_del_codigo,
        )

        funcion, version = await registrar_version(
            db_session,
            nombre="Subvenciones nominativas",
            organizacion_id=uuid.uuid4(),
            code=CUADERNO,
            contrato=_contrato(),
            declarada_por=uuid.uuid4(),
            origen="externa",
            entorno_ejecucion="cuaderno en el equipo de la persona",
        )

        assert funcion.origen == "externa"
        assert version.estado == "registrada"
        assert version.code_sha256 == sha256_del_codigo(CUADERNO)
        assert version.entorno_ejecucion == "cuaderno en el equipo de la persona"

    @pytest.mark.asyncio
    async def test_los_hallazgos_de_la_auditoria_no_bloquean_el_registro(self, db_session):
        """Perfil informativo: un cuaderno que corre fuera usa red y disco legítimamente.

        Bloquear aquí sería exigirle a un programa de fuera las reglas del sandbox de dentro, y
        además sería aprobación previa por la puerta de atrás.
        """
        from server.app.modules.redaccion.funciones_service import registrar_version

        _funcion, version = await registrar_version(
            db_session,
            nombre="Con red",
            organizacion_id=uuid.uuid4(),
            code=CUADERNO,
            contrato=_contrato(),
            declarada_por=uuid.uuid4(),
            origen="externa",
            entorno_ejecucion="un cuaderno en la nube",
            audit_result={
                "approved": False,
                "risk_level": "CRITICAL",
                "findings": [{"code": "RED_SALIENTE", "severity": "critical"}],
            },
        )

        assert version.estado == "registrada"
        assert version.audit_result_json["findings"][0]["code"] == "RED_SALIENTE"

    @pytest.mark.asyncio
    async def test_es_de_nivel_2_como_cualquier_funcion_de_su_organizacion(self, db_session):
        """El nivel se deriva del alcance, no del origen: de mi organización y sin publicar."""
        from server.app.modules.redaccion.funciones_service import registrar_version

        funcion, _version = await registrar_version(
            db_session,
            nombre="De la casa",
            organizacion_id=uuid.uuid4(),
            code=CUADERNO,
            contrato=_contrato(),
            declarada_por=uuid.uuid4(),
            origen="externa",
            entorno_ejecucion="un cuaderno en la nube",
        )

        assert funcion.nivel == 2


class TestNoSeEjecutaAqui:

    def test_la_accion_de_versionar_sigue_estando(self):
        """Se versiona registrando otro fichero, al contrario que una de paquete —que se
        versiona con `pip`—. Es la diferencia que hace que «externa» no sea «paquete»."""
        from types import SimpleNamespace

        from server.app.modules.redaccion.funciones_acciones import acciones_permitidas

        organizacion = uuid.uuid4()
        autora = uuid.uuid4()
        funcion = SimpleNamespace(
            origen="externa",
            organizacion_id=organizacion,
            creada_por=autora,
            publicada_en=None,
            promocion_solicitada_en=None,
        )
        version = SimpleNamespace(estado="registrada")
        principal = SimpleNamespace(
            user_id=str(autora),
            organizacion_ids=(str(organizacion),),
            is_superadmin=False,
            is_admin=False,
        )

        assert "versionar" in acciones_permitidas(funcion, version, principal=principal)


class TestLaAuditoriaInformativa:
    """Corre y consta; no decide. La puerta es de lo que la plataforma ejecuta."""

    def test_saca_el_codigo_de_las_celdas_de_un_cuaderno(self):
        from server.app.modules.redaccion.services.cuaderno import codigo_de_cuaderno

        # Se construye con `json.dumps` y no a mano: un cuaderno lleva saltos de linea dentro de
        # sus celdas, y escribirlos a mano en un literal es como se cuela un JSON invalido que
        # hace fallar al test por algo que no es lo que prueba.
        cuaderno = json.dumps(
            {
                "cells": [
                    {"cell_type": "markdown", "source": ["# Titulo\n"]},
                    {"cell_type": "code", "source": ["import pandas\n", "x = 1\n"]},
                    {"cell_type": "code", "source": ["print(x)\n"]},
                ]
            }
        )

        codigo = codigo_de_cuaderno(cuaderno)

        assert "import pandas" in codigo
        assert "print(x)" in codigo
        assert "# Titulo" not in codigo

    def test_un_py_es_su_propio_codigo(self):
        from server.app.modules.redaccion.services.cuaderno import codigo_de_cuaderno

        assert codigo_de_cuaderno("import requests\n") == "import requests\n"

    def test_lo_que_no_se_puede_leer_da_none_y_no_cadena_vacia(self):
        """«No pude mirar» y «miré y no hay nada» no son lo mismo: quien llama lo anota."""
        from server.app.modules.redaccion.services.cuaderno import codigo_de_cuaderno

        assert codigo_de_cuaderno('{"esto": "no es un cuaderno"}') is None
        assert codigo_de_cuaderno("{ roto") is None
        assert codigo_de_cuaderno("") is None

    def test_el_resultado_no_dice_aprobado_porque_no_hubo_puerta(self):
        from server.app.routers.redaccion.funciones_router import _auditoria_informativa

        resultado = _auditoria_informativa("import os\nos.system('ls')\n")

        assert resultado["perfil"] == "informativo"
        assert "approved" not in resultado
        assert resultado["findings"], "un `os.system` tiene que dejar constancia"

    def test_un_fichero_ilegible_lo_dice_en_vez_de_fingir_que_esta_limpio(self):
        from server.app.routers.redaccion.funciones_router import _auditoria_informativa

        resultado = _auditoria_informativa('{"sin": "celdas"}')

        assert resultado["no_se_pudo_auditar"]
        assert resultado["findings"] == []


class TestNoSeEjecutaAquiPorLaApi:

    @pytest.mark.asyncio
    async def test_pedir_que_se_ejecute_da_409_con_el_motivo_y_donde_si_corre(self, db_session):
        """**409 y no 423**: un 423 dice «espera o cambia de versión», y aquí no hay nada que
        esperar. No va a correr aquí nunca, y quien integra necesita distinguirlo."""
        from fastapi import HTTPException

        from server.app.core.auth.models import UserInfo
        from server.app.modules.redaccion.funciones_service import registrar_version
        from server.app.routers.redaccion.funciones_run_router import (
            EjecutarRequest,
            ejecutar_funcion_por_api,
        )

        organizacion = uuid.uuid4()
        funcion, _version = await registrar_version(
            db_session,
            nombre="Presupuesto propio",
            organizacion_id=organizacion,
            code=CUADERNO,
            contrato=_contrato(),
            declarada_por=uuid.uuid4(),
            origen="externa",
            entorno_ejecucion="un cuaderno en el equipo de la persona",
        )
        await db_session.commit()

        with pytest.raises(HTTPException) as fallo:
            await ejecutar_funcion_por_api(
                funcion.id,
                EjecutarRequest(version=1, ficheros={}, parametros={}),
                principal=UserInfo(
                    user_id=f"pat-{uuid.uuid4()}",
                    email="cliente@example.test",
                    role="admin",
                    organizacion_ids=[organizacion],
                ),
                session=db_session,
                sandbox=object(),
                almacen=object(),
            )

        assert fallo.value.status_code == 409
        assert "no la ejecuta" in fallo.value.detail
        assert "el equipo de la persona" in fallo.value.detail


class TestEntraEnLaMismaCola:
    """La revisión posterior no distingue orígenes, y este test lo fija.

    No hizo falta escribir código para esto: la cola se construye sobre las versiones
    `registrada` y `suspendida` sin mirar el origen. Se prueba igualmente, porque «funciona por
    casualidad» y «funciona por diseño» se distinguen el día que alguien toque la consulta.
    """

    @pytest.mark.asyncio
    async def test_una_externa_aparece_sin_revisar(self, db_session):
        from server.app.core.auth.models import UserInfo
        from server.app.modules.redaccion.funciones_service import registrar_version
        from server.app.routers.redaccion.funciones_router import cola_de_revision

        organizacion = uuid.uuid4()
        await registrar_version(
            db_session,
            nombre="Cuaderno del presupuesto",
            organizacion_id=organizacion,
            code=CUADERNO,
            contrato=_contrato(),
            declarada_por=uuid.uuid4(),
            origen="externa",
            entorno_ejecucion="un cuaderno en la nube",
        )
        await db_session.commit()

        cola = await cola_de_revision(
            estado="sin_revisar",
            muestra=None,
            principal=UserInfo(
                user_id=str(uuid.uuid4()),
                email="revisa@uji.es",
                role="admin",
                organizacion_ids=[str(organizacion)],
            ),
            session=db_session,
        )

        assert [f.funcion_nombre for f in cola] == ["Cuaderno del presupuesto"]

    @pytest.mark.asyncio
    async def test_y_sus_hallazgos_llegan_a_quien_revisa(self, db_session):
        """Es a lo que sirve el perfil informativo: no bloquea, pero se lee."""
        from server.app.core.auth.models import UserInfo
        from server.app.modules.redaccion.funciones_service import registrar_version
        from server.app.routers.redaccion.funciones_router import (
            _auditoria_informativa,
            cola_de_revision,
        )

        organizacion = uuid.uuid4()
        await registrar_version(
            db_session,
            nombre="Con os.system",
            organizacion_id=organizacion,
            code="import os\nos.system('ls')\n",
            contrato=_contrato(),
            declarada_por=uuid.uuid4(),
            origen="externa",
            entorno_ejecucion="el equipo de la persona",
            audit_result=_auditoria_informativa("import os\nos.system('ls')\n"),
        )
        await db_session.commit()

        cola = await cola_de_revision(
            estado="sin_revisar",
            muestra=None,
            principal=UserInfo(
                user_id=str(uuid.uuid4()),
                email="revisa@uji.es",
                role="admin",
                organizacion_ids=[str(organizacion)],
            ),
            session=db_session,
        )

        assert cola[0].hallazgos, "la revisión posterior tiene que poder leer lo que salió"
