"""AUT.8 (#118), revisado en la PR #210: lo que la red saliente prometía y no cumplía del todo.

La garantía de AUT.8 es que la plataforma pide **sólo** a los servidores que la función declaró,
**sólo** por `https`, y **sin** que una URL pueda costar más de lo que el tope dice. La revisión
de Copilot encontró seis sitios donde esa frase era más fuerte que el código:

1. La lista blanca se comprobaba en la URL inicial y en la final, no en **cada salto**: con
   A (declarado) → B (no declarado) → A, el servidor hablaba con B.
2. Se aceptaba `http`, y la #118 dice «esquema `https`». Un documento en claro se puede alterar
   por el camino.
3. El tope de tamaño se comprobaba **después** de cargar la respuesta entera en memoria.
4. Se bajaba **antes** de validar los slots y el tipo de función: un slot inventado, o una
   función empaquetada, provocaban un `GET` de salida y sólo entonces un 422.
5. El tope **acumulado** de la entrada se aplicaba después de bajarlo todo.
6. El nombre del fichero bajado se tiraba, y el documento llegaba al guion como `<slot>.bin`.

Y uno de forma: el 422 de «una empaquetada no acepta `urls`» se lanzaba dentro de un `try` cuyo
`except Exception` lo convertía en un 502 «falló al ejecutarse».
"""

from __future__ import annotations

import uuid

import pytest


class AlmacenDeMentiraVacio:
    async def put(self, key: str, data: bytes) -> None: ...

    async def get(self, key: str) -> bytes:
        raise FileNotFoundError(key)

    async def delete(self, key: str) -> None: ...

    async def exists(self, key: str) -> bool:
        return False


class TestSeBajaAntesDeEjecutar:
    """Los dos ayudantes de `test_aut8_origenes_declarados`, aquí para no importar entre tests."""

    @staticmethod
    async def _una_funcion(db_session, organizacion, *, origenes):
        from server.app.modules.redaccion.contracts.funciones import (
            ContratoFuncion,
            SlotDeFichero,
        )
        from server.app.modules.redaccion.funciones_service import registrar_version

        funcion, version = await registrar_version(
            db_session,
            nombre=f"Baja el tomo {uuid.uuid4().hex[:8]}",
            organizacion_id=organizacion,
            code="result = {}",
            contrato=ContratoFuncion(
                slots=[SlotDeFichero(slot_id="tomo", kind="pdf", required=True)],
                parametros=[],
                finalidad="Bajar el tomo del presupuesto",
                categorias_datos=["sin_datos_personales"],
                origenes=origenes,
            ),
            declarada_por=uuid.uuid4(),
        )
        version.estado = "registrada"
        db_session.add(version)
        await db_session.flush()
        return funcion

    @staticmethod
    def _pat(organizacion):
        from server.app.core.auth.models import UserInfo

        return UserInfo(
            user_id=f"pat-{uuid.uuid4()}",
            email="cliente@example.test",
            role="admin",
            organizacion_ids=[str(organizacion)],
        )


class TestCadaSaltoTieneQueEstarDeclarado:
    """1 — el hook de petición de `httpx` se dispara también en cada redirección."""

    @pytest.mark.asyncio
    async def test_un_salto_a_un_servidor_no_declarado_se_para(self):
        import httpx

        from server.app.modules.redaccion.funciones_origenes import (
            OrigenNoDeclarado,
            hooks_de_la_descarga,
        )

        hooks = hooks_de_la_descarga(origenes=["sede.gva.es"])

        with pytest.raises(OrigenNoDeclarado):
            for hook in hooks:
                await hook(httpx.Request("GET", "https://intermedio.example/salto"))

    @pytest.mark.asyncio
    async def test_y_la_lista_va_antes_que_la_comprobacion_de_red_publica(self):
        """La lista no necesita DNS: si va primero, un salto no declarado ni siquiera se resuelve."""
        import httpx

        from server.app.modules.redaccion.funciones_origenes import (
            OrigenNoDeclarado,
            hooks_de_la_descarga,
        )

        primero = hooks_de_la_descarga(origenes=["sede.gva.es"])[0]

        with pytest.raises(OrigenNoDeclarado):
            await primero(httpx.Request("GET", "https://intermedio.example/salto"))

    @pytest.mark.asyncio
    async def test_y_la_descarga_los_instala(self, monkeypatch):
        """Sin esto, lo de arriba se cumpliría con una función que nadie llama."""
        import httpx

        from server.app.modules.redaccion import funciones_origenes

        recibidos: dict = {}

        class _Cliente:
            def __init__(self, **kwargs):
                recibidos.update(kwargs)
                raise RuntimeError("basta con ver cómo se construye")

        monkeypatch.setattr(httpx, "AsyncClient", _Cliente)

        with pytest.raises(RuntimeError):
            await funciones_origenes.descargar_de_un_origen_declarado(
                "https://sede.gva.es/tomo.pdf", origenes=["sede.gva.es"]
            )

        nombres = [h.__qualname__ for h in recibidos["event_hooks"]["request"]]
        assert any("lista" in n for n in nombres), nombres


class TestSoloHttps:
    """2 — la #118 dice «esquema `https`»."""

    def test_http_se_rechaza(self):
        from server.app.modules.redaccion.funciones_origenes import (
            OrigenNoDeclarado,
            comprobar_contra_los_origenes,
        )

        with pytest.raises(OrigenNoDeclarado):
            comprobar_contra_los_origenes(
                "http://sede.gva.es/tomo.pdf", origenes=["sede.gva.es"]
            )

    def test_https_sigue_valiendo(self):
        from server.app.modules.redaccion.funciones_origenes import (
            comprobar_contra_los_origenes,
        )

        assert (
            comprobar_contra_los_origenes(
                "https://sede.gva.es/tomo.pdf", origenes=["sede.gva.es"]
            )
            == "sede.gva.es"
        )


class _RespuestaATrozos:
    """Una respuesta que se sirve a trozos y cuenta cuántos se han leído."""

    def __init__(self, trozos: int, tamano: int) -> None:
        self.trozos = trozos
        self.tamano = tamano
        self.leidos = 0

    async def aiter_bytes(self):
        for _ in range(self.trozos):
            self.leidos += 1
            yield b"x" * self.tamano


class TestElTopeSeAplicaLeyendo:
    """3 — un servidor declarado no puede hacer que el proceso reserve memoria sin límite."""

    @pytest.mark.asyncio
    async def test_se_deja_de_leer_en_cuanto_se_pasa(self):
        from server.app.modules.redaccion.funciones_origenes import (
            OrigenNoDeclarado,
            leer_con_tope,
        )

        respuesta = _RespuestaATrozos(trozos=1000, tamano=1024)

        with pytest.raises(OrigenNoDeclarado):
            await leer_con_tope(respuesta, maximo_bytes=10 * 1024)

        # Once trozos de 1 KB pasan de 10 KB: no se leen los otros 989.
        assert respuesta.leidos == 11

    @pytest.mark.asyncio
    async def test_lo_que_cabe_se_lee_entero(self):
        from server.app.modules.redaccion.funciones_origenes import leer_con_tope

        respuesta = _RespuestaATrozos(trozos=10, tamano=1024)

        contenido = await leer_con_tope(respuesta, maximo_bytes=10 * 1024)

        assert len(contenido) == 10 * 1024


class _Bajadas:
    """Un descargador de mentira que apunta lo que se le pide."""

    def __init__(self, *, tamano: int = 10, nombre: str = "tomo.pdf") -> None:
        self.urls: list[str] = []
        self.topes: list[int] = []
        self.tamano = tamano
        self.nombre = nombre

    async def __call__(self, url, *, origenes, maximo_bytes=None, **kwargs):
        self.urls.append(url)
        self.topes.append(maximo_bytes)
        # Como el de verdad: no lee más allá del tope que le dan.
        return b"x" * min(self.tamano, maximo_bytes or self.tamano), self.nombre


def _instalar(monkeypatch, bajadas):
    from server.app.routers.redaccion import funciones_run_router

    monkeypatch.setattr(funciones_run_router, "descargar_de_un_origen_declarado", bajadas)


class _SandboxQueApunta:
    def __init__(self) -> None:
        self.recibido: dict = {}

    async def execute_extraction_script(self, **kwargs):
        from datetime import datetime, timezone

        from server.app.modules.redaccion.pipelines.contracts import (
            ExtractionProvenance,
            ExtractionResult,
        )

        self.recibido = kwargs
        return ExtractionResult(
            provenance=ExtractionProvenance(
                pipeline_id="p", source_ref="s", extracted_at=datetime.now(timezone.utc)
            )
        )


class TestSeValidaAntesDeSalirARed:
    """4 — una petición que va a dar 422 no puede haber hablado antes con nadie de fuera."""

    @pytest.mark.asyncio
    async def test_un_slot_que_el_contrato_no_declara_no_provoca_ninguna_descarga(
        self, db_session, monkeypatch
    ):
        from fastapi import HTTPException

        from server.app.routers.redaccion.funciones_run_router import (
            EjecutarRequest,
            ejecutar_funcion_por_api,
        )

        bajadas = _Bajadas()
        _instalar(monkeypatch, bajadas)
        organizacion = uuid.uuid4()
        funcion = await TestSeBajaAntesDeEjecutar._una_funcion(
            db_session, organizacion, origenes=["sede.gva.es"]
        )

        with pytest.raises(HTTPException) as fallo:
            await ejecutar_funcion_por_api(
                funcion_id=funcion.id,
                body=EjecutarRequest(
                    version=1, urls={"inventado": "https://sede.gva.es/tomo.pdf"}
                ),
                principal=TestSeBajaAntesDeEjecutar._pat(organizacion),
                session=db_session,
                sandbox=_SandboxQueApunta(),
                almacen=AlmacenDeMentiraVacio(),
            )

        assert fallo.value.status_code == 422
        assert "inventado" in fallo.value.detail
        assert bajadas.urls == []

    @pytest.mark.asyncio
    async def test_una_empaquetada_con_urls_da_422_sin_descargar(
        self, db_session, monkeypatch
    ):
        """Y 422, no 502: el `except Exception` de la rama ya no se lo traga."""
        from fastapi import HTTPException

        from server.app.routers.redaccion.funciones_run_router import (
            EjecutarRequest,
            ejecutar_funcion_por_api,
        )

        bajadas = _Bajadas()
        _instalar(monkeypatch, bajadas)
        organizacion = uuid.uuid4()
        funcion = await TestSeBajaAntesDeEjecutar._una_funcion(
            db_session, organizacion, origenes=["sede.gva.es"]
        )
        funcion.origen = "paquete"
        funcion.entry_point = "no.se.llega:a_ejecutar"
        db_session.add(funcion)
        await db_session.flush()

        with pytest.raises(HTTPException) as fallo:
            await ejecutar_funcion_por_api(
                funcion_id=funcion.id,
                body=EjecutarRequest(
                    version=1, urls={"tomo": "https://sede.gva.es/tomo.pdf"}
                ),
                principal=TestSeBajaAntesDeEjecutar._pat(organizacion),
                session=db_session,
                sandbox=_SandboxQueApunta(),
                almacen=AlmacenDeMentiraVacio(),
            )

        assert fallo.value.status_code == 422
        assert "empaquetada" in fallo.value.detail
        assert bajadas.urls == []


class TestElTopeAcumuladoCuentaMientrasSeBaja:
    """5 — cada descarga lee como mucho lo que queda del tope total de la entrada."""

    @pytest.mark.asyncio
    async def test_cada_descarga_recibe_lo_que_queda(self, db_session, monkeypatch):
        from server.app.modules.redaccion.contracts.funciones import (
            ContratoFuncion,
            SlotDeFichero,
        )
        from server.app.modules.redaccion.funciones_service import (
            MAXIMO_BYTES_DE_ENTRADA,
            registrar_version,
        )
        from server.app.routers.redaccion.funciones_run_router import (
            EjecutarRequest,
            ejecutar_funcion_por_api,
        )

        cuarenta_mb = 40 * 1024 * 1024
        bajadas = _Bajadas(tamano=cuarenta_mb)
        _instalar(monkeypatch, bajadas)
        organizacion = uuid.uuid4()
        funcion, version = await registrar_version(
            db_session,
            nombre=f"Dos tomos {uuid.uuid4().hex[:8]}",
            organizacion_id=organizacion,
            code="result = {}",
            contrato=ContratoFuncion(
                slots=[
                    SlotDeFichero(slot_id="uno", kind="pdf", required=True),
                    SlotDeFichero(slot_id="dos", kind="pdf", required=True),
                ],
                parametros=[],
                finalidad="Bajar dos tomos",
                categorias_datos=["sin_datos_personales"],
                origenes=["sede.gva.es"],
            ),
            declarada_por=uuid.uuid4(),
        )
        version.estado = "registrada"
        db_session.add(version)
        await db_session.flush()

        await ejecutar_funcion_por_api(
            funcion_id=funcion.id,
            body=EjecutarRequest(
                version=1,
                urls={
                    "uno": "https://sede.gva.es/uno.pdf",
                    "dos": "https://sede.gva.es/dos.pdf",
                },
            ),
            principal=TestSeBajaAntesDeEjecutar._pat(organizacion),
            session=db_session,
            sandbox=_SandboxQueApunta(),
            almacen=AlmacenDeMentiraVacio(),
        )

        # La primera puede leer el tope de un documento; la segunda, sólo lo que queda de los 64
        # MB después de los 40 de la primera. Sin el tope acumulado leería otros 50.
        assert bajadas.topes[0] == 50 * 1024 * 1024
        assert bajadas.topes[1] == MAXIMO_BYTES_DE_ENTRADA - cuarenta_mb


class TestElNombreBajadoLlegaAlGuion:
    """6 — pandas elige el motor por la extensión: `<slot>.bin` no es un `.xlsx`."""

    @pytest.mark.asyncio
    async def test_el_guion_recibe_el_nombre_con_su_extension(
        self, db_session, monkeypatch
    ):
        from server.app.routers.redaccion.funciones_run_router import (
            EjecutarRequest,
            ejecutar_funcion_por_api,
        )

        _instalar(monkeypatch, _Bajadas(nombre="presupuesto-2026.pdf"))
        organizacion = uuid.uuid4()
        funcion = await TestSeBajaAntesDeEjecutar._una_funcion(
            db_session, organizacion, origenes=["sede.gva.es"]
        )
        sandbox = _SandboxQueApunta()

        await ejecutar_funcion_por_api(
            funcion_id=funcion.id,
            body=EjecutarRequest(
                version=1, urls={"tomo": "https://sede.gva.es/presupuesto-2026.pdf"}
            ),
            principal=TestSeBajaAntesDeEjecutar._pat(organizacion),
            session=db_session,
            sandbox=sandbox,
            almacen=AlmacenDeMentiraVacio(),
        )

        assert sandbox.recibido["file_name"] == "presupuesto-2026.pdf"
