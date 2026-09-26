"""Los modos de política de lengua, y su validación. Deploy: shared.

Tres modos y solo tres:

* **`prefer`** — el de siempre y el defecto: detecta la lengua de la pregunta, prefiere esa
  versión del corpus **dentro de la misma vigencia** e instruye responder en ella.
* **`none`** — sin política: ni detección, ni orden por lengua, ni instrucción de lengua en el
  prompt, ni aviso de traducción. Es lo que quiere una organización monolingüe cuyo corpus está
  en una sola lengua: la política no aporta nada y cuesta una llamada a `langdetect` por consulta.
* **`fixed:<código>`** — «responde siempre en X, pregunten como pregunten». Es el caso que no
  existía: hoy quien escribe en catalán a un ayuntamiento castellanohablante recibe la respuesta
  en catalán, y el organismo no tiene dónde decidir lo contrario.

**Vive en `core/` porque lo comparten tres capas** que no deben depender entre sí: la factoría del
grafo (edge), los routers de chatbot y de organización (cloud) y el contrato que lee el panel. Y
está en un módulo y no en un `Enum` de columna a propósito: `fixed:<código>` es un modo
**paramétrico**, así que el conjunto de valores válidos no es enumerable y un `CheckConstraint` no
podría expresarlo.

Por qué se valida: `HubChatbot.language_mode` es `String(20)` libre, así que hasta LANG.1 un
`language_mode="castellano"` se guardaba tal cual y **caía a `prefer` sin avisar a nadie** —la
factoría no lo miraba, y ningún sitio lo rechazaba—. Un typo que degrada en silencio es peor que
un 422.
"""
from __future__ import annotations

import re

from server.app.core.lengua_del_corpus import codi_del_corpus

MODO_PREFERIR = "prefer"
MODO_SIN_POLITICA = "none"
PREFIJO_FIJO = "fixed:"

#: Los dos modos sin parámetro. `fixed:<código>` se valida por forma, no por pertenencia.
MODOS_SIMPLES: tuple[str, ...] = (MODO_PREFERIR, MODO_SIN_POLITICA)

#: Un código ISO 639 de 2 o 3 letras minúsculas. Ni región ni mayúsculas: la lengua del corpus se
#: guarda así (`ca`, `es`, `en`, `val`) y aceptar `es-ES` o `ESP` daría un valor que no casa con
#: ninguna versión de una norma, o sea una preferencia que no prefiere nada.
_CODIGO = re.compile(r"^[a-z]{2,3}$")

#: El mensaje del 422. Enumera los modos porque un «valor inválido» a secas obliga a quien
#: administra a leer el código para saber qué se admite.
MENSAJE_DE_ERROR = (
    "Modo de lengua no válido. Admitidos: "
    f"«{MODO_PREFERIR}» (detecta la lengua de la pregunta), "
    f"«{MODO_SIN_POLITICA}» (sin política de lengua) "
    f"y «{PREFIJO_FIJO}<código>» con un código de 2 o 3 letras minúsculas, "
    f"por ejemplo «{PREFIJO_FIJO}es»."
)


def lengua_fijada(modo: str | None) -> str | None:
    """El código de `fixed:<código>` **tal como lo escribe el corpus**, o `None` si el modo no
    fija ninguna lengua.

    Una función y no un `split(":")` repartido por ahí: quien la use no tiene que saber cómo se
    escribe el modo, que es justamente lo que permite cambiar la forma sin ir buscando llamadores.

    Y devuelve el código del corpus, no el que le mandaron: `fixed:ca` pasa la validación —que
    comprueba la **forma**, a propósito, para que otra administración pueda desplegar esto en
    gallego— y sin esto fijaría una lengua que ningún documento lleva, o sea una preferencia que
    no prefiere nada, en silencio. `hub_opciones_router` evita que el panel lo mande; el panel no
    es la única vía a la API.
    """
    if not modo or not modo.startswith(PREFIJO_FIJO):
        return None
    codigo = modo[len(PREFIJO_FIJO) :]
    return codi_del_corpus(codigo) if _CODIGO.match(codigo) else None


def es_valido(modo: str | None) -> bool:
    """Si el valor es uno de los tres modos. `None` es válido: en la cascada significa heredar."""
    if modo is None:
        return True
    if modo in MODOS_SIMPLES:
        return True
    return lengua_fijada(modo) is not None


def valida_language_mode(modo: str | None) -> str | None:
    """El valor si es válido; `ValueError` con los modos enumerados si no.

    Pensada para un `field_validator` de Pydantic, que convierte el `ValueError` en 422.
    """
    if es_valido(modo):
        return modo
    raise ValueError(MENSAJE_DE_ERROR)
