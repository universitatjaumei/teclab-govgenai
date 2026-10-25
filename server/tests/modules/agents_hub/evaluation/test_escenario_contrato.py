"""HIB.G — el contrato del escenario de evaluación.

Lo que estos tests protegen no es un formato: es la posibilidad de medir sin una persona
delante. Un escenario contestable sin fuente esperada estructurada convierte cualquier
ablación en una nueva petición de trabajo a los informadores, y por eso las ablaciones no se
hacían.
"""
import pytest
from pydantic import ValidationError

from server.app.modules.agents_hub.evaluation.escenario_contrato import (
    Escenario,
    ExpectedSource,
    ExpectedSources,
    Kind,
    Lote,
    Provenance,
    RefusalReason,
)


def _fuente(anchor: str | None = "art-4") -> ExpectedSources:
    return ExpectedSources(
        required=[
            ExpectedSource(
                canonical_url="https://www.uji.es/norma/permanencia",
                anchor=anchor,
            )
        ]
    )


def _escenario(**cambios) -> dict:
    base = dict(
        name="ORI-01",
        prompt="Quants credits he de superar?",
        kind=Kind.ARTICULO_UNICO,
        language="ca",
        provenance=Provenance.REAL,
        expected_sources=_fuente(),
    )
    base.update(cambios)
    return base


class TestUnEscenarioContestableExigeFuente:

    def test_should_accept_a_scenario_with_a_required_source(self):
        e = Escenario(**_escenario())
        assert e.expected_sources.required[0].anchor == "art-4"

    def test_should_reject_a_scenario_without_expected_sources_when_answerable(self):
        with pytest.raises(ValidationError, match="fuente esperada"):
            Escenario(**_escenario(expected_sources=None))

    def test_should_reject_an_empty_required_set_when_answerable(self):
        with pytest.raises(ValidationError, match="fuente esperada"):
            Escenario(**_escenario(expected_sources=ExpectedSources()))

    def test_should_reject_a_refusal_reason_on_an_answerable_scenario(self):
        with pytest.raises(ValidationError, match="`refusal_reason` sólo tiene sentido"):
            Escenario(**_escenario(refusal_reason=RefusalReason.FUERA_DE_ALCANCE))


class TestUnNegativoExigeSuMotivo:

    def test_should_reject_an_unanswerable_scenario_without_refusal_reason(self):
        with pytest.raises(ValidationError, match="necesita `refusal_reason`"):
            Escenario(
                **_escenario(
                    answerable=False,
                    expected_sources=None,
                    kind=Kind.NEGATIVO,
                    provenance=Provenance.SINTETICO,
                )
            )

    def test_should_accept_an_unanswerable_scenario_with_its_reason(self):
        e = Escenario(
            **_escenario(
                answerable=False,
                expected_sources=None,
                kind=Kind.NEGATIVO,
                provenance=Provenance.SINTETICO,
                refusal_reason=RefusalReason.PREMISA_FALSA,
            )
        )
        assert e.refusal_reason is RefusalReason.PREMISA_FALSA

    def test_should_reject_an_unanswerable_scenario_that_demands_sources(self):
        with pytest.raises(ValidationError, match="no puede exigir fuentes"):
            Escenario(
                **_escenario(
                    answerable=False,
                    kind=Kind.NEGATIVO,
                    provenance=Provenance.SINTETICO,
                    refusal_reason=RefusalReason.FUERA_DE_ALCANCE,
                )
            )


class TestLosEjesDelAnalisisSonObligatorios:

    def test_should_require_language_kind_and_provenance(self):
        for falta in ("language", "kind", "provenance"):
            datos = _escenario()
            del datos[falta]
            with pytest.raises(ValidationError):
                Escenario(**datos)

    def test_should_normalise_ca_to_the_corpus_code(self):
        """ACT.2: `val` es el codigo del corpus. `ca` se sigue aceptando —los lotes de
        `_local/golden/` estan escritos asi y son el instrumento de medida— pero se normaliza,
        para que el recuento por lengua no parta en dos la misma lengua."""
        assert Escenario(**_escenario(name="ORI-99", language="ca")).language == "val"
        assert Escenario(**_escenario(name="ORI-98", language="val")).language == "val"

    def test_should_reject_a_language_outside_val_and_es(self):
        with pytest.raises(ValidationError, match="'val' o 'es'"):
            Escenario(**_escenario(language="en"))

    def test_should_require_history_on_a_follow_up_scenario(self):
        with pytest.raises(ValidationError, match="necesita `history`"):
            Escenario(**_escenario(kind=Kind.SEGUIMIENTO))

    def test_should_require_a_document_identifier_on_a_source(self):
        with pytest.raises(ValidationError, match="`document_id` o `canonical_url`"):
            ExpectedSource(anchor="art-4")


class TestElLoteSeSabeDescribir:

    def test_should_report_its_composition_by_every_axis(self):
        lote = Lote(
            name="prueba",
            scenarios=[
                Escenario(**_escenario(name="A", language="ca")),
                Escenario(**_escenario(name="B", language="es", kind=Kind.TABLA_O_DATO)),
                Escenario(
                    **_escenario(
                        name="C",
                        language="es",
                        answerable=False,
                        expected_sources=None,
                        kind=Kind.NEGATIVO,
                        provenance=Provenance.SINTETICO,
                        refusal_reason=RefusalReason.FUERA_DE_ALCANCE,
                    )
                ),
            ],
        )
        c = lote.composicion()
        assert c["total"] == 3
        # `ca` entra y se cuenta como `val`: es la misma lengua (ACT.2).
        assert c["language"] == {"val": 1, "es": 2}
        assert c["answerable"] == {"False": 1, "True": 2}
        assert c["con_fuente_requerida"] == 2
        assert c["con_ancla"] == 2

    def test_should_default_to_declaring_the_lot_is_for_tuning(self):
        """El lote afina; el piloto informa. Si nadie lo declara, se confunden."""
        lote = Lote(name="prueba", scenarios=[Escenario(**_escenario())])
        assert lote.uso == "afinado"


class TestLasVeinticincoRealesSobrevivenAlEnriquecimiento:
    """El lote de 25 con veredicto de informadores es el único material con juicio profesional
    que hay. Enriquecerlo tiene que ser aditivo: si el contrato obligara a reescribirlo, se
    perdería lo único que no se puede volver a fabricar."""

    def test_should_accept_the_existing_25_after_enrichment(self):
        legado = {
            "name": "ORI-01 — Permanencia en grado: creditos minimos a superar",
            "prompt": "Quants credits he de superar en un grau?",
            "history": None,
            "expectation_note": "VEREDICTO ANTERIOR (Unitat d'Orientacio): INCORRECTA...",
            "meta": {"failure_modes": ["ambito_equivocado"]},
        }
        esc = Escenario.model_validate(_escenario(**legado))
        assert esc.expectation_note.startswith("VEREDICTO ANTERIOR")
        assert esc.meta == {"failure_modes": ["ambito_equivocado"]}

    def test_should_keep_the_informer_prose_when_there_is_also_a_reference_answer(self):
        """La prosa del informador y la respuesta de referencia coexisten: la segunda resuelve
        desacuerdos, y sustituir la primera por ella borraría el veredicto original."""
        esc = Escenario.model_validate(
            _escenario(
                expectation_note="QUE DEBE CONTESTAR: el 20 % de los creditos matriculados.",
                reference_answer="20 % de los creditos matriculados.",
            )
        )
        assert esc.expectation_note
        assert esc.reference_answer

    def test_should_identify_an_unpublished_document_without_faking_a_url(self):
        """Las circulares e instrucciones propias de Gerencia no están publicadas y su
        `canonical_url` es una ruta local. La fuente esperada se identifica por `document_id`
        y deja la URL fuera; inventarle un `https://` la haría casar con nada."""
        fuente = ExpectedSource(
            document_id="43272ee8-0000-0000-0000-000000000000", anchor="div-3"
        )
        assert fuente.canonical_url is None

        with pytest.raises(ValidationError):
            ExpectedSource(
                document_id="43272ee8-0000-0000-0000-000000000000",
                canonical_url="C:/corpus/instruccio_contractes_menors.md",
            )

    def test_should_let_the_same_question_be_a_negative_in_one_lot_and_answerable_in_another(
        self,
    ):
        """Seis preguntas reales llegaron al asistente de Normativa siendo de Gerencia. Allí no
        son contestables —sus leyes están con `us_assistents='no'`— y aquí sí. El contrato no
        puede atar la contestabilidad a la pregunta, porque depende del corpus del asistente."""
        pregunta = "Quins son els requisits per a la contractacio menor?"
        negativo = Escenario.model_validate({
            "name": "XDO-04",
            "prompt": pregunta,
            "kind": Kind.NEGATIVO,
            "language": "ca",
            "provenance": Provenance.REAL,
            "answerable": False,
            "refusal_reason": RefusalReason.FUERA_DE_ALCANCE,
        })
        positivo = Escenario.model_validate(
            _escenario(name="GXD-04", prompt=pregunta, kind=Kind.VARIOS_ARTICULOS)
        )
        assert negativo.prompt == positivo.prompt
        assert negativo.answerable is False
        assert positivo.answerable is True


class TestUnaPremisaFalsaSeRefutaContestando:
    """Medido el 2026-08-27: modelar «puedo partir una factura de 60.000 en cuatro de 15.000»
    como negativo hizo que la respuesta ideal —«no, el art. 99.2 lo prohíbe expresamente»—
    contara como fallo. Refutar es contestar, y el contrato tiene que poder decirlo."""

    def test_should_accept_an_answerable_scenario_that_must_deny_the_premise(self):
        esc = Escenario.model_validate(_escenario(debe_refutar=True))
        assert esc.answerable is True
        assert esc.debe_refutar is True

    def test_should_default_to_not_demanding_a_refutation(self):
        assert Escenario.model_validate(_escenario()).debe_refutar is False

    def test_should_reject_a_refutation_on_an_unanswerable_scenario(self):
        """Si la refutación no se puede fundamentar en el corpus, el escenario es un negativo
        con `premisa_falsa`; pedirle que refute sería exigir una cita imposible."""
        with pytest.raises(ValidationError):
            Escenario.model_validate({
                "name": "NEG-03",
                "prompt": "Quin examen propi d'acces fa la UJI?",
                "kind": Kind.NEGATIVO,
                "language": "ca",
                "provenance": Provenance.SINTETICO,
                "answerable": False,
                "refusal_reason": RefusalReason.PREMISA_FALSA,
                "debe_refutar": True,
            })
