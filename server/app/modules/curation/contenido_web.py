"""De una página web, su texto y su título (RAS.2).

Deploy: edge

`SiteCrawler` guardaba el cuerpo de la respuesta tal cual en `markdown_content`. Medido contra el
portal real: **51.098 bytes de HTML con 4.249 caracteres de texto**. Con el marcado dentro, tres
cosas medían lo que no querían medir: el umbral de `thin` (120 tokens) era inalcanzable, el detector
semántico comparaba plantillas HTML —idénticas en todo el portal— y a la ingesta del asistente
llegaban 51 KB de `<div>` por página.

Se convierte al guardar, no al leer: lo que hay en la base es lo que se audita, lo que se embebe y
lo que acaba en el corpus, así que tiene que ser ya el texto.
"""
from __future__ import annotations

import html as _html
from datetime import datetime, timezone
import re
from typing import Any

_SCRIPT_O_ESTILO = re.compile(
    r"<(script|style|noscript|template)\b[\s\S]*?</\1>", re.IGNORECASE
)
_COMENTARIO = re.compile(r"<!--[\s\S]*?-->")
_ETIQUETA = re.compile(r"<[^>]+>")
_ESPACIOS = re.compile(r"\s+")
_TITULO = re.compile(r"<title[^>]*>([\s\S]*?)</title>", re.IGNORECASE)
_ENCABEZADO = re.compile(r"<h[1-3][^>]*>([\s\S]*?)</h[1-3]>", re.IGNORECASE)
#: Suficiente para distinguir una respuesta HTML de un Markdown o un texto plano.
_PARECE_HTML = re.compile(r"<(html|body|div|p|h[1-6]|table|span)\b", re.IGNORECASE)

#: Etiquetas que separan bloques de texto. Cada una abre línea nueva (CUR.3): sin eso el texto de
#: una página es una sola línea y no hay forma de trocearlo ni de ver qué se repite.
_BLOQUE = re.compile(
    r"</?(?:p|div|br|li|tr|h[1-6]|section|article|main|header|footer|nav|aside|table|"
    r"thead|tbody|ul|ol|dl|dt|dd|blockquote|figure|figcaption|form|hr)\b[^>]*>",
    re.IGNORECASE,
)

#: Estructura que en cualquier portal es plantilla y no contenido. Este portal no las usa —su menú
#: son `div` con clases— pero otros sí, y descartarlas no cuesta nada.
_ETIQUETAS_DE_PLANTILLA = ("nav", "header", "footer", "aside")


def parece_html(contenido: str) -> bool:
    """`True` si merece la pena convertir. El corpus normativo entra como Markdown por otra
    vía y convertirlo sería estropearlo."""
    return bool(_PARECE_HTML.search(contenido or ""))


def texto_visible(contenido: str) -> str:
    """El texto que una persona vería, **una línea por bloque**.

    `<noscript>` se descarta con los scripts: su contenido es «activa JavaScript», que no es
    contenido de la página y aparece en todas las del portal.

    CUR.3 — los saltos de bloque se conservan. Sin ellos el texto de una página es una sola línea
    de miles de caracteres: no se puede trocear con sentido para el corpus ni detectar qué líneas se
    repiten en todas las páginas, que es cómo se reconoce la plantilla.
    """
    if not contenido:
        return ""
    sin_script = _SCRIPT_O_ESTILO.sub(" ", contenido)
    sin_comentarios = _COMENTARIO.sub(" ", sin_script)
    # Cada bloque, su línea. Se marca antes de quitar las etiquetas, que es cuando se sabe dónde
    # empezaba y acababa.
    con_saltos = _BLOQUE.sub("\n", sin_comentarios)
    sin_etiquetas = _ETIQUETA.sub(" ", con_saltos)

    lineas = [
        _ESPACIOS.sub(" ", linea).strip()
        for linea in _html.unescape(sin_etiquetas).split("\n")
    ]
    limpio = "\n".join(linea for linea in lineas if linea)
    # Cinturón: cualquier respuesta puede traer bytes nulos —un binario servido como si fuera
    # página— y Postgres rechaza la fila entera con «invalid byte sequence for encoding UTF8».
    # Pasó con un PDF del portal y se llevó por delante el rastreo completo.
    return limpio.replace("\x00", "")


def contenido_y_enlaces(
    contenido: str, content_selector: str | None, boilerplate_selectors: list[str] | None
) -> tuple[str, str | None, list[str]]:
    """El texto de la página **sin su plantilla**, un aviso si algo no cuadró (CUR.3), y las líneas
    de sus enlaces (#345).

    Medido en el portal real: cada página lleva el menú completo —más de mil caracteres idénticos en
    todas—, y al corpus entraba con el contenido, así que el asistente recuperaba menús.

    Tres cosas, en este orden:

    1. Si el sitio declara **dónde está su contenido** (`main` en este portal), se conserva sólo eso.
       Es la señal más fuerte que ofrece: quita el 39 % del texto en una página del apartado y el
       67 % en la de normativa. Si el selector no encuentra nada, se sigue con la página entera y se
       avisa: mejor texto de más que una página vacía por un selector mal escrito.
    2. Se quitan los bloques de plantilla que el sitio declare —la miga de pan, la barra de fecha y
       los iconos de compartir están **dentro** de `main`—.
    3. Y las etiquetas estructurales (`nav`, `header`, `footer`, `aside`), que este portal no usa
       pero otros sí.

    #345 — los enlaces salen de la **misma zona** y la misma pasada. El texto guardado ya no tiene
    etiquetas, así que no dice qué líneas eran enlaces, y eso es lo que distingue una página de
    navegación de una con poco contenido: el detector los cruza con las líneas del texto. Cada
    enlace se pasa por `texto_visible` como el texto de la página: una tarjeta enlazada con título y
    descripción son dos líneas allí y tienen que ser dos líneas aquí, o no casarían nunca.
    """
    if not contenido:
        return "", None, []
    try:
        arbol, aviso = _zona_de_contenido(contenido, content_selector, boilerplate_selectors)
    except Exception:  # noqa: BLE001 — HTML irrecuperable: mejor el texto entero que nada
        return texto_visible(contenido), "html_no_analizable", []
    lineas = [
        linea
        for enlace in arbol.find_all("a")
        for linea in texto_visible(str(enlace)).split("\n")
        if linea
    ]
    return texto_visible(str(arbol)), aviso, lineas


def _zona_de_contenido(
    contenido: str, content_selector: str | None, boilerplate_selectors: list[str] | None
) -> tuple[Any, str | None]:
    """El árbol de la zona de contenido, sin la plantilla declarada, y el aviso si no cuadró."""
    from bs4 import BeautifulSoup

    aviso: str | None = None
    arbol: Any = BeautifulSoup(contenido, "html.parser")

    if content_selector:
        elegido = arbol.select_one(content_selector)
        if elegido is None:
            aviso = "content_selector_sin_coincidencia"
        else:
            arbol = elegido

    for selector in [*(boilerplate_selectors or []), *_ETIQUETAS_DE_PLANTILLA]:
        try:
            for encontrado in arbol.select(selector):
                encontrado.decompose()
        except Exception:  # noqa: BLE001 — un selector mal escrito no tumba el rastreo
            continue

    return arbol, aviso


def fecha_y_responsable(
    contenido: str, selector: str | None, formato: str
) -> tuple[datetime | None, str | None]:
    """La fecha que **publica** la página y la unidad que la mantiene (CUR.1).

    El portal las sirve juntas en el HTML —medido en `/base/doctorands/`:
    `<div class="clockBarDate"><span>24/09/2025</span> | <span>Escola de Doctorat</span></div>`— y
    las estábamos ignorando: `stale` adivinaba la antigüedad del año más reciente citado en el texto,
    y marcaba 303 de 400 páginas.

    El selector llega de la **configuración del sitio**, no del código: ese marcado es de este
    portal, y hardcodearlo acoplaría el módulo a un cliente. Sin selector, nada cambia.

    Nada de esto puede tumbar un rastreo: un selector inválido, un bloque que no está o un texto que
    no es una fecha devuelven `None`, que es exactamente lo que había antes.
    """
    if not selector or not contenido:
        return None, None

    try:
        from bs4 import BeautifulSoup

        bloque = BeautifulSoup(contenido, "html.parser").select_one(selector)
    except Exception:  # noqa: BLE001 — selector mal escrito, HTML roto: da igual cuál
        return None, None

    if bloque is None:
        return None, None

    partes = [t.get_text(strip=True) for t in bloque.find_all("span")]
    if not partes:
        partes = [bloque.get_text(strip=True)]

    fecha = None
    responsable = None
    for parte in partes:
        if fecha is None:
            try:
                # `strptime` rechaza `31/02/2025`, y eso es lo que se quiere: aceptar una fecha
                # imposible daría una antigüedad inventada.
                fecha = datetime.strptime(parte, formato).replace(tzinfo=timezone.utc)
                continue
            except ValueError:
                pass
        if responsable is None and parte and parte != "|":
            responsable = parte

    return fecha, responsable


def titulo_de(contenido: str) -> str | None:
    """El `<title>`, o el primer encabezado si no hay.

    Antes se llamaba a `extract_title_from_markdown` sobre HTML, que busca una línea `# `: las
    páginas rastreadas quedaban sin título y la bandeja del curador se leía por la URL.
    """
    for patron in (_TITULO, _ENCABEZADO):
        encontrado = patron.search(contenido or "")
        if encontrado:
            texto = _ESPACIOS.sub(" ", _html.unescape(_ETIQUETA.sub(" ", encontrado.group(1))))
            if texto.strip():
                return texto.strip()
    return None
