"""`val` y `ca` son la misma lengua, y el sistema tiene que escribirla de una sola manera.

**El defecto.** El corpus llama `val` al valenciano y `langdetect` lo llama `ca`. ACT.2 tradujo
`ca`→`val` **en la detección**, que es por donde entra la lengua de la *pregunta*, y ahí el
desajuste quedó cerrado. Pero la lengua entra al sistema por más puertas que esa, y las demás
siguieron abiertas:

* **Los documentos.** Tres del corpus de producción llevan `language='ca'` —los ingirió el
  camino que hoy normaliza, antes de que normalizara—. Como el emparejamiento de hermanas
  idiomáticas todavía no declara ninguna pareja, el filtro de metadatos no los esconde; lo que sí
  hacen es ordenarse detrás en `prefer` y **disparar el aviso de traducción contra una pregunta
  en valencià**, que es un aviso falso sobre la propia lengua de quien pregunta.
* **`fixed:ca`.** La validación de LANG.1 comprueba la **forma** del código, no su pertenencia,
  a propósito: otra administración puede desplegar esto en gallego. Así que `fixed:ca` se acepta
  y no prefiere ninguna versión de ninguna norma, en silencio. `hub_opciones_router` evita que el
  panel lo mande, pero el panel no es la única vía a la API.

**El arreglo es tener un solo sitio donde se diga.** Tres traducciones repartidas por tres
módulos son tres sitios donde olvidarse de la cuarta puerta. La lista de equivalencias sigue
siendo explícita y exactamente una, como en el detector: lo que cambia es que ahora vive donde la
pueden usar la detección, los modos de lengua y la ingesta.

**Lo que este fichero NO comprueba** es que no queden filas con `ca` en la base: eso lo arregla
la migración y lo comprueba `alembic upgrade`, no un test unitario.
"""

from __future__ import annotations

import pytest


class TestElCodigoDelCorpus:
    """Una función, y la lista de equivalencias exactamente una vez."""

    def test_ca_es_val(self) -> None:
        from server.app.core.lengua_del_corpus import codi_del_corpus

        assert codi_del_corpus("ca") == "val"

    def test_val_se_queda_como_esta(self) -> None:
        from server.app.core.lengua_del_corpus import codi_del_corpus

        assert codi_del_corpus("val") == "val"

    @pytest.mark.parametrize("codigo", ["es", "en", "fr", "gl", "eu"])
    def test_las_demas_lenguas_no_se_tocan(self, codigo: str) -> None:
        """Traducir sólo una cosa es el punto: esto no es un catálogo de lenguas admitidas."""
        from server.app.core.lengua_del_corpus import codi_del_corpus

        assert codi_del_corpus(codigo) == codigo

    def test_sin_lengua_sigue_sin_lengua(self) -> None:
        """`None` significa «no se sabe», y convertirlo en una lengua sería inventarla."""
        from server.app.core.lengua_del_corpus import codi_del_corpus

        assert codi_del_corpus(None) is None


class TestLaLenguaFijadaHablaElCodigoDelCorpus:
    """`fixed:ca` y `fixed:val` tienen que preferir la misma versión de cada norma.

    Si no, quien administra elige «Valencià» por la API y obtiene una preferencia que no prefiere
    nada — sin error, sin aviso y sin manera de notarlo salvo comparando respuestas.
    """

    def test_fixed_ca_fija_el_codigo_del_corpus(self) -> None:
        from server.app.core.language_mode import lengua_fijada

        assert lengua_fijada("fixed:ca") == "val"

    def test_fixed_val_sigue_siendo_val(self) -> None:
        from server.app.core.language_mode import lengua_fijada

        assert lengua_fijada("fixed:val") == "val"

    def test_las_demas_lenguas_se_fijan_tal_cual(self) -> None:
        from server.app.core.language_mode import lengua_fijada

        assert lengua_fijada("fixed:es") == "es"

    def test_lo_que_no_fija_lengua_sigue_sin_fijarla(self) -> None:
        from server.app.core.language_mode import lengua_fijada

        assert lengua_fijada("prefer") is None
        assert lengua_fijada("fixed:ESP") is None


class TestLaDeteccionSigueDevolviendoElCodigoDelCorpus:
    """Regresión de ACT.2: el detector delega, pero el contrato no cambia."""

    def test_el_detector_nunca_devuelve_ca(self) -> None:
        from server.app.modules.agents_hub.services.language_detector import detect_language

        assert detect_language("Aquest reglament regula el règim de dedicació del professorat "
                              "i les seues obligacions docents a la universitat.") == "val"

    def test_el_defecto_tambien_se_traduce(self) -> None:
        from server.app.modules.agents_hub.services.language_detector import detect_language

        assert detect_language("hola", default="ca") == "val"


class TestElCorpusNoAdmiteDosCodigosParaElValenciano:
    """La puerta de entrada del paquete de corpus, que es la otra que escribe documentos."""

    def test_un_documento_declarado_en_ca_se_guarda_como_val(self) -> None:
        from server.app.modules.agents_hub.ingestion.corpus.manifest import (
            CorpusDocumentEntry,
        )

        entrada = CorpusDocumentEntry(
            relative_path="normativa/exemple.md",
            source_url="https://www.uji.es/exemple",
            language="ca",
        )

        assert entrada.language == "val", (
            "el paquete de corpus puede meter un documento en `ca`, y entonces la misma lengua "
            "convive con dos códigos en `hub_documents`: el aviso de traducción salta contra "
            "una pregunta en valencià y `prefer` ordena la norma detrás de las demás."
        )


class TestLaIngestaNormalizaLoQueLeDicen:
    """El camino del vigilante: `language=` viene del job o del front-matter del `.md`."""

    def test_el_idioma_recibido_pasa_por_el_normalizador(self) -> None:
        import inspect

        from server.app.modules.agents_hub.ingestion import watcher

        fuente = inspect.getsource(watcher.IngestionWatcher.process_source)
        assert "codi_del_corpus" in fuente, (
            "`process_source` guarda el `language=` que le dan sin normalizarlo. El job y el "
            "front-matter del `.md` son entradas externas: un `language: ca` declarado a mano "
            "entra tal cual y el documento queda con el código que no usa nadie más."
        )
