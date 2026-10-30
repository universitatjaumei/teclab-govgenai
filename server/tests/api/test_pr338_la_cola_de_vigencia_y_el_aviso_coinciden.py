"""Revisión de la PR #338 — la cola de vigencia del panel y el aviso del asistente coinciden.

`vigencia_pendiente` traduce a SQL el criterio de `vigencia_no_validada` para no traerse el corpus
a memoria, y su docstring avisa de lo que pasa si divergen: la pantalla dice N y el asistente
advierte por M. #337 dejó de advertir de los documentos sin `estat_vigencia` —subidos, rastreados:
no son normas— y la copia en SQL seguía metiéndolos en la cola, de la que además no podían salir,
porque validar exige `estat_vigencia = 'vigent'`.

Los tests de la cola usan una sesión simulada, así que ninguno ejecutaba la consulta. Éste sí.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from server.app.modules.agents_hub.services import ingesta_del_panel
from server.app.modules.agents_hub.services.retrieval.vigencia import vigencia_no_validada
from server.tests.api.test_vas2_vigencia import _chatbot, _documento, _organizacion

VALIDADA = datetime(2026, 8, 1, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_la_cola_es_lo_que_avisa_mas_lo_que_no_rige(db_session) -> None:
    cb = await _chatbot(db_session, await _organizacion(db_session))
    casos = {
        "norma sin validar": dict(estat_vigencia="vigent", vigencia_validada_el=None),
        "norma validada": dict(estat_vigencia="vigent", vigencia_validada_el=VALIDADA),
        "vigent? sin validar": dict(estat_vigencia="vigent?", vigencia_validada_el=None),
        "subido sin estado": dict(estat_vigencia=None, vigencia_validada_el=None, source_kind="upload"),
        "derogada validada": dict(estat_vigencia="derogat", vigencia_validada_el=VALIDADA),
    }
    for titulo, campos in casos.items():
        await _documento(db_session, cb, title=titulo, **campos)

    _total, pendientes = await ingesta_del_panel.vigencia_pendiente(db_session, cb)

    en_cola = {d.title for d in pendientes}
    assert en_cola == {"norma sin validar", "vigent? sin validar", "derogada validada"}
    # Y para lo que rige, la cola y el aviso dicen lo mismo, documento a documento.
    for titulo, campos in casos.items():
        if campos["estat_vigencia"] in ("vigent", "vigent?", None):
            avisa = vigencia_no_validada(campos["estat_vigencia"], campos["vigencia_validada_el"])
            assert (titulo in en_cola) is avisa, titulo
