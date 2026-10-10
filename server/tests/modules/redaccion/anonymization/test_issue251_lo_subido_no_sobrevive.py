"""#251 — los datos de prueba de una propuesta de script no sobreviven a lo que los necesita.

Decisión del usuario (2026-10-09), las tres recomendaciones:

1. **El mapa ficticio→real no se guarda ni se devuelve.** Se guardaba en
   `test_data_anonymization_map` y no lo leía nadie —ni el reintento del administrador, que usa el
   sintético, ni la interfaz, que no lo mostraba—, y es la llave que deshace la anonimización.
2. **Lo subido se borra en cuanto deja de hacer falta**: al anonimizar, porque desde ahí todo usa
   el sintético; y al cerrar la propuesta —registrada, aprobada o rechazada—, que es cuando deja
   de hacer falta el original de quien probó con datos reales.
3. **El sintético se conserva**: es la prueba con la que se aprobó y reproduce su hash.

Lo subido vive bajo `test-data/uploads/{propuesta}/`, y el sintético en `test-data/` fuera de esa
carpeta, así que «borrar lo subido» es borrar esa carpeta entera: también las subidas que se
repitieron eligiendo otro fichero.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from server.tests.modules.redaccion.anonymization import (
    test_approval_workflow as _aprobacion,
    test_script_proposal_workflow as _propuesta,
)

# Las mismas fixtures y siembras que los tests del flujo: lo que cambia aquí es qué queda guardado.
approval_app = _aprobacion.approval_app
test_app = _propuesta.test_app
_seed_cerrable = _aprobacion._seed_proposal
_seed_template_and_version = _aprobacion._seed_template_and_version
_seed_proposal = _propuesta._seed_proposal

CSV = b"Nombre,Importe\nJuan Perez,10\nMaria Garcia,20\n"


def _storage_de(client):
    from server.app.core.storage import get_storage_service

    return client.app.dependency_overrides[get_storage_service]()


def _como(client, user_uuid, role="user"):
    from server.app.api.deps import get_current_user
    from server.app.core.auth.models import UserInfo

    async def _usuario():
        return UserInfo(user_id=str(user_uuid), email="p@test.com", role=role)

    client.app.dependency_overrides[get_current_user] = _usuario


async def _hay(storage, key) -> bool:
    return await storage.exists(key)


def _existe(storage, key) -> bool:
    import asyncio

    return asyncio.run(_hay(storage, key))


def _subir(storage, proposal_id, nombre="x.csv") -> str:
    import asyncio

    clave = f"test-data/uploads/{proposal_id}/{nombre}"
    asyncio.run(storage.put(clave, CSV))
    return clave


class TestElMapa:
    def test_should_not_have_a_column_for_the_map(self):
        from server.app.modules.redaccion.database.models import HubScriptProposal

        assert "test_data_anonymization_map" not in HubScriptProposal.__table__.c

    def test_should_have_a_migration_that_drops_it(self):
        versiones = Path(__file__).resolve().parents[4] / "migrations" / "versions"
        assert any(
            "#251" in texto and "test_data_anonymization_map" in texto and "drop_column" in texto
            for texto in (f.read_text(encoding="utf-8") for f in versiones.glob("*.py"))
        )


class TestAlAnonimizar:
    def test_should_answer_without_the_map_and_delete_every_upload(self, test_app):
        client, state, storage, _ = test_app
        user_uuid = uuid.uuid4()
        _como(client, user_uuid)
        proposal = _seed_proposal(state, user_uuid)

        # Dos subidas: quien elige otro fichero deja la primera atrás.
        refs = []
        for nombre in ("primera.csv", "segunda.csv"):
            respuesta = client.post(
                f"/api/v1/redaccion/scripts/{proposal.id}/describe-test-data",
                files={"file": (nombre, CSV, "text/csv")},
            )
            assert respuesta.status_code == 200, respuesta.text
            refs.append(respuesta.json()["file_ref"])
        assert all(_existe(storage, ref["key"]) for ref in refs)

        respuesta = client.post(
            f"/api/v1/redaccion/scripts/{proposal.id}/anonymize-test-data",
            json={"file_ref": refs[1], "kind": "csv", "substitutions": []},
        )

        assert respuesta.status_code == 200, respuesta.text
        cuerpo = respuesta.json()
        assert "anonymization_map" not in cuerpo
        assert not [ref for ref in refs if _existe(storage, ref["key"])]
        sintetico = cuerpo["synthetic_ref"]["key"]
        assert _existe(storage, sintetico)
        assert state["proposals"][str(proposal.id)].test_data_ref["key"] == sintetico


class TestAlCerrar:
    def test_should_delete_the_real_data_when_registering_in_a_private_template(
        self, approval_app
    ):
        client, state, holder = approval_app
        from server.app.core.auth.models import UserInfo

        user_uuid = uuid.uuid4()
        holder["user"] = UserInfo(user_id=str(user_uuid), email="u@t.com", role="user")
        template, _ = _seed_template_and_version(state, user_uuid)
        proposal = _seed_cerrable(
            state, user_uuid, target_template_id=template.id, is_anonymized=False
        )
        storage = _storage_de(client)
        original = _subir(storage, proposal.id)
        proposal.test_data_ref = {"bucket": "test-data", "key": original}

        respuesta = client.post(
            f"/api/v1/redaccion/scripts/{proposal.id}/save-to-private-template",
            json={
                "finalidad": "Extraer la tabla de gastos",
                "categorias_datos": ["datos_economicos_y_financieros"],
                "nombre": "Extraer gastos",
            },
        )

        assert respuesta.status_code == 200, respuesta.text
        assert not _existe(storage, original)

    def _pendiente(self, approval_app):
        client, state, holder = approval_app
        from server.app.core.auth.models import UserInfo

        admin_uuid = uuid.uuid4()
        holder["user"] = UserInfo(user_id=str(admin_uuid), email="a@t.com", role="admin")
        template, _ = _seed_template_and_version(state, admin_uuid, is_global=True)
        proposal = _seed_cerrable(
            state,
            uuid.uuid4(),
            status="pending_review",
            target_owner_kind="platform",
            admin_retest_json={
                "hash": "abc",
                "hash_matches": True,
                "retested_at": datetime.now(timezone.utc).isoformat(),
                "retester_user_id": str(admin_uuid),
            },
        )
        storage = _storage_de(client)
        resto = _subir(storage, proposal.id, "subida-repetida.csv")
        sintetico = f"test-data/{uuid.uuid4()}.csv"
        import asyncio

        asyncio.run(storage.put(sintetico, CSV))
        proposal.test_data_ref = {"bucket": "test-data", "key": sintetico}
        return client, proposal, template, storage, resto, sintetico

    def test_should_delete_leftovers_and_keep_the_synthetic_when_rejecting(self, approval_app):
        client, proposal, _, storage, resto, sintetico = self._pendiente(approval_app)

        respuesta = client.post(
            f"/api/v1/redaccion/scripts/{proposal.id}/reject", json={"review_note": "No."}
        )

        assert respuesta.status_code == 200, respuesta.text
        assert not _existe(storage, resto)
        assert _existe(storage, sintetico)

    def test_should_delete_leftovers_and_keep_the_synthetic_when_approving(self, approval_app):
        client, proposal, template, storage, resto, sintetico = self._pendiente(approval_app)

        respuesta = client.post(
            f"/api/v1/redaccion/scripts/{proposal.id}/approve",
            json={"target_global_template_id": str(template.id)},
        )

        assert respuesta.status_code == 200, respuesta.text
        assert not _existe(storage, resto)
        assert _existe(storage, sintetico)
