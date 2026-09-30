"""AUT.7 (issue #117) — el fichero se guarda, se sirve una vez, y caduca.

La primera mitad de AUT.7 dejó al guion escribiendo y al sandbox devolviendo el contenido. Ahí
todavía no vale de nada: el contenido viaja en la respuesta del sandbox y se pierde. Esto es lo
que lo convierte en algo que una persona se lleva.

**Tres cosas que se comprueban aquí y ninguna es obvia:**

1. **Se guarda por `StorageService`**, nunca en disco local. Es la regla de portabilidad, y aquí
   además es literal: el contenedor de la API es efímero y un fichero escrito en su disco no
   existe en la siguiente petición.
2. **La descarga es de quien la ejecutó.** Un artefacto es el resultado de correr código sobre
   datos de una organización; servirlo a otra sería la fuga más directa que este bloque puede
   producir. Y **404 y no 403** sobre lo ajeno, igual que en el resto del catálogo: un 403 ya
   cuenta que ese fichero existe.
3. **La retención significa algo.** Declarar `retencion_dias` y luego servir el fichero para
   siempre sería una promesa sin nada detrás — que es peor que no prometer nada, porque alguien
   la cita. Un artefacto caducado no se sirve, y hay por dónde borrarlo.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest


def _contrato(**kw):
    from server.app.modules.redaccion.contracts.funciones import (
        ArtefactosDeSalida,
        ContratoFuncion,
    )

    datos = {
        "slots": [],
        "parametros": [],
        "finalidad": "Sacar el CSV limpio del presupuesto",
        "categorias_datos": ["sin_datos_personales"],
        "artefactos": ArtefactosDeSalida(
            maximo=2, maximo_bytes=1_000_000, retencion_dias=7
        ),
    }
    datos.update(kw)
    return ContratoFuncion(**datos)


class AlmacenDeMentira:
    """Un `StorageService` en memoria. Guarda lo que le den y dice dónde lo puso."""

    def __init__(self) -> None:
        self.contenido: dict[str, bytes] = {}
        self.borrados: list[str] = []

    async def put(self, key: str, data: bytes) -> None:
        self.contenido[key] = data

    async def get(self, key: str) -> bytes:
        if key not in self.contenido:
            raise FileNotFoundError(key)
        return self.contenido[key]

    async def delete(self, key: str) -> None:
        self.contenido.pop(key, None)
        self.borrados.append(key)

    async def exists(self, key: str) -> bool:
        return key in self.contenido


async def _una_funcion(db_session, organizacion):
    """Una función de verdad en la base.

    Hace falta porque `hub_funcion_artefactos.funcion_id` tiene clave ajena con `ON DELETE
    CASCADE`, y eso **es lo que se quiere**: si la función se retira, sus ficheros se van con
    ella. Un uuid inventado en el test pasaría por encima de esa garantía sin probarla.
    """
    from server.app.modules.redaccion.contracts.funciones import ContratoFuncion
    from server.app.modules.redaccion.funciones_service import registrar_version

    funcion, _version = await registrar_version(
        db_session,
        nombre=f"Función de prueba {uuid.uuid4().hex[:8]}",
        organizacion_id=organizacion,
        code="result = {}",
        contrato=ContratoFuncion(
            slots=[],
            parametros=[],
            finalidad="Sacar el CSV limpio del presupuesto",
            categorias_datos=["sin_datos_personales"],
        ),
        declarada_por=uuid.uuid4(),
    )
    await db_session.flush()
    return funcion


def _bruto(nombre: str, contenido: bytes):
    import hashlib

    from server.app.core.sandbox_client import ArtefactoEnBruto

    return ArtefactoEnBruto(
        nombre=nombre,
        media_type="text/csv",
        bytes=len(contenido),
        sha256=hashlib.sha256(contenido).hexdigest(),
        contenido=contenido,
    )


class TestSeGuardanPorStorageService:

    @pytest.mark.asyncio
    async def test_el_contenido_acaba_en_el_almacen(self, db_session):
        from server.app.modules.redaccion.funciones_artefactos import guardar_artefactos

        almacen = AlmacenDeMentira()
        organizacion = uuid.uuid4()
        funcion = await _una_funcion(db_session, organizacion)

        guardados = await guardar_artefactos(
            db_session,
            [_bruto("limpio.csv", b"a,b\n1,2\n")],
            almacen=almacen,
            organizacion_id=organizacion,
            funcion_id=funcion.id,
            version=1,
            retencion_dias=7,
        )

        assert len(guardados) == 1
        assert almacen.contenido[guardados[0].storage_key] == b"a,b\n1,2\n"

    @pytest.mark.asyncio
    async def test_dos_ejecuciones_de_la_misma_funcion_no_se_pisan(self, db_session):
        """Sin esto, la segunda ejecución sobreescribe el fichero que la primera entregó.

        El nombre lo pone el guion y suele ser el mismo (`salida.csv`), así que la clave no
        puede salir sólo de la función y el nombre.
        """
        from server.app.modules.redaccion.funciones_artefactos import guardar_artefactos

        almacen = AlmacenDeMentira()
        organizacion = uuid.uuid4()
        funcion = await _una_funcion(db_session, organizacion)
        comun = dict(
            almacen=almacen,
            organizacion_id=organizacion,
            funcion_id=funcion.id,
            version=1,
            retencion_dias=7,
        )

        una = await guardar_artefactos(db_session, [_bruto("salida.csv", b"uno")], **comun)
        otra = await guardar_artefactos(db_session, [_bruto("salida.csv", b"dos")], **comun)

        assert una[0].storage_key != otra[0].storage_key
        assert almacen.contenido[una[0].storage_key] == b"uno"
        assert almacen.contenido[otra[0].storage_key] == b"dos"

    @pytest.mark.asyncio
    async def test_queda_registrado_con_su_hash_y_su_caducidad(self, db_session):
        from sqlalchemy import select

        from server.app.modules.redaccion.database.models import HubFuncionArtefacto
        from server.app.modules.redaccion.funciones_artefactos import guardar_artefactos

        organizacion = uuid.uuid4()
        funcion = await _una_funcion(db_session, organizacion)
        await guardar_artefactos(
            db_session,
            [_bruto("limpio.csv", b"a,b\n1,2\n")],
            almacen=AlmacenDeMentira(),
            organizacion_id=organizacion,
            funcion_id=funcion.id,
            version=1,
            retencion_dias=7,
        )
        await db_session.flush()

        fila = (
            await db_session.execute(
                select(HubFuncionArtefacto).where(
                    HubFuncionArtefacto.organizacion_id == organizacion
                )
            )
        ).scalar_one()

        assert fila.sha256 == _bruto("limpio.csv", b"a,b\n1,2\n").sha256
        assert fila.expira_en > datetime.now(timezone.utc) + timedelta(days=6)
        assert fila.expira_en < datetime.now(timezone.utc) + timedelta(days=8)


class TestLaDescargaEsDeQuienLaEjecuto:

    @pytest.mark.asyncio
    async def test_su_organizacion_lo_recibe(self, db_session):
        from server.app.modules.redaccion.funciones_artefactos import (
            artefacto_para_descargar,
            guardar_artefactos,
        )

        almacen = AlmacenDeMentira()
        organizacion = uuid.uuid4()
        funcion = await _una_funcion(db_session, organizacion)
        guardados = await guardar_artefactos(
            db_session,
            [_bruto("limpio.csv", b"contenido")],
            almacen=almacen,
            organizacion_id=organizacion,
            funcion_id=funcion.id,
            version=1,
            retencion_dias=7,
        )
        await db_session.flush()

        fila, datos = await artefacto_para_descargar(
            db_session, guardados[0].id, organizacion_id=organizacion, almacen=almacen
        )

        assert datos == b"contenido"
        assert fila.nombre == "limpio.csv"

    @pytest.mark.asyncio
    async def test_otra_organizacion_no_sabe_ni_que_existe(self, db_session):
        """404 y no 403: un 403 ya cuenta que ese fichero existe en otra organización."""
        from server.app.modules.redaccion.funciones_artefactos import (
            ArtefactoNoDisponible,
            artefacto_para_descargar,
            guardar_artefactos,
        )

        almacen = AlmacenDeMentira()
        organizacion = uuid.uuid4()
        funcion = await _una_funcion(db_session, organizacion)
        guardados = await guardar_artefactos(
            db_session,
            [_bruto("limpio.csv", b"contenido")],
            almacen=almacen,
            organizacion_id=organizacion,
            funcion_id=funcion.id,
            version=1,
            retencion_dias=7,
        )
        await db_session.flush()

        with pytest.raises(ArtefactoNoDisponible):
            await artefacto_para_descargar(
                db_session, guardados[0].id, organizacion_id=uuid.uuid4(), almacen=almacen
            )


class TestLaRetencionSignificaAlgo:

    @pytest.mark.asyncio
    async def test_un_artefacto_caducado_no_se_sirve(self, db_session):
        """Servirlo para siempre convertiría `retencion_dias` en una promesa sin nada detrás."""
        from server.app.modules.redaccion.funciones_artefactos import (
            ArtefactoNoDisponible,
            artefacto_para_descargar,
            guardar_artefactos,
        )

        almacen = AlmacenDeMentira()
        organizacion = uuid.uuid4()
        funcion = await _una_funcion(db_session, organizacion)
        guardados = await guardar_artefactos(
            db_session,
            [_bruto("limpio.csv", b"contenido")],
            almacen=almacen,
            organizacion_id=organizacion,
            funcion_id=funcion.id,
            version=1,
            retencion_dias=7,
        )
        guardados[0].expira_en = datetime.now(timezone.utc) - timedelta(minutes=1)
        db_session.add(guardados[0])
        await db_session.flush()

        with pytest.raises(ArtefactoNoDisponible):
            await artefacto_para_descargar(
                db_session, guardados[0].id, organizacion_id=organizacion, almacen=almacen
            )

    @pytest.mark.asyncio
    async def test_y_hay_por_donde_borrarlo_de_verdad(self, db_session):
        """Dejar de servirlo no es borrarlo, y el argumento de esta issue es de datos.

        El fichero sigue ocupando sitio en el almacenamiento de la organización hasta que algo
        lo quita. Esto es ese algo; **engancharlo a un programador es otra cosa**, y mientras no
        esté enganchado se ejecuta a mano — pero existe y se puede llamar.
        """
        from sqlalchemy import select

        from server.app.modules.redaccion.database.models import HubFuncionArtefacto
        from server.app.modules.redaccion.funciones_artefactos import (
            barrer_artefactos_caducados,
            guardar_artefactos,
        )

        almacen = AlmacenDeMentira()
        organizacion = uuid.uuid4()
        funcion = await _una_funcion(db_session, organizacion)
        guardados = await guardar_artefactos(
            db_session,
            [_bruto("viejo.csv", b"viejo"), _bruto("nuevo.csv", b"nuevo")],
            almacen=almacen,
            organizacion_id=organizacion,
            funcion_id=funcion.id,
            version=1,
            retencion_dias=7,
        )
        guardados[0].expira_en = datetime.now(timezone.utc) - timedelta(days=1)
        db_session.add(guardados[0])
        await db_session.flush()

        borrados = await barrer_artefactos_caducados(db_session, almacen=almacen)

        assert borrados == 1
        assert guardados[0].storage_key in almacen.borrados
        # El que no ha caducado sigue entero: un barrido que se lleva de más es peor que uno
        # que se queda corto.
        assert guardados[1].storage_key in almacen.contenido
        quedan = (
            await db_session.execute(
                select(HubFuncionArtefacto).where(
                    HubFuncionArtefacto.organizacion_id == organizacion
                )
            )
        ).scalars().all()
        assert [f.nombre for f in quedan] == ["nuevo.csv"]


class _SandboxQueProduceFicheros:
    """Un sandbox que devuelve cifras **y** un fichero, como el de verdad con AUT.7."""

    def __init__(self, contenido: bytes = b"a,b\n1,2\n") -> None:
        self.contenido = contenido
        self.topes: dict[str, int] = {}

    async def execute_extraction_script(self, **kwargs):  # pragma: no cover - no se usa
        raise AssertionError(
            "con artefactos declarados hay que llamar a execute_extraction_con_artefactos"
        )

    async def execute_extraction_con_artefactos(
        self, *, artefactos_maximo: int, artefactos_maximo_bytes: int, **kwargs
    ):
        from datetime import datetime, timezone

        from server.app.modules.redaccion.pipelines.contracts import (
            ExtractionProvenance,
            ExtractionResult,
        )

        self.topes = {
            "maximo": artefactos_maximo,
            "maximo_bytes": artefactos_maximo_bytes,
        }
        salida = ExtractionResult(
            provenance=ExtractionProvenance(
                pipeline_id="prueba",
                source_ref="sandbox",
                extracted_at=datetime.now(timezone.utc),
            )
        )
        return salida, [_bruto("limpio.csv", self.contenido)]


class TestDePuntaAPunta:
    """Ejecutar por API, recibir la referencia, y bajarse el fichero."""

    @staticmethod
    async def _una_funcion_con_artefactos(db_session, organizacion):
        from server.app.modules.redaccion.funciones_service import registrar_version

        funcion, version = await registrar_version(
            db_session,
            nombre=f"Produce ficheros {uuid.uuid4().hex[:8]}",
            organizacion_id=organizacion,
            code="result = {}",
            contrato=_contrato(),
            declarada_por=uuid.uuid4(),
        )
        version.estado = "registrada"
        db_session.add(version)
        await db_session.flush()
        return funcion, version

    @staticmethod
    def _pat(organizacion):
        from server.app.core.auth.models import UserInfo

        return UserInfo(
            user_id=f"pat-{uuid.uuid4()}",
            email="cliente@example.test",
            role="admin",
            organizacion_ids=[str(organizacion)],
        )

    @pytest.mark.asyncio
    async def test_la_respuesta_trae_la_referencia_y_no_el_contenido(self, db_session):
        """El Excel no viaja en el JSON de metadatos: viaja su referencia, su hash y su plazo."""
        from server.app.routers.redaccion.funciones_run_router import (
            EjecutarRequest,
            ejecutar_funcion_por_api,
        )

        organizacion = uuid.uuid4()
        funcion, _v = await self._una_funcion_con_artefactos(db_session, organizacion)
        almacen = AlmacenDeMentira()
        sandbox = _SandboxQueProduceFicheros()

        respuesta = await ejecutar_funcion_por_api(
            funcion_id=funcion.id,
            body=EjecutarRequest(version=1),
            principal=self._pat(organizacion),
            session=db_session,
            sandbox=sandbox,
            almacen=almacen,
        )

        assert len(respuesta.artefactos) == 1
        artefacto = respuesta.artefactos[0]
        assert artefacto.nombre == "limpio.csv"
        assert artefacto.descarga == f"/api/v1/funciones/artefactos/{artefacto.id}"
        assert artefacto.sha256 == _bruto("limpio.csv", b"a,b\n1,2\n").sha256
        # Y ni un byte del fichero en la respuesta.
        assert "contenido" not in respuesta.model_dump()["artefactos"][0]

    @pytest.mark.asyncio
    async def test_los_topes_del_contrato_llegan_al_sandbox(self, db_session):
        """Si no llegaran, el tope declarado no lo haría cumplir nadie."""
        from server.app.routers.redaccion.funciones_run_router import (
            EjecutarRequest,
            ejecutar_funcion_por_api,
        )

        organizacion = uuid.uuid4()
        funcion, _v = await self._una_funcion_con_artefactos(db_session, organizacion)
        sandbox = _SandboxQueProduceFicheros()

        await ejecutar_funcion_por_api(
            funcion_id=funcion.id,
            body=EjecutarRequest(version=1),
            principal=self._pat(organizacion),
            session=db_session,
            sandbox=sandbox,
            almacen=AlmacenDeMentira(),
        )

        assert sandbox.topes == {"maximo": 2, "maximo_bytes": 1_000_000}

    @pytest.mark.asyncio
    async def test_y_el_fichero_se_baja_con_su_nombre_y_su_hash(self, db_session):
        from server.app.routers.redaccion.funciones_run_router import (
            EjecutarRequest,
            descargar_artefacto,
            ejecutar_funcion_por_api,
        )

        organizacion = uuid.uuid4()
        funcion, _v = await self._una_funcion_con_artefactos(db_session, organizacion)
        almacen = AlmacenDeMentira()
        principal = self._pat(organizacion)

        respuesta = await ejecutar_funcion_por_api(
            funcion_id=funcion.id,
            body=EjecutarRequest(version=1),
            principal=principal,
            session=db_session,
            sandbox=_SandboxQueProduceFicheros(),
            almacen=almacen,
        )

        bajada = await descargar_artefacto(
            artefacto_id=respuesta.artefactos[0].id,
            principal=principal,
            session=db_session,
            almacen=almacen,
        )

        assert bajada.body == b"a,b\n1,2\n"
        assert bajada.media_type == "text/csv"
        assert "limpio.csv" in bajada.headers["content-disposition"]
        assert bajada.headers["x-artefacto-sha256"] == respuesta.artefactos[0].sha256

    @pytest.mark.asyncio
    async def test_otra_organizacion_recibe_404(self, db_session):
        from fastapi import HTTPException

        from server.app.routers.redaccion.funciones_run_router import (
            EjecutarRequest,
            descargar_artefacto,
            ejecutar_funcion_por_api,
        )

        organizacion = uuid.uuid4()
        funcion, _v = await self._una_funcion_con_artefactos(db_session, organizacion)
        almacen = AlmacenDeMentira()

        respuesta = await ejecutar_funcion_por_api(
            funcion_id=funcion.id,
            body=EjecutarRequest(version=1),
            principal=self._pat(organizacion),
            session=db_session,
            sandbox=_SandboxQueProduceFicheros(),
            almacen=almacen,
        )

        with pytest.raises(HTTPException) as fallo:
            await descargar_artefacto(
                artefacto_id=respuesta.artefactos[0].id,
                principal=self._pat(uuid.uuid4()),
                session=db_session,
                almacen=almacen,
            )

        assert fallo.value.status_code == 404
        # Y el mensaje nombra la retención: un 404 sobre algo que se descargó ayer desconcierta.
        assert "retención" in fallo.value.detail
