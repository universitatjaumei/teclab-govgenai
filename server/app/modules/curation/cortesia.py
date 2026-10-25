"""Cortesía del rastreo: pausa por host, `robots.txt` e identificación (RAS.1).

Deploy: edge

El rastreador se va a apuntar al portal de la propia institución. Miles de peticiones seguidas
desde una IP, sin pausa y sin leer `robots.txt`, figuran en los registros del servidor web como lo
que parecen, y quien los mira no tiene forma de saber quién es ni a quién escribir. Esto es lo que
convierte el módulo en una herramienta que se puede usar en casa.

Tres decisiones:

* **La cortesía es el defecto.** Un sitio dado de alta sin tocar la configuración rastrea despacio
  y respetando `robots.txt`. Ir rápido exige decirlo (`delay_seconds: 0`), y entonces consta en la
  configuración del sitio quién lo decidió.
* **Vive en la capa de descarga**, no en el bucle del spider, porque hay dos bucles: el BFS del
  spider y el recorrido por URL de `SiteCrawler`, que llama a `_fetch` directamente. Ponerla en uno
  solo dejaría el otro sin ella y no se notaría.
* **Por host.** Esperar por un servidor mientras se martillea otro no protege a nadie.
"""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse, urlunparse
from urllib.robotparser import RobotFileParser

#: Un segundo entre peticiones al mismo servidor. No es un número mágico: es el orden de magnitud
#: que separa «un rastreador» de «un incidente» en los registros de un servidor web.
PAUSA_POR_DEFECTO = 1.0

#: Una petición a la vez por host. El bucle ya es secuencial; el semáforo está para que siga
#: siéndolo si alguien paraleliza más arriba.
CONCURRENCIA_POR_DEFECTO = 1

#: Media hora. Un apartado de un portal se rastrea en minutos; pasado esto, algo no va como se
#: pensaba y es mejor entregar un rastreo parcial que consta como parcial.
PRESUPUESTO_POR_DEFECTO_SEGUNDOS = 1800

_VERSION = "1.0"


#: Tres intentos. Un `timeout` de red se recupera casi siempre al segundo; si tres fallan
#: seguidos con espera creciente, ya no es la red pasajera.
REINTENTOS_POR_DEFECTO = 3

#: Espera del primer reintento, que se duplica en cada vuelta.
ESPERA_INICIAL_DE_REINTENTO = 1.0


class FalloTrasReintentos(Exception):
    """La URL falló todas las veces. Sólo esto llega a ser un hallazgo, y con su recuento."""

    def __init__(self, url: str, intentos: int, causa: BaseException) -> None:
        super().__init__(f"«{url}» falló {intentos} veces; la última: {causa}")
        self.url = url
        self.intentos = intentos
        self.causa = causa


def es_transitorio(fallo: BaseException) -> bool:
    """`True` si merece otro intento.

    Un 404 **no** es transitorio: es una respuesta, y significa que esa página ya no está.
    Reintentarla es tráfico inútil contra un servidor que ya ha contestado. Un 5xx, un `timeout`
    o un fallo de conexión sí: de ellos no se puede concluir nada sobre la página.
    """
    codigo = getattr(getattr(fallo, "response", None), "status_code", None)
    if codigo is not None:
        return codigo >= 500 or codigo == 429
    if isinstance(fallo, (TimeoutError, ConnectionError, OSError)):
        return True
    nombre = type(fallo).__name__.lower()
    return "timeout" in nombre or "connect" in nombre or "read" in nombre


def clasificar_fallo(fallo: BaseException) -> str:
    """`not_found`, `transient` o `unknown`: lo que el informe puede afirmar de la causa."""
    codigo = getattr(getattr(fallo, "response", None), "status_code", None)
    if codigo == 404 or codigo == 410:
        return "not_found"
    if es_transitorio(fallo):
        return "transient"
    if codigo is not None:
        return "client_error"
    return "unknown"


class RutaProhibidaPorRobots(Exception):
    """La URL está excluida por el `robots.txt` del sitio. No se pide, y no es un error del sitio."""

    def __init__(self, url: str) -> None:
        super().__init__(f"«{url}» está excluida por el robots.txt de su servidor.")
        self.url = url


def user_agent_de_rastreo(contacto: str) -> str:
    """La cadena con la que nos presentamos. Sin contacto, lo dice en vez de callarlo."""
    quien = contacto.strip() or "sin contacto configurado"
    return f"GovGenAI-Curacion/{_VERSION} (+{quien})"


class CortesiaDeRastreo:
    """Pausa, exclusiones y concurrencia de un rastreo, por host.

    El reloj y la espera se inyectan: un test tiene que poder comprobar que **se espera lo que
    toca** sin pagar la espera, y una pausa de un segundo por petición son minutos de suite.
    """

    def __init__(
        self,
        *,
        delay_seconds: float = PAUSA_POR_DEFECTO,
        respect_robots: bool = True,
        contacto: str = "",
        max_concurrency: int = CONCURRENCIA_POR_DEFECTO,
        max_retries: int = REINTENTOS_POR_DEFECTO,
        sleep_fn: Callable[[float], Awaitable[None]] | None = None,
        clock_fn: Callable[[], float] | None = None,
    ) -> None:
        self.pausa = max(0.0, float(delay_seconds))
        self.respetar_robots = bool(respect_robots)
        self.user_agent = user_agent_de_rastreo(contacto)
        self.concurrencia = max(1, int(max_concurrency))
        self.reintentos = max(1, int(max_retries))

        self._dormir = sleep_fn or asyncio.sleep
        self._reloj = clock_fn or (lambda: asyncio.get_event_loop().time())

        self._ultima_peticion: dict[str, float] = {}
        self._robots: dict[str, RobotFileParser | None] = {}
        self._semaforos: dict[str, asyncio.Semaphore] = {}

    # -- consultas -----------------------------------------------------------

    def host_de(self, url: str) -> str:
        partes = urlparse(url)
        return f"{partes.scheme}://{partes.netloc}"

    def pausa_efectiva_para(self, url: str) -> float:
        """La nuestra, o la que el sitio declare si es mayor.

        Un `Crawl-delay` más corto que el nuestro es un permiso, no una obligación: el sitio nos
        autoriza a ir más rápido y no tenemos por qué aceptarlo.
        """
        declarada = self._crawl_delay_declarado(self.host_de(url))
        if declarada is None:
            return self.pausa
        return max(self.pausa, declarada)

    def _crawl_delay_declarado(self, host: str) -> float | None:
        robots = self._robots.get(host)
        if robots is None:
            return None
        try:
            valor = robots.crawl_delay("*")
        except Exception:  # noqa: BLE001 — robotparser no promete nada aquí
            return None
        return float(valor) if valor is not None else None

    # -- el paso por caja ----------------------------------------------------

    async def permitido(
        self, url: str, descargar: Callable[[str], Awaitable[tuple[str, dict]]]
    ) -> bool:
        """`False` si el `robots.txt` del host excluye la URL. Se consulta una vez por host."""
        if not self.respetar_robots:
            return True

        host = self.host_de(url)
        if host not in self._robots:
            self._robots[host] = await self._leer_robots(host, descargar)

        robots = self._robots[host]
        if robots is None:
            # Que un sitio no publique `robots.txt` no autoriza nada: sólo significa que no dice
            # nada. Se sigue con la pausa puesta.
            return True
        try:
            return bool(robots.can_fetch("*", url))
        except Exception:  # noqa: BLE001
            return True

    async def _leer_robots(
        self, host: str, descargar: Callable[[str], Awaitable[tuple[str, dict]]]
    ) -> RobotFileParser | None:
        partes = urlparse(host)
        destino = urlunparse((partes.scheme, partes.netloc, "/robots.txt", "", "", ""))
        try:
            cuerpo, _cabeceras = await descargar(destino)
        except Exception:  # noqa: BLE001 — 404, timeout, host sin robots: da igual cuál
            return None

        parser = RobotFileParser()
        parser.parse(cuerpo.splitlines())
        return parser

    async def esperar_turno(self, url: str) -> None:
        """Duerme lo que falte para respetar la pausa contra ese host."""
        pausa = self.pausa_efectiva_para(url)
        if pausa <= 0:
            return

        host = self.host_de(url)
        ultima = self._ultima_peticion.get(host)
        ahora = self._reloj()
        if ultima is not None:
            falta = pausa - (ahora - ultima)
            if falta > 0:
                await self._dormir(falta)
                ahora = self._reloj()
        self._ultima_peticion[host] = ahora

    async def con_reintentos(
        self, url: str, descargar: Callable[[str], Awaitable[tuple[str, dict]]]
    ) -> tuple[str, dict]:
        """Intenta la descarga, reintentando sólo lo que puede recuperarse.

        Sin esto, un `timeout` de diez segundos se convertía en un `crawl_error` crítico: en un
        rastreo grande, decenas de falsos positivos por causas de red mezclados con los hallazgos
        de verdad.
        """
        espera = ESPERA_INICIAL_DE_REINTENTO
        ultimo: BaseException | None = None

        for intento in range(1, self.reintentos + 1):
            try:
                return await descargar(url)
            except Exception as fallo:  # la clasificación decide qué hacer
                ultimo = fallo
                if not es_transitorio(fallo):
                    raise
                if intento == self.reintentos:
                    break
                await self._dormir(espera)
                espera *= 2

        assert ultimo is not None
        raise FalloTrasReintentos(url, self.reintentos, ultimo) from ultimo

    def turno_de(self, url: str) -> asyncio.Semaphore:
        host = self.host_de(url)
        if host not in self._semaforos:
            self._semaforos[host] = asyncio.Semaphore(self.concurrencia)
        return self._semaforos[host]


def cortesia_desde_config(
    config: dict[str, Any],
    *,
    contacto: str = "",
    sleep_fn: Callable[[float], Awaitable[None]] | None = None,
    clock_fn: Callable[[], float] | None = None,
) -> CortesiaDeRastreo:
    """La cortesía que declara la configuración del sitio, con los defectos conservadores."""
    return CortesiaDeRastreo(
        delay_seconds=config.get("delay_seconds", PAUSA_POR_DEFECTO),
        respect_robots=config.get("respect_robots", True),
        contacto=contacto,
        max_concurrency=config.get("max_concurrency", CONCURRENCIA_POR_DEFECTO),
        max_retries=config.get("max_retries", REINTENTOS_POR_DEFECTO),
        sleep_fn=sleep_fn,
        clock_fn=clock_fn,
    )
