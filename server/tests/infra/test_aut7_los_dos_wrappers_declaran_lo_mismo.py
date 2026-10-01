"""AUT.7 — el protocolo del guion está escrito dos veces y no puede divergir.

Un guion de extracción recibe su entrada como **variables ya definidas**: `file_path`,
`raw_text`, `options` y, desde AUT.7, `output_dir`. Esas variables las define un *wrapper*, y
hay **dos**:

* `services/script_sandbox/sandbox/wrappers.py` — el del microservicio, que es el que corre en
  producción y en CI con Docker.
* `server/app/core/sandbox_client.py` (`_build_local_extraction_wrapper`) — el del modo local,
  que corre en desarrollo y en **toda la suite de tests**, porque `TESTING=1` conmuta a él.

**El fallo que esto caza es asimétrico y por eso es peligroso.** Si una variable está en el
wrapper local y no en el del sandbox, el guion funciona en los tests y da `NameError` al
desplegar. Si está en el del sandbox y no en el local, funciona en producción y la suite entera
no puede probarlo. Las dos direcciones son malas y ninguna la ve un test de comportamiento: el
guion de prueba se escribe usando las variables que uno recuerda.

Se comprueba sobre el **texto generado** y no sobre la firma de la función, porque lo que el
guion ve son las asignaciones — una variable puede llegar como parámetro y no acabar escrita.
"""
from __future__ import annotations

import ast
import pathlib

RAIZ = pathlib.Path(__file__).resolve().parents[3]

#: Las variables que un guion de extracción puede dar por definidas. Añadir una al protocolo es
#: tocar esta lista **y** los dos wrappers: si sólo se tocan los wrappers, este test no dice
#: nada nuevo, y si sólo se toca la lista, dice exactamente qué falta.
DEL_PROTOCOLO = ("file_path", "raw_text", "options", "output_dir")


def _wrapper_del_sandbox() -> str:
    import importlib.util

    ruta = RAIZ / "services" / "script_sandbox" / "sandbox" / "wrappers.py"
    spec = importlib.util.spec_from_file_location("_wrappers_aut7", ruta)
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo.build_extraction_wrapper(
        "result = {}", "/tmp/x.csv", "", {"a": 1}, "/tmp/salida"
    )


def _wrapper_local() -> str:
    from server.app.core.sandbox_client import _build_local_extraction_wrapper

    return _build_local_extraction_wrapper(
        "result = {}", "/tmp/x.csv", "", {"a": 1}, "/tmp/salida"
    )


def _asignadas(codigo: str) -> set[str]:
    """Los nombres que el wrapper asigna en el nivel de arriba, leídos con el AST.

    Con el AST y no con un `in`: `"output_dir"` aparece dentro de un comentario o de una cadena
    sin estar asignado, y entonces la comprobación pasaría sin que el guion tenga la variable.
    """
    arbol = ast.parse(codigo)
    nombres: set[str] = set()
    for nodo in arbol.body:
        if isinstance(nodo, ast.Assign):
            for destino in nodo.targets:
                if isinstance(destino, ast.Name):
                    nombres.add(destino.id)
    return nombres


class TestLosDosWrappersDefinenElMismoProtocolo:

    def test_el_del_sandbox_define_todas(self):
        faltan = sorted(set(DEL_PROTOCOLO) - _asignadas(_wrapper_del_sandbox()))

        assert not faltan, (
            f"el wrapper del microservicio no define {faltan}: un guion que las use daría "
            f"NameError en producción"
        )

    def test_el_local_define_todas(self):
        faltan = sorted(set(DEL_PROTOCOLO) - _asignadas(_wrapper_local()))

        assert not faltan, (
            f"el wrapper del modo local no define {faltan}: la suite entera corre por aquí, "
            f"así que eso deja sin poder probar lo que sí funciona desplegado"
        )

    def test_y_ninguno_define_de_mas_que_el_otro(self):
        """Una variable en uno solo es la mitad que se descubre desplegando."""
        del_sandbox = _asignadas(_wrapper_del_sandbox())
        local = _asignadas(_wrapper_local())

        assert del_sandbox == local, (
            f"sólo en el del sandbox: {sorted(del_sandbox - local)}; "
            f"sólo en el local: {sorted(local - del_sandbox)}"
        )


class TestElGuionRecibeElDirectorioDeSalida:

    def test_output_dir_llega_con_la_ruta_que_se_le_pasa(self):
        """Y llega como literal, no interpolado a medias: `repr` y no concatenación."""
        for codigo in (_wrapper_del_sandbox(), _wrapper_local()):
            assert "output_dir = '/tmp/salida'" in codigo
