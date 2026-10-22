"""Una ejecución no puede ver, tocar ni esperar a la de otra organización.

El auditor por lista negra no es una frontera: se saltaba con `sys.modules['builtins'].eval`,
con `sys.modules['os']` o con `io.open` y una ruta concatenada, porque el envoltorio ya había
importado `sys` e `io` en nombre del guion. Y como los endpoints son `def` síncronos, corrían
**a la vez** en el threadpool con el mismo uid y el mismo `/tmp/sandbox`: un guion leía los
ficheros de entrada de otra organización mientras se ejecutaba, o dejaba un proceso esperando
a la siguiente.

Se fija por capas, de la que de verdad garantiza a la que sólo pone difícil:

* **una ejecución a la vez**, así que mientras corre un guion no existen los ficheros de otro;
* **el grupo de procesos del guion muere al acabar**, así que no queda nadie esperando;
* el envoltorio ya no deja `sys` a mano, `io` sólo trae `BytesIO` y `StringIO`, y el auditor
  rechaza los caminos reproducidos;
* `timeout_seconds` tiene techo.

El servicio normaliza el resultado a `tables`, `metrics` y `free_text` y descarta lo demás, así
que los guiones de estos tests devuelven lo que miden dentro de `metrics`.
"""
from __future__ import annotations

import os
import sys
import threading
import time

import pytest


def _payload(code: str, **overrides) -> dict:
    base = {"code": code, "file_path": "", "raw_text": "", "options": {}, "timeout_seconds": 30}
    base.update(overrides)
    return base


def _metrica(resp, nombre):
    return next(m["value"] for m in resp.json()["result"]["metrics"] if m["name"] == nombre)


def _devuelve(nombre: str, expresion: str) -> str:
    return f"result = {{'metrics': [{{'name': {nombre!r}, 'value': {expresion}}}]}}\n"


@pytest.fixture
def sin_auditor(monkeypatch):
    """Para probar las capas de debajo hay que suponer que el auditor ya se saltó."""
    from sandbox import main
    from sandbox.auditor import AuditResult

    monkeypatch.setattr(main._AUDITOR, "audit", lambda code: AuditResult(approved=True, risk_level="low"))


# ───────────────────────── El auditor ─────────────────────────


@pytest.mark.parametrize(
    "codigo",
    [
        "sys.modules['builtins'].eval('1+1')\n",
        "os = sys.modules['os']\nresult = {}\n",
        "io.open('/et' + 'c/passwd').read()\n",
        "import io\nio.open('x')\n",
        "import builtins\n",
        "x = __builtins__\n",
    ],
    ids=["builtins-por-sys", "os-por-sys", "io-open", "io-open-importado", "builtins", "dunder"],
)
def test_should_refuse_the_reproduced_bypasses(client, codigo):
    resp = client.post("/execute-extraction", json=_payload(codigo))

    assert resp.status_code == 422, resp.text
    assert resp.json()["code"] == "SCRIPT_AUDIT_FAILED"


# ───────────────────────── El envoltorio ─────────────────────────


def test_should_not_hand_sys_to_the_script(client, sin_auditor):
    resp = client.post("/execute-extraction", json=_payload(_devuelve("v", "str(sys)")))

    assert resp.status_code != 200, resp.text


def test_should_keep_bytesio_for_the_scripts_that_use_it(client):
    codigo = "buf = io.BytesIO(b'abc')\n" + _devuelve("n", "len(buf.getvalue())")

    resp = client.post("/execute-extraction", json=_payload(codigo))

    assert resp.status_code == 200, resp.text
    assert _metrica(resp, "n") == 3


def test_should_not_expose_open_through_the_provided_io(client, sin_auditor):
    resp = client.post("/execute-extraction", json=_payload(_devuelve("f", "str(io.open)")))

    assert resp.status_code != 200, resp.text


# ───────────────────────── Una a la vez ─────────────────────────


def test_should_never_run_two_executions_at_once(client, sin_auditor):
    """Dos peticiones simultáneas: cada guion sólo ve su propio directorio temporal."""
    from sandbox.main import _TMP_DIR

    codigo = (
        "import os, time\n"
        f"vistos = [n for n in os.listdir({str(_TMP_DIR)!r}) if not n.endswith('.py')]\n"
        "time.sleep(1.5)\n" + _devuelve("vistos", "len(vistos)")
    )
    respuestas = []

    def _pedir():
        respuestas.append(client.post("/execute-extraction", json=_payload(codigo)))

    hilos = [threading.Thread(target=_pedir) for _ in range(2)]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join()

    assert [r.status_code for r in respuestas] == [200, 200], [r.text for r in respuestas]
    for respuesta in respuestas:
        assert _metrica(respuesta, "vistos") == 1, respuesta.json()


@pytest.mark.skipif(not hasattr(os, "killpg"), reason="grupos de procesos: sólo POSIX")
def test_should_kill_what_the_script_left_running(client, sin_auditor):
    codigo = (
        "import subprocess, sys\n"
        "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        + _devuelve("pid", "p.pid")
    )

    resp = client.post("/execute-extraction", json=_payload(codigo))

    assert resp.status_code == 200, resp.text
    pid = _metrica(resp, "pid")
    time.sleep(0.5)
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_should_cap_the_timeout(client):
    resp = client.post("/execute-extraction", json=_payload("result = {}\n", timeout_seconds=100_000))

    assert resp.status_code == 422, resp.text


def test_the_python_running_the_tests_exists():
    """Sanidad del medidor: el test de procesos usa `sys.executable`."""
    assert os.path.exists(sys.executable)
