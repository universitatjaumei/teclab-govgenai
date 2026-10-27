"""SEG.1 — cada apartado de IA lee su tabla, no el informe entero.

`_build_context` construía **un solo contexto con todos los bloques extraídos** y se lo entregaba
igual a cada apartado de IA; y `AIAssistedTextBlock` sólo tenía `ai_prompt_template_id` y
`review_policy_id`, así que **no había forma de decir «valora la Tabla 1.2»**.

En el caso que motiva el bloque —el informe anual de seguimiento de un programa de doctorado, con
unas treinta tablas— eso significa que la valoración de cada tabla recibiría las treinta y el
encargo de «redacta esta sección». Es exactamente el fallo que el usuario ya vivió con una gema de
Gemini: mezcla, resume y se deja fuera lo relevante. No se arregla con instrucciones; se arregla
no dándole al modelo lo que no necesita.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from server.app.modules.redaccion.contracts.blocks import (
    AIAssistedTextBlock,
    DeterministicDataBlock,
)
from server.app.modules.redaccion.contracts.inputs import InputContract
from server.app.modules.redaccion.contracts.runtime import BlockState, WorkspaceState
from server.app.modules.redaccion.contracts.template import (
    AIBlockPolicy,
    ExportPolicy,
    ReportTemplateSpec,
    ReviewPolicy,
)
from server.app.modules.redaccion.contracts.ui import ReportUIContract
from server.app.modules.redaccion.graph.nodes.ai_assist_draft import AIAssistDraftNode
from server.tests.dobles import modelo_de_chat


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _tabla(block_id: str, texto: str) -> BlockState:
    """Un bloque de datos ya extraído, con su contenido reconocible en el contexto."""
    return BlockState(
        block_id=block_id,
        kind="DETERMINISTIC_DATA",
        status="extracted",
        content={"free_text": texto},
        last_updated_by="system",
        updated_at=_ahora(),
    )


def _apartado(block_id: str) -> BlockState:
    return BlockState(
        block_id=block_id,
        kind="AI_ASSISTED_TEXT",
        status="draft",
        content=None,
        last_updated_by="system",
        updated_at=_ahora(),
    )


def _spec(*bloques) -> ReportTemplateSpec:
    return ReportTemplateSpec(
        sections=[],
        blocks=list(bloques),
        input_contract=InputContract(),
        ui_contract=ReportUIContract(
            wizard_steps=[], dropzones=[], manual_fields=[],
            block_editor_enabled=False, ai_review_panel_enabled=False,
            preview_layout="markdown",
        ),
        ai_block_policy=AIBlockPolicy.ALLOWED,
        review_policy=ReviewPolicy.NONE,
        export_policy=ExportPolicy.DOCX,
    )


def _estado(spec: ReportTemplateSpec, bloques: dict) -> WorkspaceState:
    return WorkspaceState(
        workspace_id=uuid.uuid4(),
        template_version_id=uuid.uuid4(),
        report_profile="GENERIC_REPORT",
        inputs={},
        blocks=bloques,
        status="drafting",
        warnings=[],
        spec=spec,
        artifacts_normalized={},
    )


def _llm_espia() -> MagicMock:
    """Un modelo que guarda el contexto de **cada** llamada, para poder compararlos."""
    llm = modelo_de_chat()
    llm.model_name = "modelo-de-prueba"
    llm.generate = AsyncMock(return_value="Valoración redactada.")
    return llm


# ----------------------------------------------------------------------
# El anclaje
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_un_apartado_anclado_no_ve_las_tablas_de_los_demas() -> None:
    """Es el test que da sentido al bloque: con dos tablas, cada valoración ve la suya."""
    spec = _spec(
        DeterministicDataBlock(id="t_matricula", title="T1.2", source_pipeline="excel"),
        DeterministicDataBlock(id="t_tesis", title="T6.2", source_pipeline="excel"),
        AIAssistedTextBlock(
            id="v_matricula", title="Valoración de la matrícula",
            ai_prompt_template_id="generic_report_v1", review_policy_id="required",
            data_block_refs=["t_matricula"],
        ),
        AIAssistedTextBlock(
            id="v_tesis", title="Valoración de las tesis",
            ai_prompt_template_id="generic_report_v1", review_policy_id="required",
            data_block_refs=["t_tesis"],
        ),
    )
    estado = _estado(spec, {
        "t_matricula": _tabla("t_matricula", "MATRICULADOS TOTALES 138"),
        "t_tesis": _tabla("t_tesis", "TESIS LEIDAS 17"),
        "v_matricula": _apartado("v_matricula"),
        "v_tesis": _apartado("v_tesis"),
    })

    llm = _llm_espia()
    await AIAssistDraftNode(llm)(estado)

    contextos = [llamada.kwargs["context"] for llamada in llm.generate.await_args_list]

    assert len(contextos) == 2, "deberían ser dos llamadas, una por apartado"
    de_matricula = next(c for c in contextos if "MATRICULADOS" in c)
    de_tesis = next(c for c in contextos if "TESIS" in c)

    assert "TESIS" not in de_matricula, "la valoración de la matrícula ve la tabla de tesis"
    assert "MATRICULADOS" not in de_tesis, "la valoración de las tesis ve la de matrícula"


@pytest.mark.asyncio
async def test_varias_tablas_en_un_apartado_van_en_el_orden_declarado() -> None:
    """Un apartado puede valorar dos tablas juntas, y el orden lo decide la plantilla."""
    spec = _spec(
        DeterministicDataBlock(id="t_a", title="A", source_pipeline="excel"),
        DeterministicDataBlock(id="t_b", title="B", source_pipeline="excel"),
        AIAssistedTextBlock(
            id="v", title="Valoración conjunta",
            ai_prompt_template_id="generic_report_v1", review_policy_id="required",
            data_block_refs=["t_b", "t_a"],
        ),
    )
    estado = _estado(spec, {
        "t_a": _tabla("t_a", "PRIMERA"),
        "t_b": _tabla("t_b", "SEGUNDA"),
        "v": _apartado("v"),
    })

    llm = _llm_espia()
    await AIAssistDraftNode(llm)(estado)

    contexto = llm.generate.await_args_list[0].kwargs["context"]
    assert contexto.index("SEGUNDA") < contexto.index("PRIMERA"), (
        "el orden del contexto no respeta el declarado en data_block_refs"
    )


@pytest.mark.asyncio
async def test_una_referencia_a_un_bloque_sin_datos_no_se_inventa_contexto() -> None:
    """Si la referencia apunta a algo que no ha producido datos, el apartado lo dice.

    Callarlo produciría una valoración sin fundamento y con apariencia de tenerlo.
    """
    spec = _spec(
        DeterministicDataBlock(id="t_vacia", title="Sin datos", source_pipeline="excel"),
        AIAssistedTextBlock(
            id="v", title="Valoración",
            ai_prompt_template_id="generic_report_v1", review_policy_id="required",
            data_block_refs=["t_vacia"],
        ),
    )
    sin_extraer = BlockState(
        block_id="t_vacia", kind="DETERMINISTIC_DATA", status="draft",
        content=None, last_updated_by="system", updated_at=_ahora(),
    )
    estado = _estado(spec, {"t_vacia": sin_extraer, "v": _apartado("v")})

    resultado = await AIAssistDraftNode(_llm_espia())(estado)

    bloque = resultado["blocks"]["v"]
    assert bloque.status == "failed"
    assert any(a.block_id == "v" for a in resultado["warnings"])


@pytest.mark.asyncio
async def test_sin_anclaje_se_conserva_el_comportamiento_anterior() -> None:
    """Las plantillas que ya existen no declaran anclaje y no se pueden romper."""
    spec = _spec(
        DeterministicDataBlock(id="t_a", title="A", source_pipeline="excel"),
        DeterministicDataBlock(id="t_b", title="B", source_pipeline="excel"),
        AIAssistedTextBlock(
            id="v", title="Resumen de todo",
            ai_prompt_template_id="generic_report_v1", review_policy_id="required",
        ),
    )
    estado = _estado(spec, {
        "t_a": _tabla("t_a", "PRIMERA"),
        "t_b": _tabla("t_b", "SEGUNDA"),
        "v": _apartado("v"),
    })

    llm = _llm_espia()
    await AIAssistDraftNode(llm)(estado)

    contexto = llm.generate.await_args_list[0].kwargs["context"]
    assert "PRIMERA" in contexto
    assert "SEGUNDA" in contexto


# ----------------------------------------------------------------------
# Que conste en el manifiesto
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_el_alcance_del_contexto_queda_en_el_bloque() -> None:
    """Una valoración cuya fuente no consta es una valoración que nadie puede auditar.

    El alcance viaja en el contenido del bloque porque «el estado es el registro» (P6), y de ahí
    lo recoge el manifiesto.
    """
    spec = _spec(
        DeterministicDataBlock(id="t_a", title="A", source_pipeline="excel"),
        AIAssistedTextBlock(
            id="v_anclado", title="Anclado",
            ai_prompt_template_id="generic_report_v1", review_policy_id="required",
            data_block_refs=["t_a"],
        ),
        AIAssistedTextBlock(
            id="v_suelto", title="Sin anclar",
            ai_prompt_template_id="generic_report_v1", review_policy_id="required",
        ),
    )
    estado = _estado(spec, {
        "t_a": _tabla("t_a", "PRIMERA"),
        "v_anclado": _apartado("v_anclado"),
        "v_suelto": _apartado("v_suelto"),
    })

    resultado = await AIAssistDraftNode(_llm_espia())(estado)

    anclado = resultado["blocks"]["v_anclado"].content
    suelto = resultado["blocks"]["v_suelto"].content

    assert anclado["context_scope"] == "anchored"
    assert anclado["context_block_ids"] == ["t_a"]
    assert suelto["context_scope"] == "full"
    assert suelto["context_block_ids"] == []


# ----------------------------------------------------------------------
# El manifiesto y el validador
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_el_manifiesto_dice_de_que_se_apoyo_cada_apartado() -> None:
    """`ai_blocks` estaba declarado en el contrato del manifiesto y el nodo lo dejaba vacío.

    Sin esto, el alcance del contexto vive sólo en el bloque y no llega a la evidencia de la
    ejecución, que es donde lo busca quien audita el informe.
    """
    from server.app.modules.redaccion.graph.nodes.audit_log import AuditLogNode

    guardados: list = []

    class _Repo:
        async def save(self, orm):
            guardados.append(orm)

    class _Span:
        def set_attribute(self, *_a, **_kw): ...
        def end(self): ...

    class _Tracing:
        def open_trace(self, *_a, **_kw):
            return _Span()

    anclado = BlockState(
        block_id="v_anclado", kind="AI_ASSISTED_TEXT", status="ai_generated",
        content={
            "text": "…", "model_used": "m", "prompt_version": "p",
            "context_scope": "anchored", "context_block_ids": ["t_a"],
        },
        last_updated_by="ai", updated_at=_ahora(),
    )
    suelto = BlockState(
        block_id="v_suelto", kind="AI_SUMMARY", status="ai_generated",
        content={
            "text": "…", "model_used": "m", "prompt_version": "p",
            "context_scope": "full", "context_block_ids": [],
        },
        last_updated_by="ai", updated_at=_ahora(),
    )
    estado = _estado(_spec(), {"v_anclado": anclado, "v_suelto": suelto})

    await AuditLogNode(_Repo(), _Tracing())(estado)

    assert guardados, "no se ha persistido ningún manifiesto"
    ai_blocks = guardados[0].payload_json["ai_blocks"]
    por_id = {b["block_id"]: b for b in ai_blocks}

    assert por_id["v_anclado"]["context_scope"] == "anchored"
    assert por_id["v_anclado"]["context_block_ids"] == ["t_a"]
    assert por_id["v_suelto"]["context_scope"] == "full"
    assert por_id["v_anclado"]["model_used"] == "m"


def test_una_referencia_a_un_bloque_inexistente_no_pasa_la_validacion() -> None:
    """Mismo criterio que GUI.3 aplicó a TABLE y CHART: la referencia se comprueba al validar."""
    from server.app.modules.redaccion.contracts.drafts import ReportTemplateDraft
    from server.app.modules.redaccion.services.draft_validator import DraftValidator

    borrador = ReportTemplateDraft.model_validate({
        "proposed_profile": "GENERIC_REPORT",
        "proposed_sections": [{"id": "s1", "title": "S", "order": 1}],
        "proposed_blocks": [
            {"id": "t_a", "title": "A", "order": 1, "kind": "DETERMINISTIC_DATA",
             "source_pipeline": "excel"},
            {"id": "v", "title": "V", "order": 2, "kind": "AI_ASSISTED_TEXT",
             "ai_prompt_template_id": "generic_report_v1", "review_policy_id": "required",
             "data_block_refs": ["no_existe"]},
            {"id": "g", "title": "G", "order": 3, "kind": "REVIEW_GATE",
             "review_policy_id": "required"},
        ],
        "proposed_inputs": {"required_slots": []},
        "rationale": "", "model_used": "m", "prompt_version": "p",
    })

    resultado = DraftValidator().validate(borrador)

    assert not resultado.ok
    assert any("no_existe" in e.message for e in resultado.errors)


def test_una_referencia_a_un_bloque_de_texto_tampoco_vale() -> None:
    """Un texto estático no tiene datos que valorar."""
    from server.app.modules.redaccion.contracts.drafts import ReportTemplateDraft
    from server.app.modules.redaccion.services.draft_validator import DraftValidator

    borrador = ReportTemplateDraft.model_validate({
        "proposed_profile": "GENERIC_REPORT",
        "proposed_sections": [{"id": "s1", "title": "S", "order": 1}],
        "proposed_blocks": [
            {"id": "intro", "title": "Intro", "order": 1, "kind": "STATIC_TEXT",
             "content": "Hola"},
            {"id": "v", "title": "V", "order": 2, "kind": "AI_ASSISTED_TEXT",
             "ai_prompt_template_id": "generic_report_v1", "review_policy_id": "required",
             "data_block_refs": ["intro"]},
            {"id": "g", "title": "G", "order": 3, "kind": "REVIEW_GATE",
             "review_policy_id": "required"},
        ],
        "proposed_inputs": {"required_slots": []},
        "rationale": "", "model_used": "m", "prompt_version": "p",
    })

    assert not DraftValidator().validate(borrador).ok


def test_el_borrador_sabe_que_puede_anclar_la_valoracion() -> None:
    """SEG.1 hizo posible el anclaje; si el prompt no lo menciona, el modelo nunca lo usa.

    Es el mismo patrón que GUI.3 destapó con los tipos de gráfico: la capacidad existía en el
    contrato y la puerta de entrada no la ofrecía.
    """
    from server.app.modules.redaccion.services.llm_spec_service import _campos_obligatorios

    texto = _campos_obligatorios()
    assert "data_block_refs" in texto
    # Y dice para qué sirve, no solo que existe.
    assert "table" in texto.lower()
