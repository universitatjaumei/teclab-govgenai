"""El origen **empaquetado** del catálogo: funciones que llegan por *entry point* (FUN.5).

Deploy: edge — una función de paquete procesa documentos del cliente, igual que una de
autoservicio.

Es la respuesta a «¿qué añade la plataforma frente a mantener el script en el editor de quien
programa?». Un equipo con repositorio, CI y semver **mantiene el código donde lo escribe**; lo que
la plataforma se queda es la revisión, el contrato, el `RunManifest` y la trazabilidad. Y se queda
con ellos por el **mismo** camino que una función de autoservicio: un solo `ContratoFuncion`, un
solo validador, un solo resolutor, un solo nodo. Si hubiera un segundo camino, sería el que se
queda sin auditar.

Tres decisiones, y las tres siguen el precedente ya escrito en
`agents_hub/agent/public_graphs/plugins.py`, que es el cargador de *entry points* que este
proyecto ya tiene en producción:

* **Se falla en alto, nunca «avisar y seguir».** Un contrato incoherente deja el arranque
  detenido nombrando paquete y función. Con un `warning`, el servidor queda en pie sin esa
  función y el síntoma aparece mucho más tarde como «la plantilla referencia algo que no
  existe», sin ninguna pista del paquete roto.
* **La frontera de confianza se dice sin rodeos**: `run` corre **in-process, con los datos del
  cliente y sin sandbox**. La confianza está en quien instala, igual que en un plugin de pytest.
  No se finge otra cosa; lo que se audita en autoservicio es el código porque lo escribe alguien
  sin repositorio, y aquí el control equivalente es quién puede hacer `pip install` en el
  despliegue.
* **`_puntos_de_entrada` está aislado a propósito**: es la costura por la que los tests inyectan.
  Instalar distribuciones de verdad en la suite sería lento y frágil —lo midió PLG y lo dejó
  escrito— y lo que importa comprobar es el comportamiento del cargador ante lo que
  `importlib.metadata` devuelva.

**El anclaje es por mayor y no exacto**, que es justamente lo que compra el semver: una plantilla
anclada a la versión del catálogo que trajo 1.2.0 sigue ejecutando cuando se instala 1.3.0. Lo que
**no** se aproxima es el manifiesto: anota la versión instalada **exacta** y su hash, porque «qué
corrió» no admite «algo compatible».
"""
from __future__ import annotations

import asyncio
import hashlib
import importlib.metadata as md
import inspect
import re
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from server.app.modules.redaccion.contracts.funciones import (
    ContratoFuncion,
    EntradaValidada,
    contrato_coherente,
    validar_entrada,
)
from server.app.modules.redaccion.pipelines.contracts import ExtractionResult

#: El grupo de *entry points*. Mismo prefijo `govgenai.` que los tres de PLG: un solo espacio de
#: nombres para todo lo que este proyecto deja extender.
GRUPO_FUNCIONES = "govgenai.funciones"

#: Semver estricto de tres números, que es lo que el anclaje por mayor necesita para existir. Se
#: admite el sufijo de pre-lanzamiento porque un equipo publica `1.3.0rc1` antes de `1.3.0`, y
#: rechazarlo obligaría a no probar nunca en la plataforma lo que se va a instalar en ella.
_SEMVER = re.compile(r"^(?P<mayor>\d+)\.(?P<menor>\d+)\.(?P<parche>\d+)(?:[-.]?[0-9A-Za-z.]+)?$")


class PaqueteIncoherente(RuntimeError):
    """Un paquete declara algo que no se puede registrar. **Detiene el arranque.**"""


@dataclass(frozen=True)
class FuncionEmpaquetada:
    """El contrato público que un paquete de terceros exporta en su *entry point*.

    Vive aquí y no en un SDK aparte porque hoy tiene **un** consumidor; cuando aparezca el
    segundo —REG ya tiene su propio patrón de extensión— se mueve. Publicar un paquete SDK para
    un solo consumidor es prometer una superficie estable antes de saber cuál es.

    `contrato` es el `ContratoFuncion` de FUN.2 **sin variantes**: una función corporativa también
    declara finalidad y categorías de datos. La Instrucció no exime al nivel 3 de declarar; lo que
    cambia en el nivel 3 es quién valora, no si hay declaración.
    """

    nombre: str
    version: str
    contrato: ContratoFuncion
    run: Callable[[EntradaValidada], ExtractionResult]


@dataclass
class ResumenDeSincronizacion:
    """Lo que la sincronización hizo, para poder decirlo en el log del arranque.

    Sin recuento, «sincronizado» y «no había nada» se leen igual — la misma razón por la que la
    migración de FUN.3 cuenta sus bloques.
    """

    funciones_nuevas: int = 0
    versiones_nuevas: int = 0
    versiones_desinstaladas: int = 0
    entry_points: list[str] = field(default_factory=list)


def _puntos_de_entrada(grupo: str) -> Iterable[Any]:
    """La costura por la que los tests inyectan. Ver el encabezado del módulo."""
    return md.entry_points(group=grupo)


def _nombre_de_distribucion(punto: Any) -> str:
    """De qué paquete viene, para poder nombrarlo en los errores.

    `dist` es opcional en `importlib.metadata`: cuando falta se dice «distribución desconocida»
    en vez de reventar mientras se construye un mensaje de error, que convertiría un fallo
    legible en un `AttributeError` sin contexto.
    """
    dist = getattr(punto, "dist", None)
    nombre = getattr(dist, "name", None) if dist is not None else None
    return nombre or "distribucion-desconocida"


def mayor_de(version: str) -> int:
    """El número mayor de una versión semver. Es la unidad del anclaje."""
    casa = _SEMVER.match(version or "")
    if casa is None:
        raise PaqueteIncoherente(
            f"«{version}» no es una versión semver de tres números (por ejemplo «1.2.0»). El "
            "anclaje de una función empaquetada es por mayor, así que sin semver no hay anclaje "
            "posible."
        )
    return int(casa.group("mayor"))


def _descriptor_coherente(punto: Any, descriptor: Any) -> FuncionEmpaquetada:
    """Comprueba la forma del descriptor y devuelve uno tipado.

    Se comprueba **al descubrir** y no en la primera ejecución, por lo mismo que PLG comprueba
    el protocolo de un pipeline al arrancar: si no, el fallo sale delante de quien pidió un
    informe.
    """
    distribucion = _nombre_de_distribucion(punto)
    contexto = f"la función «{punto.name}» del paquete «{distribucion}»"

    nombre = getattr(descriptor, "nombre", None)
    version = getattr(descriptor, "version", None)
    contrato = getattr(descriptor, "contrato", None)
    run = getattr(descriptor, "run", None)

    if not isinstance(nombre, str) or not nombre.strip():
        raise PaqueteIncoherente(f"{contexto} no declara nombre.")
    if not isinstance(contrato, ContratoFuncion):
        raise PaqueteIncoherente(
            f"{contexto} no trae un `ContratoFuncion`. Es el mismo objeto que declara una "
            "función de autoservicio: un solo contrato y un solo validador para los dos "
            "orígenes."
        )
    if not callable(run):
        raise PaqueteIncoherente(
            f"{contexto} no apunta a algo invocable en `run`. Tiene que ser "
            "`(EntradaValidada) -> ExtractionResult`."
        )

    # El validador de FUN.2, sin ninguna rama «si es paquete».
    try:
        contrato_coherente(contrato)
    except ValueError as exc:
        raise PaqueteIncoherente(f"{contexto} tiene un contrato incoherente: {exc}") from exc

    try:
        mayor_de(str(version))
    except PaqueteIncoherente as exc:
        raise PaqueteIncoherente(f"{contexto}: {exc}") from exc

    return FuncionEmpaquetada(
        nombre=nombre, version=str(version), contrato=contrato, run=run
    )


def _sha_de_la_fuente(run: Callable[..., Any]) -> str:
    """El hash de la fuente de `run`.

    El código **no se copia** a la base —divergiría del `pip install`, y entonces habría dos
    verdades— pero el hash sí: es lo que permite contestar meses después si lo que corrió era
    esto. Si la fuente no se puede leer (un `run` compilado, un builtin), se hashea su
    identificación cualificada: peor que nada es no poder decir nada.
    """
    try:
        fuente = inspect.getsource(run)
    except (OSError, TypeError):
        fuente = f"{getattr(run, '__module__', '?')}.{getattr(run, '__qualname__', repr(run))}"
    return hashlib.sha256(fuente.encode("utf-8")).hexdigest()


#: Lo descubierto en este proceso: `entry_point` → descriptor. La ejecución lo consulta, porque
#: el `run` es un callable y no cabe en la base de datos.
_INSTALADAS: dict[str, FuncionEmpaquetada] = {}


def descubrir() -> dict[str, FuncionEmpaquetada]:
    """Los descriptores instalados, por `entry_point` («distribución:nombre»).

    Un nombre duplicado **detiene el arranque**: el que ganara dependería del orden de carga de
    `importlib.metadata`, que nadie controla, y no daría ningún síntoma.
    """
    encontradas: dict[str, FuncionEmpaquetada] = {}
    for punto in _puntos_de_entrada(GRUPO_FUNCIONES):
        distribucion = _nombre_de_distribucion(punto)
        try:
            cargado = punto.load()
        except Exception as exc:  # se reenvía con contexto y se aborta
            raise PaqueteIncoherente(
                f"el entry point «{punto.name}» de «{distribucion}» no se puede cargar: {exc}. "
                "El arranque se detiene a propósito."
            ) from exc

        descriptor = _descriptor_coherente(punto, cargado)
        clave = f"{distribucion}:{descriptor.nombre}"
        if clave in encontradas:
            raise PaqueteIncoherente(
                f"dos entry points declaran «{clave}». El que ganara dependería del orden de "
                "carga. Desinstala uno de los dos."
            )
        encontradas[clave] = descriptor
    return encontradas


async def sincronizar_paquetes(session: Any) -> ResumenDeSincronizacion:
    """Pone el catálogo al día con lo que está instalado. Idempotente.

    **Lo que no está instalado no se borra**: pasa a `no_instalada`. Hay `RunManifest` que citan
    una versión por id, y un manifiesto que apunta a una fila inexistente no se puede auditar —
    la misma razón por la que el `downgrade` de FUN.3 tampoco borra el catálogo.
    """
    from sqlalchemy import select

    from server.app.modules.redaccion.database.models import (
        HubFuncion,
        HubFuncionVersion,
    )

    instaladas = descubrir()
    _INSTALADAS.clear()
    _INSTALADAS.update(instaladas)

    resumen = ResumenDeSincronizacion(entry_points=sorted(instaladas))

    existentes = {
        f.entry_point: f
        for f in (
            await session.execute(
                select(HubFuncion).where(HubFuncion.origen == "paquete")
            )
        ).scalars().all()
        if f.entry_point
    }

    for clave, descriptor in instaladas.items():
        funcion = existentes.get(clave)
        if funcion is None:
            funcion = HubFuncion(
                id=uuid.uuid4(),
                nombre=descriptor.nombre,
                descripcion=descriptor.contrato.finalidad or "",
                organizacion_id=None,
                origen="paquete",
                entry_point=clave,
                # Una función empaquetada **nace publicada**: la instala quien opera el
                # despliegue, así que su alcance ya es de plataforma y pedir una promoción
                # después sería pedir permiso para algo que ya ocurrió.
                publicada_en=datetime.now(timezone.utc),
            )
            session.add(funcion)
            await session.flush()
            existentes[clave] = funcion
            resumen.funciones_nuevas += 1

        versiones = (
            await session.execute(
                select(HubFuncionVersion)
                .where(HubFuncionVersion.funcion_id == funcion.id)
                .order_by(HubFuncionVersion.version)
            )
        ).scalars().all()

        instalada = next(
            (v for v in versiones if v.version_paquete == descriptor.version), None
        )
        if instalada is None:
            instalada = HubFuncionVersion(
                id=uuid.uuid4(),
                funcion_id=funcion.id,
                version=(versiones[-1].version + 1) if versiones else 1,
                code=None,
                version_paquete=descriptor.version,
                contrato_entrada=descriptor.contrato.model_dump(mode="json"),
                contrato_salida={"kind": "ExtractionResult"},
                code_sha256=_sha_de_la_fuente(descriptor.run),
                estado="registrada",
                # Lo escribió un equipo, no un modelo. No es una puerta: es lo que la revisión
                # posterior quiere poder ver.
                autoria="persona",
                finalidad=descriptor.contrato.finalidad,
                categorias_datos=list(descriptor.contrato.categorias_datos),
            )
            session.add(instalada)
            await session.flush()
            versiones = list(versiones) + [instalada]
            resumen.versiones_nuevas += 1
        elif instalada.estado == "no_instalada":
            # Reinstalar la misma versión la devuelve a la vida sin crear un ordinal nuevo.
            instalada.estado = "registrada"

        for version in versiones:
            if version is instalada:
                continue
            if version.estado == "registrada":
                version.estado = "no_instalada"
                resumen.versiones_desinstaladas += 1

    # Y las funciones de paquete que ya no aporta nadie: todas sus versiones fuera de servicio.
    for clave, funcion in existentes.items():
        if clave in instaladas:
            continue
        versiones = (
            await session.execute(
                select(HubFuncionVersion).where(HubFuncionVersion.funcion_id == funcion.id)
            )
        ).scalars().all()
        for version in versiones:
            if version.estado == "registrada":
                version.estado = "no_instalada"
                resumen.versiones_desinstaladas += 1

    return resumen


def descriptor_instalado(entry_point: str) -> FuncionEmpaquetada | None:
    """El descriptor vivo de ese `entry_point`, si está instalado en este proceso."""
    return _INSTALADAS.get(entry_point)


async def ejecutar_empaquetada(
    entry_point: str,
    *,
    ficheros: dict[str, str] | None = None,
    parametros: dict[str, Any] | None = None,
    almacen: Any = None,
) -> ExtractionResult:
    """Valida la entrada y llama al `run` del paquete. **La validación va delante.**

    Con ella detrás, una entrada mal formada se manifiesta como un `KeyError` dentro del código
    de un tercero; con ella delante, «falta el slot gastos». Es el mismo punto de validación que
    el sandbox de autoservicio, no un segundo.

    Un `run` síncrono —el caso normal: es código de análisis— va al executor de hilos. La regla
    de asincronía total no se relaja porque el código sea de un tercero: bloquear el bucle
    detiene todas las peticiones del proceso.
    """
    descriptor = _INSTALADAS.get(entry_point)
    if descriptor is None:
        raise PaqueteIncoherente(
            f"«{entry_point}» no está instalado en este proceso: no se puede ejecutar una "
            "función cuyo paquete no está presente."
        )

    entrada = validar_entrada(
        descriptor.contrato, ficheros=ficheros, parametros=parametros, almacen=almacen
    )

    if inspect.iscoroutinefunction(descriptor.run):
        salida = await descriptor.run(entrada)
    else:
        salida = await asyncio.to_thread(descriptor.run, entrada)

    if not isinstance(salida, ExtractionResult):
        raise PaqueteIncoherente(
            f"«{entry_point}» devolvió {type(salida).__name__} y no un `ExtractionResult`. La "
            "salida se valida igual que la del sandbox: el nodo consume un solo tipo."
        )
    return salida
