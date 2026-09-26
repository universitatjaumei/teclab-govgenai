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

from langdetect import LangDetectException, detect

from server.app.core.lengua_del_corpus import codi_del_corpus


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
