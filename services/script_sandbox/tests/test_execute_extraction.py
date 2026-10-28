"""Tests del endpoint POST /execute-extraction."""
from __future__ import annotations


def _payload(code: str, **overrides) -> dict:
    base = {
        "code": code,
        "file_path": "",
        "raw_text": "",
        "options": {},
        "timeout_seconds": 30,
    }
    base.update(overrides)
    return base


def test_execute_extraction_runs_pandas_script(client) -> None:
    code = (
        "import pandas\n"
        "df = pandas.DataFrame({'a': [1, 2, 3]})\n"
        "result = {'metrics': [{'name': 'sum_a', 'value': int(df['a'].sum())}]}\n"
    )
    resp = client.post("/execute-extraction", json=_payload(code))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["result"]["metrics"] == [{"name": "sum_a", "value": 6}]
    assert body["stdout_truncated"] is False


def test_execute_extraction_returns_422_for_eval_call(client) -> None:
    code = "result = eval('1 + 1')\n"
    resp = client.post("/execute-extraction", json=_payload(code))
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == "SCRIPT_AUDIT_FAILED"
    assert isinstance(body["findings"], list)
    assert any("eval" in f for f in body["findings"])


def test_execute_extraction_returns_504_on_timeout(client) -> None:
    code = "while True:\n    pass\n"
    resp = client.post("/execute-extraction", json=_payload(code, timeout_seconds=1))
    assert resp.status_code == 504
    body = resp.json()
    assert body["code"] == "SCRIPT_TIMEOUT"


def test_execute_extraction_returns_500_with_stderr_truncated_on_runtime_error(client) -> None:
    code = "raise RuntimeError('boom and ' + 'x' * 2000)\n"
    resp = client.post("/execute-extraction", json=_payload(code))
    assert resp.status_code == 500
    body = resp.json()
    assert body["code"] == "SCRIPT_EXECUTION_ERROR"
    assert "stderr_truncated" in body
    # El stderr debe estar capado a 500 caracteres.
    assert len(body["stderr_truncated"]) <= 500


def test_execute_extraction_empty_code_returns_422(client) -> None:
    resp = client.post("/execute-extraction", json=_payload("   \n\t"))
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == "SCRIPT_EMPTY"


def test_execute_extraction_keeps_the_end_of_stderr(client) -> None:
    """Revisión de la PR #313: lo que imprime el guion va a stderr (#282), así que el principio
    son sus `print` y el traceback está al final. Se guarda el final."""
    code = "for i in range(200):\n    print('depurando', i)\nraise KeyError('falta')\n"
    resp = client.post("/execute-extraction", json=_payload(code))
    assert resp.status_code == 500
    assert "KeyError: 'falta'" in resp.json()["stderr_truncated"]
