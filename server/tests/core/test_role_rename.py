"""ROL.1 — Renombrado institucional de roles (superadmin | admin | user).

Cubre el enum de roles, los gates nombrados (require_superadmin / require_admin),
el techo de scopes PAT y la precedencia SAML tras el renombrado
admin→superadmin, partner→admin. INFORMER se preserva (no está en el mapa de
renombrado; su retirada sería un cambio de comportamiento fuera de alcance).
"""

from unittest.mock import patch

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from server.app.api.deps import require_admin, require_superadmin
from server.app.core.auth import UserInfo, create_token
from server.app.core.auth.models import UserRole

JWT_ENV = {
    "JWT_SECRET_KEY": "test-secret-key-that-is-at-least-32-characters-long",
    "JWT_ALGORITHM": "HS256",
    "JWT_EXPIRATION_MINUTES": "60",
}


def _make_token(role: str) -> str:
    return create_token(UserInfo(user_id="u-1", email="u@test.com", role=role))


# --- Enum de roles ---------------------------------------------------------


def test_should_expose_superadmin_admin_user_roles_only():
    values = {r.value for r in UserRole}
    # El renombrado institucional: los tres roles de la jerarquía + informer.
    assert {"superadmin", "admin", "user"} <= values
    # El Literal ya no acepta 'partner'.
    assert "partner" not in values
    with pytest.raises(ValueError, match="Invalid role"):
        UserInfo(user_id="1", email="e@test.com", role="partner")


# --- Gates nombrados -------------------------------------------------------

_app = FastAPI()


@_app.get("/superadmin-only")
async def _superadmin_only(user: UserInfo = Depends(require_superadmin)):
    return {"ok": True}


@_app.get("/admin-area")
async def _admin_area(user: UserInfo = Depends(require_admin)):
    return {"ok": True}


def _get(path: str, role: str) -> int:
    with patch.dict("os.environ", JWT_ENV, clear=False):
        client = TestClient(_app)
        return client.get(
            path, headers={"Authorization": f"Bearer {_make_token(role)}"}
        ).status_code


def test_should_require_superadmin_dependency_rejects_admin_role():
    assert _get("/superadmin-only", "admin") == 403
    assert _get("/superadmin-only", "superadmin") == 200


def test_should_require_admin_dependency_accepts_admin_and_superadmin():
    assert _get("/admin-area", "admin") == 200
    assert _get("/admin-area", "superadmin") == 200
    assert _get("/admin-area", "user") == 403


# --- Techo de scopes PAT ---------------------------------------------------


def test_should_rename_pat_scope_ceilings():
    from server.app.core.auth.pat.scopes import ALL_SCOPES, CHATBOTS_WRITE, allowed_scopes_for_role

    assert allowed_scopes_for_role(UserRole.SUPERADMIN.value) == ALL_SCOPES
    assert allowed_scopes_for_role(UserRole.ADMIN.value) == ALL_SCOPES - {CHATBOTS_WRITE}
    # 'partner' ya no puede emitir PAT.
    assert allowed_scopes_for_role("partner") == frozenset()


# --- Precedencia SAML ------------------------------------------------------


def test_should_saml_precedence_prefers_superadmin_over_admin():
    from server.app.core.auth.saml.role_mapping import _highest

    assert _highest(["user", "admin", "superadmin"]) == "superadmin"
    assert _highest(["user", "admin"]) == "admin"
    assert _highest(["user"]) == "user"
