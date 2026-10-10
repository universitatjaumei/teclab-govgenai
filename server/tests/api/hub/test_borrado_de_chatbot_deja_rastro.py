"""Borrar un chatbot deja rastro de cuánto corpus se llevó por delante.

Visto al retirar el import muerto de `CorpusRetirado`: la purga **cuenta** los documentos y
fragmentos que retira, lo devuelve —su docstring dice literalmente «para poder decirlo en voz
alta»— y el router lo descartaba. O sea que borrar un chatbot destruía corpus sin dejar registro
de cuánto.

Es un hueco de auditoría, no de funcionamiento: el borrado era correcto. Pero un borrado
irreversible del que no queda constancia impide responder «cuántos documentos se perdieron» tres
meses después, que es justo cuando se pregunta.
"""
from __future__ import annotations

import logging
import uuid

import pytest

from server.app.core.auth.models import UserInfo
from server.app.modules.agents_hub.services.corpus_purge import CorpusRetirado

pytestmark = pytest.mark.asyncio


class _SesionQueNoHaceNada:
    """Lo justo para que el endpoint llegue al final: no se prueba la base, se prueba el rastro."""

    async def execute(self, *_a, **_kw):
        return None

    async def commit(self):
        return None


class _AlmacenQueNoHaceNada:
    """#253 — borrar el chatbot borra después sus fuentes de ingesta; aquí no hay ninguna."""

    async def delete_prefix(self, _prefijo):
        return None


async def test_el_borrado_registra_cuanto_corpus_se_llevo(monkeypatch, caplog):
    import server.app.routers.hub_chatbots_router as router_mod

    chatbot_id = uuid.UUID("11111111-1111-1111-1111-111111111111")

    async def _sin_404(_session, _chatbot_id, _user):
        return object()

    async def _purga(_session, _chatbot_id):
        return CorpusRetirado(documentos=7, fragmentos=413)

    monkeypatch.setattr(router_mod, "_get_chatbot_or_404", _sin_404)
    monkeypatch.setattr(router_mod, "purgar_corpus_del_chatbot", _purga)

    with caplog.at_level(logging.INFO, logger=router_mod.__name__):
        await router_mod.delete_chatbot(
            chatbot_id=chatbot_id,
            user=UserInfo(user_id="1", email="admin@example.local", role="superadmin"),
            session=_SesionQueNoHaceNada(),
            storage=_AlmacenQueNoHaceNada(),
        )

    registro = "\n".join(caplog.messages)
    assert "7" in registro, f"no consta cuántos documentos se retiraron: {registro!r}"
    assert "413" in registro, f"no consta cuántos fragmentos se retiraron: {registro!r}"
    assert str(chatbot_id) in registro, f"no consta de qué chatbot: {registro!r}"


async def test_el_rastro_dice_quien_lo_borro(monkeypatch, caplog):
    """Sin autoría, el registro sirve para contar pero no para rendir cuentas."""
    import server.app.routers.hub_chatbots_router as router_mod

    async def _sin_404(_session, _chatbot_id, _user):
        return object()

    async def _purga(_session, _chatbot_id):
        return CorpusRetirado(documentos=1, fragmentos=2)

    monkeypatch.setattr(router_mod, "_get_chatbot_or_404", _sin_404)
    monkeypatch.setattr(router_mod, "purgar_corpus_del_chatbot", _purga)

    with caplog.at_level(logging.INFO, logger=router_mod.__name__):
        await router_mod.delete_chatbot(
            chatbot_id=uuid.uuid4(),
            user=UserInfo(user_id="42", email="gerencia@uji.es", role="admin"),
            session=_SesionQueNoHaceNada(),
            storage=_AlmacenQueNoHaceNada(),
        )

    assert "gerencia@uji.es" in "\n".join(caplog.messages)


async def test_un_borrado_sin_corpus_tambien_deja_rastro(monkeypatch, caplog):
    """Cero es un dato: distingue «no había nada» de «no se registró»."""
    import server.app.routers.hub_chatbots_router as router_mod

    async def _sin_404(_session, _chatbot_id, _user):
        return object()

    async def _purga(_session, _chatbot_id):
        return CorpusRetirado(documentos=0, fragmentos=0)

    monkeypatch.setattr(router_mod, "_get_chatbot_or_404", _sin_404)
    monkeypatch.setattr(router_mod, "purgar_corpus_del_chatbot", _purga)

    with caplog.at_level(logging.INFO, logger=router_mod.__name__):
        await router_mod.delete_chatbot(
            chatbot_id=uuid.uuid4(),
            user=UserInfo(user_id="1", email="admin@example.local", role="superadmin"),
            session=_SesionQueNoHaceNada(),
            storage=_AlmacenQueNoHaceNada(),
        )

    assert caplog.messages, "un borrado sin corpus no deja constancia de haber ocurrido"
