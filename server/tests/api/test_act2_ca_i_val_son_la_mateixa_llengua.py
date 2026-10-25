"""ACT.2 — `ca` y `val` son la misma lengua en todo el sistema.

**El detector decía `ca` y el corpus dice `val`, así que nunca coincidían.** Y ya se había
tropezado con ello: `graph_factory.py:203` documenta que el parámetro `language` «se recibe y
**no se usa**» porque «filtrar por él dejaba la búsqueda vacía siempre: los chunks del corpus
llevan `val` y `es`, y el grafo resuelve la lengua de la conversación como `ca`». La solución de
entonces fue dejar de usar la lengua; el desajuste se quedó.

Dos consecuencias que seguían vivas, y que estos tests fijan:

1. En una pregunta en valenciano, `PreferLanguagePolicy` metía **todo** en el saco de «otra
   lengua», así que su ordenación por lengua no hacía nada.
2. El aviso de traducción comparaba `val` contra `ca`: **saltaba siempre**. Y peor,
   `_NOMBRE_DE_LA_LENGUA` no tenía la clave `val`, así que el texto salía con el código crudo
   («⚠️ La normativa citada está en **val**»).

Por qué se normaliza en la FRONTERA y no en el corpus: los fragmentos son 60.859 filas y su
lengua la fija el contrato del corpus, donde `val` es el código. La detección es un solo punto.
"""

from server.app.modules.agents_hub.services.turno_de_chat import _build_translation_warning
from server.app.modules.agents_hub.services.language_detector import detect_language

VALENCIA = (
    "Quantes convocatòries d'avaluació tinc per assignatura en un grau i com es "
    "formalitza la matrícula?"
)
CASTELLA = (
    "¿Cuántas convocatorias de evaluación tengo por asignatura en un grado y cómo se "
    "formaliza la matrícula?"
)


class TestLaDeteccionDevuelveElCodigoDelCorpus:

    def test_should_return_val_for_valencian(self):
        """`langdetect` dice `ca`; el corpus dice `val`. Manda el corpus."""
        assert detect_language(VALENCIA) == "val"

    def test_should_keep_es_and_en_untouched(self):
        assert detect_language(CASTELLA) == "es"
        assert detect_language("How many exam sittings do I have per subject?") == "en"

    def test_should_not_return_ca_for_anything(self):
        """`ca` no es un código de este sistema: si alguno vuelve, el desajuste ha renacido."""
        for texto in (VALENCIA, CASTELLA, "Quin és el termini per a sol·licitar una beca?"):
            assert detect_language(texto) != "ca"


class TestElAvisoDeTraduccionEntiendeVal:

    def test_should_not_warn_when_asking_and_citing_in_valencian(self):
        """**El defecto principal.** La fuente real es `val` y la pregunta se detectaba `ca`:
        el aviso saltaba en TODAS las preguntas en valenciano sobre normas en valenciano, que es
        el caso más frecuente del corpus (195 de 290 normas sólo existen en valencià)."""
        assert _build_translation_warning(
            lengua_de_la_fuente="val", lengua_de_la_pregunta="val"
        ) is None

    def test_should_name_the_language_and_never_the_raw_code(self):
        """Salía «está en val» porque la tabla de nombres no tenía la clave del corpus."""
        aviso = _build_translation_warning(
            lengua_de_la_fuente="val", lengua_de_la_pregunta="es"
        )
        assert aviso is not None
        assert "valenciano" in aviso
        assert " val." not in aviso and " val " not in aviso

    def test_should_warn_in_valencian_when_the_source_is_spanish(self):
        aviso = _build_translation_warning(
            lengua_de_la_fuente="es", lengua_de_la_pregunta="val"
        )
        assert aviso is not None
        assert "castellà" in aviso
        assert "està" in aviso, "el aviso a quien escribe en valencià va en valencià"

    def test_should_still_warn_across_languages(self):
        assert _build_translation_warning(
            lengua_de_la_fuente="es", lengua_de_la_pregunta="val"
        ) is not None
        assert _build_translation_warning(
            lengua_de_la_fuente="val", lengua_de_la_pregunta="en"
        ) is not None


class TestPreferOrdenaDeVerdadEnValenciano:

    def _item(self, language: str, source_id: str):
        from server.app.modules.agents_hub.agent.public_graphs.strategies.retrieval_contract import (  # noqa: E501
            EvidenceItem,
        )

        return EvidenceItem(
            source_id=source_id,
            content="Text.",
            source_url=f"https://www.uji.es/{source_id}",
            title=f"Norma {source_id}",
            language=language,
            metadata={},
        )

    def test_should_put_the_query_language_first(self):
        """Con `ca` contra `val` los dos items caían en «otra lengua» y el orden era un no-op."""
        from server.app.modules.agents_hub.agent.public_graphs.strategies.protocols import (
            PreferLanguagePolicy,
        )

        items = [self._item("es", "REG-001-es"), self._item("val", "REG-001")]
        ordenados = PreferLanguagePolicy().filter_items("val", items)

        assert [i.source_id for i in ordenados] == ["REG-001", "REG-001-es"]

    def test_should_not_drop_anything(self):
        """`prefer` ordena; descartar sería cambiar de política."""
        from server.app.modules.agents_hub.agent.public_graphs.strategies.protocols import (
            PreferLanguagePolicy,
        )

        items = [self._item("es", "A"), self._item("val", "B")]
        assert len(PreferLanguagePolicy().filter_items("val", items)) == 2
