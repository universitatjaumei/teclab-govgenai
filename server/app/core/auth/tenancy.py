"""Frontera entre organizaciones (SEC.2, hallazgo A2). Deploy: shared.

**Una sola capa, no una comprobación repetida en cada endpoint.** El hallazgo A2 no fue que a
un endpoint se le olvidara filtrar: fue que no había dónde hacerlo, así que ninguno filtraba.
Repartir la regla por veinte sitios habría reproducido el problema en cuanto se añadiera el
veintiuno; concentrarla aquí hace que el endpoint nuevo tenga que decidir explícitamente
saltársela, y eso se ve en una revisión.

Dos operaciones, y hacen falta las dos:

- `assert_org_access` para el acceso **a una entidad concreta** que ya se ha leído.
- `scope_query_to_orgs` para los **listados**, donde comprobar después de leer no vale:
  filtrar en memoria tras un `LIMIT` deja fuera resultados propios y sigue trayendo ajenos a
  la memoria del proceso.

**El vacío significa lo contrario según el rol.** En un superadmin es el comodín «todas»; en
cualquier otro es «ninguna». Es la asimetría de la que depende todo el módulo, y por eso está
en un test: si «vacío = todas» valiera para cualquiera, olvidarse de poblar el claim
devolvería el acceso horizontal sin que nada fallara.
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException, status

from server.app.core.auth.models import UserInfo


def _principal(sujeto: Any) -> UserInfo:
    """Acepta un `UserInfo` o cualquier cosa que lo lleve dentro, como `PatPrincipal`."""
    return getattr(sujeto, "user_info", sujeto)


def puede_acceder(sujeto: Any, organizacion_id: Any) -> bool:
    """¿Este principal puede tocar datos de esta organización?"""
    principal = _principal(sujeto)
    if getattr(principal, "is_superadmin", False):
        return True
    if organizacion_id is None:
        # Sin organización no hay forma de decidir, y no decidir es dejar pasar.
        return False
    return str(organizacion_id) in principal.organizacion_ids


def assert_org_access(sujeto: Any, organizacion_id: Any) -> None:
    """403 si el principal no gestiona esa organización. El superadmin siempre pasa.

    Es **403 y no 404**: quien ha llegado hasta aquí está autenticado y el recurso existe;
    fingir que no existe complicaría la depuración sin ocultar gran cosa, porque los ids son
    UUID y no se adivinan.
    """
    if not puede_acceder(sujeto, organizacion_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes acceso a los datos de esta organización",
        )


def orgs_del_principal(sujeto: Any) -> tuple[uuid.UUID, ...]:
    """Los ids como UUID, descartando los que no lo sean en vez de reventar la consulta."""
    principal = _principal(sujeto)
    validos: list[uuid.UUID] = []
    for bruto in principal.organizacion_ids:
        try:
            validos.append(uuid.UUID(str(bruto)))
        except (ValueError, AttributeError, TypeError):
            continue
    return tuple(validos)


def organizacion_unica_de(sujeto: Any) -> uuid.UUID | None:
    """La organización de un principal **cuando pertenece a una sola**; `None` si no.

    Sirve a MT.3: los llamadores de Informes tienen que decir para qué organización piden un
    modelo, y hasta que MT.4 le dé la dimensión al módulo lo único que hay es quien pide.

    **Sólo con una.** Con varias no hay forma de saber cuál es «la suya», y en un
    superadministrador la lista vacía significa «todas» (ver `UserInfo.organizacion_ids`): en
    los dos casos la respuesta honesta es `None`, que en la cascada quiere decir «plataforma» —
    y que además es el comportamiento de hoy. Es el mismo criterio con el que REV.12 resolvió
    la marca institucional, y por la misma razón.
    """
    orgs = orgs_del_principal(sujeto)
    return orgs[0] if len(orgs) == 1 else None


def organizacion_para_operar(sujeto: Any, organizacion_id: Any, *, para: str) -> uuid.UUID:
    """La organización sobre la que opera esta petición: **la indicada, o la única del principal**.

    Para lo que tiene que ser de una organización —un uso que se anota en su registro, un agente
    que se publica en ella— y lo pide alguien que no pertenece a una sola: el superadministrador
    con una elegida en el selector del panel, o un token de varias. **Siempre se comprueba**: si
    no, cualquiera anotaría usos en el registro de otra organización pasando su id.

    `para` dice qué se iba a hacer, y es el principio del mensaje cuando no hay ninguna.
    """
    org = organizacion_id or organizacion_unica_de(sujeto)
    if org is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "ORGANIZACION_INDETERMINADA",
                "message": (
                    f"{para} Tu cuenta no pertenece a una sola organización: elige una en el "
                    "selector del panel."
                ),
            },
        )
    assert_org_access(sujeto, org)
    return org if isinstance(org, uuid.UUID) else uuid.UUID(str(org))


def scope_query_to_orgs(stmt, sujeto: Any, model, columna: str = "organizacion_id"):
    """Acota un SELECT a las organizaciones del principal. El superadmin no se acota.

    Un principal **sin** organizaciones recibe un `IN ()` vacío, que no devuelve nada. Es
    intencionado y es la diferencia entre «no ve nada» y «no se filtra»: devolver el listado
    entero cuando el claim viene vacío es el hallazgo A2 otra vez.
    """
    principal = _principal(sujeto)
    if getattr(principal, "is_superadmin", False):
        return stmt
    return stmt.where(getattr(model, columna).in_(orgs_del_principal(principal)))


# ─────────────── Resolución del dueño (SEC.8.1) ───────────────
#
# SEC.2 dejó las dos operaciones de arriba, que bastan cuando el endpoint YA tiene delante
# la organización. El agujero de SEC.8.1 fue otro: los routers que llegaron después reciben
# un `chatbot_id` o un `site_id` por la ruta y **la organización no está a la vista**, así
# que comprobarla exigía un paso previo que cada endpoint tenía que recordar hacer. Nadie lo
# recordó. Estos dos resolvedores son ese paso previo, escrito una vez.


async def assert_chatbot_org_access(session, chatbot_id: Any, sujeto: Any):
    """Carga el chatbot, 404 si no existe, y exige su organización al principal.

    Distinto de `chatbot_access.assert_chatbot_access`, que decide el **modo de acceso**
    (público/autenticado/restringido) de un chatbot que ya se ha resuelto. Esto decide lo
    anterior: si el principal puede siquiera mirar ese chatbot.
    """
    from server.app.modules.agents_hub.database.config_models import HubChatbot

    chatbot = await session.get(HubChatbot, chatbot_id)
    if chatbot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Chatbot no encontrado"
        )
    assert_org_access(sujeto, chatbot.organizacion_id)
    return chatbot


async def assert_site_org_access(session, site_id: Any, sujeto: Any):
    """Lo mismo para un sitio rastreado de curación (`HubWebSite`)."""
    from server.app.modules.agents_hub.database.operational_models import HubWebSite

    sitio = await session.get(HubWebSite, site_id)
    if sitio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Sitio no encontrado"
        )
    assert_org_access(sujeto, sitio.organizacion_id)
    return sitio
