"""Lo que el catálogo de funciones y su revisión leen y escriben en la base. Deploy: edge (#274).

Vivía en los handlers de `routers/redaccion/funciones_router.py`. Allí se quedan los DTO, quién
puede pedir qué (`acciones_permitidas`) y los códigos de estado; aquí, las consultas y el `commit`.
"""
from __future__ import annotations

import uuid
from typing import Callable, TypeVar

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import String, bindparam, select, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.core.auth.models import UserInfo
from server.app.core.auth.tenancy import organizacion_unica_de
from server.app.modules.redaccion.contracts.blocks import FuncionRef
from server.app.modules.redaccion.database.models import (
    HubFuncion,
    HubFuncionVersion,
)
from server.app.modules.redaccion.funciones_service import consulta_de_catalogo

_Vista = TypeVar("_Vista")


async def funcion_visible(
    session: AsyncSession, funcion_id: uuid.UUID, principal: UserInfo
) -> HubFuncion:
    """La función, si quien pregunta puede verla. **Una no publicada de otra organización es un
    404 y no un 403**: decir «existe y no puedes» ya cuenta que existe."""
    funcion = await session.get(HubFuncion, funcion_id)
    if funcion is None:
        raise HTTPException(status_code=404, detail="Función no encontrada")

    if principal.is_superadmin:
        return funcion
    visible = funcion.publicada_en is not None or funcion.organizacion_id is None
    if not visible:
        suyas = {str(o) for o in (principal.organizacion_ids or ())}
        if str(funcion.organizacion_id) not in suyas:
            raise HTTPException(status_code=404, detail="Función no encontrada")
    return funcion


async def destino_de_una_version_externa(
    session: AsyncSession, funcion_id: uuid.UUID, organizacion_id: uuid.UUID | None, principal: UserInfo
) -> HubFuncion:
    """La función externa a la que se añade una versión, autorizada **antes** de tocarla.

    `registrar_version` sólo hace un `session.get`, así que sin esto un `funcion_id` de otra
    organización colaba una versión en su catálogo — y, peor, permitía añadir código auditado
    **de forma informativa** a una función de autoservicio, que sí se ejecuta en el sandbox. Las
    dos cosas las encontró la revisión de la PR #189.
    """
    no_encontrada = HTTPException(
        status_code=404,
        detail={
            "code": "FUNCION_NO_ENCONTRADA",
            "message": f"no hay ninguna función {funcion_id} en el catálogo",
        },
    )
    destino = await session.get(HubFuncion, funcion_id)
    if destino is None:
        raise no_encontrada
    if not principal.is_superadmin and destino.organizacion_id != organizacion_id:
        # 404 y no 403: decir «existe pero no es tuya» ya es decir que existe.
        raise no_encontrada
    if destino.origen != "externa":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "ORIGEN_DISTINTO",
                "message": (
                    f"«{destino.nombre}» es de origen «{destino.origen}» y esto registra "
                    "funciones externas. Añadirle una versión con auditoría informativa "
                    "metería código sin filtro en algo que la plataforma sí ejecuta."
                ),
            },
        )
    return destino


async def versiones_por_funcion(
    session: AsyncSession, funcion_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[HubFuncionVersion]]:
    """Las versiones de todas estas funciones **en una consulta**, agrupadas (#315).

    El catálogo las pedía función a función: F + 1 consultas en una pantalla que se abre a menudo.
    Cada lista conserva el orden de `versiones_de`. Con la lista vacía no se consulta.
    """
    agrupadas: dict[uuid.UUID, list[HubFuncionVersion]] = {i: [] for i in funcion_ids}
    if not funcion_ids:
        return agrupadas
    filas = (
        await session.execute(
            select(HubFuncionVersion)
            .where(HubFuncionVersion.funcion_id.in_(funcion_ids))
            # DET.1 — orden estable con desempate: dos versiones pueden compartir `created_at`.
            .order_by(HubFuncionVersion.version.desc(), HubFuncionVersion.id)
        )
    ).scalars().all()
    for fila in filas:
        agrupadas[fila.funcion_id].append(fila)
    return agrupadas


async def versiones_de(session: AsyncSession, funcion_id: uuid.UUID) -> list[HubFuncionVersion]:
    return (await versiones_por_funcion(session, [funcion_id]))[funcion_id]


async def version_de(
    session: AsyncSession, funcion_id: uuid.UUID, numero: int
) -> HubFuncionVersion:
    fila = (
        await session.execute(
            select(HubFuncionVersion)
            .where(HubFuncionVersion.funcion_id == funcion_id)
            .where(HubFuncionVersion.version == numero)
        )
    ).scalar_one_or_none()
    if fila is None:
        raise HTTPException(status_code=404, detail=f"La versión {numero} no existe")
    return fila


async def confirmar_registro(session: AsyncSession, funcion: HubFuncion) -> HubFuncion:
    """Confirma el registro y devuelve la función releída.

    El identificador se lee **antes** del commit: con `expire_on_commit` los atributos expiran y
    leerlos después dispara una recarga perezosa que revienta con `MissingGreenlet`. Es el patrón
    que tumbó ocho endpoints de `scripts_router` el 2026-08-14.
    """
    funcion_id = funcion.id
    await session.commit()
    releida = await session.get(HubFuncion, funcion_id)
    assert releida is not None, "se acaba de crear en esta misma sesión"
    return releida


async def catalogo(session: AsyncSession, principal: UserInfo) -> list[HubFuncion]:
    """Las suyas y las publicadas; todas para el superadministrador.

    Nunca las no publicadas de otra organización — eso lo decide `consulta_de_catalogo`, que es
    la misma frontera que usa el resolutor, escrita una sola vez.
    """
    if principal.is_superadmin:
        consulta = select(HubFuncion).order_by(HubFuncion.created_at, HubFuncion.id)
    else:
        consulta = consulta_de_catalogo(organizacion_id=organizacion_unica_de(principal))
    return list((await session.execute(consulta)).scalars().all())


async def en_revision(
    session: AsyncSession, principal: UserInfo
) -> tuple[dict[uuid.UUID, HubFuncion], list[HubFuncionVersion]]:
    """Las funciones de quien revisa y sus versiones vivas, más recientes primero."""
    if principal.is_superadmin:
        consulta = select(HubFuncion).order_by(HubFuncion.created_at, HubFuncion.id)
    else:
        consulta = select(HubFuncion).where(
            HubFuncion.organizacion_id == organizacion_unica_de(principal)
        )
    por_funcion = {f.id: f for f in (await session.execute(consulta)).scalars().all()}
    if not por_funcion:
        return {}, []

    versiones = (
        await session.execute(
            select(HubFuncionVersion)
            .where(HubFuncionVersion.funcion_id.in_(list(por_funcion)))
            .where(HubFuncionVersion.estado.in_(("registrada", "suspendida")))
            .order_by(HubFuncionVersion.created_at.desc(), HubFuncionVersion.id)
        )
    ).scalars().all()
    return por_funcion, list(versiones)


#: Las anclas de todas las versiones de plantilla, expandidas en la base (#317): un bloque por fila,
#: venga `blocks` como lista o como objeto por id, y sólo los `funcion_ref` de las funciones pedidas.
#: Devuelve (versión de plantilla, función, versión anclada) sin repetir, y nunca el spec.
#: El id se compara en hexadecimal sin adornos porque `spec_json` se guarda tal como llega y
#: `FuncionRef` acepta también el id sin guiones, entre llaves o con `urn:uuid:` (revisión de la
#: PR #320); qué forma vale de verdad lo sigue decidiendo `_ancla`.
_ANCLAS = text(
    """
    SELECT DISTINCT tv.id AS plantilla, ref ->> 'funcion_id' AS funcion_id, ref -> 'version' AS version
    FROM hub_report_template_versions AS tv
    CROSS JOIN LATERAL (
        SELECT bloque FROM jsonb_array_elements(
            CASE WHEN jsonb_typeof(tv.spec_json -> 'blocks') = 'array'
                 THEN tv.spec_json -> 'blocks' ELSE '[]'::jsonb END
        ) AS lista(bloque)
        UNION ALL
        SELECT bloque FROM jsonb_each(
            CASE WHEN jsonb_typeof(tv.spec_json -> 'blocks') = 'object'
                 THEN tv.spec_json -> 'blocks' ELSE '{}'::jsonb END
        ) AS objeto(clave, bloque)
    ) AS bloques
    CROSS JOIN LATERAL (SELECT bloques.bloque -> 'funcion_ref' AS ref) AS anclas
    WHERE jsonb_typeof(anclas.ref) = 'object'
      AND regexp_replace(lower(anclas.ref ->> 'funcion_id'), '^urn:uuid:|[{}-]', '', 'g') = ANY(:ids)
    """
).bindparams(bindparam("ids", type_=ARRAY(String))).columns(version=JSONB)


def _ancla(funcion_id, version) -> tuple[uuid.UUID, int] | None:
    """El par, leído con `FuncionRef`, el contrato que valida el bloque, y no a mano: cuenta lo
    mismo que el bloque acepta (`1.0` es la versión 1, una versión 0 no es un ancla), y una versión
    que no es un número se salta en vez de tumbar la cola de revisión (revisión de la PR #316)."""
    try:
        ancla = FuncionRef.model_validate({"funcion_id": funcion_id, "version": version})
    except ValidationError:
        return None
    return ancla.funcion_id, ancla.version


async def plantillas_que_las_usan(
    session: AsyncSession, funcion_ids: list[uuid.UUID]
) -> dict[tuple[uuid.UUID, int], int]:
    """Cuántas versiones de plantilla anclan cada (función, versión), en una consulta.

    Se cuenta leyendo el spec y no con una tabla de referencias: una tabla sería un segundo sitio
    donde vive el mismo hecho, y se desincronizaría con el spec en la primera edición manual.

    #317 — la base expande los bloques y devuelve sólo las anclas de las funciones pedidas. Antes
    traía a Python el JSONB entero de cada versión que mencionara alguna, superadas incluidas, y lo
    recorría aquí: lo que se movía crecía con el historial de plantillas. El contrato de cada ancla
    se sigue comprobando en Python, con `FuncionRef`, porque es donde vive. Una versión de plantilla
    cuenta **una vez** por par aunque lo ancle en dos bloques.
    """
    if not funcion_ids:
        return {}
    buscadas = set(funcion_ids)
    filas = (
        await session.execute(_ANCLAS, {"ids": sorted(i.hex for i in buscadas)})
    ).all()

    vistas: set[tuple[object, tuple[uuid.UUID, int]]] = set()
    for plantilla, funcion_id, version in filas:
        ancla = _ancla(funcion_id, version)
        if ancla is not None and ancla[0] in buscadas:
            vistas.add((plantilla, ancla))

    cuantas: dict[tuple[uuid.UUID, int], int] = {}
    for _, ancla in vistas:
        cuantas[ancla] = cuantas.get(ancla, 0) + 1
    return cuantas


async def guardar(session: AsyncSession, vista: Callable[[], _Vista]) -> _Vista:
    """Confirma un cambio de estado y devuelve su vista, **construida antes del `commit`**.

    Hasta #272 la sesión expiraba al confirmar, y leer `version.version` después disparaba una
    recarga perezosa síncrona sobre una sesión asíncrona (`MissingGreenlet`): la escritura se
    guardaba y la respuesta era un 500. Desde #272 no expira, pero construir la vista antes sigue
    siendo lo correcto: no depende de cómo esté configurada la sesión. Lo destapó la pantalla de
    revisión posterior, que suspendía con su motivo y devolvía 500.
    """
    construida = vista()
    await session.commit()
    return construida
