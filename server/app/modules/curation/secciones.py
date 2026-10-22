"""La sección de un sitio como dato, y la cascada sitio→sección que la resuelve (DIN.1).

Deploy: edge — una sección delimita un apartado del portal de un cliente y sus criterios de
juicio; no sale de su nodo.

Hoy un apartado se expresa **creando un `HubWebSite` entero** con su `url_regex_filter`. Es la
decisión de RAS.5 y tenía una buena razón —cada apartado tiene un responsable distinto—, pero
paga un precio que se nota justo cuando los apartados se multiplican: duplica `root_url`,
sitemap, cortesía y criterios de juicio, y hace que «añadir el apartado de becas» sea trabajo de
quien administra sitios en vez de trabajo de quien cura. Es el mismo razonamiento que el proyecto
ya aplicó al vocabulario del corpus: lo que va a cambiar mientras alguien lo usa **es dato, no
estructura**.

Tres decisiones que este módulo hace cumplir, y que los seis prompts siguientes del bloque dan
por hechas:

1. **Nulo hereda.** Todo parámetro de sección admite nulo y entonces vale el del sitio — la misma
   semántica que `core/ambito.py` da a `heredable`, incluida la distinción entre `None` («no lo he
   puesto») y `0` o `""` («lo quiero así»). Un sitio **sin secciones** se comporta exactamente
   como hoy: el ámbito implícito es el sitio entero. No es un *shim*, es la herencia.
2. **Los criterios se funden clave a clave.** Un override de `stale_days` en la sección no puede
   borrar el umbral de retirada que sólo está puesto en el sitio. Con `sitio | seccion` mal
   hecho —fila entera— sí lo borra, y el síntoma aparecería un rastreo después.
3. **La pertenencia de una página a una sección se deriva del patrón, no se almacena.** Los
   patrones se editan, y una columna `section_id` en `hub_crawled_pages` habría que reescribirla
   en cada edición; peor, una edición a medias dejaría páginas apuntando a un ámbito que ya no
   existe, y con la auto-retirada de DIN.4 encima eso vacía corpus.

**Un solo comparador.** `CorpusSelectionRepo.matches` delega aquí para `path_prefix` en vez de
guardar su propia copia: una regla de selección y una sección con el mismo prefijo tienen que
decidir igual, o la pantalla y el rastreo discreparían sobre qué entra al corpus. La sección
entiende además `regex`, que la selección nunca ofreció.

Sin sesión de base de datos en ninguna función: entra dato, sale dato.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

import regex as _regex

logger = logging.getLogger(__name__)

#: Las clases de patrón que `casa_patron` entiende. La lección de VER.8 con las reglas de
#: selección: un tipo que ningún comparador entiende es una sección que **no puede casar nunca**,
#: y en pantalla se vería activa y vacía sin nada que explicara por qué.
CLASES_DE_PATRON: tuple[str, ...] = ("path_prefix", "regex")

#: Los modos de una sección. `mode` sí lleva `CheckConstraint` en la base: son dos valores
#: estables con consumidor en el código —DIN.4 decide por él si retira o sólo avisa—, como
#: `nivell_acces`. Los criterios de juicio no lo llevan: son vocabulario que crecerá.
MODOS: tuple[str, ...] = ("manual", "automatic")


class PatronInvalido(ValueError):
    """El patrón de una sección que no delimita nada, o que no compila.

    Se levanta **al guardar**, que es la lección de `CrawlConfig` en RAS.5: un regex inválido
    rompería todos los rastreos de la sección y el fallo saldría lejos del formulario donde se
    escribió.
    """


def validar_patron(pattern_kind: str, pattern: str | None) -> str:
    """El patrón, si sirve; `PatronInvalido` con el patrón y el motivo, si no."""
    if pattern_kind not in CLASES_DE_PATRON:
        raise PatronInvalido(
            f"«{pattern_kind}» no es una clase de patrón que sepamos comparar; "
            f"las que hay son {', '.join(CLASES_DE_PATRON)}"
        )
    if pattern is None or not pattern.strip():
        raise PatronInvalido(
            "una sección sin patrón no delimita nada: su ámbito sería el sitio entero con "
            "otro nombre"
        )
    limpio = pattern.strip()
    if pattern_kind == "regex":
        try:
            _regex.compile(limpio)
        except _regex.error as fallo:
            raise PatronInvalido(
                f"«{limpio}» no es una expresión regular válida: {fallo}"
            ) from fallo
    return limpio


#: Lo más que puede tardar un patrón en una URL. Una URL legítima se resuelve en microsegundos.
TIEMPO_MAXIMO_DE_UN_PATRON = 0.05


def busca_con_tope(pattern: str, url: str) -> bool:
    """`regex.search` con tiempo máximo: lo que no termina a tiempo, no casa.

    Los patrones los escribe un administrador de curación y se aplican a cada URL descubierta
    dentro del bucle de eventos. `re` no tiene tope y no suelta el GIL mientras busca, así que un
    patrón con retroceso catastrófico —`^(a+)+$`— contra una URL preparada paraba la API entera,
    y ni pasarlo a otro hilo lo habría evitado.
    """
    try:
        return _regex.search(pattern, url, timeout=TIEMPO_MAXIMO_DE_UN_PATRON) is not None
    except TimeoutError:
        logger.warning("Patrón de URL que no termina a tiempo: %r", pattern)
        return False
    except _regex.error:
        # Un patrón inválido guardado antes de que esto se validara no puede tumbar un
        # rastreo entero: no casa, y el alta ya no lo admite.
        return False


def casa_patron(pattern_kind: str, pattern: str, url: str) -> bool:
    """Si una URL pertenece al ámbito que delimita este patrón.

    `path_prefix` compara el **path** y no la URL entera, igual que la regla de selección: ninguna
    URL real empieza por «/jornadas», así que comparar la cadena completa no casaría nada.
    `regex` busca en la URL completa, como el `url_regex_filter` del sitio en el spider, para que
    un patrón pueda acotar por idioma (`/va/`) o por dominio cuando haga falta.
    """
    if not pattern:
        return False
    if pattern_kind == "path_prefix":
        from urllib.parse import urlparse

        return urlparse(url).path.startswith(pattern)
    if pattern_kind == "regex":
        return busca_con_tope(pattern, url)
    return False


def casa(section: Any | None, url: str) -> bool:
    """Si una página pertenece a una sección. Sin sección no hay patrón que evaluar."""
    if section is None:
        return False
    return casa_patron(
        getattr(section, "pattern_kind", "path_prefix"),
        getattr(section, "pattern", "") or "",
        url,
    )


#: Las dos claves con las que el ámbito viaja **dentro** de la configuración del rastreo (DIN.2).
#: Va aquí y no como argumento nuevo de `GenericSpider.crawl` porque es exactamente el camino que
#: ya recorre `url_regex_filter`: el ámbito es configuración de la pasada, y así el protocolo del
#: spider —`crawl(source)`— no cambia.
CLAVE_PATRON = "ambito_pattern"
CLAVE_CLASE_DE_PATRON = "ambito_pattern_kind"


def predicado_de_ambito(config: dict[str, Any] | None) -> Any:
    """Si una URL está en el ámbito que declara esta configuración de rastreo.

    Sin ámbito declarado el ámbito es el sitio entero, así que todo entra: es el comportamiento
    de siempre, y el que hace que un sitio sin secciones se rastree exactamente como antes.
    """
    datos = config or {}
    patron = datos.get(CLAVE_PATRON)
    if not patron:
        return lambda _url: True
    clase = datos.get(CLAVE_CLASE_DE_PATRON) or "path_prefix"
    return lambda url: casa_patron(clase, patron, url)


@dataclass(frozen=True)
class ParametrosEfectivos:
    """Los parámetros resueltos de una pasada: intervalo, criterios y patrón.

    `ambito` es lo que el summary de DIN.2 y el diario de DIN.6 escriben para poder decir qué
    cubrió una pasada: el identificador de la sección, o `"sitio"`.
    """

    crawl_interval_hours: int
    criterios: dict[str, Any]
    pattern: str | None
    pattern_kind: str | None
    section_id: uuid.UUID | None

    @property
    def es_sitio_entero(self) -> bool:
        return self.section_id is None

    @property
    def ambito(self) -> str:
        return "sitio" if self.section_id is None else str(self.section_id)

    def config_de_rastreo(self) -> dict[str, Any]:
        """Los criterios efectivos con el ámbito dentro, tal y como los lee el spider (DIN.2)."""
        config = dict(self.criterios)
        if self.pattern:
            config[CLAVE_PATRON] = self.pattern
            config[CLAVE_CLASE_DE_PATRON] = self.pattern_kind or "path_prefix"
        return config

    def en_ambito(self, url: str) -> bool:
        """Si una página pertenece al ámbito de esta pasada. Sin sección, todo el sitio lo es."""
        if self.pattern is None:
            return True
        return casa_patron(self.pattern_kind or "path_prefix", self.pattern, url)


def parametros_efectivos(site: Any, section: Any | None = None) -> ParametrosEfectivos:
    """Los parámetros con los que se rastrea y se juzga un ámbito.

    Sin sección, el ámbito es el sitio entero y los parámetros son los del sitio: el
    comportamiento de hoy, y el que DIN.2 tiene que conservar intacto.
    """
    criterios: dict[str, Any] = dict(getattr(site, "config_json", None) or {})

    if section is None:
        return ParametrosEfectivos(
            crawl_interval_hours=getattr(site, "crawl_interval_hours", 24),
            criterios=criterios,
            pattern=None,
            pattern_kind=None,
            section_id=None,
        )

    # Clave a clave, y `None` es heredar: es lo que permite vaciar un override desde la pantalla
    # sin dejar la clave en nulo para siempre.
    for clave, valor in (getattr(section, "criteria_json", None) or {}).items():
        if valor is not None:
            criterios[clave] = valor

    intervalo = getattr(section, "crawl_interval_hours", None)
    if intervalo is None:
        intervalo = getattr(site, "crawl_interval_hours", 24)

    return ParametrosEfectivos(
        crawl_interval_hours=intervalo,
        criterios=criterios,
        pattern=getattr(section, "pattern", None),
        pattern_kind=getattr(section, "pattern_kind", None),
        section_id=getattr(section, "id", None),
    )
