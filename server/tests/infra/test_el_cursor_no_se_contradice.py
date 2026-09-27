"""Una fila del cursor no puede afirmar dos estados a la vez.

**El defecto, y lo que costó.** `planificacion/PROJECT_STATE.md` es la fuente de verdad del
progreso y se lee entero al arrancar cada sesión. Sus filas crecen por acumulación: se escribe el
plan cuando el bloque se planifica, y se le añade el resultado cuando se cierra. Lo que pasó es
que **el texto viejo se quedó dentro afirmando lo contrario del nuevo**:

* la fila de **FUN** decía «✅ Completo» en la cabecera y «▶ En curso» en la prosa de debajo;
* la de **RAG.6b** decía «⏳ Pendiente, va después del Deploy» en una línea y «✅ HECHO el
  2026-08-24» en otra;
* y otras siete conservaban un «⏳ Pendiente, planificado el …» dentro de una celda que empezaba
  por «✅ Completo».

No es un problema cosmético: **quien lee una fila que se contradice escoge**, y en los dos primeros
casos se escogió mal. De ahí salieron las issues #7 y #10, abiertas semanas sobre trabajo ya
entregado — y una issue abierta **afirma** que eso falta, con el agravante de que el backlog es lo
primero que lee quien llega al repositorio. Es el mismo defecto que obligó a renombrar un hito y la
misma regla que `docs/ESPECIFICACIONES.md`: un rótulo que miente hace que nadie mire lo que hay
dentro.

**Qué comprueba esto y qué no.** Sólo que una fila no lleve a la vez dos marcadores de estado
distintos. No comprueba que el estado sea el correcto —eso no lo puede saber un test— ni prohíbe
contar la historia: el texto de cuándo y por qué se planificó algo se conserva entero, porque sigue
siendo verdad. Lo que se cae es el **marcador**, que es lo que dejó de serlo.
"""

from __future__ import annotations

import re
from pathlib import Path

CURSOR = Path(__file__).resolve().parents[3] / "planificacion" / "PROJECT_STATE.md"

#: Los marcadores de estado que usa el cursor, cada uno con su nombre para el mensaje de error.
MARCADORES: dict[str, re.Pattern[str]] = {
    "completo": re.compile(r"✅\s*\*\*Completo|✅\s*\*\*BLOQUE[^|]*COMPLETO", re.IGNORECASE),
    "en curso": re.compile(r"▶\s*\*\*En curso", re.IGNORECASE),
    "pendiente": re.compile(r"⏳\s*\*\*Pendiente", re.IGNORECASE),
}


def _filas_que_se_contradicen() -> list[str]:
    hallazgos: list[str] = []
    for numero, linea in enumerate(CURSOR.read_text(encoding="utf-8").splitlines(), 1):
        if not linea.startswith("|"):
            continue
        presentes = sorted(n for n, patron in MARCADORES.items() if patron.search(linea))
        if len(presentes) > 1:
            nombre = linea.split("|")[1].strip()[:70]
            hallazgos.append(f"línea {numero} — {nombre} — dice a la vez: {', '.join(presentes)}")
    return hallazgos


def test_ninguna_fila_afirma_dos_estados_a_la_vez() -> None:
    contradictorias = _filas_que_se_contradicen()

    assert not contradictorias, (
        "Estas filas del cursor afirman dos estados a la vez:\n  - "
        + "\n  - ".join(contradictorias)
        + "\n\nQuien lee una fila que se contradice escoge, y ya se escogió mal dos veces: las "
        "issues #7 y #10 estuvieron semanas abiertas sobre trabajo entregado porque la fila "
        "decía las dos cosas.\n\n"
        "La salida NO es borrar la historia. El texto de cuándo y por qué se planificó algo se "
        "conserva —sigue siendo verdad—; lo que se quita es el **marcador de estado** de esa "
        "parte vieja, por ejemplo «⏳ **Pendiente, planificado el …**» → «**Cuando se "
        "planificó: …**»."
    )


def test_el_guardarrail_sabe_encontrar_la_forma_que_busca() -> None:
    """Un guardarraíl que recorre algo y no encuentra nada pasa en verde sin haber mirado.

    Ya pasó en este repositorio más de una vez, así que se demuestra que los patrones casan con
    lo que tienen que casar y no con lo que se le parece.
    """
    assert MARCADORES["completo"].search("| X | ✅ **Completo (2026-09-18)** |")
    assert MARCADORES["en curso"].search("| X | ▶ **En curso, planificado el …** |")
    assert MARCADORES["pendiente"].search("| X | ⏳ **Pendiente, va antes de Deploy** |")
    # Lo que se conserva a propósito no puede disparar el guardarraíl.
    assert not MARCADORES["pendiente"].search("| X | **Cuando se planificó: 2026-08-15** |")
    # Y una mención en prosa de la palabra no es un marcador.
    assert not MARCADORES["completo"].search("| X | el bloque quedó completo aquel día |")


def test_el_guardarrail_mira_donde_hay_cursor() -> None:
    """Que el fichero exista, que es la otra forma silenciosa de no comprobar nada."""
    assert CURSOR.is_file(), f"{CURSOR} no existe: este test no está mirando ningún cursor"
    filas = [
        linea
        for linea in CURSOR.read_text(encoding="utf-8").splitlines()
        if linea.startswith("|")
    ]
    assert len(filas) > 50, f"sólo {len(filas)} filas: el cursor no puede ser tan corto"
