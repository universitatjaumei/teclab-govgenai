"""Reclasificación del corpus al sustituir un término del vocabulario (ING.0.2).

Deploy: edge — escribe documentos del cliente.

Es la otra mitad de `vocabulary/load.py:supersede_term`, que solo marca el término
antiguo. Aquí se barren los documentos que lo usaban.

**Las dos se llaman desde `vocabulary/load.py:sustituir_termino`, y no por separado** (issue
#153). Durante un tiempo no las llamaba nadie: el barrido existía, estaba probado, y renombrar
un término dejaba los documentos con el código viejo sin que nada diera error.

**Invariante que sostiene la promesa de vocabulario revisable** (CLAUDE.md §5):
reclasificar cuesta un `UPDATE` y **no toca ni un chunk**. Es cierto porque la
taxonomía nunca entra en el texto embebido; si alguien la mete, este servicio deja de
ser suficiente y cada revisión del vocabulario pasa a costar un re-embedding del corpus.
"""
from __future__ import annotations

import uuid

from collections.abc import Sequence

from sqlalchemy import case, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.modules.agents_hub.database.operational_models import HubDocument
from server.app.modules.agents_hub.services.vocabulary_service import VocabularyAxis

# Columnas afectadas por eje. Solo los dos ejes que el documento materializa como
# columnas de primer nivel; los demás (rang, colectiu, tipus) viven en doc_metadata y
# no gobiernan la recuperación, así que no se barren aquí.
_COLUMNAS_POR_EJE: dict[str, tuple[str, tuple[str, ...]]] = {
    VocabularyAxis.AMBIT: ("ambit_principal", ("ambits_secundaris",)),
    VocabularyAxis.SUBMATERIA: (None, ("submateries", "submateries_internes")),
}

#: Los ejes que esta función sabe barrer. Quien orquesta la sustitución lo consulta **antes** de
#: llamar: para `rang` o `colectiu` no hay nada que barrer, y eso no es un error que deba
#: impedir renombrar el término.
AXES_BARRIBLES: frozenset[str] = frozenset(_COLUMNAS_POR_EJE)


async def reclassify_documents(
    session: AsyncSession,
    axis: str,
    codi_antic: str,
    codi_nou: str,
    *,
    chatbot_ids: Sequence[uuid.UUID],
) -> int:
    """Sustituye `codi_antic` por `codi_nou` en los documentos de esos chatbots.

    Devuelve el número de documentos tocados. Idempotente: una segunda pasada
    devuelve 0 porque ya no queda ninguno con el código antiguo.

    **`chatbot_ids` es obligatorio y sin valor por omisión, a propósito.** Antes era un
    `chatbot_id | None` que quien llamaba dejaba en `None`, y entonces el barrido cruzaba la
    frontera entre organizaciones: el vocabulario es **por organización**, pero dos
    organizaciones pueden usar el mismo código —`personal`, `beques`, `contractacio` no son de
    nadie— y el `UPDATE` las alcanzaba a todas. Un ámbito que se puede omitir se omite; uno que
    hay que escribir obliga a pensar de quién son los documentos que se van a reescribir.

    Una lista vacía significa «esta organización no tiene chatbots», y entonces no hay nada que
    barrer: devuelve 0 sin tocar nada. Es distinto de no acotar.
    """
    if not chatbot_ids:
        return 0
    if axis not in _COLUMNAS_POR_EJE:
        raise ValueError(
            f"Eje '{axis}' sin columnas en hub_documents. "
            f"Ejes barribles: {sorted(_COLUMNAS_POR_EJE)}"
        )
    if codi_antic == codi_nou:
        raise ValueError("El código antiguo y el nuevo son el mismo")

    columna_escalar, columnas_array = _COLUMNAS_POR_EJE[axis]

    condiciones = [
        getattr(HubDocument, nombre).any(codi_antic) for nombre in columnas_array
    ]
    if columna_escalar:
        condiciones.append(getattr(HubDocument, columna_escalar) == codi_antic)

    filtro = [or_(*condiciones), HubDocument.chatbot_id.in_(list(chatbot_ids))]

    afectados = await session.scalar(
        select(func.count()).select_from(HubDocument).where(*filtro)
    )
    if not afectados:
        return 0

    valores: dict = {
        nombre: func.array_replace(getattr(HubDocument, nombre), codi_antic, codi_nou)
        for nombre in columnas_array
    }
    if columna_escalar:
        # **Igualdad, no `replace()`.** La fila entra en el `UPDATE` si **cualquiera** de sus
        # columnas trae el código viejo, así que el escalar se tocaba aunque no fuera el código:
        # un documento con `ambits_secundaris = ["administracio"]` y
        # `ambit_principal = "administracio-general"` salía con el ámbito principal convertido en
        # `"gerencia-general"`. `replace()` sustituye subcadenas y aquí el código viejo puede ser
        # prefijo de otro perfectamente legítimo. Y no da ningún error.
        columna = getattr(HubDocument, columna_escalar)
        valores[columna_escalar] = case((columna == codi_antic, codi_nou), else_=columna)

    await session.execute(
        update(HubDocument).where(*filtro).values(**valores)
    )
    return int(afectados)
