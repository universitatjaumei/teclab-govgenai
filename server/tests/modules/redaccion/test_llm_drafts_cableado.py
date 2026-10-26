"""VER.2 — proponer una plantilla con el modelo, en vez de devolver 503.

`LLMSpecService` estaba escrito y probado desde 9R; lo que devolvía 503 era la dependencia
que lo construye (`get_llm_spec_service`, un stub con «connect to model_factory»). Es la
puerta de entrada natural al módulo: describir el informe que quieres y que la plantilla se
proponga sola, en vez de montarla campo a campo en el constructor.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from server.app.core.auth.models import UserInfo
from server.app.modules.redaccion.services.llm_spec_service import LLMSpecService

#: MT.3 — el `Depends` resuelve el modelo para la organización de quien pide. Un
#: superadministrador no pertenece a ninguna, así que resuelve el nivel de plataforma, que es
#: lo que este fichero comprueba.
_SIN_ORGANIZACION = UserInfo(
    user_id="1", email="root@uji.es", role="superadmin", organizacion_ids=()
)


class TestLaDependencia:

    @pytest.mark.asyncio
    async def test_should_build_the_service_from_the_model_cascade(self):
        """Deja de ser un stub: resuelve el modelo por `model_factory`, como todo lo demás."""
        import server.app.routers.redaccion.llm_drafts_router as router_modulo

        modelo = MagicMock()
        modelo.model_name = "gemini-2.5-flash"

        async def _modelo_falso(_tier, _provider, *, organizacion_id=None):
            return modelo

        original = router_modulo.get_model_for_tier
        router_modulo.get_model_for_tier = _modelo_falso
        try:
            servicio = await router_modulo.get_llm_spec_service(
                session=MagicMock(), current_user=_SIN_ORGANIZACION
            )
        finally:
            router_modulo.get_model_for_tier = original

        assert isinstance(servicio, LLMSpecService)

    @pytest.mark.asyncio
    async def test_should_still_say_503_and_why_when_there_is_no_model(self):
        """Sin modelo configurado el 503 tiene que seguir, y decir qué falta: es la
        diferencia entre «esto no está montado» y «esto está roto»."""
        from fastapi import HTTPException

        import server.app.routers.redaccion.llm_drafts_router as router_modulo

        async def _revienta(_tier, _provider, *, organizacion_id=None):
            raise ValueError("No hay configuracion LLM por defecto para tier 1")

        original = router_modulo.get_model_for_tier
        router_modulo.get_model_for_tier = _revienta
        try:
            with pytest.raises(HTTPException) as fallo:
                await router_modulo.get_llm_spec_service(
                session=MagicMock(), current_user=_SIN_ORGANIZACION
            )
        finally:
            router_modulo.get_model_for_tier = original

        assert fallo.value.status_code == 503
        assert "tier 1" in str(fallo.value.detail)


class TestElCaminoDeLaPropuesta:

    @pytest.mark.asyncio
    async def test_should_propose_a_template_from_a_description(self):
        """El servicio pide JSON al modelo y lo valida contra el contrato de plantilla."""
        modelo = MagicMock()
        modelo.ainvoke = AsyncMock(return_value=MagicMock(content="""```json
{
  "proposed_profile": "GENERIC_REPORT",
  "proposed_sections": [{"id": "s1", "title": "Introduccion", "order": 1, "block_ids": []}],
  "proposed_blocks": [
    {"id": "b1", "kind": "STATIC_TEXT", "title": "Encabezado", "order": 1,
     "text": "Informe de ejecucion presupuestaria"}
  ],
  "proposed_inputs": {"required_slots": [], "optional_slots": []},
  "rationale": "Un informe sencillo"
}
```"""))

        borrador = await LLMSpecService(modelo, "gemini-2.5-flash").propose_template(
            prompt_nl="Un informe de ejecución presupuestaria trimestral",
            owner_kind="admin",
        )

        assert borrador.proposed_profile == "GENERIC_REPORT"
        assert [s.title for s in borrador.proposed_sections] == ["Introduccion"]
        assert borrador.model_used == "gemini-2.5-flash"


class TestLoQueSeLePideAlModelo:
    """Visto al recorrerlo en navegador (VER.3): la primera petición real —«informe
    trimestral de ejecución del presupuesto con una tabla»— dio **500**. El modelo propuso un
    bloque `TABLE` sin `data_block_ref`, que es obligatorio, porque el prompt del sistema
    enumera los tipos de bloque pero **no dice qué campos exige cada uno**."""

    def test_should_tell_the_model_the_required_fields_of_each_block_kind(self):
        from server.app.modules.redaccion.services.llm_spec_service import (
            _build_system_prompt,
        )

        prompt = _build_system_prompt("admin")

        for campo in ("data_block_ref", "source_pipeline", "ai_prompt_template_id",
                      "review_policy_id"):
            assert campo in prompt, f"el prompt no dice que {campo} es obligatorio"

    def test_should_tell_the_model_that_ai_blocks_need_a_review_gate(self):
        """`DraftValidator` devuelve `ok=False` si hay bloques de IA sin `REVIEW_GATE`, y el
        botón de aprobar exige `ok=true`: sin esto en el prompt, **ninguna** propuesta con IA
        es aprobable nunca. Visto en la primera propuesta real de VER.3."""
        from server.app.modules.redaccion.services.llm_spec_service import (
            _build_system_prompt,
        )

        prompt = _build_system_prompt("admin")

        assert "REVIEW_GATE" in prompt
        assert "AI_SUMMARY" in prompt or "AI block" in prompt

    def test_should_tell_the_model_the_shape_of_an_input_slot(self):
        """Segunda vuelta del mismo fallo: el prompt enumeraba `required_slots` sin decir
        cómo es un slot, y el modelo devolvía `{'id': ..., 'block_ref': ...}`. Cada propuesta
        con datos de entrada terminaba en 422."""
        from server.app.modules.redaccion.services.llm_spec_service import (
            _build_system_prompt,
        )

        prompt = _build_system_prompt("admin")

        assert "slot_id" in prompt
        assert "excel" in prompt, "faltan los tipos de slot"
        assert "selector" in prompt, "faltan los tipos de slot"

    def test_should_report_the_model_that_wrote_the_proposal(self):
        """Salía «Modelo: desconocido» en pantalla: `ChatGoogleGenerativeAI` no expone
        `model_name` sino `model`, y el `getattr` caía al valor por defecto."""
        from server.app.routers.redaccion._actor import nombre_del_modelo

        assert nombre_del_modelo(MagicMock(spec=[], model="gemini-2.5-flash")) == "gemini-2.5-flash"
        assert nombre_del_modelo(MagicMock(spec=[], model_name="claude-x")) == "claude-x"
        assert nombre_del_modelo(MagicMock(spec=[])) == "desconocido"

    def test_should_give_the_model_the_real_schema_instead_of_a_description(self):
        """Describir el contrato a mano fue un juego del topo: primero faltaba
        `data_block_ref`, luego el `REVIEW_GATE`, luego la forma de `InputSlot`, luego el
        título de sección llegó como diccionario i18n. El contrato lo conoce pydantic; el
        prompt lleva su JSON Schema y deja de adivinarse."""
        from server.app.modules.redaccion.services.llm_spec_service import (
            _build_system_prompt,
        )

        prompt = _build_system_prompt("admin")

        assert '"properties"' in prompt, "el prompt no lleva el esquema real"
        assert "data_block_ref" in prompt
        assert "slot_id" in prompt

    @pytest.mark.asyncio
    async def test_should_retry_once_with_the_validation_error_as_feedback(self):
        """Mismo patrón que `etl_factory`: si la propuesta no valida, se le devuelve el
        error al modelo antes de rendirse. Un reintento convierte la mayoría de estos
        fallos en una propuesta buena sin que el usuario tenga que reformular."""
        mala = ('{"proposed_profile": "GENERIC_REPORT",'
                ' "proposed_sections": [{"id": "s1", "title": {"es": "Intro"}, "order": 1}],'
                ' "proposed_blocks": [], "proposed_inputs": {"required_slots": [],'
                ' "optional_slots": []}, "rationale": ""}')
        buena = ('{"proposed_profile": "GENERIC_REPORT",'
                 ' "proposed_sections": [{"id": "s1", "title": "Intro", "order": 1}],'
                 ' "proposed_blocks": [], "proposed_inputs": {"required_slots": [],'
                 ' "optional_slots": []}, "rationale": ""}')

        modelo = MagicMock()
        modelo.ainvoke = AsyncMock(side_effect=[
            MagicMock(content=mala), MagicMock(content=buena),
        ])

        borrador = await LLMSpecService(modelo, "m").propose_template(
            prompt_nl="Un informe", owner_kind="admin",
        )

        assert borrador.proposed_sections[0].title == "Intro"
        assert modelo.ainvoke.await_count == 2
        segundo_intento = str(modelo.ainvoke.await_args_list[1])
        assert "title" in segundo_intento, "el reintento no le dice al modelo qué falló"

    @pytest.mark.asyncio
    async def test_should_reject_an_invalid_proposal_without_a_500(self):
        """Una propuesta que no valida es un fallo del modelo, no del servidor: tiene que
        salir como error de dominio y no como traza de pydantic en el log."""
        from server.app.modules.redaccion.services.llm_spec_service import (
            PropuestaInvalidaError,
        )

        invalida = (
            '{"proposed_profile": "GENERIC_REPORT", "proposed_sections": [],'
            ' "proposed_blocks": [{"kind": "TABLE", "id": "b1", "title": "Tabla",'
            ' "order": 1}],'
            ' "proposed_inputs": {"required_slots": [], "optional_slots": []},'
            ' "rationale": ""}'
        )
        modelo = MagicMock()
        # Insiste en el mismo error: agotado el reintento, se rinde con el error de dominio.
        modelo.ainvoke = AsyncMock(return_value=MagicMock(content=invalida))

        with pytest.raises(PropuestaInvalidaError) as fallo:
            await LLMSpecService(modelo, "m").propose_template(
                prompt_nl="Un informe con una tabla", owner_kind="admin",
            )

        assert "data_block_ref" in str(fallo.value)

    @pytest.mark.asyncio
    async def test_should_answer_422_and_not_500_when_the_proposal_is_invalid(self):
        from fastapi import HTTPException

        import server.app.routers.redaccion.llm_drafts_router as router_modulo
        from server.app.modules.redaccion.services.llm_spec_service import (
            PropuestaInvalidaError,
        )

        servicio = MagicMock()
        servicio.propose_template = AsyncMock(
            side_effect=PropuestaInvalidaError("TABLE.data_block_ref: Field required")
        )

        with pytest.raises(HTTPException) as fallo:
            await router_modulo.propose(
                body=router_modulo.ProposeRequest(prompt_nl="x", mode="admin_template"),
                user=MagicMock(role="superadmin"),
                service=servicio,
            )

        assert fallo.value.status_code == 422
        assert "data_block_ref" in str(fallo.value.detail)
