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

from server.app.api.deps import (
    get_session,
    require_module,
    require_pat_scopes,
    require_role,
)
from server.app.core.auth.models import UserInfo, UserRole
from server.app.core.auth.pat.scopes import MANIFIESTOS_WRITE
from server.app.core.auth.tenancy import organizacion_unica_de, scope_query_to_orgs
from server.app.modules.redaccion.contracts.manifiesto_externo import ManifiestoExterno
from server.app.modules.redaccion.database.models import HubManifiestoExterno

#: El mismo módulo que abre la lectura del registro de actividad: es la misma capacidad.
MODULO_REGISTRO = "registro"

#: Leer evidencia es de quien administra. El módulo concede la pantalla; el rol, el dato.
_require_admin = require_role(UserRole.SUPERADMIN.value, UserRole.ADMIN.value)

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


class ManifiestoCompleto(BaseModel):
    """El manifiesto tal como se depositó, con la marca que puso la plataforma.

    El contrato de entrada **es** el de salida: devolver una copia con otros nombres crearía un
    segundo esquema que divergiría del primero, y quien lo consuma tendría que traducir.
    """

    id: uuid.UUID
    depositado_en: datetime
    manifiesto: ManifiestoExterno


@router.post(
    "/manifests",
    response_model=ManifiestoDepositado,
    status_code=201,
    operation_id="depositarManifiesto",
)
async def depositar_manifiesto(
    body: ManifiestoExterno,
    principal: UserInfo = Depends(require_pat_scopes(MANIFIESTOS_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> ManifiestoDepositado:
    """Deposita el manifiesto de una generación hecha fuera de la plataforma.

    La organización **se deriva del token**: no viaja en el cuerpo, y mandarla es un 422 que lo
    explica en vez de ignorarse en silencio — ignorarla haría creer a quien integra que la está
    eligiendo.

    **El scope lo comprueba `require_pat_scopes`, que es la dependencia que ya existe.** Aquí
    hubo una reimplementación que leía `principal.pat_scopes`, y ese atributo **no existe**:
    `get_current_user` deja los scopes en `request.state` y devuelve un `UserInfo` congelado sin
    ese campo, así que todo PAT válido recibía `PAT_REQUIRED` y el endpoint no se podía usar. Lo
    encontró la revisión de la PR #189, no un test — porque los tests probaban el contrato y la
    lectura, y nunca llamaron a este endpoint.
    """
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
    principal: UserInfo = Depends(_require_admin),
    session: AsyncSession = Depends(get_session),
) -> list[ManifiestoEnLista]:
    """Los manifiestos depositados, acotados por tenencia y del más reciente al más antiguo.

    La acotación la hace `scope_query_to_orgs` y no un `if` de aquí: la regla vive en un solo
    sitio, y un principal sin organizaciones recibe `IN ()` —o sea nada—, que es la diferencia
    entre «no ve nada» y «no se filtra».

    **Y además del módulo, el rol.** `require_module` es una concesión de organización, no una
    comprobación de rol: sin `_require_admin`, cualquier persona con el módulo `registro`
    concedido leería quién aprobó qué en cada ejecución. Es el mismo par que usa
    `listar_actividad`, y aquí importa más, porque esto es la evidencia y aquello el índice.
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


@router.get(
    "/manifests/{manifiesto_id}",
    response_model=ManifiestoCompleto,
    operation_id="verManifiestoExterno",
    dependencies=[Depends(require_module(MODULO_REGISTRO))],
)
async def ver_manifiesto_externo(
    manifiesto_id: uuid.UUID,
    principal: UserInfo = Depends(_require_admin),
    session: AsyncSession = Depends(get_session),
) -> ManifiestoCompleto:
    """Un manifiesto entero: **lo que pasó dentro de aquella ejecución**.

    El listado da las columnas por las que se filtra y se ordena; esto da lo que el manifiesto
    existe para guardar —versiones de prompt, fuentes citadas, aprobaciones humanas, categorías
    de datos—, que vive en `payload_json`. Sin este endpoint, el panel sólo podía enseñar el
    resumen y la promesa de «leer qué pasó dentro» se quedaba sin cumplir.

    Acotado por tenencia como el listado: un identificador de otra organización responde **404**
    y no 403, porque decir «existe pero no es tuyo» ya es decir que existe.
    """
    consulta = scope_query_to_orgs(
        select(HubManifiestoExterno).where(HubManifiestoExterno.id == manifiesto_id),
        principal,
        HubManifiestoExterno,
    )
    fila = (await session.execute(consulta)).scalar_one_or_none()
    if fila is None:
        raise HTTPException(status_code=404, detail="No hay ningún manifiesto con ese id")

    return ManifiestoCompleto(
        id=fila.id,
        depositado_en=fila.depositado_en,
        manifiesto=ManifiestoExterno.model_validate(fila.payload_json or {}),
    )
