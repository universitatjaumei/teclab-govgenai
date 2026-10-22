"""La URL de un documento del corpus es una dirección web o una clave, nunca otro esquema.

`canonical_url` acaba en el `href` de las fuentes que cita el asistente, también en el widget que
se embebe en webs ajenas. El frontend ya filtra el esquema al pintarlo; esto es la otra mitad:
que un `javascript:` o un `data:` no entre al corpus. Lo que no tiene esquema —el nombre del
fichero, la clave de almacenamiento de una subida— sigue valiendo.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from server.app.modules.agents_hub.ingestion.corpus.manifest import entry_from_frontmatter

META = {"language": "es", "title": "Reglamento"}


@pytest.mark.parametrize(
    "url",
    [
        "https://www.uji.es/norma",
        "http://www.uji.es/norma",
        "reglamento.md",
        "ingestion/chatbot/job.md",
        "C:/corpus/reglamento.md",
    ],
)
def test_should_accept_web_addresses_and_keys(url):
    entrada = entry_from_frontmatter(META, relative_path="reglamento.md", source_url=url)

    assert entrada.source_url == url


@pytest.mark.parametrize(
    "url",
    ["javascript:alert(1)", "JavaScript:alert(1)", "data:text/html,<b>x</b>", "vbscript:x", "file:///etc/passwd"],
)
def test_should_refuse_any_other_scheme(url):
    with pytest.raises(ValidationError):
        entry_from_frontmatter(META, relative_path="reglamento.md", source_url=url)


@pytest.mark.asyncio
async def test_should_refuse_it_also_from_the_frontmatter_of_an_upload():
    """El camino real: `url_oficial` del front-matter pasa a `source_url` en la fuente."""
    from server.app.modules.agents_hub.ingestion.corpus.source import MarkdownSubido

    texto = "---\nlanguage: es\ntitle: R\nurl_oficial: javascript:alert(1)\n---\n\n# R\n\nTexto.\n"

    with pytest.raises(ValidationError):
        await MarkdownSubido("r.md", texto, url_por_defecto="ingestion/x/y.md").list_entries()
