## BLOQUE 9R — Redacción Contract-First: ReportProfiles, UI Contracts y DraftingCoreGraph (Subfase 1.A → 1.C, PENDIENTE)

> Creado: 2026-05-11. Sustituye y amplía los prompts 9.11a–9.11d (conservados como referencia histórica tras el bloque).
> Referencia estratégica: `Rediseño_informes.md`.

### Propósito del bloque 9R

Reformular la subfase de Agentes de Redacción / Workspaces para que **no** sea un grafo monolítico con extracción, redacción IA y ensamblado, sino una **arquitectura contract-first extensible** análoga al bloque 9B (CoreGraph + Profiles + Factory + Contracts):

- `DraftingCoreGraph` común para todos los tipos de informe.
- `ReportProfiles` para especializar tipos de informe (incluye `GENERIC_REPORT` obligatorio para informes no predefinidos).
- `ReportTemplateContract`, `BlockContract`, `ReportUIContract` versionados y exportados por OpenAPI.
- `ExtractionPipelineFactory` para Excel/PDF/manual/scripts seguros (extracción determinista, no IA).
- `LLM-assisted Report Specification`: el LLM propone un `ReportTemplateDraft`, el humano valida y aprueba antes de persistir.
- `HITL por bloque` con máquina de estados explícita (`draft → extracted → ai_generated → needs_review → approved | rejected → locked`).
- `DraftingRunManifest` obligatorio para trazabilidad de cada ejecución.

### Decisiones de diseño

1. **No grafo monolítico**. El `DraftingCoreGraph` es común. La variación entre tipos de informe se resuelve por `ReportProfile`, no por `if/else` dentro del core.
2. **Contratos versionados**. El antiguo `config_hibrida JSON` desaparece. Se sustituye por `ReportTemplateContract` con `version_id`, schema validable y serialización OpenAPI.
3. **UI por contrato**. El frontend no tiene pantallas hardcoded por tipo de informe. Renderiza `ReportUIContract` con `react-hook-form` + `zodResolver` + tipos generados por Orval.
4. **LLM propone, humano aprueba**. El asistente LLM genera `ReportTemplateDraft` → validador estructural → vista previa editable → aprobación HITL → persistencia como plantilla o workspace ad hoc.
5. **Extracción determinista primero**. Excel/PDF se parsean con código (`pandas`, `pdfplumber`, `camelot`), nunca con LLM como mecanismo principal. Los scripts generados por IA son una extensión controlada (refactor de 9.11b con HITL + AST + auditoría IA).
6. **Estados de bloque explícitos**. Cada bloque tiene un estado en `{draft, missing_input, extracted, ai_generated, needs_review, approved, rejected, locked}`. Un bloque IA sin `approved` no entra en el documento final. Un bloque requerido sin datos bloquea el ensamblado.
7. **RunManifest obligatorio**. Ninguna exportación procede sin un `DraftingRunManifest` con `workspace_id`, `template_version_id`, `report_profile`, `uploaded_documents`, `input_validation`, `extracted_blocks`, `ai_blocks`, `model_used`, `prompt_versions`, `citations`, `warnings`, `user_approvals` y `final_document_hash`.
8. **Edge/Cloud**. Los módulos 9R son **edge** (procesan documentos/expedientes del cliente). Los routers se etiquetan `Deploy: edge` y no importan módulos cloud directamente.

### Diagrama del DraftingCoreGraph

```
LoadTemplateNode
  → ValidateInputContractNode
    → FileNormalizationNode
      → DeterministicExtractionNode    [Excel / PDFText / PDFTable / Manual / AdminScript]
        → DataQualityCheckNode
          → MissingDataQuestionNode    [HITL: solicita inputs faltantes]
            → AIAssistDraftNode         [LLM: solo con datos validados como contexto]
              → CitationAndTraceabilityNode
                → UserReviewGateNode    [HITL: aprueba/rechaza/regenera por bloque]
                  → ApplyUserEditsNode
                    → FinalAssemblerNode
                      → AuditLogNode    [emite DraftingRunManifest]
```

### Mapa de ejecución del bloque 9R

```
9R.0   (DOC)        Decisiones de arquitectura + nota en el plan

9R.1.1 (RED/GREEN)  ReportTemplateContract + ReportTemplateVersion (Pydantic + OpenAPI)
9R.1.2 (RED/GREEN)  InputContract + BlockContract + ReportUIContract
9R.1.3 (RED/GREEN)  WorkspaceState + BlockState + ReportTemplateDraft (runtime)
9R.1.4 (RED/GREEN)  Migración Alembic: hub_report_templates / hub_workspaces / hub_workspace_blocks / hub_run_manifests

9R.2.1 (RED/GREEN)  ReportProfile registry + GENERIC_REPORT como perfil obligatorio
9R.2.2 (RED/GREEN)  Estructura inicial de GENERIC_REPORT (secciones, bloques mínimos, inputs aceptados)

9R.3.1 (RED/GREEN)  Tipos de bloque (STATIC_TEXT, USER_INPUT, DETERMINISTIC_DATA, TABLE, CHART, AI_ASSISTED_TEXT, AI_SUMMARY, AI_REWRITE, CITATION_BLOCK, REVIEW_GATE)
9R.3.2 (RED/GREEN)  BlockState machine + reglas de transición + invariantes (AI sin approved no ensambla)
9R.3.3 (RED/GREEN)  Propagación de outputs entre bloques (BlockReference + projection) + orden topológico + detección de ciclos

9R.4.1 (RED/GREEN)  LLMSpecService: NL → ReportTemplateDraft
9R.4.2 (RED/GREEN)  Validador estructural + rechazo de drafts con tipos no permitidos
9R.4.3 (RED/GREEN)  Endpoints preview/approve + HITL (admin: plantilla; user: workspace ad hoc)
9R.4.4 (RED/GREEN)  Versionado de plantillas: política de anclaje y endpoints de migración de workspaces

9R.5.1 (RED/GREEN)  Protocolo ExtractionPipeline + contratos (Input/Result/Provenance/Warning)
9R.5.2 (RED/GREEN)  ExcelExtractionPipeline + PDFTextExtractionPipeline
9R.5.3 (RED/GREEN)  PDFTableExtractionPipeline + ManualInputPipeline
9R.5.4 (RED/GREEN)  ExtractionPipelineFactory + AdminScriptExtractionPipeline (motor de ejecución)
9R.5.5 (RED/GREEN)  ScriptProposalService + migración módulo anonimización (spaCy NER + Faker + regex + anclajes, desde client_app legacy) + endpoints propose/describe/anonymize/test/validate
9R.5.6 (RED/GREEN)  Workflow de aprobación scripts: self-service usuario / cola admin para plantillas globales
9R.5.7 (RED/GREEN)  Bloque CHART (modo determinista + IA) — migración de graphics_factory + deterministic_graphics_service legacy
9R.5.8 (RED/GREEN)  Bloque DATA_TRANSFORM (filter/aggregate/join/pivot/groupby) — migración de etl_service + deterministic_etl + etl_factory legacy
9R.5.9 (RED/GREEN)  Extractor Docling rico (ExtractedDocument: markdown + tables_json + páginas con bbox) — adelantado parcial de Fase 2 prompt 9.12b

9R.6.1 (RED/GREEN)  CoreGraph: LoadTemplate / ValidateInputContract / FileNormalization
9R.6.2 (RED/GREEN)  CoreGraph: DeterministicExtraction / DataQualityCheck / MissingDataQuestion
9R.6.3 (RED/GREEN)  CoreGraph: AIAssistDraft / CitationAndTraceability
9R.6.4 (RED/GREEN)  CoreGraph: UserReviewGate / ApplyUserEdits / FinalAssembler
9R.6.5 (RED/GREEN)  CoreGraph: AuditLog + emisión de DraftingRunManifest + instrumentación Langfuse
9R.6.6 (RED/GREEN)  CoreGraph: fallback paths + BlockState=failed + política de retry

9R.7.1 (RED/GREEN)  ReportUIContractRenderer + DynamicUploadSlots + DynamicFieldRenderer
9R.7.2 (RED/GREEN)  BlockEditor + AIBlockReviewPanel + DataQualityPanel + WorkspaceStatusBar
9R.7.3 (RED/GREEN)  ReportTemplateBuilderPage (admin) + GenericReportWizard (user)
9R.7.4 (RED/GREEN)  LLMDraftPreviewPage + flujo de aprobación
9R.7.5 (RED/GREEN)  UI scripts: ScriptProposalWizardPage + AdminScriptReviewQueuePage
9R.7.6 (RED/GREEN)  Simplificación de etiquetas de estado para usuario final + panel debug admin

9R.8.1 (RED/GREEN)  HITL endpoints + servicios de transición de bloques
9R.8.2 (RED/GREEN)  Tests E2E de edición/rechazo/regeneración por bloque

9R.9.1 (RED/GREEN)  DraftingRunManifest modelo Pydantic + repo + endpoint
9R.9.2 (RED/GREEN)  Integración con ExportService (1C.4) — DOCX-only en MVP

9R.10.1 (RED)       Vertical slice E2E: tests de aceptación
9R.10.2 (GREEN)     Wire-up integral del slice
```

### Reglas duras del bloque 9R

1. **No existe `config_hibrida JSON` libre**. Cualquier dato de configuración va en un `ReportTemplateContract` versionado.
2. **Los routers HTTP devuelven Pydantic ResponseModel específicos**. Nunca devolver modelos ORM directamente.
3. **El frontend usa exclusivamente tipos generados por Orval**. Está prohibido crear interfaces TypeScript manuales para DTOs de redacción.
4. **El LLM no puede crear plantillas persistentes sin aprobación HITL**. Solo genera `ReportTemplateDraft`.
5. **Ningún bloque IA entra al documento final sin estado `approved`**. El `UserReviewGateNode` bloquea el ensamblado.
6. **Toda ejecución del agente emite `DraftingRunManifest`**, incluso si falla. La exportación a DOCX (1C.4) requiere manifest válido. ODT queda fuera del MVP (backlog post-MVP, mantener abstracción `Exporter` para no rework).
7. **Módulos 9R son edge**. Routers etiquetados `Deploy: edge` (ver CLAUDE.md), no importan módulos cloud.
8. **TDD obligatorio**. RED antes que GREEN; ningún PR del bloque se acepta sin tests del nuevo contrato/comportamiento.

---

### 9R.0 — Decisiones de arquitectura (DOC, sin TDD)

```markdown
# 9R.0 — Documento de decisiones de arquitectura

Objetivo: dejar registrada en el repositorio la arquitectura objetivo del bloque 9R antes de empezar TDD.

Tareas:
1) Crear `docs/REDACCION_CONTRACT_FIRST.md` con:
   - Propósito del bloque.
   - Decisiones de diseño (1-8 listadas arriba).
   - Diagrama del DraftingCoreGraph (versión textual).
   - Mapa de ejecución 9R.1 → 9R.10.
   - Reglas duras del bloque.
   - Glosario: ReportProfile, ReportTemplateContract, BlockContract, ReportUIContract, BlockState, DraftingRunManifest, ReportTemplateDraft, ExtractionPipeline.

2) Añadir en `CLAUDE.md` un párrafo breve en la sección de Edge/Cloud aclarando que los nuevos módulos `modules/redaccion/` son edge.

3) Crear el esqueleto de carpetas (vacías) para que la estructura sea visible:
   - `server/app/modules/redaccion/`
   - `server/app/modules/redaccion/contracts/`
   - `server/app/modules/redaccion/profiles/`
   - `server/app/modules/redaccion/pipelines/`
   - `server/app/modules/redaccion/graph/`
   - `server/app/modules/redaccion/services/`
   - `frontend/src/redaccion/`

Criterio de done:
- El documento es legible y autosuficiente.
- Cualquier dev nuevo entiende qué hace el bloque 9R sin leer el plan completo.
```

---

### Prompt 9R.1.1 (RED/GREEN) — ReportTemplateContract + ReportTemplateVersion

```markdown
# PROMPT 9R.1.1 (RED/GREEN) — Contratos Pydantic de plantilla y versión

Objetivo: definir los contratos serializables de plantilla y versión, exportables por OpenAPI y consumibles por Orval.

Estructura (en server/app/modules/redaccion/contracts/):
- template.py        # ReportTemplateContract, ReportTemplateVersion
- __init__.py

ReportTemplateContract (mínimo):
- id: UUID
- name: str
- description: str | None
- report_profile: ReportProfileId   # Enum/Literal
- owner_kind: Literal["platform","organization","user"]
- owner_id: UUID | None
- is_global: bool
- current_version_id: UUID
- created_at: datetime
- updated_at: datetime

ReportTemplateVersion (mínimo):
- id: UUID
- template_id: UUID
- version: int
- spec: ReportTemplateSpec   # contiene sections, blocks, inputs, ui_contract
- created_at: datetime
- created_by: UUID

ReportTemplateSpec (mínimo):
- sections: list[SectionContract]
- blocks: list[BlockContract]   # referencia adelantada (9R.1.2)
- input_contract: InputContract # referencia adelantada (9R.1.2)
- ui_contract: ReportUIContract # referencia adelantada (9R.1.2)
- ai_block_policy: AIBlockPolicy
- review_policy: ReviewPolicy
- export_policy: ExportPolicy

Tests (RED → GREEN):
- test_report_template_contract_is_serializable_to_openapi
- test_report_template_version_requires_template_id
- test_report_template_spec_rejects_unknown_owner_kind
- test_report_template_version_is_immutable_once_persisted   # contrato: solo se versiona, nunca se edita
- test_report_template_exports_stable_schema_names           # ChatbotRead-style naming
- test_only_admin_can_create_global_template_contract

Criterio de done:
- `uv run python export_openapi.py` muestra los schemas ReportTemplateContract, ReportTemplateVersion, ReportTemplateSpec, SectionContract.
- Los nombres de schema son estables (no `ReportTemplateRead_v1__abc`).
- Tests verdes; sin código en routers todavía.
```

---

### Prompt 9R.1.2 (RED/GREEN) — InputContract + BlockContract + ReportUIContract

```markdown
# PROMPT 9R.1.2 (RED/GREEN) — Contratos de inputs, bloques y UI adaptativa

Objetivo: definir los contratos discriminados de bloque, los inputs aceptados por la plantilla y el contrato UI que el frontend renderizará dinámicamente.

Estructura (en server/app/modules/redaccion/contracts/):
- inputs.py     # InputContract, InputSlot
- blocks.py     # BlockContract (discriminated union), BlockKind enum
- ui.py         # ReportUIContract, UISection, UIFieldDescriptor, UIDropzoneDescriptor

InputContract (mínimo):
- required_slots: list[InputSlot]
- optional_slots: list[InputSlot]

InputSlot:
- slot_id: str
- kind: Literal["pdf","excel","csv","text","number","date","selector"]
- label: dict[str, str]      # i18n {es,ca,en}
- required: bool
- multiple: bool
- max_size_mb: int | None
- validation: dict | None    # regex, min/max, schema columnas Excel, etc.

BlockContract (discriminated union por `kind`):
- STATIC_TEXT, USER_INPUT, DETERMINISTIC_DATA, TABLE, CHART,
  AI_ASSISTED_TEXT, AI_SUMMARY, AI_REWRITE, CITATION_BLOCK, REVIEW_GATE
- Campos comunes: id, kind, title, required, depends_on (list[str]), order
- Campos específicos por kind: source_pipeline (para DETERMINISTIC_DATA),
  ai_prompt_template_id (para AI_*), data_block_ref (para CHART/TABLE),
  review_policy_id (para REVIEW_GATE)

ReportUIContract:
- wizard_steps: list[UISection]
- dropzones: list[UIDropzoneDescriptor]
- manual_fields: list[UIFieldDescriptor]
- block_editor_enabled: bool
- ai_review_panel_enabled: bool
- preview_layout: Literal["markdown","docx-like","split"]

Tests (RED → GREEN):
- test_block_contract_discriminator_by_kind
- test_ai_block_requires_review_policy_reference
- test_data_block_requires_source_pipeline
- test_chart_block_requires_data_block_ref
- test_table_block_requires_data_block_ref
- test_review_gate_block_requires_review_policy_id
- test_input_slot_excel_validates_required_columns_schema
- test_input_slot_pdf_accepts_max_size_mb
- test_ui_contract_renders_wizard_steps_in_order
- test_block_contract_is_serializable_and_appears_in_openapi
- test_unknown_block_kind_is_rejected

Criterio de done:
- Discriminated union de BlockContract aparece en openapi.json con `oneOf` y `discriminator: kind`.
- `npm run generate:api` produce tipos TypeScript discriminados (no `Block` genérico con `any`).
- Tests verdes.
```

---

### Prompt 9R.1.3 (RED/GREEN) — WorkspaceState + BlockState + ReportTemplateDraft

```markdown
# PROMPT 9R.1.3 (RED/GREEN) — Contratos de runtime: estado del workspace y draft LLM

Objetivo: definir el estado de runtime que circula por el DraftingCoreGraph y el contrato del draft propuesto por el asistente LLM.

Estructura (en server/app/modules/redaccion/contracts/):
- runtime.py    # WorkspaceState, BlockState, BlockStatus, WorkspaceStatus
- drafts.py     # ReportTemplateDraft, ReportTemplateDraftValidationResult

BlockStatus (Literal):
- "draft" | "missing_input" | "extracted" | "ai_generated" | "needs_review" | "approved" | "rejected" | "locked"

BlockState:
- block_id: str
- kind: BlockKind
- status: BlockStatus
- content: dict | None         # extracted data o ai text
- citations: list[Citation] | None
- last_updated_by: Literal["system","user","ai"]
- updated_at: datetime
- approval: ApprovalRecord | None

WorkspaceStatus (Literal):
- "draft" | "ingesting" | "extracting" | "drafting" | "in_review" | "assembled" | "exported" | "error"

WorkspaceState:
- workspace_id: UUID
- template_version_id: UUID
- report_profile: ReportProfileId
- inputs: dict[str, InputArtifact]    # por slot_id
- blocks: dict[str, BlockState]
- status: WorkspaceStatus
- warnings: list[ExtractionWarning]
- run_manifest_id: UUID | None

ReportTemplateDraft (lo que devuelve el LLM):
- proposed_profile: ReportProfileId
- proposed_sections: list[SectionContract]
- proposed_blocks: list[BlockContract]
- proposed_inputs: InputContract
- rationale: str            # explicación del LLM
- model_used: str
- prompt_version: str

ReportTemplateDraftValidationResult:
- ok: bool
- normalized_draft: ReportTemplateDraft | None
- errors: list[ValidationError]

Tests (RED → GREEN):
- test_workspace_state_serializes_with_block_status
- test_block_state_status_transition_valid_paths
- test_block_state_rejects_invalid_status_transition     # draft → approved (sin pasar por needs_review) → rechazar
- test_report_template_draft_includes_model_and_prompt_version
- test_invalid_draft_returns_normalized_errors

Criterio de done:
- BlockStatus expuesto en OpenAPI como enum.
- Las transiciones inválidas levantan `InvalidBlockTransitionError`.
- Tests verdes.
```

---

### Prompt 9R.1.4 (RED/GREEN) — Migración Alembic + repos

```markdown
# PROMPT 9R.1.4 (RED/GREEN) — Tablas hub_report_templates / hub_workspaces / hub_workspace_blocks / hub_run_manifests

Objetivo: crear la capa de persistencia. Los contratos Pydantic son la fuente de verdad — los modelos ORM no se exponen al exterior.

Tablas (HubOperationalBase — edge, ver CLAUDE.md):
- hub_report_templates (id, name, description, report_profile, owner_kind, owner_id, is_global, current_version_id, created_at, updated_at)
- hub_report_template_versions (id, template_id FK, version, spec_json JSONB, created_at, created_by)
- hub_workspaces (id, template_version_id FK, owner_id, status, inputs_json JSONB, warnings_json JSONB, run_manifest_id FK nullable, created_at, updated_at)
- hub_workspace_blocks (id, workspace_id FK, block_id, kind, status, content_json JSONB, citations_json JSONB, approval_json JSONB, updated_at)
- hub_run_manifests (id, workspace_id FK, template_version_id FK, report_profile, payload_json JSONB, final_document_hash str, created_at)

Reglas:
- `hub_report_template_versions` es append-only. No hay UPDATE — solo nuevas versiones.
- `hub_workspace_blocks` tiene constraint UNIQUE(workspace_id, block_id).
- `hub_run_manifests.final_document_hash` se completa solo al ensamblar.
- Sin `relationship()` cross-base (HubConfigBase ↔ HubOperationalBase prohibido).

Tests (RED → GREEN):
- test_alembic_upgrade_head_creates_new_tables
- test_alembic_downgrade_removes_new_tables_cleanly
- test_template_version_insert_only_no_update
- test_workspace_block_unique_per_workspace
- test_run_manifest_links_to_workspace_and_template_version

Aplicar:
- cd server && uv run alembic upgrade head
- alembic current confirma la nueva revisión

Criterio de done:
- Migración aplicada en BD local.
- Tests verdes.
- Repos `ReportTemplateRepo`, `WorkspaceRepo`, `WorkspaceBlockRepo`, `RunManifestRepo` exponen métodos `get`, `list`, `save`, `update_status`, sin lógica de negocio.
```

---

### Prompt 9R.2.1 (RED/GREEN) — ReportProfile registry + GENERIC_REPORT

```markdown
# PROMPT 9R.2.1 (RED/GREEN) — Registry de perfiles + perfil obligatorio GENERIC_REPORT

Objetivo: implementar el registry de perfiles análogo al de 9B (GraphProfileRegistry), con GENERIC_REPORT como perfil obligatorio.

Estructura (en server/app/modules/redaccion/profiles/):
- registry.py        # ReportProfileRegistry, ReportProfileId enum/Literal
- generic_report.py  # GenericReportProfile (perfil base)
- __init__.py        # registro automático

ReportProfileId (Literal):
- "GENERIC_REPORT" | "ANNUAL_REPORT" | "DOCTORATE_PROGRAM_REPORT" | "CONTRACT_REPORT" | "FREEFORM_MEMO"

ReportProfile (Protocol):
- profile_id: ReportProfileId
- def default_spec() -> ReportTemplateSpec
- def applicable_pipelines() -> list[ExtractionPipelineId]
- def review_policy() -> ReviewPolicy
- def ai_block_policy() -> AIBlockPolicy

ReportProfileRegistry:
- register(profile: ReportProfile)
- get(profile_id: ReportProfileId) -> ReportProfile
- list() -> list[ReportProfileId]
- contiene una entrada obligatoria GENERIC_REPORT al importarse el módulo (auto-register en __init__).

Tests (RED → GREEN):
- test_registry_contains_generic_report_after_import
- test_registry_rejects_duplicate_profile_id
- test_get_unknown_profile_raises
- test_generic_report_default_spec_is_valid_report_template_spec
- test_generic_report_applicable_pipelines_includes_excel_pdf_manual

Criterio de done:
- `from server.app.modules.redaccion.profiles import registry; registry.get("GENERIC_REPORT")` funciona sin error.
- GENERIC_REPORT no puede desregistrarse (constante de bloque).
- Tests verdes.
```

---

### Prompt 9R.2.2 (RED/GREEN) — Estructura inicial de GENERIC_REPORT

```markdown
# PROMPT 9R.2.2 (RED/GREEN) — Spec por defecto del perfil genérico

Objetivo: que GENERIC_REPORT proponga una estructura útil para informes no predefinidos.

Spec por defecto (`generic_report.default_spec()`):
- sections (orden y nombre):
  1. Título y datos de contexto       → STATIC_TEXT + USER_INPUT
  2. Objetivo del informe              → USER_INPUT
  3. Contexto                          → USER_INPUT + AI_REWRITE (asistido, opcional)
  4. Fuentes aportadas                 → DETERMINISTIC_DATA (referencia a inputs)
  5. Datos extraídos                   → DETERMINISTIC_DATA + TABLE/CHART
  6. Análisis asistido                 → AI_ASSISTED_TEXT (sobre datos validados, requiere REVIEW_GATE)
  7. Conclusiones                      → AI_SUMMARY (requiere REVIEW_GATE)
  8. Recomendaciones                   → USER_INPUT + AI_REWRITE (asistido, opcional)
  9. Anexos / fuentes                  → CITATION_BLOCK

- input_contract:
  - opcional Excel (slot_id="datos_excel", validation: cualquier hoja)
  - opcional PDF (slot_id="memoria_pdf")
  - opcional texto libre (slot_id="notas")

- ai_block_policy: requiere `needs_review` antes de `approved`; modelo Tier-1 con prompt versionado.

Tests (RED → GREEN):
- test_generic_report_profile_exists
- test_generic_report_default_spec_contains_nine_sections_in_order
- test_generic_report_accepts_manual_blocks
- test_generic_report_accepts_excel_and_pdf_inputs
- test_generic_report_requires_human_approval_for_ai_blocks
- test_generic_report_can_be_created_from_llm_draft   # placeholder, full test en 9R.4
- test_generic_report_generates_run_manifest_field    # placeholder, full test en 9R.9

Criterio de done:
- Crear workspace con `profile=GENERIC_REPORT` y plantilla por defecto genera 9 secciones esperadas.
- Todos los bloques AI están marcados `requires_review=True`.
- Tests verdes.
```

---

### Prompt 9R.3.1 (RED/GREEN) — Tipos de bloque y comportamiento por kind

```markdown
# PROMPT 9R.3.1 (RED/GREEN) — Implementar el comportamiento por tipo de bloque

Objetivo: para cada tipo de bloque, codificar inputs/outputs/dependencias/política IA/política HITL/render UI/trazabilidad.

Para cada kind en BlockKind, implementar en server/app/modules/redaccion/blocks/handlers/:
- propósito (docstring de clase)
- inputs aceptados (qué bloques o slots leen)
- outputs (estructura del content)
- puede ser required: bool
- puede depender de otros bloques: list[BlockKind]
- usa IA: bool
- requiere aprobación: bool
- render UI: dict[str, Any]  → consumido por ReportUIContract
- registro en RunManifest: dict (qué se serializa)

Handlers mínimos:

> **Retirados el 2026-09-28 (issue #180): de estos once sólo quedó `ChartHandler`.** Los otros
> diez nunca tuvieron quien los ejecutara —lo que atiende a cada tipo de bloque son los nodos
> del grafo— y ocho eran duplicados de un nodo que hace lo mismo y más. Las dos capacidades que
> sólo vivían aquí (el texto estático de la plantilla y el apartado de fuentes) se cablearon en
> los nodos antes de retirarlas. **No los vuelvas a crear**: la tabla de quién atiende cada tipo
> está en `test_issue180_los_handlers_que_nadie_montaba.py`.

- StaticTextHandler
- UserInputHandler
- DeterministicDataHandler  (delega en ExtractionPipeline)
- TableHandler              (consume DETERMINISTIC_DATA)
- ChartHandler              (consume DETERMINISTIC_DATA o TABLE)
- AIAssistedTextHandler
- AISummaryHandler
- AIRewriteHandler
- CitationBlockHandler
- ReviewGateHandler

Tests (RED → GREEN):
- test_block_contract_has_required_fields
- test_ai_block_requires_review_policy
- test_data_block_requires_extraction_source
- test_chart_block_depends_on_data_block
- test_review_gate_blocks_final_assembly_until_approved
- test_block_contract_is_serializable
- test_chart_handler_rejects_missing_data_block_ref
- test_ai_handler_records_model_and_prompt_version_to_manifest

Criterio de done:
- Cada handler implementa `validate(block)`, `execute(block, state)`, `to_manifest(block)`.
- Tests verdes (10/10).
- Documentación por handler (docstring estructurado).
```

---

### Prompt 9R.3.2 (RED/GREEN) — BlockState machine + invariantes

```markdown
# PROMPT 9R.3.2 (RED/GREEN) — Máquina de estados de bloque y reglas de transición

Objetivo: implementar una máquina de estados explícita para BlockStatus con transiciones permitidas y rechazo determinista de las prohibidas.

Estructura (en server/app/modules/redaccion/services/block_state_machine.py):
- BlockStateMachine.transition(block: BlockState, event: BlockTransitionEvent) -> BlockState
- Eventos: REQUEST_INPUT, EXTRACT, AI_GENERATE, REQUEST_REVIEW, APPROVE, REJECT, REGENERATE, LOCK

Tabla de transiciones (resumen):
- draft ─REQUEST_INPUT→ missing_input
- missing_input ─EXTRACT→ extracted
- draft ─EXTRACT→ extracted
- extracted ─AI_GENERATE→ ai_generated
- ai_generated ─REQUEST_REVIEW→ needs_review
- needs_review ─APPROVE→ approved
- needs_review ─REJECT→ rejected
- rejected ─REGENERATE→ ai_generated
- approved ─LOCK→ locked

Invariantes:
- Un bloque AI nunca pasa de `ai_generated` directo a `approved` sin `needs_review`.
- Un bloque `locked` no admite más transiciones.
- Un bloque `required` sin estado `approved`/`locked` bloquea el ensamblado.

Tests (RED → GREEN):
- test_block_state_machine_allows_extract_from_draft
- test_block_state_machine_blocks_direct_ai_to_approved
- test_block_state_machine_locked_block_is_terminal
- test_block_state_machine_rejected_block_can_regenerate
- test_final_assembler_blocks_when_required_block_not_approved
- test_block_transition_emits_audit_event

Criterio de done:
- Toda transición ilegal levanta `InvalidBlockTransitionError` con mensaje claro.
- Cada transición emite un evento auditable (`block_transition_audit`).
- Tests verdes (6/6).
```

---

### Prompt 9R.3.3 (RED/GREEN) — Propagación de outputs entre bloques + orden topológico

```markdown
# PROMPT 9R.3.3 (RED/GREEN) — BlockReference, projection y topología de ejecución

Objetivo: definir cómo el output de un bloque se convierte en input contextual de otro y garantizar que el CoreGraph ejecuta los bloques en orden topológico, rechazando ciclos en `depends_on`.

Refinamiento del contrato (en server/app/modules/redaccion/contracts/block_io.py):
- BlockReference (Pydantic):
    block_id: UUID
    projection: Literal["raw", "summary", "field"]
    field_path: str | None       # solo si projection="field"; dot+index notation tipo "rows[0].total"
- BlockContract.depends_on (refinado): list[BlockReference]    # antes era list[str]
- WorkspaceState.block_outputs: dict[UUID, dict]               # output serializable por block_id

Servicio (en server/app/modules/redaccion/services/block_topology.py):
- BlockTopology.sort(blocks: list[BlockContract]) -> list[BlockContract]
- BlockTopology.detect_cycles(blocks: list[BlockContract]) -> list[UUID]   # vacío si OK
- BlockTopology.resolve_inputs(state: WorkspaceState, block: BlockContract) -> dict[block_id, Any]
  - Aplica projection sobre cada `depends_on` para producir un dict listo para inyectar
  - "raw" → output completo
  - "summary" → output["summary"] si existe; si no, str(output)[:1000]
  - "field" → resuelve field_path con helper seguro (rechaza eval, accesos no atómicos)

Integración:
- 9R.4.2 (DraftValidator): rechazar ciclos en `depends_on` (404 con `loc` apuntando al bloque ofensor).
- 9R.6.2 (DeterministicExtractionNode): tras éxito escribe `state.block_outputs[block.id] = result.dict()`.
- 9R.6.3 (AIAssistDraftNode): antes de invocar el LLM construye contexto vía `BlockTopology.resolve_inputs`. NO accede directo a `state.raw_data_blocks`/`state.ai_draft_blocks`.
- 9R.3.2 (BlockState machine): un bloque no entra en `EXTRACT`/`AI_GENERATE` hasta que todos sus `depends_on` están en estado `approved` o `locked`. Para DETERMINISTIC consumido solo por otros DETERMINISTIC, también vale `extracted`.

Reglas duras:
- block_outputs es parte del estado del grafo y se persiste en `hub_workspaces.state_json` para reanudación.
- La projection "field" usa una helper estricta (`safe_field_resolver`) que solo acepta tokens dot y `[<int>]`. Cualquier otra cosa levanta `UnsafeFieldPathError`.
- Ningún nodo escribe block_outputs si su bloque no terminó en éxito.

Tests (RED → GREEN):
- test_block_reference_serializable_in_openapi_with_discriminator
- test_topology_sort_orders_blocks_by_dependencies
- test_topology_detect_cycle_returns_offending_block_ids
- test_draft_validator_rejects_cyclic_depends_on_with_422
- test_projection_raw_returns_full_output
- test_projection_summary_returns_summary_field_when_present
- test_projection_summary_falls_back_to_truncated_string_when_no_summary
- test_projection_field_resolves_dot_path
- test_projection_field_resolves_index_path
- test_projection_field_rejects_unsafe_expressions
- test_ai_node_reads_dependencies_via_projection_not_state
- test_block_blocked_until_dependencies_approved_or_locked
- test_block_outputs_persisted_to_workspace_state

Criterio de done:
- BlockReference aparece en openapi.json y Orval genera tipos.
- safe_field_resolver tiene cobertura ≥ 95 % de líneas (parsing crítico de seguridad).
- 13 tests verdes.
- Documentar en docs/REDACCION_CONTRACT_FIRST.md la sección "Propagación de outputs y topología".
```

---

### Prompt 9R.4.1 (RED/GREEN) — LLMSpecService: NL → ReportTemplateDraft

```markdown
# PROMPT 9R.4.1 (RED/GREEN) — Asistente LLM de especificación de informes

Objetivo: dado un texto en lenguaje natural, devolver un `ReportTemplateDraft` estructurado. El LLM NO ejecuta, NO persiste, NO escribe código.

Estructura (en server/app/modules/redaccion/services/llm_spec_service.py):
- LLMSpecService.propose_template(prompt_nl: str, owner_kind: Literal["admin","user"]) -> ReportTemplateDraft
- Internamente:
  1) Construir prompt con system message que liste los tipos de bloque permitidos.
  2) Llamar al LLM (Tier 1, model_factory).
  3) Parsear salida JSON (json_mode si el provider lo soporta, fallback con `pydantic.TypeAdapter`).
  4) Adjuntar `model_used`, `prompt_version`.

Reglas:
- El system prompt declara explícitamente los `BlockKind` válidos y rechaza `BlockKind` desconocidos en la respuesta.
- El servicio NO crea registros en BD. Solo devuelve el draft.
- El owner_kind se propaga al draft (afecta a quién verá el preview).

Tests (RED → GREEN):
- test_llm_spec_service_returns_report_template_draft   (mock LLM)
- test_llm_spec_service_records_model_used_and_prompt_version
- test_llm_spec_service_does_not_persist_anything
- test_llm_spec_service_respects_owner_kind            (admin → puede sugerir is_global=True)

Criterio de done:
- Servicio aislado, sin acceso a repos.
- Mock LLM en tests; el test real con LLM va en integración (`tests/integration/test_llm_spec_real.py`, opcional).
- Tests verdes.
```

---

### Prompt 9R.4.2 (RED/GREEN) — Validador estructural de ReportTemplateDraft

```markdown
# PROMPT 9R.4.2 (RED/GREEN) — Validador estructural y normalizador

Objetivo: validar que un `ReportTemplateDraft` propuesto por el LLM cumpla el contrato (BlockKind permitidos, dependencias resueltas, secciones bien formadas) y normalizarlo (orden de bloques, ids únicos).

Estructura (en server/app/modules/redaccion/services/draft_validator.py):
- DraftValidator.validate(draft: ReportTemplateDraft) -> ReportTemplateDraftValidationResult
- Comprueba:
  - profile_id pertenece al registry
  - todos los BlockKind son válidos
  - dependencias (`depends_on`) referencian bloques existentes
  - CHART/TABLE referencian un DETERMINISTIC_DATA presente
  - AI_* tienen ai_prompt_template_id resoluble (o usa default policy)
  - REVIEW_GATE existe si hay bloques AI
  - input_contract es coherente (slots referenciados por DETERMINISTIC_DATA existen)
- Normaliza:
  - asigna ids únicos a bloques que no los tengan
  - ordena bloques por section/order
  - devuelve `normalized_draft`

Tests (RED → GREEN):
- test_invalid_llm_draft_is_rejected
- test_unknown_block_type_is_rejected
- test_chart_without_data_block_is_rejected
- test_ai_block_without_review_gate_is_rejected
- test_draft_normalizer_assigns_unique_block_ids
- test_draft_normalizer_orders_blocks_by_section

Criterio de done:
- Validador determinista (mismo input → mismo output).
- Errors devueltos con `loc`, `msg`, `type` (compatible con FastAPI 422).
- Tests verdes.
```

---

### Prompt 9R.4.3 (RED/GREEN) — Endpoints preview/approve + HITL

```markdown
# PROMPT 9R.4.3 (RED/GREEN) — Endpoints HTTP para asistente LLM

Objetivo: exponer la generación de drafts, su preview y su aprobación (creando plantilla persistente o workspace ad hoc).

Endpoints (en server/app/routers/redaccion/llm_drafts_router.py — Deploy: edge):
- POST /api/v1/redaccion/llm-drafts/propose
  Request: { "prompt_nl": str, "mode": "admin_template" | "user_workspace" }
  Response: ReportTemplateDraft (sin persistir)
- POST /api/v1/redaccion/llm-drafts/validate
  Request: ReportTemplateDraft
  Response: ReportTemplateDraftValidationResult
- POST /api/v1/redaccion/llm-drafts/approve-as-template
  Request: { "draft": ReportTemplateDraft, "name": str, "is_global": bool }
  Solo rol admin/partner. Solo si is_global=True requiere admin.
  Response: ReportTemplateContract
- POST /api/v1/redaccion/llm-drafts/approve-as-workspace
  Request: { "draft": ReportTemplateDraft, "name": str }
  Cualquier usuario autenticado.
  Response: WorkspaceState

Reglas:
- approve-as-template solo crea plantillas. No crea workspace.
- approve-as-workspace crea plantilla privada (owner_kind=user) + workspace en estado `draft`.
- Ambos endpoints invocan DraftValidator antes de persistir; rechazan con 422 si invalid.

Tests (RED → GREEN):
- test_llm_draft_requires_human_approval_before_persisting
- test_admin_can_save_llm_draft_as_template
- test_non_admin_cannot_save_global_template
- test_user_can_use_llm_draft_as_private_workspace
- test_llm_draft_preview_contains_sections_blocks_and_inputs
- test_approve_endpoint_rejects_invalid_draft_with_422

Criterio de done:
- 4 endpoints registrados y documentados en OpenAPI.
- Tests verdes.
- Frontend (9R.7.4) podrá consumirlos vía Orval.
```

---

### Prompt 9R.4.4 (RED/GREEN) — Versionado de plantillas: política y migración de workspaces

```markdown
# PROMPT 9R.4.4 (RED/GREEN) — Política de anclaje y endpoints de migración

Objetivo: definir el comportamiento del sistema cuando se publica una nueva versión de un `ReportTemplate` que ya tiene workspaces vivos contra la versión anterior.

Política de producto (no negociable salvo cambio explícito):
- Un Workspace queda anclado a su `template_version_id` para siempre.
- Publicar vN+1 NO migra automáticamente workspaces existentes.
- El propietario del workspace ve un aviso "Plantilla actualizada — versión vN+1 disponible" en `WorkspaceStatusBar` (9R.7.2).
- La migración es un acto explícito del propietario: crea un workspace nuevo clonado contra vN+1, conservando solo los inputs originales (sin bloques approved). El workspace antiguo queda `archived` y permanece accesible para auditoría.

Servicio (en server/app/modules/redaccion/services/template_migration_service.py):
- TemplateMigrationService.detect_new_version(workspace_id) -> NewVersionNotice | None
    NewVersionNotice = { current_version_id, latest_version_id, changes_summary, breaking_changes }
- TemplateMigrationService.migrate_workspace(workspace_id, target_version_id, user_id) -> Workspace
    - Verifica compatibilidad de InputContract (mismos slots required obligatorios)
    - Crea workspace nuevo contra target_version_id, copia `inputs_json`, NO copia outputs ni approvals
    - Marca workspace antiguo: status="archived", archived_reason=f"migrated_to_{new_id}"
    - Setea workspace nuevo: parent_workspace_id apunta al antiguo
    - Devuelve nuevo workspace

Endpoints (Deploy: edge, hub_redaccion_router.py):
- GET  /api/v1/hub/redaccion/workspaces/{id}/template-update-notice
    Response 200: NewVersionNotice | 204 si workspace ya alineado
- POST /api/v1/hub/redaccion/workspaces/{id}/migrate
    Request: { "target_version_id": UUID }
    Response 201: { "new_workspace_id": UUID } | 409 con `compatibility_errors` si InputContract incompatible | 403 si no es owner

Migración Alembic:
- hub_workspaces.parent_workspace_id (UUID, FK a hub_workspaces.id, nullable)
- hub_workspaces.archived_reason (str, nullable)
- hub_workspaces.status: extender enum con "archived"

Reglas duras:
- Migrar NO borra el workspace antiguo (auditoría + RunManifest preservado).
- Solo `owner_id` puede invocar migrate. Misma policy que autosave 1C.1.
- Si target_version_id introduce un breaking change en InputContract (campo required nuevo), devolver 409 con `compatibility_errors: list[{ slot_id, reason }]`. El usuario debe rellenar los nuevos slots manualmente tras crear el workspace nuevo.

Tests (RED → GREEN):
- test_detect_new_version_returns_notice_when_template_has_newer_version
- test_detect_new_version_returns_none_when_workspace_aligned_to_latest
- test_migrate_creates_new_workspace_against_target_version
- test_migrate_preserves_inputs_json_verbatim
- test_migrate_does_not_copy_block_outputs_or_approvals
- test_migrate_archives_old_workspace_with_reason
- test_migrate_links_parent_workspace_id_in_new_workspace
- test_migrate_returns_409_when_input_contract_breaking_change
- test_migrate_requires_workspace_ownership
- test_migration_preserves_old_workspace_run_manifest

Criterio de done:
- Migración Alembic aplicada (3 columnas).
- 2 endpoints documentados en OpenAPI.
- 10 tests verdes.
- Documentar en docs/REDACCION_CONTRACT_FIRST.md la sección "Versionado de plantillas y migración de workspaces".
```

---

### Prompt 9R.5.1 (RED/GREEN) — Protocolo ExtractionPipeline + contratos

```markdown
# PROMPT 9R.5.1 (RED/GREEN) — Protocolos y contratos comunes de extracción

Objetivo: definir el contrato común que todo pipeline de extracción debe respetar, análogo al `RetrievalPipeline` de 9B.

Estructura (en server/app/modules/redaccion/pipelines/):
- contracts.py     # ExtractionPipeline (Protocol), ExtractionInput, ExtractionResult, ExtractedTable, ExtractedMetric, ExtractionWarning, ExtractionProvenance
- __init__.py

ExtractionInput:
- source_kind: Literal["excel","pdf_text","pdf_table","manual","admin_script"]
- file_ref: StorageRef | None     # ruta fsspec
- raw_text: str | None            # para manual
- options: dict                   # ej. {sheet: 0, header_row: 1}

ExtractionResult:
- tables: list[ExtractedTable]
- metrics: list[ExtractedMetric]
- free_text: str | None
- warnings: list[ExtractionWarning]
- provenance: ExtractionProvenance

ExtractionProvenance:
- pipeline_id: str
- source_ref: str            # storage key
- extracted_at: datetime
- column_mapping: dict | None
- pages: list[int] | None

ExtractionPipeline (Protocol):
- pipeline_id: ExtractionPipelineId
- def extract(input: ExtractionInput) -> ExtractionResult
- def supports(source_kind: str) -> bool

Tests (RED → GREEN):
- test_extraction_result_contains_provenance
- test_extraction_warning_has_severity_and_code
- test_extraction_pipeline_protocol_is_typing_protocol
- test_extraction_result_serializable_to_openapi

Criterio de done:
- Contratos en OpenAPI.
- Tests verdes.
- Sin implementación de pipelines concretos todavía (eso es 9R.5.2 / 9R.5.3 / 9R.5.4).
```

---

### Prompt 9R.5.2 (RED/GREEN) — ExcelExtractionPipeline + PDFTextExtractionPipeline

```markdown
# PROMPT 9R.5.2 (RED/GREEN) — Pipelines deterministas Excel y PDF-texto

Objetivo: implementar dos pipelines deterministas reales con datos de prueba.

Estructura (en server/app/modules/redaccion/pipelines/):
- excel_pipeline.py    # ExcelExtractionPipeline (pandas)
- pdf_text_pipeline.py # PDFTextExtractionPipeline (Docling, sin OCR, sin tablas)

ExcelExtractionPipeline:
- Lee con pandas (openpyxl backend).
- Soporta `sheet` y `header_row` en options.
- Valida columnas requeridas (si vienen en options.required_columns); emite ExtractionWarning si faltan.
- Devuelve ExtractedTable con `columns`, `rows`, `dtypes`.

PDFTextExtractionPipeline (versión MVP ligera):
- Usa Docling con `do_ocr=False`, `do_table_structure=False`, `do_picture_classification=False`.
- Extrae solo texto plano vía `export_to_text()`.
- Detecta PDFs no extractables (imagen sin capa de texto) → ExtractionWarning severity=error, code=NON_EXTRACTABLE_PDF.

> Nota (2026-05-13): la versión "rica" de este pipeline (markdown + tablas estructuradas + páginas) se entrega en **9R.5.9**, que amplía este pipeline aprovechando las capacidades completas de Docling. Esta versión queda como modo ligero/rápido para casos en que solo se necesita el texto.

Tests (RED → GREEN):
- test_excel_pipeline_reads_basic_table   (fixture: tests/fixtures/redaccion/sample.xlsx)
- test_excel_pipeline_reports_missing_required_columns
- test_excel_pipeline_handles_multiple_sheets
- test_pdf_text_pipeline_extracts_paragraphs
- test_pdf_pipeline_reports_non_extractable_pdf  (fixture: imagen-only PDF)
- test_excel_provenance_records_sheet_and_header_row

Criterio de done:
- Fixtures mínimas en tests/fixtures/redaccion/.
- pandas, docling añadidos a pyproject.toml (docling ya está, instalado para RAG).
- Tests verdes.
```

---

### Prompt 9R.5.3 (RED/GREEN) — PDFTableExtractionPipeline + ManualInputPipeline

```markdown
# PROMPT 9R.5.3 (RED/GREEN) — Tablas en PDF y entrada manual

Objetivo: añadir extracción de tablas PDF y normalización de entrada manual del usuario.

Estructura:
- pdf_table_pipeline.py # PDFTableExtractionPipeline (camelot o pdfplumber tables)
- manual_pipeline.py    # ManualInputPipeline

PDFTableExtractionPipeline:
- Intenta camelot lattice → fallback stream.
- Devuelve ExtractedTable por tabla detectada (con `page`).
- Si no detecta tablas → ExtractionWarning severity=warn, code=NO_TABLES_FOUND.

ManualInputPipeline:
- Convierte texto/números introducidos por el usuario en ExtractionResult mínima.
- No usa LLM. Solo normaliza tipos (parse_number, parse_date) y valida contra el InputSlot.

Tests (RED → GREEN):
- test_pdf_table_pipeline_detects_tables_with_camelot
- test_pdf_table_pipeline_warns_when_no_tables_found
- test_manual_pipeline_parses_numbers
- test_manual_pipeline_validates_required_slots
- test_manual_pipeline_rejects_wrong_type

Criterio de done:
- camelot-py añadido a deps (opcional: ghostscript en docker).
- Tests verdes.
```

---

### Prompt 9R.5.4 (RED/GREEN) — Factory + AdminScriptExtractionPipeline

```markdown
# PROMPT 9R.5.4 (RED/GREEN) — Factory y refactor del pipeline de scripts seguros

Objetivo: agrupar todos los pipelines en una factory selectiva por `source_kind`, y refactorizar el pipeline de scripts generados por IA del antiguo 9.11b para que sea uno más entre los pipelines.

Estructura:
- factory.py                # ExtractionPipelineFactory
- admin_script_pipeline.py  # AdminScriptExtractionPipeline (reusa ScriptSecurityAuditor)

ExtractionPipelineFactory:
- register(pipeline)
- get(source_kind) -> ExtractionPipeline
- list() -> list[ExtractionPipelineId]
- Auto-registra todos los pipelines al importar el paquete.

AdminScriptExtractionPipeline:
- Solo invocable por owner admin/partner del template.
- Recupera código aprobado (ya pasó AST + auditoría IA + aprobación HITL).
- Ejecuta el script en sandbox restringido (subproc con tiempo límite, pandas/json/math permitidos).
- Devuelve ExtractionResult.

Tests (RED → GREEN):
- test_factory_returns_pipeline_for_excel
- test_factory_returns_pipeline_for_pdf_text
- test_factory_returns_pipeline_for_pdf_table
- test_factory_returns_pipeline_for_manual
- test_factory_returns_pipeline_for_admin_script
- test_factory_rejects_unknown_source_type
- test_admin_script_pipeline_only_runs_approved_code
- test_admin_script_pipeline_blocks_unsafe_imports   (reusa tests de AST de 9.11b)

Criterio de done:
- ScriptSecurityAuditor de 9.11b migrado a `modules/redaccion/services/script_auditor.py` y reutilizado por AdminScriptExtractionPipeline.
- El endpoint `/agents/generate-script` queda dentro del flujo de creación de plantilla (no externo).
- Tests verdes (8/8).

Nota (2026-05-13): este prompt entrega solo el **motor de ejecución** (audit + sandbox). El **workflow de proposición LLM-asistido** (cualquier usuario propone, AST audit + sandbox test obligatorio, admin aprueba para plantillas globales) se cubre en 9R.5.5 + 9R.5.6 + 9R.7.5.
```

---

### Prompt 9R.5.5 (RED/GREEN) — ScriptProposalService + migración del módulo de anonimización (spaCy + Faker, desde legacy)

**Modelo sugerido**: **Opus** — migración masiva de 1011 LOC legacy + 14 tests con decisiones de diseño embebidas (qué preservar/descartar, adaptaciones async, contratos StorageRef).

```markdown
# PROMPT 9R.5.5 (RED/GREEN) — Workflow de proposición de scripts: motor backend con anonimización híbrida

Objetivo: permitir que cualquier usuario solicite a un LLM la generación de un script Python de extracción para su plantilla, validarlo automáticamente (AST audit + sandbox test obligatorio sobre datos reales o sintéticos) y dejarlo listo para persistir/promocionar. Este prompt entrega el motor backend completo, incluyendo la migración del módulo de anonimización legacy (spaCy NER + Faker + regex + anclajes de formulario), que ya estaba desarrollado y probado en client_app. Los endpoints de aprobación/persistencia llegan en 9R.5.6.

> **Avance respecto al plan original**: este prompt absorbe parte del trabajo previsto inicialmente para Fase 13 (NER). Se aprovecha el módulo legacy ya probado de `client_app/app/modules/privacy/` en lugar de reinventarlo. Fase 13 se reducirá a los hooks pre/post-LLM dentro del DraftingCoreGraph, reutilizando el `PiiDetector` que se construye aquí.

Deploy: edge

## Parte 1 — Migración del módulo de anonimización desde legacy

Fuente legacy (a migrar):
- `client_app/app/modules/privacy/anonymizer.py` (1011 líneas, motor core)
- `client_app/app/modules/privacy/anonymizer_service.py` (204 líneas, alto nivel xlsx/csv)
- `client_app/app/utils/pii_detector.py` (wrapper)
- `client_app/app/services/anonymization_service.py` (async wrapper + auditoría)
- Tests asociados en `client_app/tests/`: test_ner_anonymizer.py, test_anonymizer_patterns.py, test_anonymizer.py, test_anonymizer_extended.py, test_anonymizer_service.py, test_extraction_anonymization.py, test_etl_anonymization.py, test_custom_script_anonymization.py (los UI tests no se migran — los reemplaza 9R.7.5).

Destino:
- `server/app/modules/redaccion/services/anonymization/`
  - `__init__.py`
  - `pii_detector.py`            # PiiDetector (regex + spaCy NER + anclajes)
  - `faker_generator.py`         # FakerGenerator con contexto (firstname/lastname/fullname)
  - `anonymizer.py`              # AnonymizationContext (motor)
  - `service.py`                 # AnonymizerService (alto nivel async)
  - `policies.py`                # Strategies predefinidas (NER_PERSON→FAKE_NAME, EMAIL→TOKEN, DNI→CODE, AEPD/LOPDGDD)
- `server/tests/modules/redaccion/anonymization/` (tests migrados, adaptados a async)

Adaptaciones obligatorias durante la migración:
1. **Reemplazar `file_path: str` por `file_ref: StorageRef`** en todas las firmas públicas. Internamente usar StorageService para descargar antes de procesar.
2. **Hacer async** los puntos de E/S (descarga, subida). El motor de detección/sustitución puede seguir síncrono (CPU-bound).
3. **Eliminar dependencia de `EncryptionService`** para persistencia cifrada en disco — no se necesita en MVP de scripts (la determinismo se obtiene con `Faker(seed=hash(file_path))` por proposal). Mantener la API `save_state/load_state` pero como no-op opcional, marcada `# TODO post-MVP: persistencia de auditoría`.
4. **Quitar la integración con `enterprise_audit_service`** del legacy — se reemplaza por el audit log nativo del módulo redacción (HubWorkspaceAuditEvent existente desde 9R.8.1).
5. **Mantener Disposición 7ª LOPDGDD** (`anonymize_document_id`) — útil para despliegues en sector público español.
6. **Mantener fallback sin spaCy** — si el modelo no carga, degrada a solo regex con warning explícito en el audit_result devuelto al usuario.

Dependencias nuevas en pyproject.toml:
- `spacy>=3.7`
- `faker>=22.0` (probablemente ya esté)
- En Dockerfile (server): `RUN python -m spacy download es_core_news_md && python -m spacy download en_core_web_md` durante el build.

## Parte 2 — TestDataAnonymizerService (envoltura sobre el módulo migrado)

`server/app/modules/redaccion/services/test_data_anonymizer.py`:

Métodos públicos:
- `describe_columns(file_ref: StorageRef) -> ColumnInfo[]`
  - Solo aplica a XLSX/CSV.
  - Para cada columna: ejecuta `PiiDetector` sobre los primeros 50 valores no nulos.
  - Combina con heurística por nombre de columna ("nombre", "apellido", "email", "iban", "dni"…).
  - Devuelve `ColumnInfo(name, sample_values, inferred_faker_provider, confidence)`.
- `anonymize_tabular(file_ref, substitutions: list[ColumnSubstitution]) -> StorageRef`
  - Aplica el FakerGenerator del módulo migrado, fila a fila.
  - Devuelve referencia al archivo sintético en storage.
- `anonymize_pdf_to_text(file_ref: StorageRef) -> StorageRef`
  - Pipeline: Docling → markdown → `AnonymizationContext.anonymize()` sobre el texto completo → guarda `.md` sintético en storage.
  - **Opción 1 confirmada**: no regenera PDF. El admin lo verá como markdown plano. Justificación: el pipeline de scripts trabaja sobre `raw_text` extraído por Docling, regenerar el PDF añadiría coste sin valor.
- `preview_pdf_spans(file_ref: StorageRef) -> PiiSpan[]`
  - Para la UI: devuelve los spans detectados con `{start, end, type, original_text, suggested_fake}` para que el usuario revise antes de aplicar.

ColumnSubstitution:
```python
class ColumnSubstitution(BaseModel):
    column_name: str
    faker_provider: Literal[
        "keep", "name", "first_name", "last_name", "email", "phone",
        "iban", "dni", "nie", "address", "city", "company", "date", "integer"
    ]
```

## Parte 3 — ScriptProposalService

`server/app/modules/redaccion/services/script_proposal_service.py`:

- Constructor: `(llm_service, script_auditor: ScriptSecurityAuditor)` — reutiliza el auditor de 9R.5.4.
- `propose(prompt_nl, sample_schema, owner_kind) -> ProposalResult`:
  - System prompt acotado (lista blanca de imports = WHITELIST_MODULES de 9R.5.4; contrato de salida `result: dict`; variables disponibles `file_path/raw_text/options`).
  - Few-shot: al menos 1 ejemplo Excel + 1 ejemplo PDF text + 1 ejemplo de agregación con pandas.
  - Ejecuta `script_auditor.audit(code)` y devuelve `{code, audit_result}`.
  - **No persiste** — el guardado lo hace el endpoint.

## Parte 4 — Persistencia

`HubScriptProposal` (ORM, sobre HubOperationalBase):
- id: UUID PK
- proposer_user_id: UUID
- target_owner_kind: str  # 'user' | 'platform'
- target_template_id: UUID | None
- prompt_nl: text
- code: text
- audit_result_json: JSONB
- test_data_ref: JSONB | null         # StorageRef serializado, null hasta el primer /test
- test_data_is_anonymized: bool
- test_data_anonymization_map: JSONB | null    # {columns: [...], spans: [...]} según tipo
- test_data_kind: str | null          # 'xlsx' | 'csv' | 'pdf_text'
- test_result_json: JSONB | null
- test_result_hash: str | null        # sha256 hex
- test_validated_by_proposer_at: timestamp | null
- status: str   # proposed | tested | rejected (los de aprobación llegan en 9R.5.6)
- created_at, updated_at

Migración Alembic: tabla `hub_script_proposals` + FKs a hub_users.

## Parte 5 — Endpoints

Router: `server/app/routers/redaccion/scripts_router.py` (Deploy: edge, registrado en `_register_edge`).

- `POST /api/v1/redaccion/scripts/propose`
  - Body: `{prompt_nl, target_owner_kind, target_template_id?, sample_schema?}`
  - Crea HubScriptProposal status='proposed', devuelve `{proposal_id, code, audit_result}`.

- `POST /api/v1/redaccion/scripts/{proposal_id}/describe-test-data`
  - Body: multipart con archivo XLSX/CSV.
  - Sube a storage. Llama `describe_columns()`. Devuelve sugerencias de Faker provider por columna.

- `POST /api/v1/redaccion/scripts/{proposal_id}/preview-pdf-spans`
  - Body: multipart con PDF.
  - Sube a storage. Llama `preview_pdf_spans()`. Devuelve los PiiSpan detectados.

- `POST /api/v1/redaccion/scripts/{proposal_id}/anonymize-test-data`
  - Body: `{file_ref, kind: 'xlsx'|'csv'|'pdf_text', substitutions?, span_overrides?}`
  - Tabular: aplica `anonymize_tabular`. PDF: aplica `anonymize_pdf_to_text` (con overrides del usuario sobre los spans detectados).
  - Devuelve `{synthetic_ref, anonymization_map}`.

- `POST /api/v1/redaccion/scripts/{proposal_id}/test`
  - Body: `{test_data_ref, use_real_data: bool}`.
  - Si `target_owner_kind='platform'` → `use_real_data` DEBE ser false (422 si true: `REAL_DATA_NOT_ALLOWED_FOR_PLATFORM_TARGET`).
  - Ejecuta exactamente el mismo `_execute_in_sandbox` de `AdminScriptExtractionPipeline` (no duplicar lógica).
  - Captura ExtractionResult, calcula sha256 del JSON, guarda en BD, status proposed→tested.
  - Devuelve `{result, hash}`.

- `POST /api/v1/redaccion/scripts/{proposal_id}/validate-test-result`
  - Solo el proposer. Marca `test_validated_by_proposer_at=now`. 422 si no hay test_result_json todavía.

## Tests (RED → GREEN)

Anonimización (migrados/adaptados del legacy):
- test_pii_detector_identifies_persons_with_ner
- test_pii_detector_identifies_dni_nif_with_regex
- test_pii_detector_identifies_iban_with_regex
- test_pii_detector_uses_form_anchors_for_field_context
- test_pii_detector_degrades_to_regex_only_without_spacy
- test_faker_generator_is_deterministic_per_value
- test_faker_generator_uses_lastname_after_firstname_anchor
- test_anonymizer_handles_aepd_disposicion_septima_for_dni
- test_anonymize_tabular_preserves_row_count
- test_anonymize_pdf_to_text_returns_markdown_with_substituted_spans
- test_anonymize_pdf_to_text_preserves_non_pii_content_verbatim

Workflow (nuevos):
- test_propose_generates_code_and_audit_result
- test_propose_rejects_when_llm_outputs_forbidden_import (mocked LLM)
- test_describe_test_data_suggests_iban_provider_for_iban_column
- test_test_endpoint_requires_anonymized_data_for_platform_target
- test_test_endpoint_executes_in_same_sandbox_as_admin_pipeline
- test_test_endpoint_stores_result_hash
- test_validate_test_result_requires_prior_test
- test_validate_test_result_marks_proposer_validation_timestamp

## Criterio de done

- ≥19 tests verdes (11 anonimización + 8 workflow).
- Migración Alembic aplicada (`hub_script_proposals`).
- Endpoints registrados en main.py bajo `_register_edge`.
- `PiiDetector` queda como módulo independiente (lo reutilizará Fase 13 NER para los hooks pre/post-LLM).
- spaCy `es_core_news_md` y `en_core_web_md` descargados en el build de Docker.
- Documentación: añadir sección "Módulo de anonimización" a `docs/REDACCION_CONTRACT_FIRST.md` explicando origen legacy + adaptaciones.

## Retirada legacy (CLAUDE.md regla Caso A)

Al cerrar este prompt en GREEN:
- Mover a `_legacy_nicegui/` (manteniendo ruta relativa):
  - `client_app/app/modules/privacy/`
  - `client_app/app/services/anonymization_service.py`
  - `client_app/app/utils/pii_detector.py`
  - Tests legacy (excepto los de UI NiceGUI que sí se borran directamente, ya que son código huérfano — Caso B).
- Verificar con `grep -r` que no quedan referencias activas desde código de producción a las rutas movidas.
- **No borres `_legacy_nicegui/` ni en este prompt ni al cerrar la subfase**. El borrado definitivo lo hará el usuario manualmente al cierre de la Fase 1 completa (regla actualizada en CLAUDE.md).
```

---

### Prompt 9R.5.6 (RED/GREEN) — Aprobación con gate de validación obligatoria

**Modelo sugerido**: **Sonnet** — alcance acotado (state machine con 5 endpoints, gates de validación explícitos en el prompt). Opus solo si se quiere reducir iteraciones.

```markdown
# PROMPT 9R.5.6 (RED/GREEN) — Endpoints de aprobación + cola admin + incrustación en plantilla

Objetivo: cerrar el workflow de scripts: persistencia self-service en plantillas privadas, promoción con cola admin para plantillas globales. Toda persistencia exige test_validated_by_proposer_at NOT NULL.

Deploy: edge

Endpoints nuevos en server/app/routers/redaccion/scripts_router.py:

- POST /api/v1/redaccion/scripts/{proposal_id}/save-to-private-template
  - Requiere que el proposer sea el dueño de target_template_id y target_owner_kind='user'.
  - Reglas duras:
    - audit_result.approved must be True (422: AUDIT_FAILED)
    - test_validated_by_proposer_at IS NOT NULL (422: TEST_NOT_VALIDATED)
  - Crea nueva HubReportTemplateVersion del template con el script incrustado en spec_json (un nuevo BlockContract de tipo DETERMINISTIC_DATA con source_kind='admin_script' y options={code, approved:True}).
  - Actualiza HubReportTemplate.current_version_id.
  - Transiciona HubScriptProposal a status='approved', reviewer_user_id=proposer_user_id, reviewed_at=now.

- POST /api/v1/redaccion/scripts/{proposal_id}/submit-for-review
  - Requiere target_owner_kind='platform'.
  - Reglas duras: audit_result.approved + test_validated_by_proposer_at + test_data_is_anonymized=True (422 cualquiera de las tres).
  - Transiciona status='tested' → 'pending_review'. No persiste todavía en plantilla.

- GET /api/v1/redaccion/scripts/pending
  - Solo admin/partner. Devuelve lista de HubScriptProposal con status='pending_review'.
  - Cada item: proposal_id, proposer, prompt_nl, code (head 500 chars), audit_result, test_result_hash, test_data_ref (firmado para descarga temporal).

- POST /api/v1/redaccion/scripts/{proposal_id}/admin-retest
  - Solo admin/partner. Permite que el admin re-ejecute el script contra el mismo test_data_ref.
  - Compara nuevo hash con test_result_hash original.
  - Devuelve { result, hash, hash_matches: bool }.

- POST /api/v1/redaccion/scripts/{proposal_id}/approve
  - Solo admin/partner sobre proposal con status='pending_review'.
  - Body: { target_global_template_id, review_note? }
  - Reglas duras: hash_matches en el último admin-retest debe ser true (422: HASH_MISMATCH) — o haber sido revisado <10 min antes.
  - Crea nueva versión de target_global_template_id con script incrustado.
  - status='approved', reviewer_user_id=admin_id.

- POST /api/v1/redaccion/scripts/{proposal_id}/reject
  - Solo admin/partner. Body: { review_note }.
  - status='rejected'. Audit event en hub_workspace_audit_events.

Cambios en ORM:
- HubScriptProposal.status enum ampliado: proposed | tested | pending_review | approved | rejected.

Tests (RED → GREEN):
- test_save_to_private_template_requires_audit_pass
- test_save_to_private_template_requires_validated_test
- test_save_to_private_template_creates_new_version
- test_save_to_private_template_rejects_if_not_owner
- test_submit_for_review_requires_anonymized_test_data
- test_get_pending_returns_only_pending_review_status
- test_get_pending_forbidden_for_regular_user
- test_admin_retest_returns_hash_match_flag
- test_approve_requires_recent_hash_match
- test_approve_creates_new_global_template_version
- test_reject_records_note_and_blocks_further_changes

Criterio de done:
- 11 tests verdes.
- Migración Alembic con la ampliación del enum (si la columna es String(20), no necesita migración).
- README en docs/REDACCION_CONTRACT_FIRST.md: nueva sección "Workflow de scripts metaprogramados".
```

---

### Prompt 9R.5.7 (RED/GREEN) — Bloque CHART: migración del módulo de gráficos legacy

**Modelo sugerido**: **Sonnet** — migración con patrón establecido (mismo formato que 9R.5.4); sandbox compartido reduce decisiones. Opus si la auditoría AST con plotly/matplotlib produce falsos positivos sutiles.

```markdown
# PROMPT 9R.5.7 (RED/GREEN) — Implementación del block kind CHART vía migración del legacy

Objetivo: implementar la ejecución del block kind `CHART` (definido en 9R.3.1 pero sin handler real) migrando el módulo de gráficos legacy de `client_app/`. Patrón dual confirmado: modo determinista (UI configura tipo + ejes + filtros) y modo IA (NL → script Python que genera el gráfico). Determinista first: si el usuario lo configura, no se invoca al LLM.

> Avance respecto al plan original: 9R.3.1 dejó `CHART` definido como contrato sin implementación. Este prompt cierra esa deuda reutilizando el trabajo ya probado del legacy en lugar de reinventar.

Deploy: edge

## Parte 1 — Migración desde legacy

Fuente legacy:
- `client_app/app/modules/factory/graphics_factory.py` (342 LOC — modo IA, generación de script)
- `client_app/app/services/deterministic_graphics_service.py` (modo asistido)
- `client_app/app/services/graphics_service.py` (62 LOC — wrapper headless)
- Tests: `client_app/tests/unit/test_graphics_factory.py`, `test_graphics_page_modes.py`, `client_app/tests/security/test_sandbox_graphics.py`.

Destino:
- `server/app/modules/redaccion/services/charts/`
  - `__init__.py`
  - `chart_configuration.py`           # ChartConfiguration Pydantic (migrado del dataclass legacy)
  - `deterministic_chart_service.py`   # DeterministicChartService (modo configurador)
  - `chart_factory.py`                 # ChartFactory (modo IA, NL → script)
  - `chart_renderer.py`                # render_chart(config_or_script, data) → bytes (PNG/SVG)
- `server/tests/modules/redaccion/charts/`

Adaptaciones obligatorias:
1. **Eliminar acoplamiento NiceGUI**: el legacy mezcla UI con lógica dentro de `graphics_page.py` (líneas 771-816, `handle_ai_generation`). Esa lógica se extrae a `ChartFactory.generate_script()` y `chart_renderer.render_chart()`. La página NiceGUI se descarta — la UI nueva llega en 9R.7.x.
2. **StorageRef en lugar de file paths**: input (datos) y output (imagen del gráfico) referenciados por StorageRef.
3. **Sandbox compartido con scripts**: cuando se ejecuta el script generado en modo IA, usar el mismo `_execute_in_sandbox` de `AdminScriptExtractionPipeline` (9R.5.4). No duplicar.
4. **Auditoría AST igual que scripts**: el código generado por LLM pasa por `ScriptSecurityAuditor` (9R.5.4) antes de ejecutar. Lista blanca ampliada a `plotly`, `matplotlib`, `seaborn` solo para este pipeline.
5. **Output serializable para el manifest**: además del PNG/SVG, persistir el `ChartConfiguration` JSON (qué tipo, qué columnas) en `block.content_json` para reproducibilidad.

## Parte 2 — Integración con el block kind CHART

`server/app/modules/redaccion/blocks/handlers.py` — actualizar `ChartBlockHandler`:
- `execute(block: BlockContract, ctx: ExecutionContext) -> BlockOutput`:
  - Si `block.config.mode == 'deterministic'`: invoca `DeterministicChartService.render(config, data)`.
  - Si `block.config.mode == 'ai'`: invoca `ChartFactory.generate_script(nl_prompt, schema)` → audit → sandbox → `chart_renderer.render_chart(script, data)`.
  - Output: `{image_ref: StorageRef, configuration: ChartConfiguration, model_used: str | None}`.
- `to_manifest(block) -> dict`: incluye `chart_type`, `data_source_block_id` (BlockReference), `model_used`, `prompt_version` si modo IA.

Ampliación de `BlockContract` para CHART (en `contracts/blocks.py`):
```python
class ChartBlockConfig(BaseModel):
    mode: Literal['deterministic', 'ai']
    chart_type: Literal['bar', 'line', 'pie', 'scatter', 'histogram'] | None  # solo deterministic
    x_axis: str | None
    y_axis: str | list[str] | None
    color_by: str | None
    nl_prompt: str | None  # solo ai
    palette: str = 'default'
```

## Parte 3 — Endpoints

No se añaden endpoints HTTP nuevos: el render se invoca desde el grafo (`AIAssistDraftNode` siguiente al CHART consume el `image_ref`). Sí se añade:
- `GET /api/v1/redaccion/charts/preview` — solo en el wizard de UI, permite previsualizar un chart sin persistir (datos sintéticos del usuario).

## Tests (RED → GREEN)

Migrados/adaptados del legacy:
- test_deterministic_chart_service_renders_bar_chart
- test_deterministic_chart_service_renders_line_chart
- test_deterministic_chart_service_renders_pie_chart
- test_chart_factory_generates_script_from_nl
- test_chart_factory_rejects_unsafe_imports_in_generated_script
- test_chart_renderer_outputs_png_bytes
- test_chart_renderer_outputs_svg_when_requested

Nuevos:
- test_chart_block_handler_routes_to_deterministic_when_mode_deterministic
- test_chart_block_handler_routes_to_ai_when_mode_ai
- test_chart_block_handler_audits_generated_script_before_execution
- test_chart_block_handler_persists_configuration_in_manifest
- test_chart_block_handler_resolves_data_via_block_reference

## Criterio de done

- ≥12 tests verdes.
- `ChartBlockHandler.execute()` funcional para ambos modos.
- Sandbox compartido con AdminScriptExtractionPipeline (verificable: una sola implementación de `_execute_in_sandbox`).
- Tests del slice (9R.10) preparados para incluir un bloque CHART.

## Retirada legacy (CLAUDE.md regla Caso A)

Al cerrar este prompt en GREEN, mover a `_legacy_nicegui/`:
- `client_app/app/modules/factory/graphics_factory.py`
- `client_app/app/services/graphics_service.py`
- `client_app/app/services/deterministic_graphics_service.py`
- `client_app/app/ui/graphics_page.py`
- Tests legacy asociados.
Verificar con `grep -r` que no quedan referencias activas. Borrado definitivo manual por el usuario al cierre de Fase 1.
```

---

### Prompt 9R.5.8 (RED/GREEN) — Bloque DATA_TRANSFORM: migración del módulo ETL legacy

**Modelo sugerido**: **Opus** — el prompt más denso del bloque: migración ~1200 LOC + discriminated unions de operaciones + NL→ops con refinamiento iterativo + fallback a script + integración como nodo nuevo en el grafo. Concentra decisiones de diseño.

```markdown
# PROMPT 9R.5.8 (RED/GREEN) — Nuevo block kind DATA_TRANSFORM con motor ETL determinista + modo IA

Objetivo: introducir el block kind `DATA_TRANSFORM` que ejecuta transformaciones tabulares (filter, aggregate, join, pivot, normalize, groupby) entre la extracción determinista y los bloques IA. Migrado del módulo ETL legacy, que es el módulo mejor factorizado del client_app (separación lógica/UI razonable, sandbox + anonimización + refinamiento iterativo).

> Avance respecto al plan original: el BlockContract de 9R.1.2 cubría 10 tipos de bloque pero no incluía transformación tabular. Este prompt añade el 11º tipo y resuelve el eslabón ausente entre `DeterministicExtractionNode` y `AIAssistDraftNode` para informes que necesitan agregar/filtrar antes de redactar.

Deploy: edge

## Parte 1 — Migración desde legacy

Fuente legacy:
- `client_app/app/services/etl_service.py` (425 LOC, orquestador maduro)
- `client_app/app/services/deterministic_etl_service.py` (motor de operaciones)
- `client_app/app/modules/factory/etl_factory.py` (369 LOC, modo IA)
- Tests: `client_app/tests/unit/test_etl_service.py`, `test_deterministic_etl.py`, `client_app/tests/integration/test_etl_e2e.py` + tests de modos, clarificación, anonimización.

Destino:
- `server/app/modules/redaccion/services/transformation/`
  - `__init__.py`
  - `operations.py`                # Operation Pydantic discriminated union (FilterOp, AggregateOp, JoinOp, PivotOp, NormalizeOp, GroupByOp)
  - `deterministic_etl.py`         # DeterministicETLService.execute(df, operations) → df
  - `etl_factory.py`               # ETLFactory.generate_operations_from_nl(nl, schema) → list[Operation]
  - `etl_service.py`               # ETLService (orquestador: lee → transforma → valida → devuelve)
- `server/tests/modules/redaccion/transformation/`

Adaptaciones obligatorias:
1. **Reemplazar generación de script Python por generación de `list[Operation]` JSON**: en el legacy, el modo IA generaba código Python ejecutable. Aquí preferimos que la IA produzca operaciones declarativas (más auditable, más fácil de mostrar al usuario antes de aplicar). Si una operación requerida no encaja en el catálogo, fallback a script Python via ScriptSecurityAuditor (igual que 9R.5.5).
2. **StorageRef + DataFrame async**: el legacy trabajaba sobre `pd.DataFrame` in-memory. Mantener pandas pero envolver la lectura/escritura en async (`StorageService.get_bytes` + `pd.read_excel`/`read_csv`).
3. **Refinamiento iterativo conservado**: el legacy tenía `MAX_REFINEMENT_ITERATIONS = 3` (la IA podía corregir su output si la validación fallaba). Mantener.
4. **Anonimización integrada en el flujo de tests**: cuando el bloque DATA_TRANSFORM se usa como test data para un script (9R.5.5), el anonymizer (también 9R.5.5) se aplica antes.
5. **Tipos de operación cubiertos**: filter (col, op, value), aggregate (col, function), join (other_block_ref, on, how), pivot (index, columns, values), normalize (cols, method), groupby (cols, agg_dict). Validación estricta en cada operación.

## Parte 2 — Integración con el block kind DATA_TRANSFORM

Añadir `DATA_TRANSFORM` al `BlockKind` enum en `contracts/blocks.py`:

```python
class DataTransformBlockConfig(BaseModel):
    mode: Literal['deterministic', 'ai']
    source_block_ref: BlockReference  # de qué bloque toma el DataFrame
    operations: list[Operation] | None  # solo deterministic
    nl_instruction: str | None         # solo ai (se traduce a operations)
```

`DataTransformBlockHandler.execute(block, ctx)`:
- Resuelve DataFrame desde `source_block_ref` (reusa BlockReference + projection de 9R.3.3).
- Si `mode == 'deterministic'`: `DeterministicETLService.execute(df, operations)`.
- Si `mode == 'ai'`: `ETLFactory.generate_operations_from_nl(nl, schema)` → validate → execute. Si genera operations inválidas tras 3 intentos, fallback a script Python (sandbox + audit).
- Output: `{transformed_data_ref: StorageRef, operations_applied: list[Operation], model_used: str | None}`.
- `to_manifest`: incluye lista de operaciones aplicadas y fuente (deterministic vs ai).

## Parte 3 — Integración en el grafo

Modificar `DraftingCoreGraph` (9R.6.x):
- Nuevo nodo `DataTransformationNode` (servidor entre `DeterministicExtractionNode` y `AIAssistDraftNode`).
- Itera sobre bloques `DATA_TRANSFORM` en orden topológico (reusar 9R.3.3).
- Transición de estado: `draft → ai_generated` o `draft → extracted` según mode (el resultado es determinista en ambos casos — la IA solo elige las operaciones, no las ejecuta).

## Tests (RED → GREEN)

Migrados/adaptados del legacy:
- test_deterministic_etl_filter
- test_deterministic_etl_aggregate
- test_deterministic_etl_join
- test_deterministic_etl_pivot
- test_deterministic_etl_groupby_with_multiple_aggs
- test_deterministic_etl_normalize_min_max
- test_etl_factory_generates_operations_from_nl (mocked LLM)
- test_etl_factory_refines_when_validation_fails
- test_etl_factory_falls_back_to_script_when_operations_unsupported
- test_etl_service_runs_pipeline_end_to_end

Nuevos:
- test_data_transform_block_handler_resolves_source_via_block_ref
- test_data_transform_block_persists_operations_in_manifest
- test_data_transform_node_runs_between_extraction_and_ai
- test_data_transform_block_chains_with_chart_block_consuming_output

## Criterio de done

- ≥14 tests verdes.
- DATA_TRANSFORM funcional en ambos modos.
- `DataTransformationNode` integrado en core_graph.py (9R.6.x ya completado).
- Documentación actualizada en `docs/REDACCION_CONTRACT_FIRST.md`: sección "Bloques de transformación".

## Retirada legacy (CLAUDE.md regla Caso A)

Al cerrar este prompt en GREEN, mover a `_legacy_nicegui/`:
- `client_app/app/services/etl_service.py`
- `client_app/app/services/deterministic_etl_service.py`
- `client_app/app/modules/factory/etl_factory.py`
- `client_app/app/ui/etl_page.py`
- Tests legacy asociados.
Verificar con `grep -r` que no quedan referencias activas. Borrado definitivo manual por el usuario al cierre de Fase 1.
```

---

### Prompt 9R.5.9 (RED/GREEN) — Extractor Docling rico (ExtractedDocument) — adelantado parcial de Fase 2

**Modelo sugerido**: **Sonnet** — cambio de contrato bien definido + 2 ajustes localizados en nodos del grafo. La heurística text_linear/complex_tables es simple. Pasa a Opus si la API de Docling resulta más opaca de lo esperado.

```markdown
# PROMPT 9R.5.9 (RED/GREEN) — PDFTextExtractionPipeline rico: markdown + tablas estructuradas + páginas

Objetivo: amplificar el `PDFTextExtractionPipeline` actual (que ya usa Docling pero solo extrae texto plano via `export_to_text()`) para que produzca el contrato rico `ExtractedDocument` previsto inicialmente en Fase 2 prompt 9.12b. Aprovecha Docling al máximo: markdown por documento + markdown por página + tablas estructuradas con bbox, todo en una sola ejecución. Adelantado de Fase 2 a Fase 1 porque informes habituales agregan varios PDFs en un mismo informe — sin esta riqueza, el AIAssistDraftNode trabaja sobre texto plano linealizado y pierde estructura (encabezados, listas, tablas).

> Opción B confirmada (2026-05-13): adelantar **solo el extractor Docling rico**, no el wizard interactivo de extracción (analyze→extract→refine→generate_script) que sigue en Fase 2 prompt 9.13 con UI propia. El wizard se beneficia de RPA-like batch processing y encaja mejor con el módulo de automatización.

Deploy: edge

## Parte 1 — Contrato ExtractedDocument en redaccion

Origen del contrato: Fase 2 prompt 9.12b (`Plan_TDD_Fase2.md:436-455`). Se traslada literalmente, con ubicación nueva en redaccion.

Estructura en `server/app/modules/redaccion/pipelines/contracts.py`:
```python
class ExtractedCell(BaseModel):
    text: str
    row: int
    col: int
    row_span: int = 1
    col_span: int = 1

class ExtractedTableRich(BaseModel):
    """Tabla con coordenadas y celdas — extensión de ExtractedTable existente."""
    page: int                     # 1-based
    caption: str | None = None
    headers: list[str]
    cells: list[ExtractedCell]
    bbox: tuple[float, float, float, float] | None = None

class ExtractedPage(BaseModel):
    page: int                     # 1-based
    markdown: str                 # render markdown de esta página (Docling)
    plain_text: str               # texto lineal por si el consumidor prefiere
    tables: list[ExtractedTableRich]

class ExtractedDocument(BaseModel):
    """Salida rica de Docling. Se anexa a ExtractionResult.provenance.extras."""
    filename: str
    num_pages: int
    markdown: str                 # documento completo
    pages: list[ExtractedPage]
    tables: list[ExtractedTableRich]  # vista plana
    extraction_strategy: Literal["text_linear", "complex_tables"]
    docling_version: str
```

Para mantener retrocompatibilidad con el `ExtractionResult` simple (consumido por Excel, Manual, AdminScript), `ExtractedDocument` se entrega como **campo adicional** opcional:

```python
class ExtractionResult(BaseModel):
    tables: list[ExtractedTable] = Field(default_factory=list)
    metrics: list[ExtractedMetric] = Field(default_factory=list)
    free_text: str | None = None
    document: ExtractedDocument | None = None   # ← NUEVO. Solo PDFs ricos.
    warnings: list[ExtractionWarning] = Field(default_factory=list)
    provenance: ExtractionProvenance
```

Ventaja: los nodos del grafo que ya consumen `free_text` o `tables` siguen funcionando. Los nodos nuevos (AIAssistDraftNode, citation tracking) pueden preferir `document.markdown` y `document.tables[*]` cuando estén presentes.

## Parte 2 — Upgrade del PDFTextExtractionPipeline

Modificar `server/app/modules/redaccion/pipelines/pdf_text_pipeline.py`:

```python
def __init__(self) -> None:
    opts = PdfPipelineOptions()
    opts.do_ocr = False
    opts.do_table_structure = True        # ← cambio (antes False)
    opts.do_picture_classification = False
    opts.generate_page_images = False
    self._converter = DocumentConverter(...)

def extract(self, inp: ExtractionInput) -> ExtractionResult:
    conv = self._converter.convert(str(file_path))
    doc = conv.document

    # Construir ExtractedDocument rico
    pages = [
        ExtractedPage(
            page=p.page_no,
            markdown=p.export_to_markdown(),
            plain_text=p.export_to_text(),
            tables=[_to_rich_table(t) for t in p.tables],
        )
        for p in doc.pages
    ]
    rich = ExtractedDocument(
        filename=inp.file_ref.key,
        num_pages=len(pages),
        markdown=doc.export_to_markdown(),
        pages=pages,
        tables=[_to_rich_table(t) for t in doc.tables],
        extraction_strategy=_choose_strategy(doc),
        docling_version=docling.__version__,
    )

    # Mantener compatibilidad con consumers simples
    return ExtractionResult(
        free_text=doc.export_to_text() or None,
        tables=[ExtractedTable(  # vista simple para retro-compat
            name=f"page_{t.page}_table_{i}",
            headers=t.headers,
            rows=[[c.text for c in row_cells] for row_cells in _group_by_row(t.cells)],
            source_page=t.page,
        ) for i, t in enumerate(rich.tables)],
        document=rich,
        warnings=[...] if not doc.export_to_text() else [],
        provenance=...,
    )
```

Async wrapper: Docling es síncrono y CPU-bound. Envolver con `asyncio.to_thread(self._converter.convert, ...)` en el nodo `DeterministicExtractionNode` (cambio menor en 9R.6.2 ya verde).

## Parte 3 — Estrategia de extracción

Heurística mínima para `extraction_strategy`:
- Si `len(doc.tables) >= 3` o el ratio tables/pages > 0.5 → `complex_tables`.
- Si no → `text_linear`.

Útil para que `AIAssistDraftNode` adapte su prompt: ante `complex_tables` prioriza `tables_json` en el contexto; ante `text_linear` prioriza `markdown`.

## Parte 4 — Integración con AIAssistDraftNode (9R.6.3 ya verde — micro-ajuste)

Cambio en `server/app/modules/redaccion/graph/nodes/ai_assist_draft.py`:
- Cuando el bloque depende de un input PDF cuyo `ExtractionResult.document is not None`:
  - Pasar al LLM `document.markdown[:30000]` en lugar de `free_text`.
  - Si `extraction_strategy == "complex_tables"`: anexar `json.dumps([t.model_dump() for t in document.tables[:20]])`.
- Si el bloque depende de varios PDFs: concatenar markdown con encabezados `## [filename]` para que el LLM mantenga atribución.

## Parte 5 — Citation traceability (9R.6.3 ya verde — micro-ajuste)

`CitationAndTraceabilityNode`: cuando el contenido AI cite un dato extraído de un PDF rico, la cita puede incluir:
- `source_document` (filename)
- `page` (número de página del bbox)
- `cell_ref` si proviene de una tabla específica
- `excerpt` (primeros 200 chars del párrafo donde aparece el dato)

El modelo `Citation` de `contracts/runtime.py` ya soporta estos campos. Solo hay que poblarlos.

## Tests (RED → GREEN)

Nuevos (en `server/tests/modules/redaccion/test_docling_rich_extraction.py`):
- test_pipeline_produces_extracted_document_with_markdown
- test_pipeline_produces_per_page_markdown_and_tables
- test_pipeline_chooses_complex_tables_strategy_when_many_tables
- test_pipeline_chooses_text_linear_when_few_tables
- test_pipeline_preserves_table_bbox_when_available
- test_pipeline_extracted_document_serializes_to_openapi_schema
- test_retro_compat_free_text_still_populated
- test_retro_compat_simple_tables_view_still_populated

Adaptaciones a tests existentes (smoke tests, no rehacer):
- Tests de `AIAssistDraftNode` ahora reciben `document.markdown` cuando el input es PDF — verificar que el prompt construido lo incluye.
- Tests de `CitationAndTraceabilityNode` verifican que las citas con bbox/page se persisten.

## Criterio de done

- ≥8 tests nuevos verdes.
- Tests existentes de pdf_text_pipeline siguen verdes (retro-compatibilidad).
- `ExtractedDocument` aparece en OpenAPI exportado.
- AIAssistDraftNode prefiere markdown sobre plain_text cuando está disponible.
- Documentación actualizada en `docs/REDACCION_CONTRACT_FIRST.md`: sección "Extracción rica de PDFs con Docling".

## Lo que NO se hace aquí (queda en Fase 2)

- **Wizard de extracción con fases interactivas** (analyze_structure / extract_precision / refine / generate_script): sigue en Fase 2 prompt 9.13. El usuario interactivo con muchos PDFs similares (caso RPA) lo usa allí.
- **API de runs con polling por run_id**: no es necesaria en MVP. La extracción se hace síncrona dentro del DraftingCoreGraph (con `asyncio.to_thread`). Si emerge problema de latencia con PDFs grandes, se mueve a background task post-MVP.
- **UI específica del extractor PDF**: en MVP, el usuario sube PDFs vía el `GenericReportWizard` existente; no hay pantalla dedicada al extractor.

## Implicaciones para el plan de Fase 2

- Prompt 9.12b queda **reducido a deuda residual**: actualizar fixtures de tests, limpiar imports obsoletos. La mayor parte del trabajo (motor Docling, contratos `ExtractedDocument`, prompts adaptados a markdown) ya está hecha aquí.
- Prompt 9.13 (UI wizard) sigue íntegro pero ahora consume el contrato `ExtractedDocument` ya estable desde Fase 1.
- Fase 2 actualizará `Plan_TDD_Fase2.md` y `PROJECT_STATE.md` cuando se aborde, no es responsabilidad de este prompt.
```

---

### Prompt 9R.6.1 (RED/GREEN) — CoreGraph: nodos de carga y normalización

```markdown
# PROMPT 9R.6.1 (RED/GREEN) — LoadTemplateNode / ValidateInputContractNode / FileNormalizationNode

Objetivo: implementar los tres primeros nodos del DraftingCoreGraph.

Estructura (en server/app/modules/redaccion/graph/):
- state.py           # WorkspaceState reutiliza el contrato de runtime de 9R.1.3
- core_graph.py      # build_core_graph() devuelve compiled graph
- nodes/load_template.py
- nodes/validate_inputs.py
- nodes/file_normalization.py

LoadTemplateNode:
- Lee `template_version_id` del state.
- Carga ReportTemplateVersion desde repo.
- Hidrata `state.spec`.

ValidateInputContractNode:
- Comprueba slots requeridos del InputContract contra `state.inputs`.
- Marca bloques USER_INPUT pendientes como `missing_input`.
- Si falta input requerido → status="ingesting" (pide al usuario) o "error" según política.

FileNormalizationNode:
- Para cada InputArtifact PDF/Excel: descarga vía StorageService, calcula hash, registra en `state.artifacts_normalized`.
- No parsea; solo prepara para el siguiente nodo.

Tests (RED → GREEN):
- test_load_template_node_hydrates_state_spec
- test_load_template_node_raises_if_version_not_found
- test_validate_input_contract_marks_missing_required_inputs
- test_file_normalization_records_hashes
- test_core_graph_compiles_with_generic_report_profile

Criterio de done:
- `build_core_graph()` retorna un graph compilable.
- Tests verdes.
```

---

### Prompt 9R.6.2 (RED/GREEN) — CoreGraph: extracción determinista

```markdown
# PROMPT 9R.6.2 (RED/GREEN) — DeterministicExtractionNode / DataQualityCheckNode / MissingDataQuestionNode

Objetivo: ejecutar la extracción determinista antes de cualquier nodo IA.

Nodos:
- DeterministicExtractionNode
  - Para cada DETERMINISTIC_DATA block: invoca ExtractionPipelineFactory según `source_kind`.
  - Guarda ExtractionResult en `state.blocks[block_id].content`.
  - Transición de estado: missing_input → extracted.
- DataQualityCheckNode
  - Inspecciona warnings (NO_TABLES_FOUND, MISSING_REQUIRED_COLUMNS, NON_EXTRACTABLE_PDF).
  - Si severity=error → pasa al MissingDataQuestionNode.
- MissingDataQuestionNode
  - Formula preguntas concretas al usuario (HITL): "Falta columna 'fecha' en datos_excel — ¿puedes subir versión corregida?"
  - Estado del workspace = "in_review", devuelve grafo en pausa.

Tests (RED → GREEN):
- test_core_graph_blocks_when_required_input_missing
- test_core_graph_runs_deterministic_extraction_before_ai
- test_data_quality_check_pauses_graph_on_critical_warning
- test_missing_data_question_emits_actionable_message
- test_deterministic_extraction_writes_to_block_content

Criterio de done:
- Confirmar invariante: ningún nodo IA se ejecuta si data quality tiene errores críticos.
- Tests verdes.
```

---

### Prompt 9R.6.3 (RED/GREEN) — CoreGraph: nodos IA

```markdown
# PROMPT 9R.6.3 (RED/GREEN) — AIAssistDraftNode / CitationAndTraceabilityNode

Objetivo: generar texto asistido por IA usando solo datos ya validados como contexto, y registrar provenance.

Nodos:
- AIAssistDraftNode
  - Para cada bloque AI_ASSISTED_TEXT / AI_SUMMARY / AI_REWRITE:
    - Construye contexto solo con `state.blocks[*]` en estado `extracted` o `approved`.
    - Llama al LLM con prompt_template versionado.
    - Guarda salida + model_used + prompt_version en `state.blocks[block_id]`.
    - Transición: extracted → ai_generated.
- CitationAndTraceabilityNode
  - Adjunta citaciones a cada bloque AI (referenciando data blocks origen).
  - Si AI_ASSISTED_TEXT referencia un Excel: cita `[fila X, hoja "Y", input slot "datos_excel"]`.

Tests (RED → GREEN):
- test_ai_node_receives_only_validated_data_context
- test_ai_node_records_model_and_prompt_version
- test_ai_node_skipped_if_block_already_approved_or_locked
- test_citation_node_attaches_provenance_to_ai_block
- test_ai_node_handles_llm_error_gracefully   (state="error", no contamina state.blocks)

Criterio de done:
- Tests verdes (5/5).
- No hay AIDrafterNode legacy del 9.11c: ese paso queda absorbido aquí.
```

---

### Prompt 9R.6.4 (RED/GREEN) — CoreGraph: HITL y ensamblado

```markdown
# PROMPT 9R.6.4 (RED/GREEN) — UserReviewGateNode / ApplyUserEditsNode / FinalAssemblerNode

Objetivo: bloquear el ensamblado hasta que todos los bloques AI tengan estado `approved`, aplicar ediciones del usuario y ensamblar el documento final.

Nodos:
- UserReviewGateNode
  - Para cada bloque AI en `ai_generated` → transición a `needs_review`.
  - Si quedan bloques en `needs_review` → status="in_review", grafo pausa.
  - Si todos los AI están `approved` → continúa al ensamblado.
- ApplyUserEditsNode
  - Aplica ediciones manuales del usuario sobre el contenido (override del texto AI).
  - Mantiene el original en `state.blocks[block_id].original_ai_content` para auditoría.
- FinalAssemblerNode
  - Renderiza Markdown ensamblado según orden de secciones.
  - Solo incluye bloques en estado `approved` o `locked`.
  - Calcula `final_document_hash` (SHA-256 del Markdown).
  - Transición workspace: "in_review" → "assembled".

Tests (RED → GREEN):
- test_review_gate_prevents_unapproved_ai_blocks_in_final_document
- test_review_gate_pauses_graph_until_all_ai_blocks_approved
- test_apply_user_edits_preserves_original_ai_content
- test_final_assembler_only_includes_approved_blocks
- test_final_assembler_computes_document_hash

Criterio de done:
- Tests verdes (5/5).
- `state.final_document` poblado solo si todos los bloques requeridos están `approved`.
```

---

### Prompt 9R.6.5 (RED/GREEN) — CoreGraph: AuditLog + RunManifest emission + tracing Langfuse

```markdown
# PROMPT 9R.6.5 (RED/GREEN) — AuditLogNode + emisión de DraftingRunManifest + instrumentación Langfuse

Objetivo: cerrar el grafo emitiendo un DraftingRunManifest con trazabilidad completa e instrumentar todos los nodos del DraftingCoreGraph con Langfuse para observabilidad runtime (consistente con el grafo público de 9B).

Nodo:
- AuditLogNode
  - Construye DraftingRunManifest con todo el contenido necesario (ver 9R.9.1).
  - Persiste vía RunManifestRepo.
  - Actualiza `workspace.run_manifest_id`.
  - Transición workspace: "assembled" → "assembled" (el manifest no cambia estado, solo registra).

Instrumentación Langfuse (transversal a todos los nodos del CoreGraph):
- Reusar `server/app/core/observability/langfuse.py` (existente desde Fase 8). NO crear cliente nuevo.
- Cada invocación del CoreGraph abre un span raíz `redaccion.run` con atributos: `workspace_id`, `template_version_id`, `run_manifest_id` (asignado tras AuditLogNode).
- Cada nodo abre un span hijo `redaccion.{node_name}` con atributos: `node_name`, `block_id` (si aplica), `block_kind` (si aplica).
- Nodos IA (AIAssistDraftNode, CitationAndTraceabilityNode) añaden atributos extra al span: `model_used`, `prompt_version`, `tokens_in`, `tokens_out`, `latency_ms`.
- Fallos (capturados por la política de retry de 9R.6.6) se emiten como `span.event("error", { type, message, retry_attempt })` antes de marcar el bloque como `failed`.
- El `run_manifest_id` final se escribe como atributo del span raíz para enlazar tracing ↔ manifest.

Tests (RED → GREEN):
- test_core_graph_generates_run_manifest
- test_core_graph_generates_manifest_even_on_error
- test_core_graph_supports_admin_template_and_ad_hoc_workspace
- test_run_manifest_persisted_after_audit_log_node
- test_workspace_run_manifest_id_updated
- test_core_graph_opens_root_langfuse_span_with_workspace_id
- test_each_node_opens_child_span_under_root
- test_ai_node_records_model_and_token_attributes_on_span
- test_failed_node_emits_error_event_on_span
- test_root_span_attribute_run_manifest_id_set_after_audit_log

Criterio de done:
- Cualquier ejecución del DraftingCoreGraph (éxito o fallo controlado) deja un manifest persistido.
- Cada nodo aparece como span hijo del span raíz en Langfuse.
- Span raíz contiene `workspace_id`, `template_version_id` y `run_manifest_id` final.
- 10 tests verdes.
- Documentar en docs/REDACCION_CONTRACT_FIRST.md el diagrama final + sección "Observabilidad".
```

---

### Prompt 9R.6.6 (RED/GREEN) — CoreGraph: fallback paths + BlockState=failed

```markdown
# PROMPT 9R.6.6 (RED/GREEN) — Fallos controlados, BlockState=failed y política de retry

Objetivo: definir el comportamiento del DraftingCoreGraph cuando un nodo falla por causa controlada (timeout LLM, extracción imposible, AdminScript con excepción runtime), sin abortar el workspace ni perder el progreso ya logrado en otros bloques.

Extensión de BlockState (modifica 9R.3.2):
- Nuevo estado `failed` con sub-tipo obligatorio en `failure_kind`:
    failure_kind: Literal["extraction_failed", "ai_failed", "script_failed", "validation_failed"]
- Nuevas transiciones:
    draft           ─EXTRACT_FAIL→ failed(extraction_failed)
    extracted       ─AI_FAIL→      failed(ai_failed)
    extracted       ─SCRIPT_FAIL→  failed(script_failed)
    needs_review    ─APPROVE→      approved      (sin cambio)
    failed          ─REGENERATE→   draft|extracted|ai_generated (según failure_kind)
    failed          ─REJECT→       rejected      (saltar bloque si no es required)
    *(dependencia)  ─DEP_FAIL→     failed(validation_failed) si una dependencia está failed

Servicio BlockExecutor (nuevo, en server/app/modules/redaccion/services/block_executor.py):
- Encapsula la política de retry para todos los nodos del CoreGraph.
- async def execute(node_fn: Callable, block: BlockContract, state: WorkspaceState) -> NodeResult
    - Llama node_fn(block, state).
    - LLM timeouts y errores de red: 1 retry automático con backoff de 2s.
    - AST validation errors y script runtime exceptions: NO retry (probablemente bug determinista).
    - Captura excepción y devuelve `NodeResult(status="failed", failure_kind=..., last_error=...)`.
    - Cada intento emite span Langfuse `error` (ver 9R.6.5).

Comportamiento del CoreGraph ante fallo (ver 9R.3.3 para topología):
- El nodo afectado marca su bloque `failed(<failure_kind>)` y persiste outputs parciales si existen en `state.block_outputs[block.id]["partial"] = ...`.
- El CoreGraph NO aborta: continúa con los bloques cuya topología no dependa del fallido.
- Los bloques que dependen del fallido (vía `depends_on` de 9R.3.3) pasan automáticamente a `failed(validation_failed)` con `last_error="dependency_failed:<block_id>"`.
- AuditLogNode (9R.6.5) recoge la lista de bloques fallidos en `manifest.failed_blocks: list[{block_id, failure_kind, last_error_message, retry_attempts}]`.

Integración con UserReviewGateNode (9R.6.4):
- El gate también acepta bloques `failed`: la UI muestra `failure_kind`, último error y dos acciones:
    1) "Regenerar" → REGENERATE event, vuelve al estado origen y re-ejecuta.
    2) "Saltar bloque" → solo si `required=False`; emite REJECT.

Migración Alembic:
- hub_workspace_blocks: extender enum `state` con valor `failed`
- hub_workspace_blocks.failure_kind (str, nullable)
- hub_workspace_blocks.last_error_message (text, nullable)
- hub_workspace_blocks.retry_attempts (int, default 0, not null)

Reglas duras:
- BlockExecutor es la ÚNICA superficie con la política de retry. Los nodos no implementan su propio retry.
- Un bloque `required=True` cuya dependencia está `failed(validation_failed)` impide el ensamblado final (regla heredada de 9R.3.2 + 9R.6.4): FinalAssemblerNode rechaza el workspace con un `WorkspaceBlockedByFailedBlocksError`.

Tests (RED → GREEN):
- test_block_state_machine_supports_failed_state_with_subtypes
- test_block_state_machine_failed_to_regenerate_returns_to_correct_origin_state
- test_block_executor_retries_once_on_llm_timeout
- test_block_executor_no_retry_on_script_runtime_exception
- test_block_executor_no_retry_on_ast_validation_error
- test_block_executor_emits_error_span_on_each_attempt
- test_core_graph_continues_with_independent_blocks_when_one_fails
- test_core_graph_marks_dependent_blocks_as_validation_failed
- test_partial_outputs_preserved_under_block_outputs_partial
- test_audit_log_node_records_failed_blocks_in_manifest_with_attempts
- test_user_review_gate_allows_regenerate_on_failed_block
- test_user_review_gate_allows_skip_only_if_block_not_required
- test_final_assembler_rejects_when_required_block_failed_validation

Criterio de done:
- Migración Alembic aplicada (1 enum value + 3 columnas).
- BlockExecutor centraliza el retry; sin duplicación en los nodos.
- 13 tests verdes.
- Documentar en docs/REDACCION_CONTRACT_FIRST.md la sección "Fallos controlados y política de retry".
```

---

### Prompt 9R.7.1 (RED/GREEN) — UI: Renderer base + slots dinámicos

```markdown
# PROMPT 9R.7.1 (RED/GREEN) — ReportUIContractRenderer + DynamicUploadSlots + DynamicFieldRenderer

Objetivo: componente raíz que renderiza una UI completa solo a partir de un `ReportUIContract` consumido por Orval.

Estructura (en frontend/src/redaccion/components/):
- ReportUIContractRenderer.tsx
- DynamicUploadSlots.tsx
- DynamicFieldRenderer.tsx

Reglas:
- 0 interfaces TypeScript manuales. Usar tipos de @/shared/api/generated/model.
- react-hook-form + zodResolver para validación.
- Soporta i18n por dict[str,str] en labels.

Tests Vitest RED → GREEN:
- should_render_upload_slots_from_ui_contract
- should_render_dynamic_fields_from_ui_contract
- should_block_continue_when_required_input_missing
- should_show_validation_error_on_invalid_field
- should_render_localized_labels_from_dict

Criterio de done:
- 5/5 tests verdes.
- `npx tsc -p tsconfig.app.json --noEmit` limpio.
```

---

### Prompt 9R.7.2 (RED/GREEN) — UI: BlockEditor + paneles de revisión

```markdown
# PROMPT 9R.7.2 (RED/GREEN) — BlockEditor + AIBlockReviewPanel + DataQualityPanel + WorkspaceStatusBar

Objetivo: editor visual de bloques + paneles de revisión y estado.

Componentes:
- BlockEditor.tsx           → drag & drop de bloques (no-code, estilo TipTap)
- AIBlockReviewPanel.tsx    → muestra bloques en `needs_review` con botones Approve/Reject/Regenerate
- DataQualityPanel.tsx      → lista de ExtractionWarning con severity y código
- WorkspaceStatusBar.tsx    → estado del workspace + progreso (ingesting/extracting/drafting/in_review/assembled)

Hooks consumidos (Orval):
- useGetWorkspaceById
- usePatchWorkspaceBlock      (approve/reject/regenerate)
- useGetWorkspaceWarnings

Tests Vitest RED → GREEN:
- should_show_ai_blocks_as_pending_review
- should_require_explicit_approval_before_final_assembly
- should_show_extraction_warnings_with_severity
- should_show_workspace_status_progress
- should_allow_regenerate_ai_block

Criterio de done:
- Tests verdes (5/5).
- Sin fetch manual: todo vía hooks generados.
```

---

### Prompt 9R.7.3 (RED/GREEN) — UI: páginas admin y usuario

```markdown
# PROMPT 9R.7.3 (RED/GREEN) — ReportTemplateBuilderPage + GenericReportWizard

Objetivo: dos páginas con responsabilidades claras.

ReportTemplateBuilderPage (admin):
- Listado de plantillas (globales + organización).
- Crear/editar plantilla: configura secciones, bloques, inputs, ui_contract.
- Guardar como nueva versión (append-only).
- Restringido a rol admin/partner.

GenericReportWizard (user):
- Selección de plantilla (globales + propias) o GENERIC_REPORT.
- Wizard de inputs (upload slots, manual fields).
- Acceso al BlockEditor del workspace.
- Acceso al AIBlockReviewPanel.

Hooks (Orval): useListTemplates, useCreateTemplate, useCreateWorkspace, useGetWorkspaceById.

Tests Vitest RED → GREEN:
- should_allow_admin_to_save_template_version
- should_allow_user_to_create_ad_hoc_workspace_from_generic_report
- should_list_only_user_visible_templates
- should_redirect_non_admin_away_from_builder_page

Criterio de done:
- Tests verdes.
- Páginas registradas en el router del frontend.
```

---

### Prompt 9R.7.4 (RED/GREEN) — UI: LLM draft preview + aprobación

```markdown
# PROMPT 9R.7.4 (RED/GREEN) — LLMDraftPreviewPage

Objetivo: pantalla que pide al usuario un prompt en lenguaje natural, recibe `ReportTemplateDraft`, lo muestra editable, y permite aprobar como plantilla o workspace.

Pantalla (en frontend/src/redaccion/pages/LLMDraftPreviewPage.tsx):
- Input de texto natural + botón "Generar propuesta".
- Vista previa editable del draft (mismo BlockEditor de 9R.7.2).
- Toggle "Modo": Crear plantilla (admin) | Crear workspace (cualquiera).
- Botón "Aprobar y crear".
- Muestra validación estructural en línea (errors de DraftValidator).

Hooks (Orval): useProposeLlmDraft, useValidateLlmDraft, useApproveAsTemplate, useApproveAsWorkspace.

Tests Vitest RED → GREEN:
- should_render_llm_generated_draft_preview_before_persisting
- should_block_approve_button_when_draft_invalid
- should_call_approve_as_template_when_admin_mode
- should_call_approve_as_workspace_when_user_mode
- should_show_validation_errors_inline

Criterio de done:
- Tests verdes (5/5).
- Cero llamadas manuales a fetch.
```

---

### Prompt 9R.7.5 (RED/GREEN) — UI metaprogramación: wizard de propuesta de scripts + cola admin

**Modelo sugerido**: **Sonnet** — UI con muchos pasos pero patrones React conocidos (wizard + invalidación + hooks Orval). Decisiones de diseño ya tomadas en el prompt. Opus solo si la lógica de invalidación entre pasos se complica.

```markdown
# PROMPT 9R.7.5 (RED/GREEN) — UI completa del workflow de scripts

Objetivo: dar al usuario un wizard guiado para proponer un script vía LLM, probarlo obligatoriamente sobre datos reales o sintéticos antes de poder persistirlo, y al admin una cola de revisión para promociones a plantilla global.

Estructura nueva (en frontend/src/redaccion/):
- pages/ScriptProposalWizardPage.tsx     # wizard de 7 pasos para cualquier usuario
- pages/AdminScriptReviewQueuePage.tsx   # cola para admin/partner
- components/ScriptCodePreview.tsx       # syntax highlight + AST findings
- components/TestDataAnonymizerForm.tsx  # tabla columnas + dropdown Faker provider
- components/SandboxTestResultViewer.tsx # muestra ExtractionResult + hash

ScriptProposalWizardPage (data-testids: wizard-step-{n}):
1. Prompt NL — textarea "¿Qué cálculo o extracción necesitas?" + botón "Generar".
2. Preview código + auditoría — muestra código resaltado + lista de findings AST. Si audit.approved=false, botón "Reintentar" vuelve al paso 1 (con feedback del audit).
3. Subir datos de test — dropzone para CSV/XLSX.
4. Anonimización — tabla de columnas con dropdown por columna (keep / name / email / phone / iban / address / date / integer). Si target_owner_kind='platform', "keep" está deshabilitado para columnas con sample_values no numéricos (heurística simple).
5. Ejecutar sandbox — botón "Probar"; muestra ExtractionResult + hash. Si error, vuelve al paso 1 o 4.
6. Validar resultado — checkbox "Confirmo que esta salida es correcta para mi caso de uso" + botón "Confirmar".
7. Guardar / enviar — botones condicionales:
   - Si target_owner_kind='user': "Guardar en mi plantilla" (POST save-to-private-template).
   - Si target_owner_kind='platform': "Enviar al admin para revisión" (POST submit-for-review).

Cada paso bloquea el siguiente hasta que la condición se cumple (visible vía atributo aria-disabled). No hay back-skip silencioso: si cambias el código, los pasos 3-7 se invalidan y hay que rehacerlos.

AdminScriptReviewQueuePage:
- Tabla con propuestas pending_review: proposer, fecha, target_template, hash test.
- Click → vista detalle: código + audit + descarga test_data anonimizado + último ExtractionResult.
- Botón "Re-ejecutar test" (POST admin-retest) → muestra hash_matches.
- Botones "Aprobar" (deshabilitado si último retest hace >10 min o hash_matches=false) y "Rechazar con nota".

Hooks (Orval): useProposeScript, useAnonymizeTestData, useTestScript, useValidateTestResult, useSaveToPrivateTemplate, useSubmitForReview, useGetPendingScripts, useAdminRetest, useApproveScript, useRejectScript.

Tests Vitest RED → GREEN:
- should_block_next_step_until_audit_passes
- should_block_save_button_until_test_validated
- should_require_anonymization_for_platform_target
- should_invalidate_later_steps_when_code_regenerated
- should_disable_approve_when_admin_retest_stale
- should_show_hash_match_indicator_in_review_queue
- should_redirect_non_admin_away_from_review_queue
- should_call_save_to_private_template_for_user_target
- should_call_submit_for_review_for_platform_target

Criterio de done:
- 9 tests verdes.
- Rutas registradas en App.tsx: /redaccion/scripts/wizard y /redaccion/scripts/review (admin-only).
- i18n: todas las etiquetas vía i18next (es/en/ca).
- Cero hardcoded strings en UI.
- TypeScript limpio (`npx tsc -p tsconfig.app.json --noEmit`).
```

---

### Prompt 9R.7.6 (RED/GREEN) — Simplificación de etiquetas de estado y mensajes al usuario final

**Modelo sugerido**: **Sonnet** — alcance pequeño y bien definido (mapper de status + componente StatusBadge + BlockDebugPanel admin-only). Sin decisiones abiertas.

```markdown
# PROMPT 9R.7.6 (RED/GREEN) — Mensajes amigables para el usuario; detalle técnico solo para admin

Objetivo: la máquina de estados interna del backend tiene 9+ estados (draft, missing_input, extracted, ai_generated, needs_review, approved, rejected, locked, failed) más failure_kind. La UI debe traducir esto a un vocabulario reducido y comprensible para el usuario final, manteniendo el detalle técnico accesible solo en un panel debug visible a admin/partner.

Estructura nueva:
- frontend/src/redaccion/utils/statusLabels.ts
- frontend/src/redaccion/components/BlockDebugPanel.tsx
- frontend/src/shared/i18n/locales/{es,en,ca}/redaccion.json (nuevo namespace)

statusLabels.ts:
- mapBlockStatusToUserLabel(status: string, failure_kind?: string): { label: string, tone: 'neutral'|'info'|'warning'|'success'|'error' }
  - draft, missing_input    → { label: t('redaccion.status.missing_data'), tone: 'warning' }
  - extracted               → { label: t('redaccion.status.data_loaded'), tone: 'info' }
  - ai_generated, needs_review → { label: t('redaccion.status.needs_review'), tone: 'info' }
  - approved, locked        → { label: t('redaccion.status.approved'), tone: 'success' }
  - failed                  → { label: t('redaccion.status.error_recoverable'), tone: 'error' }
  - rejected                → { label: t('redaccion.status.rejected_retry'), tone: 'warning' }
- mapWorkspaceStatusToUserLabel(status): análogo para workspace (assembled → "Listo para exportar", etc.).

Modificaciones obligatorias en componentes existentes:
- BlockEditor.tsx, AIBlockReviewPanel.tsx, WorkspaceStatusBar.tsx, DataQualityPanel.tsx: SUSTITUIR la renderización cruda del status string por <StatusBadge label={...} tone={...} />.
- Crear StatusBadge en frontend/src/shared/components/StatusBadge.tsx (componente genérico reutilizable).

BlockDebugPanel.tsx:
- Solo se monta si useAuth().user.role in ('admin','partner').
- Toggle "Detalles técnicos" (off por defecto).
- Cuando se activa, muestra: status interno, failure_kind, last_error_message, retry_attempts, updated_at, audit events más recientes.
- Aparece como sección colapsable al final de BlockEditor.

Mensajes de error:
- last_error_message del backend NO se muestra al usuario final tal cual. Se reemplaza por traducción del failure_kind:
  - ai_failed         → "La IA no pudo generar este bloque. Puedes reintentarlo."
  - extraction_failed → "No se pudieron extraer datos del documento. Revisa el archivo y reintenta."
  - script_failed     → "El cálculo automático falló. Contacta con el administrador."
  - validation_failed → "Los datos no cumplen el formato esperado."
- El last_error_message original queda accesible solo desde BlockDebugPanel.

Tests Vitest RED → GREEN:
- should_render_user_label_not_internal_status
- should_map_failed_to_recoverable_error_tone
- should_not_show_last_error_message_to_regular_user
- should_show_last_error_message_in_debug_panel_for_admin
- should_hide_debug_panel_for_user_role
- should_translate_failure_kind_to_friendly_message

Criterio de done:
- 6 tests verdes.
- Ningún componente de redacción muestra el string crudo de status (grep negativo: `\{block\.status\}` no aparece en JSX).
- i18n en 3 idiomas.
- TypeScript limpio.
```

---

### Prompt 9R.8.1 (RED/GREEN) — Endpoints HITL por bloque

```markdown
# PROMPT 9R.8.1 (RED/GREEN) — Endpoints de transición de bloques

Objetivo: exponer las transiciones de BlockStatus como endpoints HTTP, delegando en BlockStateMachine.

Endpoints (en server/app/routers/redaccion/workspaces_router.py — Deploy: edge):
- PATCH /api/v1/redaccion/workspaces/{workspace_id}/blocks/{block_id}/approve
- PATCH /api/v1/redaccion/workspaces/{workspace_id}/blocks/{block_id}/reject
- PATCH /api/v1/redaccion/workspaces/{workspace_id}/blocks/{block_id}/regenerate
- PATCH /api/v1/redaccion/workspaces/{workspace_id}/blocks/{block_id}/edit  (override de content por usuario)
- POST  /api/v1/redaccion/workspaces/{workspace_id}/resume                 (reanuda DraftingCoreGraph)

Reglas:
- Solo el owner del workspace o admin/partner pueden transicionar.
- Cada transición registra audit event en la tabla `hub_workspace_audit_events`.
- regenerate dispara un nuevo AIAssistDraftNode para ese bloque solamente.

Tests (RED → GREEN):
- test_approve_block_transitions_to_approved
- test_reject_block_transitions_to_rejected
- test_regenerate_calls_ai_node_only_for_that_block
- test_edit_block_overrides_content_and_records_original
- test_resume_workspace_continues_graph_from_review_gate
- test_non_owner_cannot_transition_blocks

Criterio de done:
- Tests verdes (6/6).
- Endpoints en OpenAPI.
```

---

### Prompt 9R.8.2 (RED/GREEN) — Tests E2E de transiciones

**Modelo sugerido**: **Sonnet** — escenarios E2E explícitos, fixtures DB. Trabajo metódico, sin decisiones abiertas.

```markdown
# PROMPT 9R.8.2 (RED/GREEN) — Tests E2E de edición/rechazo/regeneración

Objetivo: cubrir el flujo completo de HITL con tests de integración usando DB real.

Escenarios E2E (en server/tests/modules/redaccion/e2e/):
1. test_e2e_user_approves_all_blocks_and_assembles
2. test_e2e_user_rejects_ai_block_then_regenerates_then_approves
3. test_e2e_user_edits_ai_block_content_and_original_preserved
4. test_e2e_user_with_missing_input_resumes_after_upload
5. test_e2e_admin_locks_block_to_prevent_further_changes

Cada test:
- Crea template + workspace.
- Sube fixtures.
- Recorre los endpoints de 9R.8.1.
- Verifica estado final del workspace, los blocks y el RunManifest.

Criterio de done:
- 5/5 tests E2E verdes.
- DB se limpia entre tests.
- Tiempo total < 30s.
```

---

### Prompt 9R.9.1 (RED/GREEN) — DraftingRunManifest modelo + repo + endpoint

**Modelo sugerido**: **Sonnet** — contrato Pydantic + repo + 2 endpoints GET. Patrón conocido sin sorpresas.

```markdown
# PROMPT 9R.9.1 (RED/GREEN) — DraftingRunManifest

Objetivo: implementar el modelo Pydantic, el repo y el endpoint de consulta del manifest.

DraftingRunManifest (en server/app/modules/redaccion/contracts/manifest.py):
- workspace_id: UUID
- template_id: UUID
- template_version_id: UUID
- report_profile: ReportProfileId
- uploaded_documents: list[UploadedDocumentInfo]
- input_contract_validation: InputContractValidationResult
- extracted_blocks: list[ExtractedBlockSummary]
- ai_blocks: list[AIBlockSummary]    # incluye model_used, prompt_version
- model_used: str | None             # último modelo usado
- prompt_versions: list[str]
- citations: list[Citation]
- warnings: list[ExtractionWarning]
- user_approvals: list[ApprovalRecord]
- final_document_hash: str | None
- created_at: datetime

Endpoints:
- GET /api/v1/redaccion/workspaces/{workspace_id}/manifest
- GET /api/v1/redaccion/manifests/{manifest_id}

Tests (RED → GREEN):
- test_run_manifest_created_for_each_drafting_run
- test_run_manifest_records_uploaded_documents
- test_run_manifest_records_extracted_blocks
- test_run_manifest_records_ai_blocks_and_model
- test_run_manifest_records_user_approvals
- test_run_manifest_endpoint_returns_full_payload
- test_run_manifest_is_immutable

Criterio de done:
- Tests verdes (7/7).
- Manifest expuesto en OpenAPI.
- Endpoint GET disponible para frontend de 1C.4.
```

---

### Prompt 9R.9.2 (RED/GREEN) — Integración con ExportService (1C.4) — DOCX-only en MVP

**Modelo sugerido**: **Sonnet** — generación DOCX con python-docx + smoke tests + chequeo opcional LibreOffice. Sin decisiones abiertas.

```markdown
# PROMPT 9R.9.2 (RED/GREEN) — Conexión con exportación DOCX

Objetivo: garantizar que la exportación a DOCX (prompt 1C.4) consume el manifest y lo incluye en el anexo de auditoría.

Alcance MVP: SOLO DOCX. ODT queda fuera del MVP — la abstracción `Exporter` se mantiene para que ODT entre como segunda implementación post-MVP sin rework.

Cambios:
- En 1C.4 (export_service): leer el manifest del workspace antes de exportar.
- Si manifest.final_document_hash es None → ExportService rechaza la exportación.
- Adjuntar como anexo: tabla con uploaded_documents, ai_blocks (model + prompt_version), user_approvals, warnings.
- Smoke test que abra el DOCX generado con python-docx para validar estructura básica.
- Si se detecta `libreoffice` en PATH, smoke test adicional convirtiéndolo a PDF para verificar compatibilidad.

Tests (RED → GREEN):
- test_export_service_reads_run_manifest_before_export
- test_export_service_rejects_export_without_final_hash
- test_export_appendix_includes_ai_blocks_with_model
- test_export_appendix_includes_user_approvals
- test_final_document_hash_in_export_metadata_matches_manifest
- test_docx_opens_without_errors_with_python_docx
- test_docx_renders_in_libreoffice_when_available  (skip si no hay libreoffice)

Criterio de done:
- Tests verdes (7/7, con skip condicional para libreoffice).
- Documentar en 1C.4 que requiere manifest válido y produce únicamente DOCX en esta fase.
- Marcar dependencia bidireccional: 1C.4 ↔ 9R.9.
- Documentar en `docs/REDACCION_CONTRACT_FIRST.md` que ODT está en backlog post-MVP y por qué (riesgo de incompatibilidad de estilos en LibreOffice vs Word).
```

---

### Prompt 9R.10.1 (RED) — Vertical slice E2E: tests de aceptación

**Modelo sugerido**: **Sonnet** — escritura de tests sobre comportamiento ya especificado. Si los tests fallan por motivos triviales (imports, fixtures), Sonnet basta; el wire-up complejo va en 9R.10.2.

```markdown
# PROMPT 9R.10.1 (RED) — Tests E2E del slice MVP

Objetivo: escribir los tests de aceptación end-to-end del flujo completo de GENERIC_REPORT. Deben fallar inicialmente (cubren el wire-up que aún no existe).

Escenario E2E (test_generic_report_slice_mvp.py):
1. Usuario describe el informe en NL.
2. Sistema propone draft.
3. Usuario aprueba draft → crea workspace.
4. Usuario sube Excel + PDF.
5. Sistema valida inputs.
6. Sistema ejecuta DeterministicExtractionNode (Excel → tabla, PDF → texto).
7. Sistema ejecuta AIAssistDraftNode (genera análisis + summary).
8. Sistema entra en in_review.
9. Usuario aprueba ambos bloques AI.
10. Sistema ensambla documento Markdown.
11. Sistema emite DraftingRunManifest.

Tests:
- test_user_can_create_generic_report_from_natural_language
- test_user_can_upload_excel_and_pdf_to_workspace
- test_required_inputs_are_validated
- test_excel_data_is_extracted_before_ai_drafting
- test_ai_block_requires_review
- test_final_document_contains_only_approved_blocks
- test_run_manifest_is_generated_at_end_of_slice

Criterio de RED correcto:
- Todos los tests existen y describen el comportamiento esperado.
- Fallan por ImportError, endpoint no encontrado, o estados incoherentes — no por error de sintaxis.
- Documentar qué wire-up falta en `tests/modules/redaccion/e2e/slice_mvp_status.md`.
```

---

### Prompt 9R.10.2 (GREEN) — Wire-up integral del slice

**Modelo sugerido**: **Opus** — prompt crítico del bloque: integración cruzada de 9R.1 a 9R.9, debugging multi-módulo, decisiones de wire-up dispersas. Aquí Sonnet suele pegarse en bugs sutiles; Opus reduce iteraciones de forma notable.

```markdown
# PROMPT 9R.10.2 (GREEN) — Hacer pasar el slice MVP

Objetivo: conectar todas las piezas (9R.1 a 9R.9) para que los tests de 9R.10.1 pasen.

Tareas (no implementar nuevas funcionalidades — solo wire-up):
1. Registrar todos los routers en server/app/main.py con etiqueta Deploy: edge.
2. Conectar LLMSpecService → DraftValidator → approve-as-workspace → DraftingCoreGraph.
3. Conectar endpoints de 9R.8.1 al BlockStateMachine real (no stub).
4. Asegurar que AuditLogNode persiste el manifest al final.
5. Configurar fixtures de Excel/PDF en tests/fixtures/redaccion/.
6. Wire del frontend: ReportTemplateBuilderPage, GenericReportWizard, LLMDraftPreviewPage en el router del frontend.

Tests:
- Todos los tests de 9R.10.1 deben pasar.
- Suite completa de redaccion (unit + integration + e2e) verde.

Criterio de done:
- E2E del slice MVP verde (7/7).
- No hay regresiones en otros módulos.
- `uv run pytest server/tests/modules/redaccion/ -v` pasa.
- `npm test` del frontend pasa.

Aviso: tras este prompt, los antiguos endpoints `/agents/templates`, `/agents/workspaces` y `/agents/generate-script` del 9.11a–9.11d deben eliminarse o quedar como aliases que devuelven 301 a los nuevos `/redaccion/*`. Si se eliminan, dejar tests de regresión que aseguren que no hay clientes activos usándolos.
```

---

### Continuación tras el bloque 9R

Una vez completado 9R.10.2:

- Eliminar definitivamente las tablas legacy `hub_agent_templates`, `hub_user_workspaces`, `hub_workspace_documents` del 9.11a (migración de borrado tras verificar que no quedan datos).
- Eliminar el código de `modules/agents_hub/agent/` que correspondía al pipeline antiguo de redacción (DataExtractorNode/AIDrafterNode/DocumentAssemblerNode) si todavía existe — el DraftingCoreGraph del 9R lo reemplaza.
- Reanudar la subfase 1.C: el prompt 1C.0 (Focus Mode) y 1C.4 (exportación DOCX/ODT) ya pueden apoyarse en el manifest de 9R.9.

---


---

## ~~Prompts 9.11a–9.11d~~ — REEMPLAZADOS por el bloque 9R (referencia histórica, NO ejecutar)

> Los prompts 9.11a–9.11d se mantienen aquí como contexto histórico de cómo se planteó inicialmente la redacción.
> A partir del 2026-05-11 quedan **superseded** por el BLOQUE 9R (ver arriba), que aplica el patrón contract-first del bloque 9B.
> No ejecutar estos prompts directamente. La capa de scripts seguros (9.11b) se reabsorbe en `AdminScriptExtractionPipeline` del prompt 9R.5.4.

### Prompt 9.11a - Agentes Privados: Modelos y API Base (TDD RED/GREEN)

**Objetivo**: Crear la infraestructura de backend para plantillas de informes híbridas y workspaces privados, permitiendo tanto plantillas globales (admin) como privadas (usuario).

**Instrucciones**:
```text
Actúa como experto en FastAPI y SQLAlchemy async. Implementa los modelos y endpoints base en server/app/modules/agents_hub/.

TABLAS NUEVAS (crear migración Alembic):
- `hub_agent_templates`: Plantillas (id, nombre, descripcion, system_prompt, config_hibrida JSON, is_global bool, owner_id nullable)
- `hub_user_workspaces`: Sesiones de redacción (id, template_id, user_id, estado_documento JSON, created_at, updated_at)
- `hub_workspace_documents`: Documentos subidos temporalmente a una sesión (id, workspace_id, filename, file_path)

ENDPOINTS (en `hub_agents_router.py`):
GET    /api/v1/hub/agents/templates (devuelve globales + las del user)
POST   /api/v1/hub/agents/templates (crea nueva plantilla)
POST   /api/v1/hub/agents/workspaces (instancia una sesión a partir de un template)
GET    /api/v1/hub/agents/workspaces/me
GET    /api/v1/hub/agents/workspaces/{workspace_id}
POST   /api/v1/hub/agents/workspaces/{workspace_id}/upload

TESTS REQUERIDOS:
- test_user_can_read_global_templates_and_own_templates
- test_create_workspace_from_template
- test_unauthenticated_user_cannot_access_workspaces
```

---

### Prompt 9.11b - Pipeline de Seguridad y Generación de Scripts (TDD RED/GREEN)

**Objetivo**: Servicio determinista (código plano, sin LangGraph) para generar scripts extractores seguros, con validación AST y Auditoría IA, previo a la confirmación HITL del usuario.

**Instrucciones**:
```text
Actúa como experto en Python y Seguridad. Implementa `ScriptSecurityAuditor` en server/app/modules/agents_hub/services/.

FLUJO DEL SERVICIO (Código Plano, Síncrono/Stateless):
1. Recibe el prompt natural del usuario.
2. Llama al LLM (Tier 1) para generar el script Python.
3. Validación AST: parsea con `ast.parse` y bloquea imports peligrosos (os, subprocess, sys, open). Solo permite pandas, json, math, etc.
4. Auditoría IA: Llama a un LLM Tier Superior pasando el código. Pregunta si tiene efectos colaterales. Debe devolver un JSON `{ "safe": bool, "reason": "..." }`.

ENDPOINT:
POST /api/v1/hub/agents/generate-script
Request: { "prompt": "..." }
Response: { "code": "...", "is_safe": bool, "audit_reason": "..." }
(El HITL se hará en el Frontend, el usuario decidirá si guardar este código en la plantilla).

TESTS REQUERIDOS:
- test_ast_validator_blocks_os_import
- test_ast_validator_allows_pandas
- test_security_auditor_flags_malicious_code
```

---

### Prompt 9.11c - Ensamblador Híbrido LangGraph (TDD RED/GREEN)

**Objetivo**: Implementar el grafo LangGraph para el agente redactor que combina extracción determinista con reflexión IA.

**Instrucciones**:
```text
Actúa como experto en LangGraph y Python. Crea el pipeline híbrido de redacción en server/app/modules/agents_hub/agent/.

ESTADO DEL GRAFO (`WorkspaceState`):
- `workspace_id`: str
- `chat_history`: list
- `raw_data_blocks`: dict (ej. tablas extraídas determinísticamente)
- `ai_draft_blocks`: dict (ej. reflexiones generadas por IA)
- `final_document`: str (markdown ensamblado)

NODOS A IMPLEMENTAR:
1. `DataExtractorNode`: Ejecuta el script seguro (guardado en la plantilla) sobre los documentos del workspace. Guarda en `raw_data_blocks`. NO usa el LLM para parsear datos.
2. `AIDrafterNode`: Llama al LLM pasando `raw_data_blocks` como contexto. Genera el texto reflexivo en `ai_draft_blocks`.
3. `DocumentAssemblerNode`: Usa Jinja2 para combinar ambos bloques según el layout de la plantilla, actualizando `final_document`.

TESTS REQUERIDOS:
- test_data_extractor_executes_script_deterministically
- test_ai_drafter_receives_data_as_context_only
- test_document_assembler_combines_blocks_correctly
```

---

### Prompt 9.11d - Frontend: Interfaz No-Code y Workspaces (TDD RED/GREEN)

**Objetivo**: Implementar las pantallas de creación de plantillas (HITL) y la vista de redacción (Workspace) para el usuario final, integrando los átomos de automatización.

**Instrucciones**:
```text
Actúa como experto en React y Tailwind. Implementa las vistas en frontend/src/agent/.

1. PANTALLA CREACIÓN PLANTILLAS (`AgentTemplatesPage.tsx`):
- Editor visual (No-Code, estilo TipTap) para arrastrar "Bloques de Datos" y "Bloques IA".
- Generador de Scripts e Integración de Átomos: 
  - Permite añadir un "Bloque de Transformación de Datos": UI para seleccionar tipo de transformación (agrupar, filtrar, etc.) consumiendo el backend del átomo migrado.
  - Permite añadir un "Bloque de Gráfico": UI para seleccionar tipo de gráfico (barras, líneas, pastel) consumiendo el backend del átomo de ploteo.
  - Para lógicas a medida: Input de texto natural -> botón "Generar Script IA" -> llama a `/generate-script`.
- HITL: Si `is_safe` es true, muestra la razón de auditoría en verde. Exige que el usuario clique "Aprobar y Guardar" antes de persistir la plantilla.

2. PANTALLA WORKSPACE (`AgentWorkspacePanel.tsx`):
- Split View:
  - Izquierda: Chat + Dropzone de archivos.
  - Derecha: Live Preview del `final_document` (Markdown renderizado incluyendo los gráficos generados).
- Botón "Exportar PDF/Word".

TESTS REQUERIDOS (Vitest):
- should_require_explicit_hitl_approval_before_saving_template
- should_render_split_view_with_chat_and_preview
- should_render_data_transformation_and_plot_config_ui
```


---
