"""El catálogo de agentes de unidad (#172).

Deploy: edge
Módulo: agentes

Una unidad de la organización —contratación, control interno, calidad— publica un **agente**: un
prompt, una carpeta de documentos, un índice y un colectivo. Lo ejecuta el asistente general de
la organización; la plataforma lo cataloga, lo acota y, cuando llegue la consulta (#175), registra
su uso.

**Dos superficies, y no por estética:**

* **La gestión** (`router`) exige el módulo `agentes`: publicar, versionar, revisar, suspender,
  reactivar y retirar. Las acciones las decide `acciones_permitidas`, y el endpoint que no la
  tiene responde 403: la lista de botones y la comprobación son la misma función.
* **El catálogo** (`router_catalogo`) no exige módulo: es lo que se le ofrece a quien **usa** los
  agentes, que es todo su colectivo, tenga o no el módulo de publicar. No lleva el prompt: el
  vigente lo entregará la consulta, que es lo que se registra.

En el lado edge, como el catálogo de funciones: el prompt y la declaración son texto escrito por
una persona de la organización.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.api.deps import get_current_user, get_session, require_module
from server.app.core.auth.models import UserInfo
from server.app.core.auth.tenancy import organizacion_unica_de
from server.app.core.config import get_settings
from server.app.core.identidad import user_to_uuid
from server.app.modules.agentes import acciones
from server.app.modules.agents_hub.database.operational_models import (
    HubAgenteUnidad,
    HubAgenteUnidadVersion,
)

router = APIRouter(
    prefix="/agentes",
    tags=["agentes"],
    dependencies=[Depends(require_module("agentes"))],
)
router_catalogo = APIRouter(prefix="/agentes", tags=["agentes"])


# =============================================================================
#  Contratos
# =============================================================================


class DeclaracionDelAgente(BaseModel):
    """Lo que se declara al publicar y en cada versión. **Sin esto no se publica.**"""

    prompt: str = Field(min_length=1)
    carpeta_url: str = Field(min_length=1, max_length=2048)
    finalidad: str = Field(min_length=1)
    responsable: str = Field(min_length=1, max_length=255)
    colectivo: Literal["organizacion", "grupos"]
    grupos: list[str] = Field(default_factory=list)
    revision_prevista_en: date

    model_config = {"extra": "forbid"}

    @field_validator("prompt", "finalidad", "responsable")
    @classmethod
    def _con_texto(cls, valor: str) -> str:
        limpio = valor.strip()
        if not limpio:
            raise ValueError("no puede estar vacío")
        return limpio

    @field_validator("carpeta_url")
    @classmethod
    def _https(cls, valor: str) -> str:
        # La carpeta la abre el asistente general por su cuenta: una ruta local o un `http`
        # no los puede abrir nadie más que quien lo escribió, o los abre sin cifrar.
        limpio = valor.strip()
        if not limpio.startswith("https://"):
            raise ValueError("la carpeta tiene que ser una URL https del almacén de la organización")
        return limpio

    @field_validator("revision_prevista_en")
    @classmethod
    def _no_pasada(cls, valor: date) -> date:
        if valor < date.today():
            raise ValueError("la fecha de revisión prevista no puede haber pasado ya")
        return valor

    @model_validator(mode="after")
    def _grupos_si_es_por_grupos(self) -> "DeclaracionDelAgente":
        self.grupos = [g.strip() for g in self.grupos if g.strip()]
        if self.colectivo == "grupos" and not self.grupos:
            raise ValueError("un agente por grupos necesita al menos un grupo")
        if self.colectivo == "organizacion":
            # Guardarlos sería decir algo que no se aplica.
            self.grupos = []
        return self


class AgenteCreate(DeclaracionDelAgente):
    nombre: str = Field(min_length=1, max_length=200)
    unidad: str = Field(min_length=1, max_length=200)

    @field_validator("nombre", "unidad")
    @classmethod
    def _nombre_con_texto(cls, valor: str) -> str:
        limpio = valor.strip()
        if not limpio:
            raise ValueError("no puede estar vacío")
        return limpio


class MotivoDeSuspension(BaseModel):
    motivo: str = Field(min_length=1)


class RevisionDelAgente(BaseModel):
    resultado: Literal["conforme", "correcciones"]
    nota: str | None = None


class VersionDelAgente(BaseModel):
    version: int
    estado: str
    prompt: str
    carpeta_url: str
    finalidad: str
    responsable: str
    colectivo: str
    grupos: list[str]
    revision_prevista_en: date
    revision_vencida: bool
    declarada_en: datetime
    revisada_en: datetime | None
    revision_resultado: str | None
    revision_nota: str | None
    motivo_suspension: str | None
    acciones_permitidas: list[str]


class AgenteView(BaseModel):
    id: uuid.UUID
    nombre: str
    unidad: str
    es_mio: bool
    version: VersionDelAgente


class GestionDeAgentes(BaseModel):
    agentes: list[AgenteView]
    #: Si llegan grupos del IdP. **Sólo por SAML**: con el login de Google no llega ninguno, y un
    #: agente por grupos no se le ofrecería a nadie. La pantalla lo dice con esto.
    grupos_del_idp: bool


class AgenteDelCatalogo(BaseModel):
    """Lo que ve quien usa los agentes. **Sin el prompt**: lo entrega la consulta (#175)."""

    id: uuid.UUID
    nombre: str
    unidad: str
    finalidad: str
    responsable: str
    version: int
    revision_vencida: bool


# =============================================================================
#  Lo común
# =============================================================================


def _vista(agente: HubAgenteUnidad, version: HubAgenteUnidadVersion, user: UserInfo) -> AgenteView:
    return AgenteView(
        id=agente.id,
        nombre=agente.nombre,
        unidad=agente.unidad,
        es_mio=agente.creado_por == user_to_uuid(user.user_id),
        version=VersionDelAgente(
            version=version.version,
            estado=version.estado,
            prompt=version.prompt,
            carpeta_url=version.carpeta_url,
            finalidad=version.finalidad,
            responsable=version.responsable,
            colectivo=version.colectivo,
            grupos=list(version.grupos or []),
            revision_prevista_en=version.revision_prevista_en,
            revision_vencida=acciones.revision_vencida(version),
            declarada_en=version.declarada_en,
            revisada_en=version.revisada_en,
            revision_resultado=version.revision_resultado,
            revision_nota=version.revision_nota,
            motivo_suspension=version.motivo_suspension,
            acciones_permitidas=acciones.acciones_permitidas(agente, version, principal=user),
        ),
    )


def _nueva_version(
    agente_id: uuid.UUID, numero: int, declaracion: DeclaracionDelAgente, user: UserInfo
) -> HubAgenteUnidadVersion:
    return HubAgenteUnidadVersion(
        agente_id=agente_id,
        version=numero,
        # Registrar es publicar: no hay aprobación previa.
        estado="registrada",
        prompt=declaracion.prompt,
        carpeta_url=declaracion.carpeta_url,
        finalidad=declaracion.finalidad,
        responsable=declaracion.responsable,
        colectivo=declaracion.colectivo,
        grupos=declaracion.grupos,
        revision_prevista_en=declaracion.revision_prevista_en,
        declarada_por=user_to_uuid(user.user_id),
        declarada_en=datetime.now(timezone.utc),
    )


async def _vigentes(session: AsyncSession, filtro) -> list[tuple[HubAgenteUnidad, HubAgenteUnidadVersion]]:
    """Cada agente con su última versión, que es la que se ofrece."""
    ultima = (
        select(
            HubAgenteUnidadVersion.agente_id,
            func.max(HubAgenteUnidadVersion.version).label("version"),
        )
        .group_by(HubAgenteUnidadVersion.agente_id)
        .subquery()
    )
    consulta = (
        select(HubAgenteUnidad, HubAgenteUnidadVersion)
        .join(ultima, ultima.c.agente_id == HubAgenteUnidad.id)
        .join(
            HubAgenteUnidadVersion,
            (HubAgenteUnidadVersion.agente_id == ultima.c.agente_id)
            & (HubAgenteUnidadVersion.version == ultima.c.version),
        )
        .order_by(HubAgenteUnidad.nombre, HubAgenteUnidad.id)
    )
    if filtro is not None:
        consulta = consulta.where(filtro)
    return [(a, v) for a, v in (await session.execute(consulta)).all()]


def _de_sus_organizaciones(user: UserInfo):
    """El acotado del listado, **en el `WHERE`**. La lista vacía significa «ninguna» (I8)."""
    if user.is_superadmin:
        return None
    ids = [uuid.UUID(str(o)) for o in user.organizacion_ids]
    return HubAgenteUnidad.organizacion_id.in_(ids)


async def _el_agente(
    session: AsyncSession, agente_id: uuid.UUID, user: UserInfo
) -> tuple[HubAgenteUnidad, HubAgenteUnidadVersion]:
    filtro = HubAgenteUnidad.id == agente_id
    acotado = _de_sus_organizaciones(user)
    if acotado is not None:
        filtro = filtro & acotado
    encontrados = await _vigentes(session, filtro)
    if not encontrados:
        # 404 y no 403: lo de otra organización no existe para quien pregunta.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agente no encontrado")
    return encontrados[0]


def _exigir(accion: str, agente, version, user: UserInfo) -> None:
    if accion not in acciones.acciones_permitidas(agente, version, principal=user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"No puedes {accion} este agente.",
        )


async def _responder(session: AsyncSession, agente, version, user: UserInfo) -> AgenteView:
    # La vista se construye antes del commit: la sesión de los routers expira los atributos al
    # commitear, y leerlos después costaría un 500.
    await session.flush()
    vista = _vista(agente, version, user)
    await session.commit()
    return vista


# =============================================================================
#  La gestión
# =============================================================================


@router.post("", response_model=AgenteView, status_code=status.HTTP_201_CREATED)
async def publicar(
    body: AgenteCreate,
    user: UserInfo = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AgenteView:
    """Publica un agente. **Registrar es publicar**: se ofrece a su colectivo desde ya."""
    organizacion = organizacion_unica_de(user)
    if organizacion is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "ORGANIZACION_INDETERMINADA",
                "message": (
                    "Un agente es de una organización, y tu cuenta no pertenece a una sola. "
                    "Entra con una cuenta de una organización."
                ),
            },
        )
    agente = HubAgenteUnidad(
        id=uuid.uuid4(),
        organizacion_id=uuid.UUID(str(organizacion)),
        nombre=body.nombre,
        unidad=body.unidad,
        creado_por=user_to_uuid(user.user_id),
    )
    session.add(agente)
    await session.flush()
    version = _nueva_version(agente.id, 1, body, user)
    session.add(version)
    return await _responder(session, agente, version, user)


@router.get("", response_model=GestionDeAgentes)
async def listar(
    user: UserInfo = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> GestionDeAgentes:
    """Los agentes de su organización, con lo que quien pregunta puede hacer con cada uno."""
    filas = await _vigentes(session, _de_sus_organizaciones(user))
    return GestionDeAgentes(
        agentes=[_vista(a, v, user) for a, v in filas],
        grupos_del_idp=get_settings().saml_enabled,
    )


@router.post("/{agente_id}/versiones", response_model=AgenteView, status_code=status.HTTP_201_CREATED)
async def versionar(
    agente_id: uuid.UUID,
    body: DeclaracionDelAgente,
    user: UserInfo = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AgenteView:
    """Corregir es versionar: lo revisado sigue siendo lo que se revisó."""
    agente, vigente = await _el_agente(session, agente_id, user)
    _exigir("versionar", agente, vigente, user)
    version = _nueva_version(agente.id, vigente.version + 1, body, user)
    session.add(version)
    agente.updated_at = datetime.now(timezone.utc)
    return await _responder(session, agente, version, user)


@router.post("/{agente_id}/revisar", response_model=AgenteView)
async def revisar(
    agente_id: uuid.UUID,
    body: RevisionDelAgente,
    user: UserInfo = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AgenteView:
    agente, version = await _el_agente(session, agente_id, user)
    _exigir("revisar", agente, version, user)
    acciones.aplicar_revision(
        version, resultado=body.resultado, nota=body.nota, revisada_por=user_to_uuid(user.user_id)
    )
    return await _responder(session, agente, version, user)


@router.post("/{agente_id}/suspender", response_model=AgenteView)
async def suspender(
    agente_id: uuid.UUID,
    body: MotivoDeSuspension,
    user: UserInfo = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AgenteView:
    """Deja de ofrecerlo, con motivo. Es de quien revisa, nunca de quien lo publicó."""
    agente, version = await _el_agente(session, agente_id, user)
    _exigir("suspender", agente, version, user)
    try:
        acciones.suspender(
            version, motivo=body.motivo, suspendida_por=user_to_uuid(user.user_id)
        )
    except acciones.AgenteIncoherente as fallo:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(fallo)
        ) from fallo
    return await _responder(session, agente, version, user)


@router.post("/{agente_id}/reactivar", response_model=AgenteView)
async def reactivar(
    agente_id: uuid.UUID,
    user: UserInfo = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AgenteView:
    agente, version = await _el_agente(session, agente_id, user)
    _exigir("reactivar", agente, version, user)
    acciones.reactivar(version)
    return await _responder(session, agente, version, user)


@router.post("/{agente_id}/retirar", response_model=AgenteView)
async def retirar(
    agente_id: uuid.UUID,
    user: UserInfo = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AgenteView:
    """Retirar es de quien lo publicó (y del admin de su organización). Es terminal."""
    agente, version = await _el_agente(session, agente_id, user)
    _exigir("retirar", agente, version, user)
    acciones.retirar(version)
    return await _responder(session, agente, version, user)


# =============================================================================
#  El catálogo de quien usa
# =============================================================================


@router_catalogo.get("/catalogo", response_model=list[AgenteDelCatalogo])
async def catalogo(
    user: UserInfo = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[AgenteDelCatalogo]:
    """Los agentes que se le ofrecen a quien pregunta: los de su organización y su colectivo.

    La organización va en el `WHERE`; el colectivo se mira por agente, porque los grupos del IdP
    llegan en el token y no están en la base.
    """
    filas = await _vigentes(session, _de_sus_organizaciones(user))
    return [
        AgenteDelCatalogo(
            id=a.id,
            nombre=a.nombre,
            unidad=a.unidad,
            finalidad=v.finalidad,
            responsable=v.responsable,
            version=v.version,
            revision_vencida=acciones.revision_vencida(v),
        )
        for a, v in filas
        if acciones.lo_puede_usar(a, v, principal=user)
    ]
