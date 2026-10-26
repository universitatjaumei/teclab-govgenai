"""Tests del workflow de aprobación de scripts — 9R.5.6.

Cubren los 6 endpoints nuevos:
  save-to-private-template, submit-for-review, GET /pending,
  admin-retest, approve, reject.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Helpers de estado y fixture compartida
# ---------------------------------------------------------------------------

def _make_audit_result(
    approved: bool = True,
    *,
    puede_revisarse: bool | None = None,
) -> dict[str, Any]:
    """PRO.1 — el resultado de auditoría lleva nivel y `puede_revisarse`.

    Por defecto `puede_revisarse` acompaña a `approved`: un script sin hallazgos es
    revisable trivialmente, y el `audit_approved=False` de los tests anteriores sigue
    significando «no puede pasar de aquí».
    """
    if puede_revisarse is None:
        puede_revisarse = approved
    nivel = "SAFE" if approved else ("WARNING" if puede_revisarse else "CRITICAL")
    return {
        "approved": approved,
        "risk_level": nivel,
        "puede_revisarse": puede_revisarse,
        "findings": [],
        "confidence": 1.0 if approved else (0.5 if puede_revisarse else 0.0),
    }


def _seed_proposal(
    state: dict,
    owner_id: uuid.UUID,
    *,
    target_owner_kind: str = "user",
    target_template_id: uuid.UUID | None = None,
    status: str = "tested",
    audit_approved: bool = True,
    audit_puede_revisarse: bool | None = None,
    has_validated_test: bool = True,
    is_anonymized: bool = True,
    admin_retest_json: dict | None = None,
    test_result_json: dict | None = None,
) -> Any:
    from server.app.modules.redaccion.database.models import HubScriptProposal

    proposal = HubScriptProposal(
        id=uuid.uuid4(),
        proposer_user_id=owner_id,
        target_owner_kind=target_owner_kind,
        target_template_id=target_template_id,
        prompt_nl="dummy",
        code="result = {'tables': [], 'metrics': [], 'free_text': 'ok'}\n",
        audit_result_json=_make_audit_result(
            audit_approved, puede_revisarse=audit_puede_revisarse
        ),
        status=status,
        test_data_ref={"bucket": "bucket", "key": "dummy.xlsx"},
        test_data_is_anonymized=is_anonymized,
        test_result_json=(
            test_result_json
            if test_result_json is not None
            else {"tables": [], "metrics": [], "free_text": "ok"}
        ),
        test_result_hash="abc123deadbeef",
        admin_retest_json=admin_retest_json,
    )
    if has_validated_test:
        proposal.test_validated_by_proposer_at = datetime.now(timezone.utc)

    state.setdefault("HubScriptProposal", {})[str(proposal.id)] = proposal
    return proposal


def _seed_template_and_version(
    state: dict,
    owner_id: uuid.UUID,
    *,
    is_global: bool = False,
) -> tuple[Any, Any]:
    from server.app.modules.redaccion.database.models import (
        HubReportTemplate,
        HubReportTemplateVersion,
    )

    version_id = uuid.uuid4()
    template_id = uuid.uuid4()

    version = HubReportTemplateVersion(
        id=version_id,
        template_id=template_id,
        version=1,
        # PRO.3 — un spec que valida contra `ReportTemplateSpec`. Este `spec_json` tenía
        # `blocks` como diccionario y `label` en vez de `title`, así que era una plantilla que
        # el grafo no podía leer; desde que aprobar valida la versión resultante, una plantilla
        # así se rechaza con 422 en vez de quedarse guardada e inservible.
        spec_json={
            "sections": [{"id": "s1", "title": "Main", "order": 0, "block_ids": ["b1"]}],
            "blocks": [{"id": "b1", "kind": "STATIC_TEXT", "title": "Intro", "content": ""}],
            "input_contract": {"required_slots": [], "optional_slots": []},
            "ui_contract": {
                "wizard_steps": [],
                "dropzones": [],
                "manual_fields": [],
                "block_editor_enabled": True,
                "ai_review_panel_enabled": False,
                "preview_layout": "markdown",
            },
            "ai_block_policy": "disabled",
            "review_policy": "none",
            "export_policy": "docx",
        },
        created_by=owner_id,
    )
    template = HubReportTemplate(
        id=template_id,
        name="Test Template",
        report_profile="GENERIC_REPORT",
        # MT.4 — el nivel lo dice `owner_kind` y `is_global` se deriva de él, así que ya no se
        # asigna: eran el mismo hecho en dos sitios.
        owner_kind="platform" if is_global else "user",
        owner_id=owner_id,
        current_version_id=version_id,
    )

    state.setdefault("HubReportTemplate", {})[str(template_id)] = template
    state.setdefault("HubReportTemplateVersion", {})[str(version_id)] = version
    return template, version


@pytest.fixture
def approval_app(tmp_path):
    """App FastAPI con sesión fake multi-modelo para tests de aprobación."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from server.app.api.deps import get_current_user, get_session
    from server.app.core.auth.models import UserInfo
    from server.app.core.sandbox_client import LocalSandboxClient, get_sandbox_client
    from server.app.core.storage import FsspecStorageService, get_storage_service
    from server.app.modules.redaccion.services.test_data_anonymizer import (
        TestDataAnonymizerService,
    )
    from server.app.routers.redaccion.scripts_router import (
        get_test_data_anonymizer,
        router,
    )

    bucket_root = tmp_path / "bucket"
    bucket_root.mkdir()
    storage = FsspecStorageService(backend="file", bucket=str(bucket_root))

    state: dict[str, dict] = {}
    current_user_holder: dict[str, UserInfo] = {}

    class _FakeSession:
        def add(self, obj: Any) -> None:
            name = type(obj).__name__
            state.setdefault(name, {})[str(obj.id)] = obj

        async def flush(self) -> None:
            return None

        async def commit(self) -> None:
            return None

        async def get(self, model: type, key: Any) -> Any | None:
            return state.get(model.__name__, {}).get(str(key))

        async def execute(self, stmt: Any) -> Any:
            """FUN.3 — el registro en el catálogo pide el ordinal siguiente de la función.

            Este doble no sabe de SQL, y lo que necesita la prueba es que el registro ocurra:
            la primera versión de una función nueva es la 1, y el ordinal de verdad lo prueban
            los tests del catálogo contra Postgres.
            """

            class _R:
                def scalar_one(self_inner) -> int:
                    return 1

            return _R()

    async def _override_session():
        yield _FakeSession()

    async def _override_user():
        return current_user_holder.get(
            "user",
            UserInfo(user_id=str(uuid.uuid4()), email="user@test.com", role="user"),
        )

    app = FastAPI()
    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[get_storage_service] = lambda: storage
    app.dependency_overrides[get_test_data_anonymizer] = lambda: TestDataAnonymizerService(
        storage=storage
    )
    app.dependency_overrides[get_sandbox_client] = lambda: LocalSandboxClient()
    app.include_router(router, prefix="/api/v1")

    client = TestClient(app)
    return client, state, current_user_holder


# ---------------------------------------------------------------------------
# 20. save-to-private-template — requiere audit aprobado
# ---------------------------------------------------------------------------

def test_save_to_private_template_requires_audit_pass(approval_app) -> None:
    client, state, user_holder = approval_app
    from server.app.core.auth.models import UserInfo

    user_uuid = uuid.uuid4()
    user_holder["user"] = UserInfo(user_id=str(user_uuid), email="u@t.com", role="user")

    template, _ = _seed_template_and_version(state, user_uuid)
    proposal = _seed_proposal(
        state, user_uuid,
        target_template_id=template.id,
        audit_approved=False,
    )

    response = client.post(f"/api/v1/redaccion/scripts/{proposal.id}/save-to-private-template")
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "AUDIT_FAILED"


# ---------------------------------------------------------------------------
# 21. save-to-private-template — requiere test validado
# ---------------------------------------------------------------------------

def test_save_to_private_template_requires_validated_test(approval_app) -> None:
    client, state, user_holder = approval_app
    from server.app.core.auth.models import UserInfo

    user_uuid = uuid.uuid4()
    user_holder["user"] = UserInfo(user_id=str(user_uuid), email="u@t.com", role="user")

    template, _ = _seed_template_and_version(state, user_uuid)
    proposal = _seed_proposal(
        state, user_uuid,
        target_template_id=template.id,
        has_validated_test=False,
    )

    response = client.post(f"/api/v1/redaccion/scripts/{proposal.id}/save-to-private-template")
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "TEST_NOT_VALIDATED"


# ---------------------------------------------------------------------------
# 22. save-to-private-template — crea nueva versión (happy path)
# ---------------------------------------------------------------------------

def test_save_to_private_template_creates_new_version(approval_app) -> None:
    client, state, user_holder = approval_app
    from server.app.core.auth.models import UserInfo

    user_uuid = uuid.uuid4()
    user_holder["user"] = UserInfo(user_id=str(user_uuid), email="u@t.com", role="user")

    template, _version = _seed_template_and_version(state, user_uuid)
    proposal = _seed_proposal(
        state, user_uuid,
        target_template_id=template.id,
    )

    # FUN.3 — registrar en el catálogo exige la declaración responsable (Instrucció §8.2).
    response = client.post(
        f"/api/v1/redaccion/scripts/{proposal.id}/save-to-private-template",
        json={
            "finalidad": "Extraer la tabla de gastos del ERP",
            "categorias_datos": ["datos_economicos_y_financieros"],
            "nombre": "Extraer gastos",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["proposal_id"] == str(proposal.id)
    assert body["template_id"] == str(template.id)
    # Y devuelve qué función quedó registrada: antes no había nada que devolver, porque el
    # código se copiaba en la plantilla y no tenía identidad.
    assert body["funcion_id"] is not None
    assert body["funcion_version"] == 1

    # Una nueva versión fue creada en el estado
    versions = state.get("HubReportTemplateVersion", {})
    assert len(versions) == 2  # original + nueva

    # La plantilla apunta a la nueva versión
    tmpl = state["HubReportTemplate"][str(template.id)]
    assert str(tmpl.current_version_id) == body["new_version_id"]

    # La propuesta pasa a approved
    p = state["HubScriptProposal"][str(proposal.id)]
    # FUN.3 — `registrada` y no `approved`: la propuesta cumplió su papel (fue la prueba en
    # sandbox) y lo que queda vivo es la versión del catálogo. Nadie aprobó nada: en el nivel 2
    # de la Instrucció la aprobación previa está prohibida como condición para compartir.
    assert p.status == "registrada"


# ---------------------------------------------------------------------------
# 23. save-to-private-template — rechaza si no es el proposer
# ---------------------------------------------------------------------------

def test_save_to_private_template_rejects_if_not_owner(approval_app) -> None:
    client, state, user_holder = approval_app
    from server.app.core.auth.models import UserInfo

    owner_uuid = uuid.uuid4()
    other_uuid = uuid.uuid4()
    user_holder["user"] = UserInfo(user_id=str(other_uuid), email="other@t.com", role="user")

    template, _ = _seed_template_and_version(state, owner_uuid)
    proposal = _seed_proposal(state, owner_uuid, target_template_id=template.id)

    response = client.post(f"/api/v1/redaccion/scripts/{proposal.id}/save-to-private-template")
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# 24. submit-for-review — requiere datos anonimizados
# ---------------------------------------------------------------------------

def test_submit_for_review_requires_anonymized_test_data(approval_app) -> None:
    client, state, user_holder = approval_app
    from server.app.core.auth.models import UserInfo

    user_uuid = uuid.uuid4()
    user_holder["user"] = UserInfo(user_id=str(user_uuid), email="u@t.com", role="user")

    proposal = _seed_proposal(
        state, user_uuid,
        target_owner_kind="platform",
        is_anonymized=False,
    )

    response = client.post(f"/api/v1/redaccion/scripts/{proposal.id}/submit-for-review")
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "NOT_ANONYMIZED"


# ---------------------------------------------------------------------------
# PRO.1 — quien decide si algo pasa a revisión mira `puede_revisarse`
# ---------------------------------------------------------------------------

def test_submit_for_review_admite_un_warning_revisable(approval_app) -> None:
    """Un módulo fuera de la lista blanca deja de tumbar la propuesta.

    Es exactamente el caso que hacía inusable el módulo: el modelo escribe un script
    razonable con un `import` que no está en la lista, y hasta PRO.1 nadie podía ni
    mirarlo. La cola de revisión existe justo para que una persona lo mire.
    """
    client, state, user_holder = approval_app
    from server.app.core.auth.models import UserInfo

    user_uuid = uuid.uuid4()
    user_holder["user"] = UserInfo(user_id=str(user_uuid), email="u@t.com", role="user")

    proposal = _seed_proposal(
        state, user_uuid,
        target_owner_kind="platform",
        audit_approved=False,
        audit_puede_revisarse=True,
    )

    response = client.post(f"/api/v1/redaccion/scripts/{proposal.id}/submit-for-review")
    assert response.status_code == 200, response.json()
    assert response.json()["status"] == "pending_review"


def test_submit_for_review_rechaza_un_hallazgo_critico(approval_app) -> None:
    client, state, user_holder = approval_app
    from server.app.core.auth.models import UserInfo

    user_uuid = uuid.uuid4()
    user_holder["user"] = UserInfo(user_id=str(user_uuid), email="u@t.com", role="user")

    proposal = _seed_proposal(
        state, user_uuid,
        target_owner_kind="platform",
        audit_approved=False,
        audit_puede_revisarse=False,
    )

    response = client.post(f"/api/v1/redaccion/scripts/{proposal.id}/submit-for-review")
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "AUDIT_CRITICAL"


def test_submit_for_review_rechaza_un_test_que_no_extrajo_nada(approval_app) -> None:
    """El hueco que abre admitir warnings: un test que falló también tiene hash.

    `/test` guarda el `ExtractionResult` pase lo que pase, y un script rechazado por el
    sandbox devuelve un resultado con un aviso de severidad `error` y cero datos. Su hash
    es estable, así que el retest del admin coincidiría y la propuesta llegaría a
    aprobarse sin haber extraído nunca nada.
    """
    client, state, user_holder = approval_app
    from server.app.core.auth.models import UserInfo

    user_uuid = uuid.uuid4()
    user_holder["user"] = UserInfo(user_id=str(user_uuid), email="u@t.com", role="user")

    proposal = _seed_proposal(
        state, user_uuid,
        target_owner_kind="platform",
        test_result_json={
            "tables": [],
            "metrics": [],
            "free_text": None,
            "warnings": [{
                "code": "SCRIPT_SECURITY_VIOLATION",
                "message": "El script no supera la auditoría de seguridad",
                "severity": "error",
            }],
        },
    )

    response = client.post(f"/api/v1/redaccion/scripts/{proposal.id}/submit-for-review")
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "TEST_FAILED"


def test_approve_rechaza_un_hallazgo_critico(approval_app) -> None:
    """El admin no puede aprobar un crítico ni queriendo: la determinista no se convence."""
    client, state, user_holder = approval_app
    from server.app.core.auth.models import UserInfo

    admin_uuid = uuid.uuid4()
    # Revisar e incrustar en una plantilla de plataforma es del superadministrador desde que la
    # revisión se acota a la organización; el camino del administrador de organización lo prueba
    # `test_el_administrador_se_queda_en_su_organizacion.py`.
    user_holder["user"] = UserInfo(user_id=str(admin_uuid), email="admin@t.com", role="superadmin")

    template, _ = _seed_template_and_version(state, admin_uuid, is_global=True)

    proposal = _seed_proposal(
        state, uuid.uuid4(),
        status="pending_review",
        target_owner_kind="platform",
        audit_approved=False,
        audit_puede_revisarse=False,
        admin_retest_json={
            "hash": "abc",
            "hash_matches": True,
            "retested_at": datetime.now(timezone.utc).isoformat(),
            "retester_user_id": str(admin_uuid),
        },
    )

    response = client.post(
        f"/api/v1/redaccion/scripts/{proposal.id}/approve",
        json={"target_global_template_id": str(template.id)},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "AUDIT_CRITICAL"


# ---------------------------------------------------------------------------
# 25. GET /pending — devuelve solo los de status pending_review
# ---------------------------------------------------------------------------

def test_get_pending_returns_only_pending_review_status(approval_app, monkeypatch) -> None:
    client, state, user_holder = approval_app
    from server.app.core.auth.models import UserInfo
    from server.app.modules.redaccion.database.repos import ScriptProposalRepo

    admin_uuid = uuid.uuid4()
    # Revisar e incrustar en una plantilla de plataforma es del superadministrador desde que la
    # revisión se acota a la organización; el camino del administrador de organización lo prueba
    # `test_el_administrador_se_queda_en_su_organizacion.py`.
    user_holder["user"] = UserInfo(user_id=str(admin_uuid), email="admin@t.com", role="superadmin")

    owner = uuid.uuid4()
    p_pending = _seed_proposal(state, owner, status="pending_review", target_owner_kind="platform")
    _seed_proposal(state, owner, status="tested")

    async def _mock_list_by_status(self, status: str):
        return [
            p
            for p in state.get("HubScriptProposal", {}).values()
            if p.status == status
        ]

    monkeypatch.setattr(ScriptProposalRepo, "list_by_status", _mock_list_by_status)

    response = client.get("/api/v1/redaccion/scripts/pending")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["proposal_id"] == str(p_pending.id)


# ---------------------------------------------------------------------------
# 26. GET /pending — prohibido para usuario regular
# ---------------------------------------------------------------------------

def test_get_pending_forbidden_for_regular_user(approval_app, monkeypatch) -> None:
    client, state, user_holder = approval_app
    from server.app.core.auth.models import UserInfo
    from server.app.modules.redaccion.database.repos import ScriptProposalRepo

    user_holder["user"] = UserInfo(user_id=str(uuid.uuid4()), email="user@t.com", role="user")

    async def _mock_list_by_status(self, status: str):
        return []

    monkeypatch.setattr(ScriptProposalRepo, "list_by_status", _mock_list_by_status)

    response = client.get("/api/v1/redaccion/scripts/pending")
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# 27. admin-retest — devuelve hash_matches correcto
# ---------------------------------------------------------------------------

def test_admin_retest_returns_hash_match_flag(approval_app) -> None:
    """El admin re-ejecuta el script: respuesta incluye hash_matches y se persiste.

    El timestamp de `extracted_at` en ExtractionProvenance varía en cada ejecución,
    por lo que el hash del retest siempre difiere del hash seeded con valor fijo
    ("abc123deadbeef"). Verificamos que hash_matches=False se reporta correctamente
    y que admin_retest_json queda persistido.
    """
    client, state, user_holder = approval_app
    from server.app.core.auth.models import UserInfo

    admin_uuid = uuid.uuid4()
    # Revisar e incrustar en una plantilla de plataforma es del superadministrador desde que la
    # revisión se acota a la organización; el camino del administrador de organización lo prueba
    # `test_el_administrador_se_queda_en_su_organizacion.py`.
    user_holder["user"] = UserInfo(user_id=str(admin_uuid), email="admin@t.com", role="superadmin")

    owner_uuid = uuid.uuid4()
    # test_result_hash seeded con valor conocidamente distinto al que producirá el sandbox
    proposal = _seed_proposal(
        state, owner_uuid,
        status="pending_review",
        target_owner_kind="platform",
    )
    # "abc123deadbeef" nunca coincidirá con un SHA-256 de 64 caracteres hex
    assert proposal.test_result_hash == "abc123deadbeef"

    response = client.post(f"/api/v1/redaccion/scripts/{proposal.id}/admin-retest")
    assert response.status_code == 200
    body = response.json()

    # El flag se devuelve como booleano
    assert isinstance(body["hash_matches"], bool)
    assert body["hash_matches"] is False  # hash seeded != hash real del sandbox

    # El hash devuelto es un SHA-256 válido (64 chars hex)
    assert len(body["hash"]) == 64
    assert all(c in "0123456789abcdef" for c in body["hash"])

    # Persistencia: admin_retest_json queda guardado con hash_matches=False
    p = state["HubScriptProposal"][str(proposal.id)]
    assert p.admin_retest_json is not None
    assert p.admin_retest_json["hash_matches"] is False
    assert p.admin_retest_json["retested_at"] is not None


# ---------------------------------------------------------------------------
# 28. approve — requiere hash_matches reciente
# ---------------------------------------------------------------------------

def test_approve_requires_recent_hash_match(approval_app) -> None:
    client, state, user_holder = approval_app
    from server.app.core.auth.models import UserInfo

    admin_uuid = uuid.uuid4()
    # Revisar e incrustar en una plantilla de plataforma es del superadministrador desde que la
    # revisión se acota a la organización; el camino del administrador de organización lo prueba
    # `test_el_administrador_se_queda_en_su_organizacion.py`.
    user_holder["user"] = UserInfo(user_id=str(admin_uuid), email="admin@t.com", role="superadmin")

    template, _ = _seed_template_and_version(state, admin_uuid, is_global=True)

    owner_uuid = uuid.uuid4()
    # Propuesta sin admin_retest_json
    proposal = _seed_proposal(state, owner_uuid, status="pending_review", target_owner_kind="platform")

    response = client.post(
        f"/api/v1/redaccion/scripts/{proposal.id}/approve",
        json={"target_global_template_id": str(template.id)},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "HASH_MISMATCH"


# ---------------------------------------------------------------------------
# 29. approve — crea nueva versión de plantilla global (happy path)
# ---------------------------------------------------------------------------

def test_approve_creates_new_global_template_version(approval_app) -> None:
    client, state, user_holder = approval_app
    from server.app.core.auth.models import UserInfo

    admin_uuid = uuid.uuid4()
    # Revisar e incrustar en una plantilla de plataforma es del superadministrador desde que la
    # revisión se acota a la organización; el camino del administrador de organización lo prueba
    # `test_el_administrador_se_queda_en_su_organizacion.py`.
    user_holder["user"] = UserInfo(user_id=str(admin_uuid), email="admin@t.com", role="superadmin")

    template, _ = _seed_template_and_version(state, admin_uuid, is_global=True)

    owner_uuid = uuid.uuid4()
    recent_retest = {
        "hash": "abc",
        "hash_matches": True,
        "retested_at": datetime.now(timezone.utc).isoformat(),
        "retester_user_id": str(admin_uuid),
    }
    proposal = _seed_proposal(
        state, owner_uuid,
        status="pending_review",
        target_owner_kind="platform",
        admin_retest_json=recent_retest,
    )

    response = client.post(
        f"/api/v1/redaccion/scripts/{proposal.id}/approve",
        json={"target_global_template_id": str(template.id), "review_note": "LGTM"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["proposal_id"] == str(proposal.id)
    assert body["template_id"] == str(template.id)

    versions = state.get("HubReportTemplateVersion", {})
    assert len(versions) == 2

    p = state["HubScriptProposal"][str(proposal.id)]
    assert p.status == "approved"
    assert p.review_note == "LGTM"


# ---------------------------------------------------------------------------
# 30. reject — graba nota y bloquea cambios posteriores
# ---------------------------------------------------------------------------

def test_reject_records_note_and_blocks_further_changes(approval_app) -> None:
    client, state, user_holder = approval_app
    from server.app.core.auth.models import UserInfo

    admin_uuid = uuid.uuid4()
    # Revisar e incrustar en una plantilla de plataforma es del superadministrador desde que la
    # revisión se acota a la organización; el camino del administrador de organización lo prueba
    # `test_el_administrador_se_queda_en_su_organizacion.py`.
    user_holder["user"] = UserInfo(user_id=str(admin_uuid), email="admin@t.com", role="superadmin")

    template, _ = _seed_template_and_version(state, admin_uuid, is_global=True)

    owner_uuid = uuid.uuid4()
    recent_retest = {
        "hash": "abc",
        "hash_matches": True,
        "retested_at": datetime.now(timezone.utc).isoformat(),
        "retester_user_id": str(admin_uuid),
    }
    proposal = _seed_proposal(
        state, owner_uuid,
        status="pending_review",
        target_owner_kind="platform",
        admin_retest_json=recent_retest,
    )

    # Rechazar
    resp_reject = client.post(
        f"/api/v1/redaccion/scripts/{proposal.id}/reject",
        json={"review_note": "Código inseguro."},
    )
    assert resp_reject.status_code == 200
    body = resp_reject.json()
    assert body["status"] == "rejected"
    assert body["review_note"] == "Código inseguro."

    p = state["HubScriptProposal"][str(proposal.id)]
    assert p.status == "rejected"
    assert p.review_note == "Código inseguro."

    # Intentar aprobar después del rechazo → 422
    resp_approve = client.post(
        f"/api/v1/redaccion/scripts/{proposal.id}/approve",
        json={"target_global_template_id": str(template.id)},
    )
    assert resp_approve.status_code == 422
