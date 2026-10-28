"""Validación de perfil y modo de recuperación contra los registros vivos.

Deploy: edge

**Por qué esto existe y no un `Literal[...]` en el DTO.** Hasta PLG.1 el modo de recuperación era
un `Literal["RAG", "MD_LONG_CONTEXT", "MD_AGENT_SELECTOR"]` en tres sitios de
`hub_chatbots_router`, y el perfil era `str` **sin validar ninguna**. Las dos cosas estaban mal
por el mismo motivo, en direcciones opuestas:

* El `Literal` **cierra** el vocabulario en el código: un modo aportado por un paquete instalado
  lo rechazaría el propio FastAPI antes de llegar a nadie, y no habría forma de aceptarlo sin
  tocar el repositorio. Es lo contrario de lo que PLG construye.
* El `str` libre **no comprueba nada**: se podía guardar `public_graph_profile="PUBLICO"` y el
  fallo aparecía al primer mensaje del usuario, como «perfil desconocido», lejos del formulario
  que lo causó.

Lo correcto es lo de en medio: **cadena en el contrato, validada contra el registro vivo**. El
contrato OpenAPI expone `str` —que es la verdad, porque la lista depende de lo instalado— y la
lista para el panel llega por el endpoint de opciones de PLG.3.

El 422 **lista siempre las opciones válidas**. Un «perfil desconocido» a secas obliga a ir al
código, y quien configura un chatbot desde el panel no tiene el código delante.
"""

from __future__ import annotations

from fastapi import HTTPException, status

from server.app.modules.agents_hub.agent.public_graphs.registry import list_profiles
from server.app.modules.agents_hub.agent.public_graphs.strategies.retrieval_pipeline_factory import (
    list_modes,
)


def _error(campo: str, valor: str, disponibles: list[str], extra: str = "") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={
            "campo": campo,
            "valor": valor,
            "disponibles": disponibles,
            "mensaje": (
                f"'{valor}' no es un valor válido para {campo}. Disponibles: "
                f"{', '.join(disponibles)}.{(' ' + extra) if extra else ''}"
            ),
        },
    )


def validar_perfil(valor: str | None, campo: str = "public_graph_profile") -> None:
    """Rechaza un perfil que no esté registrado, o que esté registrado pero sin configurar.

    `None` pasa: significa «hereda», y quién hereda de quién lo decide la cascada, no esto.
    """
    if valor is None:
        return

    from server.app.modules.agents_hub.agent.public_graphs.core.graph_factory import (
        PERFILES_SIN_CONFIGURAR,
    )

    disponibles = sorted(list_profiles())
    if valor not in disponibles:
        raise _error(campo, valor, disponibles)

    if valor in PERFILES_SIN_CONFIGURAR:
        # Registrado y ofrecido, pero su factoría lanza `NotImplementedError` a propósito: le
        # faltan campos de configuración que nadie ha definido todavía. Dejar que se guarde
        # significaría un asistente que responde «no encuentro información» con el corpus
        # perfectamente cargado — el hallazgo I5 de la auditoría, que costó encontrar.
        raise _error(
            campo,
            valor,
            sorted(set(disponibles) - PERFILES_SIN_CONFIGURAR),
            extra=(
                f"'{valor}' está registrado pero no está configurado: no hay dónde declarar los "
                f"chatbots de los que depende, así que recuperaría vacío en silencio."
            ),
        )


def validar_modo(valor: str | None, campo: str = "retrieval_mode") -> None:
    """Rechaza un modo de recuperación que no esté registrado. `None` significa «hereda»."""
    if valor is None:
        return

    disponibles = list_modes()
    if valor not in disponibles:
        raise _error(campo, valor, disponibles)


def validar_estrategias(
    valor: dict[str, str] | None, campo: str = "estrategias"
) -> None:
    """Cada clave un eje válido, cada valor una estrategia registrada EN ESE EJE (PLG.2).

    Se valida aquí y no con un CHECK en la base por la misma razón que el modo: un CHECK no puede
    saber qué paquetes hay instalados. Y se valida **por eje**, no contra un catálogo plano,
    porque el mismo nombre puede existir en dos ejes y significar cosas distintas.

    `None` y `{}` pasan: los dos significan «hereda todo», que es el caso normal.
    """
    if not valor:
        return

    from server.app.modules.agents_hub.agent.public_graphs.strategies.registry import (
        EjeDeEstrategia,
        list_strategies,
    )

    ejes = [e.value for e in EjeDeEstrategia]
    for eje, nombre in valor.items():
        if eje not in ejes:
            raise _error(
                f"{campo}.<eje>",
                eje,
                ejes,
                extra=(
                    "Los ejes son estructura: añadir uno exige escribir el nodo del CoreGraph "
                    "que lo consuma, así que no se pueden inventar desde la configuración."
                ),
            )
        if not nombre:
            # Cadena vacía = «no he elegido». Se deja pasar y la cascada la ignora, en vez de
            # rechazarla: un formulario que manda "" por un select sin tocar es normal.
            continue
        disponibles = list_strategies(eje)
        if nombre not in disponibles:
            raise _error(f"{campo}.{eje}", nombre, disponibles)
