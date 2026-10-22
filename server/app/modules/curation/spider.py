"""Spider genérico BFS con control de profundidad, filtros regex y límite de páginas.

Deploy: edge

**Cortesía (RAS.1)**: la pausa por host, el `robots.txt` y el `User-Agent` identificable viven en
`_fetch`, que es por donde pasan los dos bucles —el BFS de aquí y el recorrido por URL de
`SiteCrawler`—. La configuración del sitio puede relajarla, nunca al revés por descuido.
"""

import re
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Protocol
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse

import regex as _regex

from server.app.modules.curation.cortesia import (
    PRESUPUESTO_POR_DEFECTO_SEGUNDOS,
    CortesiaDeRastreo,
    RutaProhibidaPorRobots,
    clasificar_fallo,
    cortesia_desde_config,
)
from server.app.modules.curation.secciones import busca_con_tope, predicado_de_ambito


#: Tope de páginas que se guardan en memoria para no volver a pedirlas. Con ~50 KB de HTML por
#: página, quinientas son unos 25 MB; por encima se vuelve a pedir, que es lento pero acotado.
_PAGINAS_RECORDADAS = 500

#: Lo que un rastreador de páginas no debe tratar como página. Un PDF del portal puede ser
#: contenido valioso, pero no por esta vía: `httpx` decodifica sus bytes como texto y lo que se
#: guarda es basura —26.872 «tokens» de cabecera binaria e idioma «bengalí», medido en el rastreo
#: real— que además lleva bytes nulos y Postgres rechaza la fila entera.
_EXTENSIONES_NO_LEGIBLES = (
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".ods", ".odp",
    ".zip", ".rar", ".7z", ".tar", ".gz", ".jpg", ".jpeg", ".png", ".gif", ".svg",
    ".webp", ".ico", ".mp3", ".mp4", ".avi", ".mov", ".wmv", ".exe", ".dmg", ".woff",
    ".woff2", ".ttf", ".eot", ".css", ".js", ".xml", ".rss", ".csv", ".json",
)

#: Los tipos que sí se leen. La extensión no siempre está —`/descarrega` sirve un PDF—, así que
#: la verdad la dice la cabecera de la respuesta.
_TIPOS_LEGIBLES = ("text/html", "application/xhtml", "text/plain", "text/markdown")


def _parece_descarga(url: str) -> bool:
    ruta = urlparse(url).path.lower()
    return ruta.endswith(_EXTENSIONES_NO_LEGIBLES)


def cliente_de_rastreo(user_agent: str, *, transport: Any = None):
    """El cliente con el que se pide cualquier página, y el único sitio donde se construye.

    **Es el punto donde se cierra el SSRF de APER.1.** `hook_de_destino_publico` se dispara en
    cada petición y `httpx` los dispara también en **cada salto de redirección**, así que un
    portal público que redirige a `169.254.169.254` o a un contenedor vecino no lo alcanza.
    Comprobar sólo la URL de entrada no habría servido: la redirección era la mitad del defecto.

    Que haya **una** función que construye el cliente es lo que hace la protección auditable —un
    `httpx.AsyncClient` suelto en este módulo la esquivaría sin que nada avisara—, y lo comprueba
    un guardarraíl. El `transport` es el asiento de los tests: con `MockTransport` se prueba la
    redirección sin red y con el hook de verdad puesto.
    """
    import httpx

    from server.app.core.red_publica import (
        hook_de_destino_publico,
        transporte_a_la_direccion_validada,
    )

    # **Dos capas, y hacen cosas distintas (issue #161).** El hook valida pronto y es quien da el
    # mensaje de por qué no se pide una URL, redirecciones incluidas. Pero un hook **no puede
    # cerrar el DNS rebinding**: mira la petición y la deja seguir, y quien resuelve el nombre
    # para conectar es el transporte. Por eso el transporte vuelve a comprobar y **conecta a la
    # dirección que acaba de validar**, que es el único punto donde esa ventana se cierra.
    #
    # Sí, eso resuelve el nombre dos veces. Es esfuerzo duplicado, no criterio duplicado: la
    # seguridad la garantiza la segunda, porque es la que decide a dónde se abre el socket.
    return httpx.AsyncClient(
        follow_redirects=True,
        timeout=10.0,
        headers={"User-Agent": user_agent},
        transport=transport if transport is not None else transporte_a_la_direccion_validada(),
        event_hooks={"request": [hook_de_destino_publico()]},
    )


#: Ninguna página de contenido necesita una URL así de larga. Es la red de seguridad contra las
#: trampas de rastreador que no se dejen ver por sus parámetros.
_LARGO_MAXIMO_DE_URL = 400


def url_de_pagina(url: str) -> str | None:
    """La URL que identifica **la página**, sin los parámetros de navegación. `None` si hay que
    descartarla.

    Medido en el segundo rastreo real del apartado: el conmutador de idioma del portal construye
    enlaces que llevan la URL actual dentro (`?urlRedirect=https://…&url=/centres/…`), así que cada
    página rastreada generaba una variante más larga de sí misma —espacio de URLs infinito, mismo
    contenido— y el detector las agrupaba después declarando 107 supersesiones falsas.

    La regla: un parámetro cuyo valor **es una URL o una ruta** es un ayudante de navegación, no
    identidad de página. Un parámetro de verdad (`?pagina=3`, `?id=42`) sí distingue contenido y se
    conserva.
    """
    if len(url) > _LARGO_MAXIMO_DE_URL:
        return None

    partes = urlparse(url)
    if not partes.query:
        return url

    conservados = [
        (clave, valor)
        for clave, valor in parse_qsl(partes.query, keep_blank_values=True)
        if not _parece_una_direccion(valor)
    ]
    if len(conservados) == len(parse_qsl(partes.query, keep_blank_values=True)):
        return url
    return partes._replace(query=urlencode(conservados)).geturl()


def clave_de_pagina(url: str) -> str:
    """Con qué se compara si dos URLs son **la misma página**, sin cambiar lo que se pide.

    Lo destapó el detector semántico en CUR.7: `…/base/calendari` y `…/base/calendari/` salieron
    como duplicado con similitud **1,000**. No era un duplicado del portal —el portal enlaza las dos
    formas—, era la misma página rastreada y guardada dos veces.

    La barra final se ignora **sólo para comparar**. Añadirla a la URL que se pide sería otra cosa y
    peor: hay servidores donde `/x/doc` existe y `/x/doc/` da 404, así que la petición tiene que
    salir tal como el portal la enlazó. Es identidad de página, como el `http`/`https` de RAS.5: no
    se configura.
    """
    partes = urlparse(url_de_pagina(url) or url)
    ruta = partes.path.rstrip("/") or "/"
    return partes._replace(path=ruta).geturl()


def _parece_una_direccion(valor: str) -> bool:
    limpio = valor.strip()
    return limpio.startswith(("http://", "https://", "/"))


def _mismo_esquema_que_la_raiz(url: str, raiz: str) -> str:
    """La URL con el esquema del sitio, si es el mismo host.

    El portal responde por `http://` y por `https://` y su HTML enlaza a los dos, así que el
    rastreo pedía cada página **dos veces** —la mitad del presupuesto y de la paciencia del
    servidor— y el detector emitía después «hay una versión nueva y la vieja sigue ahí» entre las
    dos. Normalizar antes de encolar es gratis: no cuesta ni una petición.
    """
    partes = urlparse(url)
    raiz_partes = urlparse(raiz)
    if partes.netloc != raiz_partes.netloc or partes.scheme == raiz_partes.scheme:
        return url
    if partes.scheme not in ("http", "https") or raiz_partes.scheme not in ("http", "https"):
        return url
    return partes._replace(scheme=raiz_partes.scheme).geturl()


def _es_legible(cabeceras: dict) -> bool:
    tipo = str(cabeceras.get("content-type") or cabeceras.get("Content-Type") or "").lower()
    if not tipo:
        # Sin cabecera no se puede afirmar que no lo sea; se intenta leer.
        return True
    return any(tipo.startswith(t) for t in _TIPOS_LEGIBLES)


class CrawlStatus(Enum):
    COMPLETED = "completed"
    COMPLETED_PARTIAL = "completed_partial"


@dataclass
class CrawlResult:
    crawled_urls: list[str]
    pages_crawled: int
    pages_skipped: int
    status: CrawlStatus
    #: Por qué se paró antes de agotar la cola: `max_pages`, `time_budget` o nada.
    #: Sin esto, un rastreo truncado y uno completo se cuentan igual, y las páginas que no se
    #: llegaron a visitar acaban declaradas desaparecidas (ver `SiteCrawler`).
    stop_reason: str | None = None
    #: URLs excluidas por el `robots.txt` del sitio. No son errores: son decisiones del servidor.
    urls_prohibidas: int = 0
    #: La cola que quedó pendiente, con su profundidad (RAS.3). Vivía sólo en memoria, así que un
    #: corte en la página 8.000 obligaba a empezar de cero; con pausa de dos segundos, horas.
    frontier: list[tuple[str, int]] = field(default_factory=list)
    #: Todo lo visitado, incluido lo que venía de una ejecución anterior.
    visited: list[str] = field(default_factory=list)
    #: `True` si esta ejecución arrancó de una cola guardada y no de `root_url`.
    resumed: bool = False
    #: Las páginas que fallaron, con su causa e intentos. Antes una sola tumbaba el rastreo
    #: completo: la excepción subía hasta el `except` global y el sitio quedaba en error sin
    #: ninguna página guardada.
    fallos: list[dict[str, Any]] = field(default_factory=list)
    #: Recursos que no son páginas —PDF, imágenes, hojas de cálculo— descartados por su extensión
    #: o por su `Content-Type`. No son fallos, y contarlos evita que parezca que no estaban.
    no_legibles: int = 0


class _WebSource(Protocol):
    """El sitio a rastrear, tal y como lo guarda la base.

    Decía `url`, y el modelo se llama `root_url` desde que `HubWebSource` pasó a ser
    `HubWebSite`: el rastreo fallaba **siempre** con `'HubWebSite' object has no attribute
    'url'` y el sitio quedaba en `status='error'`. No lo cazó ningún test porque todos doblan
    el spider, y el doble del sitio ya usaba `root_url`.
    """

    root_url: str
    config_json: dict


class GenericSpider:
    """Spider BFS que respeta crawl_depth, url_regex_filter y max_pages leídos de config_json."""

    def __init__(
        self,
        fetch_fn: Callable[[str], Awaitable[tuple[str, dict]]] | None = None,
        *,
        sleep_fn: Callable[[float], Awaitable[None]] | None = None,
        clock_fn: Callable[[], float] | None = None,
        contacto: str | None = None,
    ) -> None:
        self._fetch_fn = fetch_fn
        self._sleep_fn = sleep_fn
        self._clock_fn = clock_fn
        self._contacto = contacto
        # Cortesía por defecto hasta que un sitio diga otra cosa: si alguien llama a `_fetch`
        # antes de `crawl`, se rastrea despacio, no a toda velocidad.
        self._cortesia = self._nueva_cortesia({})
        # Lo descargado en esta ejecución, para no volver a pedirlo (RAS.3).
        self._leido: dict[str, tuple[str, dict]] = {}

    # -- configuración -------------------------------------------------------

    def _nueva_cortesia(self, config: dict) -> CortesiaDeRastreo:
        if self._contacto is None:
            from server.app.core.config import get_settings

            try:
                contacto = get_settings().crawler_contact
            except Exception:  # noqa: BLE001 — sin configuración cargada seguimos, sin contacto
                contacto = ""
        else:
            contacto = self._contacto
        return cortesia_desde_config(
            config, contacto=contacto, sleep_fn=self._sleep_fn, clock_fn=self._clock_fn
        )

    def configurar_cortesia(self, config: dict) -> None:
        """Aplica la cortesía que declara la configuración de un sitio."""
        self._cortesia = self._nueva_cortesia(config)

    def pausa_efectiva_para(self, url: str) -> float:
        return self._cortesia.pausa_efectiva_para(url)

    # -- descarga ------------------------------------------------------------

    async def _descargar(self, url: str) -> tuple[str, dict]:
        """La descarga a secas, sin cortesía: la usan `_fetch` y la lectura del `robots.txt`."""
        if self._fetch_fn is not None:
            return await self._fetch_fn(url)
        async with cliente_de_rastreo(self._cortesia.user_agent) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            cabeceras = dict(resp.headers)
            # La URL final tras las redirecciones es la única que dice qué página se ha leído de
            # verdad. Se estaba tirando, y con ella se perdía que `http://x` y `https://x` son la
            # misma. Viaja como cabecera sintética para no cambiar la forma de la respuesta.
            cabeceras["x-final-url"] = str(resp.url)
            return resp.text, cabeceras

    async def _fetch(self, url: str) -> tuple[str, dict]:
        """Descarga una URL respetando `robots.txt`, la pausa, la concurrencia y los reintentos.

        Si el recorrido ya la descargó en esta misma ejecución, se devuelve lo leído: `crawl()`
        pedía cada página para extraer sus enlaces y `SiteCrawler` la volvía a pedir para
        guardarla, o sea el doble de peticiones y el doble de tiempo contra el mismo servidor
        (medido en el sondeo del apartado real: 25 páginas, 50 peticiones).
        """
        if url in self._leido:
            return self._leido[url]

        if not await self._cortesia.permitido(url, self._descargar):
            raise RutaProhibidaPorRobots(url)

        async with self._cortesia.turno_de(url):
            await self._cortesia.esperar_turno(url)
            respuesta = await self._cortesia.con_reintentos(url, self._descargar)

        self._recordar(url, respuesta)
        return respuesta

    def _recordar(self, url: str, respuesta: tuple[str, dict]) -> None:
        """Guarda lo leído para no repetir la petición, con tope: un rastreo de miles de páginas
        no puede quedarse con todas en memoria, y degradar a volver a pedirlas es correcto."""
        if len(self._leido) >= _PAGINAS_RECORDADAS:
            return
        self._leido[url] = respuesta

    def olvidar_lo_leido(self) -> None:
        self._leido.clear()

    def _extract_links(self, html: str, base_url: str) -> list[str]:
        links: list[str] = []
        for match in re.finditer(r'href=["\']([^"\']+)["\']', html, re.IGNORECASE):
            href = match.group(1).strip()
            if not href or href.startswith(("mailto:", "javascript:", "#")):
                continue
            absolute = urljoin(base_url, href).split("#")[0]
            if absolute:
                links.append(absolute)
        return links

    # -- recorrido -----------------------------------------------------------

    async def crawl(self, source: _WebSource) -> CrawlResult:
        config: dict = source.config_json
        crawl_depth: int = config.get("crawl_depth", 1)
        url_regex_filter: str | None = config.get("url_regex_filter")
        max_pages: int = config.get("max_pages", 50)
        max_seconds: float = float(
            config.get("max_seconds", PRESUPUESTO_POR_DEFECTO_SEGUNDOS)
        )

        self.configurar_cortesia(config)
        empezado = self._cortesia._reloj()

        # Se compila sólo para fallar en alto si no es válido, como antes; la búsqueda va por
        # `busca_con_tope`, con tiempo máximo: el patrón lo escribe un administrador y se aplica
        # a cada URL dentro del bucle de eventos.
        if url_regex_filter:
            _regex.compile(url_regex_filter)
        # DIN.2 — el apartado dentro de la valla. El filtro del sitio acota el dominio y este
        # acota la sección **dentro** de él: se aplican los dos, no uno en lugar del otro. Sin
        # ámbito declarado esto es siempre cierto, que es el rastreo de siempre.
        en_ambito = predicado_de_ambito(config)
        base_netloc = urlparse(source.root_url).netloc

        # Cola BFS: pares (url, profundidad). Si el sitio guarda una cola de una ejecución
        # interrumpida, se retoma por ahí en vez de volver a empezar por la raíz (RAS.3).
        guardada = getattr(source, "crawl_frontier", None) or {}
        pendientes = [(u, int(d)) for u, d in (guardada.get("pending") or [])]
        ya_visitadas = set(guardada.get("visited") or [])
        reanudado = bool(pendientes)

        if reanudado:
            queue: deque[tuple[str, int]] = deque(pendientes)
            visited: set[str] = ya_visitadas | {u for u, _d in pendientes}
        else:
            queue = deque([(source.root_url, 0)])
            visited = {source.root_url}

        # CUR.7 — qué páginas se han visto ya, comparadas por identidad y no por texto de URL. El
        # conjunto de URLs sigue siendo el de arriba (es lo que se guarda para reanudar y lo que
        # cuenta el reconocimiento); esto es sólo para no pedir dos veces la misma página servida con
        # y sin barra final, que es como se colaron dos copias de `/base/calendari` en el corpus.
        claves_vistas: set[str] = {clave_de_pagina(u) for u in visited}

        crawled_urls: list[str] = []
        pages_skipped = 0
        prohibidas = 0
        fallos: list[dict[str, Any]] = []
        no_legibles = 0
        stop_reason: str | None = None

        while queue:
            if len(crawled_urls) >= max_pages:
                stop_reason = "max_pages"
                pages_skipped += len(queue)
                break
            if self._cortesia._reloj() - empezado >= max_seconds:
                # El presupuesto es de tiempo además de páginas porque el coste real de un
                # rastreo cortés es el tiempo: con pausa de un segundo, mil páginas son veinte
                # minutos. Parar y decirlo es mejor que no terminar nunca.
                stop_reason = "time_budget"
                pages_skipped += len(queue)
                break

            url, depth = queue.popleft()
            try:
                html, cabeceras = await self._fetch(url)
            except RutaProhibidaPorRobots:
                # No es un error del sitio ni nuestro: el servidor ha dicho que no. Se cuenta y
                # se sigue; convertirlo en `crawl_error` llenaría el informe de acusaciones.
                prohibidas += 1
                continue
            except Exception as fallo:  # noqa: BLE001
                # Una página que falla **no puede tumbar el rastreo**. Así estaba: la excepción
                # subía por `crawl()` hasta el `except` global de `crawl_site`, el sitio quedaba en
                # error y no se guardaba ni una página. Medido con el primer rastreo real del
                # apartado: un 404 en una página cualquiera devolvió **cero páginas**. Y todo
                # portal real tiene enlaces rotos: son justo lo que este módulo busca.
                fallos.append({
                    "url": url,
                    "kind": clasificar_fallo(getattr(fallo, "causa", fallo)),
                    "attempts": getattr(fallo, "intentos", 1),
                    "message": str(fallo)[:500],
                })
                continue

            if not _es_legible(cabeceras):
                # La extensión no lo delataba, pero la respuesta sí: no es una página.
                no_legibles += 1
                continue

            # Lo que se ha leído es la URL final, no la pedida. Si ya se había leído, la página no
            # es nueva: es la misma servida por otra dirección.
            final = str(cabeceras.get("x-final-url") or url)
            if final != url:
                if clave_de_pagina(final) in {clave_de_pagina(u) for u in crawled_urls}:
                    continue
                visited.add(final)
                claves_vistas.add(clave_de_pagina(final))
                self._recordar(final, (html, cabeceras))
                url = final

            crawled_urls.append(url)

            # No encolar hijos si hemos alcanzado la profundidad máxima
            if depth >= crawl_depth:
                continue

            for enlace in self._extract_links(html, url):
                # El mismo esquema que la raíz del sitio: el portal enlaza a http y a https.
                # Y sin los parámetros de navegación, que multiplican la misma página.
                normalizado = url_de_pagina(_mismo_esquema_que_la_raiz(enlace, source.root_url))
                if normalizado is None:
                    no_legibles += 1
                    continue
                link = normalizado
                if clave_de_pagina(link) in claves_vistas:
                    continue
                if urlparse(link).netloc != base_netloc:
                    continue
                if url_regex_filter and not busca_con_tope(url_regex_filter, link):
                    continue
                if not en_ambito(link):
                    continue
                if _parece_descarga(link):
                    # Se ve en la URL, así que ni se pide: es tráfico que no aporta nada y, si se
                    # pidiera, lo que se guardaría sería un binario decodificado como texto.
                    no_legibles += 1
                    continue
                # Comprobar la exclusión **antes de encolar**: si sólo se viera al pedir, cada
                # ruta prohibida costaría una vuelta de la cola y una excepción.
                if not await self._cortesia.permitido(link, self._descargar):
                    prohibidas += 1
                    continue
                visited.add(link)
                claves_vistas.add(clave_de_pagina(link))
                queue.append((link, depth + 1))

        status = (
            CrawlStatus.COMPLETED_PARTIAL if stop_reason is not None else CrawlStatus.COMPLETED
        )
        return CrawlResult(
            crawled_urls=crawled_urls,
            pages_crawled=len(crawled_urls),
            pages_skipped=pages_skipped,
            status=status,
            stop_reason=stop_reason,
            urls_prohibidas=prohibidas,
            # La cola pendiente sólo tiene sentido si quedó algo: un rastreo completo no deja
            # nada que reanudar, y dejar restos haría que la siguiente ejecución arrancara por
            # la mitad de un recorrido ya terminado.
            frontier=list(queue) if stop_reason is not None else [],
            visited=sorted(visited),
            resumed=reanudado,
            fallos=fallos,
            no_legibles=no_legibles,
        )
