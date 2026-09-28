"""El mapa `ancora nuestra → ancla del diario`, leído de la página (issue #157). Deploy: edge.

**Por qué no se calcula.** La #152 retiró la composición de anclas del BOE porque no hay fórmula:
el diario usa dos esquemas y sólo coinciden en los artículos de un dígito.

    Ley Orgánica 6/2001   #a110   → Artículo 110    (el ancla ES el número)
    Ley 9/2017 Contratos  #a1-10  → Artículo 18     (contador de bloques del BOE)

Para saber qué ancla lleva al artículo 18 hay que leer la página. Y leída la página, **el mapa
completo sale casi gratis y es mejor que cualquier fórmula**: vale para los dos esquemas sin
distinguirlos, no hay catálogo de esquemas que mantener, y no trae los artículos derogados —el
texto consolidado no los renderiza, así que su bloque no existe—, que es precisamente donde
también fallaba el esquema bueno.

**Sólo artículos, y es una decisión.** Las disposiciones, anexos y secciones del corpus (`da-N`,
`df-N`, `annex-N`, `sec-N`) nunca han tenido fragmento al citar al diario: la regla retirada sólo
componía ancla cuando la nuestra era `art-N`. Traducirlas exigiría convertir «séptima» en `7`, o
sea una lista de ordinales escrita a mano, y este módulo ya ha visto tres veces cómo se queda
corta una lista así. Se amplía el día que alguien lo necesite y con su medición delante.
"""

from __future__ import annotations

import asyncio
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Awaitable, Callable

#: Cada bloque del texto consolidado, con su ancla. El `(?=...)` corta en el siguiente bloque en
#: vez de tragárselo: sin eso, el encabezado de un bloque acabaría asignado al anterior y el mapa
#: entero quedaría desplazado un artículo — un ancla que **sí existe** y lleva a otro sitio, que
#: es el modo de fallo peor.
_BLOQUE = re.compile(
    r'<div class="bloque" id="(?P<ancla>[^"]+)"[^>]*>(?P<cuerpo>.*?)'
    r'(?=<div class="bloque" id="|\Z)',
    re.DOTALL,
)

#: El encabezado del artículo. El BOE lo sirve como `<h5 class="articulo">`; se admite cualquier
#: nivel porque el nivel depende de la profundidad del título y del capítulo que lo contienen.
_ENCABEZADO = re.compile(r'<h\d[^>]*class="articulo"[^>]*>(?P<texto>[^<]*)</h\d>')

#: «Artículo 18.», «Artículo 30 bis.». El ordinal latino es parte del identificador del artículo,
#: no un adorno: el 30 y el 30 bis son dos artículos distintos, y el corpus los distingue como
#: `art-30` y `art-30-bis`.
_ARTICULO = re.compile(
    r"^Art[íi]culo\s+(?P<numero>\d+)"
    r"(?:\s+(?P<ordinal>bis|ter|qu[aá]ter|quinquies|sexies|septies|octies|novies|decies))?"
    r"\s*[.\s]",
    re.IGNORECASE,
)


def mapa_de_ancores(html: str) -> dict[str, str]:
    """`{"art-18": "a1-10", …}` a partir del HTML del texto consolidado.

    Devuelve un mapa vacío ante una página vacía o que no sea del diario, en vez de levantar:
    quien llama decide qué hacer sin mapa, y reventar aquí pararía la ingesta entera por una
    página que no respondió como se esperaba.
    """
    mapa: dict[str, str] = {}
    for bloque in _BLOQUE.finditer(html or ""):
        encabezado = _ENCABEZADO.search(bloque.group("cuerpo"))
        if encabezado is None:
            continue
        articulo = _ARTICULO.match(encabezado.group("texto").strip())
        if articulo is None:
            continue
        ordinal = articulo.group("ordinal")
        nuestra = f"art-{articulo.group('numero')}"
        if ordinal:
            nuestra = f"{nuestra}-{ordinal.lower().replace('á', 'a')}"
        mapa[nuestra] = bloque.group("ancla")
    return mapa


# ── Refresco: leer la página y guardar el mapa con el documento ───────────────────────

#: Dónde vive el mapa dentro de `doc_metadata`. El corpus **no** lo declara —lo calcula la
#: plataforma leyendo el diario—, así que el reconciliador lo conserva entre pasadas en vez de
#: borrarlo y reponerlo; está en `_METADATOS_QUE_NO_VIENEN_DEL_CORPUS`.
CLAVE = "ancores_del_diari"

#: De qué diarios se sabe leer. El DOGV usa otro marcado y es trabajo aparte: hoy sus citas van
#: sin fragmento, igual que antes, en vez de con uno inventado.
_DIARIOS_QUE_SE_LEEN = ("boe.es",)


def url_del_diari(documento) -> str | None:
    """La página del diario de esta norma, si es una de las que se sabe leer.

    Mismo orden de preferencia que `citations._url_en_el_diario_oficial`, y sin fragmento: lo
    que se descarga es el documento entero.
    """
    metadatos = getattr(documento, "doc_metadata", None) or {}
    base = (
        metadatos.get("url_oficial")
        or metadatos.get("url_eli")
        or getattr(documento, "canonical_url", None)
        or ""
    )
    base = str(base).split("#", 1)[0].strip()
    if not base.startswith(("http://", "https://")):
        return None
    return base if any(d in base for d in _DIARIOS_QUE_SE_LEEN) else None


@dataclass
class Refresco:
    """Qué pasó al refrescar, para que la ingesta lo pueda contar."""

    actualizadas: int = 0
    sin_cambio: int = 0
    #: Páginas que no se pudieron leer, con el motivo. **No son un fallo de la ingesta**: la
    #: norma se ingiere igual y sus citas van sin fragmento, que es lo que hacían antes.
    no_se_pudo: dict[str, str] = field(default_factory=dict)
    #: Páginas leídas de las que no salió ni un artículo. Se distingue de la anterior a
    #: propósito: «no pude mirar» y «miré y no hay nada» son cosas distintas, y confundirlas es
    #: como un medidor informa de cero en verde.
    sin_articulos: list[str] = field(default_factory=list)

    @property
    def resumen(self) -> str:
        partes = [f"{self.actualizadas} actualizadas", f"{self.sin_cambio} sin cambio"]
        if self.sin_articulos:
            partes.append(f"{len(self.sin_articulos)} sin artículos")
        if self.no_se_pudo:
            partes.append(f"{len(self.no_se_pudo)} ilegibles")
        return "anclas del diario: " + ", ".join(partes)


Fetch = Callable[[str], Awaitable[tuple[int, str]]]


async def refrescar_ancores(
    documentos: list, fetch: Fetch, *, concurrencia: int = 4
) -> Refresco:
    """Lee el diario y deja el mapa en `doc_metadata[CLAVE]` de cada documento.

    **Una descarga por página, no por documento.** El corpus tiene una versión por lengua de
    cada norma —cuatro documentos por norma en el despliegue real—, así que pedir la página por
    documento la descargaría cuatro veces. Es el mismo criterio que `verificar_enlaces`.

    **Que el diario no responda no rompe la ingesta.** La norma entra igual y sus citas van sin
    fragmento, que es exactamente lo que hacían antes de esto. Acoplar la disponibilidad del
    corpus a la de una web ajena sería peor que la imprecisión que se viene a arreglar.

    **Y un mapa vacío no pisa uno bueno.** Si la página respondió pero no se le sacó ni un
    artículo —cambió el marcado, o llegó una página de error con estado 200—, se deja el mapa
    anterior y se anota. Sustituirlo por `{}` apagaría en silencio todas las citas de esa norma.
    """
    por_pagina: dict[str, list] = defaultdict(list)
    for documento in documentos:
        url = url_del_diari(documento)
        if url:
            por_pagina[url].append(documento)

    if not por_pagina:
        return Refresco()

    if concurrencia < 1:
        raise ValueError(
            f"concurrencia={concurrencia}: tiene que ser al menos 1. Un cero no quita el "
            f"límite, deja el refresco colgado indefinidamente."
        )

    limite = asyncio.Semaphore(concurrencia)
    resultado = Refresco()

    async def _una(url: str) -> tuple[str, dict[str, str] | None, str | None]:
        async with limite:
            try:
                estado, cuerpo = await fetch(url)
            except Exception as exc:  # noqa: BLE001
                # Una excepción NO es «no hay artículos»: sin este `except` un fallo de red
                # dejaría el mapa vacío y las citas apagadas sin que nadie supiera por qué.
                return url, None, f"{type(exc).__name__}: {exc}"
        if estado != 200:
            return url, None, f"estado {estado}"
        return url, mapa_de_ancores(cuerpo), None

    for url, mapa, motivo in await asyncio.gather(*(_una(u) for u in por_pagina)):
        if motivo is not None:
            resultado.no_se_pudo[url] = motivo
            continue
        if not mapa:
            resultado.sin_articulos.append(url)
            continue
        for documento in por_pagina[url]:
            metadatos = dict(getattr(documento, "doc_metadata", None) or {})
            if metadatos.get(CLAVE) == mapa:
                resultado.sin_cambio += 1
                continue
            metadatos[CLAVE] = mapa
            # Diccionario **nuevo**: SQLAlchemy detecta el cambio por identidad del atributo, y
            # mutar el JSONB en sitio no marca la columna como sucia. Es el mismo defecto que
            # dejó `inputs_json` sin escribir en VER.4.
            documento.doc_metadata = metadatos
            resultado.actualizadas += 1

    return resultado
