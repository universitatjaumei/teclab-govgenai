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

import asyncio
import hashlib
import os
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.api.deps import (
    get_session,
    require_module,
    require_scopes,
    require_sesion_humana,
    require_superadmin,
)
from server.app.api.deps import modulos_concedidos
from server.app.core.auth.pat.service import PatForbiddenError, PatInvalidError, PatService
from server.app.core.auth.models import UserInfo
from server.app.core.auth.tenancy import organizacion_para_operar
from server.app.core.config import get_settings
from server.app.core.auth.pat.scopes import AGENTES_CONSULTA, AGENTES_INDICE_WRITE
from server.app.core.identidad import user_to_uuid
from server.app.core.uploads import read_within_limit, sanitizar_nombre
from server.app.core.llm_text import texto_de
from server.app.modules.agentes import acciones, consulta, datos, indice, propuesta, registro
from server.app.modules.agents_hub.services.config_provider import LocalConfigProvider
from server.app.modules.agents_hub.services.model_factory import get_model_for_tier
from server.app.routers.redaccion._actor import nombre_del_modelo
from server.app.modules.agentes.guion_del_indice import guion_del_indice
from server.app.modules.agents_hub.contracts.actividad import ActividadIAEvent
from server.app.modules.agents_hub.database.operational_models import (
    HubActividadIA,
    HubAgenteConsulta,
    HubAgenteFicha,
    HubAgenteUnidad,
    HubAgenteUnidadVersion,
    HubAsistenteAdaptador,
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


class DatoDeLaConsulta(BaseModel):
    """Un dato que tiene que dar quien pregunta (#219). Dos tipos: lista de opciones y texto."""

    etiqueta: str = Field(min_length=1, max_length=80)
    tipo: Literal["opciones", "texto"]
    ayuda: str | None = Field(default=None, max_length=200)
    #: Sólo en `opciones`: al menos dos, sin repetir.
    opciones: list[str] = Field(default_factory=list, max_length=30)
    obligatorio: bool = False
    #: La columna del índice con la que casa: si la tiene, filtra (en suave).
    columna: str | None = Field(default=None, max_length=80)
    #: Sólo en `texto`: para códigos jerárquicos como el CPV, casa por prefijo.
    prefijo: bool = False

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _coherente(self) -> "DatoDeLaConsulta":
        self.etiqueta = self.etiqueta.strip()
        self.ayuda = (self.ayuda or "").strip() or None
        self.columna = (self.columna or "").strip() or None
        self.opciones = [o.strip() for o in self.opciones if o.strip()]
        if self.tipo == "opciones":
            if len(self.opciones) < 2 or len(set(self.opciones)) != len(self.opciones):
                raise ValueError(f"«{self.etiqueta}»: una lista lleva al menos dos opciones distintas")
            if self.prefijo:
                raise ValueError(f"«{self.etiqueta}»: el prefijo es para códigos escritos, no para una lista")
        elif self.opciones:
            raise ValueError(f"«{self.etiqueta}»: un texto no lleva opciones")
        return self


class ReservaDeCapa(BaseModel):
    """#228 — cuántas plazas de cada consulta se reservan, como mínimo, a una capa del índice."""

    capa: str = Field(min_length=1, max_length=80)
    plazas: int = Field(ge=1, le=10)

    model_config = {"extra": "forbid"}

    @field_validator("capa")
    @classmethod
    def _con_texto(cls, valor: str) -> str:
        limpio = valor.strip()
        # Sólo signos se normaliza a vacío, que es la «capa» de las fichas sin columna `capa`
        # (revisión de la PR #229): la reserva preferiría documentos sin clasificar.
        if not indice.normalizar_columna(limpio):
            raise ValueError("la capa tiene que tener letras o números")
        return limpio


class DatoDeLaConsultaView(DatoDeLaConsulta):
    #: Contra qué clave se manda el valor en la consulta. La deriva la plataforma de la etiqueta.
    clave: str


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
    #: #175, #218 — si quien consulta adjunta un documento en el asistente general.
    adjunto: Literal["no", "opcional", "obligatorio"] = "no"
    #: #218 — en qué lengua se responde; la instrucción la añade la plataforma.
    lengua_respuesta: Literal["pregunta", "es", "ca"] = "pregunta"
    #: #219 — los datos que tiene que dar quien pregunta, y una línea de indicaciones.
    datos_consulta: list[DatoDeLaConsulta] = Field(default_factory=list, max_length=8)
    indicaciones: str | None = Field(default=None, max_length=500)
    #: #228 — plazas reservadas por capa del índice.
    reservas: list[ReservaDeCapa] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def _reservas_que_caben(self) -> "DeclaracionDelAgente":
        claves = [indice.normalizar_columna(r.capa) for r in self.reservas]
        repetidas = sorted({c for c in claves if claves.count(c) > 1})
        if repetidas:
            raise ValueError(f"la misma capa reservada dos veces: {', '.join(repetidas)}")
        total = sum(r.plazas for r in self.reservas)
        if total > self.presupuesto_documentos:
            raise ValueError(
                f"las reservas suman {total} plazas y el agente sólo devuelve {self.presupuesto_documentos} documentos"
            )
        return self

    @field_validator("datos_consulta")
    @classmethod
    def _claves_distintas(cls, valor: list[DatoDeLaConsulta]) -> list[DatoDeLaConsulta]:
        claves = [datos.clave(d.etiqueta) for d in valor]
        repetidas = sorted({c for c in claves if claves.count(c) > 1})
        if repetidas:
            raise ValueError(f"dos datos con la misma etiqueta: {', '.join(repetidas)}")
        return valor
    #: #213 — `ia` si el prompt se redactó con el asistente de propuestas. Lo declara quien publica.
    autoria_prompt: Literal["persona", "ia"] = "persona"

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
    adjunto: str
    lengua_respuesta: str
    datos_consulta: list[DatoDeLaConsultaView]
    indicaciones: str | None
    reservas: list[ReservaDeCapa]
    autoria_prompt: str
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


class CalidadDelAgente(BaseModel):
    """#217 — los contadores de la ficha. Sólo los ve quien puede ver la calidad."""

    consultas: int
    respuestas_leidas: int
    informes_sin_revisar: int


class AgenteView(BaseModel):
    id: uuid.UUID
    nombre: str
    unidad: str
    es_mio: bool
    indice: EstadoDelIndice
    #: #216 — qué se guarda de sus conversaciones.
    modo_registro: Literal["validacion", "incidencias"]
    #: #217 — nulo para quien no puede ver la calidad del agente.
    calidad: CalidadDelAgente | None = None
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
    #: Para que la pantalla recuerde adjuntar el documento —u ofrezca hacerlo, si es opcional— y
    #: pida describirlo en la pregunta.
    adjunto: str
    #: #219 — el formulario de la consulta lo pinta la pantalla a partir de esto.
    datos_consulta: list[DatoDeLaConsultaView]
    indicaciones: str | None
    #: #174 — el guion lleva días sin mandar el índice: se ofrece, pero marcado.
    indice_sin_actualizar: bool
    #: #216 — para avisar, antes de consultar, de que en validación se guarda la conversación.
    modo_registro: Literal["validacion", "incidencias"]


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
    calidad: tuple[int, int, int] = (0, 0, 0),
) -> AgenteView:
    permitidas = acciones.acciones_permitidas(agente, version, principal=user)
    return AgenteView(
        calidad=CalidadDelAgente(
            consultas=calidad[0], respuestas_leidas=calidad[1], informes_sin_revisar=calidad[2]
        )
        if "ver_calidad" in permitidas
        else None,
        id=agente.id,
        nombre=agente.nombre,
        unidad=agente.unidad,
        es_mio=agente.creado_por == user_to_uuid(user.user_id),
        indice=_estado_del_indice(agente, *cuentas),
        modo_registro=agente.modo_registro,
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
            adjunto=version.adjunto,
            lengua_respuesta=version.lengua_respuesta,
            datos_consulta=version.datos_consulta or [],
            indicaciones=version.indicaciones,
            reservas=version.reservas or [],
            autoria_prompt=version.autoria_prompt,
            declarada_en=version.declarada_en,
            revisada_en=version.revisada_en,
            revision_resultado=version.revision_resultado,
            revision_nota=version.revision_nota,
            motivo_suspension=version.motivo_suspension,
            acciones_permitidas=permitidas,
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
        adjunto=declaracion.adjunto,
        lengua_respuesta=declaracion.lengua_respuesta,
        datos_consulta=[
            {"clave": datos.clave(d.etiqueta), **d.model_dump()} for d in declaracion.datos_consulta
        ],
        indicaciones=(declaracion.indicaciones or "").strip() or None,
        reservas=[r.model_dump() for r in declaracion.reservas],
        autoria_prompt=declaracion.autoria_prompt,
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
    session: AsyncSession, vigentes: dict[uuid.UUID, HubAgenteUnidadVersion]
) -> dict[uuid.UUID, tuple[int, int]]:
    """Por agente: cuántas fichas y cuántas resumidas con otra versión del prompt.

    Una ficha sin versión no está desfasada: la escribió una persona, no un prompt. **La versión
    con que se compara es la del agente** (#220): con datos que extraer, su prompt no es el común.
    """
    if not vigentes:
        return {}
    suya = {aid: indice.prompt_de_resumen(v.datos_consulta)[0] for aid, v in vigentes.items()}
    filas = await session.execute(
        select(HubAgenteFicha.agente_id, HubAgenteFicha.version_prompt_resumen, func.count())
        .where(HubAgenteFicha.agente_id.in_(list(vigentes)))
        .group_by(HubAgenteFicha.agente_id, HubAgenteFicha.version_prompt_resumen)
    )
    cuentas: dict[uuid.UUID, tuple[int, int]] = {}
    for agente_id, version_resumen, n in filas.all():
        total, viejas = cuentas.get(agente_id, (0, 0))
        desfasada = version_resumen is not None and version_resumen != suya[agente_id]
        cuentas[agente_id] = (total + n, viejas + (n if desfasada else 0))
    return cuentas


async def _calidad_por_agente(
    session: AsyncSession, ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[int, int, int]]:
    """#217 — por agente: consultas, respuestas leídas e informes sin revisar."""
    if not ids:
        return {}
    filas = await session.execute(
        select(
            HubAgenteConsulta.agente_id,
            func.count(),
            func.count().filter(HubAgenteConsulta.respuesta.is_not(None)),
            func.count().filter((HubAgenteConsulta.puntuacion == -1) & HubAgenteConsulta.veredicto.is_(None)),
        )
        .where(HubAgenteConsulta.agente_id.in_(ids))
        .group_by(HubAgenteConsulta.agente_id)
    )
    return {agente_id: (n, leidas, abiertos) for agente_id, n, leidas, abiertos in filas.all()}


async def _responder(session: AsyncSession, agente, version, user: UserInfo) -> AgenteView:
    # La vista se construye antes del commit: la sesión de los routers expira los atributos al
    # commitear, y leerlos después costaría un 500.
    await session.flush()
    cuentas = (await _fichas_por_agente(session, {agente.id: version})).get(agente.id, (0, 0))
    calidad = (await _calidad_por_agente(session, [agente.id])).get(agente.id, (0, 0, 0))
    vista = _vista(agente, version, user, cuentas, calidad)
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
    fichas = await _fichas_por_agente(session, {a.id: v for a, v in filas})
    calidad = await _calidad_por_agente(session, [a.id for a, _ in filas])
    return GestionDeAgentes(
        agentes=[_vista(a, v, user, fichas.get(a.id, (0, 0)), calidad.get(a.id, (0, 0, 0))) for a, v in filas],
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
    if body.carpeta_url != vigente.carpeta_url:
        # Otra carpeta, otro índice: el de la anterior no puede seguir sirviéndose hasta que el
        # guion corra sobre la nueva (revisión de la PR #221). El índice es derivado: se rehace.
        await session.execute(delete(HubAgenteFicha).where(HubAgenteFicha.agente_id == agente.id))
        agente.indice_actualizado_en = None
        agente.indice_origen = None
        agente.documentos_en_carpeta = None
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


class DatoAExtraer(BaseModel):
    columna: str
    etiqueta: str
    tipo: str
    opciones: list[str]


class PromptDeResumen(BaseModel):
    version: str
    texto: str
    #: #220 — los datos que el guion extrae a su columna del índice. Vacío sin agente o sin datos.
    datos: list[DatoAExtraer] = Field(default_factory=list)


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
    agente_id: uuid.UUID | None = None,
    user: UserInfo = Depends(require_scopes(AGENTES_INDICE_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> PromptDeResumen:
    """El prompt con el que el guion resume cada documento, y su versión (#174).

    Lo sirve la plataforma y lo ejecuta el guion. El guion escribe la versión en cada ficha, y si
    la plataforma no responde usa la última que guardó **y escribe esa**: el índice sigue diciendo
    con qué se hizo cada resumen.
    """
    if agente_id is None:
        return PromptDeResumen(version=indice.VERSION_PROMPT_RESUMEN, texto=indice.PROMPT_DE_RESUMEN)
    # #220 — el del agente: pide extraer los datos de la consulta ligados a una columna.
    _, version = await _el_agente(session, agente_id, user)
    numero, texto, extraer = indice.prompt_de_resumen(version.datos_consulta)
    return PromptDeResumen(version=numero, texto=texto, datos=[DatoAExtraer(**e) for e in extraer])


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
#  La propuesta del prompt (#213)
# =============================================================================


class PeticionDePropuesta(BaseModel):
    """Lo que la unidad describe, y lo que ya ha declarado en el formulario."""

    descripcion: str = Field(min_length=10, max_length=4000)
    nombre: str | None = Field(default=None, max_length=200)
    unidad: str | None = Field(default=None, max_length=200)
    finalidad: str | None = Field(default=None, max_length=2000)
    colectivo: Literal["organizacion", "grupos"] | None = None
    grupos: list[str] = Field(default_factory=list)
    adjunto: Literal["no", "opcional", "obligatorio"] = "no"
    lengua_respuesta: Literal["pregunta", "es", "ca"] = "pregunta"
    lengua: Literal["es", "ca", "en"] = "es"

    model_config = {"extra": "forbid"}

    @field_validator("descripcion")
    @classmethod
    def _descripcion_con_texto(cls, valor: str) -> str:
        limpio = valor.strip()
        if len(limpio) < 10:
            raise ValueError("describe en una frase al menos para qué quieres el agente")
        return limpio


class PropuestaDePrompt(BaseModel):
    """El prompt propuesto. **No se ha guardado**: va al formulario para editarlo."""

    prompt: str
    modelo_usado: str
    version: str


async def obtener_modelo_de_redaccion(
    organizacion_id: Annotated[uuid.UUID | None, Query()] = None,
    user: UserInfo = Depends(require_sesion_humana()),
    session: AsyncSession = Depends(get_session),
):
    """El modelo de nivel 1 de la organización, o el de la plataforma, como los borradores."""
    organizacion = organizacion_para_operar(
        user, organizacion_id, para="La propuesta usa el modelo de una organización."
    )
    try:
        return await get_model_for_tier(1, LocalConfigProvider(session), organizacion_id=organizacion)
    except Exception as fallo:  # noqa: BLE001 — sin modelo no hay propuesta, y el motivo va en el mensaje
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "No hay modelo para redactar la propuesta (nivel 1). Asígnale uno en Plataforma › "
                f"Modelos IA. Motivo: {fallo}"
            ),
        ) from fallo


@router.post("/proponer-prompt", response_model=PropuestaDePrompt)
async def proponer_prompt(
    body: PeticionDePropuesta,
    organizacion_id: Annotated[uuid.UUID | None, Query()] = None,
    user: UserInfo = Depends(require_sesion_humana()),
    session: AsyncSession = Depends(get_session),
    modelo=Depends(obtener_modelo_de_redaccion),
) -> PropuestaDePrompt:
    """Un prompt propuesto a partir de lo que la unidad describe. **Propone, no publica.**

    Queda constancia del uso en el registro de actividad —quién, cuándo, con qué modelo y la huella
    de la descripción—, nunca del texto.
    """
    organizacion = organizacion_para_operar(
        user, organizacion_id, para="La propuesta se anota en el registro de una organización."
    )
    try:
        respuesta = await modelo.ainvoke(
            propuesta.mensajes(
                descripcion=body.descripcion,
                nombre=body.nombre,
                unidad=body.unidad,
                finalidad=body.finalidad,
                colectivo=body.colectivo,
                grupos=body.grupos,
                adjunto=body.adjunto,
                lengua_respuesta=body.lengua_respuesta,
                lengua=body.lengua,
            )
        )
    except Exception as fallo:  # noqa: BLE001 — el proveedor puede fallar de muchas maneras
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="El modelo no ha respondido. Inténtalo de nuevo en un momento.",
        ) from fallo
    texto = propuesta.limpiar(texto_de(respuesta))
    if not texto:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="El modelo no ha devuelto ninguna propuesta. Inténtalo de nuevo.",
        )

    modelo_usado = nombre_del_modelo(modelo)
    evento = ActividadIAEvent(
        ocurrido_en=datetime.now(timezone.utc),
        actor=user.user_id,
        herramienta="agentes/proponer-prompt",
        agente=(body.nombre or None),
        finalidad="Proponer el prompt de un agente de unidad a partir de su finalidad",
        modelo_usado=(modelo_usado or None),
        payload_hash=hashlib.sha256(body.descripcion.encode("utf-8")).hexdigest(),
    )
    session.add(
        HubActividadIA(
            organizacion_id=organizacion,
            ocurrido_en=evento.ocurrido_en,
            actor=evento.actor,
            herramienta=evento.herramienta,
            agente=evento.agente,
            finalidad=evento.finalidad,
            modelo_usado=evento.modelo_usado,
            categorias_datos=evento.categorias_datos,
            payload_hash=evento.payload_hash,
        )
    )
    await session.commit()
    return PropuestaDePrompt(
        prompt=texto, modelo_usado=modelo_usado or "", version=propuesta.VERSION_META_PROMPT
    )


# =============================================================================
#  El guion (#174)
# =============================================================================


class GuionDelIndiceView(BaseModel):
    """El guion de Apps Script, su manifiesto, su versión y su huella."""

    version: str
    sha256: str
    codigo: str
    manifiesto: str


@router.get("/guion", response_model=GuionDelIndiceView)
async def guion(
    _: UserInfo = Depends(require_sesion_humana()),
) -> GuionDelIndiceView:
    """El guion que mantiene el índice. **Uno para todas las unidades**, con sus parámetros.

    Se entrega con su huella: quien lo instala puede comprobar que es este, y no una copia que
    alguien haya retocado.
    """
    g = await asyncio.to_thread(guion_del_indice)
    return GuionDelIndiceView(version=g.version, sha256=g.sha256, codigo=g.codigo, manifiesto=g.manifiesto)


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
    user: UserInfo = Depends(require_scopes(AGENTES_CONSULTA)),
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
            adjunto=v.adjunto,
            datos_consulta=v.datos_consulta or [],
            indicaciones=v.indicaciones,
            indice_sin_actualizar=_sin_actualizar(a),
            modo_registro=a.modo_registro,
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
    #: #218 — si quien pregunta va a adjuntar un documento. Sólo cuenta en un agente con el adjunto
    #: `opcional`; en los demás lo decidió la unidad.
    adjunta: bool = False
    #: #219 — los datos que declara el agente, por su clave.
    datos: dict[str, Annotated[str, Field(max_length=200)]] = Field(default_factory=dict)

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
    #: Si **esta consulta** lleva adjunto (#218: según el agente y, si es opcional, quien pregunta).
    #: El adjunto va directo al asistente: la plataforma no lo ve, y por eso tampoco lo registra.
    espera_adjunto: bool
    #: #216 — contra qué se mandan la respuesta y la valoración.
    consulta_id: uuid.UUID
    #: #216 — en `validacion` la extensión manda la respuesta que lea; en `incidencias`, sólo un
    #: informe si la persona lo pide.
    modo_registro: Literal["validacion", "incidencias"]


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
    pares = _validar_datos(version, body.datos)
    elegidas = await _seleccionar(session, agente, version, body.consulta, pares, embedder, user)

    # #218 — en `opcional` lo dice quien pregunta; en los otros dos, lo decidió la unidad.
    con_adjunto = version.adjunto == "obligatorio" or (version.adjunto == "opcional" and body.adjunta)
    prompt = consulta.componer(
        version.prompt,
        body.consulta,
        elegidas,
        body.lengua,
        con_adjunto=con_adjunto,
        lengua_respuesta=version.lengua_respuesta,
        datos=[(d["etiqueta"], v) for d, v in pares],
    )
    consulta_id = uuid.uuid4()
    respuesta = RespuestaDeConsulta(
        consulta_id=consulta_id,
        modo_registro=agente.modo_registro,
        agente=agente.nombre,
        version=version.version,
        prompt=prompt,
        espera_adjunto=con_adjunto,
        documentos=[
            DocumentoOfrecido(
                url=e.url, titulo=e.titulo, score=e.score, revision_vencida=e.revision_vencida
            )
            for e in elegidas
        ],
    )

    _registrar(
        session, agente, version, user, consulta_id, prompt, elegidas,
        pregunta=body.consulta, datos_dados={d["clave"]: v for d, v in pares},
    )
    await session.commit()
    return respuesta


async def _seleccionar(session, agente, version, texto, pares, embedder, user, excluir=frozenset()):
    """La selección con los errores de la consulta traducidos a HTTP: la comparten la consulta y
    su ampliación."""
    try:
        return await indice.seleccionar(
            session,
            agente,
            version,
            datos.para_buscar(texto, pares),
            embedder,
            principal=user,
            filtros=datos.filtros(pares),
            excluir=excluir,
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


def _validar_datos(version, dados: dict[str, str]):
    try:
        return datos.validar(version.datos_consulta or [], dados)
    except datos.DatosNoValidos as fallo:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(fallo)) from fallo


def _registrar(
    session: AsyncSession,
    agente,
    version,
    user: UserInfo,
    consulta_id: uuid.UUID,
    prompt: str,
    elegidas,
    *,
    pregunta: str,
    datos_dados: dict[str, str],
    consulta_madre_id: uuid.UUID | None = None,
) -> None:
    """El uso en el registro de actividad y la consulta con lo que se ofreció.

    El evento pasa por la misma validación que un uso declarado desde fuera, que rechaza
    cualquier campo de contenido. El hash es del prompt entregado: coteja sin guardar el texto.
    """
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
            id=consulta_id,
            agente_id=agente.id,
            version=version.version,
            actor=user.user_id,
            documentos=[{"url": e.url, "score": e.score} for e in elegidas],
            actividad_id=actividad.id,
            modo=agente.modo_registro,
            # #216 — en validación se guarda la pregunta; el registro de actividad, nunca.
            pregunta=pregunta if agente.modo_registro == "validacion" else None,
            datos=datos_dados if agente.modo_registro == "validacion" and datos_dados else None,
            consulta_madre_id=consulta_madre_id,
        )
    )


class Ampliacion(BaseModel):
    """#225 — «Buscar más documentos»: qué falta o qué se quiere precisar, y los datos, que pueden
    cambiar. Se busca con esto y no con la pregunta original: lo que se pide es otra cosa o la misma
    más concreta."""

    texto: str = Field(min_length=1, max_length=2000)
    lengua: Literal["es", "ca", "en"] = "es"
    datos: dict[str, Annotated[str, Field(max_length=200)]] = Field(default_factory=dict)

    model_config = {"extra": "forbid"}

    @field_validator("texto")
    @classmethod
    def _con_texto(cls, valor: str) -> str:
        limpio = valor.strip()
        if not limpio:
            raise ValueError("el texto no puede estar vacío")
        return limpio


@router_catalogo.post("/consultas/{consulta_id}/ampliacion", response_model=RespuestaDeConsulta)
async def ampliar(
    consulta_id: uuid.UUID,
    body: Ampliacion,
    user: UserInfo = Depends(require_scopes(AGENTES_CONSULTA)),
    session: AsyncSession = Depends(get_session),
    embedder=Depends(obtener_embedder),
) -> RespuestaDeConsulta:
    """Más documentos para la conversación ya abierta en el asistente (#225), **sin repetir** los
    ofrecidos en ella. Sólo quien hizo la consulta; se puede ampliar desde cualquier eslabón.

    Con las reglas de la versión vigente —filtro, prioritarias, reservas por capa— sobre lo que
    queda. Lo que se pega es corto: el texto y los enlaces nuevos, sin el prompt del agente, que ya
    está en la conversación. Es una consulta más, ligada a la primera, con su fila en el registro.
    """
    fila = await _la_consulta(session, consulta_id, user)
    madre_id = fila.consulta_madre_id or fila.id
    ofrecidas = (
        await session.execute(
            select(HubAgenteConsulta.documentos).where(
                or_(HubAgenteConsulta.id == madre_id, HubAgenteConsulta.consulta_madre_id == madre_id)
            )
        )
    ).scalars()
    excluir = frozenset(d["url"] for documentos in ofrecidas for d in (documentos or []))

    agente, version = await _el_agente(session, fila.agente_id, user)
    pares = _validar_datos(version, body.datos)
    elegidas = await _seleccionar(session, agente, version, body.texto, pares, embedder, user, excluir)
    prompt = consulta.componer_ampliacion(
        body.texto, elegidas, body.lengua, datos=[(d["etiqueta"], v) for d, v in pares]
    )
    nueva_id = uuid.uuid4()
    # Antes del commit: la sesión de los routers expira los objetos al commitear, y leer después
    # `agente.nombre` daba 500 (verificación en vivo; `db_session` de las pruebas no expira).
    respuesta = RespuestaDeConsulta(
        consulta_id=nueva_id,
        modo_registro=agente.modo_registro,
        agente=agente.nombre,
        version=version.version,
        prompt=prompt,
        espera_adjunto=False,
        documentos=[
            DocumentoOfrecido(url=e.url, titulo=e.titulo, score=e.score, revision_vencida=e.revision_vencida)
            for e in elegidas
        ],
    )
    _registrar(
        session, agente, version, user, nueva_id, prompt, elegidas,
        pregunta=body.texto, datos_dados={d["clave"]: v for d, v in pares}, consulta_madre_id=madre_id,
    )
    await session.commit()
    return respuesta


# =============================================================================
#  La extensión del navegador (#176)
# =============================================================================

#: Los identificadores de extensión a los que se entrega un token, separados por comas. El de una
#: extensión cargada sin empaquetar cambia con la carpeta; el de la publicada es fijo. Vacío, no se
#: conecta ninguna.
VARIABLE_DE_LAS_EXTENSIONES = "AGENTES_EXTENSION_IDS"
#: Lo que dura una conexión. Vive en el navegador, y una olvidada no debe durar para siempre;
#: al caducar, la extensión pide conectar otra vez.
DURACION_DE_LA_CONEXION = timedelta(days=30)
NOMBRE_DE_LA_CONEXION = "Extensión del navegador"


def _destinos_de_la_extension() -> set[str]:
    ids = (i.strip() for i in os.getenv(VARIABLE_DE_LAS_EXTENSIONES, "").split(","))
    return {f"https://{i}.chromiumapp.org/" for i in ids if i}


def _es_de_la_extension(pat) -> bool:
    return list(pat.scopes) == [AGENTES_CONSULTA] and pat.revoked_at is None


def _vigente(pat) -> bool:
    if pat.expires_at is None:
        return True
    caduca = pat.expires_at if pat.expires_at.tzinfo else pat.expires_at.replace(tzinfo=timezone.utc)
    return caduca > datetime.now(timezone.utc)


class PeticionDeConexion(BaseModel):
    #: La dirección de vuelta de la extensión: `chrome.identity.getRedirectURL()`.
    destino: str = Field(max_length=200)

    model_config = {"extra": "forbid"}


class ConexionDeLaExtension(BaseModel):
    """Una conexión, **sin el texto del token**: ése sólo lo recibe la extensión."""

    id: uuid.UUID
    prefijo: str
    creado_en: datetime
    ultimo_uso_en: datetime | None
    caduca_en: datetime | None


class ConexionEmitida(BaseModel):
    id: uuid.UUID
    token: str
    #: El destino que validó el servidor: la página redirige a éste y no al de su dirección.
    destino: str


@router_catalogo.post(
    "/extension/conectar", response_model=ConexionEmitida, status_code=status.HTTP_201_CREATED
)
async def conectar_la_extension(
    body: PeticionDeConexion,
    user: UserInfo = Depends(require_sesion_humana()),
    modulos: list[str] = Depends(modulos_concedidos),
    session: AsyncSession = Depends(get_session),
) -> ConexionEmitida:
    """Un token que **sólo sirve para consultar**, para la extensión de quien lo pide.

    **Sólo a un destino declarado**: la página del panel redirige al destino con el token, y si
    aceptara cualquiera, una página ajena podría pedir uno haciéndose pasar por la extensión y
    llevárselo. Lo pide una persona con su sesión: un token no emite otro.
    """
    if body.destino not in _destinos_de_la_extension():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "EXTENSION_NO_RECONOCIDA",
                "message": "Esta extensión no está reconocida por la plataforma.",
            },
        )
    try:
        pat, token = await PatService(session).create(
            owner=user,
            name=NOMBRE_DE_LA_CONEXION,
            scopes=[AGENTES_CONSULTA],
            expires_at=datetime.now(timezone.utc) + DURACION_DE_LA_CONEXION,
            modulos=modulos,
        )
    except PatForbiddenError as fallo:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(fallo)) from fallo
    return ConexionEmitida(id=pat.id, token=token, destino=body.destino)


@router_catalogo.get("/extension/conexiones", response_model=list[ConexionDeLaExtension])
async def conexiones_de_la_extension(
    user: UserInfo = Depends(require_sesion_humana()),
    session: AsyncSession = Depends(get_session),
) -> list[ConexionDeLaExtension]:
    """Las conexiones vigentes de quien pregunta, para saber dónde está conectada y revocarlas."""
    return [
        ConexionDeLaExtension(
            id=p.id,
            prefijo=p.token_prefix,
            creado_en=p.created_at,
            ultimo_uso_en=p.last_used_at,
            caduca_en=p.expires_at,
        )
        for p in await PatService(session).list_for(user)
        if _es_de_la_extension(p) and _vigente(p)
    ]


@router_catalogo.delete("/extension/conexiones/{conexion_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revocar_conexion_de_la_extension(
    conexion_id: uuid.UUID,
    user: UserInfo = Depends(require_sesion_humana()),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Revoca una conexión propia. La de otra persona no existe para quien pregunta."""
    servicio = PatService(session)
    if not any(p.id == conexion_id and _es_de_la_extension(p) for p in await servicio.list_for(user)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conexión no encontrada")
    try:
        await servicio.revoke(user, conexion_id)
    except PatInvalidError as fallo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conexión no encontrada") from fallo
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# =============================================================================
#  El adaptador del asistente (#215)
# =============================================================================

#: Lo que lee `extension/asistente.js`. Un adaptador sin alguno no se guarda: la extensión fallaría
#: en todos los navegadores a la vez.
SELECTORES_DEL_ADAPTADOR = ("cuadro", "respuesta", "texto", "ocupado", "fuentes")
#: De qué puede avisar la extensión: un selector, o que el editor no aceptó el texto insertado.
SelectorQueFalla = Literal["cuadro", "respuesta", "texto", "ocupado", "fuentes", "insercion"]


class AdaptadorDelAsistente(BaseModel):
    asistente: str
    nombre: str
    origen: str
    version: int
    selectores: dict[str, str]


class EstadoDelAdaptador(AdaptadorDelAsistente):
    actualizado_en: datetime
    fallos_de_la_version: int
    ultimo_fallo_en: datetime | None
    ultimo_fallo_selector: str | None
    #: Hay fallos de la versión vigente. Lo calcula el servidor: la pantalla sólo lo pinta.
    rota: bool


class CambioDelAdaptador(BaseModel):
    selectores: dict[str, str]

    model_config = {"extra": "forbid"}

    @field_validator("selectores")
    @classmethod
    def _completos(cls, valor: dict[str, str]) -> dict[str, str]:
        faltan = [k for k in SELECTORES_DEL_ADAPTADOR if not (valor.get(k) or "").strip()]
        if faltan:
            raise ValueError(f"faltan selectores: {', '.join(faltan)}")
        return {k: valor[k].strip() for k in SELECTORES_DEL_ADAPTADOR}


class FalloDelAdaptador(BaseModel):
    version: int
    selector: SelectorQueFalla

    model_config = {"extra": "forbid"}


def _estado(a: HubAsistenteAdaptador) -> EstadoDelAdaptador:
    return EstadoDelAdaptador(
        asistente=a.asistente,
        nombre=a.nombre,
        origen=a.origen,
        version=a.version,
        selectores=a.selectores,
        actualizado_en=a.actualizado_en,
        fallos_de_la_version=a.fallos_de_la_version,
        ultimo_fallo_en=a.ultimo_fallo_en,
        ultimo_fallo_selector=a.ultimo_fallo_selector,
        rota=a.fallos_de_la_version > 0,
    )


async def _el_adaptador(session: AsyncSession, asistente: str, *, bloquear: bool = False) -> HubAsistenteAdaptador:
    consulta = select(HubAsistenteAdaptador).where(HubAsistenteAdaptador.asistente == asistente)
    if bloquear:
        consulta = consulta.with_for_update()
    adaptador = (await session.execute(consulta)).scalar_one_or_none()
    if adaptador is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asistente no encontrado")
    return adaptador


@router_catalogo.get("/asistentes/{asistente}/adaptador", response_model=AdaptadorDelAsistente)
async def adaptador_del_asistente(
    asistente: str,
    _user: UserInfo = Depends(require_scopes(AGENTES_CONSULTA)),
    session: AsyncSession = Depends(get_session),
) -> AdaptadorDelAsistente:
    """Los selectores vigentes, para la extensión. Con el token de consulta, como el catálogo."""
    a = await _el_adaptador(session, asistente)
    return AdaptadorDelAsistente(
        asistente=a.asistente, nombre=a.nombre, origen=a.origen, version=a.version, selectores=a.selectores
    )


@router_catalogo.post("/asistentes/{asistente}/fallos", status_code=status.HTTP_204_NO_CONTENT)
async def avisar_de_un_fallo(
    asistente: str,
    body: FalloDelAdaptador,
    _user: UserInfo = Depends(require_scopes(AGENTES_CONSULTA)),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """La extensión avisa de que un selector dejó de casar. **Sólo metadatos**: qué selector y de
    qué versión, nunca la página. El de una versión que ya no es la vigente no cuenta: ya se
    corrigió."""
    a = await _el_adaptador(session, asistente, bloquear=True)
    if body.version == a.version:
        a.fallos_de_la_version += 1
        a.ultimo_fallo_en = datetime.now(timezone.utc)
        a.ultimo_fallo_selector = body.selector
        await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router_catalogo.get("/asistentes", response_model=list[EstadoDelAdaptador])
async def estado_de_los_adaptadores(
    _user: UserInfo = Depends(require_superadmin),
    session: AsyncSession = Depends(get_session),
) -> list[EstadoDelAdaptador]:
    """Si la integración con cada asistente funciona, para quien la mantiene."""
    filas = (await session.execute(select(HubAsistenteAdaptador).order_by(HubAsistenteAdaptador.asistente))).scalars()
    return [_estado(a) for a in filas]


@router_catalogo.put("/asistentes/{asistente}/adaptador", response_model=EstadoDelAdaptador)
async def cambiar_el_adaptador(
    asistente: str,
    body: CambioDelAdaptador,
    user: UserInfo = Depends(require_superadmin),
    _sesion: UserInfo = Depends(require_sesion_humana()),
    session: AsyncSession = Depends(get_session),
) -> EstadoDelAdaptador:
    """Corrige los selectores: una versión nueva, con los fallos a cero. Todas las extensiones la
    toman la próxima vez que la piden, sin publicar nada."""
    a = await _el_adaptador(session, asistente, bloquear=True)
    a.selectores = body.selectores
    a.version += 1
    a.fallos_de_la_version = 0
    a.ultimo_fallo_en = None
    a.ultimo_fallo_selector = None
    a.actualizado_en = datetime.now(timezone.utc)
    a.actualizado_por = user.user_id
    await session.commit()
    await session.refresh(a)
    return _estado(a)


# =============================================================================
#  Las conversaciones (#216)
# =============================================================================


class CambioDelRegistro(BaseModel):
    modo: Literal["validacion", "incidencias"]

    model_config = {"extra": "forbid"}


@router.post("/{agente_id}/registro", response_model=AgenteView)
async def cambiar_registro(
    agente_id: uuid.UUID,
    body: CambioDelRegistro,
    user: UserInfo = Depends(require_sesion_humana()),
    session: AsyncSession = Depends(get_session),
) -> AgenteView:
    """Qué se guarda de sus conversaciones: todo (`validacion`) o sólo lo informado
    (`incidencias`). Lo deciden quien lo publica y quien lo revisa. No versiona: no cambia lo que
    se ofrece."""
    agente, version = await _el_agente(session, agente_id, user)
    _exigir("cambiar_registro", agente, version, user)
    agente.modo_registro = body.modo
    agente.updated_at = datetime.now(timezone.utc)
    return await _responder(session, agente, version, user)


class RespuestaLeida(BaseModel):
    """Lo que la extensión leyó en el asistente, o por qué no pudo leerlo. Una de las dos."""

    texto: str | None = Field(default=None, min_length=1, max_length=100_000)
    fuentes: list[str] = Field(default_factory=list, max_length=50)
    no_capturada: Literal["sin_respuesta", "sin_terminar", "selector", "copiado"] | None = None

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _una_de_las_dos(self) -> "RespuestaLeida":
        if (self.texto is None) == (self.no_capturada is None):
            raise ValueError("o la respuesta, o por qué no se pudo leer")
        return self


class Valoracion(BaseModel):
    """1 o -1. **-1 es un informe**, y lleva motivo. En `incidencias` el informe trae la pregunta
    y la respuesta, que la consulta no guardó."""

    puntuacion: Literal[1, -1]
    motivo: str | None = None
    comentario: str | None = Field(default=None, max_length=4000)
    pregunta: str | None = Field(default=None, max_length=2000)
    respuesta: str | None = Field(default=None, max_length=100_000)

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _el_informe_lleva_motivo(self) -> "Valoracion":
        if self.puntuacion == -1 and self.motivo not in registro.MOTIVOS:
            raise ValueError(f"un informe lleva uno de estos motivos: {', '.join(registro.MOTIVOS)}")
        if self.puntuacion == 1 and self.motivo is not None:
            raise ValueError("una valoración buena no lleva motivo")
        return self


class MotivoDeInforme(BaseModel):
    codigo: str
    etiqueta: str


async def _la_consulta(session: AsyncSession, consulta_id: uuid.UUID, user: UserInfo) -> HubAgenteConsulta:
    """La consulta de **quien pregunta**: la de otra persona no existe para él (404)."""
    fila = (
        await session.execute(
            select(HubAgenteConsulta)
            .where(HubAgenteConsulta.id == consulta_id, HubAgenteConsulta.actor == user.user_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if fila is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Consulta no encontrada")
    return fila


@router_catalogo.post("/consultas/{consulta_id}/respuesta", status_code=status.HTTP_204_NO_CONTENT)
async def guardar_respuesta(
    consulta_id: uuid.UUID,
    body: RespuestaLeida,
    user: UserInfo = Depends(require_scopes(AGENTES_CONSULTA)),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """La respuesta que la extensión leyó en el asistente, en un agente en validación. Una vez: la
    conversación es la que fue. En incidencias no se manda la de cada consulta, sólo un informe."""
    fila = await _la_consulta(session, consulta_id, user)
    if fila.modo != "validacion":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Este agente sólo guarda lo que se informa: la respuesta va con el informe.",
        )
    if fila.respuesta is not None or fila.respuesta_no_capturada is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="La respuesta ya está guardada.")
    fila.respuesta = body.texto
    fila.fuentes = body.fuentes if body.texto is not None else None
    fila.respuesta_no_capturada = body.no_capturada
    fila.respuesta_en = datetime.now(timezone.utc)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router_catalogo.post("/consultas/{consulta_id}/valoracion", status_code=status.HTTP_204_NO_CONTENT)
async def valorar(
    consulta_id: uuid.UUID,
    body: Valoracion,
    user: UserInfo = Depends(require_scopes(AGENTES_CONSULTA)),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """👍 o 👎 sobre la respuesta de su consulta; 👎 con motivo es un informe. Se puede cambiar.

    En incidencias, el informe es lo único que se guarda, y por eso trae la pregunta y la respuesta;
    una valoración buena guarda la puntuación y nada más. En validación ya estaban: no se pisan."""
    fila = await _la_consulta(session, consulta_id, user)
    fila.puntuacion = body.puntuacion
    fila.motivo = body.motivo
    fila.comentario = (body.comentario or "").strip() or None
    fila.valorada_en = datetime.now(timezone.utc)
    if fila.modo == "incidencias":
        # En incidencias sólo se guarda lo informado como inadecuado: si deja de serlo, se borra.
        fila.pregunta = body.pregunta if body.puntuacion == -1 else None
        fila.respuesta = body.respuesta if body.puntuacion == -1 else None
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router_catalogo.get("/motivos-de-informe", response_model=list[MotivoDeInforme])
async def motivos_de_informe(
    lengua: Literal["es", "ca", "en"] = "es",
    _user: UserInfo = Depends(require_scopes(AGENTES_CONSULTA)),
) -> list[MotivoDeInforme]:
    """Los motivos de un informe, con su etiqueta: la extensión los pinta, no los conoce."""
    return [MotivoDeInforme(codigo=c, etiqueta=e[lengua]) for c, e in registro.MOTIVOS.items()]


# =============================================================================
#  La calidad (#217)
# =============================================================================


class DocumentoOfrecidoEnLaConsulta(BaseModel):
    url: str
    #: El de la ficha del índice ahora; vacío si la ficha ya no existe.
    titulo: str | None
    score: float


class ConversacionDelAgente(BaseModel):
    """Una consulta con lo que se guardó de ella. **Sin quién preguntó**: para corregir el agente
    no hace falta, y no se enseña."""

    id: uuid.UUID
    #: #225 — si es una ampliación, la consulta con que empezó la conversación.
    consulta_madre_id: uuid.UUID | None = None
    ocurrido_en: datetime
    version: int
    modo: str
    pregunta: str | None
    datos: dict[str, str] | None
    documentos: list[DocumentoOfrecidoEnLaConsulta]
    respuesta: str | None
    respuesta_no_capturada: str | None
    fuentes: list[str] | None
    puntuacion: int | None
    motivo: str | None
    comentario: str | None
    #: Dónde mirar primero, según el motivo. La calcula el servidor; nula si no apunta a nada.
    pista: Literal["almacen", "indice", "prompt", "seleccion"] | None
    veredicto: Literal["good", "bad", "mixed"] | None
    nota_revision: str | None
    revisada_en: datetime | None


class RevisionDeLaConversacion(BaseModel):
    veredicto: Literal["good", "bad", "mixed"]
    nota: str | None = Field(default=None, max_length=4000)

    model_config = {"extra": "forbid"}


def _conversacion(fila: HubAgenteConsulta, titulos: dict[str, str]) -> ConversacionDelAgente:
    return ConversacionDelAgente(
        id=fila.id,
        consulta_madre_id=fila.consulta_madre_id,
        ocurrido_en=fila.ocurrido_en,
        version=fila.version,
        modo=fila.modo,
        pregunta=fila.pregunta,
        datos=fila.datos,
        documentos=[
            DocumentoOfrecidoEnLaConsulta(url=d["url"], titulo=titulos.get(d["url"]), score=d["score"])
            for d in (fila.documentos or [])
        ],
        respuesta=fila.respuesta,
        respuesta_no_capturada=fila.respuesta_no_capturada,
        fuentes=fila.fuentes,
        puntuacion=fila.puntuacion,
        motivo=fila.motivo,
        comentario=fila.comentario,
        pista=registro.PISTAS.get(fila.motivo or ""),
        veredicto=fila.veredicto,
        nota_revision=fila.nota_revision,
        revisada_en=fila.revisada_en,
    )


@router.get("/{agente_id}/conversaciones", response_model=list[ConversacionDelAgente])
async def conversaciones(
    agente_id: uuid.UUID,
    modo: Literal["validacion", "incidencias"] | None = None,
    # Entero y no `Literal[1, -1]`: en la consulta de la URL llega como texto, y el literal
    # rechazaba el «-1» (la misma trampa que el «3» de un formulario, ver la memoria del proyecto).
    puntuacion: int | None = Query(default=None, ge=-1, le=1),
    motivo: str | None = None,
    sin_revisar: bool = False,
    limite: int = Query(default=50, ge=1, le=200),
    user: UserInfo = Depends(require_sesion_humana()),
    session: AsyncSession = Depends(get_session),
) -> list[ConversacionDelAgente]:
    """Las conversaciones y los informes de un agente, de lo más reciente a lo más antiguo. Para
    quien lo publicó y quien lo revisa: es lo que permite ver dónde está el fallo."""
    agente, version = await _el_agente(session, agente_id, user)
    _exigir("ver_calidad", agente, version, user)
    consulta_sql = select(HubAgenteConsulta).where(HubAgenteConsulta.agente_id == agente.id)
    if modo:
        consulta_sql = consulta_sql.where(HubAgenteConsulta.modo == modo)
    if puntuacion == 0:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="la valoración es 1 o -1")
    if puntuacion is not None:
        consulta_sql = consulta_sql.where(HubAgenteConsulta.puntuacion == puntuacion)
    if motivo:
        consulta_sql = consulta_sql.where(HubAgenteConsulta.motivo == motivo)
    if sin_revisar:
        consulta_sql = consulta_sql.where(HubAgenteConsulta.veredicto.is_(None))
    filas = (
        await session.execute(consulta_sql.order_by(HubAgenteConsulta.ocurrido_en.desc()).limit(limite))
    ).scalars().all()
    urls = {d["url"] for f in filas for d in (f.documentos or [])}
    titulos = (
        dict(
            (
                await session.execute(
                    select(HubAgenteFicha.url, HubAgenteFicha.titulo).where(
                        HubAgenteFicha.agente_id == agente.id, HubAgenteFicha.url.in_(urls)
                    )
                )
            ).all()
        )
        if urls
        else {}
    )
    return [_conversacion(f, titulos) for f in filas]


@router.put("/consultas/{consulta_id}/revision", response_model=ConversacionDelAgente)
async def revisar_conversacion(
    consulta_id: uuid.UUID,
    body: RevisionDeLaConversacion,
    user: UserInfo = Depends(require_sesion_humana()),
    session: AsyncSession = Depends(get_session),
) -> ConversacionDelAgente:
    """El veredicto sobre una conversación, como en la revisión de los chatbots. Se puede cambiar."""
    fila = (
        await session.execute(select(HubAgenteConsulta).where(HubAgenteConsulta.id == consulta_id))
    ).scalar_one_or_none()
    if fila is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Consulta no encontrada")
    agente, version = await _el_agente(session, fila.agente_id, user)
    _exigir("ver_calidad", agente, version, user)
    fila.veredicto = body.veredicto
    fila.nota_revision = (body.nota or "").strip() or None
    fila.revisada_por = user.user_id
    fila.revisada_en = datetime.now(timezone.utc)
    await session.flush()
    vista = _conversacion(fila, {})
    await session.commit()
    return vista
