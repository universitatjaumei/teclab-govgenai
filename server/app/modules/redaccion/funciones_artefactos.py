"""Los ficheros que una función produce: guardarlos, servirlos y caducarlos (AUT.7, issue #117).

Deploy: edge — son datos del cliente, producidos corriendo su código sobre sus documentos.
Módulo: informes.

La primera mitad de AUT.7 dejó al guion escribiendo en `output_dir` y al sandbox devolviendo el
contenido. Ahí todavía no vale de nada: el contenido viaja en una respuesta HTTP y se pierde.
Esto es lo que lo convierte en algo que una persona se lleva.

**Tres decisiones que no son obvias y que el resto del módulo da por hechas:**

* **Se guarda por `StorageService`, nunca en disco local.** Es la regla de portabilidad del
  proyecto, y aquí además es literal: el contenedor de la API es efímero y un fichero escrito en
  su disco no existe en la siguiente petición.
* **La clave lleva la ejecución dentro.** El nombre lo pone el guion y suele ser el mismo
  (`salida.csv`); sin la ejecución en la clave, la segunda corrida sobreescribiría el fichero
  que la primera entregó.
* **Caducar es dejar de servir *y* poder borrar.** Dejar de servirlo no libera el sitio, y el
  argumento de esta funcionalidad es de protección de datos: el barrido existe. Engancharlo a un
  programador es otra cosa y no está hecho — mientras tanto se llama a mano, pero se puede
  llamar, que es la diferencia entre una promesa con mecanismo y una sin él.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.core.sandbox_client import ArtefactoEnBruto
from server.app.core.storage import StorageService
from server.app.modules.redaccion.database.models import HubFuncionArtefacto


class ArtefactoNoDisponible(LookupError):
    """No existe, no es de quien pregunta, o ha caducado.

    **Una sola excepción para los tres casos, a propósito.** Quien la traduce responde 404, y
    distinguirlos en la respuesta contaría que el fichero existe en otra organización — que es
    justo lo que el resto del catálogo evita respondiendo 404 y no 403.
    """


def _clave(
    *,
    organizacion_id: uuid.UUID | None,
    funcion_id: uuid.UUID,
    ejecucion_id: uuid.UUID,
    nombre: str,
) -> str:
    """Dónde vive el fichero dentro del bucket de la organización.

    La organización va delante para que un barrido o una exportación por organización sea un
    prefijo y no un recorrido entero; y `plataforma` cuando no hay ninguna, en vez de dejar el
    segmento vacío, que produciría `//` y claves que no cuadran entre backends.
    """
    duenio = str(organizacion_id) if organizacion_id else "plataforma"
    return f"funciones/{duenio}/{funcion_id}/{ejecucion_id}/{nombre}"


async def guardar_artefactos(
    session: AsyncSession,
    brutos: list[ArtefactoEnBruto],
    *,
    almacen: StorageService,
    organizacion_id: uuid.UUID | None,
    funcion_id: uuid.UUID,
    version: int,
    retencion_dias: int,
    ejecucion_id: uuid.UUID | None = None,
) -> list[HubFuncionArtefacto]:
    """Guarda lo que el guion produjo y devuelve las filas, con su clave ya puesta.

    `ejecucion_id` se genera aquí si no viene: es lo que agrupa los ficheros de una corrida y lo
    que impide que dos corridas se pisen.

    **No hace `commit`.** Lo hace quien orquesta, para que el registro de actividad y los
    artefactos de una misma ejecución entren o no entren juntos.
    """
    corrida = ejecucion_id or uuid.uuid4()
    expira = datetime.now(timezone.utc) + timedelta(days=retencion_dias)

    filas: list[HubFuncionArtefacto] = []
    for bruto in brutos:
        clave = _clave(
            organizacion_id=organizacion_id,
            funcion_id=funcion_id,
            ejecucion_id=corrida,
            nombre=bruto.nombre,
        )
        await almacen.put(clave, bruto.contenido)
        fila = HubFuncionArtefacto(
            # **El id se pone aquí y no se deja al `default` de la columna.** Ese default lo
            # aplica SQLAlchemy al hacer `flush`, así que quien llama —que necesita el id para
            # componer la URL de descarga— se lo encontraba en `None` si no había flushado
            # todavía. Ponerlo explícito quita esa dependencia del orden.
            id=uuid.uuid4(),
            funcion_id=funcion_id,
            version=version,
            organizacion_id=organizacion_id,
            ejecucion_id=corrida,
            nombre=bruto.nombre,
            media_type=bruto.media_type,
            bytes=bruto.bytes,
            sha256=bruto.sha256,
            storage_key=clave,
            expira_en=expira,
        )
        session.add(fila)
        filas.append(fila)
    return filas


async def artefacto_para_descargar(
    session: AsyncSession,
    artefacto_id: uuid.UUID,
    *,
    organizacion_id: uuid.UUID | None,
    almacen: StorageService,
) -> tuple[HubFuncionArtefacto, bytes]:
    """La fila y su contenido, si quien pregunta puede llevárselo.

    Comprueba las tres cosas juntas —que existe, que es suya y que no ha caducado— y falla igual
    en los tres casos.
    """
    fila = await session.get(HubFuncionArtefacto, artefacto_id)
    if fila is None:
        raise ArtefactoNoDisponible(str(artefacto_id))

    if str(fila.organizacion_id) != str(organizacion_id):
        raise ArtefactoNoDisponible(str(artefacto_id))

    if _ya_caduco(fila):
        raise ArtefactoNoDisponible(str(artefacto_id))

    try:
        datos = await almacen.get(fila.storage_key)
    except FileNotFoundError as fallo:
        # La fila existe y el fichero no. Pasa si algo lo borró por fuera del barrido; se
        # responde lo mismo que si no existiera, porque para quien descarga es lo mismo.
        raise ArtefactoNoDisponible(str(artefacto_id)) from fallo

    return fila, datos


def _ya_caduco(fila: HubFuncionArtefacto) -> bool:
    """`expira_en` se compara en UTC **y con el tzinfo puesto**.

    SQLite —que es donde corren las bases desechables de los tests— devuelve la fecha sin zona,
    y comparar una naive con una aware revienta con `TypeError`. Se normaliza aquí en vez de en
    cada llamada.
    """
    expira = fila.expira_en
    if expira.tzinfo is None:
        expira = expira.replace(tzinfo=timezone.utc)
    return expira <= datetime.now(timezone.utc)


async def barrer_artefactos_caducados(
    session: AsyncSession, *, almacen: StorageService, tope: int = 500
) -> int:
    """Borra de verdad lo que ya no se sirve: del almacenamiento y de la tabla.

    Devuelve cuántos se llevó. `tope` acota el lote para que un barrido sobre un atraso grande no
    tenga la base ocupada indefinidamente.

    **El fichero primero y la fila después.** Al revés, un fallo entre las dos operaciones
    dejaría un fichero sin fila que lo nombre — o sea, sin nada que diga a quién pertenece ni
    cuándo caducó, que es exactamente lo que este módulo existe para que no pase.
    """
    ahora = datetime.now(timezone.utc)
    filas = (
        (
            await session.execute(
                select(HubFuncionArtefacto)
                .where(HubFuncionArtefacto.expira_en <= ahora)
                .limit(tope)
            )
        )
        .scalars()
        .all()
    )

    borrados = 0
    for fila in filas:
        await almacen.delete(fila.storage_key)
        await session.delete(fila)
        borrados += 1
    return borrados
