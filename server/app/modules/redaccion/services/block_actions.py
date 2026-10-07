"""Qué se puede hacer con cada bloque, decidido en el servidor (INF.2).

Deploy: edge

El módulo tenía **tres reglas distintas** para «qué está pendiente» y no coincidían:

1. `preview_builder.bloques_pendientes` — pendiente = bloque de IA fuera de {approved, locked}.
2. `AIBlockReviewPanel` — pendiente = bloque en `needs_review`, y solo esos se pintaban.
3. `FinalAssemblerNode` — se bloquea solo si un bloque **`required`** está `failed`, y
   `required` es `False` por defecto en todo bloque.

Un bloque de IA que **falla** no está `approved` ni está `needs_review`, así que caía en el
hueco: bloqueaba el informe (409 en vista previa y exportación) y no ofrecía ninguna acción. Y
como su bloque no era `required`, el ensamblador daba el informe por `assembled` de todas
formas, con lo que la insignia decía «Listo para exportar» sobre algo que no se podía exportar.

La causa de fondo es que el cliente **calculaba** el estado. Aquí se calcula una vez, en el
servidor, y el cliente itera lo que reciba: es la regla maestra nº2 de `CLAUDE.md`, la misma
que gobierna `acciones_permitidas` en expedientes.

**Las acciones se derivan de `_VALID_TRANSITIONS`**, no de una lista escrita a mano. Eso hace
imposible ofrecer un botón que el servidor rechace —el panel pintaba «Regenerar» en bloques
`needs_review` y esa transición no existe, así que devolvía 422— y es la cuarta vez en el
módulo que una lista paralela se desincroniza de la que manda.
"""
from __future__ import annotations

from typing import Any

from server.app.modules.redaccion.contracts.runtime import _VALID_TRANSITIONS

#: Bloques cuyo contenido lo escribe un modelo, y por tanto lo revisa una persona.
#
# Estaba repetido en tres módulos —aquí, `preview_builder` y `final_assembler`—, que es la
# forma en que tres reglas empiezan a discrepar. Vive aquí porque este módulo es el que decide
# la política de revisión; los otros dos la consumen.
TIPOS_DE_IA = frozenset({"AI_ASSISTED_TEXT", "AI_SUMMARY", "AI_REWRITE"})

#: Estados en los que un bloque de IA ya pasó por una persona.
ESTADOS_APROBADOS = frozenset({"approved", "locked"})

#: Estado al que lleva cada acción. `edit` no está: sobreescribe el contenido y **no
#: transiciona** —editar no aprueba—, así que su permiso se decide aparte.
_DESTINO_DE_LA_ACCION: dict[str, str] = {
    "approve": "approved",
    "reject": "rejected",
    "regenerate": "ai_generated",
}

#: Editar deja de estar permitido cuando la revisión ya se cerró. Un `approved` que se puede
#: reescribir sin volver a revisarse convierte la aprobación en un sello sobre otro texto, que
#: es exactamente lo que la supervisión humana tiene que impedir; y `locked` está congelado por
#: definición (`_VALID_TRANSITIONS['locked']` está vacío).
_ESTADOS_SIN_EDICION = frozenset({"approved", "locked"})

#: Orden estable en la respuesta: la pantalla itera la lista tal cual, así que **el orden de
#: los botones lo decide el servidor**. Primero lo que cierra la revisión, después lo que la
#: devuelve atrás; es el orden que el panel ya tenía cuando los botones estaban escritos a mano.
_ORDEN = ("approve", "edit", "reject", "regenerate")


def acciones_permitidas(kind: str, status: str) -> list[str]:
    """Las acciones que una persona puede pedir sobre este bloque, ahora mismo.

    Solo se ofrece lo que la máquina de estados aceptaría: la lista es un subconjunto de lo
    posible, nunca un superconjunto. Si aparece aquí, el endpoint correspondiente no puede
    responder 422 por transición inválida.

    Un bloque que **no** lo escribió un modelo no ofrece nada: no se aprueba ni se regenera un
    `DETERMINISTIC_DATA`, y su arreglo —aportar el dato que falta— vive en el formulario de
    datos de partida, que desde INF.1 es el único camino para relanzar el informe.
    """
    if kind not in TIPOS_DE_IA:
        return []

    alcanzables = _VALID_TRANSITIONS.get(status, set())
    acciones = {
        accion
        for accion, destino in _DESTINO_DE_LA_ACCION.items()
        if destino in alcanzables
    }

    if status not in _ESTADOS_SIN_EDICION:
        acciones.add("edit")

    return [accion for accion in _ORDEN if accion in acciones]


def bloques_pendientes(bloques: list[Any], *, omitidos: frozenset[str] | set[str] = frozenset()) -> list[str]:
    """Los bloques que impiden dar el informe por terminado.

    Son solo los de IA sin aprobar. Exigirlo a **todos** lo haría inalcanzable por
    construcción: nada transiciona un `STATIC_TEXT` o un `DETERMINISTIC_DATA` a `approved`.
    Lo que se revisa es lo que escribió el modelo.

    Vivía en `preview_builder`, y el ensamblador del grafo usaba una regla **distinta**: se
    bloqueaba solo si un bloque `required` estaba `failed`, y `required` es `False` por defecto
    en todo bloque. Con eso, un informe con dos apartados de IA fallidos llegaba a `assembled`
    —insignia «Listo para exportar»— y luego la vista previa y la exportación devolvían 409 por
    esos mismos bloques. Ahora la regla es una sola y vive aquí.

    `omitidos` son los bloques que alguien decidió saltarse (`skip_blocks` del grafo): un
    apartado descartado a conciencia no puede seguir bloqueando el informe.
    """
    return [
        b.block_id
        for b in bloques
        if b.block_id not in omitidos
        and b.kind in TIPOS_DE_IA
        and b.status not in ESTADOS_APROBADOS
    ]


def acciones_del_informe(status: str, bloques: list[Any]) -> list[str]:
    """Lo que se puede hacer con el informe entero, ahora mismo (#243).

    Hoy, sólo «ensamblar»: cuando está **en revisión** y no queda nada pendiente. El panel lo
    deducía de que ningún bloque tuviera acciones, y eso también es verdad antes de generar
    —un informe recién creado anunciaba «todos aprobados»— y después de ensamblar, cuando el
    botón seguía ahí y el servidor lo rechazaba.
    """
    if status == "in_review" and not bloques_pendientes(bloques):
        return ["ensamblar"]
    return []
