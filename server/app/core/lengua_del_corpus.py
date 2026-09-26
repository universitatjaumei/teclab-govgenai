"""El código con el que este sistema escribe cada lengua. Deploy: shared.

**Hay exactamente una equivalencia, y es `ca` → `val`.** El corpus llama `val` al valenciano
—lo fija `docs/CONTRATO_MD_CORPUS.md`— y `langdetect` lo llama `ca`. Mientras los dos códigos
convivieron nunca coincidían: `prefer` metía las preguntas en valencià en el saco de «otra
lengua» y el aviso de traducción comparaba `val` contra `ca`, así que saltaba siempre.

ACT.2 lo cerró **en la detección**, que es por donde entra la lengua de la pregunta. La lengua
entra por más puertas: el `language:` del front-matter de un `.md`, el `idioma` del manifiesto de
un paquete de corpus, y el `fixed:<código>` que una organización puede mandar por la API sin
pasar por el panel. Esas tres seguían admitiendo `ca`, y lo que dejan detrás no es un error: es un
documento que existe, se recupera y se ordena mal.

**Por qué aquí y no en cada sitio.** Tres traducciones repartidas son tres sitios donde olvidarse
de la cuarta puerta; ya pasó con estas mismas. Y por qué no al revés —normalizar el corpus a
`ca`—: el código del corpus es el que está escrito en los documentos y en su contrato, y
cambiarlo costaría reescribir los `.md` y reindexar; traducir en la frontera cuesta una función.

**No es un catálogo de lenguas admitidas.** Cualquier código de 2-3 letras sigue siendo válido
—otra administración puede desplegar esto en gallego o en euskera— y esta función lo deja pasar
sin tocarlo. Lo único que hace es escoger entre dos maneras de escribir **una** lengua.
"""
from __future__ import annotations

#: De lo que dice el mundo a lo que dice el corpus. Explícito y no un `.replace()`: quien lea
#: esto tiene que ver que la lista de traducciones es exactamente una.
_AL_CODIGO_DEL_CORPUS = {"ca": "val"}


def codi_del_corpus(codigo: str | None) -> str | None:
    """El código con el que este sistema escribe esa lengua. **Nunca `ca`.**

    `None` se devuelve tal cual: significa «no se sabe la lengua», y convertirlo en una lengua
    sería inventarla.
    """
    if codigo is None:
        return None
    return _AL_CODIGO_DEL_CORPUS.get(codigo, codigo)
