"""Issue #180 — diez de los once handlers de bloque no los ejecutaba nadie.

**Lo que se midió, y lo que decide el remedio.** `blocks/handlers.py` declaraba once clases, una
por tipo de bloque, y fuera de sus propios tests **sólo `ChartHandler` tenía consumidor vivo**
(`ChartRenderNode._dibujar`). No había registro por `kind`, ni despachador, ni nada que las
recorriera: lo que ejecuta cada tipo de bloque son los nodos del grafo.

**La tercera posibilidad queda descartada por medición**, y era la que había que descartar
primero: la familia **no** es un contrato de extensión para que un tercero añada tipos de
bloque. No hay registro, `docs/REDACCION_CONTRACT_FIRST.md` sólo menciona `ChartHandler` —el
vivo— y nada en el código invita a registrar nada. Así que el remedio no es cablear un
despachador.

**De las diez, ocho eran duplicados** de un nodo que hace lo mismo y más, y se retiran:
`DeterministicDataHandler` frente a `DeterministicExtractionNode`, `TableHandler` frente a
`TableRenderNode`, `DataTransformHandler` frente a `DataTransformationNode`, los tres de IA
frente a `AIAssistDraftNode`, `ReviewGateHandler` frente a `UserReviewGateNode` más
`bloques_pendientes`, y `UserInputHandler`, que sólo devolvía lo que el estado ya tenía.

**Y tres eran capacidades que nadie había cableado**, que es lo que este fichero fija. Los tres
tipos cuyo contenido **no lo produce ningún nodo** no aparecían en el informe, porque el
ensamblador salta lo que no tiene contenido:

- `STATIC_TEXT` — el texto que trae escrito la plantilla. Hay uno en la plantilla de ejecución
  presupuestaria y **nunca se imprimía**.
- `USER_INPUT` — lo que escribe una persona. Es la issue #86, y ya está.
- `CITATION_BLOCK` — el apartado de fuentes, que `llm_spec_service` ofrece al modelo como tipo
  disponible: una plantilla propuesta podía llevarlo y salía en blanco sin decirlo.

Es literalmente lo que la #171 dejó escrito: **una clase que nadie monta no se prueba en uso**,
así que acumula defectos que nadie ve. Aquí los defectos eran tres apartados que no salían.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from server.app.modules.redaccion.contracts.blocks import (
    AIAssistedTextBlock,
    CitationBlock,
    StaticTextBlock,
)
from server.app.modules.redaccion.contracts.inputs import InputContract
from server.app.modules.redaccion.contracts.runtime import (
    BlockState,
    Citation,
    WorkspaceState,
)
from server.app.modules.redaccion.contracts.template import (
    AIBlockPolicy,
    ExportPolicy,
    ReportTemplateSpec,
    ReviewPolicy,
    SectionContract,
)
from server.app.modules.redaccion.contracts.ui import ReportUIContract


def _spec(bloques) -> ReportTemplateSpec:
    return ReportTemplateSpec(
        sections=[
            SectionContract(
                id="s1", title="Única", order=1, block_ids=[b.id for b in bloques]
            )
        ],
        blocks=bloques,
        input_contract=InputContract(required_slots=[], optional_slots=[]),
        ui_contract=ReportUIContract(
            wizard_steps=[],
            dropzones=[],
            manual_fields=[],
            block_editor_enabled=True,
            ai_review_panel_enabled=True,
            preview_layout="markdown",
        ),
        ai_block_policy=AIBlockPolicy.ALLOWED,
        review_policy=ReviewPolicy.NONE,
        export_policy=ExportPolicy.DOCX,
    )


def _estado(bloques, *, manual_inputs=None, estados=None) -> WorkspaceState:
    ahora = datetime.now(timezone.utc)
    spec = _spec(bloques)
    return WorkspaceState(
        workspace_id=uuid.uuid4(),
        template_version_id=uuid.uuid4(),
        report_profile="GENERIC_REPORT",
        inputs={},
        blocks={
            b.id: BlockState(
                block_id=b.id,
                kind=b.kind,
                status=(estados or {}).get(b.id, "draft"),
                last_updated_by="system",
                updated_at=ahora,
                **((estados or {}).get(f"{b.id}__extra") or {}),
            )
            for b in bloques
        },
        status="drafting",
        warnings=[],
        spec=spec,
        manual_inputs=manual_inputs or {},
    )


class TestElTextoDeLaPlantillaSaleEnElInforme:
    """`STATIC_TEXT`: lo produce la plantilla y nadie lo volcaba."""

    @pytest.mark.asyncio
    async def test_el_contenido_estatico_llega_al_bloque(self):
        from server.app.modules.redaccion.graph.nodes.fill_direct_blocks import (
            FillDirectBlocksNode,
        )

        bloque = StaticTextBlock(
            id="b_intro", title="Presentación", content="Este informe cubre el curso 2025-2026."
        )
        cambios = await FillDirectBlocksNode()(_estado([bloque]))

        assert cambios["blocks"]["b_intro"].content == {
            "text": "Este informe cubre el curso 2025-2026."
        }

    @pytest.mark.asyncio
    async def test_y_se_imprime_en_el_documento_ensamblado(self):
        """Medir el efecto, no la forma: el síntoma era un apartado que no salía."""
        from server.app.modules.redaccion.graph.nodes.fill_direct_blocks import (
            FillDirectBlocksNode,
        )
        from server.app.modules.redaccion.graph.nodes.final_assembler import (
            FinalAssemblerNode,
        )

        bloque = StaticTextBlock(
            id="b_intro", title="Presentación", content="Este informe cubre el curso 2025-2026."
        )
        estado = _estado([bloque])
        cambios = await FillDirectBlocksNode()(estado)
        final = await FinalAssemblerNode()(
            estado.model_copy(update={"blocks": cambios["blocks"]})
        )

        assert "Este informe cubre el curso 2025-2026." in final["final_document"]

    @pytest.mark.asyncio
    async def test_un_estatico_vacio_no_inventa_contenido(self):
        """Sin esto, lo de arriba se cumpliría metiendo un apartado en blanco en el informe."""
        from server.app.modules.redaccion.graph.nodes.fill_direct_blocks import (
            FillDirectBlocksNode,
        )

        bloque = StaticTextBlock(id="b_vacio", title="Sin texto", content="")
        cambios = await FillDirectBlocksNode()(_estado([bloque]))

        assert cambios == {}


class TestElApartadoDeFuentes:
    """`CITATION_BLOCK`: recoge las citas de los bloques que nombra."""

    def _bloques(self):
        return [
            AIAssistedTextBlock(
                id="b_valoracion",
                title="Valoración",
                ai_prompt_template_id="p1",
                review_policy_id="r1",
            ),
            CitationBlock(
                id="b_fuentes", title="Fuentes", source_block_refs=["b_valoracion"]
            ),
        ]

    def _con_citas(self):
        bloques = self._bloques()
        estado = _estado(bloques, estados={"b_valoracion": "ai_generated"})
        citada = estado.blocks["b_valoracion"].model_copy(
            update={
                "content": {"text": "La ejecución fue del 92 %."},
                "citations": [
                    Citation(
                        source_document="b_datos", page=4, excerpt="Ejecución: 92 %"
                    )
                ],
            }
        )
        return estado.model_copy(
            update={"blocks": {**estado.blocks, "b_valoracion": citada}}
        )

    @pytest.mark.asyncio
    async def test_recoge_las_citas_de_los_bloques_que_nombra(self):
        from server.app.modules.redaccion.graph.nodes.citation_traceability import (
            CitationAndTraceabilityNode,
        )

        cambios = await CitationAndTraceabilityNode()(self._con_citas())

        citas = (cambios["blocks"]["b_fuentes"].content or {}).get("citations") or []
        assert [c["source_document"] for c in citas] == ["b_datos"]

    @pytest.mark.asyncio
    async def test_y_las_imprime_en_el_documento(self):
        from server.app.modules.redaccion.graph.nodes.citation_traceability import (
            CitationAndTraceabilityNode,
        )
        from server.app.modules.redaccion.graph.nodes.final_assembler import (
            contenido_a_markdown,
        )

        cambios = await CitationAndTraceabilityNode()(self._con_citas())

        markdown = contenido_a_markdown(cambios["blocks"]["b_fuentes"].content)
        assert "b_datos" in markdown
        assert "Ejecución: 92 %" in markdown

    @pytest.mark.asyncio
    async def test_sin_citas_no_deja_un_apartado_en_blanco(self):
        """Sin esto, lo de arriba se cumpliría imprimiendo el título y nada debajo."""
        from server.app.modules.redaccion.graph.nodes.citation_traceability import (
            CitationAndTraceabilityNode,
        )

        cambios = await CitationAndTraceabilityNode()(_estado(self._bloques()))

        assert cambios["blocks"]["b_fuentes"].content is None


class TestSoloQuedaElHandlerQueAlguienEjecuta:
    """El guardarraíl: la familia entera no vuelve a crecer sin consumidor."""

    def test_handlers_declara_solo_el_que_esta_montado(self):
        import inspect

        from server.app.modules.redaccion.blocks import handlers

        clases = sorted(
            nombre
            for nombre, objeto in vars(handlers).items()
            if inspect.isclass(objeto)
            and nombre.endswith("Handler")
            and objeto.__module__ == handlers.__name__
        )
        assert clases == ["ChartHandler"], (
            "un handler que nadie monta no se prueba en uso, así que acumula defectos que "
            "nadie ve: fue el caso de los diez de la issue #180. Si hace falta uno nuevo, va "
            "con su consumidor en el mismo commit"
        )

    #: Quién ejecuta cada tipo de bloque. Es la tabla que la issue #180 pedía, y lo que
    #: sustituye a la familia de handlers: un tipo del contrato sin nodo que lo atienda es un
    #: apartado que no sale en el informe, que es lo que se acaba de arreglar tres veces.
    QUIEN_ATIENDE_CADA_TIPO = {
        "STATIC_TEXT": "fill_direct_blocks",
        "USER_INPUT": "fill_direct_blocks",
        "DETERMINISTIC_DATA": "deterministic_extraction",
        "TABLE": "table_render",
        "CHART": "chart_render",
        "DATA_TRANSFORM": "data_transformation",
        "AI_ASSISTED_TEXT": "ai_assist_draft",
        "AI_SUMMARY": "ai_assist_draft",
        "AI_REWRITE": "ai_assist_draft",
        "CITATION_BLOCK": "citation_traceability",
        "REVIEW_GATE": "review_gate",
    }

    def _nodos_del_grafo(self) -> set[str]:
        from unittest.mock import MagicMock

        from server.app.modules.redaccion.graph.core_graph import build_core_graph

        grafo = build_core_graph(
            MagicMock(), MagicMock(), MagicMock(), MagicMock()
        ).get_graph()
        return {n for n in grafo.nodes if not n.startswith("__")}

    def _tipos_del_contrato(self) -> set[str]:
        from server.app.modules.redaccion.contracts.blocks import BlockContract

        return {
            opcion.model_fields["kind"].default
            for opcion in BlockContract.__args__[0].__args__  # type: ignore[attr-defined]
        }

    def test_cada_tipo_de_bloque_tiene_su_nodo_en_el_grafo(self):
        """Se mira el grafo **compilado**, no el texto del fichero: un nodo que se importa y no
        se registra pasaría una comprobación de código fuente y no ejecutaría nada."""
        nodos = self._nodos_del_grafo()

        sin_nodo = {
            kind: nodo
            for kind, nodo in self.QUIEN_ATIENDE_CADA_TIPO.items()
            if nodo not in nodos
        }
        assert not sin_nodo, (
            f"estos tipos de bloque se quedan sin quien los atienda: {sin_nodo}. Un tipo sin "
            "nodo es un apartado que no sale en el informe, y no da ningún error"
        )

    def test_la_tabla_cubre_todos_los_tipos_del_contrato(self):
        """Sin esto, añadir un tipo de bloque nuevo no rompería nada y saldría en blanco."""
        assert self._tipos_del_contrato() == set(self.QUIEN_ATIENDE_CADA_TIPO), (
            "el contrato de bloques y la tabla de quién los atiende han dejado de coincidir"
        )
