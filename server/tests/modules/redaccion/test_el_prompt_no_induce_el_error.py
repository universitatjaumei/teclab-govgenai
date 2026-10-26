"""INF.5 — el prompt deja de inducir el error que el validador castiga.

Los dos errores rojos que dejaron al usuario sin poder aprobar, el 2026-08-20:

    blocks[b6].data_block_refs: AI_SUMMARY block 'b6' valora 'b4', que no produce datos ('TABLE')
    blocks[b6].data_block_refs: AI_SUMMARY block 'b6' valora 'b5', que no produce datos ('CHART')

El validador tiene razón: una valoración debe apoyarse en el bloque que **produce** los datos,
no en el que los dibuja. Pero el prompt describía el campo como «the table or tables this
passage is about», y para el modelo la «tabla» del informe es el bloque `TABLE`. **El texto del
prompt es la causa**, no el modelo.
"""
from __future__ import annotations

import pytest


class TestElTextoDelPrompt:
    def test_should_name_the_data_kinds_for_data_block_refs(self):
        from server.app.modules.redaccion.services.llm_spec_service import _campos_obligatorios

        texto = _campos_obligatorios()
        fragmento = texto[texto.index("data_block_refs"):]
        fragmento = fragmento[: fragmento.index("CITATION_BLOCK")]

        assert "DETERMINISTIC_DATA" in fragmento, (
            "sin nombrar el kind, el modelo entiende «tabla» como el bloque TABLE"
        )
        assert "DATA_TRANSFORM" in fragmento

    def test_should_forbid_table_and_chart_for_data_block_refs(self):
        from server.app.modules.redaccion.services.llm_spec_service import _campos_obligatorios

        texto = _campos_obligatorios()
        fragmento = texto[texto.index("data_block_refs"):]
        fragmento = fragmento[: fragmento.index("CITATION_BLOCK")]

        assert "never" in fragmento.lower()
        assert "TABLE" in fragmento
        assert "CHART" in fragmento

    def test_should_show_a_correct_example(self):
        """Un ejemplo mínimo evita la ambigüedad mejor que una frase más."""
        from server.app.modules.redaccion.services.llm_spec_service import _campos_obligatorios

        texto = _campos_obligatorios()
        assert "Example" in texto or "example" in texto


class TestLaPropuestaDelCasoRealPasaElValidador:
    """El caso del usuario, con el anclaje correcto, valida sin errores.

    Es el test que faltaba: los dos errores rojos eran de `data_block_refs`, así que hace falta
    una propuesta completa —datos, transformación, tabla, gráfico, valoración y puerta de
    revisión— que demuestre que la forma correcta pasa.
    """

    @staticmethod
    def _propuesta_de_tesoreria() -> dict:
        return {
            "proposed_profile": "GENERIC_REPORT",
            "proposed_sections": [
                {"id": "s1", "title": "Evolucion de la tesoreria", "order": 1,
                 "block_ids": ["b_datos", "b_num", "b_tabla", "b_grafico", "b_val", "b_gate"]}
            ],
            "proposed_blocks": [
                {"kind": "DETERMINISTIC_DATA", "id": "b_datos", "title": "Saldos",
                 "order": 1, "source_pipeline": "excel"},
                # `to_number` antes de agrupar: los importes vienen como texto.
                {"kind": "DATA_TRANSFORM", "id": "b_num", "title": "Saldos por ano y mes",
                 "order": 2,
                 "config": {"source_block_ref": {"block_id": "b_datos"},
                            "mode": "deterministic",
                            "operations": [{"op": "to_number", "columns": ["saldo"]}]}},
                {"kind": "TABLE", "id": "b_tabla", "title": "Saldos agrupados",
                 "order": 3, "data_block_ref": "b_num"},
                {"kind": "CHART", "id": "b_grafico", "title": "Evolucion", "order": 4,
                 "data_block_ref": "b_num"},
                # Lo que el modelo hacía mal: esto apuntaba a "b_tabla" y a "b_grafico".
                {"kind": "AI_SUMMARY", "id": "b_val", "title": "Valoracion", "order": 5,
                 "ai_prompt_template_id": "generic_report_v1",
                 "review_policy_id": "required",
                 "data_block_refs": ["b_num"]},
                {"kind": "REVIEW_GATE", "id": "b_gate", "title": "Revision", "order": 6,
                 "review_policy_id": "required"},
            ],
            "proposed_inputs": {
                "required_slots": [
                    {"slot_id": "saldos", "kind": "csv",
                     "label": {"es": "Saldos", "ca": "Saldos", "en": "Balances"}}
                ],
                "optional_slots": [],
            },
            "rationale": "Agrupa los saldos por ano y mes y comenta la tendencia.",
            # Los pone el servicio al proponer; aqui hacen falta para validar el borrador suelto.
            "model_used": "modelo-de-prueba",
            "prompt_version": "llm_spec_v2",
        }

    @pytest.mark.asyncio
    async def test_should_validate_without_errors(self):
        from server.app.modules.redaccion.contracts.drafts import ReportTemplateDraft
        from server.app.modules.redaccion.services.draft_validator import DraftValidator

        borrador = ReportTemplateDraft.model_validate(self._propuesta_de_tesoreria())
        resultado = DraftValidator().validate(borrador)

        assert resultado.ok, [
            f"{e.field}: {e.message}" for e in resultado.errors
        ]

    @pytest.mark.asyncio
    async def test_should_reject_the_shape_the_model_produced_before(self):
        """Guardarraíl del caso real: anclar la valoración al TABLE sigue siendo un error.

        Si esto dejara de fallar, el validador habría aflojado en vez de arreglarse el prompt.
        """
        from server.app.modules.redaccion.contracts.drafts import ReportTemplateDraft
        from server.app.modules.redaccion.services.draft_validator import DraftValidator

        propuesta = self._propuesta_de_tesoreria()
        for bloque in propuesta["proposed_blocks"]:
            if bloque["id"] == "b_val":
                bloque["data_block_refs"] = ["b_tabla", "b_grafico"]

        resultado = DraftValidator().validate(
            ReportTemplateDraft.model_validate(propuesta)
        )

        assert not resultado.ok
        campos = " ".join(e.field for e in resultado.errors)
        assert "data_block_refs" in campos

    @pytest.mark.asyncio
    async def test_should_survive_the_whole_service_with_a_model_double(self):
        """De la respuesta del modelo a un borrador válido, sin tocar el validador.

        Un doble que devuelve la propuesta correcta: comprueba que el servicio no la estropea
        al parsearla —que es lo que pasaba con `required_slots` antes de SEG.3—.
        """
        import json

        from server.app.modules.redaccion.services.draft_validator import DraftValidator
        from server.app.modules.redaccion.services.llm_spec_service import LLMSpecService

        class _Respuesta:
            content = json.dumps(TestLaPropuestaDelCasoRealPasaElValidador._propuesta_de_tesoreria())

        class _ModeloFalso:
            async def ainvoke(self, _messages, **_kwargs):
                return _Respuesta()

        servicio = LLMSpecService(_ModeloFalso(), "modelo-de-prueba")
        borrador = await servicio.propose_template("Informe de tesoreria", "admin")

        resultado = DraftValidator().validate(borrador)
        assert resultado.ok, [f"{e.field}: {e.message}" for e in resultado.errors]
