"""AUT.8 (issue #118) — una función puede pedir documentos de fuera, y sólo de donde declaró.

**La decisión, del 2026-09-30.** Escribir hacia fuera no tiene sentido para una función de
extracción; **leer sí**: bajar un PDF de la sede de la GVA, el tomo de un presupuesto, una
resolución del BOE. Así que la red saliente se abre, y se abre con dos cerrojos: **sólo `GET`** y
**sólo a los orígenes que la declaración responsable enumera**.

**Por qué el `GET` solo no basta, y por eso hay lista blanca.** Una petición de lectura lleva
datos en la URL: `GET https://donde-sea.example/?nif=12345678Z` es una exfiltración completa y es
un `GET`. Lo que protege el dato no es el método, es el destino.

**Y quien baja es la plataforma, no el guion.** Esto no es un detalle de implementación, es la
garantía:

* La red del sandbox está **cerrada en producción** (`internal: true`). Abrirla para que el guion
  pudiera bajar cosas dejaría la salida abierta a cualquier intento, con la lista blanca
  defendida sólo por código Python **en el mismo proceso que el guion del usuario** — el peor
  sitio posible para un límite de seguridad.
* Haciéndolo desde el servidor, `requests`, `urllib` y `socket` siguen denegados en el auditor, la
  red del sandbox sigue cerrada, y la comprobación vive donde ya está probada: `assert_destino_publico`
  (I15), que comprueba **en cada salto** y por tanto no la burla una redirección.

Así que la frase que sostiene la respuesta de la #121 sigue en pie, y más fuerte: una función
**no puede hablar con nada**; lo que necesita de fuera lo pide la plataforma por ella, sólo por
`GET` y sólo a lo que su declaración enumera.

**Lo que esto no hace**, y se dice aquí para que no se descubra usándolo: un guion **no puede
pedir una URL a mitad de ejecución**. Bajar una página, buscar enlaces dentro y bajar ésos son
dos rondas. Afecta al caso de las subvenciones nominativas de la #120.
"""
from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError


def _contrato(**kw):
    from server.app.modules.redaccion.contracts.funciones import ContratoFuncion

    datos = {
        "slots": [],
        "parametros": [],
        "finalidad": "Bajar el tomo del presupuesto y contar las subvenciones",
        "categorias_datos": ["sin_datos_personales"],
    }
    datos.update(kw)
    return ContratoFuncion(**datos)


class TestLaDeclaracionEnumeraLosOrigenes:

    def test_por_omision_una_funcion_no_sale_a_ninguna_parte(self):
        """El defecto seguro, igual que con los artefactos: la capacidad se pide."""
        assert _contrato().origenes == []

    def test_se_declaran_por_host(self):
        contrato = _contrato(origenes=["sede.gva.es", "www.boe.es"])

        assert contrato.origenes == ["sede.gva.es", "www.boe.es"]

    def test_un_origen_no_es_una_url(self):
        """Se declara el **servidor**, no una dirección concreta.

        Si fuera una URL, habría que declarar cada documento —imposible— o aceptar prefijos, y un
        prefijo invita a `https://sede.gva.es@atacante.example/`, que tiene el origen declarado
        dentro y apunta a otro sitio.
        """
        with pytest.raises(ValidationError):
            _contrato(origenes=["https://sede.gva.es/documentos"])

    def test_ni_un_comodin(self):
        """`*.gva.es` parece razonable y no lo es: cualquiera que consiga un subdominio entra."""
        for malo in ("*", "*.gva.es", ".gva.es", ""):
            with pytest.raises(ValidationError):
                _contrato(origenes=[malo])

    def test_ni_una_direccion_ip(self):
        """Una IP salta la comprobación de nombre y no dice de quién es el servidor."""
        with pytest.raises(ValidationError):
            _contrato(origenes=["93.184.216.34"])


class TestSoloSeBajaDeLoDeclarado:

    def test_una_url_de_un_origen_declarado_pasa(self):
        from server.app.modules.redaccion.funciones_origenes import (
            comprobar_contra_los_origenes,
        )

        comprobar_contra_los_origenes(
            "https://sede.gva.es/documentos/tomo.pdf", origenes=["sede.gva.es"]
        )

    def test_otro_servidor_no(self):
        from server.app.modules.redaccion.funciones_origenes import (
            OrigenNoDeclarado,
            comprobar_contra_los_origenes,
        )

        with pytest.raises(OrigenNoDeclarado):
            comprobar_contra_los_origenes(
                "https://otro.example/x.pdf", origenes=["sede.gva.es"]
            )

    def test_un_subdominio_de_uno_declarado_tampoco(self):
        """Declarar `gva.es` no autoriza `cualquiera.gva.es`: la lista es de servidores.

        Si autorizara subdominios, quien controle uno —o quien consiga que se lo den— hereda el
        permiso sin que nadie lo declarara.
        """
        from server.app.modules.redaccion.funciones_origenes import (
            OrigenNoDeclarado,
            comprobar_contra_los_origenes,
        )

        with pytest.raises(OrigenNoDeclarado):
            comprobar_contra_los_origenes("https://otra.gva.es/x.pdf", origenes=["gva.es"])

    def test_el_truco_del_arroba_no_cuela(self):
        """`https://sede.gva.es@atacante.example/` tiene el origen dentro y va a otro sitio.

        Se compara el **hostname parseado**, no la cadena, que es lo que distingue esta
        comprobación de un `in`.
        """
        from server.app.modules.redaccion.funciones_origenes import (
            OrigenNoDeclarado,
            comprobar_contra_los_origenes,
        )

        with pytest.raises(OrigenNoDeclarado):
            comprobar_contra_los_origenes(
                "https://sede.gva.es@atacante.example/x.pdf", origenes=["sede.gva.es"]
            )

    def test_y_sin_origenes_declarados_no_pasa_nada(self):
        """Una función que no declaró orígenes no baja ni de un sitio."""
        from server.app.modules.redaccion.funciones_origenes import (
            OrigenNoDeclarado,
            comprobar_contra_los_origenes,
        )

        with pytest.raises(OrigenNoDeclarado):
            comprobar_contra_los_origenes("https://sede.gva.es/x.pdf", origenes=[])

    def test_mayusculas_y_puerto_no_despistan(self):
        """`SEDE.GVA.ES:443` es el mismo servidor. Normalizar aquí evita un rechazo falso."""
        from server.app.modules.redaccion.funciones_origenes import (
            comprobar_contra_los_origenes,
        )

        comprobar_contra_los_origenes(
            "https://SEDE.GVA.ES:443/x.pdf", origenes=["sede.gva.es"]
        )


class TestSoloLectura:

    def test_solo_se_permite_http_y_https(self):
        """`file://` leería el disco del servidor, y `ftp://` no es lo que se decidió."""
        from server.app.modules.redaccion.funciones_origenes import (
            OrigenNoDeclarado,
            comprobar_contra_los_origenes,
        )

        for malo in (
            "file:///etc/passwd",
            "ftp://sede.gva.es/x",
            "gopher://sede.gva.es/x",
        ):
            with pytest.raises(OrigenNoDeclarado):
                comprobar_contra_los_origenes(malo, origenes=["sede.gva.es"])


class TestSeBajaAntesDeEjecutar:
    """De punta a punta: la petición trae URLs y el guion recibe ficheros.

    **El guion no se entera de que hubo red.** Recibe el contenido por el mismo camino que un
    fichero subido a mano, que es lo que hace que abrir la red no cambie el protocolo del guion
    ni lo que el auditor le permite.
    """

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

    @pytest.mark.asyncio
    async def test_una_url_de_un_origen_declarado_llega_como_fichero(
        self, db_session, monkeypatch
    ):
        from server.app.modules.redaccion import funciones_origenes
        from server.app.routers.redaccion import funciones_run_router
        from server.app.routers.redaccion.funciones_run_router import (
            EjecutarRequest,
            ejecutar_funcion_por_api,
        )

        bajadas = []

        async def _falso(url, **kwargs):
            bajadas.append(url)
            return b"%PDF-1.4 contenido", "tomo.pdf"

        monkeypatch.setattr(
            funciones_origenes, "descargar_de_un_origen_declarado", _falso
        )
        monkeypatch.setattr(
            funciones_run_router, "descargar_de_un_origen_declarado", _falso
        )

        class _Sandbox:
            def __init__(self):
                self.opciones = None

            async def execute_extraction_script(self, *, options, **kwargs):
                from datetime import datetime, timezone

                from server.app.modules.redaccion.pipelines.contracts import (
                    ExtractionProvenance,
                    ExtractionResult,
                )

                self.opciones = options
                return ExtractionResult(
                    provenance=ExtractionProvenance(
                        pipeline_id="p", source_ref="s",
                        extracted_at=datetime.now(timezone.utc),
                    )
                )

        organizacion = uuid.uuid4()
        funcion = await self._una_funcion(
            db_session, organizacion, origenes=["sede.gva.es"]
        )
        sandbox = _Sandbox()

        await ejecutar_funcion_por_api(
            funcion_id=funcion.id,
            body=EjecutarRequest(
                version=1, urls={"tomo": "https://sede.gva.es/tomo.pdf"}
            ),
            principal=self._pat(organizacion),
            session=db_session,
            sandbox=sandbox,
            almacen=AlmacenDeMentiraVacio(),
        )

        assert bajadas == ["https://sede.gva.es/tomo.pdf"]

    @pytest.mark.asyncio
    async def test_una_url_de_fuera_de_la_lista_devuelve_422_y_no_toca_el_sandbox(
        self, db_session
    ):
        """**Y no toca el sandbox**, igual que cuando la entrada no cumple el contrato.

        Si lo tocara, una URL rechazada habría gastado una ejecución y dejado rastro de algo que
        no ocurrió.
        """
        from fastapi import HTTPException

        from server.app.routers.redaccion.funciones_run_router import (
            EjecutarRequest,
            ejecutar_funcion_por_api,
        )

        class _Espia:
            async def execute_extraction_script(self, **kwargs):
                raise AssertionError("no tendría que haberse llamado")

        organizacion = uuid.uuid4()
        funcion = await self._una_funcion(
            db_session, organizacion, origenes=["sede.gva.es"]
        )

        with pytest.raises(HTTPException) as fallo:
            await ejecutar_funcion_por_api(
                funcion_id=funcion.id,
                body=EjecutarRequest(
                    version=1, urls={"tomo": "https://otro.example/tomo.pdf"}
                ),
                principal=self._pat(organizacion),
                session=db_session,
                sandbox=_Espia(),
                almacen=AlmacenDeMentiraVacio(),
            )

        assert fallo.value.status_code == 422
        assert "otro.example" in fallo.value.detail


class AlmacenDeMentiraVacio:
    async def put(self, key: str, data: bytes) -> None: ...

    async def get(self, key: str) -> bytes:
        raise FileNotFoundError(key)

    async def delete(self, key: str) -> None: ...

    async def exists(self, key: str) -> bool:
        return False
