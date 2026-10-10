"""
Data Transfer Objects (DTOs) for AutomatIA platform.
Pure Pydantic models for data exchange between server and client.
"""

from datetime import datetime
import hashlib
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict, field_validator

from automatia_shared.enums import TaskStatus, TriggerType, StepType, ScriptStatus, AutomationType
from .accounts import AdminProfileDTO, PartnerProfileDTO, ClientProfileDTO
from .trigger_payloads import (
    TriggerPayloadMeta,
    FileWatcherPayload,
    MailWatcherPayload,
    WebWatcherPayload,
    SchedulerPayload
)


class TaskSpec(BaseModel):
    """Specification for a single workflow task/step."""
    model_config = ConfigDict(use_enum_values=True)

    name: str = Field(..., description="Human-readable task name")
    type: StepType = Field(..., description="Type of task to execute")
    script_id: Optional[str] = Field(None, description="ID of script to execute (for extraction/etl)")
    config: Dict[str, Any] = Field(default_factory=dict, description="Task-specific configuration")
    # Added for Logic Unification (Prompt 2/5)
    inputs: List[str] = Field(default_factory=list, description="List of required input variable names")
    outputs: List[str] = Field(default_factory=list, description="List of produced output variable names")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata for UI/Tools")


class FlowSpec(BaseModel):
    """Specification for a complete workflow."""
    model_config = ConfigDict(use_enum_values=True)

    name: str = Field(..., description="Workflow name")
    description: Optional[str] = Field(None, description="Workflow description")
    version: str = Field(default="0.1.0", pattern=r"^\d+\.\d+\.\d+$", description="Semantic version")
    status: str = Field(default="DRAFT", description="DRAFT|PUBLISHED|DEPRECATED")
    row_version: int = Field(default=0, description="Optimistic locking version")
    trigger_type: TriggerType = Field(default=TriggerType.MANUAL, description="How the flow is triggered")
    trigger_config: Dict[str, Any] = Field(default_factory=dict, description="Trigger-specific config")
    steps: List[TaskSpec] = Field(default_factory=list, description="Ordered list of steps")
    is_active: bool = Field(default=True, description="Whether workflow is active")
    owner_scope: Optional[str] = Field(None, description="Partner or client scope identifier")
    trigger_id: Optional[int] = Field(None, description="Linked TriggerConfig ID")


class ScriptContext(BaseModel):
    """
    Contexto de ejecución para trazabilidad y auditoría.

    Se crea antes de cada ejecución de script y se asocia al resultado.
    Permite debugging remoto y análisis de errores.
    """
    model_config = ConfigDict(use_enum_values=True)

    # Identificadores únicos
    execution_id: str = Field(..., description="UUID único de esta ejecución")
    script_id: str = Field(..., description="ID del script ejecutado")
    script_version: int = Field(default=1)

    # Contexto de usuario
    user_id: Optional[str] = Field(None, description="ID del usuario que ejecutó")
    license_key: Optional[str] = Field(None, description="Licencia activa (últimos 8 chars)")
    machine_id: Optional[str] = Field(None, description="Fingerprint de la máquina")

    # Timestamps
    started_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: Optional[datetime] = None
    duration_ms: Optional[int] = None

    # Entradas utilizadas (sin datos sensibles)
    input_summary: Dict[str, str] = Field(
        default_factory=dict,
        description="Resumen de inputs (tipos, no valores)"
    )

    # Resultado
    status: TaskStatus = Field(default=TaskStatus.PENDING)
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    traceback: Optional[str] = None


class ExtractionResult(BaseModel):
    """
    Resultado estandarizado de extracción/ejecución de scripts.

    TODOS los scripts deben retornar este formato para permitir
    encadenamiento en flujos y validación post-ejecución.
    """
    model_config = ConfigDict(use_enum_values=True)

    # Datos extraídos
    datos: Dict[str, Any] = Field(default_factory=dict, description="Extracted data")

    # Metadata de la extracción
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Extraction metadata")

    # Estado
    status: TaskStatus = Field(default=TaskStatus.COMPLETED)
    error: Optional[str] = Field(None, description="Error message if failed")

    # Contexto de ejecución (trazabilidad)
    context: Optional[ScriptContext] = Field(None, description="Execution context for audit")

    # Validación contra contrato
    validation_errors: List[str] = Field(
        default_factory=list,
        description="Errores si los datos no cumplen el esquema de salida esperado"
    )

    @classmethod
    def success(cls, datos: Dict[str, Any], context: Optional[ScriptContext] = None) -> "ExtractionResult":
        """Factory para resultado exitoso."""
        return cls(datos=datos, status=TaskStatus.COMPLETED, context=context)

    @classmethod
    def failure(cls, error: str, context: Optional[ScriptContext] = None, traceback: Optional[str] = None) -> "ExtractionResult":
        """Factory para resultado fallido."""
        if context:
            context.status = TaskStatus.FAILED
            context.error_message = error
            context.traceback = traceback
        return cls(datos={}, status=TaskStatus.FAILED, error=error, context=context)


class ScriptAuditResult(BaseModel):
    """Result from script security audit."""
    is_safe: bool = Field(..., description="Whether script passed security audit")
    violations: List[str] = Field(default_factory=list, description="List of security violations")
    warnings: List[str] = Field(default_factory=list, description="Non-blocking warnings")


class AutomationBlueprintDTO(BaseModel):
    """Objeto de transferencia para la sincronización de automatizaciones (Blueprints)."""
    model_config = ConfigDict(use_enum_values=True)

    id: str
    name: str
    type: AutomationType
    code_content: str  # Script Python o JSON del workflow
    version: int = 1
    updated_at: datetime
    
    # Propiedad y Jerarquía
    client_id: Optional[str] = None
    partner_id: Optional[str] = None
    is_system_template: bool = False
    
    # --- NUEVOS CAMPOS ---
    signature: Optional[str] = None  # Firma criptográfica del contenido
    access_groups: List[str] = Field(default_factory=list)  # Etiquetas para segmentación
    is_workflow: bool = False  # True si es un flujo de múltiples pasos
    # ---------------------
    
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def get_content_hash(self) -> str:
        """
        Genera un hash MD5 del contenido del script/workflow para comparaciones rápidas.
        """
        return hashlib.md5(self.code_content.encode('utf-8')).hexdigest()

    @field_validator('updated_at', mode='before')
    @classmethod
    def parse_datetime(cls, v):
        """
        Validador para asegurar que las fechas se procesen correctamente si vienen como string ISO.
        """
        if isinstance(v, str):
            try:
                return datetime.fromisoformat(v)
            except ValueError:
                return v
        return v


__all__ = [
    "TaskSpec",
    "FlowSpec",
    "ExtractionResult",
    "ScriptContext",
    "ScriptAuditResult",
    "AutomationBlueprintDTO",
    "AdminProfileDTO",
    "PartnerProfileDTO",
    "ClientProfileDTO",
    "TriggerPayloadMeta",
    "FileWatcherPayload",
    "MailWatcherPayload",
    "WebWatcherPayload",
    "SchedulerPayload",
]
