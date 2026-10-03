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
import os
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.api.deps import (
    get_current_user,
    get_session,
    require_module,
    require_scopes,
    require_sesion_humana,
)
from server.app.api.deps import modulos_concedidos
from server.app.core.auth.pat.service import PatForbiddenError, PatInvalidError, PatService
from server.app.core.auth.models import UserInfo
from server.app.core.auth.tenancy import organizacion_para_operar
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
    #: #175 — quien consulta adjuntará un documento en el asistente general.
    espera_adjunto: bool = False

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
    espera_adjunto: bool
    declarada_en: datetime
    revisada_en: datetime | None
    revision_resultado: str | None
    revision_nota: str | None
    motivo_suspension: str | None
    acciones_permitidas: list[str]


class EstadoDelIndice(BaseModel):
    """Cómo está el índice (#173, #174). **Lo normal es que lo mantenga el guion a diario.**"""

    fichas: int
    actualizado_en: datetime | None
    #: `guion` o `hoja`.
    origen: str | None
    #: Si el guion lleva más de su plazo sin mandarlo. **Avisa, no oculta.**
    sin_actualizar: bool
    #: Documentos que el guion encontró en la carpeta, y cuántos no tienen ficha.
    documentos_en_carpeta: int | None
    faltan: int | None
    #: Fichas resumidas con una versión del prompt que ya no es la vigente.
    desfasadas: int


class AgenteView(BaseModel):
    id: uuid.UUID
    nombre: str
    unidad: str
    es_mio: bool
    indice: EstadoDelIndice
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
    #: Para que la pantalla recuerde adjuntar el documento, y pida describirlo en la pregunta.
    espera_adjunto: bool
    #: #174 — el guion lleva días sin mandar el índice: se ofrece, pero marcado.
    indice_sin_actualizar: bool


# =============================================================================
#  Lo común
# =============================================================================


#: Días que puede pasar el guion sin mandar el índice antes de avisar. Corre a diario; tres días
#: dejan margen a un fin de semana sin que un fallo de verdad pase desapercibido. Cada despliegue
#: lo cambia sin tocar código.
VARIABLE_DEL_PLAZO_DEL_INDICE = "INDICE_SIN_ACTUALIZAR_DIAS"
PLAZO_DEL_INDICE_POR_DEFECTO = 3


def _plazo_del_indice() -> int:
    try:
        dias = int(os.getenv(VARIABLE_DEL_PLAZO_DEL_INDICE, PLAZO_DEL_INDICE_POR_DEFECTO))
    except ValueError:
        return PLAZO_DEL_INDICE_POR_DEFECTO
    return dias if dias > 0 else PLAZO_DEL_INDICE_POR_DEFECTO


def _sin_actualizar(agente: HubAgenteUnidad) -> bool:
    """Sólo el guion promete ir a diario: una hoja subida a mano no se para."""
    if agente.indice_origen != "guion" or agente.indice_actualizado_en is None:
        return False
    return datetime.now(timezone.utc) - agente.indice_actualizado_en > timedelta(
        days=_plazo_del_indice()
    )


def _estado_del_indice(agente: HubAgenteUnidad, fichas: int, desfasadas: int) -> EstadoDelIndice:
    en_carpeta = agente.documentos_en_carpeta
    return EstadoDelIndice(
        fichas=fichas,
        actualizado_en=agente.indice_actualizado_en,
        origen=agente.indice_origen,
        sin_actualizar=_sin_actualizar(agente),
        documentos_en_carpeta=en_carpeta,
        faltan=max(en_carpeta - fichas, 0) if en_carpeta is not None else None,
        desfasadas=desfasadas,
    )


def _vista(
    agente: HubAgenteUnidad,
    version: HubAgenteUnidadVersion,
    user: UserInfo,
    cuentas: tuple[int, int] = (0, 0),
) -> AgenteView:
    return AgenteView(
        id=agente.id,
        nombre=agente.nombre,
        unidad=agente.unidad,
        es_mio=agente.creado_por == user_to_uuid(user.user_id),
        indice=_estado_del_indice(agente, *cuentas),
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
            espera_adjunto=version.espera_adjunto,
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
        espera_adjunto=declaracion.espera_adjunto,
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


async def _fichas_por_agente(
    session: AsyncSession, ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[int, int]]:
    """Por agente: cuántas fichas y cuántas resumidas con otra versión del prompt.

    Una ficha sin versión no está desfasada: la escribió una persona, no un prompt.
    """
    if not ids:
        return {}
    desfasada = (HubAgenteFicha.version_prompt_resumen.is_not(None)) & (
        HubAgenteFicha.version_prompt_resumen != indice.VERSION_PROMPT_RESUMEN
    )
    filas = await session.execute(
        select(
            HubAgenteFicha.agente_id,
            func.count(),
            func.count().filter(desfasada),
        )
        .where(HubAgenteFicha.agente_id.in_(ids))
        .group_by(HubAgenteFicha.agente_id)
    )
    return {agente_id: (n, viejas) for agente_id, n, viejas in filas.all()}


async def _responder(session: AsyncSession, agente, version, user: UserInfo) -> AgenteView:
    # La vista se construye antes del commit: la sesión de los routers expira los atributos al
    # commitear, y leerlos después costaría un 500.
    await session.flush()
    cuentas = (await _fichas_por_agente(session, [agente.id])).get(agente.id, (0, 0))
    vista = _vista(agente, version, user, cuentas)
    await session.commit()
    return vista


# =============================================================================
#  La gestión
# =============================================================================


@router.post("", response_model=AgenteView, status_code=status.HTTP_201_CREATED)
async def publicar(
    body: AgenteCreate,
    organizacion_id: Annotated[
        uuid.UUID | None,
        Query(description="Obligatoria sólo si quien publica no pertenece a una sola organización."),
    ] = None,
    user: UserInfo = Depends(require_sesion_humana()),
    session: AsyncSession = Depends(get_session),
) -> AgenteView:
    """Publica un agente. **Registrar es publicar**: se ofrece a su colectivo desde ya.

    Un agente es de una organización: la de quien publica, o la elegida en el panel si pertenece
    a varias o a ninguna (el superadministrador).
    """
    organizacion = organizacion_para_operar(
        user, organizacion_id, para="Un agente se publica en una organización."
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
    user: UserInfo = Depends(require_sesion_humana()),
    session: AsyncSession = Depends(get_session),
) -> GestionDeAgentes:
    """Los agentes de su organización, con lo que quien pregunta puede hacer con cada uno."""
    filas = await _vigentes(session, _de_sus_organizaciones(user))
    fichas = await _fichas_por_agente(session, [a.id for a, _ in filas])
    return GestionDeAgentes(
        agentes=[_vista(a, v, user, fichas.get(a.id, (0, 0))) for a, v in filas],
        grupos_del_idp=get_settings().saml_enabled,
    )


@router.post("/{agente_id}/versiones", response_model=AgenteView, status_code=status.HTTP_201_CREATED)
async def versionar(
    agente_id: uuid.UUID,
    body: DeclaracionDelAgente,
    user: UserInfo = Depends(require_sesion_humana()),
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
    user: UserInfo = Depends(require_sesion_humana()),
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
    user: UserInfo = Depends(require_sesion_humana()),
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
    user: UserInfo = Depends(require_sesion_humana()),
    session: AsyncSession = Depends(get_session),
) -> AgenteView:
    agente, version = await _el_agente(session, agente_id, user)
    _exigir("reactivar", agente, version, user)
    acciones.reactivar(version)
    return await _responder(session, agente, version, user)


@router.post("/{agente_id}/retirar", response_model=AgenteView)
async def retirar(
    agente_id: uuid.UUID,
    user: UserInfo = Depends(require_sesion_humana()),
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
    #: #174 — cuántos documentos encontró el guion en la carpeta, tengan o no ficha. Es lo que
    #: permite ver los que se quedaron fuera: sin contarlos, un documento que no llega no existe.
    documentos_en_carpeta: int | None = Field(default=None, ge=0)


class PromptDeResumen(BaseModel):
    version: str
    texto: str


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


async def _cargar(
    session, agente_id, fichas, embedder, *, origen: str, documentos_en_carpeta: int | None = None
) -> InformeDeCarga:
    try:
        informe = await indice.cargar(session, agente_id, fichas, embedder)
    except indice.IndiceNoValido as fallo:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(fallo)
        ) from fallo
    # La fecha se apunta **también sin cambios**: es la prueba de que el guion sigue vivo.
    await session.execute(
        update(HubAgenteUnidad)
        .where(HubAgenteUnidad.id == agente_id)
        .values(
            indice_actualizado_en=datetime.now(timezone.utc),
            indice_origen=origen,
            documentos_en_carpeta=documentos_en_carpeta,
        )
    )
    await session.commit()
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
    return await _cargar(
        session,
        agente.id,
        fichas,
        embedder,
        origen="guion",
        documentos_en_carpeta=body.documentos_en_carpeta,
    )


@router.post("/{agente_id}/indice/hoja", response_model=InformeDeCarga)
async def subir_hoja(
    agente_id: uuid.UUID,
    file: UploadFile = File(...),
    user: UserInfo = Depends(require_sesion_humana()),
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
    return await _cargar(session, agente.id, fichas, embedder, origen="hoja")


@router.get("/prompt-de-resumen", response_model=PromptDeResumen)
async def prompt_de_resumen(
    _: UserInfo = Depends(require_scopes(AGENTES_INDICE_WRITE)),
) -> PromptDeResumen:
    """El prompt con el que el guion resume cada documento, y su versión (#174).

    Lo sirve la plataforma y lo ejecuta el guion. El guion escribe la versión en cada ficha, y si
    la plataforma no responde usa la última que guardó **y escribe esa**: el índice sigue diciendo
    con qué se hizo cada resumen.
    """
    return PromptDeResumen(version=indice.VERSION_PROMPT_RESUMEN, texto=indice.PROMPT_DE_RESUMEN)


@router.get("/{agente_id}/indice", response_model=list[FichaView])
async def ver_indice(
    agente_id: uuid.UUID,
    user: UserInfo = Depends(require_sesion_humana()),
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
#  El token del guion (#174)
# =============================================================================


class TokenDelGuionCreate(BaseModel):
    nombre: str = Field(min_length=1, max_length=100)

    model_config = {"extra": "forbid"}


class TokenDelGuion(BaseModel):
    """Un token del guion, **sin su texto**: éste se ve una sola vez, al emitirlo."""

    id: uuid.UUID
    nombre: str
    prefijo: str
    creado_en: datetime
    ultimo_uso_en: datetime | None


class TokenDelGuionEmitido(TokenDelGuion):
    #: El texto del token. **Única vez que se devuelve**: va a las propiedades del guion.
    token: str


def _es_del_guion(pat) -> bool:
    return list(pat.scopes) == [AGENTES_INDICE_WRITE] and pat.revoked_at is None


@router.post("/tokens", response_model=TokenDelGuionEmitido, status_code=status.HTTP_201_CREATED)
async def emitir_token_del_guion(
    body: TokenDelGuionCreate,
    user: UserInfo = Depends(require_sesion_humana()),
    modulos: list[str] = Depends(modulos_concedidos),
    session: AsyncSession = Depends(get_session),
) -> TokenDelGuionEmitido:
    """Un token con **un solo alcance**, `agentes:indice`, para el guion que mantiene el índice.

    Lo emite quien publica, sin pasar por un administrador (decisión del usuario, 2026-10-03). El
    token abre la puerta y nada más: qué agente puede cargar lo sigue decidiendo `cargar_indice`,
    y no sirve para publicar, retirar ni emitir otros tokens.
    """
    try:
        pat, token = await PatService(session).create(
            owner=user, name=body.nombre, scopes=[AGENTES_INDICE_WRITE], modulos=modulos
        )
    except PatForbiddenError as fallo:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(fallo)) from fallo
    return TokenDelGuionEmitido(
        id=pat.id,
        nombre=pat.name,
        prefijo=pat.token_prefix,
        creado_en=pat.created_at,
        ultimo_uso_en=pat.last_used_at,
        token=token,
    )


@router.get("/tokens", response_model=list[TokenDelGuion])
async def tokens_del_guion(
    user: UserInfo = Depends(require_sesion_humana()),
    session: AsyncSession = Depends(get_session),
) -> list[TokenDelGuion]:
    """Los tokens del guion de quien pregunta, vigentes. Para saber cuáles hay y revocarlos."""
    return [
        TokenDelGuion(
            id=p.id,
            nombre=p.name,
            prefijo=p.token_prefix,
            creado_en=p.created_at,
            ultimo_uso_en=p.last_used_at,
        )
        for p in await PatService(session).list_for(user)
        if _es_del_guion(p)
    ]


@router.delete("/tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revocar_token_del_guion(
    token_id: uuid.UUID,
    user: UserInfo = Depends(require_sesion_humana()),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Revoca un token del guion propio. El de otra persona no existe para quien pregunta."""
    servicio = PatService(session)
    if not any(p.id == token_id and _es_del_guion(p) for p in await servicio.list_for(user)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token no encontrado")
    try:
        await servicio.revoke(user, token_id)
    except PatInvalidError as fallo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token no encontrado") from fallo
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
            espera_adjunto=v.espera_adjunto,
            indice_sin_actualizar=_sin_actualizar(a),
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
    #: El adjunto va directo al asistente: la plataforma no lo ve, y por eso tampoco lo registra.
    espera_adjunto: bool


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

    prompt = consulta.componer(
        version.prompt,
        body.consulta,
        elegidas,
        body.lengua,
        espera_adjunto=version.espera_adjunto,
    )
    respuesta = RespuestaDeConsulta(
        agente=agente.nombre,
        version=version.version,
        prompt=prompt,
        espera_adjunto=version.espera_adjunto,
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
