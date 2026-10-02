"""Conceder y retirar módulos, a una persona o a un grupo del IdP (IDE.5).

Deploy: cloud
Módulo: plataforma

INF.7 puso el control de acceso por módulo y `modulos_del_usuario` lo resuelve bien, pero las
concesiones eran filas de `hub_module_grants` que solo se ponían conectándose a Postgres. Una
plataforma que se entrega a otra administración no puede pedir eso: quien la administra no tiene
por qué tener acceso a la base de datos, y no debería tenerlo.

**El catálogo se lee de la tabla**, nunca de una lista en el código: es la regla del catálogo
como dato, la misma que rige el vocabulario del corpus. Si los módulos fueran un `Enum`, añadir
uno exigiría una migración y un despliegue.

**Reservado a superadministrador**: conceder módulos es repartir acceso a toda la plataforma.
Y el superadministrador **no necesita concesión** —entra en todo por su rol—, así que la pantalla
lo dice para que nadie busque su fila.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.api.deps import require_role
from server.app.core.auth.models import UserInfo, UserRole
from server.app.core.auth.modulos_service import (
    TIPO_GRUPO,
    TIPO_USUARIO,
    modulos_con_origen,
)
from server.app.modules.agents_hub.database.config_models import (
    HubModuleGrant,
    HubPlatformModule,
    HubUser,
)
from server.app.modules.agents_hub.database.connection import get_async_session
from server.app.routers.redaccion._actor import user_to_uuid

router = APIRouter(prefix="/hub/modulos", tags=["hub-modulos"])

_require_superadmin = require_role(UserRole.SUPERADMIN.value)

_TIPOS = (TIPO_USUARIO, TIPO_GRUPO)


class ModuloDelCatalogo(BaseModel):
    code: str
    label: str
    vigente: bool
    #: Lo tiene cualquier persona sin concesión: la pantalla no lo ofrece para conceder.
    de_oficio: bool = False


class ConcesionRead(BaseModel):
    id: int
    subject_type: str
    subject_id: str
    module_code: str
    granted_at: datetime
    granted_by: str | None


class ConcesionCreate(BaseModel):
    subject_type: str
    subject_id: str = Field(min_length=1, max_length=255)
    module_code: str

    model_config = {"extra": "forbid"}

    @field_validator("subject_type")
    @classmethod
    def _tipo_conocido(cls, valor: str) -> str:
        if valor not in _TIPOS:
            raise ValueError(f"tipo de sujeto desconocido. Admitidos: {', '.join(_TIPOS)}")
        return valor

    @field_validator("subject_id")
    @classmethod
    def _sujeto_limpio(cls, valor: str) -> str:
        limpio = valor.strip()
        if not limpio:
            raise ValueError("el sujeto no puede estar vacío")
        return limpio


class AlcanceDeGrupo(BaseModel):
    """A cuántas personas **conocidas** afecta retirar la concesión de un grupo.

    «Conocidas» y no «afectadas»: la plataforma solo sabe de los grupos de quien ha entrado
    alguna vez, porque los grupos llegan en la aserción y no se guardan. Puede haber más gente
    en ese grupo que todavía no ha aparecido, y decir «afecta a 3» sin más sería mentir por
    precisión falsa.
    """

    personas_conocidas: int


@router.get("/catalogo", response_model=list[ModuloDelCatalogo])
async def get_catalogo(
    _: UserInfo = Depends(_require_superadmin),
    session: AsyncSession = Depends(get_async_session),
) -> list[ModuloDelCatalogo]:
    """El catálogo de módulos, como dato. La pantalla itera esto; no trae los códigos escritos."""
    filas = (
        await session.execute(select(HubPlatformModule).order_by(HubPlatformModule.code))
    ).scalars().all()
    return [
        ModuloDelCatalogo(code=f.code, label=f.label, vigente=f.vigente, de_oficio=f.de_oficio)
        for f in filas
    ]


@router.get("", response_model=list[ConcesionRead])
async def list_concesiones(
    _: UserInfo = Depends(_require_superadmin),
    session: AsyncSession = Depends(get_async_session),
) -> list[ConcesionRead]:
    filas = (
        await session.execute(
            select(HubModuleGrant).order_by(
                HubModuleGrant.subject_type, HubModuleGrant.subject_id
            )
        )
    ).scalars().all()
    return [
        ConcesionRead(
            id=f.id,
            subject_type=f.subject_type,
            subject_id=f.subject_id,
            module_code=f.module_code,
            granted_at=f.granted_at,
            granted_by=f.granted_by,
        )
        for f in filas
    ]


@router.get("/de-persona/{user_id}")
async def modulos_de_persona(
    user_id: uuid.UUID,
    _: UserInfo = Depends(_require_superadmin),
    session: AsyncSession = Depends(get_async_session),
) -> dict:
    """Los módulos de una persona **y de dónde le vienen**.

    El origen no es adorno: retirar lo que le llega por un grupo afecta a todo el grupo, y quien
    mira la ficha tiene que poder distinguirlo de lo que se le concedió a ella.

    **Los grupos son los de su última entrada**, porque llegan en la aserción y no se guardan.
    Si no ha entrado nunca, aquí solo se ve lo concedido a su persona — y eso es la verdad, no
    una carencia de la pantalla.
    """
    persona = await session.get(HubUser, user_id)
    if persona is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Persona no encontrada")

    ficticio = UserInfo(
        user_id=str(persona.id),
        email=persona.email,
        role=persona.role,
        organizacion_ids=(str(persona.organizacion_id),) if persona.organizacion_id else (),
    )
    return {"modulos": await modulos_con_origen(session, ficticio)}


@router.get("/alcance-de-grupo/{grupo}", response_model=AlcanceDeGrupo)
async def alcance_de_grupo(
    grupo: str,
    _: UserInfo = Depends(_require_superadmin),
    session: AsyncSession = Depends(get_async_session),
) -> AlcanceDeGrupo:
    """Cuánta gente conocida hay en un grupo, para poder confirmar una retirada con un número.

    Un «¿seguro?» a secas no informa de nada cuando lo que se retira alcanza a un colectivo.
    """
    # La plataforma no guarda los grupos de nadie: llegan en cada aserción. Lo que sí puede
    # contar es cuánta gente hay dada de alta, que es el techo de lo que esto puede afectar.
    total = (
        await session.execute(select(func.count()).select_from(HubUser).where(HubUser.is_active))
    ).scalar_one()
    return AlcanceDeGrupo(personas_conocidas=int(total))


@router.post("", response_model=ConcesionRead, status_code=status.HTTP_201_CREATED)
async def conceder(
    body: ConcesionCreate,
    user: UserInfo = Depends(_require_superadmin),
    session: AsyncSession = Depends(get_async_session),
) -> ConcesionRead:
    """Concede un módulo a una persona o a un grupo del IdP.

    Con `subject_type = 'grupo'` el sujeto es el nombre del grupo tal como lo declara el IdP.
    Se guarda como se escribe —la pantalla lo muestra tal cual— y la resolución compara
    plegando la caja, porque los acrónimos institucionales se teclean como salen.
    """
    modulo = await session.get(HubPlatformModule, body.module_code)
    if modulo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"El módulo {body.module_code} no está en el catálogo",
        )
    if not modulo.vigente:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"El módulo {body.module_code} está retirado del catálogo: concederlo no daría "
                "acceso a nada."
            ),
        )
    if modulo.de_oficio:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"El módulo {body.module_code} es de oficio: lo tiene cualquier persona de la "
                "plataforma, así que concederlo no cambiaría nada."
            ),
        )

    sujeto = body.subject_id
    if body.subject_type == TIPO_USUARIO:
        # Se admite el UUID de la fila de `hub_users` y se guarda la clave derivada, que es la
        # que consulta la resolución. Sin esto, conceder desde la pantalla escribiría una fila
        # que `modulos_del_usuario` no encuentra.
        sujeto = str(user_to_uuid(sujeto))

    existente = (
        await session.execute(
            select(HubModuleGrant).where(
                HubModuleGrant.subject_type == body.subject_type,
                HubModuleGrant.subject_id == sujeto,
                HubModuleGrant.module_code == body.module_code,
            )
        )
    ).scalars().first()
    if existente is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Esa concesión ya existe"
        )

    fila = HubModuleGrant(
        subject_type=body.subject_type,
        subject_id=sujeto,
        module_code=body.module_code,
        granted_by=user.user_id,
        granted_at=datetime.now(timezone.utc),
    )
    session.add(fila)
    await session.commit()
    await session.refresh(fila)
    return ConcesionRead(
        id=fila.id,
        subject_type=fila.subject_type,
        subject_id=fila.subject_id,
        module_code=fila.module_code,
        granted_at=fila.granted_at,
        granted_by=fila.granted_by,
    )


@router.delete("/{concesion_id}", status_code=status.HTTP_204_NO_CONTENT)
async def retirar(
    concesion_id: int,
    _: UserInfo = Depends(_require_superadmin),
    session: AsyncSession = Depends(get_async_session),
) -> None:
    """Retira una concesión.

    Se borra la fila en vez de marcarla: el modelo dice que la fila **es** el permiso vivo, y
    `HubPlatformModule.vigente` es lo que guarda el histórico de qué módulos existieron. Meter
    aquí un borrado lógico duplicaría ese papel en dos sitios.
    """
    fila = await session.get(HubModuleGrant, concesion_id)
    if fila is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Concesión no encontrada")
    await session.delete(fila)
    await session.commit()
