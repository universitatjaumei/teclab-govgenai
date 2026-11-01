"""#339 — `show_citation_corrections` se puede devolver a «heredar» desde el panel.

El formulario ofrece tres estados y manda `null` para heredar. El PATCH hacía
`model_dump(exclude_none=True)`, así que ese `null` se descartaba y el chatbot se quedaba con el
último sí o no: el desplegable decía «Heredar» y guardar no cambiaba nada. Es el mismo defecto que
FIX.3 arregló en la ventana de vigencia.
"""
from __future__ import annotations

import server.tests.api.test_chatbot_availability as disponibilidad


def _cliente(**campos):
    from fastapi.testclient import TestClient

    andamio = disponibilidad.TestPoderQuitarLaFecha()
    app, chatbot = andamio._app(andamio._chatbot_completo(**campos))
    return TestClient(app), chatbot


def test_null_devuelve_el_chatbot_a_heredar() -> None:
    cliente, chatbot = _cliente(show_citation_corrections=True)

    respuesta = cliente.patch(
        f"/api/v1/hub/chatbots/{chatbot.id}", json={"show_citation_corrections": None}
    )

    assert respuesta.status_code == 200, respuesta.text
    assert chatbot.show_citation_corrections is None


def test_lo_que_no_se_envia_no_se_toca() -> None:
    cliente, chatbot = _cliente(show_citation_corrections=True)

    respuesta = cliente.patch(f"/api/v1/hub/chatbots/{chatbot.id}", json={"name": "Otro"})

    assert respuesta.status_code == 200, respuesta.text
    assert chatbot.show_citation_corrections is True
