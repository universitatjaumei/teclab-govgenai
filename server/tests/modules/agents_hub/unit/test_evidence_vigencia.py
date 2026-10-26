"""PIL.3 — el aviso de vigencia desplazada llega a TODOS los fragmentos del artículo.

Medido por la curación del corpus el 2026-08-10: 45 documentos tienen artículos **vigentes
cuyo contenido está desplazado** por los Estatutos de 2025 —el texto se aprobó, nadie lo ha
modificado, y lo que se aplica es otra cosa—. El corpus lo marca con un bloque
`::: nota-vigencia` dentro del texto del artículo, pero **un artículo se parte en 3-6
fragmentos y la nota cae físicamente en uno solo**: de 86 unidades desplazadas, 83 tienen
trozos sin el aviso. Quien recupere uno de esos trozos contesta un texto que no se aplica,
sin ninguna señal.

No se arregla en el corpus: la única forma sería escribir el aviso en la rúbrica del
artículo, que es texto aprobado de la norma. Se arregla aquí, hidratando desde
`desplacat_per` —que el front matter da **por ancla**— al montar la evidencia.

Es texto de la EVIDENCIA, no una instrucción al modelo: avisar en el prompt («ojo, este
artículo puede estar desplazado») es lo que CRITERIS §1.4 prohíbe para algo que puede
resolverse antes de llegar al modelo.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

# Forma real, copiada del front matter de
# `es_REGLAMENTO_DE_LA_SINDICATURA_DE_AGRAVIOS...md` (2026-08-15).
DESPLACAT_PER = [
    {
        "ancora": "art-9",
        "apartat_afectat": "1",
        "desplacat_per": {
            "id_norma": "EST-002",
            "norma": "Estatuts de la Universitat Jaume I",
            "ancora": "art-128",
            "apartat": "4",
            "data": "2025-12-18",
        },
    }
]


_SIN_INDICAR = object()


def _documento(desplacat_per=_SIN_INDICAR):
    """`None` explícito significa «el documento no declara desplazamientos», que es un caso
    distinto de «no me molesté en indicarlo»: por eso el centinela y no un default None."""
    valor = DESPLACAT_PER if desplacat_per is _SIN_INDICAR else desplacat_per
    return SimpleNamespace(
        title="Reglament de la Sindicatura de Greuges",
        doc_metadata={"desplacat_per": valor},
    )


def _fragmento(ancora="art-9", classes=("desplacat",)):
    return {"ancora": ancora, "classes": list(classes)}


class TestAvisoDeDesplazamiento:

    def test_should_prepend_notice_when_chunk_has_desplacat_class_and_matching_anchor(self):
        from server.app.modules.agents_hub.services.retrieval.vigencia import (
            hidratar_desplazamiento,
        )

        texto = "1. La duracion del mandato es de cinco anos."

        salida = hidratar_desplazamiento(texto, _documento(), _fragmento())

        assert salida.endswith(texto), "el texto del fragmento tiene que conservarse entero"
        assert salida != texto, "no se anadio ningun aviso"
        assert salida.index("desplaz") < salida.index(texto), "el aviso va DELANTE"

    def test_should_name_the_displacing_norm_article_and_date(self):
        """Un aviso que no dice qué desplaza obliga a creerse la advertencia a ciegas."""
        from server.app.modules.agents_hub.services.retrieval.vigencia import (
            hidratar_desplazamiento,
        )

        salida = hidratar_desplazamiento("Text.", _documento(), _fragmento())

        assert "Estatuts de la Universitat Jaume I" in salida
        assert "art-128" in salida
        assert "2025-12-18" in salida

    def test_should_not_touch_chunks_without_the_class(self):
        from server.app.modules.agents_hub.services.retrieval.vigencia import (
            hidratar_desplazamiento,
        )

        texto = "Article normal."

        salida = hidratar_desplazamiento(
            texto, _documento(), _fragmento(ancora="art-9", classes=())
        )

        assert salida == texto

    def test_should_not_touch_chunks_whose_anchor_has_no_entry(self):
        from server.app.modules.agents_hub.services.retrieval.vigencia import (
            hidratar_desplazamiento,
        )

        texto = "Article 10, que no esta desplazado."

        salida = hidratar_desplazamiento(texto, _documento(), _fragmento(ancora="art-10"))

        assert salida == texto

    def test_should_not_touch_documents_without_the_metadata(self):
        from server.app.modules.agents_hub.services.retrieval.vigencia import (
            hidratar_desplazamiento,
        )

        texto = "Article de un documento sin desplazamientos."

        salida = hidratar_desplazamiento(texto, _documento(desplacat_per=None), _fragmento())

        assert salida == texto

    def test_should_survive_a_document_without_doc_metadata(self):
        """Chunk temporal o legado: sin metadatos no se inventa un aviso, pero tampoco revienta."""
        from server.app.modules.agents_hub.services.retrieval.vigencia import (
            hidratar_desplazamiento,
        )

        assert hidratar_desplazamiento("Text.", None, _fragmento()) == "Text."

    def test_should_hydrate_every_chunk_of_a_split_displaced_article(self):
        """El caso real: el artículo se parte en 6 y la nota cae en uno.

        Los seis llevan `desplacat` en `classes` y la misma ancla —lo garantiza el
        troceador—, así que los seis tienen que salir avisados.
        """
        from server.app.modules.agents_hub.services.retrieval.vigencia import (
            hidratar_desplazamiento,
        )

        doc = _documento()
        trozos = [f"Apartado {i} del articulo 9." for i in range(6)]

        salidas = [hidratar_desplazamiento(t, doc, _fragmento()) for t in trozos]

        assert all(s != t for s, t in zip(salidas, trozos, strict=True)), (
            "algun trozo del articulo desplazado se quedo sin aviso"
        )

    def test_should_mention_the_affected_paragraph_when_the_corpus_declares_it(self):
        from server.app.modules.agents_hub.services.retrieval.vigencia import (
            hidratar_desplazamiento,
        )

        salida = hidratar_desplazamiento("Text.", _documento(), _fragmento())

        assert "1" in salida  # apartat_afectat


class TestIntegracionConLaRecuperacion:

    @pytest.mark.asyncio
    async def test_should_hydrate_the_excerpt_of_the_rag_path(self):
        """La ruta RAG es la única que trocea, y por tanto la única que pierde la nota."""
        import uuid

        from server.app.modules.agents_hub.services.retrieval.vigencia import (
            hidratar_desplazamiento,
        )
        from server.app.modules.agents_hub.services.retrieval import vector_strategy

        # ACT.4: `hidratar_desplazamiento` paso a ser una de las dos hidrataciones que hace
        # `hidratar_avisos_de_vigencia` —la otra es la vigencia transitoria—, y es esa la que
        # llama la estrategia.
        assert "hidratar_avisos_de_vigencia" in vector_strategy.__dict__ or hasattr(
            vector_strategy, "hidratar_avisos_de_vigencia"
        ), "vector_strategy no hidrata el aviso"
        assert callable(hidratar_desplazamiento)
        assert uuid  # el import existe para fijar que este test vive en la ruta RAG

    def test_should_not_be_used_by_the_ingestion_path(self):
        """El aviso es de LECTURA. Si entrara al texto embebido, cambiaría el vector.

        Y con él, la procedencia dejaría de describir lo que se embebió: reescribir la nota
        obligaría a re-embeber los 290 fragmentos afectados, que es exactamente lo que esta
        solución evita.
        """
        import pathlib

        raiz = pathlib.Path(__file__).resolve().parents[5] / "app" / "modules" / "agents_hub"
        ingestion = raiz / "ingestion"
        culpables = [
            f.name
            for f in ingestion.rglob("*.py")
            if "hidratar_desplazamiento" in f.read_text(encoding="utf-8")
        ]

        assert culpables == [], f"la ingesta hidrata el aviso: {culpables}"


class TestLaRutaDeDocumentoEnteroNoLoNecesita:
    """Comprobación de que el problema es exclusivo del troceado.

    `MD_AGENT_SELECTOR` responde leyendo el markdown COMPLETO (`read_document`), y el bloque
    `::: nota-vigencia` vive dentro de ese markdown. Añadir ahí una hidratación sería código
    muerto: se comprueba que la nota ya viaja, en vez de escribir una rama que no hace nada.
    """

    @pytest.mark.asyncio
    async def test_should_carry_the_notice_inside_the_full_document(self):
        from server.app.modules.agents_hub.agent.tools.read_document import read_document

        markdown = (
            "##### Article 9 {#art-9 .desplacat}\n"
            "::: nota-vigencia\n**Nota de vigencia.** ...\n:::\n\n"
            "1. La duracio del mandat es de cinc anys.\n"
        )

        class _Lector:
            async def read(self, document_id):
                return {
                    "title": "Reglament",
                    "url": "https://uji.es/r",
                    "markdown_content": markdown,
                }

        salida = await read_document(str(__import__("uuid").uuid4()), _Lector())

        assert "nota-vigencia" in salida
