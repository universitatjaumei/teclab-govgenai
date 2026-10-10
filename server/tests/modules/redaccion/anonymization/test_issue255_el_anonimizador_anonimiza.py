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
