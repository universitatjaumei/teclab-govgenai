"""`sandbox_client` tiene que poder importarse primero, sin nadie delante.

Encontrado al ejecutar `test_approval_workflow.py` en aislamiento durante PRO.1: el
fichero entero daba ERROR de colección con

    ImportError: cannot import name 'LocalSandboxClient' from partially initialized
    module 'server.app.core.sandbox_client' (most likely due to a circular import)

El ciclo es real y estaba latente: `sandbox_client` importa
`redaccion.pipelines.contracts`, y para llegar al submódulo Python inicializa primero el
paquete `redaccion.pipelines`, cuyo `__init__` reexportaba `admin_script_pipeline`, que
importa `sandbox_client` — todavía a medio cargar. En la suite completa no se ve porque
algún otro módulo carga el paquete antes; el orden lo decidía el azar.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[3]


def test_should_importar_sandbox_client_sin_nada_cargado_antes() -> None:
    proceso = subprocess.run(
        [sys.executable, "-c", "from server.app.core.sandbox_client import LocalSandboxClient"],
        cwd=str(_RAIZ),
        capture_output=True,
        text=True,
        check=False,
    )

    assert proceso.returncode == 0, proceso.stderr


def test_should_importar_el_paquete_de_pipelines_sin_nada_cargado_antes() -> None:
    proceso = subprocess.run(
        [
            sys.executable,
            "-c",
            "from server.app.modules.redaccion.pipelines.admin_script_pipeline "
            "import AdminScriptExtractionPipeline",
        ],
        cwd=str(_RAIZ),
        capture_output=True,
        text=True,
        check=False,
    )

    assert proceso.returncode == 0, proceso.stderr
