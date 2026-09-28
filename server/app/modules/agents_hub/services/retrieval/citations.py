"""Construcción de la URL de cita (ING.0.4). Deploy: edge.

El corpus trae ancla estable por unidad citable (`docs/CONTRATO_MD_CORPUS.md`), y el
chunker la deja en `chunk_metadata['ancora']`. Aquí se convierte en el fragmento de la
URL, que es lo que hace la cita verificable: el usuario abre exactamente el artículo del
que sale la respuesta, no el documento de 40 páginas.
"""
from __future__ import annotations

import os

from server.app.modules.agents_hub.ingestion.ancores_del_diari import (
    CLAVE as ANCORES_DEL_DIARI,
)

# ── Cita al sitio publicado (PUB.3) ───────────────────────────────────────────────────
#
# El PDF oficial no tiene anclas: se abre por la primera página y quien pregunta ha de
# buscar el artículo a mano. El sitio de publicación **sí** las tiene —`html/<slug>.html#art-9`
# abre el artículo—, y es lo que convierte el esfuerzo de generar 6.571 anclas en algo que
# el ciudadano nota.
#
# Se configura por entorno porque la URL depende del despliegue, y **vacía significa
# desactivado**: sin sitio publicado se cita el PDF, como hasta ahora. Nada que decidir
# hasta que exista de verdad.
BASE_DEL_SITIO = "CORPUS_SITE_BASE_URL"


def _slug_de(documento) -> str | None:
    """Nombre del `.md` del que salió el documento, que es el slug de su página.

    Viaja en `doc_metadata['relative_path']` desde la ingesta. No se deriva de
    `canonical_url` porque para los 234 documentos publicados esa URL es la del PDF del
    portal, que no dice nada del nombre de la página.
    """
    metadatos = getattr(documento, "doc_metadata", None) or {}
    ruta = metadatos.get("relative_path")
    if not ruta:
        return None
    nombre = str(ruta).replace("\\", "/").rsplit("/", 1)[-1]
    return nombre[:-3] if nombre.endswith(".md") else nombre


# ── Normas externas (BOE, DOGV) ───────────────────────────────────────────────────────
#
# El sitio de publicación tiene página para las normas **propias** de la Universidad. La Ley
# de Contratos, la LPAC y las de la Generalitat no: viven en su diario oficial. Citarlas
# como si tuvieran página daba un 404, que es lo que se vio al probar el asistente.
#
# La señal es explícita en el corpus y no hay que deducirla de la URL ni del título.
TIPO_EXTERNA = "norma_externa"

# **Aquí se tradujo `art-118` a `#a118` hasta el 2026-09-24, y era una regla inventada.**
#
# El principio que la acompañaba era bueno —«un ancla inventada es peor que ninguna: lleva a un
# punto que no existe sin que se note»— y el hecho, falso: se daba por supuesto que el BOE ancla
# siempre los artículos por su número. **No lo hace.** Usa dos esquemas según la norma, y sólo
# coinciden en los artículos de un dígito:
#
#     Ley Orgánica 6/2001    #a110  → Artículo 110   (el ancla ES el número de artículo)
#     Ley 9/2017 Contratos   #a1-10 → Artículo 18    (identificador de bloque; el propio BOE lo
#                                                     marca como «[Bloque 26: #a1-10]»)
#
# El barrido del corpus encontró **785 anclas rotas, todas del BOE y ninguna de nuestro sitio**,
# concentradas en nueve normas. De la Ley de Contratos salieron 338: exactamente todos sus
# artículos del 10 en adelante, porque la regla acertaba del 1 al 9 y fallaba en el resto.
#
# Y ni el esquema bueno es seguro: en la 6/2001 el `#a114` no existe porque ese artículo está
# derogado.
#
# **No hay fórmula que arregle esto**: para saber qué ancla lleva al artículo 18 hay que leer la
# página. **Y eso es lo que hace la issue #157**: la ingesta lee el texto consolidado una vez y
# deja el mapa `art-18 → a1-10` en `doc_metadata` (`ingestion/ancores_del_diari.py`). Aquí sólo
# se consulta.
#
# Lo que no cambia es la regla: **el mapa es la única fuente del fragmento**. Si no trae la
# ancora que se cita —artículo derogado, disposición, norma de un diario que no se sabe leer, o
# página que nunca se pudo descargar—, se cita la norma **sin fragmento**: el enlace lleva a la
# cabecera del documento correcto en vez de a un punto equivocado del documento correcto.


def _es_externa(documento) -> bool:
    metadatos = getattr(documento, "doc_metadata", None) or {}
    return metadatos.get("tipus_document") == TIPO_EXTERNA


def _url_en_el_diario_oficial(documento, metadata: dict | None) -> str:
    metadatos = getattr(documento, "doc_metadata", None) or {}
    base = (
        metadatos.get("url_oficial")
        or metadatos.get("url_eli")
        or getattr(documento, "canonical_url", None)
        or ""
    ).split("#", 1)[0]

    # Issue #157 — el fragmento sale del mapa leído en la ingesta, y de ningún otro sitio. Un
    # `.get` sobre el mapa es exactamente la regla que se quiere: lo que no esté, no se cita.
    mapa = metadatos.get(ANCORES_DEL_DIARI) or {}
    del_diario = mapa.get((metadata or {}).get("ancora")) if base else None
    return f"{base}#{del_diario}" if del_diario else base


def _solo_si_es_url(valor: str | None) -> str | None:
    """`valor` si es una dirección; `None` si no lo es (issue #14).

    **Medido en producción el 2026-09-24**: de 2.607 URL de cita del corpus, 37 no eran URL sino
    nombres de fichero —`20050715_UJI_GER_Circular_11_05_….md`—, porque eso es lo que esos
    documentos llevan en `canonical_url`. La cita salía como `[Circular 11/05](20050715_….md)`,
    que en un navegador no lleva a ninguna parte.

    Es la peor de las tres formas de fallar que tiene un enlace: no da error, se ve como un
    enlace normal, y **aparenta verificación**. Devolver `None` hace que el contrato de citas no
    tenga a dónde enlazar y cite el documento **sin enlace** — se pierde comodidad y no
    veracidad, que es la misma regla con la que `citation_validator` degrada un ancla.

    La comprobación es de forma y no de existencia. Si la dirección resuelve o no lo dice
    `evaluacion/verificar_enlaces.py`, que sale a la red; esto sólo impide emitir algo que ni
    siquiera es una dirección.
    """
    if not valor:
        return None
    limpio = valor.strip()
    return limpio if limpio.startswith(("http://", "https://")) else None


def url_de_cita(documento, metadata: dict | None) -> str | None:
    """URL a la que apunta la cita, en este orden de preferencia.

    1. **Diario oficial**, si es una norma externa: no tiene página en nuestro sitio.
    2. **Nuestro sitio publicado**, si está configurado: es el único que tiene anclas.
    3. **El PDF**, que es lo que había antes de PUB.3.
    """
    if _es_externa(documento):
        return _solo_si_es_url(_url_en_el_diario_oficial(documento, metadata))

    base = (os.getenv(BASE_DEL_SITIO) or "").strip().rstrip("/")
    slug = _slug_de(documento) if base else None
    if base and slug:
        return _solo_si_es_url(f"{base}/html/{slug}.html{_fragmento(metadata)}")

    # Issue #15: aquí se cita el PDF, y **sin ancla**. El ancla la componemos nosotros a partir
    # de los encabezados del `.md` ingerido, así que sólo la sirve quien publica ese `.md` como
    # HTML — nuestro sitio, que es la rama de arriba. Pegada a un PDF no lleva a ninguna parte:
    # el visor ignora el fragmento que no entiende y el lector aterriza en la primera página
    # creyendo que va al artículo.
    #
    # Es el mismo criterio que la rama del diario oficial aplica una función más arriba —sólo
    # compone ancla si el destino es el BOE, y si no la quita—, y el que `citation_validator`
    # defiende para lo que dice el modelo: «componer un ancla que nadie leyó sería fabricar un
    # puntero». El puntero lo fabricábamos aquí, un paso antes de que el contrato mirase.
    #
    # Sin ancla en la evidencia, una cita anclada del modelo se degrada sola con la lógica que
    # ya existe. No hace falta tocar el validador.
    canonica = getattr(documento, "canonical_url", None)
    return _solo_si_es_url(_sin_ancla(canonica))


def _fragmento(metadata: dict | None) -> str:
    ancora = (metadata or {}).get("ancora")
    return f"#{ancora}" if ancora else ""


def _sin_ancla(url: str | None) -> str | None:
    """La URL sin fragmento. `None` y cadena vacía se devuelven tal cual."""
    return url.split("#", 1)[0] if url else url


def with_anchor(url: str | None, metadata: dict | None) -> str | None:
    """Añade el fragmento del ancla a la URL, si el fragmento existe.

    Sustituye un fragmento previo en lugar de acumularlo: la URL canónica del documento
    puede traer uno y el del fragmento recuperado es el que manda.
    """
    if not url:
        return url
    ancora = (metadata or {}).get("ancora")
    if not ancora:
        return url
    return f"{url.split('#', 1)[0]}#{ancora}"


# ─────────────────── Autoridad del fragmento (FAQ.2) ───────────────────
#
# Una respuesta de preguntas frecuentes **no es una norma**. Si se cita con la misma forma que
# un artículo, se publica una respuesta no revisada con la autoridad de la normativa, y eso no
# se ve leyendo la respuesta.
#
# `content_class` ya distingue `regulation | faq | generic` desde el contrato del corpus; esto
# es lo que la convierte en algo visible para quien pregunta.

ORIENTATIVA = "orientativa"

_AVISO = (
    "[Respuesta orientativa de preguntas frecuentes: no es el texto de la norma. "
    "Cítala como tal y remite a la norma que la sostiene si la hay.]"
)


def etiqueta_de_autoridad(metadata: dict | None) -> str | None:
    """`"orientativa"` si el fragmento sale de una FAQ; `None` en cualquier otro caso.

    Devuelve `None` y no `"normativa"` a propósito: lo que hay que marcar es la excepción.
    Etiquetar también las normas obligaría a que todo el corpus antiguo declarara su clase
    para no parecer sospechoso, cuando el default (`generic`) no dice nada malo de él.
    """
    if (metadata or {}).get("content_class") == "faq":
        return ORIENTATIVA
    return None


def marcar_autoridad(texto: str, metadata: dict | None) -> str:
    """Antepone el aviso al fragmento cuando viene de una FAQ.

    Va en el texto que ve el **modelo**, no solo en el JSON: si el aviso solo viajara en la
    carga útil, la respuesta redactada podría presentar la sugerencia como si fuera la norma
    y el frontend pintaría una etiqueta que contradice lo que se lee.

    Es la misma razón por la que la nota de vigencia del §8.13 del contrato va DENTRO del
    cuerpo del artículo y no en la cabecera del documento: lo que no viaja con el fragmento
    no llega al que responde.
    """
    if etiqueta_de_autoridad(metadata) is None:
        return texto
    return f"{_AVISO}\n{texto}"
