"""DraftingCoreGraph bootstrap — 9R.6.1–9R.6.5.

build_core_graph() devuelve el StateGraph compilado listo para invocar.
El grafo usa WorkspaceState (Pydantic BaseModel) como tipo de estado.
Todos los nodos se envuelven con el helper traced_node para observabilidad Langfuse.
"""
from __future__ import annotations

from typing import Any

from langgraph.graph import StateGraph

from server.app.modules.redaccion.contracts.runtime import WorkspaceState
from server.app.modules.redaccion.graph.nodes.ai_assist_draft import AIAssistDraftNode
from server.app.modules.redaccion.graph.nodes.apply_user_edits import ApplyUserEditsNode
from server.app.modules.redaccion.graph.nodes.audit_log import AuditLogNode
from server.app.modules.redaccion.graph.nodes.citation_traceability import CitationAndTraceabilityNode
from server.app.modules.redaccion.graph.nodes.data_quality_check import (
    DataQualityCheckNode,
    data_quality_router,
)
from server.app.modules.redaccion.graph.nodes.chart_render import ChartRenderNode
from server.app.modules.redaccion.graph.nodes.table_render import TableRenderNode
from server.app.modules.redaccion.graph.nodes.data_transformation import DataTransformationNode
from server.app.modules.redaccion.graph.nodes.deterministic_extraction import DeterministicExtractionNode
from server.app.modules.redaccion.graph.nodes.file_normalization import FileNormalizationNode
from server.app.modules.redaccion.graph.nodes.final_assembler import FinalAssemblerNode
from server.app.modules.redaccion.graph.nodes.init_anonymization import InitAnonymizationNode
from server.app.modules.redaccion.graph.nodes.load_template import LoadTemplateNode
from server.app.modules.redaccion.graph.nodes.missing_data_question import MissingDataQuestionNode
from server.app.modules.redaccion.graph.nodes.review_gate import UserReviewGateNode, review_gate_router
from server.app.modules.redaccion.graph.nodes.validate_inputs import ValidateInputContractNode
from server.app.modules.redaccion.graph.tracing import NoOpTracingService, traced_node


def build_core_graph(
    template_version_repo: Any,
    storage_service: Any,
    extraction_factory: Any,
    llm_service: Any,
    manifest_repo: Any = None,
    tracing_service: Any = None,
    etl_llm: Any = None,
    etl_model_name: str = "",
    etl_system_prompt: str | None = None,
    pii_detector: Any = None,
    faker_generator: Any = None,
    resolvedor_de_funciones: Any = None,
):
    """Construye y compila el DraftingCoreGraph.

    Args:
        template_version_repo: instancia compatible con ReportTemplateVersionRepo.
        storage_service: instancia compatible con StorageService.
        extraction_factory: instancia compatible con ExtractionPipelineFactory.
        llm_service: instancia compatible con LLMService Protocol.
        manifest_repo: instancia compatible con RunManifestRepo (opcional; no persiste sin él).
        tracing_service: instancia compatible con TracingService (por defecto: NoOp).
        resolvedor_de_funciones: `ResolvedorDeFuncion` (FUN.3). Sin él, un bloque que
            referencia una función del catálogo falla en alto diciéndolo — que es mejor que
            ejecutar nada en silencio, pero en producción hay que pasarlo.

    Returns:
        Grafo compilado listo para invocar con `await graph.ainvoke(state)`.
    """
    tracing = tracing_service or NoOpTracingService()

    load_node = LoadTemplateNode(template_version_repo)
    validate_node = ValidateInputContractNode()
    normalize_node = FileNormalizationNode(storage_service)
    extract_node = DeterministicExtractionNode(
        extraction_factory,
        resolvedor=resolvedor_de_funciones,
        # El mismo almacenamiento que usa la normalización: una función empaquetada resuelve su
        # entrada por aquí desde APER.14, en vez de abrir la ruta que le llegue.
        almacen=storage_service,
    )
    transform_node = DataTransformationNode(
        llm_service=etl_llm,
        model_name=etl_model_name,
        system_prompt=etl_system_prompt,
    )
    # PRO.5 — el nodo que dibuja los bloques CHART. No existía: `ChartHandler` estaba escrito
    # y probado, y sólo lo importaban los tests, así que un bloque CHART no dibujaba nada.
    chart_node = ChartRenderNode(
        storage_service=storage_service,
        llm_service=etl_llm,
        model_name=etl_model_name,
    )
    # SEG.5 — el hermano del nodo de gráficos para los bloques TABLE, que tampoco los pintaba
    # nadie: estaban en el contrato y salían vacíos en el informe.
    table_node = TableRenderNode()
    quality_node = DataQualityCheckNode()
    missing_node = MissingDataQuestionNode()
    init_anon_node = _build_init_anonymization_node(pii_detector, faker_generator)
    # El tracing va al nodo porque su `BlockExecutor` emite un span por intento fallido:
    # sin él, un reintento no se distingue de una llamada que salió a la primera.
    ai_node = AIAssistDraftNode(llm_service, tracing)
    citation_node = CitationAndTraceabilityNode()
    review_node = UserReviewGateNode()
    edits_node = ApplyUserEditsNode()
    assembler_node = FinalAssemblerNode()
    audit_node = AuditLogNode(manifest_repo, tracing)

    def _t(node, name: str):
        return traced_node(node, tracing, name)

    graph = StateGraph(WorkspaceState)
    graph.add_node("load_template",           _t(load_node,      "load_template"))
    graph.add_node("validate_inputs",         _t(validate_node,  "validate_inputs"))
    graph.add_node("file_normalization",      _t(normalize_node, "file_normalization"))
    graph.add_node("deterministic_extraction",_t(extract_node,     "deterministic_extraction"))
    graph.add_node("data_transformation",     _t(transform_node,  "data_transformation"))
    graph.add_node("chart_render",            _t(chart_node,     "chart_render"))
    graph.add_node("table_render",            _t(table_node,     "table_render"))
    graph.add_node("data_quality_check",      _t(quality_node,   "data_quality_check"))
    graph.add_node("missing_data_question",   _t(missing_node,   "missing_data_question"))
    graph.add_node("init_anonymization",      _t(init_anon_node, "init_anonymization"))
    graph.add_node("ai_assist_draft",         _t(ai_node,        "ai_assist_draft"))
    graph.add_node("citation_traceability",   _t(citation_node,  "citation_traceability"))
    graph.add_node("review_gate",             _t(review_node,    "review_gate"))
    graph.add_node("apply_user_edits",        _t(edits_node,     "apply_user_edits"))
    graph.add_node("final_assembler",         _t(assembler_node, "final_assembler"))
    graph.add_node("audit_log",               _t(audit_node,     "audit_log"))

    graph.set_entry_point("load_template")
    graph.add_edge("load_template", "validate_inputs")
    graph.add_edge("validate_inputs", "file_normalization")
    graph.add_edge("file_normalization", "deterministic_extraction")
    # **La anonimización va aquí, justo detrás de la extracción** (issue #170). Estaba entre
    # `data_quality_check` y `ai_assist_draft`, y su propio docstring decía «antes de cualquier
    # nodo que toque LLM»: no era cierto, porque la transformación de datos y el nodo de gráficos
    # llaman al modelo y quedaban por delante. Los dos invocan `apply_pre_llm` con un contexto
    # que en ese punto todavía era `None`, así que el hook devolvía el texto sin tocar.
    #
    # Detrás de la extracción es donde ya existe el texto que hay que escanear, y lo que se
    # detecta ahí sigue valiendo después: el mapa sustituye **cadenas**, no posiciones, así que un
    # dato del documento se sustituye igual cuando reaparece en una tabla transformada.
    graph.add_edge("deterministic_extraction", "init_anonymization")
    graph.add_edge("init_anonymization", "data_transformation")
    # El gráfico va después de la transformación: dibuja los datos ya limpios.
    graph.add_edge("data_transformation", "chart_render")
    # Y la tabla igual: reproduce los datos ya limpios, antes de que la IA los valore.
    graph.add_edge("chart_render", "table_render")
    graph.add_edge("table_render", "data_quality_check")
    graph.add_conditional_edges(
        "data_quality_check",
        data_quality_router,
        {"ask_user": "missing_data_question", "ok": "ai_assist_draft"},
    )
    graph.add_edge("missing_data_question", "audit_log")
    graph.add_edge("ai_assist_draft", "citation_traceability")
    graph.add_edge("citation_traceability", "review_gate")
    graph.add_conditional_edges(
        "review_gate",
        review_gate_router,
        {"pause": "audit_log", "continue": "apply_user_edits"},
    )
    graph.add_edge("apply_user_edits", "final_assembler")
    graph.add_edge("final_assembler", "audit_log")
    graph.set_finish_point("audit_log")

    return graph.compile()


def _build_init_anonymization_node(
    pii_detector: Any, faker_generator: Any
) -> Any:
    """Si no se inyectan dependencias, devuelve un nodo no-op (modo OFF efectivo).

    Permite que tests existentes que construyen el grafo sin servicios NER
    sigan funcionando: el nodo no detecta nada y deja `anonymization_context=None`,
    los hooks pre/post-LLM no operan, comportamiento idéntico al previo a 13.1.
    """
    if pii_detector is None or faker_generator is None:
        async def _noop(state: WorkspaceState) -> dict:
            return {}
        return _noop
    return InitAnonymizationNode(pii_detector, faker_generator)
