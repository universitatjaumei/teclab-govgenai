"""Ejecutar una versión del catálogo por API: lo que pasa entre la petición y la respuesta (#274).

Vivía dentro de `routers/redaccion/funciones_run_router.py:ejecutar_funcion_por_api`, 258 líneas,
el segundo endpoint más largo de `app/`. El endpoint conserva lo que es de la superficie —quién
ve la función, el tope de la petición, el registro de actividad y la forma de la respuesta— y
esto hace el resto: elegir la versión, comprobar que puede correr, traer lo que haya que traer,
ejecutar y guardar lo producido.

**Los rechazos llevan su código HTTP** (`RechazoDeEjecucion`). No es acoplar el servicio a
HTTP por comodidad: el código *es* el contrato con quien integra —423 «detenida, espera», 409
«no corre aquí nunca», 502 «el fallo es del servidor de fuera», 503 «no es tuyo, reintenta»—, y
cada uno está razonado donde se decide. Repartir la decisión en dos sitios la haría divergir.

Deploy: edge
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.core.sandbox_client import SandboxClient, SandboxUnavailableError
from server.app.core.storage import StorageService
from server.app.modules.redaccion.contracts.funciones import (
    ContratoFuncion,
    EntradaNoCumpleElContrato,
)
from server.app.modules.redaccion.database.models import HubFuncion, HubFuncionVersion
from server.app.modules.redaccion.funciones_artefactos import guardar_artefactos
from server.app.modules.redaccion.funciones_origenes import (
    MAXIMO_BYTES as MAXIMO_BYTES_DESCARGA,
    OrigenNoDeclarado,
    descargar_de_un_origen_declarado,
)
from server.app.modules.redaccion.funciones_service import (
    MAXIMO_BYTES_DE_ENTRADA,
    artefactos_en_bruto,
    ejecutar_funcion,
)

#: Tope de la ejecución. Un script pesado no puede tener el proceso ocupado indefinidamente, y
#: para quien integra un 504 con el motivo es accionable mientras un 500 no dice si reintentar.
TIMEOUT_SEGUNDOS = 30


class RechazoDeEjecucion(Exception):
    """La ejecución no ocurre, con el código y el motivo que se le dan a quien integra."""

    def __init__(self, status_code: int, detalle: str) -> None:
        super().__init__(detalle)
        self.status_code = status_code
        self.detalle = detalle


@dataclass
class Ejecucion:
    """Lo que se ejecutó y lo que salió, ya guardado."""

    version: HubFuncionVersion
    contrato: ContratoFuncion
    salida: Any
    guardados: list = field(default_factory=list)


async def _version_que_puede_correr(
    session: AsyncSession, funcion: HubFuncion, numero: int
) -> HubFuncionVersion:
    version = (
        await session.execute(
            select(HubFuncionVersion)
            .where(HubFuncionVersion.funcion_id == funcion.id)
            .where(HubFuncionVersion.version == numero)
        )
    ).scalar_one_or_none()
    if version is None:
        raise RechazoDeEjecucion(404, f"«{funcion.nombre}» no tiene versión {numero}")

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
        raise RechazoDeEjecucion(
            409,
            f"«{funcion.nombre}» es una función de origen externo: la plataforma la "
            f"registra y no la ejecuta. Corre en {donde}, con las credenciales de quien la "
            f"usa. Lo que la plataforma aporta aquí es el registro, la declaración "
            f"responsable y la revisión posterior.",
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
        raise RechazoDeEjecucion(423, detalle)

    return version


async def _traer_de_fuera(
    funcion: HubFuncion, contrato: ContratoFuncion, urls: dict[str, str]
) -> tuple[dict[str, bytes], dict[str, str]]:
    """AUT.8 — lo que hay que traer de fuera se trae **antes** de tocar el sandbox y antes de
    validar la entrada contra el contrato: una URL rechazada no puede haber gastado una
    ejecución ni dejado rastro de algo que no ocurrió.

    El guion recibe el contenido por el camino de un fichero subido a mano, así que **no se
    entera de que hubo red**: abrir la red no cambia el protocolo del guion ni lo que el
    auditor le permite.
    """
    bajados: dict[str, bytes] = {}
    nombres_bajados: dict[str, str] = {}
    if not urls:
        return bajados, nombres_bajados

    # **Todo lo que se pueda rechazar sin red, se rechaza antes de salir a red** (PR #210).
    # Una petición que va a dar 422 no puede haber hablado antes con un servidor de fuera:
    # el GET habría ocurrido igual, y el registro diría que no pasó nada.
    if funcion.origen == "paquete":
        # Una empaquetada corre en el proceso del servidor y se trae lo que necesita por su
        # cuenta: darle además el contenido sería un segundo camino para lo mismo. Se
        # rechaza en vez de ignorarlo, porque aceptar `urls` y no entregar nada dejaría a
        # quien integra buscando por qué su slot llega vacío.
        raise RechazoDeEjecucion(
            422,
            f"«{funcion.nombre}» es una función empaquetada: corre en el proceso "
            "del servidor y se trae lo que necesita por su cuenta, así que no "
            "acepta `urls`. Los orígenes declarados son para las de autoservicio, "
            "que corren en el sandbox y no tienen red.",
        )
    declarados = {s.slot_id for s in contrato.slots}
    ajenos = sorted(set(urls) - declarados)
    if ajenos:
        raise RechazoDeEjecucion(
            422,
            f"el contrato no declara los slots {ajenos}, así que no se baja nada para "
            f"ellos. Declara: {sorted(declarados)}.",
        )

    # El tope **acumulado** de la entrada se aplica mientras se baja, no al final: cada
    # descarga lee como mucho lo que queda. Si no, cinco URLs de 50 MB ocupaban 250 MB antes
    # de que el tope de 64 dijera nada.
    restante = MAXIMO_BYTES_DE_ENTRADA
    for slot, url in urls.items():
        tope = min(MAXIMO_BYTES_DESCARGA, restante)
        try:
            contenido, nombre = await descargar_de_un_origen_declarado(
                url, origenes=contrato.origenes, maximo_bytes=tope
            )
        except OrigenNoDeclarado as fallo:
            raise RechazoDeEjecucion(422, str(fallo)) from fallo
        except Exception as fallo:  # noqa: BLE001 — se traduce, no se deja subir opaco
            # 502 y no 500: el fallo es del servidor de fuera, no de la petición. Quien
            # integra necesita distinguirlo para saber si reintentar.
            raise RechazoDeEjecucion(
                502,
                f"no se pudo traer «{url}» para el slot «{slot}»: {fallo}. El origen "
                f"está declarado, así que el problema es del servidor remoto.",
            ) from fallo
        bajados[slot] = contenido
        # El nombre real de la descarga, con su extensión: pandas elige el motor por ella,
        # y sin él el documento llegaba al guion como `<slot>.bin`.
        nombres_bajados[slot] = nombre
        restante -= len(contenido)
    return bajados, nombres_bajados


async def _correr(
    funcion: HubFuncion,
    version: HubFuncionVersion,
    contrato: ContratoFuncion,
    *,
    ficheros: dict[str, str],
    parametros: dict[str, Any],
    bajados: dict[str, bytes],
    nombres_bajados: dict[str, str],
    sandbox: SandboxClient,
    almacen: StorageService,
) -> Any:
    if funcion.origen == "paquete":
        # In-process, por el camino de FUN.5. No pasa por el sandbox y no se finge lo contrario.
        from server.app.modules.redaccion.funciones_paquete import ejecutar_empaquetada

        try:
            return await ejecutar_empaquetada(
                funcion.entry_point or "",
                ficheros=ficheros,
                parametros=parametros,
                almacen=almacen,
            )
        except EntradaNoCumpleElContrato as fallo:
            raise RechazoDeEjecucion(422, str(fallo)) from fallo
        except Exception as fallo:  # noqa: BLE001 — se traduce, no se deja subir opaco
            raise RechazoDeEjecucion(
                502, f"la función empaquetada «{funcion.nombre}» falló al ejecutarse: {fallo}"
            ) from fallo

    try:
        return await ejecutar_funcion(
            contrato=contrato,
            code=version.code or "",
            ficheros=ficheros,
            almacen=almacen,
            contenidos=bajados,
            nombres_de_los_traidos=nombres_bajados,
            parametros=parametros,
            sandbox=sandbox,
            timeout_seconds=TIMEOUT_SEGUNDOS,
        )
    except EntradaNoCumpleElContrato as fallo:
        # 422 tipado y **sin tocar el sandbox**: `ejecutar_funcion` valida delante.
        raise RechazoDeEjecucion(422, str(fallo)) from fallo
    except TimeoutError as fallo:
        raise RechazoDeEjecucion(
            504,
            f"la función agotó el tiempo de ejecución ({TIMEOUT_SEGUNDOS} s). Es el "
            "fallo más probable con un fichero grande; reintentar con menos datos o "
            "revisar el script.",
        ) from fallo
    except SandboxUnavailableError as fallo:
        # 503 y no 500, y lo destapó el `curl` real con el sandbox apagado. En producción el
        # sandbox es otro servicio, así que «no responde» es la causa más probable de un
        # fallo **que no es de quien integra**: un 500 le dice «algo se rompió, mira si es
        # tuyo» y un 503 con el motivo le dice «no es tuyo, reintenta». Es la diferencia
        # entre un aviso al equipo de la plataforma y una tarde depurando código ajeno.
        raise RechazoDeEjecucion(
            503,
            "el servicio de ejecución (sandbox) no responde, así que la función no se "
            f"ha ejecutado. No es un problema de tu petición: reintenta en unos "
            f"minutos. Detalle: {fallo}",
        ) from fallo


async def ejecutar_version(
    session: AsyncSession,
    funcion: HubFuncion,
    *,
    numero_de_version: int,
    ficheros: dict[str, str],
    urls: dict[str, str],
    parametros: dict[str, Any],
    organizacion: Any,
    sandbox: SandboxClient,
    almacen: StorageService,
) -> Ejecucion:
    """Ejecuta `funcion@numero_de_version` y guarda lo que produzca. Lanza `RechazoDeEjecucion`."""
    version = await _version_que_puede_correr(session, funcion, numero_de_version)
    contrato = ContratoFuncion.model_validate(version.contrato_entrada or {})
    bajados, nombres_bajados = await _traer_de_fuera(funcion, contrato, urls)
    salida = await _correr(
        funcion,
        version,
        contrato,
        ficheros=ficheros,
        parametros=parametros,
        bajados=bajados,
        nombres_bajados=nombres_bajados,
        sandbox=sandbox,
        almacen=almacen,
    )

    # AUT.7 — lo que el guion produjo se guarda **antes** de componer la respuesta: si el
    # almacenamiento falla, es mejor un 5xx sin respuesta que una respuesta con referencias a
    # ficheros que no están.
    guardados: list = []
    brutos = artefactos_en_bruto(salida)
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
    return Ejecucion(version=version, contrato=contrato, salida=salida, guardados=guardados)
