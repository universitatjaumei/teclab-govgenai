"""Que el servidor no pida una URL que apunte a su propia red (APER.1).

Deploy: shared

**El defecto que cierra.** El rastreador de curación descargaba lo que le dijeran: `root_url`
llegaba como `str` sin validar desde `POST /hub/sites` y `POST /hub/site-reconnaissance`, y el
cliente seguía redirecciones. Cualquier **administrador de organización** podía hacer que el
servidor pidiera `http://169.254.169.254/…`, los otros contenedores del compose o cualquier
servicio HTTP sin autenticación de la red interna, y leer de vuelta el texto por el informe de
reconocimiento. Es el hallazgo M1 de la auditoría previa a abrir el repositorio.

**Dos piezas, porque hay dos momentos.**

- `assert_forma_publica` no pregunta al DNS: decide por el esquema y por la dirección si viene
  literal. Es síncrona a propósito —no hace E/S— y es la que valida la entrada de la API, así
  que quien se equivoca al dar de alta un sitio recibe un 422 con el motivo y no un rastreo que
  falla sin explicar por qué.
- `assert_destino_publico` resuelve el nombre y comprueba **todas** las direcciones. Se aplica en
  cada petición a través de `hook_de_destino_publico`, y eso incluye **cada salto de
  redirección**: httpx dispara los hooks de petición dentro del bucle de redirecciones, de modo
  que un portal público que redirige a una dirección privada no la alcanza. Comprobar sólo la URL
  de entrada no habría servido de nada, y es la mitad del defecto que se escapaba.

**Y el DNS rebinding, cerrado el 2026-09-26 (issue #161).** Este fichero decía, con razón, que no
lo cerraba: entre resolver el nombre y abrir la conexión httpx resolvía otra vez, y un DNS hostil
podía contestar una dirección pública a la primera pregunta y `169.254.169.254` a la segunda. En
la VM de GCP esa segunda respuesta llega al servidor de metadatos, donde están las credenciales de
la cuenta de servicio.

El problema no era qué se comprobaba sino **cuándo**, así que no se arregla comprobando mejor:
`fijar_destino_validado` resuelve **una vez** y deja la petición apuntando a esa dirección, con el
nombre conservado en `sni_hostname` y en la cabecera `Host` para que el certificado siga
validándose contra quien debe. Va en el **transporte** y no en un hook, porque un hook mira la
petición y la deja seguir: quien abre el socket es el transporte, y ahí es donde la ventana se
cierra.

**La válvula, y por qué existe.** Verificar curación sin salir a internet se hace con un
`http.server` en `127.0.0.1`, que es justo lo que esto bloquea. Sin una forma declarada de
permitirlo, el guardia se acabaría apagando entero para poder trabajar —y un guardia apagado a
mano no se vuelve a encender—. `CRAWLER_ALLOW_PRIVATE_TARGETS=true` lo permite y **producción se
niega a arrancar con ella puesta**, igual que con `SANDBOX_MODE=local`. La válvula es sobre
direcciones: `file://` sigue prohibido con ella encendida, porque nada lo necesita.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import socket
from typing import Awaitable, Callable
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

#: Resolver un nombre y devolver sus direcciones como texto.
Resolvedor = Callable[[str], Awaitable[list[str]]]

ESQUEMAS_PERMITIDOS = ("http", "https")


class DestinoNoPublico(ValueError):
    """La URL no se pide: o no es http(s), o su destino no está en la red pública."""


def _valvula_abierta() -> bool:
    """`CRAWLER_ALLOW_PRIVATE_TARGETS`, leída sin depender de que la configuración cargue.

    Se lee del entorno y no de `get_settings()` porque este módulo lo usa el rastreador, que
    corre también en guiones sin `JWT_SECRET_KEY` —`_nueva_cortesia` ya tiene el mismo cuidado—.
    Quien la pone en producción se encuentra el gate de `core/config.py` al arrancar.
    """
    return os.getenv("CRAWLER_ALLOW_PRIVATE_TARGETS", "").strip().lower() == "true"


def _direccion_o_none(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """La dirección si el host **es** una dirección; `None` si es un nombre."""
    candidato = host.strip()
    if candidato.startswith("[") and candidato.endswith("]"):
        candidato = candidato[1:-1]
    # Una dirección IPv6 puede traer el identificador de zona (`fe80::1%eth0`), que
    # `ip_address` no acepta y que no cambia si la dirección es pública o no.
    candidato, _, _ = candidato.partition("%")
    try:
        return ipaddress.ip_address(candidato)
    except ValueError:
        pass
    # Las formas cortas y numéricas de IPv4 —`127.1`, `2130706433`, `0x7f.1`— son direcciones
    # para `getaddrinfo`, o sea que **se conectan**, pero `ip_address` las rechaza y sin esto
    # pasarían por nombres. Es el rodeo de manual contra un guardia que sólo entiende la forma
    # larga. `inet_aton` acepta exactamente lo que acepta el sistema al conectar.
    try:
        return ipaddress.IPv4Address(socket.inet_aton(candidato))
    except (OSError, ipaddress.AddressValueError):
        return None


def _es_publica(direccion: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """`is_global` decide: excluye privadas, loopback, link-local, multicast y reservadas.

    Las IPv4 disfrazadas de IPv6 (`::ffff:127.0.0.1`) caen aquí también, porque `::ffff:0:0/96`
    está entre las redes privadas de IPv6 — y son el rodeo clásico contra una lista escrita a
    mano rango por rango. Por eso se pregunta por «es pública» y no se enumeran los rangos
    malos: una lista escrita a mano se queda corta en el primer rodeo que nadie previó.
    """
    return bool(direccion.is_global)


def assert_forma_publica(url: str) -> None:
    """Lo que se decide sin preguntar al DNS: el esquema y la dirección si viene literal.

    No hace E/S, así que la pueden llamar los validadores de los contratos de entrada.
    """
    partes = urlsplit((url or "").strip())

    if partes.scheme.lower() not in ESQUEMAS_PERMITIDOS:
        raise DestinoNoPublico(
            f"«{url}» no es una dirección web: sólo se piden URL "
            f"{' o '.join(ESQUEMAS_PERMITIDOS)}."
        )

    host = partes.hostname
    if not host:
        raise DestinoNoPublico(f"«{url}» no dice a qué servidor apunta.")

    direccion = _direccion_o_none(host)
    if direccion is None:
        # Es un nombre: lo que se pueda decir de él se dirá al resolverlo.
        return

    if not _es_publica(direccion) and not _valvula_abierta():
        raise DestinoNoPublico(
            f"«{url}» apunta a {direccion}, que no es una dirección de la red pública. "
            "El servidor no pide direcciones de su propia red. Para el portal de pruebas "
            "local, CRAWLER_ALLOW_PRIVATE_TARGETS=true (nunca en producción)."
        )


async def _resolver_por_dns(host: str) -> list[str]:
    """Las direcciones del nombre, por el resolvedor del sistema y sin bloquear el bucle."""
    bucle = asyncio.get_running_loop()
    infos = await bucle.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


async def assert_destino_publico(url: str, *, resolver: Resolvedor | None = None) -> None:
    """La comprobación completa: la forma, y el nombre resuelto a direcciones públicas.

    Si el nombre resuelve a varias direcciones, **todas** tienen que ser públicas. Un nombre que
    publica una pública y una privada es el patrón del rebinding, y elegir la buena no es
    trabajo de quien pide la página.
    """
    assert_forma_publica(url)

    host = urlsplit(url.strip()).hostname or ""
    if _direccion_o_none(host) is not None:
        return  # Era una dirección literal: `assert_forma_publica` ya ha decidido.

    if _valvula_abierta():
        logger.warning(
            "CRAWLER_ALLOW_PRIVATE_TARGETS está puesta: no se comprueba el destino de %s", host
        )
        return

    resolver = resolver or _resolver_por_dns
    try:
        direcciones = await resolver(host)
    except Exception as exc:  # cualquier fallo de resolución es un «no»
        raise DestinoNoPublico(
            f"«{host}» no se puede resolver ({type(exc).__name__}), así que no se pide. "
            "Un nombre que no resuelve tampoco se puede rastrear."
        ) from exc

    if not direcciones:
        raise DestinoNoPublico(f"«{host}» no resuelve a ninguna dirección.")

    for texto in direcciones:
        direccion = _direccion_o_none(texto)
        if direccion is None or not _es_publica(direccion):
            raise DestinoNoPublico(
                f"«{host}» resuelve a {texto}, que no es una dirección de la red pública. "
                "El servidor no pide direcciones de su propia red."
            )


async def _direcciones_publicas(host: str, resolver: Resolvedor) -> list[str]:
    """Las direcciones del nombre, **todas** comprobadas. Levanta si alguna no es pública."""
    try:
        direcciones = await resolver(host)
    except Exception as exc:  # cualquier fallo de resolución es un «no»
        raise DestinoNoPublico(
            f"«{host}» no se puede resolver ({type(exc).__name__}), así que no se pide. "
            "Un nombre que no resuelve tampoco se puede rastrear."
        ) from exc

    if not direcciones:
        raise DestinoNoPublico(f"«{host}» no resuelve a ninguna dirección.")

    for texto in direcciones:
        direccion = _direccion_o_none(texto)
        if direccion is None or not _es_publica(direccion):
            raise DestinoNoPublico(
                f"«{host}» resuelve a {texto}, que no es una dirección de la red pública. "
                "El servidor no pide direcciones de su propia red."
            )
    return direcciones


async def fijar_destino_validado(request, *, resolver: Resolvedor | None = None) -> None:
    """Deja la petición apuntando a la dirección **que se acaba de validar** (issue #161).

    **Cierra la ventana del DNS rebinding, que hasta hoy estaba admitida por escrito en este
    mismo fichero.** El problema no era qué se comprobaba sino *cuándo*: por buena que fuera la
    comprobación, `httpx` resolvía el nombre otra vez para conectar, y un DNS hostil podía
    contestar una dirección pública a la primera pregunta y `169.254.169.254` a la segunda. En
    esta VM, esa segunda respuesta llega al servidor de metadatos de GCP, donde están las
    credenciales de la cuenta de servicio.

    Se resuelve **una sola vez** y se conecta a eso: la URL pasa a llevar la dirección, y el
    nombre sobrevive en `sni_hostname` y en la cabecera `Host`. Las dos cosas son necesarias y no
    son cosmética — el certificado se valida contra el nombre, y un servidor que aloja varios
    sitios decide por la cabecera—. Cambiar la URL a secas convertiría un arreglo de seguridad en
    una avería.

    Se aplica en **cada** petición, redirecciones incluidas, porque va en el transporte.
    """
    assert_forma_publica(str(request.url))

    host = request.url.host
    if not host or _direccion_o_none(host) is not None:
        return  # Una dirección literal ya la decidió `assert_forma_publica`.

    if _valvula_abierta():
        logger.warning(
            "CRAWLER_ALLOW_PRIVATE_TARGETS está puesta: no se comprueba el destino de %s", host
        )
        return

    direcciones = await _direcciones_publicas(host, resolver or _resolver_por_dns)

    # La cabecera lleva el puerto sólo si la URL lo llevaba explícito; si no, se omite, que es lo
    # que espera el otro extremo para los puertos por defecto.
    autoridad = host if request.url.port is None else f"{host}:{request.url.port}"
    request.url = request.url.copy_with(host=direcciones[0])
    request.headers["Host"] = autoridad
    request.extensions = {**request.extensions, "sni_hostname": host}


def transporte_a_la_direccion_validada(*, resolver: Resolvedor | None = None, **kwargs):
    """El transporte de `httpx` que conecta a la dirección ya comprobada.

    Va en el transporte y no en un hook de petición porque **un hook no puede impedir la segunda
    resolución**: mira la petición y la deja seguir, y quien conecta es el transporte. Aquí se
    reescribe el destino antes de abrir la conexión, que es el único sitio donde la ventana se
    cierra de verdad.
    """
    import httpx

    class _Transporte(httpx.AsyncHTTPTransport):
        async def handle_async_request(self, request):
            # **La dirección es para el socket; la URL lógica sigue siendo la del portal.**
            #
            # Lo señaló la revisión de la PR #168 y era una regresión de verdad: dejar la
            # petición apuntando a la dirección se filtra a `Response.url`, que es lo que
            # `GenericSpider._descargar` guarda como `x-final-url` y lo que `crawl()` usa para
            # deduplicar y para filtrar por dominio. Cada página con nombre se habría registrado
            # como `https://93.184.216.34/…`.
            #
            # Se restaura en `finally` y no al final del camino bueno: httpx **reutiliza este
            # mismo objeto** para los reintentos y para construir la siguiente petición de una
            # redirección, así que dejarlo con la dirección tras un error sería peor que no
            # restaurarlo nunca.
            original = request.url
            await fijar_destino_validado(request, resolver=resolver)
            try:
                return await super().handle_async_request(request)
            finally:
                request.url = original

    return _Transporte(**kwargs)


def hook_de_destino_publico(*, resolver: Resolvedor | None = None):
    """El hook de petición de `httpx`, que se dispara **también en cada redirección**.

    Es la pieza que hace que el arreglo valga: comprobar sólo la URL de entrada deja pasar un
    portal público que redirige a una dirección privada, y eso estaba comprobado contra la
    versión instalada antes de escribir el arreglo.
    """

    async def comprobar(request) -> None:
        await assert_destino_publico(str(request.url), resolver=resolver)

    return comprobar
