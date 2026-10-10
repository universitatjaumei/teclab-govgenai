"""
Canonical enums for AutomatIA platform.
These enums are shared between server and client_app.
"""

from enum import Enum


class TaskStatus(str, Enum):
    """Status states for workflow tasks."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    PENDING_USER_VALIDATION = "pending_validation"
    USER_APPROVED = "user_approved"
    USER_REJECTED = "user_rejected"
    READY_FOR_ESCALATION = "escalation_ready"
    ESCALATED = "escalated"
    COMPLETED = "completed"
    FAILED = "failed"


class ScriptStatus(str, Enum):
    """Status states for trusted scripts."""
    DRAFT = "draft"
    PUBLISHED = "published"
    DEPRECATED = "deprecated"
    REJECTED = "rejected"


class ExtractionPhase(str, Enum):
    """Phases in the document extraction pipeline."""
    DISCOVERY = "discovery"
    CALIBRATION = "calibration"
    EXTRACTION = "extraction"
    VALIDATION = "validation"
    GENERATION = "generation"
    AUDIT = "audit"


class TriggerType(str, Enum):
    """Types of workflow triggers."""
    MANUAL = "manual"
    SCHEDULE = "schedule"
    EMAIL = "email"
    FILE = "file"
    API = "api"
    WEBHOOK = "webhook"
    WEB = "web"


class StepType(str, Enum):
    """Types of workflow steps."""
    # === PROCESADORES (Processors) ===
    EXTRACTION = "extraction"
    ETL_TRANSFORM = "etl_transform"
    CUSTOM_SCRIPT = "custom_script"
    RPA_EXECUTE = "rpa_execute"
    NAVIGATION = "navigation"
    REPORT_GENERATE = "report_generate"
    ANONYMIZATION = "anonymization"
    MASKING = "masking"
    GRAPHICS = "graphics"        # Generación de gráficos (antes de informes)
    PDF_TOOLS = "pdf_tools"      # Herramientas PDF: unir, dividir, optimizar
    LLM_PROCESS = "llm_process"  # Procesamiento de texto con LLM

    # === DISPARADORES (Triggers) ===
    FOLDER_WATCHER = "folder_watcher"
    EMAIL_WATCHER = "email_watcher"
    WEB_WATCHER = "web_watcher"  # Monitor de cambios en páginas web
    SCHEDULER = "scheduler"  # Programador de ejecuciones

    # === ENTRADAS (Inputs) ===
    SQL_QUERY = "sql_query"
    API_FETCH = "api_fetch"
    FOLDER_SCAN = "folder_scan"  # Escaneo pasivo de carpeta
    EMAIL_SCAN = "email_scan"    # Recolector de adjuntos

    # === SALIDAS (Outputs) ===
    SQL_INSERT = "sql_insert"
    SMTP = "smtp"
    EMAIL_SEND = "email_send"
    ARCHIVE_FILE = "archive_file"  # Archivar resultado en carpeta

    # === LEGACY / CONEXIONES ===
    ETL = "etl"  # DEPRECATED: Usar ETL_TRANSFORM
    EMAIL = "email"  # Alias de EMAIL_WATCHER
    WEBHOOK = "webhook"  # ELIMINADO: No viable en instalaciones locales
    CONNECTION = "connection"  # Credenciales reutilizables


class AtomCategory(str, Enum):
    """
    Categorías funcionales de átomos (5 capas).

    Taxonomía unificada para organizar todos los tipos de átomos
    según su función en el flujo de datos.
    """
    TRIGGER = "trigger"       # Disparadores: inician flujos
    INPUT = "input"           # Entradas: obtienen datos externos
    PROCESSOR = "processor"   # Procesadores: transforman datos
    OUTPUT = "output"         # Salidas: envían o almacenan resultados
    UTILITY = "utility"       # Utilidades: herramientas auxiliares


class AutomationType(str, Enum):
    """Types of automations available in the library."""
    PDF_EXTRACTOR = "pdf_extractor"
    RPA_WEB = "rpa_web"
    ETL_TRANSFORM = "etl_transform"
    CHART_GENERATOR = "chart_generator"
    CUSTOM_SCRIPT = "custom_script"
    WORKFLOW = "workflow"


__all__ = [
    "TaskStatus",
    "ScriptStatus",
    "ExtractionPhase",
    "TriggerType",
    "StepType",
    "AtomCategory",
    "AutomationType",
    "InputType",
]


class InputType(str, Enum):
    """Tipos de datos soportados para entradas de tareas."""
    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    LIST = "list"
    DICT = "dict"
    FILE = "file"

