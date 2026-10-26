"""El fichero de prueba tiene que llegar **dentro** del sandbox — PRO.2.

Encontrado recorriendo el asistente de scripts en navegador: la ejecución devolvía
`SCRIPT_EXECUTION_ERROR` con este traceback del contenedor del sandbox:

    File "/tmp/sandbox/tmp3tubrj_j.py", line 15, in <module>
        df = pd.read_excel(file_path)
    ...pandas/io/excel/_base.py, inspect_excel_format

`AdminScriptExtractionPipeline` construía `Path(file_ref.bucket) / file_ref.key` y mandaba
**esa cadena** como `file_path`. Es una ruta del host de la API —y encima relativa al bucket
de `StorageService`, que en producción es GCS y no un directorio—, así que dentro del
contenedor del sandbox no existe ningún fichero ahí. Ningún script de extracción podía leer
su fichero: el camino no había funcionado nunca.

La forma correcta ya estaba inventada en el propio sandbox: `/execute-chart` y `/execute-etl`
reciben **el contenido** (`data_csv`) y lo escriben en su propio temporal. La extracción hace
ahora lo mismo, y el contenido se lee por `StorageService`, que es la única forma de que esto
funcione igual con un directorio local, con MinIO y con GCS.
"""
from __future__ import annotations

import base64
from typing import Any

import pytest

from server.app.modules.redaccion.pipelines.contracts import ExtractionInput, StorageRef

_CODIGO = (
    "import pandas as pd\n"
    "df = pd.read_excel(file_path)\n"
    "result = {'tables': [], 'metrics': [{'name': 'filas', 'value': len(df)}]}\n"
)


class _ClienteEspia:
    """Registra lo que la tubería manda al sandbox."""

    def __init__(self) -> None:
        self.recibido: dict[str, Any] = {}

    async def execute_extraction_script(self, **kwargs):
        from server.app.modules.redaccion.pipelines.contracts import (
            ExtractionProvenance,
            ExtractionResult,
        )
        from datetime import datetime, timezone

        self.recibido = kwargs
        return ExtractionResult(
            provenance=ExtractionProvenance(
                pipeline_id="espia",
                source_ref="espia",
                extracted_at=datetime.now(timezone.utc),
            )
        )


class _AlmacenFalso:
    """Lo mínimo de `StorageService` que la tubería necesita."""

    def __init__(self, contenido: bytes) -> None:
        self._contenido = contenido
        self.pedido: str | None = None

    async def get(self, key: str) -> bytes:
        self.pedido = key
        return self._contenido


@pytest.mark.asyncio
async def test_should_mandar_el_contenido_del_fichero_y_no_una_ruta_del_host() -> None:
    from server.app.modules.redaccion.pipelines.admin_script_pipeline import (
        AdminScriptExtractionPipeline,
    )

    cliente = _ClienteEspia()
    almacen = _AlmacenFalso(b"PK\x03\x04 contenido del xlsx")
    tuberia = AdminScriptExtractionPipeline(client=cliente, storage=almacen)

    await tuberia.extract_async(ExtractionInput(
        source_kind="admin_script",
        file_ref=StorageRef(bucket="test-data", key="test-data/uploads/p1/f.xlsx"),
        options={"code": _CODIGO, "approved": True},
    ))

    assert almacen.pedido == "test-data/uploads/p1/f.xlsx", (
        "el fichero se lee por StorageService con su clave, no del disco"
    )
    assert cliente.recibido["file_bytes"] == b"PK\x03\x04 contenido del xlsx"
    assert cliente.recibido["file_name"] == "f.xlsx", (
        "el nombre viaja porque pandas elige el motor por la extensión"
    )


@pytest.mark.asyncio
async def test_should_no_pedir_nada_al_almacen_sin_fichero() -> None:
    """Un script que trabaja sobre `raw_text` no tiene fichero, y eso es legítimo."""
    from server.app.modules.redaccion.pipelines.admin_script_pipeline import (
        AdminScriptExtractionPipeline,
    )

    cliente = _ClienteEspia()
    almacen = _AlmacenFalso(b"")
    tuberia = AdminScriptExtractionPipeline(client=cliente, storage=almacen)

    await tuberia.extract_async(ExtractionInput(
        source_kind="admin_script",
        raw_text="una linea",
        options={"code": "result = {'free_text': raw_text}", "approved": True},
    ))

    assert almacen.pedido is None
    assert cliente.recibido["file_bytes"] is None


@pytest.mark.asyncio
async def test_should_avisar_cuando_el_fichero_no_esta_en_el_almacen() -> None:
    """Antes esto era un traceback de pandas dentro del sandbox, sin decir qué faltaba."""
    from server.app.modules.redaccion.pipelines.admin_script_pipeline import (
        AdminScriptExtractionPipeline,
    )

    class _AlmacenVacio:
        async def get(self, key: str) -> bytes:
            raise FileNotFoundError(key)

    resultado = await AdminScriptExtractionPipeline(
        client=_ClienteEspia(), storage=_AlmacenVacio()
    ).extract_async(ExtractionInput(
        source_kind="admin_script",
        file_ref=StorageRef(bucket="test-data", key="no/existe.xlsx"),
        options={"code": _CODIGO, "approved": True},
    ))

    codigos = [w.code for w in resultado.warnings]
    assert "TEST_DATA_NOT_FOUND" in codigos
    assert any(w.severity == "error" for w in resultado.warnings)


# ---------------------------------------------------------------------------
# El transporte, en el cliente y en el sandbox
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_should_viajar_el_contenido_en_base64_por_http(monkeypatch) -> None:
    from server.app.core.sandbox_client import HttpSandboxClient

    enviado: dict[str, Any] = {}

    class _Respuesta:
        status_code = 200

        def json(self) -> dict:
            return {"result": {"tables": [], "metrics": [], "free_text": None}}

    async def _post(self, ruta: str, payload: dict, script_timeout: int):
        enviado.update(payload)
        return _Respuesta()

    monkeypatch.setattr(HttpSandboxClient, "_post_with_retry", _post)

    await HttpSandboxClient(base_url="http://sandbox:5000").execute_extraction_script(
        code=_CODIGO,
        file_path=None,
        raw_text=None,
        options={},
        file_bytes=b"contenido binario",
        file_name="datos.xlsx",
    )

    assert base64.b64decode(enviado["file_bytes_b64"]) == b"contenido binario"
    assert enviado["file_name"] == "datos.xlsx"


def test_should_escribir_el_sandbox_el_fichero_en_su_propio_temporal() -> None:
    """La prueba que cierra el agujero: el script lee de verdad lo que se le manda."""
    import io
    import sys
    from pathlib import Path

    import pandas as pd

    raiz = Path(__file__).resolve().parents[4] / "services" / "script_sandbox"
    if str(raiz) not in sys.path:
        sys.path.insert(0, str(raiz))

    from fastapi.testclient import TestClient

    from sandbox.main import app  # type: ignore[import-not-found]

    buffer = io.BytesIO()
    pd.DataFrame({"capitulo": ["1", "2"], "importe": [10, 20]}).to_excel(buffer, index=False)

    respuesta = TestClient(app).post(
        "/execute-extraction",
        json={
            "code": (
                "import pandas as pd\n"
                "df = pd.read_excel(file_path)\n"
                "result = {'tables': [], 'metrics': [{'name': 'filas', 'value': len(df)}],"
                " 'free_text': None}\n"
            ),
            "file_bytes_b64": base64.b64encode(buffer.getvalue()).decode("ascii"),
            "file_name": "datos.xlsx",
            "raw_text": "",
            "options": {},
            "timeout_seconds": 30,
        },
    )

    assert respuesta.status_code == 200, respuesta.text
    metricas = respuesta.json()["result"]["metrics"]
    assert metricas[0]["value"] == 2
