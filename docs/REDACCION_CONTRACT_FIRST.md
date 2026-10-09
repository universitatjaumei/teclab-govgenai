# Bloque 9R — Redacción Contract-First

> Documento de decisiones de arquitectura. Autosuficiente: cualquier dev nuevo puede
> entender qué hace el bloque 9R sin leer el plan completo.

---

## Propósito

El bloque 9R implementa el sistema de **redacción asistida por IA** de Gov Gen AI Platform.
Permite generar informes estructurados combinando:

- **extracción determinista** de datos desde Excel/PDF/tablas,
- **asistencia LLM** para secciones narrativas,
- **revisión humana explícita (HITL)** bloque a bloque antes de ensamblar el documento final,
- **trazabilidad completa** mediante `DraftingRunManifest`.

El módulo reemplaza el antiguo `config_hibrida JSON` y los prompts 9.11a–9.11d (superseded).

---

## Decisiones de diseño

### 1. No grafo monolítico
El `DraftingCoreGraph` es el grafo común para todos los tipos de informe. La variación entre
tipos se resuelve mediante `ReportProfile`, no mediante condicionales `if/else` dentro del core.
Cada perfil selecciona su propio conjunto de pipelines de extracción y políticas de revisión.

### 2. Contratos versionados
El antiguo `config_hibrida JSON` desaparece. Se sustituye por `ReportTemplateContract` con
`version_id`, esquema validable (Pydantic) y serialización estable para OpenAPI. Los workspaces
quedan anclados a una `template_version_id` concreta; la migración es una acción explícita del
usuario, nunca automática.

### 3. UI por contrato
El frontend no tiene pantallas hardcoded por tipo de informe. Renderiza `ReportUIContract`
recibido del backend, usando `react-hook-form` + `zodResolver` + tipos generados por Orval.
Está prohibido crear interfaces TypeScript manuales para DTOs de redacción.

### 4. LLM propone, humano aprueba
El asistente LLM genera un `ReportTemplateDraft` → pasa por validador estructural → se muestra
como vista previa editable → requiere aprobación HITL → se persiste como plantilla o workspace
ad hoc. El LLM no puede crear plantillas persistentes sin aprobación humana.

### 5. Extracción determinista primero
Excel y PDF se parsean con código (`pandas`, `pdfplumber`, `camelot`), nunca con LLM como
mecanismo principal. Los scripts generados por IA son una extensión controlada con HITL + AST +
auditoría (refactor de 9.11b). La IA interviene solo cuando el código estructurado no es
suficiente (secciones narrativas, resúmenes, reescrituras).

### 6. Estados de bloque explícitos
Cada bloque tiene un estado en la máquina de estados:

```
draft → missing_input
      → extracted
      → ai_generated → needs_review → approved → locked
                                    → rejected → (retry)
      → failed (con failure_kind + retry_policy)
```

Un bloque IA sin estado `approved` no entra en el documento final. Un bloque requerido sin
datos bloquea el ensamblado. Los bloques `failed` propagan el fallo a sus dependientes según
la topología del grafo.

### 7. RunManifest obligatorio
Ninguna exportación procede sin un `DraftingRunManifest` con todos los campos requeridos:
`workspace_id`, `template_version_id`, `report_profile`, `uploaded_documents`,
`input_validation`, `extracted_blocks`, `ai_blocks`, `model_used`, `prompt_versions`,
`citations`, `warnings`, `user_approvals`, `final_document_hash`.
El manifest se emite incluso si la ejecución falla (para auditoría).

### 8. Edge/Cloud
Los módulos 9R son **edge**: procesan documentos y expedientes del cliente. Los routers
se etiquetan `Deploy: edge` y no importan módulos cloud directamente. La configuración
se lee vía `ConfigProvider`. Ver `AGENTS.md` §Frontera Edge-Cloud.

---

## Diagrama del DraftingCoreGraph

```
LoadTemplateNode
  │  Carga ReportTemplateContract (version anclada) + WorkspaceState
  ▼
ValidateInputContractNode
  │  Valida que los inputs del workspace satisfacen InputContract de la plantilla
  ▼
FileNormalizationNode
  │  Normaliza documentos subidos → formatos internos (Markdown, DataFrame, bytes)
  ▼
DeterministicExtractionNode
  │  Ramifica por tipo de bloque:
  │    Excel          → ExcelExtractionPipeline
  │    PDFText        → PDFTextExtractionPipeline
  │    PDFTable       → PDFTableExtractionPipeline
  │    Manual         → ManualInputPipeline
  │    AdminScript    → AdminScriptExtractionPipeline
  ▼
DataQualityCheckNode
  │  Verifica completitud, rango, formato de cada campo extraído
  │  → marca bloques con estado missing_input / extracted
  ▼
MissingDataQuestionNode          [HITL — solicita inputs faltantes al usuario]
  │  Genera preguntas para bloques en missing_input
  │  Espera respuesta antes de continuar
  ▼
AIAssistDraftNode
  │  LLM con contexto de datos validados como contexto
  │  → genera texto para bloques AI_ASSISTED_TEXT / AI_SUMMARY / AI_REWRITE
  │  → estado: ai_generated
  ▼
CitationAndTraceabilityNode
  │  Anota fuente (documento, página, celda) de cada fragmento
  │  → adjunta CitationBlock a cada bloque IA
  ▼
UserReviewGateNode               [HITL — aprueba / rechaza / regenera por bloque]
  │  Bloquea el ensamblado hasta que todos los bloques IA estén approved
  │  Bloques rechazados vuelven a AIAssistDraftNode
  ▼
ApplyUserEditsNode
  │  Incorpora ediciones manuales del usuario sobre bloques aprobados
  ▼
FinalAssemblerNode
  │  Ensambla secciones en orden; solo incluye bloques con estado approved/locked
  │  → genera PreviewPayload compartido con ExportService (1C.4)
  ▼
AuditLogNode
     Emite DraftingRunManifest con todos los campos requeridos
     Persiste en hub_run_manifests
```

---

## Mapa de ejecución — bloque 9R

```
9R.0   (DOC)        Decisiones de arquitectura + nota en el plan          ← ESTE DOC

── Contratos ──
9R.1.1 (RED/GREEN)  ReportTemplateContract + ReportTemplateVersion (Pydantic + OpenAPI)
9R.1.2 (RED/GREEN)  InputContract + BlockContract + ReportUIContract
9R.1.3 (RED/GREEN)  WorkspaceState + BlockState + ReportTemplateDraft (runtime)
9R.1.4 (RED/GREEN)  Migración Alembic: hub_report_templates / hub_workspaces
                                       hub_workspace_blocks / hub_run_manifests

── Perfiles ──
9R.2.1 (RED/GREEN)  ReportProfile registry + GENERIC_REPORT como perfil obligatorio
9R.2.2 (RED/GREEN)  Estructura inicial GENERIC_REPORT (secciones, bloques, inputs)

── Bloques ──
9R.3.1 (RED/GREEN)  Tipos de bloque (STATIC_TEXT, USER_INPUT, DETERMINISTIC_DATA,
                                     TABLE, CHART, DATA_TRANSFORM, AI_ASSISTED_TEXT,
                                     AI_SUMMARY, AI_REWRITE, CITATION_BLOCK, REVIEW_GATE)
9R.3.2 (RED/GREEN)  BlockState machine + reglas de transición + invariantes
9R.3.3 (RED/GREEN)  BlockReference + projection + orden topológico + detección de ciclos

── LLMSpec ──
9R.4.1 (RED/GREEN)  LLMSpecService: lenguaje natural → ReportTemplateDraft
9R.4.2 (RED/GREEN)  Validador estructural + rechazo de drafts con tipos no permitidos
9R.4.3 (RED/GREEN)  Endpoints preview/approve + HITL (admin: plantilla; user: workspace ad hoc)
9R.4.4 (RED/GREEN)  Versionado de plantillas: política de anclaje + endpoints de migración

── Extracción ──
9R.5.1 (RED/GREEN)  Protocolo ExtractionPipeline + contratos (Input/Result/Provenance/Warning)
9R.5.2 (RED/GREEN)  ExcelExtractionPipeline + PDFTextExtractionPipeline
9R.5.3 (RED/GREEN)  PDFTableExtractionPipeline + ManualInputPipeline
9R.5.4 (RED/GREEN)  ExtractionPipelineFactory + AdminScriptExtractionPipeline

── CoreGraph ──
9R.6.1 (RED/GREEN)  LoadTemplate / ValidateInputContract / FileNormalization
9R.6.2 (RED/GREEN)  DeterministicExtraction / DataQualityCheck / MissingDataQuestion
9R.6.3 (RED/GREEN)  AIAssistDraft / CitationAndTraceability
9R.6.4 (RED/GREEN)  UserReviewGate / ApplyUserEdits / FinalAssembler
9R.6.5 (RED/GREEN)  AuditLog + DraftingRunManifest + instrumentación Langfuse
9R.6.6 (RED/GREEN)  Fallback paths + BlockState=failed + política de retry + propagación

── UI (Frontend) ──
9R.7.1 (RED/GREEN)  ReportUIContractRenderer + DynamicUploadSlots + DynamicFieldRenderer
9R.7.2 (RED/GREEN)  BlockEditor + AIBlockReviewPanel + DataQualityPanel + WorkspaceStatusBar
9R.7.3 (RED/GREEN)  ReportTemplateBuilderPage (admin) + GenericReportWizard (user)
9R.7.4 (RED/GREEN)  LLMDraftPreviewPage + flujo de aprobación

── HITL ──
9R.8.1 (RED/GREEN)  HITL endpoints + servicios de transición de bloques
9R.8.2 (RED/GREEN)  Tests E2E de edición/rechazo/regeneración por bloque

── RunManifest ──
9R.9.1 (RED/GREEN)  DraftingRunManifest modelo Pydantic + repo + endpoint
9R.9.2 (RED/GREEN)  Integración con ExportService (1C.4) + final_document_hash

── Vertical Slice ──
9R.10.1 (RED)       Tests de aceptación E2E del slice completo
9R.10.2 (GREEN)     Wire-up integral del slice
```

---

## Reglas duras

1. **No existe `config_hibrida JSON` libre.** Cualquier dato de configuración va en un
   `ReportTemplateContract` versionado.
2. **Los routers HTTP devuelven modelos Pydantic específicos.** Nunca devolver modelos ORM
   directamente.
3. **El frontend usa exclusivamente tipos generados por Orval.** Está prohibido crear
   interfaces TypeScript manuales para DTOs de redacción.
4. **El LLM no puede crear plantillas persistentes sin aprobación HITL.** Solo genera
   `ReportTemplateDraft`.
5. **Ningún bloque IA entra al documento final sin estado `approved`.** El `UserReviewGateNode`
   bloquea el ensamblado.
6. **Toda ejecución del agente emite `DraftingRunManifest`**, incluso si falla. La exportación
   a DOCX/ODT (1C.4) requiere manifest válido.
7. **Módulos 9R son edge.** Routers etiquetados `Deploy: edge`; no importan módulos cloud.
8. **TDD obligatorio.** RED antes que GREEN; ningún PR del bloque se acepta sin tests del
   nuevo contrato o comportamiento.

---

## Versionado de plantillas y migración de workspaces

### Política de anclaje (no negociable)

Un `HubWorkspace` queda anclado a su `template_version_id` para siempre:

- **Publicar vN+1 NO migra automáticamente** los workspaces existentes.
- El propietario del workspace recibe un aviso ("Plantilla actualizada — versión vN+1 disponible") en `WorkspaceStatusBar` (9R.7.2) consultando `GET /api/v1/hub/redaccion/workspaces/{id}/template-update-notice`.
- La migración es un **acto explícito**: `POST /api/v1/hub/redaccion/workspaces/{id}/migrate`.

### Qué hace la migración

1. Detecta `breaking_changes` entre la versión actual y la versión objetivo (nuevos `required_slots` no presentes en el workspace actual).
2. Si hay `breaking_changes` → `409 Conflict` con `compatibility_errors: [{slot_id, reason}]`. El usuario debe rellenar los nuevos slots manualmente tras crear el workspace.
3. Si es compatible → crea un workspace nuevo:
   - `template_version_id = target_version_id`
   - `inputs_json` copiado verbatim del workspace original
   - `parent_workspace_id = original_workspace.id` (trazabilidad de auditoría)
   - **No se copian** outputs de bloques ni registros de aprobación (el nuevo workspace empieza desde cero).
4. Archiva el workspace original: `status = "archived"`, `archived_reason = "migrated_to_{new_id}"`.
5. El workspace original sigue siendo accesible para auditoría; su `run_manifest_id` no se toca.

### Columnas añadidas a `hub_workspaces` (migración n5c6d7e8f9a0)

| Columna | Tipo | Descripción |
|---------|------|-------------|
| `parent_workspace_id` | UUID FK nullable | Apunta al workspace original tras una migración |
| `archived_reason` | String(500) nullable | Razón del archivado (ej. `"migrated_to_{new_id}"`) |

El campo `status` ya admite `"archived"` a nivel de app (tipo `String(30)`, sin enum DB).

### Servicio

```
server/app/modules/redaccion/services/template_migration_service.py

TemplateMigrationService.detect_new_version(workspace_id) -> NewVersionNotice | None
TemplateMigrationService.migrate_workspace(workspace_id, target_version_id, user_id) -> HubWorkspace

NewVersionNotice:
  current_version_id: UUID
  latest_version_id: UUID
  changes_summary: str
  breaking_changes: list[BreakingChange]  # [] si no hay cambios disruptivos

CompatibilityConflictError  → capturada por el router → 409
WorkspaceOwnershipError     → capturada por el router → 403
```

### Endpoints (Deploy: edge)

```
GET  /api/v1/hub/redaccion/workspaces/{id}/template-update-notice
     → 200 NewVersionNotice | 204 si ya alineado

POST /api/v1/hub/redaccion/workspaces/{id}/migrate
     Body: { target_version_id: UUID }
     → 201 { new_workspace_id: UUID }
     → 409 { compatibility_errors: [{slot_id, reason}] }
     → 403 si el llamante no es el owner
```

---

## Módulo de anonimización (9R.5.5)

El módulo `server/app/modules/redaccion/services/anonymization/` proporciona
detección y sustitución determinista de PII (regex + spaCy NER + anclajes
de formulario), reutilizado por dos flujos:

1. **TestDataAnonymizerService** (`services/test_data_anonymizer.py`) —
   anonimiza datos de prueba sintéticos para el workflow de scripts
   (`/api/v1/redaccion/scripts/{id}/anonymize-test-data`). Obligatorio
   cuando `target_owner_kind = 'platform'`.
2. **Fase 13 (NER reversible)** — hooks `pre_llm` / `post_llm` dentro de
   `DraftingCoreGraph` que reutilizan `PiiDetector` para anonimizar texto
   antes de enviarlo al LLM y recomponerlo a la salida (próximo prompt 13.1).

### Origen y migración

Migrado de `client_app/app/modules/privacy/` (1011 LOC). Adaptaciones duras:

- **`StorageRef` en lugar de `Path`**: todas las firmas públicas reciben
  referencias de storage y leen/escriben vía `StorageService` (fsspec).
- **Async**: las operaciones de I/O son `async`; la detección/sustitución
  CPU-bound sigue síncrona.
- **Sin `EncryptionService`**: el determinismo se obtiene por instancia
  (`FakerGenerator(seed=...)`). El mapa ficticio→real **no se persiste**
  (`save_state` / `load_state` son no-op explícitos): en el flujo de scripts todo
  trabaja sobre el sintético, y desde #251 ni se guarda en la propuesta ni se
  devuelve; lo subido se borra al anonimizar y al cerrar la propuesta.
- **Sin `enterprise_audit_service`**: la auditoría la delega el llamador a
  `hub_workspace_audit_events` (existente desde 9R.8.1).
- **Fallback explícito sin spaCy**: si el modelo no carga, degrada a
  `regex + anclajes` y emite warning en logs. Los flujos siguen funcionando.
- **Mantenida Disposición Adicional Séptima LOPDGDD** (`anonymize_document_id(mode='AEPD')`).

### Componentes

| Archivo | Responsabilidad |
|---------|-----------------|
| `anonymizer.py` | `AnonymizationContext` — motor híbrido regex + NER + anclajes. |
| `faker_generator.py` | Generación determinista de valores sintéticos con cache. |
| `pii_detector.py` | Wrapper ligero: `scan_dataframe()`, `detect_spans()`, `ColumnInfo`, `PiiSpan`. |
| `policies.py` | `AnonymizerPolicy` + lista de `Strategy` predefinidas. |
| `service.py` | `AnonymizerService` — alto nivel async sobre archivos en storage. |

### Tipos PII reconocidos

DNI, NIE, IBAN, EMAIL, PHONE, PASSPORT, CREDIT_CARD, NSS, DATE, POSTAL_CODE,
PERSON_NAME (via NER + anclajes), ADDRESS, ORGANIZATION (via NER).

### Anclajes de formulario

`PiiDetector` detecta etiquetas de campo (`Nombre:`, `Apellidos:`,
`Representante Legal:`) y las marca con prioridad sobre el NER. La estructura
del formulario está disponible vía `get_form_structure_hint()` para inyectar
como contexto al LLM en tiempo de redacción.

### PDF → markdown sintético

Para PDFs, el flujo no regenera el PDF: extrae markdown con **`pdfplumber`**, lo
anonimiza y persiste un `.md`. Justificación: el pipeline de scripts trabaja
sobre `raw_text`, y regenerar el PDF añade coste sin valor en el MVP.

> **EXT.2 (2026-08-11)**: la extracción era Docling y pasó a `pdfplumber`. El alcance no cambió
> —Docling corría aquí **sin OCR**—, y Docling se retiró del servidor entero; el OCR vive en el
> pipeline de curación. Ver [`DECISION_EXTRACCION_Y_DESPLIEGUE.md`](DECISION_EXTRACCION_Y_DESPLIEGUE.md).

### Modelos spaCy

- `es_core_news_md` (español, ~40 MiB) — se instala via
  `python -m spacy download es_core_news_md` (Dockerfile durante el build).
- `en_core_web_md` (inglés) — instalable de la misma forma cuando se
  amplíe la cobertura.

---

## Workflow de scripts metaprogramados (9R.5.5 – 9R.5.6)

Los scripts de extracción generados por LLM siguen un ciclo de vida con estados
explícitos y tres gates obligatorios antes de incrustarse en una plantilla.

### Estados de `HubScriptProposal`

```
proposed → tested → pending_review → approved
                                   → rejected
```

| Estado | Descripción |
|--------|-------------|
| `proposed` | LLM propuso código; auditado con AST. |
| `tested` | Proposer ejecutó en sandbox y validó con `validate-test-result`. |
| `pending_review` | Enviado a la cola de revisión admin (solo `target_owner_kind='platform'`). |
| `approved` | Script incrustado en plantilla (privada o global). |
| `rejected` | Rechazado por admin con nota de revisión; no permite nuevas transiciones. |

### Gates obligatorios

| Gate | Cuándo | Qué verifica |
|------|--------|--------------|
| **Auditoría AST** | Al proponer | `ScriptSecurityAuditor` — imports prohibidos, builtins peligrosos. |
| **Test sandbox** | Antes de persistir | El proposer ejecuta contra datos de prueba y valida el resultado. |
| **Anonimización** | Solo para `platform` | `test_data_is_anonymized=True` exigido en `submit-for-review`. |
| **Admin retest** | Antes de `approve` | Hash del re-test admin debe coincidir y ser reciente (<10 min). |

### Flujo self-service (plantilla privada)

```
POST /propose
  → POST /{id}/anonymize-test-data   (si necesita datos sintéticos)
  → POST /{id}/test
  → POST /{id}/validate-test-result
  → POST /{id}/save-to-private-template
```

### Flujo de revisión (plantilla global)

```
POST /propose
  → POST /{id}/anonymize-test-data   (OBLIGATORIO)
  → POST /{id}/test
  → POST /{id}/validate-test-result
  → POST /{id}/submit-for-review
  ↓
  GET  /pending                       (admin/partner)
  → POST /{id}/admin-retest
  → POST /{id}/approve  |  POST /{id}/reject
```

### Incrustación del script en la plantilla

Al aprobar, se crea una nueva `HubReportTemplateVersion` con el script embebido
como un bloque `DETERMINISTIC_DATA` con `source_kind='admin_script'`:

```json
{
  "id": "<uuid>",
  "kind": "DETERMINISTIC_DATA",
  "label": "Script de extracción",
  "source_kind": "admin_script",
  "options": { "code": "...", "approved": true },
  "depends_on": []
}
```

La versión anterior sigue existente (append-only); los workspaces existentes no
migran automáticamente (ver sección "Versionado de plantillas").

### Endpoints (Deploy: edge)

| Método | Ruta | Actor | Descripción |
|--------|------|-------|-------------|
| `POST` | `/redaccion/scripts/propose` | User | Genera y persiste propuesta. |
| `POST` | `/redaccion/scripts/{id}/describe-test-data` | Proposer | Sugiere providers Faker por columna. |
| `POST` | `/redaccion/scripts/{id}/preview-pdf-spans` | Proposer | Detecta spans PII en PDF. |
| `POST` | `/redaccion/scripts/{id}/anonymize-test-data` | Proposer | Genera datos sintéticos. |
| `POST` | `/redaccion/scripts/{id}/test` | Proposer | Ejecuta en sandbox, persiste hash. |
| `POST` | `/redaccion/scripts/{id}/validate-test-result` | Proposer | Marca test validado. |
| `POST` | `/redaccion/scripts/{id}/save-to-private-template` | Proposer | Incrusta en plantilla propia. |
| `POST` | `/redaccion/scripts/{id}/submit-for-review` | Proposer | Envía a cola admin (solo `platform`). |
| `GET` | `/redaccion/scripts/pending` | Admin/Partner | Lista cola de revisión. |
| `POST` | `/redaccion/scripts/{id}/admin-retest` | Admin/Partner | Re-ejecuta y compara hash. |
| `POST` | `/redaccion/scripts/{id}/approve` | Admin/Partner | Aprueba e incrusta en plantilla global. |
| `POST` | `/redaccion/scripts/{id}/reject` | Admin/Partner | Rechaza con nota. |

---

## Glosario

| Término | Definición |
|---------|------------|
| **ReportProfile** | Identificador del tipo de informe (`GENERIC_REPORT`, futuro `ACTA_REUNION`, etc.). Determina qué secciones, bloques y pipelines de extracción están disponibles. |
| **ReportTemplateContract** | Contrato serializable (Pydantic + OpenAPI) que describe la estructura de un tipo de informe: secciones, bloques, inputs requeridos, políticas de IA y exportación. Versionado e inmutable una vez publicado. |
| **BlockContract** | Especificación de un bloque individual dentro de una plantilla: tipo, inputs aceptados, reglas de validación, política de revisión. |
| **ReportUIContract** | Subconjunto del contrato dirigido al frontend. Describe qué componentes renderizar, en qué orden, con qué validaciones. El frontend lo consume via Orval; nunca lo hardcodea. |
| **BlockState** | Estado de un bloque dentro de un workspace activo: `draft → missing_input / extracted → ai_generated → needs_review → approved / rejected → locked`. Estado adicional: `failed` (con `failure_kind`). |
| **DraftingRunManifest** | Registro completo e inmutable de una ejecución del agente de redacción: documentos subidos, resultados de extracción, bloques IA generados, modelo/versiones de prompt usados, citas, advertencias, aprobaciones del usuario, hash del documento final. |
| **ReportTemplateDraft** | Propuesta temporal generada por `LLMSpecService` a partir de lenguaje natural. No es persistente; requiere validación estructural + aprobación HITL antes de convertirse en `ReportTemplateContract`. |
| **ExtractionPipeline** | Protocolo que encapsula la lógica de extracción de datos desde un tipo de fuente (Excel, PDFText, PDFTable, Manual, AdminScript). Devuelve `ExtractionResult` con datos, provenance y warnings. |
| **NewVersionNotice** | DTO devuelto por `TemplateMigrationService.detect_new_version()`. Informa al propietario de que hay una versión más reciente disponible e indica si hay `breaking_changes` en el `InputContract`. |
| **Operation** | Transformación tabular declarativa (discriminated union por `op`): `FilterOp`, `AggregateOp`, `JoinOp`, `PivotOp`, `NormalizeOp`, `GroupByOp`. Ejecutada por `DeterministicETLService` o generada por `ETLFactory`. |
| **DataTransformBlock** | Block kind que aplica transformaciones tabulares (modo determinista o IA) entre la extracción y los nodos IA. La IA produce una `list[Operation]` auditable; si no encaja en el catálogo, fallback a script Python auditado. |

---

## Bloques de transformación (9R.5.8)

`DATA_TRANSFORM` es el 11º block kind. Se ejecuta **entre** `DeterministicExtractionNode` y `DataQualityCheckNode` en el `DraftingCoreGraph`.

### Módulo

```
server/app/modules/redaccion/services/transformation/
  operations.py          # Discriminated union: FilterOp | AggregateOp | JoinOp | PivotOp | NormalizeOp | GroupByOp
  deterministic_etl.py   # DeterministicETLService.execute(df, ops, joinable_resolver?)
  etl_factory.py         # ETLFactory.generate_operations_from_nl(nl, schema) → ETLPlan
  etl_service.py         # ETLService.run(df, mode, ...) → ETLServiceResult
```

### Modos

| Modo | Flujo |
|------|-------|
| `deterministic` | `config.operations` → `DeterministicETLService.execute(df, ops)` |
| `ai` | `nl_instruction` → `ETLFactory` → `list[Operation]` → `DeterministicETLService` (con refinamiento iterativo, max 3 intentos) |

Si el LLM no consigue producir operaciones válidas tras 3 intentos, `ETLFactory` genera un script Python con `def transform(df)` y lo audita con `ScriptSecurityAuditor`. El `ETLService` ejecuta el script solo si la auditoría lo aprueba.

### JoinOp y resolución de bloques

`JoinOp.other_block_ref` contiene el `block_id` del bloque fuente del otro DataFrame. `DataTransformationNode` inyecta un `joinable_resolver` que resuelve ese `block_id` desde `state.blocks` / `state.block_outputs`.

### Cadena típica

```
DETERMINISTIC_DATA (Excel) → DATA_TRANSFORM (GroupBy región) → CHART (barras por región)
```

El `DataTransformBlock` escribe `{"rows": [...], "operations_applied": [...]}` en `state.block_outputs[block_id]`, que `ChartHandler._resolve_data()` consume directamente.

---

## Exportación DOCX (9R.9.2 / 1C.4)

`ExportService` genera el documento final en formato DOCX a partir del contenido ensamblado
y el `DraftingRunManifest`. Es la única implementación de exportación del MVP.

### Prerrequisito

`manifest.final_document_hash` **debe ser no nulo**. Si es `None`, el documento no está
ensamblado y `ExportService.export_to_docx()` lanza `ExportNotReadyError`. No hay forma de
exportar un workspace que no ha completado `FinalAssemblerNode`.

### Estructura del DOCX generado

```
[Título: "Informe Generado"]
  └─ Contenido del documento (párrafos del assembled text)

[Página nueva]
[Anexo de Auditoría]
  ├─ Hash del documento: sha256:…
  ├─ Perfil | Estado al cierre | Fecha de generación
  ├─ Tabla: Documentos subidos (slot_id, filename, tamaño)
  ├─ Tabla: Bloques IA (block_id, kind, modelo, versión prompt)
  ├─ Tabla: Aprobaciones (aprobado_por, fecha, nota)
  └─ Tabla: Advertencias de extracción (bloque, tipo, mensaje)
```

### ODT — backlog post-MVP

ODT **no está implementado** en esta fase. Las razones:

1. Las tablas de estilo en LibreOffice Writer y Microsoft Word no comparten el mismo mapa de
   estilos integrados (p.ej. `"Table Grid"` no existe en ODT nativo).
2. Las diferencias de sangría y espaciado entre ambos procesadores generan documentos
   visualmente inconsistentes sin rework de estilos.
3. El riesgo de incompatibilidad supera el beneficio en MVP donde Word/Google Docs son el
   destino dominante.

La abstracción `ExportService.export_to_docx()` no genera un protocolo `Exporter` aún, pero
el nombre del método es suficientemente específico para que ODT entre como
`export_to_odt()` en post-MVP sin romper los consumidores actuales.

### Módulo

```
server/app/modules/redaccion/services/export_service.py
  ExportNotReadyError   # final_document_hash is None
  ExportService
    .export_to_docx(manifest, document_content) → bytes
```

### Dependencia bidireccional 1C.4 ↔ 9R.9

- **9R.9** define `DraftingRunManifest` (contrato de datos) y lo expone via endpoint REST.
- **1C.4** (este prompt) produce el DOCX consumiendo ese manifest.
- El `ExportService` no accede a la base de datos directamente; recibe el manifest ya
  deserializado, lo que facilita el testing sin mock de sesión.

---

## NER reversible (Fase 13)

> Objetivo: **ningún PII real sale del edge hacia el LLM** (RGPD), pero el output final
> preserva los originales para el usuario. La reversibilidad vive en memoria durante la
> ejecución del workspace; nunca se persiste en BD ni se loguea.

### Contrato — `RunAnonymizationContext`

Ubicación: `server/app/modules/redaccion/services/anonymization/run_context.py`.

```python
class AnonymizationMode(str, Enum):
    OFF = "off"                              # PII real al LLM (solo dev/test)
    DETECT_ONLY = "detect_only"              # detecta y audita, no sustituye
    REPLACE = "replace"                      # sustituye Faker + revierte (default)
    REPLACE_WITH_DISPOSITION_7 = "replace_with_disposition_7"  # LOPDGDD para DNI/NIE/Passport

class RunAnonymizationContext(BaseModel):
    workspace_id: UUID
    mode: AnonymizationMode
    spans: list[PiiSpan]
    forward_map: dict[str, str]   # original → synthetic (NUNCA persistir)
    reverse_map: dict[str, str]   # synthetic → original (NUNCA persistir)

    def substitute(self, text: str) -> str: ...
    def reverse(self, text: str) -> str: ...
```

### Reglas duras

- `substitute()` ordena las claves por **longitud descendente** antes de reemplazar
  para evitar que "Juan García" se rompa por sustituir "Juan" primero.
- `reverse()` SÓLO sustituye cadenas **exactas** del `reverse_map`. Si el LLM "alucina"
  un nombre tipo Faker que no estaba en el mapping, queda tal cual (cero falsos positivos).
- Modo **Disposición 7 (LOPDGDD)**: DNI/NIE/Pasaporte se enmascaran con
  `****1234X` (oculta primeros caracteres, preserva los últimos 4 chars y la letra de
  control). La transformación **NO es reversible** para esos tipos — el output final
  queda enmascarado. Para el resto de tipos PII, el modo se comporta como `REPLACE`.
- Los mapas `forward_map` / `reverse_map` viven sólo en memoria. `AnonymizationSummary`
  (persistido en el manifest) expone únicamente `mode + counts_by_type + total_spans +
  detected_at`.

### Topología del grafo

```
… → data_quality_check ──(ok)──► init_anonymization ──► ai_assist_draft ──► citation_traceability → …
                       └(ask_user)──► missing_data_question
```

- `InitAnonymizationNode` corre después de la extracción determinista y antes de
  cualquier nodo que invoque el LLM. Detecta PII en `artifacts_normalized` +
  `blocks[*].content`, genera sintéticos con `FakerGenerator` (semilla determinista
  por workspace + idx) y construye el `RunAnonymizationContext` en
  `state.anonymization_context`.
- `AIAssistDraftNode` aplica `apply_pre_llm(context, ctx)` antes de llamar al LLM y
  `apply_post_llm(text, ctx)` al output. Ambos helpers son no-op en modos OFF y
  DETECT_ONLY.
- `ChartFactory.generate_script` y `ETLFactory.generate_operations_from_nl` aceptan
  un parámetro opcional `anonymization_context`: cuando se invocan desde el grafo
  con un contexto activo, sustituyen el prompt NL antes del LLM y revierten el
  código/JSON generado antes de devolverlo al llamador.

### Citas y trazabilidad

`CitationAndTraceabilityNode` construye `Citation.excerpt` a partir de
`source_block.content` (datos deterministas), nunca del output del LLM. Por tanto las
citas **siempre** contienen originales mientras el bloque fuente sea determinista —
el sintético que circula por el LLM no toca el path de citas. `source_document` y
`page` son metadata estable (no PII).

### Persistencia segura

```python
class AnonymizationSummary(BaseModel):
    mode: AnonymizationMode
    counts_by_type: dict[str, int]   # {PERSON: 5, IBAN: 2, …}
    total_spans: int
    detected_at: datetime
```

`DraftingRunManifest.anonymization_summary` se rellena al cerrar el grafo. El test
`test_anonymization_context_never_persists_forward_or_reverse_map_to_db` bloquea
estructuralmente cualquier intento futuro de añadir originales / sintéticos / mapas
al summary.

### Configuración por workspace

`HubWorkspace.anonymization_mode` (columna `String(40)`, default `replace`). La UI de
configuración (13.2) permite al owner cambiarlo antes de ejecutar el grafo; durante
la ejecución el modo queda fijado en `state.anonymization_mode`.

### Out-of-scope en Fase 1

- La integración con el módulo de expedientes (re-uso del context entre runs) llega
  en Fase 3, no aquí. En Fase 1 cada ejecución de workspace genera un context nuevo.
- La UI de auditoría (panel admin con counts_by_type + selector de modo) es la
  13.2 — el contrato del summary y los endpoints quedan listos para consumirla.
