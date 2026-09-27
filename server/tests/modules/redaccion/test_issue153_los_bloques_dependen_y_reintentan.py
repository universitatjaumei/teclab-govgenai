"""Issue #153 — `block_executor` decía ser la única superficie con política de reintento.

Su docstring dice, en mayúsculas: «BlockExecutor es la ÚNICA superficie con política de retry.
Los nodos del grafo NO implementan su propio retry; delegan en BlockExecutor». **No lo importaba
nadie.** Y una regla que dice «soy el único» y no se llama sólo deja dos desenlaces: o nadie
reintenta, o cada cual se lo hace por su cuenta. Aquí era el primero.

Dos consecuencias, y ninguna avisaba:

1. **Nada reintentaba.** Un *timeout* del modelo —transitorio por definición— dejaba el apartado
   en `failed` para siempre. La columna `retry_attempts` existe en la base, viaja en el DTO y la
   pinta la pantalla desde la #98: valía 0 en todas las filas de todas las ejecuciones, porque
   nadie la escribía nunca.

2. **Un apartado se redactaba sin sus datos.** `propagate_dependency_failures` marca como
   fallidos los bloques cuyas dependencias fallaron, en cascada. Sin llamarla, si la extracción
   de `b_data` fallaba, el `b_analysis` que declara `depends_on: [b_data]` **se generaba igual**,
   con el contexto que quedara. Es exactamente lo que el propio módulo evita en el camino
   anclado, y con las mismas palabras: «una valoración redactada sin sus datos parece
   fundamentada y no lo está, que es peor que un apartado que falta».

   El camino anclado (`data_block_refs`, SEG.1) sí lo comprobaba. Pero `depends_on` es otro
   campo, y el perfil genérico declara `b_analysis → b_data` con `depends_on` y sin anclaje.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from server.app.modules.redaccion.contracts.blocks import (
    AIAssistedTextBlock,
    AISummaryBlock,
    BlockReference,
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

AHORA = datetime(2026, 9, 27, tzinfo=timezone.utc)


def _spec() -> ReportTemplateSpec:
    """El encadenado del perfil genérico: datos → análisis → conclusiones."""
    return ReportTemplateSpec(
        sections=[],
        blocks=[
            DeterministicDataBlock(id="b_data", title="Dades", source_pipeline="EXCEL"),
            AIAssistedTextBlock(
                id="b_analysis",
                title="Analisi",
                depends_on=[BlockReference(block_id="b_data")],
                ai_prompt_template_id="analisi_v1",
                review_policy_id="required",
            ),
            AISummaryBlock(
                id="b_conclusions",
                title="Conclusions",
                depends_on=[BlockReference(block_id="b_analysis")],
                ai_prompt_template_id="conclusions_v1",
                review_policy_id="required",
            ),
        ],
        input_contract=InputContract(),
        ui_contract=ReportUIContract(
            wizard_steps=[], dropzones=[], manual_fields=[],
            block_editor_enabled=False, ai_review_panel_enabled=True,
            preview_layout="markdown",
        ),
        ai_block_policy=AIBlockPolicy.ALLOWED,
        review_policy=ReviewPolicy.REQUIRED,
        export_policy=ExportPolicy.DOCX,
    )


def _bloque(block_id: str, kind: str, status: str, content: dict | None = None) -> BlockState:
    return BlockState(
        block_id=block_id,
        kind=kind,
        status=status,
        content=content,
        last_updated_by="system",
        updated_at=AHORA,
    )


def _estado(estado_de_los_datos: str, content: dict | None = None) -> WorkspaceState:
    return WorkspaceState(
        workspace_id=uuid.uuid4(),
        template_version_id=uuid.uuid4(),
        report_profile="GENERIC_REPORT",
        inputs={},
        blocks={
            "b_data": _bloque("b_data", "DETERMINISTIC_DATA", estado_de_los_datos, content),
            "b_analysis": _bloque("b_analysis", "AI_ASSISTED_TEXT", "draft"),
            "b_conclusions": _bloque("b_conclusions", "AI_SUMMARY", "draft"),
        },
        status="drafting",
        warnings=[],
        spec=_spec(),
    )


def _llm(*respuestas) -> MagicMock:
    """Modelo que devuelve —o levanta— una cosa distinta en cada llamada."""
    servicio = MagicMock()
    servicio.model_name = "modelo-de-prueba"
    servicio.generate = AsyncMock(side_effect=list(respuestas))
    return servicio


def _nodo(llm: MagicMock) -> AIAssistDraftNode:
    # Sin espera entre intentos: el reintento se comprueba por que ocurre, no por lo que tarda.
    return AIAssistDraftNode(llm, retry_delay_seconds=0)


class TestUnApartadoNoSeRedactaSinSusDatos:

    @pytest.mark.asyncio
    async def test_si_falla_el_bloque_del_que_depende_no_se_genera(self):
        llm = _llm("no deberia llamarse")
        salida = await _nodo(llm)(_estado("failed"))

        analisis = salida["blocks"]["b_analysis"]
        assert analisis.status == "failed", (
            "el análisis se redactó con la extracción caída: parece fundamentado y no lo está"
        )
        assert analisis.failure_kind == "validation_failed"
        assert "b_data" in (analisis.last_error_message or ""), (
            "el motivo tiene que nombrar de qué dependía, o desde la pantalla es un fallo mudo"
        )
        assert llm.generate.await_count == 0, "se llamó al modelo igualmente"

    @pytest.mark.asyncio
    async def test_la_cascada_llega_al_siguiente(self):
        """`b_conclusions` depende de `b_analysis`, que depende de `b_data`."""
        llm = _llm("no deberia llamarse")
        salida = await _nodo(llm)(_estado("failed"))

        assert salida["blocks"]["b_conclusions"].status == "failed"
        assert llm.generate.await_count == 0

    @pytest.mark.asyncio
    async def test_si_falla_un_apartado_de_ia_tampoco_se_redacta_el_que_depende_de_el(self):
        """El fallo nace **dentro** de este nodo: la propagación tiene que verlo en el mismo paso."""
        llm = _llm(ValueError("el modelo no contesta"))
        salida = await _nodo(llm)(_estado("extracted", {"free_text": "dades"}))

        assert salida["blocks"]["b_analysis"].status == "failed"
        assert salida["blocks"]["b_conclusions"].status == "failed", (
            "el análisis falló y las conclusiones se redactaron igual, apoyadas en nada"
        )
        assert llm.generate.await_count == 1, "sólo debía llamarse para el análisis"


class TestLoQueEsTransitorioSeReintenta:

    @pytest.mark.asyncio
    async def test_un_timeout_se_reintenta_y_queda_contado(self):
        llm = _llm(TimeoutError("se agotó el tiempo"), "Analisi redactada", "Conclusions")
        salida = await _nodo(llm)(_estado("extracted", {"free_text": "dades"}))

        analisis = salida["blocks"]["b_analysis"]
        assert analisis.status == "ai_generated", (
            "un timeout es transitorio por definición y dejaba el apartado caído para siempre"
        )
        assert analisis.retry_attempts == 1, (
            "la pantalla pinta `retry_attempts` desde la #98 y valía 0 en todas las filas"
        )

    @pytest.mark.asyncio
    async def test_un_error_determinista_no_se_reintenta(self):
        """Reintentar un fallo que se repetirá igual es gastar el doble en el mismo error."""
        llm = _llm(ValueError("plantilla mal formada"), "esto no debería usarse")
        salida = await _nodo(llm)(_estado("extracted", {"free_text": "dades"}))

        analisis = salida["blocks"]["b_analysis"]
        assert analisis.status == "failed"
        assert analisis.failure_kind == "ai_failed"
        assert analisis.retry_attempts == 0
        assert llm.generate.await_count == 1


class TestElCaminoBuenoSigueSiendoElMismo:
    """Donde un `except` evita una caída hace falta un test del camino BUENO."""

    @pytest.mark.asyncio
    async def test_con_todo_en_orden_se_redactan_los_dos_apartados(self):
        llm = _llm("Analisi redactada", "Conclusions redactades")
        salida = await _nodo(llm)(_estado("extracted", {"free_text": "dades"}))

        analisis = salida["blocks"]["b_analysis"]
        conclusiones = salida["blocks"]["b_conclusions"]

        assert analisis.status == "ai_generated"
        assert analisis.content["text"] == "Analisi redactada"
        assert analisis.retry_attempts == 0
        assert conclusiones.status == "ai_generated"
        assert conclusiones.content["model_used"] == "modelo-de-prueba"
        assert llm.generate.await_count == 2
