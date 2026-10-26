"""El auditor del sandbox no puede ser más laxo que el de la API.

Hay dos copias del auditor a propósito (`docs/SANDBOX_SECURITY.md`, SBX.4): la de la API
mira el código antes de mandarlo, y la del sandbox lo vuelve a mirar justo antes del
`exec`. El contrato escrito dice que si divergen es porque **el sandbox es más estricto**,
nunca menos — pero hasta PRO.1 ese contrato solo vivía en un docstring, así que endurecer
la copia de la API dejaba la del sandbox atrás sin que nada lo notara. Y es lo que pasó:
PRO.1 le añadió las rutas absolutas a la API.

El test no compara las listas —divergir está permitido— sino el veredicto: todo lo que la
API considera crítico, el sandbox tiene que rechazarlo también.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

_RAIZ = Path(__file__).resolve().parents[3]
_AUDITOR_SANDBOX = _RAIZ / "services" / "script_sandbox" / "sandbox" / "auditor.py"
_NOMBRE_MODULO = "_sandbox_auditor_bajo_prueba"

# Cada entrada es código que la API considera CRITICAL. La copia del sandbox es la última
# barrera antes del `exec`: no puede aprobar ninguno.
_CODIGOS_CRITICOS = [
    "result = eval('1+1')\n",
    "import os\nresult = {}\n",
    "__builtins__['eval']('1+1')\n",
    "().__class__.__bases__[0].__subclasses__()\n",
    "import pandas as pd\ndf = pd.read_excel('C:\\\\Users\\\\fabra\\\\datos.xlsx')\n",
    "import pandas as pd\ndf = pd.read_excel('C:/Users/fabra/datos.xlsx')\n",
    "import pandas as pd\ndf = pd.read_csv('/etc/passwd')\n",
]


def _cargar_auditor_del_sandbox() -> ModuleType:
    if (ya := sys.modules.get(_NOMBRE_MODULO)) is not None:
        return ya

    spec = importlib.util.spec_from_file_location(_NOMBRE_MODULO, _AUDITOR_SANDBOX)
    assert spec is not None
    assert spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    # `@dataclass` resuelve las anotaciones contra `sys.modules[cls.__module__]`, así que
    # el módulo tiene que estar registrado antes de ejecutarlo.
    sys.modules[_NOMBRE_MODULO] = modulo
    spec.loader.exec_module(modulo)
    return modulo


def test_should_existir_la_copia_del_sandbox() -> None:
    assert _AUDITOR_SANDBOX.is_file(), f"no está {_AUDITOR_SANDBOX}"


@pytest.mark.parametrize("codigo", _CODIGOS_CRITICOS)
def test_should_rechazar_el_sandbox_todo_lo_que_la_api_llama_critico(codigo: str) -> None:
    from server.app.modules.redaccion.services.script_auditor import ScriptSecurityAuditor

    api = ScriptSecurityAuditor().audit(codigo)
    assert api.risk_level == "CRITICAL", f"el caso ya no es crítico para la API: {codigo!r}"

    sandbox = _cargar_auditor_del_sandbox().ScriptSecurityAuditor().audit(codigo)
    assert not sandbox.approved, (
        f"el sandbox aprobaría lo que la API considera crítico: {codigo!r}"
    )


def test_should_seguir_aprobando_el_sandbox_un_script_legitimo() -> None:
    """Endurecer las dos copias no puede convertirlas en un «no» permanente."""
    codigo = (
        "import pandas as pd\n"
        "df = pd.read_excel(file_path)\n"
        "result = {'tables': [], 'metrics': [{'name': 'filas', 'value': len(df)}]}\n"
    )

    sandbox = _cargar_auditor_del_sandbox().ScriptSecurityAuditor().audit(codigo)
    assert sandbox.approved, sandbox.findings
