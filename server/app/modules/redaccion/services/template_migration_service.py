"""Versionado de plantillas y migración de workspaces — 9R.4.4.

Política de producto:
- Un Workspace queda anclado a su template_version_id para siempre.
- Publicar vN+1 NO migra automáticamente workspaces existentes.
- La migración es explícita: crea workspace nuevo (inputs copiados, sin blocks),
  archiva el antiguo y registra el parentesco vía parent_workspace_id.
"""
from __future__ import annotations

import uuid

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.modules.redaccion.database.models import HubWorkspace
from server.app.modules.redaccion.database.repos import (
    ReportTemplateRepo,
    ReportTemplateVersionRepo,
    WorkspaceRepo,
)


# ---------------------------------------------------------------------------
# DTOs públicos
# ---------------------------------------------------------------------------

class BreakingChange(BaseModel):
    slot_id: str
    reason: str


class NewVersionNotice(BaseModel):
    current_version_id: uuid.UUID
    latest_version_id: uuid.UUID
    changes_summary: str
    breaking_changes: list[BreakingChange] = []


# ---------------------------------------------------------------------------
# Excepciones de dominio
# ---------------------------------------------------------------------------

class WorkspaceNotFoundError(ValueError):
    pass


class WorkspaceOwnershipError(PermissionError):
    pass


class CompatibilityConflictError(Exception):
    def __init__(self, compatibility_errors: list[dict]) -> None:
        super().__init__("InputContract incompatible with target version")
        self.compatibility_errors = compatibility_errors


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _required_slot_ids(spec_json: dict) -> set[str]:
    """Los `slot_id` obligatorios de una **spec** guardada.

    **`input_contract`, no `proposed_inputs`.** Aquí llegan `spec_json` de
    `HubReportTemplateVersion`, y una `ReportTemplateSpec` declara `input_contract`;
    `proposed_inputs` es la clave del **borrador del modelo** (`ReportTemplateDraft`). Leer la
    del borrador hacía que el `.get()` no encontrara nada, el `{}` por omisión hiciera el resto y
    `_compute_breaking_changes` devolviera **siempre** vacío: migrar no avisaba nunca.

    Las dos claves envuelven el **mismo tipo** (`InputContract`), o sea que confundirlas no da
    error de tipos. Y no lo cazó el test que existía porque su fixture construía la forma del
    borrador, así que código y medida se daban la razón. Lo fija ahora
    `test_issue84_los_cambios_rompedores_miran_la_clave_de_la_spec.py`, que además afirma sobre
    los contratos cuál es la clave de cada uno.
    """
    inputs = spec_json.get("input_contract", {})
    return {slot["slot_id"] for slot in inputs.get("required_slots", [])}


def _compute_breaking_changes(
    current_spec: dict, target_spec: dict
) -> list[BreakingChange]:
    current_slots = _required_slot_ids(current_spec)
    target_slots = _required_slot_ids(target_spec)
    new_required = target_slots - current_slots
    return [
        BreakingChange(
            slot_id=slot_id,
            reason="New required input slot not present in current workspace",
        )
        for slot_id in sorted(new_required)
    ]


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

def _existe(valor, que: str):
    """Lo que la base garantiza por clave ajena; si falta, el dato está roto y se dice cuál."""
    if valor is None:
        raise LookupError(f"falta {que}: el workspace apunta a algo que ya no existe")
    return valor


class TemplateMigrationService:
    def __init__(self, session: AsyncSession) -> None:
        self._ws_repo = WorkspaceRepo(session)
        self._ver_repo = ReportTemplateVersionRepo(session)
        self._tpl_repo = ReportTemplateRepo(session)
        self._session = session

    async def detect_new_version(
        self, workspace_id: uuid.UUID
    ) -> NewVersionNotice | None:
        workspace = await self._ws_repo.get(workspace_id)
        if workspace is None:
            raise WorkspaceNotFoundError(f"Workspace {workspace_id} not found")

        current_version = _existe(
            await self._ver_repo.get(workspace.template_version_id), "la versión del workspace"
        )
        template = _existe(await self._tpl_repo.get(current_version.template_id), "su plantilla")

        if template.current_version_id == workspace.template_version_id:
            return None

        latest_id = _existe(template.current_version_id, "la versión vigente de la plantilla")
        latest_version = _existe(await self._ver_repo.get(latest_id), "la versión vigente")
        breaking = _compute_breaking_changes(
            current_version.spec_json, latest_version.spec_json
        )
        summary = (
            f"Template updated to version {latest_version.version} "
            f"(current: {current_version.version})"
        )
        return NewVersionNotice(
            current_version_id=workspace.template_version_id,
            latest_version_id=latest_id,
            changes_summary=summary,
            breaking_changes=breaking,
        )

    async def migrate_workspace(
        self,
        workspace_id: uuid.UUID,
        target_version_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> HubWorkspace:
        workspace = await self._ws_repo.get(workspace_id)
        if workspace is None:
            raise WorkspaceNotFoundError(f"Workspace {workspace_id} not found")

        if workspace.owner_id != user_id:
            raise WorkspaceOwnershipError(
                "Only the workspace owner can trigger migration"
            )

        target_version = _existe(await self._ver_repo.get(target_version_id), "la versión de destino")
        current_version = _existe(
            await self._ver_repo.get(workspace.template_version_id), "la versión del workspace"
        )

        breaking = _compute_breaking_changes(
            current_version.spec_json, target_version.spec_json
        )
        if breaking:
            raise CompatibilityConflictError(
                [{"slot_id": b.slot_id, "reason": b.reason} for b in breaking]
            )

        new_workspace_id = uuid.uuid4()
        new_workspace = HubWorkspace(
            id=new_workspace_id,
            template_version_id=target_version_id,
            owner_id=workspace.owner_id,
            status="draft",
            inputs_json=workspace.inputs_json,
            warnings_json=[],
            parent_workspace_id=workspace.id,
        )

        workspace.status = "archived"
        workspace.archived_reason = f"migrated_to_{new_workspace_id}"

        await self._ws_repo.save(new_workspace)

        return new_workspace
