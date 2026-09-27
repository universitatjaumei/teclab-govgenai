"""Qué bloques se pintan y en qué sección (SEG.5).

La vista previa y el ensamblado final recorren las **secciones** y pintan los bloques que cada
sección enumera en `block_ids`. Un bloque que no aparece en ninguna sección existe, se ejecuta,
extrae sus datos, pasa la revisión... y no sale en el informe. Sin error y sin aviso.

Es el fallo que produjo un informe de seguimiento con las dos secciones vacías después de que
las nueve tablas se extrajeran y las nueve valoraciones se aprobaran. Aquí vive la comprobación
para que ni el borrador que propone el modelo ni la plantilla que se publica puedan quedarse así.

Deploy: edge
"""
from __future__ import annotations

from typing import Any, Iterable

#: Bloques que no se imprimen: producen datos para que otro los pinte, o frenan el flujo.
#: Un `DETERMINISTIC_DATA` puesto en una sección además duplicaría la tabla, porque el
#: `TABLE` que lo referencia ya la pinta. Que estén fuera de toda sección es lo normal.
_NO_SE_IMPRIMEN = frozenset({"DETERMINISTIC_DATA", "DATA_TRANSFORM", "REVIEW_GATE"})


def bloques_sin_seccion(sections: Iterable[Any], blocks: Iterable[Any]) -> list[str]:
    """Los ids de bloque **imprimibles** que ninguna sección enumera, en orden de declaración.

    Al revés no se comprueba: una sección que referencia un bloque inexistente no rompe el
    informe —la vista previa se lo salta— y en cambio la plantilla se construye por pasos, así
    que una referencia adelantada es un estado de trabajo legítimo.
    """
    asignados: set[str] = set()
    for seccion in sections:
        for bid in getattr(seccion, "block_ids", None) or []:
            asignados.add(str(bid))

    return [
        str(bloque.id)
        for bloque in blocks
        if str(getattr(bloque, "id", "")) not in asignados
        and str(getattr(bloque, "kind", "")) not in _NO_SE_IMPRIMEN
    ]


def dependencias_imposibles(blocks: Iterable[Any]) -> list[str]:
    """Las dependencias que ningún orden de ejecución podrá cumplir, explicadas.

    Devuelve una lista de frases listas para enseñar, vacía si la plantilla es coherente.

    **Por qué se comprueba el orden de declaración y no se ordena solo.** El orden de ejecución
    es el de la plantilla, y es una decisión escrita en SEG.1: quien la redacta sabe si la tabla
    de matrícula va antes que la de tasas, y reordenar por dependencias cambiaría en silencio el
    orden en que se presentan los datos. Si el orden lo fija quien escribe, lo que hace falta es
    comprobar que el orden que escribió es posible — no sustituirlo.

    Tres cosas son imposibles, y ninguna daba error antes (revisión de la PR #178):

    - **depender de un bloque que no existe**: nunca se cumplirá;
    - **depender de uno declarado después**: cuando al dependiente le toque, su dependencia no
      habrá producido nada, así que la propagación de fallos no ve nada que propagar y el
      apartado se redacta igual — apoyado en un vacío;
    - **un ciclo**: no rompe nada y ninguna de las puertas de revisión implicadas se abre jamás.

    Comprobar el orden de declaración cubre las tres: un grafo en el que toda arista va hacia
    atrás no puede tener ciclos.
    """
    posicion: dict[str, int] = {}
    for indice, bloque in enumerate(blocks):
        posicion[str(getattr(bloque, "id", ""))] = indice

    problemas: list[str] = []
    for indice, bloque in enumerate(blocks):
        bid = str(getattr(bloque, "id", ""))
        for referencia in getattr(bloque, "depends_on", None) or []:
            dependencia = str(getattr(referencia, "block_id", ""))
            if dependencia not in posicion:
                problemas.append(
                    f"«{bid}» declara depender de «{dependencia}», que no existe en la plantilla"
                )
            elif posicion[dependencia] >= indice:
                problemas.append(
                    f"«{bid}» declara depender de «{dependencia}», que está declarado después: "
                    f"cuando le toque a «{bid}», «{dependencia}» todavía no habrá producido nada"
                )
    return problemas
