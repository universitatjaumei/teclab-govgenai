"""LLMSpecService — 9R.4.1.

Convierte texto en lenguaje natural en un ReportTemplateDraft estructurado.
No persiste nada; solo propone. La validación estructural es responsabilidad
de DraftValidator (9R.4.2).
"""
from __future__ import annotations

import json
from functools import lru_cache
from typing import Any, Literal, get_args

from pydantic import TypeAdapter

from server.app.core.llm_text import texto_de

from server.app.modules.redaccion.contracts.blocks import BlockContract
from server.app.modules.redaccion.contracts.drafts import ReportTemplateDraft
from server.app.modules.redaccion.contracts.inputs import InputContract, InputSlotKind
from server.app.modules.redaccion.contracts.template import SectionContract
from server.app.modules.redaccion.pipelines.contracts import ExtractionSourceKind
from server.app.modules.redaccion.services.charts.chart_configuration import TipoDeGrafico
from server.app.modules.redaccion.services.muestra_de_datos import MuestraDeDatos
from server.app.modules.redaccion.services.redactor_de_bloques import (
    PROMPT_RESUMEN_DE_RESULTADOS,
    PROMPT_VALORACION_DE_TENDENCIA,
)
from server.app.modules.redaccion.services.transformation.operations import (
    catalogo_de_operaciones,
)

_BLOCK_KINDS = [
    "STATIC_TEXT",
    "USER_INPUT",
    "DETERMINISTIC_DATA",
    # GUI.3 — faltaba, y detrás llevaba un «Do NOT use any block kind not in this list»: el ETL
    # entero (PRO.4 y PRO.9) era inalcanzable para una persona, porque tampoco hay ninguna
    # pantalla que configure bloques. Los bloques sólo entran por aquí.
    "DATA_TRANSFORM",
    "TABLE",
    "CHART",
    "AI_ASSISTED_TEXT",
    "AI_SUMMARY",
    "AI_REWRITE",
    "CITATION_BLOCK",
    "REVIEW_GATE",
]

_BLOCK_ADAPTER: TypeAdapter[BlockContract] = TypeAdapter(BlockContract)

PROMPT_VERSION = "llm_spec_v2"

#: Cada bloque tiene campos propios y obligatorios. Sin esto en el prompt, el modelo propone
#: estructuras razonables que el contrato rechaza, y el usuario ve un error del servidor por
#: algo que no hizo mal.
#:
#: GUI.3 — lo que era una constante pasa a ser una función, porque dos de sus listas **se
#: generan del contrato**: los tipos de gráfico y las operaciones de transformación. Escritas a
#: mano divergen en el primer cambio, y eso ya pasó: PRO.8 dejó once tipos de gráfico y este
#: prompt seguía ofreciendo cinco.
def _campos_obligatorios() -> str:
    return (
    "Every block needs: id, title, order. Additionally, by kind:\n"
    "- STATIC_TEXT: content (the literal text).\n"
    "- USER_INPUT: field_type (text | number | date).\n"
    # SEG.3 — la lista estaba escrita a mano y se quedó corta en cuanto entró `md_table`. Es la
    # tercera vez que pasa (tipos de gráfico y operaciones de ETL en GUI.3): sale del contrato.
    f"- DETERMINISTIC_DATA: source_pipeline ({' | '.join(get_args(ExtractionSourceKind))}).\n"
    # INF.5 — el mismo repaso que a `data_block_refs`: nombrar los kinds y decir qué **no**
    # vale. El validador comprueba las tres referencias con la misma regla, así que las tres
    # tienen que describirse igual; una referencia inventada deja el bloque sin datos en
    # ejecución y sin nada que explique por qué.
    "- DATA_TRANSFORM: config with source_block_ref ({\"block_id\": \"<id>\"}) — again the id of"
    " a DETERMINISTIC_DATA or DATA_TRANSFORM block, never a TABLE or a CHART — plus EITHER"
    ' mode="deterministic" and operations (a list, see the catalogue below), OR mode="ai" and'
    " nl_instruction (what to do, in words). Prefer deterministic when you can express it.\n"
    "- TABLE: data_block_ref — the id of a DETERMINISTIC_DATA or DATA_TRANSFORM block in this"
    " same template. Never another TABLE or a CHART: a presentation cannot feed another"
    " presentation.\n"
    "- CHART: data_block_ref (same rule as TABLE), and optionally config with chart_type"
    f" ({' | '.join(get_args(TipoDeGrafico))}), title, x_label, y_label, show_values, sort"
    " (none | asc | desc). x_axis is the column on the X axis and y_axis the one on the Y axis,"
    " exactly as their labels say: for a plain bar chart the category goes in x_axis, and for"
    " barh (horizontal bars, use it when the category names are long) the category goes in"
    " y_axis and the number in x_axis.\n"
    "- AI_ASSISTED_TEXT, AI_SUMMARY, AI_REWRITE: ai_prompt_template_id and review_policy_id."
    " Use 'required' as review_policy_id unless the request says otherwise, and pick the"
    f" instruction: '{PROMPT_VALORACION_DE_TENDENCIA}' to comment on the trend of ONE table,"
    f" '{PROMPT_RESUMEN_DE_RESULTADOS}' to summarise several, 'generic_report_v1' for anything"
    " else.\n"
    # SEG.1 — sin esto el modelo nunca ancla, y una valoración que recibe las treinta tablas del
    # informe mezcla y omite. Es lo que hizo fracasar el intento anterior con una gema.
    #
    # INF.5 — y decía «the table or tables this passage is about», que es exactamente lo que
    # induce el error: para el modelo la «tabla» del informe es el bloque TABLE, y el validador
    # exige el bloque que **produce** los datos. En las pruebas del 2026-08-20 el modelo ancló
    # la valoración al TABLE y al CHART, y la pantalla se quedó con dos errores rojos y el botón
    # de aprobar deshabilitado, sin forma de corregirlo.
    "  **data_block_refs** (list of block ids): the ids of the blocks that PRODUCE the data this"
    " passage comments on — a DETERMINISTIC_DATA or a DATA_TRANSFORM block. **Never** the id of"
    " a TABLE or a CHART: those are presentations of data that already exists somewhere else,"
    " they hold no data of their own, and pointing a passage at one is rejected. USE IT. A"
    " passage that comments on one dataset must reference that dataset and no other: giving the"
    " model every table of the report produces a blended summary that leaves things out. One AI"
    " block per dataset is the normal shape for a monitoring report.\n"
    "  Example of the correct shape — the passage points at the data block, not at the table"
    " that draws it:\n"
    '    {"kind": "DETERMINISTIC_DATA", "id": "d_saldos", ...}\n'
    '    {"kind": "TABLE", "id": "t_saldos", "data_block_ref": "d_saldos", ...}\n'
    '    {"kind": "AI_SUMMARY", "id": "v_saldos", "data_block_refs": ["d_saldos"], ...}\n'
    '  Wrong: "data_block_refs": ["t_saldos"] — that is the table, not the data.\n'
    "- CITATION_BLOCK: source_block_refs (list of block ids).\n"
    "- REVIEW_GATE: review_policy_id.\n"
    "A TABLE or CHART without a data block to point at is invalid: add the data block first.\n"
    # Es el fallo silencioso de PRO.9: sumar texto no da error, da una cifra mal. Si el prompt
    # no lo dice, el modelo pondrá el groupby y no la conversión.
    "When a spreadsheet holds amounts written as text (\"1.234,56 EUR\" is how applications"
    " here export them), any sum or group-by over that column is WRONG WITHOUT AN ERROR."
    " Put a DATA_TRANSFORM with to_number first, before any calculation.\n"
    "Catalogue of operations for DATA_TRANSFORM (use these and no others):\n"
    f"{catalogo_de_operaciones()}\n"
    # Sin esto, `DraftValidator` devuelve ok=False en toda propuesta con IA y el botón de
    # aprobar —que exige ok=true— no se habilita nunca. Es decir: la pantalla entera era
    # inutilizable para el caso normal.
    "If the template has ANY of AI_ASSISTED_TEXT, AI_SUMMARY or AI_REWRITE, it MUST also"
    " include one REVIEW_GATE block: a human approves the AI text before the report is"
    " assembled.\n"
    # Igual que con los bloques: enumerar `required_slots` sin decir cómo es un slot
    # producía `{'id': ..., 'block_ref': ...}` y un 422 en cada propuesta con datos.
    "Each entry of proposed_inputs.required_slots / optional_slots is:\n"
    '  {"slot_id": "budget_data", "kind": "excel",'
    ' "label": {"es": "...", "ca": "...", "en": "..."}}\n'
    f"kind is one of: {' | '.join(get_args(InputSlotKind))}. `label` is an object"
    " with the three languages, never a plain string. Do not add fields like `id` or"
    " `block_ref`: a slot does not point at a block; a DETERMINISTIC_DATA block declares"
    " which pipeline reads it.\n"
    )


class PropuestaInvalidaError(ValueError):
    """El modelo devolvió una estructura que el contrato de plantilla no acepta.

    Es un fallo **del modelo**, no del servidor: sale como error de dominio para que el
    router lo traduzca a 422 en vez de dejar una traza de pydantic en el log y un 500 en la
    pantalla de quien solo pidió un informe con una tabla.
    """


def _build_system_prompt(owner_kind: Literal["admin", "user"]) -> str:
    admin_note = ""
    if owner_kind == "admin":
        admin_note = (
            "\n- You are acting as a platform administrator. "
            "You may suggest is_global=true for templates intended for all users."
        )

    return (
        "You are an expert at designing report templates for government and academic institutions.\n"
        "Given a natural language description, return a JSON object with EXACTLY this structure:\n"
        "{\n"
        '  "proposed_profile": "<one of: GENERIC_REPORT, ANNUAL_REPORT, DOCTORATE_PROGRAM_REPORT,'
        ' CONTRACT_REPORT, FREEFORM_MEMO>",\n'
        '  "proposed_sections": [{"id": "s1", "title": "...", "order": 1, "block_ids": ["b1"]}],\n'
        '  "proposed_blocks": [{"kind": "STATIC_TEXT", "id": "b1", "title": "..."}],\n'
        '  "proposed_inputs": {"required_slots": [], "optional_slots": []},\n'
        '  "rationale": "Why this structure fits the request."\n'
        "}\n"
        f"Valid 'kind' values for blocks: {_BLOCK_KINDS}.\n"
        "Do NOT use any block kind not in this list.\n"
        # SEG.5 — la vista previa y el ensamblado recorren las secciones. Un bloque que
        # ninguna sección enumera se ejecuta y no sale en el informe, y eso no daba error:
        # el informe salía con las secciones vacías y aspecto de estar bien.
        "EVERY block id you create MUST appear in the block_ids of exactly one section, in "
        "the order it should be printed. A block listed by no section does not appear in the "
        "report at all.\n"
        # Enumerar los tipos sin decir qué exige cada uno producía propuestas que no
        # validaban y salían como 500. Visto en la primera petición real (VER.3): un bloque
        # TABLE sin `data_block_ref`, que es obligatorio.
        + _campos_obligatorios()
        + _esquema_del_contrato()
        + "Respond ONLY with valid JSON — no markdown, no explanation.\n"
        # GUI.6 — el `rationale` se le muestra a la persona que pidió el informe, así que salía
        # en inglés en una pantalla institucional en castellano. Los títulos de sección sí
        # llegaban en el idioma de la petición; el razonamiento, no.
        + "Write `rationale` and all section/block titles in the SAME LANGUAGE as the request."
        + admin_note
    )


@lru_cache(maxsize=1)
def _esquema_del_contrato() -> str:
    """El JSON Schema real de las tres piezas que el modelo tiene que producir.

    Describir el contrato a mano fue un juego del topo: faltaba `data_block_ref`, luego el
    `REVIEW_GATE`, luego la forma de `InputSlot`, luego el título de sección llegaba como
    diccionario i18n. El contrato lo conoce pydantic, así que se lo damos tal cual y deja de
    adivinarse. `lru_cache` porque generarlo cuesta y no cambia en caliente.
    """
    esquema = {
        "proposed_sections": TypeAdapter(list[SectionContract]).json_schema(),
        "proposed_blocks": TypeAdapter(list[BlockContract]).json_schema(),
        "proposed_inputs": TypeAdapter(InputContract).json_schema(),
    }
    return (
        "The exact JSON Schema of these three fields follows. It is authoritative: any field"
        " name or type not in it will be rejected.\n"
        + json.dumps(esquema, ensure_ascii=False)
        + "\n"
    )


# AIS.3 — la definición se fue a `core/llm_json.py`. Era una función privada de este fichero de
# la que tiraba `modules/curation/semantic_detector.py`, o sea el único import módulo→módulo sin
# justificación: no es que curación necesitara algo de Informes, es que la utilidad estaba en el
# sitio equivocado. Se conserva el nombre local porque es el que usa el resto del fichero.
from server.app.core.llm_json import extraer_json as _extract_json  # noqa: E402

#: Un solo reintento: si la segunda tampoco valida, el problema no es de forma.
INTENTOS_DE_PROPUESTA = 2

_REINTENTO = (
    "Your previous answer did not validate against the schema. Fix EXACTLY this and return"
    " the whole JSON again:\n{error}"
)


class LLMSpecService:
    """Servicio de especificación de plantillas vía LLM. Sin acceso a BD."""

    def __init__(self, llm: Any, model_name: str, prompt_version: str = PROMPT_VERSION) -> None:
        self._llm = llm
        self._model_name = model_name
        self._prompt_version = prompt_version

    async def _proponer(self, messages: list[dict]) -> dict:
        """Una vuelta: pide, extrae el JSON y comprueba que las tres piezas validan.

        La validación va aquí y no en el llamador para que el reintento pueda usar el error
        como respuesta al modelo; devolver el dict ya comprobado deja al llamador con la
        construcción del borrador y nada más.
        """
        respuesta = await self._llm.ainvoke(messages)
        raw = texto_de(respuesta)
        try:
            data = json.loads(_extract_json(raw))
        except json.JSONDecodeError as fallo:
            raise PropuestaInvalidaError(f"la respuesta no es JSON: {fallo}") from fallo

        try:
            [SectionContract(**s) for s in data.get("proposed_sections", [])]
            [_BLOCK_ADAPTER.validate_python(b) for b in data.get("proposed_blocks", [])]
            InputContract(
                **data.get("proposed_inputs", {"required_slots": [], "optional_slots": []})
            )
        except Exception as fallo:  # noqa: BLE001 — pydantic levanta varios tipos
            raise PropuestaInvalidaError(str(fallo)) from fallo
        return data

    async def propose_template(
        self,
        prompt_nl: str,
        owner_kind: Literal["admin", "user"],
        muestra: "MuestraDeDatos | None" = None,
    ) -> ReportTemplateDraft:
        messages = [
            {"role": "system", "content": _build_system_prompt(owner_kind)},
            {"role": "user", "content": prompt_nl},
        ]

        # INF.4 — la estructura del fichero, si quien pide el informe la aportó. Sin esto el
        # modelo adivina los nombres de las columnas, y en las pruebas del 2026-08-20 adivinó
        # mal. Los valores ya vienen anonimizados de `muestra_de_datos`.
        if muestra is not None:
            messages.append({"role": "user", "content": _contexto_de_la_muestra(muestra)})

        # Un reintento con el error como respuesta, igual que `etl_factory`: la mayoría de
        # estos fallos son de forma y el modelo los corrige en cuanto se le dice cuál es,
        # sin que quien pidió el informe tenga que reformular su petición.
        ultimo_fallo: str | None = None
        for intento in range(INTENTOS_DE_PROPUESTA):
            if ultimo_fallo is not None:
                messages = messages + [
                    {"role": "user", "content": _REINTENTO.format(error=ultimo_fallo)}
                ]
            try:
                data = await self._proponer(messages)
                break
            except PropuestaInvalidaError as fallo:
                ultimo_fallo = str(fallo)
                if intento == INTENTOS_DE_PROPUESTA - 1:
                    raise

        sections = [SectionContract(**s) for s in data.get("proposed_sections", [])]
        blocks = [_BLOCK_ADAPTER.validate_python(b) for b in data.get("proposed_blocks", [])]
        inputs = InputContract(
            **data.get("proposed_inputs", {"required_slots": [], "optional_slots": []})
        )

        return ReportTemplateDraft(
            proposed_profile=data.get("proposed_profile", "GENERIC_REPORT"),
            proposed_sections=sections,
            proposed_blocks=blocks,
            proposed_inputs=inputs,
            rationale=data.get("rationale", ""),
            model_used=self._model_name,
            prompt_version=self._prompt_version,
        )


def _contexto_de_la_muestra(muestra: "MuestraDeDatos") -> str:
    """La estructura del fichero, en el formato que usaba `etl_factory` en el legacy.

    Tres cosas que este texto tiene que dejar claras, y las tres salieron de ver fallar la
    propuesta del usuario:

    - **Las columnas listadas son las que existen.** Sin decirlo, el modelo completa con
      campos plausibles que no están en el fichero, y el informe falla al extraer.
    - **El tipo importa.** Si `saldo` sale como `str` (`object` antes de pandas 3), los importes vienen como texto y hay
      que convertirlos antes de sumar; el prompt del sistema ya avisa de que sumar texto da una
      cifra mal sin error.
    - **Los valores son de ejemplo y están anonimizados**, para que el modelo no los tome como
      datos reales ni los repita en el informe.
    """
    import json

    columnas = ", ".join(muestra.columnas)
    tipos = json.dumps(muestra.tipos, ensure_ascii=False, indent=2)
    filas = json.dumps(muestra.primeras_filas, ensure_ascii=False, indent=2, default=str)

    return (
        f"## The data file the report is about\n"
        f"File: {muestra.nombre_del_fichero}\n"
        f"Rows: {muestra.filas_totales}\n"
        f"Columns: {columnas}\n"
        f"Inferred types:\n{tipos}\n"
        f"First {len(muestra.primeras_filas)} rows (values anonymised, use them only to see the"
        f" shape of the data):\n{filas}\n"
        f"\nThese are the **only columns** that exist. Do not invent column names: a block that"
        f" reads a column which is not in this list fails at extraction time. If the report the"
        f" user asks for needs something that is not here, say so in a STATIC_TEXT block"
        f" instead of guessing.\n"
    )
