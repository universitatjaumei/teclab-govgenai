"""ScriptProposalService — 9R.5.5 Parte 3.

Genera scripts Python de extracción a partir de prompts NL del usuario y
audita el resultado con ScriptSecurityAuditor (9R.5.4). NO persiste.

Reutiliza el mismo contrato de salida que AdminScriptExtractionPipeline:
- variables disponibles: file_path (str), raw_text (str), options (dict)
- el script debe asignar `result: dict` con tables/metrics/free_text.
"""
from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel

from server.app.modules.redaccion.services.actividades_llm import (
    ActividadLLM,
    PROMPT_POR_ACTIVIDAD,
    rellenar,
)
from server.app.modules.redaccion.services.script_auditor import (
    AuditResult,
    MODULOS_PROHIBIDOS,
    NOMBRES_PROHIBIDOS,
    RiskLevel,
    ScriptSecurityAuditor,
    WHITELIST_MODULES,
)
from server.app.core.llm_text import texto_de


PROMPT_VERSION = "script_proposal_v1"


def _build_system_prompt(
    sample_schema: dict[str, Any] | None, plantilla: str | None = None
) -> str:
    """El prompt del sistema, con sus variables rellenas.

    PRO.2.1 — la plantilla puede venir de la biblioteca de prompts; por defecto es la del
    catálogo de código. Las listas de módulos y de nombres **se leen del auditor**, porque un
    prompt que enumera a mano lo que otro fichero bloquea divergen en el primer cambio, y el
    síntoma es una propuesta rechazada sin motivo entendible.
    """
    schema_hint = ""
    if sample_schema:
        schema_hint = (
            "\n\nSCHEMA DE LOS DATOS DE ENTRADA (informativo):\n"
            f"{sample_schema}\n"
        )
    return rellenar(
        plantilla or PROMPT_POR_ACTIVIDAD[ActividadLLM.PROPUESTA_DE_SCRIPT],
        {
            "lista_blanca": sorted(WHITELIST_MODULES),
            "modulos_prohibidos": sorted(MODULOS_PROHIBIDOS),
            "nombres_prohibidos": sorted(
                n for n in NOMBRES_PROHIBIDOS if not n.startswith("__")
            ),
            "atributos_prohibidos": sorted(
                n for n in NOMBRES_PROHIBIDOS if n.startswith("__")
            ),
            "schema": schema_hint,
        },
    )


AUDITOR_PROMPT_VERSION = "script_audit_v1"


_FEW_SHOT_EXAMPLES: list[dict[str, str]] = [
    {
        "user": (
            "Extrae todas las filas del Excel y devuelve una tabla con sus columnas."
        ),
        "assistant": (
            "import pandas as pd\n"
            "\n"
            "df = pd.read_excel(file_path)\n"
            "result = {\n"
            "    'tables': [{\n"
            "        'name': 'sheet1',\n"
            "        'headers': list(df.columns),\n"
            "        'rows': df.astype(str).where(df.notna(), '').values.tolist(),\n"
            "        'source_page': None,\n"
            "    }],\n"
            "    'metrics': [],\n"
            "    'free_text': None,\n"
            "}\n"
        ),
    },
    {
        "user": "Devuelve el texto plano del PDF.",
        "assistant": (
            "import pdfplumber\n"
            "\n"
            "with pdfplumber.open(file_path) as pdf:\n"
            "    text = '\\n\\n'.join(p.extract_text() or '' for p in pdf.pages)\n"
            "result = {'tables': [], 'metrics': [], 'free_text': text}\n"
        ),
    },
    {
        "user": (
            "Lee el Excel y calcula la suma de la columna 'importe' agrupada por "
            "'departamento'; devuelve una tabla con dos columnas."
        ),
        "assistant": (
            "import pandas as pd\n"
            "\n"
            "df = pd.read_excel(file_path)\n"
            "agg = df.groupby('departamento')['importe'].sum().reset_index()\n"
            "result = {\n"
            "    'tables': [{\n"
            "        'name': 'importe_por_departamento',\n"
            "        'headers': ['departamento', 'importe_total'],\n"
            "        'rows': agg.astype(str).where(agg.notna(), '').values.tolist(),\n"
            "        'source_page': None,\n"
            "    }],\n"
            "    'metrics': [],\n"
            "    'free_text': None,\n"
            "}\n"
        ),
    },
]


def _extract_code(text: str) -> str:
    """Si el LLM devuelve markdown fences, extrae solo el código."""
    m = re.search(r"```(?:python)?\s*([\s\S]*?)```", text)
    if m:
        return m.group(1).strip()
    return text.strip()


_VEREDICTOS = ("acepta", "duda", "rechaza")


def _leer_veredicto(texto: str, model_name: str) -> RevisionDelModelo:
    """El veredicto del auditor, y `duda` cuando no se le entiende.

    Un auditor que responde en prosa no puede convertirse en un «acepta» silencioso: el valor
    por defecto de una respuesta ilegible es la sospecha, no la aprobación. Y el texto crudo
    se conserva como motivo, porque es lo que permite saber si el prompt hay que afinarlo.
    """
    bruto = (texto or "").strip()
    bloque = re.search(r"\{[\s\S]*\}", bruto)
    if bloque:
        try:
            datos = json.loads(bloque.group(0))
        except json.JSONDecodeError:
            datos = None
        if isinstance(datos, dict) and datos.get("veredicto") in _VEREDICTOS:
            motivos = datos.get("motivos") or []
            return RevisionDelModelo(
                veredicto=datos["veredicto"],
                motivos=[str(m) for m in motivos] if isinstance(motivos, list) else [str(motivos)],
                model_used=model_name,
            )

    return RevisionDelModelo(
        veredicto="duda",
        motivos=[f"El auditor no devolvió un veredicto legible: {bruto[:300]}"],
        model_used=model_name,
    )


class RevisionDelModelo(BaseModel):
    """Lo que el modelo auditor opina del script — PRO.2.

    Es un segundo par de ojos, no una puerta: el veredicto **no toca** `audit_result`. La
    auditoría determinista es la que no se puede convencer; ésta explica, y lo que explica
    viaja con la propuesta hasta quien la revisa.
    """

    veredicto: Literal["acepta", "duda", "rechaza"]
    motivos: list[str]
    model_used: str
    prompt_version: str = AUDITOR_PROMPT_VERSION


class ProposalResult(BaseModel):
    """Resultado de `ScriptProposalService.propose()`. Sin persistencia."""

    code: str
    audit_result: AuditResult
    model_used: str
    prompt_version: str = PROMPT_VERSION
    rationale: str | None = None
    revision_del_modelo: RevisionDelModelo | None = None


class ScriptProposalService:
    """Genera scripts a partir de NL + audita con ScriptSecurityAuditor."""

    def __init__(
        self,
        llm: Any,
        script_auditor: ScriptSecurityAuditor | None = None,
        model_name: str = "unknown",
        prompt_version: str = PROMPT_VERSION,
        auditor_llm: Any = None,
        auditor_model_name: str = "",
        system_prompt: str | None = None,
        auditor_system_prompt: str | None = None,
    ) -> None:
        self._llm = llm
        self._auditor = script_auditor or ScriptSecurityAuditor()
        self._model_name = model_name
        self._prompt_version = prompt_version
        self._auditor_llm = auditor_llm
        self._auditor_model_name = auditor_model_name
        # PRO.2.1 — los dos prompts pueden venir de la biblioteca; None = el del catálogo.
        self._system_prompt = system_prompt
        self._auditor_system_prompt = auditor_system_prompt

    @property
    def modelo(self) -> Any:
        """El modelo que escribe: el que el Copilot nombra si la propuesta falla (#348)."""
        return self._llm

    async def propose(
        self,
        prompt_nl: str,
        sample_schema: dict[str, Any] | None = None,
        owner_kind: Literal["user", "platform"] = "user",
    ) -> ProposalResult:
        system_prompt = _build_system_prompt(sample_schema, self._system_prompt)
        if owner_kind == "platform":
            system_prompt += (
                "\n\nCONTEXTO: este script será propuesto para una plantilla GLOBAL "
                "(uso por toda la plataforma). Sé especialmente conservador con las "
                "operaciones; evita asumir nombres de columna concretos si no aparecen "
                "en el SCHEMA."
            )

        messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
        for example in _FEW_SHOT_EXAMPLES:
            messages.append({"role": "user", "content": example["user"]})
            messages.append({"role": "assistant", "content": example["assistant"]})
        messages.append({"role": "user", "content": prompt_nl})

        response = await self._llm.ainvoke(messages)
        raw = texto_de(response)
        code = _extract_code(raw)

        # Primero el AST, que no se puede convencer; después el modelo, que explica.
        audit = self._auditor.audit(code)
        revision = await self._revisar_con_modelo(code, prompt_nl, audit)

        return ProposalResult(
            code=code,
            audit_result=audit,
            model_used=self._model_name,
            prompt_version=self._prompt_version,
            revision_del_modelo=revision,
        )

    async def _revisar_con_modelo(
        self, code: str, prompt_nl: str, audit: AuditResult
    ) -> RevisionDelModelo | None:
        """El segundo par de ojos, cuando hay algo que mirar.

        No se pide sobre un script CRÍTICO: no se va a ejecutar nunca, así que juzgar su
        semántica es pagar una llamada por una opinión sobre código muerto. Y los hallazgos
        deterministas ya dicen qué línea es y por qué.
        """
        if self._auditor_llm is None or audit.risk_level == RiskLevel.CRITICAL:
            return None

        peticion = (
            f"PETICIÓN DEL USUARIO:\n{prompt_nl}\n\n"
            f"SCRIPT PROPUESTO:\n```python\n{code}\n```"
        )
        instrucciones = self._auditor_system_prompt or PROMPT_POR_ACTIVIDAD[
            ActividadLLM.AUDITORIA_DE_SCRIPT
        ]
        respuesta = await self._auditor_llm.ainvoke([
            {"role": "system", "content": instrucciones},
            {"role": "user", "content": peticion},
        ])
        texto = texto_de(respuesta)
        return _leer_veredicto(texto, self._auditor_model_name)
