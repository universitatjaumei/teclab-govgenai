"""Detector de idioma para mensajes.

**Devuelve el código del CORPUS, no el de `langdetect`** (ACT.2). Es el único punto donde se
produce la lengua de una pregunta, así que es donde se traduce: `langdetect` llama `ca` a lo que
el corpus llama `val`, y mientras los dos códigos convivieron **nunca coincidían**.

Ya se había tropezado con ello y la salida de entonces fue dejar de usar la lengua:
`graph_factory.py` documenta que el parámetro «se recibe y no se usa» porque «filtrar por él
dejaba la búsqueda vacía siempre». El desajuste seguía vivo en dos sitios: `prefer` metía todo en
el saco de «otra lengua» en las preguntas en valenciano, y el aviso de traducción comparaba `val`
contra `ca`, así que saltaba siempre.

Se normaliza aquí y no en el corpus porque el corpus son 60.859 fragmentos y su código lo fija
`CONTRATO_MD_CORPUS.md`; la detección es una función.

**La equivalencia ya no vive aquí**: la detección no es la única puerta por la que entra una
lengua —también el front-matter de un `.md`, el manifiesto de un paquete de corpus y el
`fixed:<código>` de la API—, y tener la lista en cada una es tener dónde olvidarse de la
siguiente. Está en `core/lengua_del_corpus.py`, donde las cuatro la comparten.
"""

import re
from collections.abc import Sequence

from langdetect import DetectorFactory, LangDetectException, detect, detect_langs

from server.app.core.language_mode import LENGUAS_DE_RESPUESTA
from server.app.core.lengua_del_corpus import codi_del_corpus

# `langdetect` es probabilístico y sin semilla fija da resultados distintos para el mismo texto
# ambiguo (#363). Una pregunta no puede cambiar de lengua entre dos ejecuciones.
DetectorFactory.seed = 0

#: Por debajo de esta probabilidad la detección no decide y manda la lengua de la página (#363).
#: Medido con 43 preguntas reales del DOCENTIA: las bien detectadas salen por encima de 0,85 y las
#: dudosas —«Quan estan obertes les enquestes…?», es 0,29— muy por debajo.
UMBRAL_DE_CONFIANZA = 0.8


def detect_language(text: str, default: str = "es") -> str:
    """Detecta el idioma de un texto y lo devuelve en el código del corpus.

    Args:
        text: Texto a analizar
        default: Idioma por defecto si no se puede detectar

    Returns:
        Código de idioma del corpus (`val`, `es`, `en`...). **Nunca `ca`.**
    """
    if len(text.strip()) < 10:
        return codi_del_corpus(default)  # type: ignore[return-value]

    try:
        detectado = detect(text)
    except LangDetectException:
        detectado = default
    return codi_del_corpus(detectado)  # type: ignore[return-value]


def lengua_de_la_pregunta(texto: str, reserva: str | None) -> str:
    """La lengua de una pregunta de chat, **sólo entre las de respuesta** (#363).

    `detect_language` sirve para documentos, que son largos; con una pregunta corta `langdetect`
    dice `pt` o `fr` con toda tranquilidad. Aquí se miran sus candidatas, se quedan las que son
    lenguas de respuesta y:

    - si la mejor pasa del umbral, es esa;
    - si no, la `reserva` —la lengua de la página donde está el widget—;
    - si no hay reserva, la mejor candidata admitida aunque no pase;
    - y si no hay ninguna, la primera lengua de respuesta (`es`), que era el `default` de
      `detect_language`. Devolver `None` dejaría sin preferencia de versión, y el contexto largo
      cargaría el corpus en las dos lenguas, que es justo el coste que #363 quitaba.

    No decide la lengua de la respuesta, que la decide el modelo leyendo la pregunta: decide qué
    versión del corpus se prefiere, y es la reserva que se le da al modelo cuando duda.
    """
    try:
        candidatas = detect_langs(texto) if texto.strip() else []
    except LangDetectException:
        candidatas = []
    pares = [(codi_del_corpus(c.lang), c.prob) for c in candidatas]
    admitidas = [(codigo, prob) for codigo, prob in pares if codigo in LENGUAS_DE_RESPUESTA]
    if admitidas and admitidas[0][1] >= UMBRAL_DE_CONFIANZA:
        return str(admitidas[0][0])
    if reserva is not None:
        return reserva
    return str(admitidas[0][0]) if admitidas else LENGUAS_DE_RESPUESTA[0]


#: Un enlace markdown entero, título incluido, y una URL suelta.
_ENLACE = re.compile(r"\[[^\]]*\]\([^)]*\)|https?://\S+")

#: Por debajo de esto, una vez quitados enlaces y títulos, no se le pregunta a `langdetect`: con
#: tan poco texto se equivoca con toda seguridad, como se midió con las preguntas en #363.
LONGITUD_MINIMA_DE_LA_RESPUESTA = 100


def lengua_de_la_respuesta(
    texto: str, preferida: str, titulos: Sequence[str] = ()
) -> str:
    """En qué lengua ha contestado el modelo (revisión de la PR #365).

    Desde #363 la decide el modelo, así que el aviso de traducción no puede salir de la lengua
    preferida para el corpus. Se detecta sobre la respuesta **sin los enlaces ni los títulos de
    las fuentes**, enlazados o no: están en la lengua de las fuentes y empujarían la detección
    justo hacia la que oculta el aviso.

    - Si queda muy poco texto, la `preferida`: es lo que se hacía antes, y mejor que una
      detección segura y equivocada.
    - Si no, la mejor candidata entre las lenguas de respuesta **aunque no pase del umbral**: la
      reserva de las preguntas aquí sería la preferida, que es justo el valor que ocultaba el
      aviso.
    """
    limpio = _ENLACE.sub(" ", texto)
    for titulo in titulos:
        if titulo:
            limpio = limpio.replace(titulo, " ")
    if len(limpio.strip()) < LONGITUD_MINIMA_DE_LA_RESPUESTA:
        return preferida
    try:
        candidatas = detect_langs(limpio)
    except LangDetectException:
        return preferida
    for candidata in candidatas:
        codigo = codi_del_corpus(candidata.lang)
        if codigo in LENGUAS_DE_RESPUESTA:
            return str(codigo)
    return preferida
