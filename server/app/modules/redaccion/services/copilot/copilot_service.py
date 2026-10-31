"""Copilot: dos modos, en dos clases (#348).

1. `answer(question, module)`: RAG sobre la documentación interna + síntesis LLM con citas.
2. `CopilotTranslator.translate_nl_to_config(instruction, target_kind)`: traduce instrucción NL a configuración
   estructurada para los wizards (chart, ETL, script proposal).
"""

from __future__ import annotations

from typing import Any

from .docs_retriever import DocsRetriever
from .models import (
    CopilotAnswer,
    CopilotModule,
    CopilotTargetKind,
    CopilotTranslateResponse,
)
from server.app.core.llm_text import texto_de


_ANSWER_SYSTEM_PROMPT = """Eres un asistente experto en la plataforma Gov Gen AI. \
Respondes preguntas del usuario apoyándote ÚNICAMENTE en los fragmentos de documentación \
que se te pasan como contexto. Si la respuesta no está en el contexto, di explícitamente \
"No tengo esa información en la documentación disponible." y no inventes.

Cita las secciones relevantes mencionando el título del documento entre corchetes."""


class ElModeloNoResponde(Exception):
    """La llamada al modelo falló: el proveedor lo rechazó, no respondió o no existe (#344).

    Lleva el modelo para que quien la recoja pueda decir **cuál**; el motivo es la excepción
    encadenada. Se levanta sólo alrededor de la llamada al modelo: un fallo del buscador no es del
    modelo, y atribuírselo mandaría a mirar la pantalla equivocada.
    """

    def __init__(self, modelo: Any, motivo: Exception) -> None:
        super().__init__(str(motivo))
        self.modelo = modelo
        self.motivo = motivo


class ModeloVigilado:
    """Un modelo cuya llamada, si falla, dice que ha sido **él** (revisión de la PR #349).

    El modo traducción pasa por fábricas que llaman al modelo desde dentro —y la de scripts, a dos
    modelos de dos niveles—. Recoger el fallo fuera atribuía al que escribe lo que fallaba en el
    auditor, y convertía en «el modelo no responde» cualquier error de la fábrica. Envuelto así,
    sólo la llamada al modelo levanta `ElModeloNoResponde`, y con el modelo que de verdad falló.
    El resto de atributos —el nombre, sobre todo— se leen del modelo envuelto.
    """

    def __init__(self, modelo: Any) -> None:
        self._modelo = modelo

    async def ainvoke(self, *args: Any, **kwargs: Any) -> Any:
        try:
            return await self._modelo.ainvoke(*args, **kwargs)
        except Exception as fallo:  # el proveedor puede fallar de muchas maneras
            raise ElModeloNoResponde(self._modelo, fallo) from fallo

    def __getattr__(self, nombre: str) -> Any:
        return getattr(self._modelo, nombre)


class CopilotService:
    def __init__(self, llm: Any, retriever: DocsRetriever) -> None:
        self._llm = llm
        self._retriever = retriever

    async def answer(
        self,
        question: str,
        module: CopilotModule | None = None,
        top_k: int = 4,
        contexto_del_informe: str | None = None,
    ) -> CopilotAnswer:
        chunks = await self._retriever.retrieve(question, module=module, top_k=top_k)
        if not chunks and not contexto_del_informe:
            return CopilotAnswer(
                answer="No tengo esa información en la documentación disponible.",
                source_refs=[],
            )
        context_block = "\n\n---\n\n".join(
            f"[{chunk.source_path}]\n{chunk.text}" for chunk in chunks
        )
        messages = [
            {"role": "system", "content": _ANSWER_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"CONTEXTO:\n{context_block}\n\n"
                    # INF.10 — el estado del informe abierto va **después** de la documentación
                    # y marcado como tal: cuando la pregunta es «dónde hago esto», lo que vale
                    # es este informe y no la descripción general de la pantalla. El texto ya
                    # viene anonimizado de `contexto_del_informe`.
                    + (f"{contexto_del_informe}\n\n" if contexto_del_informe else "")
                    + f"PREGUNTA: {question}\n\n"
                    "Si el estado del informe abierto responde a la pregunta, contesta con la"
                    " accion concreta de ESTE informe —qué apartado y dónde— en vez de con una"
                    " descripción general. Si hay algo pendiente de una persona, dilo aunque no"
                    " te lo pregunten.\n"
                    "Responde en el idioma de la pregunta."
                ),
            },
        ]
        try:
            response = await self._llm.ainvoke(messages)
        except Exception as fallo:  # el proveedor puede fallar de muchas maneras
            raise ElModeloNoResponde(self._llm, fallo) from fallo
        raw = texto_de(response)
        return CopilotAnswer(
            answer=raw,
            source_refs=[c.to_source_ref() for c in chunks],
        )


class CopilotTranslator:
    """El modo traducción: instrucción en lenguaje natural → configuración de un asistente (#348).

    Estaba dentro de `CopilotService`, que el router construía con el modelo del nivel 1 y el
    buscador de documentación y **sin ninguna fábrica**: cada traducción era un 500. Va aparte
    porque no comparte nada con el modo pregunta: no busca en la documentación, y cada modo
    tiene el modelo y el prompt de su actividad. Las fábricas llevan sus modelos envueltos en
    `ModeloVigilado`, que es lo que hace que un fallo nombre al modelo que falló.
    """

    def __init__(
        self,
        chart_factory: Any | None = None,
        etl_factory: Any | None = None,
        script_proposal: Any | None = None,
    ) -> None:
        self._chart_factory = chart_factory
        self._etl_factory = etl_factory
        self._script_proposal = script_proposal

    async def translate_nl_to_config(
        self,
        instruction: str,
        target_kind: CopilotTargetKind,
        sample_schema: dict[str, Any] | None = None,
    ) -> CopilotTranslateResponse:
        schema = sample_schema or {}
        if target_kind == "chart_config":
            if self._chart_factory is None:
                raise ValueError("ChartFactory no configurada en este CopilotTranslator")
            # PRO.8 — esto llamaba a `generate_script`, así que el `target_kind` mentía: pedía
            # una configuración y devolvía código. Ahora devuelve configuración cuando la
            # petición cabe en el catálogo, y baja al script sólo cuando no cabe.
            result = await self._chart_factory.generate_chart_from_nl(
                nl_prompt=instruction, schema=schema
            )
            return CopilotTranslateResponse(
                kind="chart_config", payload=self._to_dict(result)
            )
        if target_kind == "etl_ops":
            if self._etl_factory is None:
                raise ValueError("ETLFactory no configurada en este CopilotTranslator")
            result = await self._etl_factory.generate_operations_from_nl(
                nl_prompt=instruction, schema=schema
            )
            return CopilotTranslateResponse(
                kind="etl_ops", payload=self._to_dict(result)
            )
        if target_kind == "script_proposal":
            if self._script_proposal is None:
                raise ValueError("ScriptProposalService no configurado en este CopilotTranslator")
            result = await self._script_proposal.propose(
                prompt_nl=instruction, sample_schema=schema or None
            )
            return CopilotTranslateResponse(
                kind="script_proposal", payload=self._to_dict(result)
            )
        raise ValueError(f"target_kind desconocido: {target_kind}")

    @staticmethod
    def _to_dict(obj: Any) -> dict[str, Any]:
        if hasattr(obj, "model_dump"):
            return obj.model_dump(mode="json")
        if isinstance(obj, dict):
            return obj
        return {"value": obj}
