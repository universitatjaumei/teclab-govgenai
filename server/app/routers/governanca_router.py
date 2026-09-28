"""El depósito de manifiestos de ejecuciones hechas fuera (AUT.6, issue #116).

**No confundir con `manifests_router`**, que sirve los manifiestos que produce la propia
plataforma al ejecutar un informe: aquéllos se leen por workspace y son inmutables por
construcción; éstos llegan declarados por una aplicación de fuera. Son dos superficies con
dos modelos de confianza distintos, y por eso viven en dos ficheros.

Deploy: edge — describe tratamientos de datos de la organización.
Módulo: — en la escritura; `registro` en la lectura.

**Y por eso vive aquí y no en `routers/redaccion/`**, aunque el contrato reutilice piezas del
manifiesto de informes: todo router de `redaccion/` exige el módulo `informes` —lo comprueba el
guardarraíl de SEC.9.6— y esto no es una superficie de informes, es la misma capacidad de
gobernanza que el registro de actividad, que está en esta misma carpeta por lo mismo.

El reparto de módulo es también el de aquél: **la escritura no exige módulo** —la autentica un
PAT de máquina, y un token de máquina no tiene módulos concedidos, porque los módulos son de
personas— y **la lectura sí**, con `registro`.

**Qué añade sobre el evento de actividad.** El evento (REG.2, AUT.5) dice «quién, qué, cuándo,
con qué finalidad». El manifiesto dice **qué pasó dentro de esa ejecución**: qué modelo, qué
versión de prompt, qué se citó, quién aprobó qué, con qué salida. Es el paso del registro de uso
a la evidencia por ejecución.

**Escribir exige un PAT; leer, una sesión.** Es el mismo reparto que el registro de actividad, y
por el mismo motivo: una sesión de navegador con permiso de escritura aquí permitiría fabricar
evidencia desde el panel, que es justo lo que un registro de gobernanza no puede admitir.

**Y se lee distinguiendo el origen.** Un manifiesto declarado por un tercero no tiene la misma
autoridad que uno que la plataforma produjo ella misma; leerlos sin distinguir sería perder lo
único que los diferencia.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.api.deps import get_current_user, get_session, require_module
from server.app.core.auth.models import UserInfo
from server.app.core.auth.pat.scopes import MANIFIESTOS_WRITE
from server.app.core.auth.tenancy import organizacion_unica_de, scope_query_to_orgs
from server.app.modules.redaccion.contracts.manifiesto_externo import ManifiestoExterno
from server.app.modules.redaccion.database.models import HubManifiestoExterno

#: El mismo módulo que abre la lectura del registro de actividad: es la misma capacidad.
MODULO_REGISTRO = "registro"

router = APIRouter(prefix="/governanca", tags=["governanca"])


class ManifiestoDepositado(BaseModel):
    """Lo que devuelve el depósito.

    Se devuelve `depositado_en` y no sólo el `id` porque es lo que quien integra necesita para
    conciliar: su reloj y el nuestro no son el mismo, y la marca que vale en una auditoría es la
    que pone la plataforma.
    """

    id: uuid.UUID
    depositado_en: datetime


class ManifiestoEnLista(BaseModel):
    """Un manifiesto tal como lo lee el panel."""

    id: uuid.UUID
    ocurrido_en: datetime
    depositado_en: datetime
    aplicacion: str
    referencia_externa: str | None
    finalidad: str
    modelo_usado: str | None
    hash_de_la_salida: str | None
    funcion_sha256: str | None
    #: **Siempre `externo`**, y es un campo y no una convención: el panel los enseña junto a los
    #: de la plataforma, y sin esto un manifiesto declarado por un tercero se leería con la misma
    #: autoridad que uno que la plataforma produjo. No son lo mismo.
    origen: str = "externo"


@router.post(
    "/manifests",
    response_model=ManifiestoDepositado,
    status_code=201,
    operation_id="depositarManifiesto",
)
async def depositar_manifiesto(
    body: ManifiestoExterno,
    principal: UserInfo = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ManifiestoDepositado:
    """Deposita el manifiesto de una generación hecha fuera de la plataforma.

    La organización **se deriva del token**: no viaja en el cuerpo, y mandarla es un 422 que lo
    explica en vez de ignorarse en silencio — ignorarla haría creer a quien integra que la está
    eligiendo.
    """
    scopes = getattr(principal, "pat_scopes", None)
    if scopes is None:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "PAT_REQUIRED",
                "message": (
                    "Depositar un manifiesto exige un token de acceso personal con el scope "
                    f"`{MANIFIESTOS_WRITE}`. Una sesión de navegador con permiso de escritura "
                    "aquí permitiría fabricar evidencia desde el panel."
                ),
            },
        )
    if MANIFIESTOS_WRITE not in scopes:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "SCOPE_REQUIRED",
                "message": f"Este token no lleva el scope `{MANIFIESTOS_WRITE}`.",
            },
        )

    organizacion = organizacion_unica_de(principal)
    if organizacion is None:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "SIN_ORGANIZACION",
                "message": (
                    "El token no pertenece a ninguna organización, así que no hay registro en "
                    "el que depositar: el manifiesto se acota por ella y no se puede elegir en "
                    "la petición."
                ),
            },
        )

    fila = HubManifiestoExterno(
        organizacion_id=organizacion,
        ocurrido_en=body.ocurrido_en,
        aplicacion=body.aplicacion,
        referencia_externa=body.referencia_externa,
        finalidad=body.finalidad,
        modelo_usado=body.modelo_usado,
        hash_de_la_salida=body.hash_de_la_salida,
        funcion_sha256=body.funcion_sha256,
        payload_json=body.model_dump(mode="json"),
    )
    session.add(fila)
    await session.commit()
    await session.refresh(fila)

    return ManifiestoDepositado(id=fila.id, depositado_en=fila.depositado_en)


@router.get(
    "/manifests",
    response_model=list[ManifiestoEnLista],
    operation_id="listarManifiestosExternos",
    dependencies=[Depends(require_module(MODULO_REGISTRO))],
)
async def listar_manifiestos_externos(
    limite: int = Query(default=50, ge=1, le=200),
    principal: UserInfo = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[ManifiestoEnLista]:
    """Los manifiestos depositados, acotados por tenencia y del más reciente al más antiguo.

    La acotación la hace `scope_query_to_orgs` y no un `if` de aquí: la regla vive en un solo
    sitio, y un principal sin organizaciones recibe `IN ()` —o sea nada—, que es la diferencia
    entre «no ve nada» y «no se filtra».
    """
    consulta = scope_query_to_orgs(
        select(HubManifiestoExterno), principal, HubManifiestoExterno
    ).order_by(HubManifiestoExterno.ocurrido_en.desc()).limit(limite)

    filas = (await session.execute(consulta)).scalars().all()
    return [
        ManifiestoEnLista(
            id=f.id,
            ocurrido_en=f.ocurrido_en,
            depositado_en=f.depositado_en,
            aplicacion=f.aplicacion,
            referencia_externa=f.referencia_externa,
            finalidad=f.finalidad,
            modelo_usado=f.modelo_usado,
            hash_de_la_salida=f.hash_de_la_salida,
            funcion_sha256=f.funcion_sha256,
        )
        for f in filas
    ]
