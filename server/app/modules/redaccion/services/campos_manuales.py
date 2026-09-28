"""Los campos del formulario que salen de los bloques `USER_INPUT` (issue #86). Deploy: edge.

**Por qué se deriva al servir y no se guarda.** Es el mismo argumento que INF.1 usó para el
`required` de las zonas de arrastre: las versiones de plantilla son inmutables y la del
doctorado —la que tiene el problema— ya está sembrada. Un arreglo que dependa de volver a
sembrar no llega a ella, porque el sembrador salta por nombre las plantillas que ya existen, a
propósito, y la vía correcta sería publicar una versión nueva. Derivar al servir arregla también
lo que ya está publicado.

**Y por qué hacía falta.** `spec_builder` deriva `manual_fields` de los **slots de entrada**, y
lo que hay que rellenar aquí son **bloques**. Son dos cosas distintas y confundirlas es lo que
dejó el contrato describiendo un informe que no se puede completar: cuatro bloques que piden un
dato de una persona y ningún campo donde dárselo.
"""

from __future__ import annotations

from server.app.modules.redaccion.contracts.template import ReportTemplateSpec
from server.app.modules.redaccion.contracts.ui import (
    ReportUIContract,
    UIFieldDescriptor,
)


def campos_de_los_bloques(spec: ReportTemplateSpec) -> list[UIFieldDescriptor]:
    """Un campo por cada bloque `USER_INPUT` que la plantilla no declarara ya.

    La etiqueta lleva **una sola lengua**. El bloque trae `title` como cadena suelta, así que
    repetirla bajo `es`, `ca` y `en` fingiría que está traducida; con una sola clave,
    `getLocalizedLabel` cae a ella para cualquier idioma, que es lo que ya hace con las
    etiquetas que sólo traen castellano.
    """
    declarados = {campo.slot_id for campo in spec.ui_contract.manual_fields}
    return [
        UIFieldDescriptor(
            slot_id=bloque.id,
            label={"es": bloque.title},
            field_type=getattr(bloque, "field_type", "text"),
            required=bloque.required,
        )
        for bloque in spec.blocks
        if bloque.kind == "USER_INPUT" and bloque.id not in declarados
    ]


def con_los_campos_de_los_bloques(spec: ReportTemplateSpec) -> ReportUIContract:
    """El contrato de UI de la plantilla, con los campos de sus bloques `USER_INPUT` añadidos.

    Lo que la plantilla declaró se respeta tal cual y va primero: derivar completa, nunca pisa.
    """
    derivados = campos_de_los_bloques(spec)
    if not derivados:
        return spec.ui_contract
    return spec.ui_contract.model_copy(
        update={"manual_fields": [*spec.ui_contract.manual_fields, *derivados]}
    )
