"""#265b — Dos regresiones del arreglo de #265, encontradas al revisar la PR #283.

`MarkdownSubido` hace que un `.md` del panel entre por el reconciliador, que identifica cada
documento por su URL canónica y su lengua. Dos detalles de cómo construía la entrada rompían
esa identidad:

* **La URL por omisión era el nombre del fichero.** Sin URL en el formulario ni `url_oficial`
  en el front-matter, la entrada quedaba con `source_url = "reglament.md"`, y dos documentos
  distintos subidos con el mismo nombre se sustituían en silencio. Antes de #265 la URL por
  omisión era la clave de almacenamiento del trabajo, que es única.
* **El idioma del formulario no se normalizaba.** Se aplicaba con `model_copy`, que no pasa por
  los validadores de Pydantic, así que el `ca` del selector del panel no se convertía en `val`
  y el reconciliador no encontraba el documento guardado como `val`.
"""
from __future__ import annotations

import pytest

from server.app.modules.agents_hub.ingestion.corpus.source import MarkdownSubido

SIN_URL = "---\nlanguage: es\ntitle: Reglamento\n---\n\n# Reglamento\n\nTexto.\n"
CLAVE = "ingestion/chatbot-1/0b6c2a4e-job.md"


@pytest.mark.asyncio
async def test_should_use_the_storage_key_when_neither_form_nor_frontmatter_give_a_url():
    [entrada] = await MarkdownSubido("reglament.md", SIN_URL, url_por_defecto=CLAVE).list_entries()

    assert entrada.source_url == CLAVE


@pytest.mark.asyncio
async def test_should_still_prefer_the_frontmatter_url_over_the_storage_key():
    texto = SIN_URL.replace("title:", "url_oficial: https://www.uji.es/r\ntitle:")
    [entrada] = await MarkdownSubido("reglament.md", texto, url_por_defecto=CLAVE).list_entries()

    assert entrada.source_url == "https://www.uji.es/r"


@pytest.mark.asyncio
async def test_should_normalise_the_language_chosen_in_the_form():
    # El selector del panel ofrece `ca`; el corpus escribe `val`.
    [entrada] = await MarkdownSubido(
        "reglament.md", SIN_URL, url_por_defecto=CLAVE, language="ca"
    ).list_entries()

    assert entrada.language == "val"
