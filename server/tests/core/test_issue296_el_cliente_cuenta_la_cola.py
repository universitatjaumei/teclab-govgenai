"""#296 — el cliente del sandbox cuenta la espera en cola y no convierte un turno en un 500.

El sandbox ejecuta de una en una (PR #294) y, si el turno no llega a tiempo, contesta 503
`SANDBOX_BUSY`. El cliente lo dice como aviso, como hace con el tiempo agotado del guion, y un
`ReadTimeout` sale como `SandboxUnavailableError`, que los llamantes ya saben tratar, en vez de
reventar como excepción de httpx.
"""
from __future__ import annotations

import httpx
import pytest
import respx

from server.app.core.sandbox_client import HttpSandboxClient, SandboxUnavailableError

_BASE = "http://script-sandbox:5000"


def _cliente() -> HttpSandboxClient:
    return HttpSandboxClient(base_url=_BASE, connect_timeout=5.0, max_retries=1, default_timeout=30)


@pytest.mark.asyncio
@respx.mock
async def test_should_say_the_sandbox_is_busy():
    respx.post(f"{_BASE}/execute-extraction").mock(
        return_value=httpx.Response(503, json={"code": "SANDBOX_BUSY"})
    )

    resultado = await _cliente().execute_extraction_script(
        code="result = {}", file_path=None, raw_text=None, options={}
    )

    assert [a.code for a in resultado.warnings] == ["SANDBOX_BUSY"]


@pytest.mark.asyncio
@respx.mock
async def test_should_turn_a_read_timeout_into_unavailable():
    respx.post(f"{_BASE}/execute-extraction").mock(side_effect=httpx.ReadTimeout("lento"))

    with pytest.raises(SandboxUnavailableError):
        await _cliente().execute_extraction_script(
            code="result = {}", file_path=None, raw_text=None, options={}
        )
