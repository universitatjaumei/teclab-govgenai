"""Issue #194 — al guion le llega el **contenido** de sus ficheros, no una clave de almacén.

**El defecto.** `ejecutar_funcion` pasaba al sandbox `file_path=<referencia de almacenamiento>`.
`EntradaValidada` dice de sí misma, literalmente, que «`ficheros` son referencias, no rutas, y no
se abren». El sandbox es otro contenedor: ahí esa cadena no es una ruta que exista, así que un
guion que hiciera `pandas.read_csv(file_path)` fallaba.

**Por qué nadie lo vio, y por qué estos tests van por el cliente HTTP.** En desarrollo la
ejecución va por `LocalSandboxClient`, que lanza el subproceso **en la misma máquina**, y con
`STORAGE_BACKEND=file` la referencia es una ruta local de verdad. Las dos coincidencias juntas
hacen que la clave resuelva. En producción no se da ninguna: el sandbox tiene su propio sistema
de ficheros, de sólo lectura, y el almacenamiento es GCS.

Así que **un test en modo local no puede distinguir el arreglo del defecto**. Estos miran lo que
sale por el cable: el cuerpo de la petición HTTP. Es la única forma de que digan algo.

**Y el camino correcto ya existía al lado**: `admin_script_pipeline` —la ruta de un bloque de
informe— lee el contenido y manda `file_bytes` con `file_path=None`, que es para lo que PRO.2
introdujo ese campo. La ruta del catálogo se quedó sin ese arreglo.

**Lo segundo que arregla este bloque**: el protocolo materializaba **un solo fichero**. Los demás
slots viajaban en `options["ficheros"]` como referencias que el guion tampoco podía abrir — o
sea que declarar dos slots era declarar uno y medio. Ahora van todos, y `options["ficheros"]`
lleva **rutas reales dentro del sandbox**.
"""
from __future__ import annotations

import base64
import json

import httpx
import pytest
import respx

API = "http://sandbox.test:5000"


class AlmacenConDocumentos:
    """Un `StorageService` con documentos dentro, por su clave."""

    def __init__(self, **documentos: bytes) -> None:
        self.contenido = dict(documentos)
        self.leidos: list[str] = []

    async def put(self, key: str, data: bytes) -> None:
        self.contenido[key] = data

    async def get(self, key: str) -> bytes:
        self.leidos.append(key)
        if key not in self.contenido:
            raise FileNotFoundError(key)
        return self.contenido[key]

    async def delete(self, key: str) -> None:
        self.contenido.pop(key, None)

    async def exists(self, key: str) -> bool:
        return key in self.contenido


def _contrato(slots):
    from server.app.modules.redaccion.contracts.funciones import (
        ContratoFuncion,
        SlotDeFichero,
    )

    return ContratoFuncion(
        slots=[SlotDeFichero(slot_id=s, kind="excel", required=True) for s in slots],
        parametros=[],
        finalidad="Cruzar el presupuesto con la clasificación económica",
        categorias_datos=["sin_datos_personales"],
    )


def _cliente():
    from server.app.core.sandbox_client import HttpSandboxClient

    return HttpSandboxClient(base_url=API, connect_timeout=1.0, max_retries=0)


def _respuesta_vacia(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200, json={"result": {"tables": [], "metrics": [], "free_text": None}}
    )


class TestElContenidoViajaPorElCable:
    """Lo que se mira es el cuerpo de la petición: es donde el defecto era visible."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_el_fichero_va_como_contenido_y_no_como_referencia(self):
        from server.app.modules.redaccion.funciones_service import ejecutar_funcion

        ruta = respx.post(f"{API}/execute-extraction").mock(side_effect=_respuesta_vacia)
        almacen = AlmacenConDocumentos(**{"org/123/gastos.xlsx": b"contenido del excel"})

        await ejecutar_funcion(
            contrato=_contrato(["gastos"]),
            code="result = {}",
            ficheros={"gastos": "org/123/gastos.xlsx"},
            parametros={},
            sandbox=_cliente(),
            almacen=almacen,
        )

        cuerpo = json.loads(ruta.calls[0].request.content)
        assert base64.b64decode(cuerpo["file_bytes_b64"]) == b"contenido del excel"
        # **Y `file_path` va vacío**: mandar la referencia además del contenido dejaría al guion
        # eligiendo cuál usar, y el defecto volvería por el camino de quien eligiera mal.
        assert cuerpo["file_path"] == ""

    @pytest.mark.asyncio
    @respx.mock
    async def test_el_nombre_conserva_la_extension(self):
        """pandas elige el motor por la extensión: sin ella, un `.xlsx` se lee como CSV."""
        from server.app.modules.redaccion.funciones_service import ejecutar_funcion

        ruta = respx.post(f"{API}/execute-extraction").mock(side_effect=_respuesta_vacia)

        await ejecutar_funcion(
            contrato=_contrato(["gastos"]),
            code="result = {}",
            ficheros={"gastos": "org/123/presupuesto-2026.xlsx"},
            parametros={},
            sandbox=_cliente(),
            almacen=AlmacenConDocumentos(**{"org/123/presupuesto-2026.xlsx": b"x"}),
        )

        cuerpo = json.loads(ruta.calls[0].request.content)
        assert cuerpo["file_name"].endswith(".xlsx")

    @pytest.mark.asyncio
    @respx.mock
    async def test_se_lee_del_almacen_de_verdad(self):
        from server.app.modules.redaccion.funciones_service import ejecutar_funcion

        respx.post(f"{API}/execute-extraction").mock(side_effect=_respuesta_vacia)
        almacen = AlmacenConDocumentos(**{"org/123/gastos.xlsx": b"x"})

        await ejecutar_funcion(
            contrato=_contrato(["gastos"]),
            code="result = {}",
            ficheros={"gastos": "org/123/gastos.xlsx"},
            parametros={},
            sandbox=_cliente(),
            almacen=almacen,
        )

        assert almacen.leidos == ["org/123/gastos.xlsx"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_un_documento_que_no_esta_se_dice_claro(self):
        """Y no como un `KeyError` de pandas dentro del sandbox, que es lo que pasaba."""
        from server.app.modules.redaccion.contracts.funciones import (
            EntradaNoCumpleElContrato,
        )
        from server.app.modules.redaccion.funciones_service import ejecutar_funcion

        ruta = respx.post(f"{API}/execute-extraction").mock(side_effect=_respuesta_vacia)

        with pytest.raises(EntradaNoCumpleElContrato) as fallo:
            await ejecutar_funcion(
                contrato=_contrato(["gastos"]),
                code="result = {}",
                ficheros={"gastos": "org/123/no-esta.xlsx"},
                parametros={},
                sandbox=_cliente(),
                almacen=AlmacenConDocumentos(),
            )

        assert "no-esta.xlsx" in str(fallo.value)
        # Y sin tocar el sandbox: no se paga un subproceso para obtener un error peor.
        assert not ruta.calls


class TestVariosFicherosLleganTodos:
    """El límite que la #117 dejó anotado como pregunta. La respuesta era «no bastan»."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_los_tres_slots_viajan_con_su_contenido(self):
        from server.app.modules.redaccion.funciones_service import ejecutar_funcion

        ruta = respx.post(f"{API}/execute-extraction").mock(side_effect=_respuesta_vacia)
        almacen = AlmacenConDocumentos(
            **{
                "org/p.csv": b"presupuesto",
                "org/c.csv": b"clasificacion",
                "org/n.csv": b"nombres",
            }
        )

        await ejecutar_funcion(
            contrato=_contrato(["presupuesto", "clasificacion", "nombres"]),
            code="result = {}",
            ficheros={
                "presupuesto": "org/p.csv",
                "clasificacion": "org/c.csv",
                "nombres": "org/n.csv",
            },
            parametros={},
            sandbox=_cliente(),
            almacen=almacen,
        )

        cuerpo = json.loads(ruta.calls[0].request.content)
        # El primero va como `file_bytes` y `file_slot` dice de qué slot es; los demás, aquí.
        assert cuerpo["file_slot"] == "presupuesto"
        assert base64.b64decode(cuerpo["file_bytes_b64"]) == b"presupuesto"
        entregados = cuerpo["ficheros_b64"]
        assert set(entregados) == {"clasificacion", "nombres"}
        assert base64.b64decode(entregados["clasificacion"]["contenido_b64"]) == b"clasificacion"

    @pytest.mark.asyncio
    @respx.mock
    async def test_el_principal_no_viaja_dos_veces(self):
        """El temporal del sandbox es un `tmpfs` de 128 MB que comparte con los artefactos.

        Si el principal fuera como `file_bytes` **y** dentro de `ficheros_b64`, se escribiría dos
        veces: un solo fichero de 60 MB, que cabe en el tope de 64, ocuparía 120 y dejaría a la
        salida sin sitio. El tope sólo significa algo si cada byte cuenta una vez.
        """
        from server.app.modules.redaccion.funciones_service import ejecutar_funcion

        ruta = respx.post(f"{API}/execute-extraction").mock(side_effect=_respuesta_vacia)

        await ejecutar_funcion(
            contrato=_contrato(["gastos"]),
            code="result = {}",
            ficheros={"gastos": "org/g.csv"},
            parametros={},
            sandbox=_cliente(),
            almacen=AlmacenConDocumentos(**{"org/g.csv": b"G"}),
        )

        cuerpo = json.loads(ruta.calls[0].request.content)
        assert cuerpo["file_slot"] == "gastos"
        assert cuerpo["ficheros_b64"] == {}

    @pytest.mark.asyncio
    @respx.mock
    async def test_el_primero_sigue_yendo_tambien_como_file_bytes(self):
        """Retrocompatible: un guion que ya usaba `file_path` no se entera del cambio."""
        from server.app.modules.redaccion.funciones_service import ejecutar_funcion

        ruta = respx.post(f"{API}/execute-extraction").mock(side_effect=_respuesta_vacia)

        await ejecutar_funcion(
            contrato=_contrato(["uno", "dos"]),
            code="result = {}",
            ficheros={"uno": "org/a.csv", "dos": "org/b.csv"},
            parametros={},
            sandbox=_cliente(),
            almacen=AlmacenConDocumentos(**{"org/a.csv": b"A", "org/b.csv": b"B"}),
        )

        cuerpo = json.loads(ruta.calls[0].request.content)
        assert base64.b64decode(cuerpo["file_bytes_b64"]) == b"A"

    @pytest.mark.asyncio
    @respx.mock
    async def test_lo_bajado_de_una_url_llega_aunque_no_sea_el_primer_slot(self):
        """AUT.8 limitaba las URL al primer slot porque era el único que se materializaba.

        Desde aquí se materializan todos, así que la limitación ya no tiene razón de ser — y
        dejarla sería volver a declarar tres slots y poder usar uno y medio.
        """
        from server.app.modules.redaccion.funciones_service import ejecutar_funcion

        ruta = respx.post(f"{API}/execute-extraction").mock(side_effect=_respuesta_vacia)
        almacen = AlmacenConDocumentos(**{"org/a.csv": b"A"})

        await ejecutar_funcion(
            contrato=_contrato(["uno", "dos"]),
            code="result = {}",
            ficheros={"uno": "org/a.csv"},
            contenidos={"dos": b"bajado de fuera"},
            parametros={},
            sandbox=_cliente(),
            almacen=almacen,
        )

        cuerpo = json.loads(ruta.calls[0].request.content)
        assert base64.b64decode(cuerpo["ficheros_b64"]["dos"]["contenido_b64"]) == (
            b"bajado de fuera"
        )
        # Y no se busca en el almacén lo que ya vino de fuera.
        assert almacen.leidos == ["org/a.csv"]


class TestElGuionRecibeRutasQuePuedeAbrir:
    """En el sandbox de verdad, no en el cliente: `options['ficheros']` tiene que ser usable."""

    def test_el_sandbox_materializa_cada_fichero_y_pasa_su_ruta(self):
        import importlib.util
        import pathlib

        raiz = pathlib.Path(__file__).resolve().parents[4]
        ruta = raiz / "services" / "script_sandbox" / "sandbox" / "wrappers.py"
        spec = importlib.util.spec_from_file_location("_wrappers_194", ruta)
        assert spec and spec.loader
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)

        codigo = modulo.build_extraction_wrapper(
            "result = {}", "/tmp/a.csv", "", {"ficheros": {"uno": "/tmp/a.csv"}}, "/tmp/salida"
        )

        # El guion recibe `ficheros` dentro de `options`, y ahí tiene que haber rutas.
        assert "'ficheros': {'uno': '/tmp/a.csv'}" in codigo

    @pytest.mark.asyncio
    async def test_en_modo_local_el_guion_lee_los_dos_por_su_ruta(self):
        """El modo local tiene que hacer lo mismo que el microservicio.

        Si no, un guion con varios ficheros pasaría en un sitio y fallaría en el otro, que es la
        forma de este defecto. Aquí corre un guion de verdad que lee por `options["ficheros"]`.
        """
        from server.app.core.sandbox_client import LocalSandboxClient
        from server.app.modules.redaccion.funciones_service import ejecutar_funcion

        codigo = (
            "import pandas\n"
            "rutas = options['ficheros']\n"
            "assert rutas['presupuesto'] == file_path\n"
            "a = pandas.read_csv(rutas['presupuesto'])\n"
            "b = pandas.read_csv(rutas['clasificacion'])\n"
            "result = {'metrics': ["
            "  {'name': 'filas_a', 'value': len(a)},"
            "  {'name': 'filas_b', 'value': len(b)}]}\n"
        )

        salida = await ejecutar_funcion(
            contrato=_contrato(["presupuesto", "clasificacion"]),
            code=codigo,
            ficheros={"presupuesto": "org/p.csv", "clasificacion": "org/c.csv"},
            parametros={},
            sandbox=LocalSandboxClient(),
            almacen=AlmacenConDocumentos(
                **{"org/p.csv": b"a\n1\n2\n3\n", "org/c.csv": b"b\n9\n"}
            ),
        )

        metricas = {m.name: m.value for m in salida.metrics}
        assert metricas == {"filas_a": 3, "filas_b": 1}, salida.warnings

    @pytest.mark.asyncio
    @respx.mock
    async def test_y_tambien_por_el_camino_con_artefactos(self):
        """Hay **dos** caminos al sandbox, y los dos tienen que llevar los ficheros.

        Este test existe porque el primer arreglo sólo reenvió el parámetro por uno de ellos: el
        de artefactos lo aceptaba en la firma y lo dejaba caer. Una función que produzca ficheros
        **y** lea varios habría perdido los de entrada en silencio, que es el peor sitio donde
        perder algo. No lo vio ningún test hasta que se escribió éste.
        """
        from server.app.modules.redaccion.contracts.funciones import ArtefactosDeSalida
        from server.app.modules.redaccion.funciones_service import ejecutar_funcion

        ruta = respx.post(f"{API}/execute-extraction").mock(side_effect=_respuesta_vacia)
        contrato = _contrato(["presupuesto", "clasificacion"])
        contrato.artefactos = ArtefactosDeSalida(
            maximo=1, maximo_bytes=1_000_000, retencion_dias=7
        )

        await ejecutar_funcion(
            contrato=contrato,
            code="result = {}",
            ficheros={"presupuesto": "org/p.csv", "clasificacion": "org/c.csv"},
            parametros={},
            sandbox=_cliente(),
            almacen=AlmacenConDocumentos(**{"org/p.csv": b"P", "org/c.csv": b"C"}),
        )

        cuerpo = json.loads(ruta.calls[0].request.content)
        assert cuerpo["file_slot"] == "presupuesto"
        assert set(cuerpo["ficheros_b64"]) == {"clasificacion"}
        # Y los topes de artefactos siguen viajando: el arreglo no puede haberlos tapado.
        assert cuerpo["artefactos_maximo"] == 1


class TestEnModoLocalUnNombreNoSaleDeSuCarpeta:
    """Lo mismo que el sandbox de verdad (PR #210, CodeQL): `Path("..").name` es `".."`."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("camino", ["sin_artefactos", "con_artefactos"])
    async def test_dos_puntos_como_nombre_se_rechaza_en_los_dos_caminos(self, camino):
        from server.app.core.sandbox_client import LocalSandboxClient

        cliente = LocalSandboxClient()
        comunes = dict(
            code="result = {}",
            file_path=None,
            raw_text=None,
            options={},
            ficheros_con_contenido={"dos": ("..", b"x")},
        )
        if camino == "sin_artefactos":
            salida = await cliente.execute_extraction_script(**comunes)
        else:
            salida, _ = await cliente.execute_extraction_con_artefactos(
                **comunes, artefactos_maximo=1, artefactos_maximo_bytes=1000
            )

        assert [w.code for w in salida.warnings] == ["FILE_NAME_INVALID"]

    @pytest.mark.asyncio
    async def test_y_tambien_el_principal(self):
        from server.app.core.sandbox_client import LocalSandboxClient

        salida = await LocalSandboxClient().execute_extraction_script(
            code="result = {}",
            file_path=None,
            raw_text=None,
            options={},
            file_bytes=b"x",
            file_name="..",
        )

        assert [w.code for w in salida.warnings] == ["FILE_NAME_INVALID"]


class TestEnModoLocalDosSlotsNoCompartenCarpeta:
    """`a/b` y `ab` se limpiaban igual y compartían carpeta (PR #210). En local, lo mismo."""

    @pytest.mark.asyncio
    async def test_cada_slot_lee_lo_suyo(self):
        from server.app.core.sandbox_client import LocalSandboxClient

        codigo = (
            "import pandas\n"
            "rutas = options['ficheros']\n"
            "result = {'metrics': ["
            "  {'name': 'a', 'value': len(pandas.read_csv(rutas['a/b']))},"
            "  {'name': 'b', 'value': len(pandas.read_csv(rutas['ab']))}]}\n"
        )

        salida = await LocalSandboxClient().execute_extraction_script(
            code=codigo,
            file_path=None,
            raw_text=None,
            options={},
            ficheros_con_contenido={
                "a/b": ("datos.csv", b"x\n1\n2\n"),
                "ab": ("datos.csv", b"x\n1\n2\n3\n4\n"),
            },
        )

        assert {m.name: m.value for m in salida.metrics} == {"a": 2, "b": 4}, salida.warnings


class TestElTopeDeLosDocumentosDeEntrada:
    """Cuánto puede pesar lo que se lee del almacenamiento antes de mandarlo al sandbox.

    **Por qué hace falta un tope y por qué no lo cubría el que ya había.** El tope de la petición
    (`MAXIMO_BYTES`, heredado de VAS.1) mide el JSON que llega, y ahí sólo viajan **referencias**.
    Desde el arreglo del #194 el servidor resuelve esas referencias y junta los documentos en
    memoria: tres CSV no son nada, varios PDF grandes sí. Son dos riesgos distintos y por eso son
    dos números, no uno que diverge — que es lo que aquel docstring avisaba de no hacer.

    **Y el número no es inventado.** El sandbox monta su temporal como un `tmpfs` de 128 MB
    (`docker-compose.yml`), y ahí caben los ficheros de entrada materializados **y** los
    artefactos que el guion escriba. El tope de entrada se queda en la mitad para que producir la
    salida no se estrelle contra la entrada.
    """

    @pytest.mark.asyncio
    @respx.mock
    async def test_lo_que_cabe_pasa(self):
        from server.app.modules.redaccion.funciones_service import (
            MAXIMO_BYTES_DE_ENTRADA,
            ejecutar_funcion,
        )

        ruta = respx.post(f"{API}/execute-extraction").mock(side_effect=_respuesta_vacia)

        await ejecutar_funcion(
            contrato=_contrato(["gastos"]),
            code="result = {}",
            ficheros={"gastos": "org/g.csv"},
            parametros={},
            sandbox=_cliente(),
            almacen=AlmacenConDocumentos(**{"org/g.csv": b"x" * (MAXIMO_BYTES_DE_ENTRADA // 2)}),
        )

        assert ruta.calls

    @pytest.mark.asyncio
    @respx.mock
    async def test_pasarse_se_dice_antes_de_tocar_el_sandbox(self):
        from server.app.modules.redaccion.contracts.funciones import (
            EntradaNoCumpleElContrato,
        )
        from server.app.modules.redaccion.funciones_service import (
            MAXIMO_BYTES_DE_ENTRADA,
            ejecutar_funcion,
        )

        ruta = respx.post(f"{API}/execute-extraction").mock(side_effect=_respuesta_vacia)

        with pytest.raises(EntradaNoCumpleElContrato) as fallo:
            await ejecutar_funcion(
                contrato=_contrato(["gastos"]),
                code="result = {}",
                ficheros={"gastos": "org/g.csv"},
                parametros={},
                sandbox=_cliente(),
                almacen=AlmacenConDocumentos(
                    **{"org/g.csv": b"x" * (MAXIMO_BYTES_DE_ENTRADA + 1)}
                ),
            )

        # Los dos numeros, porque «te has pasado» sin decir de cuanto no es accionable.
        assert str(MAXIMO_BYTES_DE_ENTRADA) in str(fallo.value)
        assert not ruta.calls

    @pytest.mark.asyncio
    @respx.mock
    async def test_el_tope_es_del_total_y_no_de_cada_uno(self):
        """Tres documentos que caben sueltos y no juntos: lo que llena la memoria es la suma."""
        from server.app.modules.redaccion.contracts.funciones import (
            EntradaNoCumpleElContrato,
        )
        from server.app.modules.redaccion.funciones_service import (
            MAXIMO_BYTES_DE_ENTRADA,
            ejecutar_funcion,
        )

        respx.post(f"{API}/execute-extraction").mock(side_effect=_respuesta_vacia)
        cacho = b"x" * (MAXIMO_BYTES_DE_ENTRADA // 2)

        with pytest.raises(EntradaNoCumpleElContrato):
            await ejecutar_funcion(
                contrato=_contrato(["a", "b", "c"]),
                code="result = {}",
                ficheros={"a": "org/a", "b": "org/b", "c": "org/c"},
                parametros={},
                sandbox=_cliente(),
                almacen=AlmacenConDocumentos(
                    **{"org/a": cacho, "org/b": cacho, "org/c": cacho}
                ),
            )

    def test_el_tope_cabe_en_el_tmpfs_del_sandbox(self):
        """El numero sale del `tmpfs` de 128 MB, no de una corazonada.

        Si alguien sube el tope por encima de la mitad, los artefactos que el guion escriba se
        quedan sin sitio en el mismo temporal — y eso falla dentro del sandbox, que es donde peor
        se depura. Este test ata el numero a su razon.
        """
        import pathlib
        import re

        from server.app.modules.redaccion.funciones_service import MAXIMO_BYTES_DE_ENTRADA

        compose = (
            pathlib.Path(__file__).resolve().parents[4] / "docker-compose.yml"
        ).read_text(encoding="utf-8")
        casado = re.search(r"/tmp/sandbox:size=(\d+)M", compose)
        assert casado, "el sandbox ya no monta su temporal como tmpfs con tamano"

        tmpfs_bytes = int(casado.group(1)) * 1024 * 1024
        assert MAXIMO_BYTES_DE_ENTRADA <= tmpfs_bytes // 2
