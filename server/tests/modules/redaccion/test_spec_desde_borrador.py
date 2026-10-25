"""VER.3 — la plantilla aprobada tiene que ser una plantilla, no el borrador.

`approve-as-template` guardaba en `spec_json` el **borrador** tal cual: `proposed_sections`,
`proposed_blocks`, `proposed_inputs`, `rationale`. Una `ReportTemplateSpec` es otra cosa
—`sections`, `blocks`, `input_contract`, `ui_contract` y las tres políticas—, así que toda
plantilla aprobada desde una propuesta de IA quedaba inservible: `GET
/template-versions/{id}/ui-contract` devolvía **500** y la generación (VER.1) tampoco podía
leerla.

Visto en vivo al recorrer VER.3, justo después de aprobar la primera propuesta buena.

La conversión no es mecánica en un punto: **el contrato de UI hay que derivarlo**, porque el
borrador no lo trae. Un slot de fichero es una zona de arrastre y uno de dato es un campo, y
eso es lo que hace que el formulario del asistente se construya solo.
"""
from __future__ import annotations

import pytest

from server.app.modules.redaccion.contracts.blocks import (
    AIAssistedTextBlock,
    DeterministicDataBlock,
    ReviewGateBlock,
    StaticTextBlock,
)
from server.app.modules.redaccion.contracts.drafts import ReportTemplateDraft
from server.app.modules.redaccion.contracts.inputs import InputContract, InputSlot
from server.app.modules.redaccion.contracts.template import (
    AIBlockPolicy,
    ReportTemplateSpec,
    ReviewPolicy,
    SectionContract,
)
from server.app.modules.redaccion.services.spec_builder import spec_desde_borrador


def _borrador(**cambios) -> ReportTemplateDraft:
    base = dict(
        proposed_profile="GENERIC_REPORT",
        proposed_sections=[
            SectionContract(id="s1", title="Contexto", order=1, block_ids=["b_texto"]),
            SectionContract(id="s2", title="Datos", order=2, block_ids=["b_datos"]),
        ],
        proposed_blocks=[
            StaticTextBlock(id="b_texto", title="Encabezado", order=1, content="Informe"),
            DeterministicDataBlock(
                id="b_datos", title="Importes", order=2, source_pipeline="excel"
            ),
            AIAssistedTextBlock(
                id="b_resumen", title="Resumen", order=3,
                ai_prompt_template_id="generic_report_v1", review_policy_id="required",
            ),
            ReviewGateBlock(id="b_gate", title="Revisión", order=4,
                            review_policy_id="required"),
        ],
        proposed_inputs=InputContract(
            required_slots=[
                InputSlot(slot_id="datos_excel", kind="excel",
                          label={"es": "Datos", "ca": "Dades", "en": "Data"}),
                InputSlot(slot_id="periodo", kind="text",
                          label={"es": "Periodo", "ca": "Període", "en": "Period"}),
            ],
        ),
        rationale="Porque sí",
        model_used="m",
        prompt_version="v",
    )
    base.update(cambios)
    return ReportTemplateDraft(**base)


class TestLaConversion:

    def test_should_produce_something_the_contract_accepts(self):
        """Es la comprobación que faltaba: lo guardado tiene que volver a leerse."""
        spec = spec_desde_borrador(_borrador())

        assert isinstance(spec, ReportTemplateSpec)
        ReportTemplateSpec.model_validate(spec.model_dump(mode="json"))

    def test_should_keep_the_sections_and_blocks_that_were_proposed(self):
        spec = spec_desde_borrador(_borrador())

        assert [s.id for s in spec.sections] == ["s1", "s2"]
        assert [b.id for b in spec.blocks] == ["b_texto", "b_datos", "b_resumen", "b_gate"]

    def test_should_turn_file_slots_into_dropzones_and_data_slots_into_fields(self):
        """El contrato de UI no viene en el borrador: se deriva de los slots, y es lo que
        hace que el formulario del asistente se construya solo."""
        contrato = spec_desde_borrador(_borrador()).ui_contract

        assert [d.slot_id for d in contrato.dropzones] == ["datos_excel"]
        assert [c.slot_id for c in contrato.manual_fields] == ["periodo"]

    def test_should_carry_the_sections_as_wizard_steps(self):
        contrato = spec_desde_borrador(_borrador()).ui_contract

        assert [p.id for p in contrato.wizard_steps] == ["s1", "s2"]

    def test_should_enable_the_review_panel_when_there_are_ai_blocks(self):
        con_ia = spec_desde_borrador(_borrador())
        sin_ia = spec_desde_borrador(_borrador(proposed_blocks=[
            StaticTextBlock(id="b_texto", title="Encabezado", order=1, content="Informe"),
        ]))

        assert con_ia.ui_contract.ai_review_panel_enabled is True
        assert con_ia.ai_block_policy == AIBlockPolicy.ALLOWED
        assert sin_ia.ui_contract.ai_review_panel_enabled is False
        assert sin_ia.ai_block_policy == AIBlockPolicy.DISABLED

    def test_should_require_review_when_the_template_has_a_review_gate(self):
        con_puerta = spec_desde_borrador(_borrador())
        sin_puerta = spec_desde_borrador(_borrador(proposed_blocks=[
            StaticTextBlock(id="b_texto", title="Encabezado", order=1, content="Informe"),
        ]))

        assert con_puerta.review_policy == ReviewPolicy.REQUIRED
        assert sin_puerta.review_policy == ReviewPolicy.NONE

    @pytest.mark.parametrize(("tipo", "es_fichero"), [
        ("pdf", True), ("excel", True), ("csv", True),
        ("text", False), ("number", False), ("date", False), ("selector", False),
    ])
    def test_should_classify_every_slot_kind(self, tipo, es_fichero):
        """Los siete tipos del contrato, para que ninguno se quede sin superficie."""
        spec = spec_desde_borrador(_borrador(proposed_inputs=InputContract(
            required_slots=[InputSlot(slot_id="s", kind=tipo, label={"es": "x"})],
        )))

        assert bool(spec.ui_contract.dropzones) is es_fichero
        assert bool(spec.ui_contract.manual_fields) is not es_fichero
