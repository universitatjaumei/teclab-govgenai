"""Tests del servicio PAT y de la dependencia de auth dual JWT/PAT (AUTH.3).

Usan el PostgreSQL de desarrollo vía el fixture ``db`` (engine fresco por test +
limpieza por email/owner_email). Las pruebas de dependencia montan una app mínima y la
ejercen con httpx.AsyncClient (mismo event loop que el test → sin conflictos de loop).
"""

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi import Depends, FastAPI

from server.tests.core.auth._duenos import persona_real


def _uid() -> str:
    return uuid.uuid4().hex[:12]


def _admin(email: str | None = None):
    from server.app.core.auth.models import UserInfo

    email = email or f"admin-{_uid()}@uji.es"
    return UserInfo(user_id=f"admin-{_uid()}", email=email, role="admin")


# --------------------------------------------------------------------------- #
# PatService.create / verify                                                    #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_create_returns_plaintext_and_stores_hash(db):
    from server.app.core.auth.pat.service import PatService

    owner = _admin()
    db.track(owner.email)
    pat, token = await PatService(db.session).create(
        owner, name="mcp", scopes=["redaccion:templates:read"]
    )
    assert token.startswith("pat_")
    assert pat.token_hash != token
    assert pat.token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert pat.token_prefix and pat.token_prefix in token


@pytest.mark.asyncio
async def test_verify_valid_returns_principal_and_updates_last_used(db):
    from server.app.core.auth.pat.service import PatService

    owner = await persona_real(db.session, "admin")
    db.track(owner.email)
    service = PatService(db.session)
    _, token = await service.create(
        owner, name="mcp", scopes=["redaccion:templates:read", "chatbots:read"]
    )
    principal = await service.verify(token)
    assert principal.user_info.email == owner.email
    assert principal.user_info.role == "admin"
    assert set(principal.scopes) == {"redaccion:templates:read", "chatbots:read"}


@pytest.mark.asyncio
async def test_verify_revoked_raises(db):
    from server.app.core.auth.pat.service import PatInvalidError, PatService

    owner = _admin()
    db.track(owner.email)
    service = PatService(db.session)
    pat, token = await service.create(owner, name="mcp", scopes=["chatbots:read"])
    await service.revoke(owner, pat.id)
    with pytest.raises(PatInvalidError):
        await service.verify(token)


@pytest.mark.asyncio
async def test_verify_expired_raises(db):
    from server.app.core.auth.pat.service import PatInvalidError, PatService

    owner = _admin()
    db.track(owner.email)
    service = PatService(db.session)
    _, token = await service.create(
        owner,
        name="mcp",
        scopes=["chatbots:read"],
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    with pytest.raises(PatInvalidError):
        await service.verify(token)


@pytest.mark.asyncio
async def test_verify_wrong_secret_raises(db):
    from server.app.core.auth.pat.service import PatInvalidError, PatService

    owner = _admin()
    db.track(owner.email)
    service = PatService(db.session)
    pat, token = await service.create(owner, name="mcp", scopes=["chatbots:read"])
    # Mismo prefijo, secreto distinto → hash no casa (compare_digest).
    forged = f"pat_{pat.token_prefix}_secreto-falso"
    with pytest.raises(PatInvalidError):
        await service.verify(forged)


@pytest.mark.asyncio
async def test_admin_cannot_grant_chatbots_write(db):
    from server.app.core.auth.models import UserInfo
    from server.app.core.auth.pat.service import PatForbiddenError, PatService

    admin = UserInfo(
        user_id=f"a-{_uid()}", email=f"admin-{_uid()}@uji.es", role="admin"
    )
    db.track(admin.email)
    with pytest.raises(PatForbiddenError):
        await PatService(db.session).create(
            admin, name="mcp", scopes=["chatbots:write"]
        )


@pytest.mark.asyncio
async def test_non_privileged_role_cannot_create(db):
    from server.app.core.auth.models import UserInfo
    from server.app.core.auth.pat.service import PatForbiddenError, PatService

    enduser = UserInfo(user_id=f"u-{_uid()}", email=f"u-{_uid()}@uji.es", role="user")
    db.track(enduser.email)
    with pytest.raises(PatForbiddenError):
        await PatService(db.session).create(
            enduser, name="mcp", scopes=["chatbots:read"]
        )


@pytest.mark.asyncio
async def test_unknown_scope_raises(db):
    from server.app.core.auth.pat.scopes import UnknownScopeError
    from server.app.core.auth.pat.service import PatService

    owner = _admin()
    db.track(owner.email)
    with pytest.raises(UnknownScopeError):
        await PatService(db.session).create(
            owner, name="mcp", scopes=["bogus:scope"]
        )


@pytest.mark.asyncio
async def test_revoke_other_owner_raises(db):
    from server.app.core.auth.pat.service import PatInvalidError, PatService

    owner_a = _admin()
    owner_b = _admin()
    db.track(owner_a.email)
    db.track(owner_b.email)
    service = PatService(db.session)
    pat, _ = await service.create(owner_a, name="mcp", scopes=["chatbots:read"])
    with pytest.raises(PatInvalidError):
        await service.revoke(owner_b, pat.id)


# --------------------------------------------------------------------------- #
# Dependencia de auth dual JWT/PAT + require_scopes                             #
# --------------------------------------------------------------------------- #
def _protected_app(db):
    from server.app.api.deps import get_session, require_scopes
    from sqlmodel.ext.asyncio.session import AsyncSession

    async def _override_session():
        async with AsyncSession(db.engine) as s:
            yield s

    app = FastAPI()
    app.dependency_overrides[get_session] = _override_session

    @app.get("/protected")
    async def protected(user=Depends(require_scopes("redaccion:templates:read"))):
        return {"email": user.email}

    return app


def _client(app):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    )


@pytest.mark.asyncio
async def test_dependency_pat_with_scope_allows(db):
    from server.app.core.auth.pat.service import PatService

    owner = await persona_real(db.session, "admin")
    db.track(owner.email)
    _, token = await PatService(db.session).create(
        owner, name="mcp", scopes=["redaccion:templates:read"]
    )
    async with _client(_protected_app(db)) as client:
        resp = await client.get(
            "/protected", headers={"Authorization": f"Bearer {token}"}
        )
    assert resp.status_code == 200
    assert resp.json()["email"] == owner.email


@pytest.mark.asyncio
async def test_dependency_pat_missing_scope_403(db):
    from server.app.core.auth.pat.service import PatService

    owner = await persona_real(db.session, "admin")
    db.track(owner.email)
    _, token = await PatService(db.session).create(
        owner, name="mcp", scopes=["chatbots:read"]  # falta templates:read
    )
    async with _client(_protected_app(db)) as client:
        resp = await client.get(
            "/protected", headers={"Authorization": f"Bearer {token}"}
        )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "PAT_SCOPE_MISSING"


@pytest.mark.asyncio
async def test_dependency_jwt_not_scope_filtered(db):
    from server.app.core.auth import create_token

    owner = _admin()
    token = create_token(owner)  # JWT humano: sin scopes → no se filtra
    async with _client(_protected_app(db)) as client:
        resp = await client.get(
            "/protected", headers={"Authorization": f"Bearer {token}"}
        )
    assert resp.status_code == 200
    assert resp.json()["email"] == owner.email


@pytest.mark.asyncio
async def test_dependency_revoked_pat_401(db):
    from server.app.core.auth.pat.service import PatService

    owner = _admin()
    db.track(owner.email)
    service = PatService(db.session)
    pat, token = await service.create(
        owner, name="mcp", scopes=["redaccion:templates:read"]
    )
    await service.revoke(owner, pat.id)
    async with _client(_protected_app(db)) as client:
        resp = await client.get(
            "/protected", headers={"Authorization": f"Bearer {token}"}
        )
    assert resp.status_code == 401
