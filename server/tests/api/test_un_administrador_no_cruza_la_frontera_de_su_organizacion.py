"""Dos campos con los que un administrador alcanzaba fuera de su organización.

* **`partner_id` de la organización.** Decide quién la ve: `_orgs_del_admin` resuelve el claim
  de un administrador por `partner_id`. Al crear ya no se acepta del cuerpo (SEC.9.6); al
  editar sí, así que un administrador podía entregar su organización a otro partner. Ahora sólo
  lo cambia un superadministrador.
* **`llm_config_id` del chatbot.** Sólo se comprobaba que existiera. Un chatbot usa una
  configuración de plataforma o de su propia organización; una de otra organización es 404,
  igual que si no existiera, porque usarla es gastar su credencial.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from server.app.core.auth.models import UserInfo

ORG_A = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
ORG_B = uuid.UUID("00000000-0000-0000-0000-0000000000b2")


def _admin() -> UserInfo:
    return UserInfo(user_id="admin-a", email="a@uji.es", role="admin", organizacion_ids=(str(ORG_A),))


def _superadmin() -> UserInfo:
    return UserInfo(user_id="root", email="root@uji.es", role="superadmin")


# ───────────────────────── partner_id ─────────────────────────


def _sesion_con_organizacion():
    organizacion = MagicMock()
    organizacion.id = ORG_A
    session = MagicMock()
    session.get = AsyncMock(return_value=organizacion)
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return session, organizacion


class TestElPartnerLoCambiaElSuperadministrador:

    async def test_should_refuse_an_admin_changing_the_partner(self):
        from server.app.routers.hub_organizaciones_router import OrganizacionUpdate, update_organizacion

        session, organizacion = _sesion_con_organizacion()
        organizacion.partner_id = "partner-a"

        with pytest.raises(HTTPException) as fallo:
            await update_organizacion(ORG_A, OrganizacionUpdate(partner_id="partner-b"), _admin(), session)

        assert fallo.value.status_code == 403
        assert organizacion.partner_id == "partner-a"
        session.commit.assert_not_awaited()

    async def test_should_let_an_admin_resend_the_same_partner_while_renaming(self):
        """El formulario del panel envía el partner siempre: renombrar no puede costar un 403."""
        from server.app.routers.hub_organizaciones_router import OrganizacionUpdate, update_organizacion

        session, organizacion = _sesion_con_organizacion()
        organizacion.partner_id = "partner-a"

        try:
            await update_organizacion(
                ORG_A, OrganizacionUpdate(name="Nuevo", partner_id="partner-a"), _admin(), session
            )
        except HTTPException as fallo:
            pytest.fail(f"renombrar con el mismo partner dio {fallo.status_code}")
        except Exception:  # la respuesta se construye sobre un doble; lo que se mira es el cambio
            pass

        assert organizacion.name == "Nuevo"

    async def test_should_let_a_superadmin_change_it(self):
        from server.app.routers.hub_organizaciones_router import OrganizacionUpdate, update_organizacion

        session, organizacion = _sesion_con_organizacion()

        try:
            await update_organizacion(ORG_A, OrganizacionUpdate(partner_id="partner-b"), _superadmin(), session)
        except Exception:  # la respuesta se construye sobre un doble; lo que se mira es el cambio
            pass

        assert organizacion.partner_id == "partner-b"


# ───────────────────────── llm_config_id ─────────────────────────


def _sesion_con(chatbot, config):
    from server.app.modules.agents_hub.database.config_models import HubChatbot, HubLLMConfig

    async def _get(modelo, _id):
        return {HubChatbot: chatbot, HubLLMConfig: config}.get(modelo)

    session = MagicMock()
    session.get = AsyncMock(side_effect=_get)
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return session


class TestElChatbotUsaUnaConfiguracionPropiaODePlataforma:

    async def test_should_hide_another_organizations_config(self):
        from server.app.routers.hub_chatbots_router import ChatbotUpdate, update_chatbot

        chatbot = SimpleNamespace(id=uuid.uuid4(), organizacion_id=ORG_A, retrieval_mode="RAG")
        ajena = SimpleNamespace(id=uuid.uuid4(), organizacion_id=ORG_B)
        session = _sesion_con(chatbot, ajena)

        with pytest.raises(HTTPException) as fallo:
            await update_chatbot(chatbot.id, ChatbotUpdate(llm_config_id=ajena.id), _admin(), session)

        assert fallo.value.status_code == 404
        session.commit.assert_not_awaited()

    @pytest.mark.parametrize("organizacion", [None, ORG_A], ids=["de-plataforma", "propia"])
    async def test_should_accept_a_platform_or_own_config(self, organizacion):
        from server.app.routers.hub_chatbots_router import _exigir_configuracion_utilizable

        config = SimpleNamespace(id=uuid.uuid4(), organizacion_id=organizacion)
        session = _sesion_con(None, config)

        await _exigir_configuracion_utilizable(session, config.id, ORG_A)
