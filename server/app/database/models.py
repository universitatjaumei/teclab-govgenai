"""
Modelos de base de datos del lado del servidor para AutomatIA Brain (SaaS).

Estos modelos se almacenan en brain_server.db y contienen:
- Configuración de IA y ajustes de modelos.
- Registros de consumo de tokens (facturación).
- Prompts del sistema y configuraciones de servicios de extracción.
- Datos de precios de modelos.
"""

from datetime import datetime
from typing import Optional, Dict, List, Any
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import JSON, DateTime, Text
from automatia_shared.enums import AutomationType
from pydantic import field_validator, ConfigDict


class AIConfig(SQLModel, table=True):
    """
    Persiste la configuración de proveedor/modelo por rol.

    Los roles definen el nivel de capacidad (Tier):
    - extraccion_pdf: Extracción rápida de texto (Tier 1).
    - logico_navegacion: Lógica y razonamiento (Tier 2).
    - supervision: Tareas complejas y generación de código (Tier 3).
    """

    role_key: str = Field(
        primary_key=True,
        description="Unique role key (e.g., 'extraccion_pdf', 'supervision')",
    )
    provider: str = Field(description="AI provider: 'google', 'openrouter'")
    model_id: str = Field(description="Model identifier")
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class TokenLog(SQLModel, table=True):
    """
    Registro unificado de consumo de tokens para fines de facturación.

    Almacena todas las llamadas a la API de los proveedores de LLM,
    permitiendo el cálculo de costes y auditoría de uso.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    script_source: str = Field(description="Module that made the call")
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cost: float = Field(default=0.0, description="Calculated cost in USD")


class ModelPricing(SQLModel, table=True):
    """
    Datos de precios de modelos por cada millón de tokens.

    Sincronizado periódicamente a través de la API de OpenRouter.
    """

    id: str = Field(
        primary_key=True, description="Model ID (e.g., 'google/gemini-1.5-flash')"
    )
    input_cost_per_m: float = Field(description="Cost per 1M input tokens")
    output_cost_per_m: float = Field(description="Cost per 1M output tokens")
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ModelCache(SQLModel, table=True):
    """
    Caché de modelos disponibles por proveedor.

    Evita llamadas repetitivas a la API para obtener la lista de modelos.
    """

    provider: str = Field(
        primary_key=True, description="Provider: 'google', 'openrouter', 'ollama'"
    )
    models: List[str] = Field(default=[], sa_column=Column(JSON))
    last_updated: datetime = Field(default_factory=datetime.utcnow)


class AutomationLibrary(SQLModel, table=True):
    """
    Repositorio central de automatizaciones (scripts y flujos).

    Soporta versionado, firmas criptográficas y grupos de acceso para
    una distribución segura de componentes.
    """

    __tablename__ = "automation_library"

    id: str = Field(primary_key=True, index=True)
    name: str = Field(index=True)
    type: AutomationType
    code_content: str = Field(sa_column=Column(Text))
    version: int = 1
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # Jerarquía y Seguridad
    client_id: Optional[str] = Field(default=None, index=True)
    partner_id: Optional[str] = Field(default=None, index=True)
    is_system_template: bool = Field(default=False)

    # --- NUEVOS CAMPOS (Sincronizados con DTO v2.0) ---
    signature: Optional[str] = Field(default=None)  # Firma del Partner/Superadmin
    is_workflow: bool = Field(
        default=False
    )  # Distingue script simple de flujo complejo
    # Almacenado como JSON/Array en la BD
    access_groups: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    # --------------------------------------------------

    metadata_json: Optional[Dict[str, Any]] = Field(default={}, sa_column=Column(JSON))


# === MULTITENANCY MODELS (Future - Phase 1) ===


class SuperAdminAccount(SQLModel, table=True):
    """
    Cuenta de Superadministrador del Sistema.

    Gestiona la plataforma global, admins y configuraciones de IA.
    """

    model_config = ConfigDict(validate_assignment=True)

    admin_id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(nullable=False)
    email: str = Field(nullable=False, sa_column_kwargs={"unique": True}, index=True)
    hashed_password: str = Field(nullable=False)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    #: Cuándo entró por última vez (issue #102). **Nulo = todavía no ha entrado**, que es un
    #: estado legítimo de una cuenta recién creada.
    #:
    #: No es un dato cosmético: `last_login_at IS NULL` es la regla de «se creó a mano y no se
    #: ha usado», y decide si una fila se puede borrar (REV.8). Sin esta columna, la pantalla de
    #: Personas decía «Nunca ha entrado» del superadministrador que entra a diario — cierto
    #: sobre el dato y falso sobre la realidad.
    #:
    #: **Con zona horaria**, como la de `HubUser`: lo que se escribe es
    #: `datetime.now(timezone.utc)`, y una columna sin zona la guardaría descolgada de su huso.
    #: Dos columnas que significan lo mismo y se declaran distinto acaban comparándose mal.
    last_login_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, v: Any) -> str:
        if isinstance(v, str):
            return v.lower()
        return v

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("El nombre no puede estar vacío")
        return v.strip()


class AdminAccount(SQLModel, table=True):
    """
    Cuenta de Administrador (gestor de organizaciones) para multi-tenencia.

    Los Admins administran múltiples organizaciones y sus créditos.
    """

    partner_id: str = Field(primary_key=True)
    name: str
    #: **Único** (USR.5), como el de `SuperAdminAccount` y por el mismo motivo: dos sitios lo
    #: consultan esperando una fila —`login_admin` y el ACS de SAML—, y con dos filas del mismo
    #: correo cuál gana depende del orden que devuelva Postgres, que sin `ORDER BY` no está
    #: definido. El síntoma sería un **401 intermitente**, imposible de diagnosticar desde
    #: fuera. Se cerró cuando la tabla estaba vacía en producción y el índice no costaba
    #: migración de datos.
    email: str = Field(nullable=False, sa_column_kwargs={"unique": True}, index=True)
    # SEC.1 (hallazgo A1): hasta aquí esta tabla no tenía hash, así que el login de Admin no
    # comprobaba nada — no era un descuido de una rama, es que no había contra qué comparar.
    #
    # NULL significa **login local deshabilitado**: la cuenta entra por SSO o por PAT, o un
    # superadmin le fija una contraseña. Nunca significa «pasa sin comprobar»; interpretarlo
    # así reabriría el mismo agujero por la puerta de atrás, y por eso tiene test propio.
    hashed_password: str | None = Field(default=None, nullable=True)
    credits_balance: int = Field(default=0)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    #: Cuándo entró por última vez (issue #102). Misma razón, misma semántica y **mismo tipo con
    #: zona** que en `SuperAdminAccount`: nulo es «todavía no ha entrado».
    last_login_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )


class SchedulerConfig(SQLModel, table=True):
    """
    Configuración para el programador de tareas en segundo plano.

    Controla tareas automatizadas como la actualización de la caché de modelos.
    """

    id: int = Field(default=1, primary_key=True)
    enabled: bool = Field(default=True, description="Whether scheduler is enabled")
    refresh_hour: int = Field(default=3, description="Hour to run daily refresh (0-23)")
    refresh_minute: int = Field(
        default=0, description="Minute to run daily refresh (0-59)"
    )
    last_run: Optional[datetime] = Field(
        default=None, description="Timestamp of last successful run"
    )
    updated_at: datetime = Field(default_factory=datetime.utcnow)
