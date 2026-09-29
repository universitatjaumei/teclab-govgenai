"""Quién puede qué con una función del catálogo, y cuándo (FUN.4).

Deploy: edge.

Aquí la Instrucció 02/2026 se convierte en máquina de estados. La idea que gobierna el módulo es
**control proporcional al alcance**:

* **Nivel 2** —compartir dentro del servicio— no lleva aprobación previa. La revisión posterior
  puede pedir correcciones, reclasificar o suspender, pero **revisar no bloquea usar**: una
  versión recién registrada está en la cola de revisión *y* funcionando. Bloquear sería
  aprobación previa con otro nombre, y es lo que empuja al *Shadow IT*.
* **Nivel 3** —alcance superior al servicio— sí la lleva: la promoción la valora el
  superadministrador con motivo escrito. Es la única aprobación previa del bloque.

Dos reparticiones de responsabilidad que no se mezclan (§9):

* **Suspender es de quien revisa; retirar es de quien escribe.** El autor no puede reactivar lo
  que otro suspendió: si pudiera, suspender no sería una decisión, sería una sugerencia.
* **Revisar es de otra persona.** La autora de una función no aparece como revisora de su propia
  versión.

Y `acciones_permitidas` las calcula el servidor (regla maestra 2): la pantalla itera la lista. Si
una acción aparece, su endpoint no puede responder 403 ni 422 por estado — la lista es un
subconjunto de lo posible, nunca un superconjunto.
"""
from __future__ import annotations

import random
import uuid
from datetime import datetime, timezone
from typing import Any

from server.app.modules.redaccion.funciones_service import FuncionIncoherente

#: Los resultados que la revisión posterior puede dejar (§8.4). **«aprobada» no está, y no está a
#: propósito**: aprobar no es un resultado de la revisión posterior, porque en el nivel 2 no hay
#: nada que aprobar.
RESULTADOS_DE_REVISION: tuple[str, ...] = (
    "conforme",
    "correcciones",
    "reclasificada",
    "suspendida",
)

#: Orden estable de los botones: lo decide el servidor, como en `block_actions`. Primero lo que
#: hace avanzar la función, después lo que la frena.
_ORDEN = (
    "adoptar_version",
    "versionar",
    "revisar",
    "solicitar_promocion",
    "promover",
    "suspender",
    "reactivar",
    "retirar",
)

#: Estados en los que una versión ya no admite ninguna acción: `retirada` es terminal y
#: `no_instalada` lo decide el `pip uninstall`, no una persona.
_TERMINALES = frozenset({"retirada", "no_instalada"})


class RevisionInvalida(ValueError):
    """El resultado de revisión no es uno de los que la Instrucció contempla."""


class PromocionInvalida(ValueError):
    """La promoción a nivel 3 no se sostiene."""


def _es_superadmin(principal: Any) -> bool:
    return bool(getattr(principal, "is_superadmin", False))


def _organizaciones(principal: Any) -> set[str]:
    return {str(o) for o in (getattr(principal, "organizacion_ids", None) or ())}


def _es_de_su_organizacion(funcion: Any, principal: Any) -> bool:
    propietaria = getattr(funcion, "organizacion_id", None)
    if propietaria is None:
        return False
    return str(propietaria) in _organizaciones(principal)


def _es_la_autora(funcion: Any, principal: Any) -> bool:
    creada_por = getattr(funcion, "creada_por", None)
    if creada_por is None:
        return False
    return str(creada_por) == str(getattr(principal, "user_id", ""))


def _publicada(funcion: Any) -> bool:
    return getattr(funcion, "publicada_en", None) is not None or getattr(
        funcion, "organizacion_id", None
    ) is None


def acciones_permitidas(funcion: Any, version: Any, *, principal: Any) -> list[str]:
    """Lo que **quien pregunta** puede pedir sobre esta versión, ahora mismo.

    Se calcula aquí y viaja en el DTO. Si esto viviera en React como un `rol === 'admin'`, sería
    la autorización escrita por segunda vez, y el día que cambiara dirían cosas distintas.
    """
    estado = getattr(version, "estado", "draft")
    origen = getattr(funcion, "origen", "autoservicio")
    de_paquete = origen == "paquete"
    # AUT.3 — una función externa **no se adopta**: adoptar es anclarla en una plantilla, y una
    # plantilla la ejecuta. Ofrecer el botón sería ofrecer la acción que la garantía de este
    # origen —se registra, no se ejecuta— existe para impedir.
    de_fuera = origen == "externa"
    superadmin = _es_superadmin(principal)
    de_la_casa = _es_de_su_organizacion(funcion, principal)
    admin_de_la_casa = de_la_casa and bool(getattr(principal, "is_admin", False))
    autora = _es_la_autora(funcion, principal)
    manda = superadmin or admin_de_la_casa

    acciones: set[str] = set()

    # Usar lo publicado por otra organización es el caso de la consumidora: puede anclar una
    # versión y nada más.
    if (_publicada(funcion) or de_la_casa) and not de_fuera:
        if estado == "registrada":
            acciones.add("adoptar_version")

    if estado in _TERMINALES:
        # `retirada` es terminal: ofrecer cualquier cosa sería un botón que da 422.
        return [a for a in _ORDEN if a in acciones and a == "adoptar_version"]

    # Versionar: sólo la autora (o la plataforma). Una función de paquete se versiona con `pip`.
    if not de_paquete and (superadmin or ((autora or admin_de_la_casa) and de_la_casa)):
        acciones.add("versionar")

    # Retirar es de quien escribe —y del superadministrador, que puede vetar una instalada—.
    if superadmin or (autora and de_la_casa) or (admin_de_la_casa and not de_paquete):
        acciones.add("retirar")

    # Revisar y suspender son de quien revisa, y **no** de la autora: revisar es de otra persona.
    if manda and not autora:
        if estado == "registrada":
            acciones.add("revisar")
            acciones.add("suspender")
        if estado == "suspendida":
            acciones.add("reactivar")

    # El paso a nivel 3: lo pide la organización autora, lo resuelve el superadministrador.
    if not de_paquete and not _tiene_publicacion(funcion):
        if admin_de_la_casa:
            acciones.add("solicitar_promocion")
        if superadmin and getattr(funcion, "promocion_solicitada_en", None) is not None:
            acciones.add("promover")

    return [a for a in _ORDEN if a in acciones]


def _tiene_publicacion(funcion: Any) -> bool:
    return getattr(funcion, "publicada_en", None) is not None


def aplicar_revision(
    version: Any, *, resultado: str, nota: str | None, revisada_por: uuid.UUID
) -> None:
    """Sella la revisión posterior. **`correcciones` y `reclasificada` no cambian el estado.**

    La corrección es una versión nueva del autor, y la reclasificación es una señal para el
    nivel 3: las dos dejan la versión en uso, que es lo que distingue una revisión posterior de
    una aprobación previa.
    """
    if resultado not in RESULTADOS_DE_REVISION:
        raise RevisionInvalida(
            f"«{resultado}» no es un resultado de la revisión posterior; los que hay son "
            f"{', '.join(RESULTADOS_DE_REVISION)}. Aprobar no es uno: en el nivel 2 no hay "
            "nada que aprobar."
        )

    version.revisada_por = revisada_por
    version.revisada_en = datetime.now(timezone.utc)
    version.revision_resultado = resultado
    version.revision_nota = nota or None

    if resultado == "suspendida":
        suspender(version, motivo=nota, suspendida_por=revisada_por)


def candidata_a_nivel_3(funcion: Any, versiones: list[Any]) -> tuple[bool, list[str]]:
    """Si esta función parece exceder el nivel 2, y por qué.

    **No se infiere nada más** que lo que alguien ha dicho: una reclasificación en la revisión, o
    una promoción pedida. Ni por antigüedad, ni por cuántas plantillas la usan: la Instrucció
    deja la valoración a personas y la plataforma sólo la señala.
    """
    motivos: list[str] = []
    if any(getattr(v, "revision_resultado", None) == "reclasificada" for v in versiones):
        motivos.append(
            "una revisión la reclasificó: su alcance excede el nivel 2"
        )
    if getattr(funcion, "promocion_solicitada_en", None) is not None:
        motivos.append("su organización ha solicitado la promoción")
    return bool(motivos), motivos


def muestra_para_revisar(versiones: list[Any], *, cuantas: int) -> list[Any]:
    """`cuantas` versiones **no revisadas**, al azar.

    Al azar y no las primeras: con un orden fijo, las últimas de la cola no se revisarían nunca,
    y el muestreo de §8.4 existe justamente para que revisar no exija leerlo todo.
    """
    sin_revisar = [v for v in versiones if getattr(v, "revisada_por", None) is None]
    if cuantas >= len(sin_revisar):
        return sin_revisar
    return random.sample(sin_revisar, cuantas)


def suspender(version: Any, *, motivo: str | None, suspendida_por: uuid.UUID) -> None:
    """Deja la versión sin ejecutar. **Con motivo**, que viaja hasta el fallo del bloque."""
    if not motivo or not str(motivo).strip():
        raise FuncionIncoherente(
            "suspender exige motivo: el bloque anclado a esta versión va a fallar en alto y "
            "tiene que poder decir por qué"
        )
    version.estado = "suspendida"
    version.motivo_suspension = str(motivo).strip()
    version.suspendida_por = suspendida_por
    version.suspendida_en = datetime.now(timezone.utc)


def reactivar(version: Any) -> None:
    """Vuelve a `registrada`. **El motivo se conserva**: es historia de por qué estuvo suspendida."""
    version.estado = "registrada"


def promover(funcion: Any, *, valoracion: str, publicada_por: uuid.UUID) -> None:
    """Publica la función a nivel de plataforma. La única aprobación **previa** del bloque.

    No muta código ni versiones, y **la organización autora se conserva** como atribución: la
    plataforma no se apropia de lo que hizo un servicio.
    """
    if getattr(funcion, "origen", "autoservicio") == "paquete":
        raise PromocionInvalida(
            "una función empaquetada ya es de plataforma: la instala quien opera el despliegue, "
            "así que promoverla no significaría nada"
        )
    if not valoracion or not valoracion.strip():
        raise PromocionInvalida(
            "promover exige una valoración escrita: es la única aprobación previa del catálogo "
            "y es lo que la hace auditable"
        )
    funcion.publicada_en = datetime.now(timezone.utc)
    funcion.publicada_por = publicada_por
    funcion.valoracion_promocion = valoracion.strip()
