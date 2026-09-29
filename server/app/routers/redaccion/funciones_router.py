"""El catálogo de funciones y su revisión posterior (FUN.4).

Deploy: edge — el código y la declaración de una función son de la organización.
Módulo: informes — hoy lo consumen los informes; en Fase 3, las fases de expediente.

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
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.api.deps import get_current_user, get_session, require_module
from server.app.core.auth.models import UserInfo
from server.app.core.auth.tenancy import organizacion_unica_de
from server.app.modules.redaccion.database.models import (
    HubFuncion,
    HubFuncionVersion,
    HubReportTemplateVersion,
)
from server.app.modules.redaccion.funciones_acciones import (
    PromocionInvalida,
    RevisionInvalida,
    acciones_permitidas,
    aplicar_revision,
    candidata_a_nivel_3,
    muestra_para_revisar,
    promover,
    reactivar,
    suspender,
)
from server.app.modules.redaccion.funciones_service import (
    FuncionIncoherente,
    consulta_de_catalogo,
)
from server.app.routers.redaccion._actor import user_to_uuid

router = APIRouter(
    prefix="/funciones",
    tags=["funciones"],
    dependencies=[Depends(require_module("informes"))],
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


async def _funcion_visible(
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


async def _versiones_de(
    session: AsyncSession, funcion_id: uuid.UUID
) -> list[HubFuncionVersion]:
    filas = (
        await session.execute(
            select(HubFuncionVersion)
            .where(HubFuncionVersion.funcion_id == funcion_id)
            # DET.1 — orden estable con desempate: dos versiones pueden compartir `created_at`.
            .order_by(HubFuncionVersion.version.desc(), HubFuncionVersion.id)
        )
    ).scalars().all()
    return list(filas)


async def _version_de(
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


# La vista se construye **antes** del `commit`, no después.
#
# `api/deps.py::get_session` construye `AsyncSession(server_engine)` a pelo, y ahí
# `expire_on_commit` vale `True` —el `expire_on_commit=False` vive en el `sessionmaker` de
# `database/db.py`, que es **otro** `get_session`—. Leer `version.version` después de commitear
# dispara entonces una recarga perezosa síncrona sobre una sesión asíncrona, que revienta con
# `MissingGreenlet`: la escritura se guarda y la respuesta es un 500.
#
# Es el mismo defecto que `scripts_router` tuvo en ocho endpoints, y aquí lo destapó la pantalla
# de revisión posterior: suspendía con su motivo y devolvía 500, así que quien revisa veía un
# error sobre una versión que acababa de quedar detenida.


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
    except Exception as fallo:  # noqa: BLE001 — el registro no depende de esto
        return {
            "perfil": "informativo",
            "no_se_pudo_auditar": f"{type(fallo).__name__}: {fallo}",
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
    principal: UserInfo = Depends(get_current_user),
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
    except Exception as fallo:  # noqa: BLE001 — se traduce a 422 con su motivo
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
        destino = await session.get(HubFuncion, body.funcion_id)
        if destino is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "FUNCION_NO_ENCONTRADA",
                    "message": f"no hay ninguna función {body.funcion_id} en el catálogo",
                },
            )
        if not principal.is_superadmin and destino.organizacion_id != organizacion:
            # 404 y no 403: decir «existe pero no es tuya» ya es decir que existe.
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "FUNCION_NO_ENCONTRADA",
                    "message": f"no hay ninguna función {body.funcion_id} en el catálogo",
                },
            )
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

    # El identificador se lee **antes** del commit: `expire_on_commit` expira los atributos y
    # leerlos después dispara una recarga perezosa que revienta con `MissingGreenlet`. Es el
    # patrón que tumbó ocho endpoints de `scripts_router` el 2026-08-14.
    funcion_id = funcion.id
    await session.commit()

    funcion = await session.get(HubFuncion, funcion_id)
    versiones = await _versiones_de(session, funcion_id)
    return _vista_de_funcion(funcion, versiones, principal)


# ──────────────────────────── El catálogo ────────────────────────────


@router.get("", response_model=list[FuncionView], operation_id="listarFunciones")
async def listar_funciones(
    principal: UserInfo = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[FuncionView]:
    """El catálogo que ve quien pregunta: las suyas y las publicadas.

    Nunca las no publicadas de otra organización — eso lo decide `consulta_de_catalogo`, que es
    la misma frontera que usa el resolutor, escrita una sola vez.
    """
    if principal.is_superadmin:
        funciones = (await session.execute(select(HubFuncion).order_by(HubFuncion.created_at, HubFuncion.id))).scalars().all()
    else:
        funciones = (
            await session.execute(
                consulta_de_catalogo(organizacion_id=organizacion_unica_de(principal))
            )
        ).scalars().all()

    vistas = []
    for funcion in funciones:
        vistas.append(
            _vista_de_funcion(funcion, await _versiones_de(session, funcion.id), principal)
        )
    return vistas


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
    if principal.is_superadmin:
        funciones = (await session.execute(select(HubFuncion).order_by(HubFuncion.created_at, HubFuncion.id))).scalars().all()
    else:
        de_quien = organizacion_unica_de(principal)
        funciones = (
            await session.execute(
                select(HubFuncion).where(HubFuncion.organizacion_id == de_quien)
            )
        ).scalars().all()

    por_funcion = {f.id: f for f in funciones}
    if not por_funcion:
        return []

    versiones = (
        await session.execute(
            select(HubFuncionVersion)
            .where(HubFuncionVersion.funcion_id.in_(list(por_funcion)))
            .where(HubFuncionVersion.estado.in_(("registrada", "suspendida")))
            .order_by(HubFuncionVersion.created_at.desc(), HubFuncionVersion.id)
        )
    ).scalars().all()

    candidatas = list(versiones)
    if estado == "sin_revisar":
        candidatas = [v for v in candidatas if v.revisada_por is None]
    if muestra is not None:
        candidatas = muestra_para_revisar(candidatas, cuantas=muestra)

    ahora = datetime.now(timezone.utc)
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
                plantillas_que_la_usan=await _cuantas_plantillas_la_usan(
                    session, funcion.id, version.version
                ),
                dias_desde_el_registro=max((ahora - creada).days, 0),
                acciones_permitidas=acciones_permitidas(
                    funcion, version, principal=principal
                ),
            )
        )
    return filas


async def _cuantas_plantillas_la_usan(
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


@router.get(
    "/{funcion_id}", response_model=FuncionView, operation_id="verFuncion"
)
async def ver_funcion(
    funcion_id: uuid.UUID,
    principal: UserInfo = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> FuncionView:
    """La ficha: el contrato legible, la declaración, los hallazgos y las versiones."""
    funcion = await _funcion_visible(session, funcion_id, principal)
    return _vista_de_funcion(funcion, await _versiones_de(session, funcion_id), principal)


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
    funcion = await _funcion_visible(session, funcion_id, principal)
    version = await _version_de(session, funcion_id, numero)
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

    vista = _vista_de_version(funcion, version, principal)
    await session.commit()
    return vista


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
    funcion = await _funcion_visible(session, funcion_id, principal)
    version = await _version_de(session, funcion_id, numero)
    _exigir("suspender", funcion, version, principal)

    try:
        suspender(
            version, motivo=body.motivo, suspendida_por=user_to_uuid(principal.user_id)
        )
    except FuncionIncoherente as fallo:
        raise HTTPException(status_code=422, detail=str(fallo)) from fallo

    vista = _vista_de_version(funcion, version, principal)
    await session.commit()
    return vista


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
    funcion = await _funcion_visible(session, funcion_id, principal)
    version = await _version_de(session, funcion_id, numero)
    _exigir("reactivar", funcion, version, principal)

    reactivar(version)
    vista = _vista_de_version(funcion, version, principal)
    await session.commit()
    return vista


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
    funcion = await _funcion_visible(session, funcion_id, principal)
    version = await _version_de(session, funcion_id, numero)
    _exigir("retirar", funcion, version, principal)

    version.estado = "retirada"
    vista = _vista_de_version(funcion, version, principal)
    await session.commit()
    return vista


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
    funcion = await _funcion_visible(session, funcion_id, principal)
    versiones = await _versiones_de(session, funcion_id)
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
    vista = _vista_de_funcion(funcion, versiones, principal)
    await session.commit()
    return vista


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
    funcion = await _funcion_visible(session, funcion_id, principal)
    versiones = await _versiones_de(session, funcion_id)
    _exigir("promover", funcion, versiones[0] if versiones else None, principal)

    try:
        promover(
            funcion,
            valoracion=body.valoracion,
            publicada_por=user_to_uuid(principal.user_id),
        )
    except PromocionInvalida as fallo:
        raise HTTPException(status_code=422, detail=str(fallo)) from fallo

    vista = _vista_de_funcion(funcion, versiones, principal)
    await session.commit()
    return vista
