"""El catálogo de funciones y su revisión posterior (FUN.4).

Deploy: edge — el código y la declaración de una función son de la organización.
Módulo: automatizacion — desde el 2026-10-05; antes, `informes`. Las plantillas de informe
usan las funciones por dentro, al ejecutar el workspace, así que no necesitan este módulo.

**Lo que esta superficie hace cumplir**, y que no se puede deducir leyendo los endpoints uno a
uno:

* La cola de revisión y el uso **no se estorban**: una versión recién registrada aparece en
  `sin_revisar` y se está ejecutando a la vez. Es el nivel 2 de la Instrucció 02/2026.
* `muestra=N` devuelve N **al azar** entre las no revisadas: el muestreo de §8.4 existe para que
  revisar no exija leerlo todo.
* `acciones_permitidas` viaja en cada DTO y la calcula el servidor (regla maestra 2). La pantalla
  itera; no decide.
* La frontera: una organización ve las suyas y las publicadas, **nunca las no publicadas de
  otra**, y sólo la autora versiona.

Lo que lee y escribe la base está en `modules/redaccion/funciones_catalogo.py` (#274).
"""
from __future__ import annotations

import logging

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.api.deps import (
    get_current_user,
    get_session,
    require_alguno_de,
    require_module,
    require_scopes,
)
from server.app.core.auth.models import UserInfo
from server.app.core.auth.pat.scopes import FUNCIONES_EXECUTE, FUNCIONES_REGISTER
from server.app.core.auth.tenancy import organizacion_unica_de
from server.app.modules.redaccion import funciones_catalogo as catalogo
from server.app.modules.redaccion.database.models import HubFuncion, HubFuncionVersion
from server.app.modules.redaccion.funciones_acciones import (
    PromocionInvalida,
    RevisionInvalida,
    acciones_permitidas,
    aplicar_revision,
    candidata_a_nivel_3,
    fuera_de_plazo,
    muestra_para_revisar,
    plazo_de_revision_en_dias,
    promover,
    reactivar,
    suspender,
)
from server.app.modules.redaccion.funciones_service import FuncionIncoherente
from server.app.routers.redaccion._actor import user_to_uuid

_log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/funciones",
    tags=["funciones"],
    dependencies=[Depends(require_module("automatizacion"))],
)


# ──────────────────────────── DTOs ────────────────────────────


class VersionView(BaseModel):
    """Una versión, con su estado, su declaración y su revisión."""

    version: int
    estado: str
    autoria: str | None
    finalidad: str | None
    categorias_datos: list[str] = Field(default_factory=list)
    #: Los hallazgos del auditor, incluidos los `WARNING` que **no** bloquearon: es lo que la
    #: revisión posterior tiene que poder leer.
    hallazgos: list[dict[str, Any]] = Field(default_factory=list)
    revisada_en: Any = None
    revision_resultado: str | None = None
    revision_nota: str | None = None
    motivo_suspension: str | None = None
    code_sha256: str
    version_paquete: str | None = None
    #: AUT.3 — dónde corre, en las de origen externo. Nulo en las otras dos: ahí la respuesta
    #: está en el código (sandbox o proceso) y no hace falta declararla.
    entorno_ejecucion: str | None = None
    created_at: Any = None
    #: FUN.4 — lo que quien pregunta puede pedir sobre **esta** versión.
    acciones_permitidas: list[str] = Field(default_factory=list)


class FuncionView(BaseModel):
    id: uuid.UUID
    nombre: str
    descripcion: str
    organizacion_id: uuid.UUID | None
    origen: str
    #: Derivado, no guardado: 2 es «de mi organización y sin publicar», 3 es «publicada» o «de
    #: paquete».
    nivel: int
    entry_point: str | None = None
    #: FUN.5 — de qué paquete pip viene, para las de origen `paquete`. Se deriva del
    #: `entry_point` («distribución:nombre») y no se guarda aparte: sería el mismo hecho en dos
    #: sitios, y el segundo se quedaría viejo.
    distribucion: str | None = None
    #: La versión semver **instalada** de la que está en servicio, que puede no ser la anclada
    #: por una plantilla. Quien mira el catálogo necesita ver ésta, no el ordinal interno.
    version_paquete_instalada: str | None = None
    publicada_en: Any = None
    valoracion_promocion: str | None = None
    #: FUN.4 — **señal**, no decisión: la Instrucció deja la valoración a personas.
    candidata_nivel_3: bool = False
    motivos_nivel_3: list[str] = Field(default_factory=list)
    versiones: list[VersionView] = Field(default_factory=list)


class VersionEnRevision(BaseModel):
    """Una fila de la cola de revisión posterior."""

    funcion_id: uuid.UUID
    funcion_nombre: str
    version: int
    estado: str
    autoria: str | None
    finalidad: str | None
    categorias_datos: list[str] = Field(default_factory=list)
    hallazgos: list[dict[str, Any]] = Field(default_factory=list)
    #: Cuántas plantillas la referencian. Es lo que dice si revisarla es urgente.
    plantillas_que_la_usan: int = 0
    dias_desde_el_registro: int = 0
    #: AUT.12 — el plazo vigente en este despliegue y si esta versión ya lo pasó. **Los dos
    #: campos y no sólo el segundo**: quien ve «fuera de plazo» sin saber cuál es el plazo no
    #: puede juzgar si la cola va mal o el plazo es corto.
    plazo_en_dias: int = 0
    fuera_de_plazo: bool = False
    acciones_permitidas: list[str] = Field(default_factory=list)


class RevisarRequest(BaseModel):
    resultado: Literal["conforme", "correcciones", "reclasificada", "suspendida"]
    nota: str | None = None


class SuspenderRequest(BaseModel):
    motivo: str


class SolicitarPromocionRequest(BaseModel):
    motivo: str


class PromoverRequest(BaseModel):
    valoracion: str


# ──────────────────────────── Helpers ────────────────────────────


def _hallazgos_de(version: HubFuncionVersion) -> list[dict[str, Any]]:
    """Los hallazgos del auditor de esa versión, o ninguno si es de paquete."""
    auditoria = version.audit_result_json or {}
    hallazgos = auditoria.get("findings") or []
    return [h for h in hallazgos if isinstance(h, dict)]


def _exigir(accion: str, funcion: Any, version: Any, principal: UserInfo) -> None:
    """La autorización se lee de la **misma** función que llena el DTO.

    Es lo que hace cierto que «si el botón aparece, el endpoint no responde 403»: no hay dos
    listas que puedan discrepar.
    """
    if accion not in acciones_permitidas(funcion, version, principal=principal):
        raise HTTPException(
            status_code=403,
            detail=f"No puedes «{accion}» sobre esta versión",
        )


# La vista se construye **antes** del `commit`, no después: el porqué, en
# `funciones_catalogo.guardar`, que es quien confirma.


def _vista_de_version(
    funcion: HubFuncion, version: HubFuncionVersion, principal: UserInfo
) -> VersionView:
    return VersionView(
        version=version.version,
        estado=version.estado,
        autoria=version.autoria,
        finalidad=version.finalidad,
        categorias_datos=list(version.categorias_datos or []),
        hallazgos=_hallazgos_de(version),
        revisada_en=version.revisada_en,
        revision_resultado=version.revision_resultado,
        revision_nota=version.revision_nota,
        motivo_suspension=version.motivo_suspension,
        code_sha256=version.code_sha256,
        version_paquete=version.version_paquete,
        entorno_ejecucion=version.entorno_ejecucion,
        created_at=version.created_at,
        acciones_permitidas=acciones_permitidas(funcion, version, principal=principal),
    )


def _vista_de_funcion(
    funcion: HubFuncion, versiones: list[HubFuncionVersion], principal: UserInfo
) -> FuncionView:
    candidata, motivos = candidata_a_nivel_3(funcion, versiones)
    instalada = next(
        (v for v in versiones if v.estado == "registrada" and v.version_paquete), None
    )
    return FuncionView(
        id=funcion.id,
        nombre=funcion.nombre,
        descripcion=funcion.descripcion,
        organizacion_id=funcion.organizacion_id,
        origen=funcion.origen,
        nivel=funcion.nivel,
        entry_point=funcion.entry_point,
        distribucion=(funcion.entry_point or "").split(":")[0] or None
        if funcion.origen == "paquete"
        else None,
        version_paquete_instalada=instalada.version_paquete if instalada else None,
        publicada_en=funcion.publicada_en,
        valoracion_promocion=funcion.valoracion_promocion,
        candidata_nivel_3=candidata,
        motivos_nivel_3=motivos,
        versiones=[_vista_de_version(funcion, v, principal) for v in versiones],
    )


class RegistrarExternaRequest(BaseModel):
    """Lo que hay que declarar para registrar un cuaderno que se ejecuta fuera (AUT.3)."""

    nombre: str = Field(min_length=1, max_length=120)
    #: El fichero entero, `.ipynb` o `.py`. Su hash es la versión.
    fichero: str = Field(min_length=1)
    finalidad: str = Field(min_length=1)
    categorias_datos: list[str] = Field(min_length=1)
    #: Dónde corre: «un cuaderno en Colab», «el equipo de la persona», «el servidor del
    #: servicio». Texto libre a propósito: es una declaración de quien responde, no una
    #: taxonomía que la plataforma pueda comprobar — no ve ese entorno.
    entorno_ejecucion: str = Field(min_length=1)
    #: `persona` | `ia`. Igual que en autoservicio: no hay ninguna rama según quién escribió, se
    #: guarda porque la revisión posterior quiere verlo.
    #:
    #: `Literal` y no `str`: el comentario prometía dos valores y el tipo aceptaba cualquiera,
    #: así que una cadena de más de 20 caracteres no fallaba como 422 de contrato sino como 500
    #: al escribir en la columna. Lo que el docstring promete, lo exige el tipo.
    autoria: Literal["persona", "ia"] = "persona"
    #: Para registrar una versión más de una función externa que ya existe.
    funcion_id: uuid.UUID | None = None


def _auditoria_informativa(fichero: str) -> dict[str, Any]:
    """El auditor sobre el fichero, **sin puerta** (AUT.3).

    El resultado se guarda y llega a la cola de revisión; no decide si se registra. Un programa
    que corre fuera usa red y disco legítimamente, así que bloquear por eso sería exigirle las
    reglas del sandbox a algo que no va a entrar en él —y, además, aprobación previa por la
    puerta de atrás, que es lo que la Instrucció prohíbe en el nivel 2.

    **Que el auditor no pueda mirar no se disfraza de «no hay hallazgos»**: se anota. Es la
    diferencia entre «miré y está limpio» y «no pude mirar», y confundirlas es como un medidor
    informa de cero en verde.
    """
    from server.app.modules.redaccion.services.cuaderno import codigo_de_cuaderno
    from server.app.modules.redaccion.services.script_auditor import (
        ScriptSecurityAuditor,
    )

    codigo = codigo_de_cuaderno(fichero)
    if codigo is None:
        return {
            "perfil": "informativo",
            "no_se_pudo_auditar": "el fichero no trae código legible como Python",
            "findings": [],
        }

    try:
        resultado = ScriptSecurityAuditor().audit(codigo).model_dump(mode="json")
    except Exception:  # noqa: BLE001 — se registra con traza: `_log.exception`
        # El registro no depende de la auditoría —es informativa—, así que no se rechaza; pero el
        # fallo se registra con traza y el cliente no recibe el texto de la excepción (#276).
        _log.exception("El auditor de scripts falló sobre una función externa")
        return {
            "perfil": "informativo",
            "no_se_pudo_auditar": "el auditor falló; el motivo está en el registro del servidor",
            "findings": [],
        }

    # `approved` no aplica: aquí no hubo ninguna puerta que aprobara o rechazara, y dejarlo
    # haría creer lo contrario a quien lea la ficha o la cola de revisión.
    resultado.pop("approved", None)
    resultado["perfil"] = "informativo"
    return resultado


@router.post(
    "/externas",
    response_model=FuncionView,
    status_code=201,
    operation_id="registrarFuncionExterna",
)
async def registrar_funcion_externa(
    body: RegistrarExternaRequest,
    # #236 — también con un token: es el agente de código que acaba de escribir el cuaderno.
    principal: UserInfo = Depends(require_scopes(FUNCIONES_REGISTER)),
    session: AsyncSession = Depends(get_session),
) -> FuncionView:
    """Registra un cuaderno o script que se ejecuta **fuera** de la plataforma (AUT.3).

    **El problema que resuelve es de registro, no de ejecución.** Una organización que trabaja
    con cuadernos escritos por agentes de código no sabe cuáles circulan, quién los usa ni de qué
    versión. Las normas de desarrollo ciudadano exigen registrar antes de compartir y prohíben la
    distribución informal; hasta aquí el catálogo sólo admitía lo que él mismo ejecuta o lo que
    llega por punto de entrada, así que un cuaderno no tenía dónde registrarse.

    **Y registrarlo sin ejecutarlo respeta la soberanía local** que esas normas suelen fijar: el
    código sigue corriendo donde corría, con las credenciales de quien lo usa. La plataforma no
    toca el dato; sabe que el cuaderno existe, de qué versión, para qué se declaró y quién
    responde de él.

    Entra en la **misma cola de revisión** que las demás y con los mismos resultados. Lo que hay
    que decir sin adornos es que **suspender una función externa es un aviso**: la plataforma
    puede marcarla y dejar de recomendarla, y no puede impedir que alguien la ejecute fuera.
    """
    from server.app.modules.redaccion.contracts.funciones import ContratoFuncion
    from server.app.modules.redaccion.funciones_service import registrar_version

    quien = user_to_uuid(principal.user_id)

    try:
        contrato = ContratoFuncion(
            slots=[],
            parametros=[],
            finalidad=body.finalidad,
            categorias_datos=list(body.categorias_datos),
        )
    except Exception as fallo:  # se traduce a 422 con su motivo
        raise HTTPException(
            status_code=422,
            detail={"code": "DECLARACION_INCOMPLETA", "message": str(fallo)},
        ) from fallo

    organizacion = organizacion_unica_de(principal)

    # **Versionar una función existente se autoriza antes de tocarla.** `registrar_version` sólo
    # hace un `session.get`, así que sin esto un `funcion_id` de otra organización colaba una
    # versión en su catálogo — y, peor, permitía añadir código auditado **de forma informativa**
    # a una función de autoservicio, que sí se ejecuta en el sandbox. Las dos cosas las encontró
    # la revisión de la PR #189.
    if body.funcion_id is not None:
        await catalogo.destino_de_una_version_externa(
            session, body.funcion_id, organizacion, principal
        )

    try:
        funcion, _version = await registrar_version(
            session,
            nombre=body.nombre,
            organizacion_id=organizacion,
            code=body.fichero,
            contrato=contrato,
            declarada_por=quien,
            audit_result=_auditoria_informativa(body.fichero),
            autoria=body.autoria,
            funcion_id=body.funcion_id,
            origen="externa",
            entorno_ejecucion=body.entorno_ejecucion,
        )
    except FuncionIncoherente as fallo:
        raise HTTPException(
            status_code=422,
            detail={"code": "FUNCION_INCOHERENTE", "message": str(fallo)},
        ) from fallo

    funcion = await catalogo.confirmar_registro(session, funcion)
    versiones = await catalogo.versiones_de(session, funcion.id)
    return _vista_de_funcion(funcion, versiones, principal)


# ──────────────────────────── El catálogo ────────────────────────────


@router.get("", response_model=list[FuncionView], operation_id="listarFunciones")
async def listar_funciones(
    # #236 — quien registra, para no duplicar; quien ejecuta, para saber el `funcion_id`.
    principal: UserInfo = Depends(require_alguno_de(FUNCIONES_REGISTER, FUNCIONES_EXECUTE)),
    session: AsyncSession = Depends(get_session),
) -> list[FuncionView]:
    """El catálogo que ve quien pregunta: las suyas y las publicadas.

    Nunca las no publicadas de otra organización — eso lo decide `consulta_de_catalogo`, que es
    la misma frontera que usa el resolutor, escrita una sola vez.
    """
    return [
        _vista_de_funcion(funcion, await catalogo.versiones_de(session, funcion.id), principal)
        for funcion in await catalogo.catalogo(session, principal)
    ]


@router.get(
    "/revision", response_model=list[VersionEnRevision], operation_id="colaDeRevision"
)
async def cola_de_revision(
    estado: Literal["sin_revisar", "todas"] = Query(default="sin_revisar"),
    muestra: int | None = Query(default=None, ge=1, le=100),
    principal: UserInfo = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[VersionEnRevision]:
    """La cola de la revisión posterior (§8.4), con muestreo.

    **Estar en la cola no impide usar la versión**: eso es lo que distingue una revisión
    posterior de una aprobación previa, y es lo que la Instrucció exige en el nivel 2.
    """
    por_funcion, versiones = await catalogo.en_revision(session, principal)
    if not por_funcion:
        return []

    candidatas = list(versiones)
    if estado == "sin_revisar":
        candidatas = [v for v in candidatas if v.revisada_por is None]
    if muestra is not None:
        candidatas = muestra_para_revisar(candidatas, cuantas=muestra)

    ahora = datetime.now(timezone.utc)
    # Se lee **una vez** por petición y no por fila: es una variable de entorno, y leerla en
    # cada versión haría que una misma cola pudiera pintarse con dos plazos distintos.
    plazo = plazo_de_revision_en_dias()
    filas = []
    for version in candidatas:
        funcion = por_funcion[version.funcion_id]
        creada = version.created_at or ahora
        filas.append(
            VersionEnRevision(
                funcion_id=funcion.id,
                funcion_nombre=funcion.nombre,
                version=version.version,
                estado=version.estado,
                autoria=version.autoria,
                finalidad=version.finalidad,
                categorias_datos=list(version.categorias_datos or []),
                hallazgos=_hallazgos_de(version),
                plantillas_que_la_usan=await catalogo.cuantas_plantillas_la_usan(
                    session, funcion.id, version.version
                ),
                dias_desde_el_registro=(dias := max((ahora - creada).days, 0)),
                plazo_en_dias=plazo,
                # Sólo lo pendiente puede ir tarde (issue #200): el plazo es el de **revisar**, y
                # una revisada ya lo cumplió. Con `estado=todas` entran las dos.
                fuera_de_plazo=(
                    version.revisada_por is None and fuera_de_plazo(dias, plazo=plazo)
                ),
                acciones_permitidas=acciones_permitidas(
                    funcion, version, principal=principal
                ),
            )
        )
    return filas


@router.get(
    "/{funcion_id}", response_model=FuncionView, operation_id="verFuncion"
)
async def ver_funcion(
    funcion_id: uuid.UUID,
    principal: UserInfo = Depends(require_alguno_de(FUNCIONES_REGISTER, FUNCIONES_EXECUTE)),
    session: AsyncSession = Depends(get_session),
) -> FuncionView:
    """La ficha: el contrato legible, la declaración, los hallazgos y las versiones."""
    funcion = await catalogo.funcion_visible(session, funcion_id, principal)
    return _vista_de_funcion(funcion, await catalogo.versiones_de(session, funcion_id), principal)


# ──────────────────────────── Revisión posterior ────────────────────────────


@router.post(
    "/{funcion_id}/versiones/{numero}/revisar",
    response_model=VersionView,
    operation_id="revisarVersion",
)
async def revisar_version(
    funcion_id: uuid.UUID,
    numero: int,
    body: RevisarRequest,
    principal: UserInfo = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> VersionView:
    """Sella la revisión posterior. `correcciones` y `reclasificada` **no** cambian el estado."""
    funcion = await catalogo.funcion_visible(session, funcion_id, principal)
    version = await catalogo.version_de(session, funcion_id, numero)
    _exigir("revisar", funcion, version, principal)

    try:
        aplicar_revision(
            version,
            resultado=body.resultado,
            nota=body.nota,
            revisada_por=user_to_uuid(principal.user_id),
        )
    except (RevisionInvalida, FuncionIncoherente) as fallo:
        raise HTTPException(status_code=422, detail=str(fallo)) from fallo

    return await catalogo.guardar(session, lambda: _vista_de_version(funcion, version, principal))


@router.post(
    "/{funcion_id}/versiones/{numero}/suspender",
    response_model=VersionView,
    operation_id="suspenderVersion",
)
async def suspender_version(
    funcion_id: uuid.UUID,
    numero: int,
    body: SuspenderRequest,
    principal: UserInfo = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> VersionView:
    """Deja de ejecutarse. El bloque anclado falla en alto **con este motivo** (FUN.3)."""
    funcion = await catalogo.funcion_visible(session, funcion_id, principal)
    version = await catalogo.version_de(session, funcion_id, numero)
    _exigir("suspender", funcion, version, principal)

    try:
        suspender(
            version, motivo=body.motivo, suspendida_por=user_to_uuid(principal.user_id)
        )
    except FuncionIncoherente as fallo:
        raise HTTPException(status_code=422, detail=str(fallo)) from fallo

    return await catalogo.guardar(session, lambda: _vista_de_version(funcion, version, principal))


@router.post(
    "/{funcion_id}/versiones/{numero}/reactivar",
    response_model=VersionView,
    operation_id="reactivarVersion",
)
async def reactivar_version(
    funcion_id: uuid.UUID,
    numero: int,
    principal: UserInfo = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> VersionView:
    """Vuelve a `registrada`. **No lo puede hacer la autora** si lo suspendió otra persona."""
    funcion = await catalogo.funcion_visible(session, funcion_id, principal)
    version = await catalogo.version_de(session, funcion_id, numero)
    _exigir("reactivar", funcion, version, principal)

    reactivar(version)
    return await catalogo.guardar(session, lambda: _vista_de_version(funcion, version, principal))


@router.post(
    "/{funcion_id}/versiones/{numero}/retirar",
    response_model=VersionView,
    operation_id="retirarVersion",
)
async def retirar_version(
    funcion_id: uuid.UUID,
    numero: int,
    principal: UserInfo = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> VersionView:
    """Retirar es de quien escribe. Es terminal: el estado no vuelve."""
    funcion = await catalogo.funcion_visible(session, funcion_id, principal)
    version = await catalogo.version_de(session, funcion_id, numero)
    _exigir("retirar", funcion, version, principal)

    version.estado = "retirada"
    return await catalogo.guardar(session, lambda: _vista_de_version(funcion, version, principal))


# ──────────────────────────── Paso a nivel 3 ────────────────────────────


@router.post(
    "/{funcion_id}/solicitar-promocion",
    response_model=FuncionView,
    operation_id="solicitarPromocionDeFuncion",
)
async def solicitar_promocion(
    funcion_id: uuid.UUID,
    body: SolicitarPromocionRequest,
    principal: UserInfo = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> FuncionView:
    """La organización autora pide que su función pase a plataforma, con motivo."""
    funcion = await catalogo.funcion_visible(session, funcion_id, principal)
    versiones = await catalogo.versiones_de(session, funcion_id)
    _exigir(
        "solicitar_promocion",
        funcion,
        versiones[0] if versiones else None,
        principal,
    )

    if not body.motivo.strip():
        raise HTTPException(
            status_code=422, detail="Solicitar la promoción exige un motivo escrito"
        )

    funcion.promocion_solicitada_por = user_to_uuid(principal.user_id)
    funcion.promocion_solicitada_en = datetime.now(timezone.utc)
    funcion.motivo_promocion = body.motivo.strip()
    return await catalogo.guardar(session, lambda: _vista_de_funcion(funcion, versiones, principal))


@router.post(
    "/{funcion_id}/promover",
    response_model=FuncionView,
    operation_id="promoverFuncion",
)
async def promover_funcion(
    funcion_id: uuid.UUID,
    body: PromoverRequest,
    principal: UserInfo = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> FuncionView:
    """Nivel 3, y la **única aprobación previa** del bloque: sólo el superadministrador, con
    valoración escrita. No muta código ni versiones."""
    funcion = await catalogo.funcion_visible(session, funcion_id, principal)
    versiones = await catalogo.versiones_de(session, funcion_id)
    _exigir("promover", funcion, versiones[0] if versiones else None, principal)

    try:
        promover(
            funcion,
            valoracion=body.valoracion,
            publicada_por=user_to_uuid(principal.user_id),
        )
    except PromocionInvalida as fallo:
        raise HTTPException(status_code=422, detail=str(fallo)) from fallo

    return await catalogo.guardar(session, lambda: _vista_de_funcion(funcion, versiones, principal))
