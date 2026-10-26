"""VIS.5 — El aviso de traducción avisa de lo que no es.

`_build_translation_warning` llega al usuario —el widget lo pinta— y **decía lo contrario de lo
que hace falta**. Tres defectos, cada uno con su consecuencia:

1. **Avisaba del idioma de la pregunta, no del de la fuente.** Que alguien pregunte en valencià no
   es una anomalía aquí. Lo que hay que decirle es que **la norma que se le cita está en
   castellano**, porque el enlace le va a llevar a un documento en otra lengua.
2. **Se callaba si la pregunta era en castellano** (`language == "es"` → `None`). Es justo el caso
   más frecuente del corpus real —195 de 290 normas sólo existen en valencià—, así que preguntar
   en castellano y recibir una norma en valencià es lo habitual, y nunca avisaba. Y lo peor: el
   grafo **sí** había decidido que había que avisar, y el texto se descartaba después.
3. **Estaba redactado en castellano y sin acentos**, y se le mostraba a quien acababa de escribir
   en valencià.

Lo que **ya estaba bien y no se toca**: el `CoreGraph` calcula la señal con
`should_warn_translation(query_language, context_source_language)`, o sea desde la lengua de la
fuente. El dato correcto existía; lo que fallaba era el texto que se construía con él.
"""
from __future__ import annotations

import pytest

from server.app.modules.agents_hub.services.turno_de_chat import _build_translation_warning


# ACT.2 (2026-08-28): este fichero estaba escrito con `ca` en las DOS direcciones, y por eso no
# vio el defecto que arreglo ACT.2: la lengua de la fuente que llega de verdad es `val` —la del
# corpus—, no `ca`. Con `ca` en los dos lados los tests pasaban y produccion fallaba, que es la
# peor combinacion posible. Ahora usan el codigo real.
class TestElAvisoSaleDeLaLenguaDeLaFuente:

    def test_should_warn_when_the_source_language_differs_from_the_question(self):
        aviso = _build_translation_warning(lengua_de_la_fuente="es", lengua_de_la_pregunta="val")

        assert aviso is not None
        assert "castellà" in aviso.lower() or "castellano" in aviso.lower()

    def test_should_warn_when_asking_in_spanish_and_citing_a_valencian_norm(self):
        """**El caso que se callaba**, y es el más frecuente del corpus real."""
        aviso = _build_translation_warning(lengua_de_la_fuente="val", lengua_de_la_pregunta="es")

        assert aviso is not None, (
            "preguntar en castellano y recibir una norma en valencià es lo habitual en este "
            "corpus, y era exactamente el caso en el que el aviso no se emitía"
        )
        assert "valenci" in aviso.lower()

    def test_should_not_warn_when_both_match(self):
        assert _build_translation_warning(lengua_de_la_fuente="val", lengua_de_la_pregunta="val") is None
        assert _build_translation_warning(lengua_de_la_fuente="es", lengua_de_la_pregunta="es") is None

    def test_should_not_warn_without_enough_information(self):
        """Sin saber una de las dos lenguas no se puede afirmar que difieran, y un aviso falso
        sobre el idioma de una norma erosiona la confianza en los que sí son ciertos."""
        assert _build_translation_warning(lengua_de_la_fuente=None, lengua_de_la_pregunta="val") is None
        assert _build_translation_warning(lengua_de_la_fuente="val", lengua_de_la_pregunta=None) is None


class TestElAvisoSeEscribeEnLaLenguaDeQuienPregunta:

    def test_should_write_the_warning_in_the_language_of_the_question(self):
        en_valenciano = _build_translation_warning(
            lengua_de_la_fuente="es", lengua_de_la_pregunta="val"
        )
        en_castellano = _build_translation_warning(
            lengua_de_la_fuente="val", lengua_de_la_pregunta="es"
        )
        en_ingles = _build_translation_warning(
            lengua_de_la_fuente="val", lengua_de_la_pregunta="en"
        )

        # Cada uno en su lengua: mostrarle castellano a quien acaba de escribir en valencià es
        # el detalle que convierte un aviso útil en una impertinencia.
        assert "està" in en_valenciano or "està" in en_valenciano.lower()
        assert "está" in en_castellano
        assert "is in" in en_ingles.lower() or "written in" in en_ingles.lower()

    @pytest.mark.parametrize("pregunta", ["val", "es", "en"])
    def test_should_write_it_with_accents(self, pregunta: str):
        """El texto anterior estaba sin acentos («se detecto», «catalan», «ingles»), lo que en
        un aviso institucional se lee como descuido."""
        aviso = _build_translation_warning(
            lengua_de_la_fuente="fr", lengua_de_la_pregunta=pregunta
        )
        assert aviso is not None
        if pregunta != "en":
            assert any(letra in aviso for letra in "áéíóúàèìòùï"), (
                f"el aviso en «{pregunta}» no lleva un solo acento: {aviso!r}"
            )


class TestElEscenarioDePruebaLoEnsena:
    """Los dos ejecutores pasaban `translation_warning: False` fijo, así que el defecto era
    **invisible** desde la pantalla de escenarios y desde el lote — que son precisamente las dos
    herramientas con las que se mira si el asistente responde bien."""

    def test_should_record_the_warning_in_the_run(self):
        """Se guarda **el texto**, no el booleano.

        Matiz que se aclaró al implementarlo, porque el diagnóstico del plan lo daba por otra
        cosa: el `translation_warning: False` de los dos ejecutores es el **estado inicial** del
        grafo, y el grafo lo sobrescribe. Lo que de verdad faltaba es que el resultado guardara
        el aviso: sin eso, el texto que ve el ciudadano no aparece en ninguna herramienta de
        revisión, y un aviso que dice algo equivocado puede estar años sin que nadie lo note.
        """
        from server.app.modules.agents_hub.database.operational_models import HubTestRun

        assert "translation_warning" in HubTestRun.__table__.columns

    def test_should_expose_the_warning_in_the_contract(self):
        from server.app.routers.hub_test_scenarios_router import RunRead

        assert "translation_warning" in RunRead.model_fields, (
            "quien revisa una respuesta tiene que ver lo mismo que vio quien preguntó"
        )
