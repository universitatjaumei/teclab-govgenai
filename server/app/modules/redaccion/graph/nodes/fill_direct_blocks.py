"""FillDirectBlocksNode — los bloques cuyo contenido no lo produce nadie. Deploy: edge.

Dos tipos de bloque tienen su contenido **antes** de que empiece el informe: el que lo trae
escrito en la plantilla (`STATIC_TEXT`) y el que lo escribe una persona (`USER_INPUT`). No hay
pipeline que los extraiga ni modelo que los redacte, así que sin un paso que los vuelque al
`content` del bloque **no aparecen en el informe**: el ensamblador salta lo que no tiene
contenido.

Y era exactamente lo que pasaba. Los dos tenían su clase en `blocks/handlers.py`
—`StaticTextHandler` y `UserInputHandler`— que **nadie montaba** (issue #180), y el resultado
medido es el de siempre: un `STATIC_TEXT` en la plantilla de ejecución presupuestaria que nunca
se imprimía, y cuatro `USER_INPUT` en la del doctorado sin dónde rellenarse (issue #86). Una
clase que nadie ejecuta no se prueba en uso.

Va **detrás de la validación de entradas y delante de todo lo demás**: no depende de ningún
fichero ni de ninguna extracción, y ponerlo pronto hace que lo escrito esté disponible para los
bloques de IA que lo citen.

Y va **delante de `init_anonymization`**, que no es casual: ese nodo escanea
`blocks[*].content`, así que un nombre que teclea una persona se anonimiza igual que uno que
salió de un documento. Al revés viajaría al modelo sin tocar.

El contenido se escribe como `{"text": …}`, que es lo que `contenido_a_markdown` sabe imprimir.
`CITATION_BLOCK` es el tercer tipo que tampoco produce nadie, y lo rellena
`citation_traceability`: es el nodo cuyo trabajo son las citas.
"""

from __future__ import annotations

from datetime import datetime, timezone

from server.app.modules.redaccion.contracts.runtime import (
    ExtractionWarning,
    WorkspaceState,
)


class FillDirectBlocksNode:
    """Vuelca en el `content` lo que trae la plantilla y lo que escribió una persona."""

    async def __call__(self, state: WorkspaceState) -> dict:
        if state.spec is None:
            return {}

        bloques = dict(state.blocks)
        avisos = list(state.warnings)
        ahora = datetime.now(timezone.utc)
        tocado = False

        for contrato in state.spec.blocks:
            bloque = bloques.get(contrato.id)
            if bloque is None:
                continue

            if contrato.kind == "STATIC_TEXT":
                texto = (getattr(contrato, "content", "") or "").strip()
                quien = "system"
            elif contrato.kind == "USER_INPUT":
                valor = state.manual_inputs.get(contrato.id)
                texto = str(valor).strip() if valor is not None else ""
                # Quien lo escribió es una persona, y eso se dice: el informe distingue lo que
                # aportó alguien de lo que dedujo el sistema.
                quien = "user"
            else:
                continue

            if texto:
                bloques[contrato.id] = bloque.model_copy(
                    update={
                        "content": {"text": texto},
                        "status": "extracted",
                        "last_updated_by": quien,
                        "updated_at": ahora,
                    }
                )
                tocado = True
            elif contrato.required:
                # Se dice en vez de callarlo: la sección vacía sin explicación es justo el
                # síntoma que abrió la issue #86.
                bloques[contrato.id] = bloque.model_copy(
                    update={"status": "missing_input", "updated_at": ahora}
                )
                avisos.append(
                    ExtractionWarning(
                        block_id=contrato.id,
                        kind="missing_data",
                        message=f"El campo «{contrato.title}» no se ha rellenado.",
                    )
                )
                tocado = True

        if not tocado:
            return {}
        return {"blocks": bloques, "warnings": avisos}

