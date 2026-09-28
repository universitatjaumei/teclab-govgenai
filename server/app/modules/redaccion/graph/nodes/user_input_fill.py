"""UserInputFillNode — lo que escribió una persona acaba en su bloque (issue #86). Deploy: edge.

Los bloques `USER_INPUT` estaban en el contrato y **nadie los rellenaba**: no había campo donde
escribir y, si lo hubiera habido, el valor no llegaba al informe. Sembrar sólo el campo habría
sido peor que la sección vacía, porque un formulario que se rellena y cuya respuesta no sale
parece que funcionó. Este nodo es la otra mitad.

Va **detrás de la validación de entradas y delante de todo lo demás**: no depende de ningún
fichero ni de ninguna extracción, y ponerlo pronto hace que lo escrito esté disponible para los
bloques de IA que lo citen.

El contenido se escribe como `{"text": …}`, que es lo que `contenido_a_markdown` sabe imprimir.

Y va **delante de `init_anonymization`**, que no es casual: ese nodo escanea
`blocks[*].content`, así que un nombre que teclea una persona se anonimiza igual que uno
que salió de un documento. Al revés viajaría al modelo sin tocar.
"""

from __future__ import annotations

from datetime import datetime, timezone

from server.app.modules.redaccion.contracts.runtime import (
    ExtractionWarning,
    WorkspaceState,
)


class UserInputFillNode:
    """Vuelca `state.manual_inputs` en el `content` de los bloques `USER_INPUT`."""

    async def __call__(self, state: WorkspaceState) -> dict:
        if state.spec is None:
            return {}

        bloques = dict(state.blocks)
        avisos = list(state.warnings)
        ahora = datetime.now(timezone.utc)
        tocado = False

        for contrato in state.spec.blocks:
            if contrato.kind != "USER_INPUT":
                continue
            bloque = bloques.get(contrato.id)
            if bloque is None:
                continue

            valor = state.manual_inputs.get(contrato.id)
            texto = str(valor).strip() if valor is not None else ""

            if texto:
                bloques[contrato.id] = bloque.model_copy(
                    update={
                        "content": {"text": texto},
                        "status": "extracted",
                        # Quien lo escribió es una persona, y eso se dice: el informe distingue
                        # lo que aportó alguien de lo que dedujo el sistema.
                        "last_updated_by": "user",
                        "updated_at": ahora,
                    }
                )
                tocado = True
            elif contrato.required:
                # Se dice en vez de callarlo: la sección vacía sin explicación es justo el
                # síntoma que abrió esta issue.
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
