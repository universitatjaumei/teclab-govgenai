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

import hashlib
import uuid
from datetime import date, datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.api.deps import get_current_user, get_session, require_module, require_scopes
from server.app.core.auth.models import UserInfo
from server.app.core.auth.tenancy import organizacion_unica_de
from server.app.core.config import get_settings
from server.app.core.auth.pat.scopes import AGENTES_CONSULTA, AGENTES_INDICE_WRITE
from server.app.core.identidad import user_to_uuid
from server.app.core.uploads import read_within_limit, sanitizar_nombre
from server.app.modules.agentes import acciones, consulta, indice
from server.app.modules.agents_hub.contracts.actividad import ActividadIAEvent
from server.app.modules.agents_hub.database.operational_models import (
    HubActividadIA,
    HubAgenteConsulta,
    HubAgenteFicha,
    HubAgenteUnidad,
    HubAgenteUnidadVersion,
)
from server.app.modules.agents_hub.services.embedding_resolver import resolve_embedding_service
from server.app.modules.utilidades.anonimizar import FicheroNoValido, leer_tabla

router = APIRouter(
    prefix="/agentes",
    tags=["agentes"],
    dependencies=[Depends(require_module("agentes"))],
)
#: El de quien **usa** los agentes: el catálogo y la consulta. Exige `consulta_agentes`, que es de
#: oficio —lo tiene cualquiera— y por eso retirarlo del catálogo apaga la consulta para todos.
router_catalogo = APIRouter(
    prefix="/agentes",
    tags=["agentes"],
    dependencies=[Depends(require_module("consulta_agentes"))],
)


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
    #: #173 — cuántos documentos devuelve una consulta como mucho. Lo declara el agente.
    presupuesto_documentos: int = Field(default=5, ge=1, le=10)

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
    presupuesto_documentos: int
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
    #: Cuántas fichas tiene su índice (#173).
    fichas: int
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


def _vista(
    agente: HubAgenteUnidad, version: HubAgenteUnidadVersion, user: UserInfo, fichas: int = 0
) -> AgenteView:
    return AgenteView(
        id=agente.id,
        nombre=agente.nombre,
        unidad=agente.unidad,
        es_mio=agente.creado_por == user_to_uuid(user.user_id),
        fichas=fichas,
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
            presupuesto_documentos=version.presupuesto_documentos,
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
        presupuesto_documentos=declaracion.presupuesto_documentos,
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


async def _fichas_por_agente(session: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not ids:
        return {}
    filas = await session.execute(
        select(HubAgenteFicha.agente_id, func.count())
        .where(HubAgenteFicha.agente_id.in_(ids))
        .group_by(HubAgenteFicha.agente_id)
    )
    return {agente_id: n for agente_id, n in filas.all()}


async def _responder(session: AsyncSession, agente, version, user: UserInfo) -> AgenteView:
    # La vista se construye antes del commit: la sesión de los routers expira los atributos al
    # commitear, y leerlos después costaría un 500.
    await session.flush()
    fichas = (await _fichas_por_agente(session, [agente.id])).get(agente.id, 0)
    vista = _vista(agente, version, user, fichas)
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
    fichas = await _fichas_por_agente(session, [a.id for a, _ in filas])
    return GestionDeAgentes(
        agentes=[_vista(a, v, user, fichas.get(a.id, 0)) for a, v in filas],
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
#  El índice (#173)
# =============================================================================

#: Cuánto puede pesar la hoja. Dos mil fichas con su resumen caben de sobra.
MAXIMO_BYTES_DE_LA_HOJA = 10 * 1024 * 1024


async def obtener_embedder(session: AsyncSession = Depends(get_session)):
    """El servicio de embeddings de la plataforma, el mismo con el que se seleccionará."""
    return await resolve_embedding_service(session)


class FichaDelIndice(BaseModel):
    url: str
    titulo: str
    resumen: str
    vigente: bool = True
    revision_prevista_en: date | None = None
    metadatos: dict[str, str] = Field(default_factory=dict)
    version_prompt_resumen: str | None = None
    modelo_resumen: str | None = None

    model_config = {"extra": "forbid"}


class IndiceCompleto(BaseModel):
    """**El estado completo** del índice: lo que no venga, se retira."""

    fichas: list[FichaDelIndice]


class InformeDeCarga(BaseModel):
    nuevas: int
    actualizadas: int
    sin_cambios: int
    retiradas: int


class FichaView(BaseModel):
    """Lo que se enseña de una ficha. **Sin el vector**: no le sirve a nadie que lo lea."""

    url: str
    titulo: str
    resumen: str
    vigente: bool
    revision_prevista_en: date | None
    metadatos: dict[str, str]
    version_prompt_resumen: str | None
    modelo_resumen: str | None
    updated_at: datetime


async def _cargar(session, agente_id, fichas, embedder) -> InformeDeCarga:
    try:
        informe = await indice.cargar(session, agente_id, fichas, embedder)
    except indice.IndiceNoValido as fallo:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(fallo)
        ) from fallo
    return InformeDeCarga(
        nuevas=informe.nuevas,
        actualizadas=informe.actualizadas,
        sin_cambios=informe.sin_cambios,
        retiradas=informe.retiradas,
    )


@router.put("/{agente_id}/indice", response_model=InformeDeCarga)
async def cargar_indice(
    agente_id: uuid.UUID,
    body: IndiceCompleto,
    user: UserInfo = Depends(require_scopes(AGENTES_INDICE_WRITE)),
    session: AsyncSession = Depends(get_session),
    embedder=Depends(obtener_embedder),
) -> InformeDeCarga:
    """Deja el índice igual que lo que se manda. Es la vía del guion de curación (#174).

    Un token necesita `agentes:indice`; una sesión no, pero las dos necesitan que el agente les
    permita `cargar_indice`: el token abre la puerta, no elige el agente.
    """
    agente, version = await _el_agente(session, agente_id, user)
    _exigir("cargar_indice", agente, version, user)
    fichas = [indice.FichaEntrada(**f.model_dump()) for f in body.fichas]
    return await _cargar(session, agente.id, fichas, embedder)


@router.post("/{agente_id}/indice/hoja", response_model=InformeDeCarga)
async def subir_hoja(
    agente_id: uuid.UUID,
    file: UploadFile = File(...),
    user: UserInfo = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    embedder=Depends(obtener_embedder),
) -> InformeDeCarga:
    """La misma carga, desde la hoja en CSV o Excel. Es la vía del piloto, antes del guion."""
    agente, version = await _el_agente(session, agente_id, user)
    _exigir("cargar_indice", agente, version, user)
    datos = await read_within_limit(file, max_bytes=MAXIMO_BYTES_DE_LA_HOJA)
    try:
        tabla = leer_tabla(datos, sanitizar_nombre(file.filename))
        fichas = indice.desde_tabla(tabla.df)
    except (FicheroNoValido, indice.IndiceNoValido) as fallo:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(fallo)
        ) from fallo
    return await _cargar(session, agente.id, fichas, embedder)


@router.get("/{agente_id}/indice", response_model=list[FichaView])
async def ver_indice(
    agente_id: uuid.UUID,
    user: UserInfo = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[FichaView]:
    agente, _ = await _el_agente(session, agente_id, user)
    filas = (
        await session.execute(
            select(HubAgenteFicha)
            .where(HubAgenteFicha.agente_id == agente.id)
            .order_by(HubAgenteFicha.titulo, HubAgenteFicha.url)
        )
    ).scalars()
    return [
        FichaView(
            url=f.url,
            titulo=f.titulo,
            resumen=f.resumen,
            vigente=f.vigente,
            revision_prevista_en=f.revision_prevista_en,
            metadatos=dict(f.metadatos or {}),
            version_prompt_resumen=f.version_prompt_resumen,
            modelo_resumen=f.modelo_resumen,
            updated_at=f.updated_at,
        )
        for f in filas
    ]


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


# =============================================================================
#  La consulta (#175)
# =============================================================================


class Consulta(BaseModel):
    consulta: str = Field(min_length=1, max_length=2000)
    #: La lengua de las instrucciones fijas; el prompt del agente va como lo escribió su unidad.
    lengua: Literal["es", "ca", "en"] = "es"

    model_config = {"extra": "forbid"}

    @field_validator("consulta")
    @classmethod
    def _con_texto(cls, valor: str) -> str:
        limpio = valor.strip()
        if not limpio:
            raise ValueError("la consulta no puede estar vacía")
        return limpio


class DocumentoOfrecido(BaseModel):
    url: str
    titulo: str
    score: float
    revision_vencida: bool


class RespuestaDeConsulta(BaseModel):
    """El prompt y los enlaces. **Ningún contenido**: los documentos los abre el asistente."""

    agente: str
    version: int
    prompt: str
    documentos: list[DocumentoOfrecido]


@router_catalogo.post("/{agente_id}/consulta", response_model=RespuestaDeConsulta)
async def consultar(
    agente_id: uuid.UUID,
    body: Consulta,
    user: UserInfo = Depends(require_scopes(AGENTES_CONSULTA)),
    session: AsyncSession = Depends(get_session),
    embedder=Depends(obtener_embedder),
) -> RespuestaDeConsulta:
    """El prompt del agente con los enlaces a los documentos pertinentes para esta pregunta.

    No exige el módulo `agentes`: lo usa su colectivo. **No se comprueba si cada enlace se puede
    abrir**: la plataforma sólo podría hacerlo con su propia identidad, que no dice nada de la de
    quien pregunta; la puerta es el almacén, y el prompt pide decirlo si no se abre.

    Se registra lo que se ofreció —quién, cuándo, qué agente, qué documentos y con qué
    puntuación—, nunca la pregunta. Si la consulta falla, no se registra nada.
    """
    agente, version = await _el_agente(session, agente_id, user)
    try:
        elegidas = await indice.seleccionar(
            session, agente, version, body.consulta, embedder, principal=user
        )
    except indice.AgenteNoDisponible as fallo:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "AGENTE_NO_DISPONIBLE",
                "message": (
                    "Este agente no se te ofrece: está suspendido o retirado, o no es para tu "
                    "colectivo."
                ),
            },
        ) from fallo
    except indice.IndiceDeOtroModelo as fallo:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(fallo)) from fallo

    prompt = consulta.componer(version.prompt, body.consulta, elegidas, body.lengua)
    respuesta = RespuestaDeConsulta(
        agente=agente.nombre,
        version=version.version,
        prompt=prompt,
        documentos=[
            DocumentoOfrecido(
                url=e.url, titulo=e.titulo, score=e.score, revision_vencida=e.revision_vencida
            )
            for e in elegidas
        ],
    )

    # El evento pasa por la misma validación que un uso declarado desde fuera, que rechaza
    # cualquier campo de contenido. El hash es del prompt entregado: coteja sin guardar el texto.
    evento = ActividadIAEvent(
        ocurrido_en=datetime.now(timezone.utc),
        actor=user.user_id,
        herramienta="agente-de-unidad",
        agente=f"{agente.nombre} v{version.version} ({agente.id})"[-255:],
        finalidad=version.finalidad[:500],
        payload_hash=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
    )
    actividad = HubActividadIA(
        id=uuid.uuid4(),
        organizacion_id=agente.organizacion_id,
        ocurrido_en=evento.ocurrido_en,
        actor=evento.actor,
        herramienta=evento.herramienta,
        agente=evento.agente,
        finalidad=evento.finalidad,
        categorias_datos=evento.categorias_datos,
        payload_hash=evento.payload_hash,
    )
    session.add(actividad)
    session.add(
        HubAgenteConsulta(
            agente_id=agente.id,
            version=version.version,
            actor=user.user_id,
            documentos=[{"url": e.url, "score": e.score} for e in elegidas],
            actividad_id=actividad.id,
        )
    )
    await session.commit()
    return respuesta
