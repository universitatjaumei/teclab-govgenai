"""#258 — si falla el borrado de ficheros después del commit, la operación ya está hecha.

Varios endpoints borran del almacenamiento **después** del commit, a propósito: el almacenamiento no
es transaccional y, al revés, un fallo dejaría la fila apuntando a ficheros que ya no existen
(`delete_chatbot` y `delete_organizacion` con las fuentes de ingesta, #253; anonimizar, guardar,
aprobar y rechazar con lo subido para una propuesta de script, #251). Encontrado en la auditoría
independiente de la PR #256: si ese borrado fallaba, la respuesta era un 500 de algo que sí había
ocurrido —y en anonimizar, el asistente se quedaba sin el sintético y probaba con el original—, y
lo que no se borró se quedaba para siempre.

Ahora el fallo se registra y no cambia la respuesta, y **un barrido recoge lo que quedó**: las
fuentes de chatbots que ya no existen y las subidas de propuestas que no existen o están cerradas.
Las de propuestas **abiertas y abandonadas** no se tocan: borrarlas exige un plazo, y los plazos son
#162.

Hay dos caminos y los dos se prueban, que es la regla de una guarda defensiva: el bueno —el fichero
se borra— sigue en `test_issue251_*` y `test_issue253_*`; aquí, el del almacenamiento fallando, y el
barrido que lo arregla después.
"""
from __future__ import annotations

import logging
import uuid

import pytest

from server.tests.modules.redaccion.anonymization import (
    test_script_proposal_workflow as _propuesta,
)

test_app = _propuesta.test_app
_seed_proposal = _propuesta._seed_proposal

@pytest.fixture
async def db_session(db_url: str):
    from server.app.modules.agents_hub.database.connection import (
        create_async_engine,
        create_session_factory,
    )

    motor = create_async_engine(db_url)
    async with create_session_factory(motor)() as s:
        yield s
    await motor.dispose()


CSV = "Nombre,IBAN,Importe\nJuan Pérez,ES7621000418401234567891,10\n".encode("utf-8")


class _AlmacenQueNoBorra:
    """Guarda y lee de verdad, y falla al borrar: la nube que no responde a un `rm`."""

    def __init__(self, real):
        self._real = real

    async def put(self, key, data):
        await self._real.put(key, data)

    async def get(self, key):
        return await self._real.get(key)

    async def exists(self, key):
        return await self._real.exists(key)

    async def delete(self, key):
        raise OSError("el bucket no responde")

    async def delete_prefix(self, prefix):
        raise OSError("el bucket no responde")

    async def listar(self, prefix):
        return await self._real.listar(prefix)


# ───────────────────────── El almacenamiento sabe listar ─────────────────────────


@pytest.mark.asyncio
async def test_listar_da_los_hijos_directos_y_nada_si_no_existe(tmp_path):
    from server.app.core.storage import FsspecStorageService

    almacen = FsspecStorageService(backend="file", bucket=str(tmp_path))
    await almacen.put("ingestion/a/1.md", b"x")
    await almacen.put("ingestion/a/2.md", b"x")
    await almacen.put("ingestion/b/1.md", b"x")

    assert sorted(await almacen.listar("ingestion/")) == ["a", "b"]
    assert await almacen.listar("no-existe/") == []


# ───────────────────────── El fallo no cambia la respuesta ─────────────────────────


def test_anonimizar_responde_aunque_no_pueda_borrar_lo_subido(test_app, caplog):
    from server.app.core.storage import get_storage_service
    from server.app.routers.redaccion.scripts_router import get_test_data_anonymizer
    from server.app.modules.redaccion.services.test_data_anonymizer import (
        TestDataAnonymizerService,
    )

    client, state, storage, _ = test_app
    roto = _AlmacenQueNoBorra(storage)
    client.app.dependency_overrides[get_storage_service] = lambda: roto
    client.app.dependency_overrides[get_test_data_anonymizer] = lambda: TestDataAnonymizerService(
        storage=roto
    )
    user_uuid = uuid.uuid4()
    from server.app.api.deps import get_current_user
    from server.app.core.auth.models import UserInfo

    async def _usuario():
        return UserInfo(user_id=str(user_uuid), email="p@t.com", role="user")

    client.app.dependency_overrides[get_current_user] = _usuario
    proposal = _seed_proposal(state, user_uuid)
    subida = client.post(
        f"/api/v1/redaccion/scripts/{proposal.id}/describe-test-data",
        files={"file": ("datos.csv", CSV, "text/csv")},
    ).json()["file_ref"]

    with caplog.at_level(logging.WARNING):
        respuesta = client.post(
            f"/api/v1/redaccion/scripts/{proposal.id}/anonymize-test-data",
            json={"file_ref": subida, "kind": "csv"},
        )

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["synthetic_ref"]["key"]
    assert state["proposals"][str(proposal.id)].test_data_is_anonymized
    assert any("no se pudo borrar" in m.lower() for m in caplog.messages), caplog.messages


@pytest.mark.asyncio
async def test_borrar_las_fuentes_de_un_chatbot_no_lanza_si_el_almacen_falla(tmp_path, caplog):
    from server.app.core.storage import FsspecStorageService
    from server.app.modules.agents_hub.services.corpus_purge import borrar_fuentes_del_chatbot

    roto = _AlmacenQueNoBorra(FsspecStorageService(backend="file", bucket=str(tmp_path)))
    with caplog.at_level(logging.WARNING):
        await borrar_fuentes_del_chatbot(roto, uuid.uuid4())

    assert any("no se pudo borrar" in m.lower() for m in caplog.messages), caplog.messages


# ───────────────────────── El barrido recoge lo que quedó ─────────────────────────


@pytest.mark.asyncio
async def test_el_barrido_borra_las_fuentes_de_chatbots_que_ya_no_existen(db_session, tmp_path):
    from server.app.core.storage import FsspecStorageService
    from server.app.modules.agents_hub.database.config_models import (
        HubChatbot,
        HubLLMConfig,
        HubOrganizacion,
        HubProvider,
    )
    from server.app.modules.agents_hub.services.corpus_purge import barrer_fuentes_huerfanas

    almacen = FsspecStorageService(backend="file", bucket=str(tmp_path))
    await db_session.merge(HubProvider(id="google", name="Google", provider_type="google_genai"))
    llm = HubLLMConfig(provider="google", model_name="gemini-2.0-flash", temperature=0.2)
    org = uuid.uuid4()
    db_session.add_all([llm, HubOrganizacion(id=org, name=f"O {org.hex[:6]}", partner_id=f"p{org.hex[:6]}")])
    await db_session.flush()
    vivo = HubChatbot(organizacion_id=org, llm_config_id=llm.id, name=f"B {org.hex[:6]}", system_prompt="x")
    db_session.add(vivo)
    await db_session.flush()
    borrado = uuid.uuid4()
    await almacen.put(f"ingestion/{vivo.id}/a.md", b"x")
    await almacen.put(f"ingestion/{borrado}/a.md", b"x")
    await almacen.put("ingestion/no-es-un-uuid/a.md", b"x")

    retirados = await barrer_fuentes_huerfanas(db_session, almacen)

    assert retirados == 1
    assert await almacen.exists(f"ingestion/{vivo.id}/a.md")
    assert not await almacen.exists(f"ingestion/{borrado}")
    # Lo que no sabe interpretar no lo toca.
    assert await almacen.exists("ingestion/no-es-un-uuid/a.md")


@pytest.mark.asyncio
async def test_el_barrido_borra_las_subidas_de_propuestas_cerradas_o_que_no_existen(
    db_session, tmp_path
):
    from server.app.core.storage import FsspecStorageService
    from server.app.modules.redaccion.database.models import HubScriptProposal
    from server.app.modules.redaccion.services.subidas_huerfanas import barrer_subidas_huerfanas

    almacen = FsspecStorageService(backend="file", bucket=str(tmp_path))

    def _propuesta(status):
        return HubScriptProposal(
            proposer_user_id=uuid.uuid4(), target_owner_kind="user", prompt_nl="x", code="x",
            audit_result_json={}, status=status,
        )

    abierta, rechazada, registrada = _propuesta("tested"), _propuesta("rejected"), _propuesta("registrada")
    db_session.add_all([abierta, rechazada, registrada])
    await db_session.flush()
    inexistente = uuid.uuid4()
    for p in (abierta.id, rechazada.id, registrada.id, inexistente):
        await almacen.put(f"test-data/uploads/{p}/f.csv", b"x")

    retirados = await barrer_subidas_huerfanas(db_session, almacen)

    assert retirados == 3
    # La abierta se queda: borrar lo de una propuesta abandonada exige un plazo (#162).
    assert await almacen.exists(f"test-data/uploads/{abierta.id}/f.csv")
    for p in (rechazada.id, registrada.id, inexistente):
        assert not await almacen.exists(f"test-data/uploads/{p}")


def test_el_arranque_lanza_los_dos_barridos():
    import ast
    from pathlib import Path

    main = Path(__file__).resolve().parents[2] / "app" / "main.py"
    arbol = ast.parse(main.read_text(encoding="utf-8"))
    arranque = next(
        n for n in ast.walk(arbol) if isinstance(n, ast.AsyncFunctionDef) and n.name == "_arranque"
    )
    nombres = {n.id for n in ast.walk(arranque) if isinstance(n, ast.Name)} | {
        n.attr for n in ast.walk(arranque) if isinstance(n, ast.Attribute)
    }
    assert {"barrer_fuentes_huerfanas", "barrer_subidas_huerfanas"} <= nombres
