"""Quién puede qué con un agente de unidad, y quién lo ve (#172).

Deploy: edge.

**La gobernanza es la del catálogo de funciones**, trasladada sin inventar nada
(`redaccion/funciones_acciones.py`):

* **Registrar es publicar.** Sin aprobación previa: la normativa de referencia la prohíbe como
  condición para compartir dentro del servicio. La revisión es posterior y no bloquea usar.
* **Suspender es de quien revisa; retirar es de quien publica.** Quien revisa es el
  administrador de la organización o el superadministrador, **nunca quien lo publicó**.

Lo que **no** se traslada es la auditoría: nada lee un corpus y dice «esto ya no vale». Lo que
hace sus veces es la declaración —finalidad, responsable, colectivo y **fecha de revisión
prevista**—, y la fecha **avisa, no oculta** (decisión del usuario, 2026-10-02).

Y `acciones_permitidas` la calcula el servidor (regla maestra 2): la pantalla itera la lista.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

from server.app.core.identidad import user_to_uuid

#: Lo que la revisión posterior puede dejar. **«aprobada» no está, a propósito**: no hay nada que
#: aprobar. Suspender es una acción aparte, con su motivo.
RESULTADOS_DE_REVISION: tuple[str, ...] = ("conforme", "correcciones")

#: Orden estable de los botones: primero lo que hace avanzar el agente, después lo que lo frena.
_ORDEN = ("versionar", "cargar_indice", "revisar", "suspender", "reactivar", "retirar")


class AgenteIncoherente(ValueError):
    """La operación no se sostiene: falta el motivo, o el agente ya no admite cambios."""


class RevisionInvalida(ValueError):
    """El resultado de revisión no es uno de los que hay."""


def _organizaciones(principal: Any) -> set[str]:
    return {str(o) for o in (getattr(principal, "organizacion_ids", None) or ())}


def _es_de_su_organizacion(agente: Any, principal: Any) -> bool:
    return str(agente.organizacion_id) in _organizaciones(principal)


def _es_la_autora(agente: Any, principal: Any) -> bool:
    user_id = getattr(principal, "user_id", "")
    return bool(user_id) and agente.creado_por == user_to_uuid(user_id)


def acciones_permitidas(agente: Any, version: Any, *, principal: Any) -> list[str]:
    """Lo que **quien pregunta** puede pedir sobre la versión vigente del agente, ahora mismo."""
    if version.estado == "retirada":
        return []

    superadmin = bool(getattr(principal, "is_superadmin", False))
    de_la_casa = _es_de_su_organizacion(agente, principal)
    admin_de_la_casa = de_la_casa and bool(getattr(principal, "is_admin", False))
    autora = _es_la_autora(agente, principal) and de_la_casa
    manda = superadmin or admin_de_la_casa

    acciones: set[str] = set()
    if superadmin or autora or admin_de_la_casa:
        # Cargar el índice es mantener el agente, como versionarlo: de quien lo publicó (#173).
        acciones.update({"versionar", "cargar_indice", "retirar"})
    if manda and not autora:
        if version.estado == "registrada":
            acciones.update({"revisar", "suspender"})
        if version.estado == "suspendida":
            acciones.add("reactivar")
    return [a for a in _ORDEN if a in acciones]


def lo_puede_usar(agente: Any, version: Any, *, principal: Any) -> bool:
    """Si el agente se le ofrece a esta persona en el catálogo.

    **La organización primero, siempre**: un grupo con el mismo nombre en otra organización no
    da acceso. Y los grupos se comparan sin mayúsculas, como las concesiones de módulos.

    Una revisión vencida **no** entra aquí: avisa, no oculta.
    """
    if version.estado != "registrada":
        return False
    if getattr(principal, "is_superadmin", False):
        return True
    if not _es_de_su_organizacion(agente, principal):
        return False
    if version.colectivo == "organizacion":
        return True
    suyos = {g.strip().lower() for g in (getattr(principal, "saml_groups", None) or ())}
    return any(g.strip().lower() in suyos for g in (version.grupos or []))


def revision_vencida(version: Any, *, hoy: date | None = None) -> bool:
    """Si ya pasó la fecha que la unidad declaró para volver a mirarlo. El mismo día, no."""
    return (hoy or date.today()) > version.revision_prevista_en


def aplicar_revision(
    version: Any, *, resultado: str, nota: str | None, revisada_por: uuid.UUID
) -> None:
    """Sella la revisión posterior. **No cambia el estado**: revisar no bloquea usar."""
    if resultado not in RESULTADOS_DE_REVISION:
        raise RevisionInvalida(
            f"«{resultado}» no es un resultado de la revisión posterior; los que hay son "
            f"{', '.join(RESULTADOS_DE_REVISION)}. Aprobar no es uno: no hay nada que aprobar, y "
            "para dejar de ofrecerlo está suspender."
        )
    version.revisada_por = revisada_por
    version.revisada_en = datetime.now(timezone.utc)
    version.revision_resultado = resultado
    version.revision_nota = (nota or "").strip() or None


def suspender(version: Any, *, motivo: str | None, suspendida_por: uuid.UUID) -> None:
    """Deja de ofrecerlo. **Con motivo**: quien lo publicó tiene que saber qué corregir."""
    if not motivo or not str(motivo).strip():
        raise AgenteIncoherente(
            "suspender exige motivo: quien publicó el agente tiene que saber qué corregir"
        )
    version.estado = "suspendida"
    version.motivo_suspension = str(motivo).strip()
    version.suspendida_por = suspendida_por
    version.suspendida_en = datetime.now(timezone.utc)


def reactivar(version: Any) -> None:
    """Vuelve a ofrecerse. **El motivo se conserva**: es historia de por qué estuvo suspendido."""
    version.estado = "registrada"


def retirar(version: Any) -> None:
    """Terminal: un agente retirado no vuelve. Para volver a publicarlo, se publica otro."""
    version.estado = "retirada"
