"""Tests del workflow ScriptProposalService + TestDataAnonymizerService.

Cubren 9R.5.5 Parte 3 (proponer + auditar) y los puntos críticos de la
Parte 5 (endpoints) que pueden testarse en aislamiento:
- describe-test-data sugiere providers Faker coherentes.
- test endpoint exige datos anonimizados para target=platform.
- test endpoint ejecuta en el sandbox compartido con AdminScriptExtractionPipeline.
- test endpoint persiste hash sha256 del resultado.
- validate-test-result requiere test previo.
- validate-test-result marca timestamp.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock

import pandas as pd
import pytest
from server.tests.dobles import modelo_de_chat


# ---------------------------------------------------------------------------
# 12. ScriptProposalService genera código + audit_result
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_propose_generates_code_and_audit_result() -> None:
    from server.app.modules.redaccion.services.script_proposal_service import (
        ScriptProposalService,
    )

    @dataclass
    class _FakeResponse:
        content: str

    llm = modelo_de_chat()
    llm.ainvoke = AsyncMock(
        return_value=_FakeResponse(
            content=(
                "```python\n"
                "import pandas as pd\n"
                "df = pd.read_excel(file_path)\n"
                "result = {'tables': [], 'metrics': [], 'free_text': None}\n"
                "```"
            )
        )
    )

    service = ScriptProposalService(llm=llm, model_name="test-model")
    result = await service.propose("Lee el Excel y deja el resultado vacío.")

    assert "pandas" in result.code
    assert "result = {" in result.code
    assert result.audit_result.approved is True
    assert result.model_used == "test-model"


# ---------------------------------------------------------------------------
# 13. Rechazo si el LLM produce import prohibido
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_propose_rejects_when_llm_outputs_forbidden_import() -> None:
    from server.app.modules.redaccion.services.script_proposal_service import (
        ScriptProposalService,
    )

    @dataclass
    class _FakeResponse:
        content: str

    llm = modelo_de_chat()
    llm.ainvoke = AsyncMock(
        return_value=_FakeResponse(
            content=(
                "import requests\n"
                "data = requests.get('http://evil.example/data')\n"
                "result = {'tables': [], 'metrics': [], 'free_text': data.text}\n"
            )
        )
    )

    service = ScriptProposalService(llm=llm, model_name="test-model")
    result = await service.propose("Descarga datos remotos.")
    assert result.audit_result.approved is False
    assert any(f.detail == "requests" for f in result.audit_result.findings)
    # PRO.1 — `requests` no es un hueco en una lista: es la red. Está en la denegación
    # explícita que el legacy ya tenía, así que es CRITICAL y nadie lo acepta mirándolo.
    assert result.audit_result.risk_level == "CRITICAL"
    assert result.audit_result.puede_revisarse is False


# ---------------------------------------------------------------------------
# 14. describe_test_data sugiere provider iban para columna IBAN
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_describe_test_data_suggests_iban_provider_for_iban_column(
    tmp_path,
) -> None:
    from server.app.core.storage import FsspecStorageService
    from server.app.modules.redaccion.pipelines.contracts import StorageRef
    from server.app.modules.redaccion.services.test_data_anonymizer import (
        TestDataAnonymizerService,
    )

    df = pd.DataFrame(
        {
            "Nombre": ["Juan Pérez", "María García"],
            "IBAN": ["ES7621000418401234567891", "ES1100491800052810279102"],
        }
    )
    bucket_root = tmp_path / "bucket"
    bucket_root.mkdir()
    storage = FsspecStorageService(backend="file", bucket=str(bucket_root))
    csv_bytes = df.to_csv(index=False).encode("utf-8")
    await storage.put("clientes.csv", csv_bytes)

    service = TestDataAnonymizerService(storage=storage)
    columns = await service.describe_columns(
        StorageRef(bucket="bucket", key="clientes.csv")
    )
    by_name = {c.name: c for c in columns}
    assert by_name["IBAN"].inferred_faker_provider == "iban"
    # La columna Nombre debería sugerir first_name o name
    assert by_name["Nombre"].inferred_faker_provider in ("first_name", "name")


# ---------------------------------------------------------------------------
# Helpers compartidos para tests del router (15-19)
# ---------------------------------------------------------------------------

@pytest.fixture
def test_app(tmp_path, monkeypatch):
    """App FastAPI con sesión mockeada y storage local."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from server.app.api.deps import get_current_user, get_session
    from server.app.core.auth.models import UserInfo
    from server.app.core.sandbox_client import LocalSandboxClient, get_sandbox_client
    from server.app.core.storage import FsspecStorageService, get_storage_service
    from server.app.routers.redaccion.scripts_router import (
        get_test_data_anonymizer,
        router,
    )
    from server.app.modules.redaccion.services.test_data_anonymizer import (
        TestDataAnonymizerService,
    )

    bucket_root = tmp_path / "bucket"
    bucket_root.mkdir()
    storage = FsspecStorageService(backend="file", bucket=str(bucket_root))

    # Sesión: dict[uuid -> HubScriptProposal]
    state: dict[str, Any] = {"proposals": {}}

    class _FakeSession:
        def add(self, obj):
            from server.app.modules.redaccion.database.models import HubScriptProposal
            if isinstance(obj, HubScriptProposal):
                state["proposals"][str(obj.id)] = obj

        async def flush(self):
            return None

        async def commit(self):
            return None

        async def get(self, model, key):
            from server.app.modules.redaccion.database.models import HubScriptProposal
            if model is HubScriptProposal:
                return state["proposals"].get(str(key))
            return None

    async def _override_session():
        yield _FakeSession()

    async def _override_user():
        return UserInfo(
            user_id=str(uuid.uuid4()), email="proposer@test.com", role="user"
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
    return client, state, storage, _override_user


def _seed_proposal(state, owner_id, *, target_owner_kind="user", with_test_result=False):
    """Insert directo en el dict de estado para tests del router."""
    from server.app.modules.redaccion.database.models import HubScriptProposal

    proposal = HubScriptProposal(
        id=uuid.uuid4(),
        proposer_user_id=owner_id,
        target_owner_kind=target_owner_kind,
        target_template_id=None,
        prompt_nl="dummy",
        code="result = {'tables': [], 'metrics': [], 'free_text': 'ok'}\n",
        audit_result_json={
            "approved": True,
            "risk_level": "low",
            "findings": [],
            "confidence": 1.0,
        },
        status="proposed",
        test_data_is_anonymized=False,
    )
    if with_test_result:
        proposal.test_result_json = {"hello": "world"}
        proposal.test_result_hash = "deadbeef"
        proposal.status = "tested"
    state["proposals"][str(proposal.id)] = proposal
    return proposal


# ---------------------------------------------------------------------------
# 15. /test exige datos anonimizados para target=platform
# ---------------------------------------------------------------------------

def test_test_endpoint_requires_anonymized_data_for_platform_target(test_app) -> None:
    client, state, _storage, override_user = test_app

    # Re-bind el override_user para devolver el mismo user que el proposer
    user_uuid = uuid.uuid4()
    from server.app.core.auth.models import UserInfo

    async def _user_override():
        return UserInfo(user_id=str(user_uuid), email="proposer@test.com", role="user")

    client.app.dependency_overrides[
        list(client.app.dependency_overrides.keys())[1]
    ] = _user_override
    # Trick: reaplicar el override correcto a get_current_user
    from server.app.api.deps import get_current_user

    client.app.dependency_overrides[get_current_user] = _user_override

    proposal = _seed_proposal(state, user_uuid, target_owner_kind="platform")
    response = client.post(
        f"/api/v1/redaccion/scripts/{proposal.id}/test",
        json={
            "test_data_ref": {"bucket": "bucket", "key": "irrelevante.xlsx"},
            "use_real_data": True,
        },
    )
    assert response.status_code == 422
    body = response.json()
    assert body["detail"]["code"] == "REAL_DATA_NOT_ALLOWED_FOR_PLATFORM_TARGET"


# ---------------------------------------------------------------------------
# 16. /test usa el mismo sandbox que AdminScriptExtractionPipeline
# ---------------------------------------------------------------------------

def test_test_endpoint_executes_in_same_sandbox_as_admin_pipeline(test_app) -> None:
    """Smoke check: el endpoint /test usa AdminScriptExtractionPipeline directamente
    (verificable por estructura del resultado retornado)."""
    client, state, _storage, _ = test_app
    from server.app.api.deps import get_current_user
    from server.app.core.auth.models import UserInfo

    user_uuid = uuid.uuid4()

    async def _user_override():
        return UserInfo(user_id=str(user_uuid), email="proposer@test.com", role="user")

    client.app.dependency_overrides[get_current_user] = _user_override

    proposal = _seed_proposal(state, user_uuid, target_owner_kind="user")

    response = client.post(
        f"/api/v1/redaccion/scripts/{proposal.id}/test",
        json={
            "test_data_ref": {"bucket": "bucket", "key": "dummy.xlsx"},
            "use_real_data": False,
        },
    )
    assert response.status_code == 200
    body = response.json()
    # El resultado expone la forma de ExtractionResult (warnings/provenance presentes
    # incluso si el script no produjo nada).
    assert body["status"] == "tested"
    assert "tables" in body["result"]
    assert "warnings" in body["result"]
    assert "provenance" in body["result"]
    assert body["result"]["provenance"]["pipeline_id"]  # non-empty string from sandbox client


# ---------------------------------------------------------------------------
# 17. /test persiste hash sha256
# ---------------------------------------------------------------------------

def test_test_endpoint_stores_result_hash(test_app) -> None:
    client, state, _storage, _ = test_app
    from server.app.api.deps import get_current_user
    from server.app.core.auth.models import UserInfo

    user_uuid = uuid.uuid4()

    async def _user_override():
        return UserInfo(user_id=str(user_uuid), email="proposer@test.com", role="user")

    client.app.dependency_overrides[get_current_user] = _user_override

    proposal = _seed_proposal(state, user_uuid)
    response = client.post(
        f"/api/v1/redaccion/scripts/{proposal.id}/test",
        json={
            "test_data_ref": {"bucket": "bucket", "key": "x.xlsx"},
            "use_real_data": False,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["hash"]) == 64
    assert all(c in "0123456789abcdef" for c in body["hash"])
    # Persistencia simulada: el proposal en state debería tener el hash igual
    persisted = state["proposals"][str(proposal.id)]
    assert persisted.test_result_hash == body["hash"]


# ---------------------------------------------------------------------------
# 18. /validate-test-result requiere test previo
# ---------------------------------------------------------------------------

def test_validate_test_result_requires_prior_test(test_app) -> None:
    client, state, _storage, _ = test_app
    from server.app.api.deps import get_current_user
    from server.app.core.auth.models import UserInfo

    user_uuid = uuid.uuid4()

    async def _user_override():
        return UserInfo(user_id=str(user_uuid), email="proposer@test.com", role="user")

    client.app.dependency_overrides[get_current_user] = _user_override

    # Sin test previo
    proposal = _seed_proposal(state, user_uuid, with_test_result=False)
    response = client.post(
        f"/api/v1/redaccion/scripts/{proposal.id}/validate-test-result"
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "TEST_NOT_RUN"


# ---------------------------------------------------------------------------
# 19. /validate-test-result marca timestamp cuando ya hay test
# ---------------------------------------------------------------------------

def test_validate_test_result_marks_proposer_validation_timestamp(test_app) -> None:
    client, state, _storage, _ = test_app
    from server.app.api.deps import get_current_user
    from server.app.core.auth.models import UserInfo

    user_uuid = uuid.uuid4()

    async def _user_override():
        return UserInfo(user_id=str(user_uuid), email="proposer@test.com", role="user")

    client.app.dependency_overrides[get_current_user] = _user_override

    proposal = _seed_proposal(state, user_uuid, with_test_result=True)
    response = client.post(
        f"/api/v1/redaccion/scripts/{proposal.id}/validate-test-result"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["proposal_id"] == str(proposal.id)
    assert body["test_validated_by_proposer_at"] is not None

    persisted = state["proposals"][str(proposal.id)]
    assert persisted.test_validated_by_proposer_at is not None
