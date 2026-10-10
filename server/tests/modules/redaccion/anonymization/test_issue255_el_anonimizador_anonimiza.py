"""#255 — con Excel y CSV, el anonimizador de datos de prueba no anonimizaba nada.

El asistente llamaba a `anonymize-test-data` sin `substitutions`, y con la lista vacía
`anonymize_tabular` no cambiaba ninguna columna: escribía una copia idéntica al original y la
propuesta quedaba marcada como anonimizada. Desde #251 el original se borra y el «sintético» se
conserva como prueba, así que lo conservado eran los datos reales.

**El servidor ya no depende de que el cliente se acuerde**: una columna que no le llega se trata
con lo que él mismo propuso al describirla (`describe-test-data`). Lo que el cliente manda manda,
`keep` incluido, que es como se dice «esta columna no es dato personal».
"""
from __future__ import annotations

import asyncio
import io
import uuid

import pandas as pd

from server.tests.modules.redaccion.anonymization import (
    test_script_proposal_workflow as _propuesta,
)

test_app = _propuesta.test_app
_seed_proposal = _propuesta._seed_proposal

IBAN_1 = "ES7621000418401234567891"
IBAN_2 = "ES1100491800052810279102"
CSV = (
    "Nombre,IBAN,Importe\n"
    f"Juan Pérez,{IBAN_1},10\n"
    f"María García,{IBAN_2},20\n"
).encode("utf-8")


def _como(client, user_uuid):
    from server.app.api.deps import get_current_user
    from server.app.core.auth.models import UserInfo

    async def _usuario():
        return UserInfo(user_id=str(user_uuid), email="p@test.com", role="user")

    client.app.dependency_overrides[get_current_user] = _usuario


def _anonimizar(test_app, **cuerpo_extra):
    client, state, storage, _ = test_app
    user_uuid = uuid.uuid4()
    _como(client, user_uuid)
    proposal = _seed_proposal(state, user_uuid)
    subida = client.post(
        f"/api/v1/redaccion/scripts/{proposal.id}/describe-test-data",
        files={"file": ("datos.csv", CSV, "text/csv")},
    )
    assert subida.status_code == 200, subida.text
    respuesta = client.post(
        f"/api/v1/redaccion/scripts/{proposal.id}/anonymize-test-data",
        json={"file_ref": subida.json()["file_ref"], "kind": "csv", **cuerpo_extra},
    )
    assert respuesta.status_code == 200, respuesta.text
    clave = respuesta.json()["synthetic_ref"]["key"]
    return pd.read_csv(io.BytesIO(asyncio.run(storage.get(clave))), dtype=str)


def test_sin_sustituciones_aplica_lo_que_el_servidor_propuso(test_app):
    sintetico = _anonimizar(test_app)

    assert IBAN_1 not in set(sintetico["IBAN"])
    assert IBAN_2 not in set(sintetico["IBAN"])
    assert "Juan Pérez" not in set(sintetico["Nombre"])
    # Lo que no es dato personal se queda como estaba.
    assert list(sintetico["Importe"]) == ["10", "20"]


def test_lo_que_manda_el_cliente_manda_y_keep_mantiene_la_columna(test_app):
    sintetico = _anonimizar(
        test_app, substitutions=[{"column_name": "Nombre", "faker_provider": "keep"}]
    )

    assert list(sintetico["Nombre"]) == ["Juan Pérez", "María García"]
    # La que no se mencionó sigue la propuesta del servidor.
    assert IBAN_1 not in set(sintetico["IBAN"])


# ---------------------------------------------------------------------------
# 2–4 — el informe de anonimización: qué se hizo, qué quedó, quién lo aceptó y quién lo ve
# ---------------------------------------------------------------------------
#
# Sin guardar ni un valor. La segunda pasada no vuelve a buscar datos personales en el sintético
# —encontraría los IBAN y DNI inventados, que tienen la misma forma que los reales—: comprueba si
# algún **valor original** sigue en el resultado, y se calcula en memoria al anonimizar.

from server.tests.modules.redaccion.anonymization import (  # noqa: E402
    test_approval_workflow as _aprobacion,
)

approval_app = _aprobacion.approval_app
_seed_cerrable = _aprobacion._seed_proposal


def _anonimizar_entero(test_app, **cuerpo_extra):
    client, state, storage, _ = test_app
    user_uuid = uuid.uuid4()
    _como(client, user_uuid)
    proposal = _seed_proposal(state, user_uuid)
    subida = client.post(
        f"/api/v1/redaccion/scripts/{proposal.id}/describe-test-data",
        files={"file": ("datos.csv", CSV, "text/csv")},
    )
    respuesta = client.post(
        f"/api/v1/redaccion/scripts/{proposal.id}/anonymize-test-data",
        json={"file_ref": subida.json()["file_ref"], "kind": "csv", **cuerpo_extra},
    )
    assert respuesta.status_code == 200, respuesta.text
    return client, state, proposal, respuesta.json()


def test_el_informe_dice_que_se_sustituyo_y_no_lleva_valores(test_app):
    _, state, proposal, cuerpo = _anonimizar_entero(test_app)

    informe = cuerpo["informe"]
    assert informe["tipo"] == "tabular"
    sustituidas = {s["columna"]: s["sustituto"] for s in informe["sustituidas"]}
    assert sustituidas["IBAN"] == "iban"
    assert "Nombre" in sustituidas
    assert informe["restos"] == 0
    assert informe["requiere_aceptacion"] is False
    # Queda guardado en la propuesta, y sin ningún valor del fichero.
    guardado = state["proposals"][str(proposal.id)].anonymization_report_json
    assert guardado["sustituidas"] == informe["sustituidas"]
    texto = str(guardado)
    assert IBAN_1 not in texto and "Juan" not in texto


def test_mantener_una_columna_que_el_servidor_veia_personal_pide_aceptarlo(test_app):
    _, _, _, cuerpo = _anonimizar_entero(
        test_app, substitutions=[{"column_name": "Nombre", "faker_provider": "keep"}]
    )

    informe = cuerpo["informe"]
    mantenidas = {m["columna"]: m["propuesta"] for m in informe["mantenidas"]}
    assert mantenidas["Nombre"] != "keep"
    assert informe["requiere_aceptacion"] is True


def test_en_un_pdf_cuenta_por_tipo_lo_sustituido_y_lo_rechazado(tmp_path, monkeypatch):
    from server.app.core.storage import FsspecStorageService
    from server.app.modules.redaccion.pipelines.contracts import StorageRef
    from server.app.modules.redaccion.services.test_data_anonymizer import (
        SpanOverride,
        TestDataAnonymizerService,
    )

    texto = f"El interesado con DNI 12345678Z y cuenta {IBAN_1} solicita la ayuda."
    storage = FsspecStorageService(backend="file", bucket=str(tmp_path))
    servicio = TestDataAnonymizerService(storage=storage)

    async def _markdown(_ref):
        return texto

    monkeypatch.setattr(servicio, "_extract_pdf_markdown", _markdown)
    ref = StorageRef(bucket="test-data", key="test-data/uploads/p/x.pdf")
    spans = asyncio.run(servicio.preview_pdf_spans(ref))
    dni = next(s for s in spans if "12345678Z" in texto[s.start : s.end])

    resultado = asyncio.run(
        servicio.anonymize_pdf_to_text(
            ref, [SpanOverride(start=dni.start, end=dni.end, accept=False)]
        )
    )

    informe = resultado.informe
    assert informe.tipo == "pdf"
    assert sum(informe.fragmentos.values()) >= 1
    assert sum(informe.rechazados.values()) == 1
    assert informe.restos == 0  # lo aceptado no queda; lo rechazado se cuenta aparte
    assert informe.requiere_aceptacion is True
    assert "12345678Z" not in str(informe.model_dump())


_INFORME_CON_RESTOS = {
    "tipo": "tabular",
    "sustituidas": [{"columna": "IBAN", "sustituto": "iban"}],
    "mantenidas": [{"columna": "Nombre", "propuesta": "first_name"}],
    "fragmentos": {},
    "rechazados": {},
    "restos": 0,
    "requiere_aceptacion": True,
}


def _pedir_revision(approval_app, cuerpo=None):
    client, state, holder = approval_app
    from server.app.core.auth.models import UserInfo

    user_uuid = uuid.uuid4()
    holder["user"] = UserInfo(user_id=str(user_uuid), email="u@t.com", role="user")
    proposal = _seed_cerrable(state, user_uuid, target_owner_kind="platform")
    proposal.anonymization_report_json = dict(_INFORME_CON_RESTOS)
    url = f"/api/v1/redaccion/scripts/{proposal.id}/submit-for-review"
    respuesta = client.post(url, json=cuerpo) if cuerpo is not None else client.post(url)
    return respuesta, proposal, user_uuid


def test_sin_aceptar_lo_que_queda_no_se_pide_revision_para_plantilla_global(approval_app):
    respuesta, proposal, _ = _pedir_revision(approval_app)

    assert respuesta.status_code == 422, respuesta.text
    assert respuesta.json()["detail"]["code"] == "RESTOS_SIN_ACEPTAR"
    assert proposal.status != "pending_review"


def test_aceptandolo_se_pide_y_queda_dicho_quien_y_cuando(approval_app):
    respuesta, proposal, user_uuid = _pedir_revision(approval_app, {"acepto_restos": True})

    assert respuesta.status_code == 200, respuesta.text
    informe = proposal.anonymization_report_json
    assert informe["aceptado_por"] == str(user_uuid)
    assert informe["aceptado_en"]


def test_la_cola_de_revision_trae_el_informe(approval_app, monkeypatch):
    client, state, holder = approval_app
    from server.app.core.auth.models import UserInfo
    from server.app.modules.redaccion.database.repos import ScriptProposalRepo

    holder["user"] = UserInfo(user_id=str(uuid.uuid4()), email="a@t.com", role="admin")
    p = _seed_cerrable(state, uuid.uuid4(), status="pending_review", target_owner_kind="platform")
    p.anonymization_report_json = dict(_INFORME_CON_RESTOS)

    async def _por_estado(self, status):
        return [x for x in state["HubScriptProposal"].values() if x.status == status]

    monkeypatch.setattr(ScriptProposalRepo, "list_by_status", _por_estado)
    cuerpo = client.get("/api/v1/redaccion/scripts/pending").json()

    assert cuerpo[0]["informe_anonimizacion"]["mantenidas"] == _INFORME_CON_RESTOS["mantenidas"]


def test_el_sintetico_se_descarga_por_quien_propone_y_por_un_admin_y_nadie_mas(test_app):
    client, _, proposal, _ = _anonimizar_entero(test_app)
    url = f"/api/v1/redaccion/scripts/{proposal.id}/test-data"

    respuesta = client.get(url)
    assert respuesta.status_code == 200
    assert b"Importe" in respuesta.content

    _como(client, uuid.uuid4())
    assert client.get(url).status_code == 403

    from server.app.api.deps import get_current_user
    from server.app.core.auth.models import UserInfo

    async def _admin():
        return UserInfo(user_id=str(uuid.uuid4()), email="a@t.com", role="admin")

    client.app.dependency_overrides[get_current_user] = _admin
    proposal.status = "pending_review"  # quien revisa, cuando hay algo que revisar
    assert client.get(url).status_code == 200


def test_lo_que_no_esta_anonimizado_no_se_descarga(test_app):
    """Lo subido sin anonimizar son datos reales: no se sirven, ni siquiera a quien los subió."""
    client, state, _, _ = test_app
    user_uuid = uuid.uuid4()
    _como(client, user_uuid)
    proposal = _seed_proposal(state, user_uuid)
    proposal.test_data_ref = {"bucket": "test-data", "key": "test-data/uploads/x/y.csv"}

    respuesta = client.get(f"/api/v1/redaccion/scripts/{proposal.id}/test-data")
    assert respuesta.status_code == 404


# ---------------------------------------------------------------------------
# Auditoría independiente de la PR #256 (2026-10-10)
# ---------------------------------------------------------------------------


def test_no_se_anonimiza_un_fichero_que_no_se_subio_para_esta_propuesta(test_app):
    """`file_ref` lo manda el cliente. Sin comprobarlo, con `keep` en todas las columnas el
    «sintético» era una copia de cualquier clave del almacenamiento —de otra propuesta, de otra
    organización—, y la descarga nueva se la servía a quien la pidió."""
    client, state, storage, _ = test_app
    ajena = "test-data/uploads/otra-propuesta/fichero.csv"
    asyncio.run(storage.put(ajena, CSV))
    user_uuid = uuid.uuid4()
    _como(client, user_uuid)
    proposal = _seed_proposal(state, user_uuid)

    respuesta = client.post(
        f"/api/v1/redaccion/scripts/{proposal.id}/anonymize-test-data",
        json={
            "file_ref": {"bucket": "test-data", "key": ajena},
            "kind": "csv",
            "substitutions": [
                {"column_name": c, "faker_provider": "keep"} for c in ("Nombre", "IBAN", "Importe")
            ],
        },
    )

    assert respuesta.status_code == 404, respuesta.text
    assert not state["proposals"][str(proposal.id)].test_data_is_anonymized


def test_un_admin_que_no_propuso_solo_lo_baja_si_esta_pendiente_de_revision(test_app):
    """La cola de revisión es el único motivo para que otra persona lo vea. Una propuesta privada,
    que nunca pasa por la cola, no se la baja ningún administrador."""
    client, _, proposal, _ = _anonimizar_entero(test_app)
    url = f"/api/v1/redaccion/scripts/{proposal.id}/test-data"

    from server.app.api.deps import get_current_user
    from server.app.core.auth.models import UserInfo

    async def _admin():
        return UserInfo(user_id=str(uuid.uuid4()), email="a@t.com", role="admin")

    client.app.dependency_overrides[get_current_user] = _admin
    assert client.get(url).status_code == 404

    proposal.status = "pending_review"
    assert client.get(url).status_code == 200


def test_si_el_fichero_ya_no_esta_es_un_404_y_no_un_500(test_app):
    client, state, storage, _ = test_app
    user_uuid = uuid.uuid4()
    _como(client, user_uuid)
    proposal = _seed_proposal(state, user_uuid)
    proposal.test_data_is_anonymized = True
    proposal.test_data_ref = {"bucket": "test-data", "key": "test-data/no-existe.csv"}

    assert client.get(f"/api/v1/redaccion/scripts/{proposal.id}/test-data").status_code == 404
