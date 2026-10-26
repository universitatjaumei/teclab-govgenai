"""Issue #147 — el detalle de una excepción no viaja al cliente en el flujo del chat.

**Qué pasaba.** Los dos manejadores de última instancia del turno de chat emitían
`_sse("error", {"message": str(exc)})`. El `str(exc)` de una excepción cualquiera lleva lo que
lleve: el mensaje de un error de base de datos, una ruta del contenedor, la respuesta cruda del
proveedor de modelo.

**Por qué aquí importa más que en otro endpoint.** El widget del chatbot es **público**: no hace
falta credencial ni pertenecer a la organización. Cualquiera que lo visite o lo embeba puede
provocar un error y leer ese detalle. En una plataforma para administración pública el listón de
lo que cruza esa frontera es más alto, no más bajo.

Y uno de los dos era peor que el otro: el del bucle de eventos mandaba el detalle al cliente **y
no lo registraba**, de modo que el único que no se enteraba de qué había fallado era quien tenía
que arreglarlo.

**Lo que no se toca, y conviene decir por qué.** El `HTTPException(400, detail=str(exc))` del
enrutado sigue igual: ahí la excepción es un `ValueError` propio y acotado, y su texto **es** el
mensaje de validación que el cliente necesita para corregir la petición. La diferencia no es el
`str(exc)`, es si la excepción es de un tipo que tú controlas o un `except Exception` que atrapa
lo que sea.

**Por qué un test sobre el código fuente y no sobre la respuesta.** Montar el generador SSE
completo exige simular el grafo, el proveedor de modelo y la sesión; el test acabaría
comprobando los dobles. Lo que hay que impedir es una forma de escribir, y eso se lee. El riesgo
de un test así —que pase en el vacío porque el patrón ya no encuentra nada— se cubre con la
primera comprobación: si los manejadores desaparecen, esto se pone rojo.

De dónde sale: CodeQL (`py/stack-trace-exposure`) en su primer análisis tras abrir el
repositorio, el 2026-09-24. De las 18 alertas de esa tanda, 12 eran falsos positivos verificados
a mano; ésta tenía razón.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[3]
# #274 — los manejadores del flujo SSE salieron del endpoint a su servicio.
ROUTER = RAIZ / "server" / "app" / "modules" / "agents_hub" / "services" / "turno_de_chat.py"

#: `except Exception:` y `except Exception as exc:`. El `as` es opcional a proposito: al
#: arreglar la issue dejo de hacer falta ligar la excepcion, el patron que lo exigia dejo de
#: encontrar nada, y el test que recorre los manejadores paso **en verde sobre una lista
#: vacia**. Lo cazó el autocomprobante de arriba, que es para lo que está.
_CAPTURA = r"except Exception(?: as \w+)?:"


@pytest.fixture(scope="module")
def fuente() -> str:
    assert ROUTER.is_file(), f"Falta {ROUTER.relative_to(RAIZ).as_posix()}"
    return ROUTER.read_text(encoding="utf-8")


def test_el_medidor_encuentra_los_manejadores(fuente: str) -> None:
    """Sin esto, los test de abajo pasarían en verde sobre una lista vacía."""
    capturas = re.findall(_CAPTURA, fuente)
    assert len(capturas) >= 2, (
        f"se esperaban al menos dos `except Exception` en el turno de chat y hay "
        f"{len(capturas)}. O el router se reorganizó, o este test dejó de saber leerlo."
    )


def test_ningun_evento_de_error_lleva_el_texto_de_la_excepcion(fuente: str) -> None:
    culpables = [
        linea.strip()
        for linea in fuente.splitlines()
        if "_sse(" in linea and "error" in linea and re.search(r"str\(\s*\w+\s*\)", linea)
    ]
    assert not culpables, (
        f"un evento `error` del flujo SSE lleva el texto de la excepción: {culpables}. El widget "
        f"es público: ese texto puede llevar el mensaje de un error de base de datos, una ruta "
        f"del contenedor o la respuesta cruda del proveedor. El cliente tiene que saber que hubo "
        f"un error, no cuál."
    )


def test_los_dos_manejadores_registran_lo_que_no_mandan(fuente: str) -> None:
    """Si el detalle no va al cliente, tiene que ir al registro. En algún sitio tiene que estar.

    Uno de los dos no lo hacía ni antes: mandaba el detalle fuera y no lo escribía en el log.
    """
    lineas = fuente.splitlines()
    for i, linea in enumerate(lineas):
        if not re.match(r"\s*" + _CAPTURA, linea):
            continue
        bloque = "\n".join(lineas[i : i + 8])
        if "_sse(" not in bloque or "error" not in bloque:
            continue
        assert "logger.exception" in bloque or "logger.error" in bloque, (
            f"el manejador de la línea {i + 1} emite un evento `error` sin registrar la "
            f"excepción. Entonces el detalle no lo tiene nadie: ni el cliente, que está bien, "
            f"ni quien tiene que arreglarlo, que no."
        )
