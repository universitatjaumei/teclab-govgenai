"""El código de un cuaderno, para poder mirarlo (AUT.3, issue #114). Deploy: edge.

Una función de origen **externo** se registra como fichero: `.py` o `.ipynb`. El auditor sólo
sabe leer Python, y un cuaderno es JSON con el código repartido en celdas, así que hay que
sacarlo antes.

**Y sacarlo es todo lo que se hace.** No se ejecuta, no se valida contra ningún contrato y no se
decide nada con el resultado: el auditor corre aquí con perfil informativo y sus hallazgos van a
la cola de revisión. Un cuaderno que se ejecuta fuera usa red y disco legítimamente.
"""

from __future__ import annotations

import json


def codigo_de_cuaderno(fichero: str) -> str | None:
    """El Python de un fichero registrado, o `None` si no se puede leer como tal.

    - Un `.py` es su propio código y se devuelve tal cual.
    - Un `.ipynb` es JSON: se concatenan sus celdas de código, en orden y separadas por una
      línea en blanco, que es lo que el auditor puede parsear de una vez.

    **`None` no es «no hay hallazgos»**, y por eso se devuelve en vez de una cadena vacía: quien
    llama lo anota como «no se pudo auditar». Confundir las dos cosas es como un medidor acaba
    informando de cero en verde.
    """
    if not fichero or not fichero.strip():
        return None

    texto = fichero.lstrip()
    if not texto.startswith("{"):
        # No es JSON, así que se toma por Python. Si no lo es, el auditor lo dirá con un
        # hallazgo de sintaxis, que es información y no un fallo de esta función.
        return fichero

    try:
        cuaderno = json.loads(fichero)
    except json.JSONDecodeError:
        return None
    if not isinstance(cuaderno, dict):
        return None

    celdas = cuaderno.get("cells")
    if not isinstance(celdas, list):
        return None

    trozos: list[str] = []
    for celda in celdas:
        if not isinstance(celda, dict) or celda.get("cell_type") != "code":
            continue
        fuente = celda.get("source")
        if isinstance(fuente, list):
            trozos.append("".join(str(linea) for linea in fuente))
        elif isinstance(fuente, str):
            trozos.append(fuente)

    return "\n\n".join(t for t in trozos if t.strip()) or None
