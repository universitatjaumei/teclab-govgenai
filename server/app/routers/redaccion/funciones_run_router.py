"""Ejecutar una función del catálogo por API (FUN.6).

Deploy: edge — se ejecuta código sobre datos del cliente.
Módulo: informes.

La superficie para una aplicación externa. Lo que esta capa añade sobre `ejecutar_funcion` no es
la ejecución: es **no relajar nada** de lo que el catálogo hace cumplir por dentro.

* **La versión va en el cuerpo y es obligatoria.** El anclaje también rige fuera: una API que
  ejecutara «la última» convertiría cada publicación en un cambio silencioso de comportamiento
  para todos sus consumidores, que es exactamente lo que el anclaje evita dentro.
* **La organización se deriva del dueño del PAT.** Si viniera en la petición, un token filtrado
  podría ejecutar contra cualquier organización.
* **Una versión suspendida devuelve 423 con el motivo**, no un 404: la función existe, y quien
  integra tiene que poder distinguir «no está» de «está detenida, y por esto». Y no toca el
  sandbox, igual que dentro.
* **El evento del registro de actividad lleva metadatos y ni un byte de la entrada.** La
  finalidad y las categorías son las que la **función declaró**; si las eligiera quien llama, la
  declaración responsable dejaría de significar algo.

`require_pat_scopes` y no `require_scopes`: esta superficie existe para clientes máquina, y una
sesión de navegador que pudiera ejecutarla dejaría rastro con la identidad de una persona en el
registro sin que ninguna persona hubiera pedido nada.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status

from server.app.core.storage import StorageService, get_storage_service
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.api.deps import get_session, require_module, require_pat_scopes
from server.app.core.auth.models import UserInfo
from server.app.core.auth.pat.scopes import FUNCIONES_EXECUTE
from server.app.core.auth.tenancy import organizacion_unica_de
from server.app.core.sandbox_client import (
    SandboxClient,
    SandboxUnavailableError,
    get_sandbox_client,
)
from server.app.modules.agents_hub.contracts.actividad import ActividadIAEvent
from server.app.modules.agents_hub.database.operational_models import HubActividadIA
from server.app.modules.redaccion.contracts.funciones import (
    ContratoFuncion,
    EntradaNoCumpleElContrato,
)
from server.app.modules.redaccion.database.models import HubFuncion, HubFuncionVersion
from server.app.modules.redaccion.funciones_origenes import (
    OrigenNoDeclarado,
    descargar_de_un_origen_declarado,
)
from server.app.modules.redaccion.funciones_artefactos import (
    ArtefactoNoDisponible,
    artefacto_para_descargar,
    guardar_artefactos,
)
from server.app.modules.redaccion.funciones_service import (
    artefactos_en_bruto,
    ejecutar_funcion,
)
from server.app.routers.verificaciones_router import MAXIMO_BYTES

router = APIRouter(
    prefix="/funciones",
    tags=["funciones"],
    dependencies=[Depends(require_module("informes"))],
)

#: Tope de la ejecución. Un script pesado no puede tener el proceso ocupado indefinidamente, y
#: para quien integra un 504 con el motivo es accionable mientras un 500 no dice si reintentar.
TIMEOUT_SEGUNDOS = 30


class EjecutarRequest(BaseModel):
    """La petición. **`version` no tiene defecto**: el anclaje también rige fuera."""

    version: int = Field(ge=1)
    #: Referencias de almacenamiento por slot, tal como las declara el contrato. Son rutas o
    #: claves, **no contenido**: el fichero ya está en el almacenamiento de la organización.
    ficheros: dict[str, str] = Field(default_factory=dict)
    #: AUT.8 — URL por slot, para los documentos que hay que **bajar de fuera**. Cada una tiene
    #: que salir de un servidor que la función declara en `origenes`; si no, 422 y el sandbox no
    #: se toca.
    #:
    #: Va aparte de `ficheros` y no mezclado con él porque son dos cosas distintas para quien
    #: integra: una referencia de almacenamiento es un documento que ya tiene, y una URL es uno
    #: que le pide a la plataforma que traiga. Mezclarlas obligaría a adivinar cuál es cuál por
    #: la forma de la cadena.
    urls: dict[str, str] = Field(default_factory=dict)
    parametros: dict[str, Any] = Field(default_factory=dict)


class EjecutarResponse(BaseModel):
    """La salida, más **qué se ejecutó**.

    Sin `funcion`, un consumidor externo no puede anotar en su propio registro de actividad qué
    versión le contestó — y entonces su registro y el nuestro no se pueden cruzar, que es
    justamente lo que REG existe para permitir.
    """

    tables: list[dict[str, Any]] = Field(default_factory=list)
    metrics: list[dict[str, Any]] = Field(default_factory=list)
    free_text: str | None = None
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    funcion: dict[str, Any] = Field(default_factory=dict)
    #: AUT.7 — los ficheros producidos, **por referencia y no por contenido**. Devolver el
    #: Excel en base64 dentro de este JSON haría que una respuesta de metadatos pesara
    #: megabytes, y quien integra suele querer las cifras sin el fichero.
    artefactos: list["ArtefactoEnLaRespuesta"] = Field(default_factory=list)


class ArtefactoEnLaRespuesta(BaseModel):
    """Un fichero producido: qué es, cuánto pesa, y por dónde se baja.

    Lleva `sha256` para que quien integra pueda comprobar lo que descarga, y `expira_en` porque
    **la referencia caduca**: sin esa fecha, un consumidor que guarda el enlace descubre la
    retención el día que le devuelve un 404.
    """

    id: uuid.UUID
    nombre: str
    media_type: str
    bytes: int
    sha256: str
    expira_en: datetime
    descarga: str


async def _visible_para(
    session: AsyncSession, funcion_id: uuid.UUID, organizacion: uuid.UUID | None
) -> HubFuncion:
    """La función, si ese PAT puede verla. **404 y no 403** sobre lo que no le corresponde: un
    403 ya cuenta que esa función existe en otra organización."""
    funcion = await session.get(HubFuncion, funcion_id)
    if funcion is None:
        raise HTTPException(status_code=404, detail="Función no encontrada")

    publicada = funcion.publicada_en is not None or funcion.organizacion_id is None
    suya = organizacion is not None and str(funcion.organizacion_id) == str(organizacion)
    if not (publicada or suya):
        raise HTTPException(status_code=404, detail="Función no encontrada")
    return funcion


def _cabe_en_el_tope(body: EjecutarRequest) -> None:
    """El tope de entrada, **heredado** del que VAS.1 fijó.

    Aquel bloque lo dejó escrito esperando a éste, literalmente: «no hay límite de entrada del
    sandbox del que heredarlo —FUN.6 aún no existe—, así que se fija aquí y ese bloque lo
    heredará de este sitio en vez de inventar otro». Dos topes para el mismo riesgo son dos
    números que divergen.
    """
    tamano = len(json.dumps(body.model_dump(), ensure_ascii=False).encode("utf-8"))
    if tamano > MAXIMO_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"la petición pesa {tamano} bytes y el tope es {MAXIMO_BYTES}. Los ficheros se "
                "pasan por referencia de almacenamiento, no por contenido."
            ),
        )


async def _anotar_en_el_registro(
    session: AsyncSession,
    *,
    organizacion: uuid.UUID | None,
    principal: UserInfo,
    funcion: HubFuncion,
    version: HubFuncionVersion,
) -> None:
    """Un evento de REG por ejecución. **Metadatos y ningún payload.**

    La referencia de lo ejecutado va en `herramienta` —`funcion:<id>@<v>#<sha12>`— y no en un
    campo nuevo del contrato: el contrato de REG.1 es el mismo para toda herramienta que
    registre, y un campo que sólo rellena un caso de uso lo convierte en un formulario con
    huecos. Es la misma decisión que tomó VAS.1 con el nivel de riesgo, y por la misma razón.
    """
    evento = ActividadIAEvent(
        ocurrido_en=datetime.now(timezone.utc),
        actor=principal.user_id,
        herramienta=(
            f"funcion:{funcion.id}@{version.version}#{version.code_sha256[:12]}"
        ),
        agente=None,
        # Las declaradas por la función, no las que diga quien llama.
        finalidad=version.finalidad or funcion.nombre,
        modelo_usado=None,
        categorias_datos=list(version.categorias_datos or []),
        payload_hash=None,
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


@router.post(
    "/{funcion_id}/run",
    response_model=EjecutarResponse,
    operation_id="ejecutarFuncion",
    dependencies=[Depends(require_pat_scopes(FUNCIONES_EXECUTE))],
)
async def ejecutar_funcion_por_api(
    funcion_id: uuid.UUID,
    body: EjecutarRequest,
    principal: UserInfo = Depends(require_pat_scopes(FUNCIONES_EXECUTE)),
    session: AsyncSession = Depends(get_session),
    sandbox: SandboxClient = Depends(get_sandbox_client),
    # APER.14 — con esto una función empaquetada **no abre la ruta que le den**: la referencia
    # se resuelve contra el almacenamiento de la organización, con la clave validada.
    almacen: StorageService = Depends(get_storage_service),
) -> EjecutarResponse:
    """Ejecuta `funcion@version` con la entrada dada, y lo anota en el registro de actividad."""
    organizacion = organizacion_unica_de(principal)
    funcion = await _visible_para(session, funcion_id, organizacion)
    _cabe_en_el_tope(body)

    version = (
        await session.execute(
            select(HubFuncionVersion)
            .where(HubFuncionVersion.funcion_id == funcion_id)
            .where(HubFuncionVersion.version == body.version)
        )
    ).scalar_one_or_none()
    if version is None:
        raise HTTPException(
            status_code=404,
            detail=f"«{funcion.nombre}» no tiene versión {body.version}",
        )

    if funcion.origen == "externa":
        # AUT.3 — se registra, no se ejecuta. **Y va antes de mirar el estado**: una
        # versión externa suspendida devolvía 423 «espera o cambia de versión», que
        # contradice lo que este mismo bloque documenta —suspender una externa es un aviso,
        # no un cerrojo— y le dice a quien integra que esperando podría llegar a ejecutarse.
        # Lo señaló la revisión de la PR #189. **409 y no 423**: un 423 dice «existe y está
        # detenida», o sea espera o cambia de versión, y aquí no hay nada que esperar. Esta
        # función no va a correr aquí nunca, y quien integra necesita distinguirlo para no
        # reintentar contra una puerta que no existe.
        #
        # Y la respuesta dice **dónde sí corre**, que es el dato que el registro guarda
        # justamente para esto.
        donde = version.entorno_ejecucion or "fuera de la plataforma"
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"«{funcion.nombre}» es una función de origen externo: la plataforma la "
                f"registra y no la ejecuta. Corre en {donde}, con las credenciales de quien la "
                f"usa. Lo que la plataforma aporta aquí es el registro, la declaración "
                f"responsable y la revisión posterior."
            ),
        )

    if version.estado != "registrada":
        # 423 «locked»: existe y está detenida. Con el motivo, que es lo que quien integra
        # necesita para saber si esperar o cambiar de versión.
        detalle = f"la versión {version.version} de «{funcion.nombre}» no está en servicio"
        if version.estado == "suspendida" and version.motivo_suspension:
            detalle += f": {version.motivo_suspension}"
        elif version.estado == "no_instalada":
            detalle += ": su paquete no está instalado en este despliegue"
        else:
            detalle += f" (estado «{version.estado}»)"
        raise HTTPException(status_code=status.HTTP_423_LOCKED, detail=detalle)

    contrato = ContratoFuncion.model_validate(version.contrato_entrada or {})

    # AUT.8 — lo que hay que traer de fuera se trae **aquí**, antes de tocar el sandbox y antes
    # de validar la entrada contra el contrato: una URL rechazada no puede haber gastado una
    # ejecución ni dejado rastro de algo que no ocurrió. Es el mismo orden que ya tenía la
    # validación de entrada, y por la misma razón.
    #
    # El guion recibe el contenido por el camino de un fichero subido a mano, así que **no se
    # entera de que hubo red**: abrir la red no cambia el protocolo del guion ni lo que el
    # auditor le permite.
    bajados: dict[str, bytes] = {}
    if body.urls:
        for slot, url in body.urls.items():
            try:
                contenido, _nombre = await descargar_de_un_origen_declarado(
                    url, origenes=contrato.origenes
                )
            except OrigenNoDeclarado as fallo:
                raise HTTPException(status_code=422, detail=str(fallo)) from fallo
            except Exception as fallo:  # noqa: BLE001 — se traduce, no se deja subir opaco
                # 502 y no 500: el fallo es del servidor de fuera, no de la petición. Quien
                # integra necesita distinguirlo para saber si reintentar.
                raise HTTPException(
                    status_code=502,
                    detail=(
                        f"no se pudo traer «{url}» para el slot «{slot}»: {fallo}. El origen "
                        f"está declarado, así que el problema es del servidor remoto."
                    ),
                ) from fallo
            bajados[slot] = contenido

    if funcion.origen == "paquete":
        # In-process, por el camino de FUN.5. No pasa por el sandbox y no se finge lo contrario.
        from server.app.modules.redaccion.funciones_paquete import ejecutar_empaquetada

        try:
            # AUT.8 — una función **empaquetada** no recibe documentos bajados, y no es un
            # olvido: corre **en el proceso del servidor** y con acceso a `StorageService`, así
            # que su `run` puede traerse lo que necesite por su cuenta. Darle además el
            # contenido aquí sería un segundo camino para lo mismo, y el que sobra es éste.
            #
            # Se rechaza en vez de ignorarlo: aceptar `urls` y no entregar nada dejaría a quien
            # integra buscando por qué su slot llega vacío.
            if bajados:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"«{funcion.nombre}» es una función empaquetada: corre en el proceso "
                        "del servidor y se trae lo que necesita por su cuenta, así que no "
                        "acepta `urls`. Los orígenes declarados son para las de autoservicio, "
                        "que corren en el sandbox y no tienen red."
                    ),
                )
            salida = await ejecutar_empaquetada(
                funcion.entry_point or "",
                ficheros=body.ficheros,
                parametros=body.parametros,
                almacen=almacen,
            )
        except EntradaNoCumpleElContrato as fallo:
            raise HTTPException(status_code=422, detail=str(fallo)) from fallo
        except Exception as fallo:  # noqa: BLE001 — se traduce, no se deja subir opaco
            raise HTTPException(
                status_code=502,
                detail=(
                    f"la función empaquetada «{funcion.nombre}» falló al ejecutarse: {fallo}"
                ),
            ) from fallo
    else:
        try:
            salida = await ejecutar_funcion(
                contrato=contrato,
                code=version.code or "",
                ficheros=body.ficheros,
                contenidos=bajados,
                parametros=body.parametros,
                sandbox=sandbox,
                timeout_seconds=TIMEOUT_SEGUNDOS,
            )
        except EntradaNoCumpleElContrato as fallo:
            # 422 tipado y **sin tocar el sandbox**: `ejecutar_funcion` valida delante.
            raise HTTPException(status_code=422, detail=str(fallo)) from fallo
        except TimeoutError as fallo:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail=(
                    f"la función agotó el tiempo de ejecución ({TIMEOUT_SEGUNDOS} s). Es el "
                    "fallo más probable con un fichero grande; reintentar con menos datos o "
                    "revisar el script."
                ),
            ) from fallo
        except SandboxUnavailableError as fallo:
            # 503 y no 500, y lo destapó el `curl` real con el sandbox apagado. En producción el
            # sandbox es otro servicio, así que «no responde» es la causa más probable de un
            # fallo **que no es de quien integra**: un 500 le dice «algo se rompió, mira si es
            # tuyo» y un 503 con el motivo le dice «no es tuyo, reintenta». Es la diferencia
            # entre un aviso al equipo de la plataforma y una tarde depurando código ajeno.
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "el servicio de ejecución (sandbox) no responde, así que la función no se "
                    f"ha ejecutado. No es un problema de tu petición: reintenta en unos "
                    f"minutos. Detalle: {fallo}"
                ),
            ) from fallo

    # La respuesta se compone **antes** de anotar el evento, porque anotar commitea y la sesión
    # de `api/deps.py` expira al commitear: leer `version.version` después dispara una recarga
    # perezosa y revienta con `MissingGreenlet`. Aquí duele el doble, porque el evento sí se
    # guarda: el consumidor recibiría un 500 sobre una ejecución que ocurrió, reintentaría, y
    # quedarían dos eventos para un solo uso. Mismo defecto que en `funciones_router` (FUN.4) y
    # que en ocho endpoints de `scripts_router`; lo destapó un `curl` real.
    # AUT.7 — lo que el guion produjo se guarda **antes** de componer la respuesta: si el
    # almacenamiento falla, es mejor un 5xx sin respuesta que una respuesta con referencias a
    # ficheros que no están.
    brutos = artefactos_en_bruto(salida)
    guardados = []
    if brutos:
        declarados = contrato.artefactos
        guardados = await guardar_artefactos(
            session,
            brutos,
            almacen=almacen,
            organizacion_id=organizacion,
            funcion_id=funcion.id,
            version=version.version,
            retencion_dias=declarados.retencion_dias if declarados else 1,
        )

    respuesta = EjecutarResponse(
        tables=[t.model_dump() for t in salida.tables],
        metrics=[m.model_dump() for m in salida.metrics],
        free_text=salida.free_text,
        warnings=[w.model_dump() for w in salida.warnings],
        artefactos=[
            ArtefactoEnLaRespuesta(
                id=a.id,
                nombre=a.nombre,
                media_type=a.media_type,
                bytes=a.bytes,
                sha256=a.sha256,
                expira_en=a.expira_en,
                descarga=f"/api/v1/funciones/artefactos/{a.id}",
            )
            for a in guardados
        ],
        funcion={
            "funcion_id": str(funcion.id),
            "nombre": funcion.nombre,
            "version": version.version,
            "origen": funcion.origen,
            "code_sha256": version.code_sha256,
            "version_paquete": version.version_paquete,
        },
    )

    await _anotar_en_el_registro(
        session,
        organizacion=organizacion,
        principal=principal,
        funcion=funcion,
        version=version,
    )

    return respuesta


@router.get(
    "/artefactos/{artefacto_id}",
    operation_id="descargarArtefactoDeFuncion",
    dependencies=[Depends(require_pat_scopes(FUNCIONES_EXECUTE))],
    response_class=Response,
)
async def descargar_artefacto(
    artefacto_id: uuid.UUID,
    principal: UserInfo = Depends(require_pat_scopes(FUNCIONES_EXECUTE)),
    session: AsyncSession = Depends(get_session),
    almacen: StorageService = Depends(get_storage_service),
) -> Response:
    """Sirve un fichero producido por una ejecución (AUT.7).

    **El mismo scope que ejecutar y no uno nuevo.** Quien puede ejecutar la función puede
    llevarse lo que produce; un scope aparte sugeriría que se puede dar lo uno sin lo otro, y no
    es cierto en ninguna de las dos direcciones — sin ejecutar no hay fichero, y ejecutar sin
    poder recogerlo no sirve de nada.

    **404 para lo que no existe, lo ajeno y lo caducado, sin distinguirlos.** Distinguirlos
    contaría que ese fichero existe en otra organización, que es lo que el resto del catálogo
    evita respondiendo 404 y no 403. Y el mensaje nombra la retención, porque «404» sobre algo
    que alguien descargó ayer es desconcertante si no se sabe que caduca.
    """
    organizacion = organizacion_unica_de(principal)
    try:
        fila, datos = await artefacto_para_descargar(
            session, artefacto_id, organizacion_id=organizacion, almacen=almacen
        )
    except ArtefactoNoDisponible as fallo:
        raise HTTPException(
            status_code=404,
            detail=(
                "ese fichero no está disponible: o no existe, o no es de tu organización, o ha "
                "pasado su plazo de retención. El plazo lo declara el contrato de la función."
            ),
        ) from fallo

    # `filename*` en UTF-8 además de `filename`: el nombre lo pone el guion y puede llevar
    # acentos, y sin la forma extendida algunos clientes lo rompen.
    from urllib.parse import quote

    seguro = quote(fila.nombre)
    return Response(
        content=datos,
        media_type=fila.media_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{seguro}",
            "X-Artefacto-SHA256": fila.sha256,
        },
    )
