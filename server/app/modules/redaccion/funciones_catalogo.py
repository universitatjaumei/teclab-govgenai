"""Lo que el catálogo de funciones y su revisión leen y escriben en la base. Deploy: edge (#274).

Vivía en los handlers de `routers/redaccion/funciones_router.py`. Allí se quedan los DTO, quién
puede pedir qué (`acciones_permitidas`) y los códigos de estado; aquí, las consultas y el `commit`.
"""
from __future__ import annotations

import uuid
from typing import Callable, TypeVar

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.core.auth.models import UserInfo
from server.app.core.auth.tenancy import organizacion_unica_de
from server.app.modules.redaccion.database.models import (
    HubFuncion,
    HubFuncionVersion,
    HubReportTemplateVersion,
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


async def versiones_de(session: AsyncSession, funcion_id: uuid.UUID) -> list[HubFuncionVersion]:
    return list(
        (
            await session.execute(
                select(HubFuncionVersion)
                .where(HubFuncionVersion.funcion_id == funcion_id)
                # DET.1 — orden estable con desempate: dos versiones pueden compartir `created_at`.
                .order_by(HubFuncionVersion.version.desc(), HubFuncionVersion.id)
            )
        )
        .scalars()
        .all()
    )


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


async def cuantas_plantillas_la_usan(
    session: AsyncSession, funcion_id: uuid.UUID, version: int
) -> int:
    """Cuántas versiones de plantilla anclan **esta** versión.

    Se cuenta leyendo el spec y no con una tabla de referencias: una tabla sería un segundo sitio
    donde vive el mismo hecho, y se desincronizaría con el spec en la primera edición manual.

    El `LIKE` sólo **preselecciona** las plantillas que mencionan el id; el par (función, versión)
    se comprueba bloque a bloque en Python. Confiar en el `LIKE` para las dos cosas contaría una
    plantilla que cita la función en un bloque y el número de versión en otro.
    """
    filas = (
        await session.execute(
            select(HubReportTemplateVersion.spec_json).where(
                text(
                    "hub_report_template_versions.spec_json::text LIKE :patron"
                ).bindparams(patron=f"%{funcion_id}%")
            )
        )
    ).scalars().all()

    total = 0
    for spec in filas:
        if not isinstance(spec, dict):
            continue
        bloques = spec.get("blocks")
        if isinstance(bloques, dict):
            bloques = list(bloques.values())
        if not isinstance(bloques, list):
            continue
        for bloque in bloques:
            ref = (bloque or {}).get("funcion_ref") if isinstance(bloque, dict) else None
            if not isinstance(ref, dict):
                continue
            if str(ref.get("funcion_id")) == str(funcion_id) and ref.get("version") == version:
                total += 1
                break
    return total


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
