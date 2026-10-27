"""#296 — una ejecución que espera turno no espera para siempre.

Desde la PR #294 el sandbox ejecuta de una en una. El cliente esperaba `timeout + 30` segundos,
así que una petición encolada detrás de un guion largo recibía `ReadTimeout` —un 500 en el
servidor— y el sandbox la ejecutaba igualmente después, para nadie. Ahora la espera en cola tiene
un máximo: pasado, el sandbox contesta 503 `SANDBOX_BUSY` sin ejecutar nada.
"""
from __future__ import annotations

from sandbox import main


def _payload() -> dict:
    return {"code": "result = {}", "file_path": "", "raw_text": "", "options": {}, "timeout_seconds": 5}


def test_should_answer_busy_when_the_turn_does_not_come(client, monkeypatch):
    monkeypatch.setattr(main, "ESPERA_EN_COLA_SEGUNDOS", 0.2)
    assert main._UNA_A_LA_VEZ.acquire(timeout=1)
    try:
        resp = client.post("/execute-extraction", json=_payload())
    finally:
        main._UNA_A_LA_VEZ.release()

    assert resp.status_code == 503
    assert resp.json()["code"] == "SANDBOX_BUSY"


def test_should_run_when_the_turn_comes(client):
    resp = client.post("/execute-extraction", json=_payload())

    assert resp.status_code == 200
