"""Las personas de la plataforma: lo que la pantalla de Personas lee y escribe. Deploy: cloud (#274).

Vivía en los handlers de `hub_users_router`. Ahí se queda el contrato, quién puede hacer qué con
quién y los códigos de estado; las consultas y las escrituras están aquí.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlmodel import col

from server.app.core.auth.models import UserInfo, UserRole
from server.app.core.auth.modulos_service import TIPO_USUARIO
from server.app.core.auth.tenancy import assert_org_access, scope_query_to_orgs
from server.app.core.identidad import user_to_uuid
from server.app.core.security import hash_password
from server.app.modules.agents_hub.database.config_models import (
    HubModuleGrant,
    HubPlatformModule,
    HubUser,
)


async def persona_o_404(session, user_id: uuid.UUID) -> HubUser:
    fila = await session.get(HubUser, user_id)
    if fila is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Persona no encontrada")
    return fila


async def listar(session, principal, organizacion_id: uuid.UUID | None) -> list[HubUser]:
    """Acotado por tenencia y, si se pide, a una organización.

    La acotación la hace `scope_query_to_orgs` y no un `if` aquí, para que la regla siga viviendo
    en un solo sitio. MT.9 — el filtro va **después** de la tenencia y nunca en su lugar: pedir
    una organización que no se gestiona es 403 y no una lista vacía.
    """
    consulta = scope_query_to_orgs(select(HubUser), principal, HubUser).order_by(HubUser.email)
    if organizacion_id is not None:
        assert_org_access(principal, organizacion_id)
        consulta = consulta.where(HubUser.organizacion_id == organizacion_id)
    return list((await session.execute(consulta)).scalars().all())


async def cuantas_sin_organizacion(session) -> int:
    return int(
        await session.scalar(
            select(func.count()).select_from(HubUser).where(HubUser.organizacion_id.is_(None))
        )
        or 0
    )


async def cuentas_de_arranque(session) -> list[Any]:
    """Las filas de `superadminaccount`, por correo (REV.8)."""
    from server.app.database.models import SuperAdminAccount

    return list(
        (await session.execute(select(SuperAdminAccount).order_by(SuperAdminAccount.email)))
        .scalars()
        .all()
    )


async def concesiones_por_sujeto(session, ids: list[uuid.UUID]) -> dict[str, list[str]]:
    """Qué módulos tiene cada persona, **en una sola consulta**.

    Una por persona sería N+1 sobre una pantalla que se abre en cada sesión. Y la clave es la
    que guarda la tabla: `user_to_uuid` del `id` de la fila, no el `id` a secas — el endpoint que
    concede ya lo convierte antes de escribir, y leerlo de otra forma no encontraría nada.

    Con la lista vacía **no se consulta**: `IN ()` es un error en algunos motores, y además no
    hay nada que preguntar.
    """
    if not ids:
        return {}

    claves = {str(user_to_uuid(str(i))): str(i) for i in ids}
    filas = (
        await session.execute(
            select(HubModuleGrant.subject_id, HubModuleGrant.module_code).where(
                HubModuleGrant.subject_type == TIPO_USUARIO,
                HubModuleGrant.subject_id.in_(list(claves)),
            )
        )
    ).all()

    por_persona: dict[str, list[str]] = {}
    for clave, codigo in filas:
        persona = claves.get(str(clave))
        if persona is not None:
            por_persona.setdefault(persona, []).append(codigo)
    return {persona: sorted(codigos) for persona, codigos in por_persona.items()}


async def otro_superadmin_activo(session, excluido: uuid.UUID) -> bool:
    """Si queda algún superadministrador activo **aparte** del que se va a tocar.

    Cuenta las dos tablas: si sólo mirara `hub_users`, la cuenta de arranque no valdría y la
    regla bloquearía una desactivación perfectamente segura.
    """
    from server.app.database.models import SuperAdminAccount

    otros = (
        await session.execute(
            select(HubUser).where(
                HubUser.role == UserRole.SUPERADMIN.value,
                HubUser.is_active.is_(True),
                HubUser.id != excluido,
            )
        )
    ).scalars().first()
    if otros is not None:
        return True

    de_arranque = (
        await session.execute(
            select(SuperAdminAccount).where(col(SuperAdminAccount.is_active).is_(True))
        )
    ).scalars().first()
    return de_arranque is not None


async def por_correo(session, email: str) -> HubUser | None:
    return (await session.execute(select(HubUser).where(HubUser.email == email))).scalars().first()


async def comprobar_modulos(session, codigos: list[str]) -> None:
    """Que todos estén en el catálogo y vigentes, o 400 diciendo cuáles no.

    Son las dos reglas de `conceder`, consultadas al catálogo y no copiadas como lista: conceder
    un módulo retirado no daría acceso a nada, así que aceptarlo en silencio crearía una persona
    que cree tener acceso y no lo tiene.
    """
    if not codigos:
        return

    vigentes = {
        codigo
        for (codigo,) in (
            await session.execute(
                select(HubPlatformModule.code).where(
                    HubPlatformModule.code.in_(codigos),
                    HubPlatformModule.vigente.is_(True),
                )
            )
        ).all()
    }
    invalidos = [c for c in codigos if c not in vigentes]
    if invalidos:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Estos módulos no están en el catálogo o están retirados: "
                f"{', '.join(invalidos)}"
            ),
        )


def _preparar_concesiones(session, fila: HubUser, codigos: list[str], *, quien: UserInfo) -> list[str]:
    """Añade las concesiones a la sesión **sin confirmar**: las confirma `dar_de_alta`.

    Que no haya `commit` aquí es lo que hace el alta atómica (issue #109). Mientras esta función
    cerraba su propia transacción, la fila de la persona ya estaba confirmada por la suya y un
    fallo en ésta dejaba a alguien creado sin sus módulos.

    **La clave que se guarda es `user_to_uuid` del id**, igual que en `conceder`: es la que
    consulta `modulos_del_usuario`, y escribir el id a secas dejaría una fila que la resolución
    no encuentra.
    """
    if not codigos:
        return []

    sujeto = str(user_to_uuid(str(fila.id)))
    ahora = datetime.now(timezone.utc)
    for codigo in codigos:
        session.add(
            HubModuleGrant(
                subject_type=TIPO_USUARIO,
                subject_id=sujeto,
                module_code=codigo,
                granted_by=quien.user_id,
                granted_at=ahora,
            )
        )
    return sorted(codigos)


async def dar_de_alta(session, fila: HubUser, modulos: list[str], *, quien: UserInfo) -> list[str]:
    """Guarda a la persona y sus concesiones en **un solo `commit`** (issue #109). Los concedidos.

    Antes la persona se confirmaba por su cuenta y las concesiones después: si el segundo fallaba
    quedaba alguien dado de alta **sin los módulos que se pidieron**, y sin que nadie lo supiera
    porque la respuesta ya se había ido. El `flush` da el id a la fila sin cerrar la transacción,
    que es lo que las concesiones necesitan para su `subject_id`.
    """
    session.add(fila)
    await session.flush()
    concedidos = _preparar_concesiones(session, fila, modulos, quien=quien)
    await session.commit()
    await session.refresh(fila)
    return concedidos


async def reconciliar_modulos(
    session, fila: HubUser, modulos: list[str], *, quien: UserInfo
) -> list[str]:
    """Deja a la persona **exactamente** con estos módulos, sin confirmar. Los que le quedan.

    - **Sólo se reconcilia lo que se puede conceder**: vigente y no de oficio. Una concesión a un
      módulo retirado no se ofrece, así que no se puede desmarcar; borrarla por no venir en la
      lista sería retirar algo que nadie ha pedido retirar.
    - **Lo que sigue marcado conserva su fila**, y con ella cuándo y quién lo concedió.
    - **Un código que no se puede conceder no cambia nada**: se comprueba todo antes de tocar.

    Confirma `confirmar_modulos`, aparte: quien llama construye la respuesta antes del `commit`.
    """
    concedibles = {
        codigo
        for (codigo,) in (
            await session.execute(
                select(HubPlatformModule.code).where(
                    HubPlatformModule.vigente.is_(True),
                    HubPlatformModule.de_oficio.is_(False),
                )
            )
        ).all()
    }
    invalidos = [c for c in modulos if c not in concedibles]
    if invalidos:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Estos módulos no se pueden conceder —no están en el catálogo, están retirados o "
                f"son de oficio—: {', '.join(invalidos)}"
            ),
        )

    sujeto = str(user_to_uuid(str(fila.id)))
    actuales = (
        await session.execute(
            select(HubModuleGrant).where(
                HubModuleGrant.subject_type == TIPO_USUARIO,
                HubModuleGrant.subject_id == sujeto,
            )
        )
    ).scalars().all()
    pedidos = set(modulos)
    tenidos = {g.module_code for g in actuales}

    for concesion in actuales:
        if concesion.module_code in concedibles and concesion.module_code not in pedidos:
            await session.delete(concesion)
    ahora = datetime.now(timezone.utc)
    for codigo in modulos:
        if codigo not in tenidos:
            session.add(
                HubModuleGrant(
                    subject_type=TIPO_USUARIO,
                    subject_id=sujeto,
                    module_code=codigo,
                    granted_by=quien.user_id,
                    granted_at=ahora,
                )
            )
    return sorted((tenidos - (concedibles - pedidos)) | pedidos)


async def confirmar_modulos(session) -> None:
    try:
        await session.commit()
    except IntegrityError as exc:
        # Otro guardado —esta pantalla en otra pestaña, o Plataforma → Módulos— concedió lo mismo
        # entre la lectura y el `commit`. Es un conflicto, no un fallo del servidor.
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Los módulos de esta persona acaban de cambiar en otro sitio: vuelve a cargar y repite.",
        ) from exc


async def actualizar(session, fila: HubUser, cambios: dict[str, Any]) -> HubUser:
    for campo, valor in cambios.items():
        setattr(fila, campo, valor)
    await session.commit()
    await session.refresh(fila)
    return fila


async def fijar_contrasena(session, fila: HubUser, contrasena: str, *, quien: UserInfo) -> None:
    """Issue #94 — **la contraseña que pone otra persona vale una sola vez**.

    Quien restablece conoce el secreto; con la marca, ese conocimiento se agota en la primera
    entrada, porque el token que se emita no servirá para nada más que cambiarla. Y queda dicho
    quién y cuándo: sin la traza, un restablecimiento es indistinguible de un cambio propio.
    """
    fila.hashed_password = hash_password(contrasena)
    fila.debe_cambiar_contrasena = True
    fila.password_reset_at = datetime.now(timezone.utc)
    fila.password_reset_by = quien.user_id
    session.add(fila)
    await session.commit()


async def borrar(session, fila: HubUser) -> None:
    """**Sus concesiones se van con ella**, en la misma transacción: una concesión a alguien que
    ya no existe es una fila que ninguna pantalla enseña y que se queda ahí para siempre."""
    concesiones = (
        await session.execute(
            select(HubModuleGrant).where(
                HubModuleGrant.subject_type == "usuario",
                HubModuleGrant.subject_id == str(fila.id),
            )
        )
    ).scalars().all()
    for concesion in concesiones:
        await session.delete(concesion)

    await session.delete(fila)
    await session.commit()
