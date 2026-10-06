"""#214 — un token personal sólo entra donde el endpoint declara qué alcance acepta.

Antes, `require_scopes` sólo filtraba donde se ponía, y `require_role` mira el rol del dueño y no
los alcances del token. Un token de superadministrador emitido **sólo con `actividad:write`** —el
que se da a una herramienta para anotar usos— pasaba por `_require_superadmin` y podía conceder
módulos o dar de alta personas: todo lo que su dueño puede con sesión. Medido el 2026-10-06: 197
rutas con usuario no declaraban nada, y todas aceptaban cualquier token.

**El valor por defecto es ahora el seguro.** `get_current_user`, al validar un token, mira la ruta
que atiende la petición: si no declara alcance —`require_scopes`, `require_pat_scopes`, la
variante del widget— o la declara de persona —`require_sesion_humana`—, el token no entra. Un
endpoint nuevo que no diga nada es de sesión, no de máquina.

Los endpoints que usa el servidor MCP declaran ahora el alcance que sus herramientas ya
documentaban (`chatbots:read`, `chatbots:write`, `redaccion:templates:*`): funcionaban por el
agujero que esto cierra.
"""
from __future__ import annotations

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient

from server.app.api import deps
from server.app.core.auth.models import UserInfo
from server.app.core.auth.pat.service import PatPrincipal, PatService

SUPERADMIN = UserInfo(user_id="dueno", email="admin@uji.es", role="superadmin")


@pytest.fixture
def con_token(monkeypatch):
    """Un token válido de superadministrador con los alcances que se pidan.

    Se sustituye sólo la **verificación** del token —que mira la base—, no la autorización: lo que
    se prueba es lo que `get_current_user` hace después de verificarlo.
    """
    alcances: list[str] = []

    async def _verifica(self, token):
        return PatPrincipal(user_info=SUPERADMIN, scopes=list(alcances))

    monkeypatch.setattr(PatService, "verify", _verifica)
    return alcances


def _app() -> TestClient:
    app = FastAPI()
    r = APIRouter()

    @r.get("/sin-declarar")
    def sin_declarar(user: UserInfo = Depends(deps.require_superadmin)):
        return {"ok": True}

    @r.get("/con-alcance", dependencies=[Depends(deps.require_scopes("actividad:write"))])
    def con_alcance(user: UserInfo = Depends(deps.get_current_user)):
        return {"ok": True}

    @r.get("/de-persona")
    def de_persona(user: UserInfo = Depends(deps.require_sesion_humana())):
        return {"ok": True}

    app.include_router(r, prefix="/api/v1")

    async def _sin_bd():
        yield None

    app.dependency_overrides[deps.get_session] = _sin_bd
    return TestClient(app)


_TOKEN = {"Authorization": "Bearer pat_abc_secreto"}


class TestElValorPorDefecto:

    def test_un_token_no_entra_donde_no_se_declara_alcance(self, con_token):
        con_token.append("actividad:write")
        r = _app().get("/api/v1/sin-declarar", headers=_TOKEN)
        assert r.status_code == 403, r.text
        assert r.json()["detail"]["code"] == "PAT_NO_PERMITIDO"

    def test_aunque_su_dueno_sea_superadministrador(self, con_token):
        """El caso de la issue: el rol del dueño no abre lo que el token no declara."""
        con_token.extend(["actividad:write", "chatbots:write"])
        assert _app().get("/api/v1/sin-declarar", headers=_TOKEN).status_code == 403

    def test_donde_se_declara_entra_con_el_alcance(self, con_token):
        con_token.append("actividad:write")
        assert _app().get("/api/v1/con-alcance", headers=_TOKEN).status_code == 200

    def test_y_sin_el_alcance_no(self, con_token):
        con_token.append("anonimizacion:use")
        r = _app().get("/api/v1/con-alcance", headers=_TOKEN)
        assert r.status_code == 403
        assert r.json()["detail"]["code"] == "PAT_SCOPE_MISSING"

    def test_lo_de_persona_sigue_sin_admitir_tokens(self, con_token):
        con_token.append("actividad:write")
        assert _app().get("/api/v1/de-persona", headers=_TOKEN).status_code == 403


class TestElCasoDeLaIssue:
    """Con los routers reales: conceder módulos con un token que sólo anota usos."""

    def test_un_token_de_actividad_no_concede_modulos(self, con_token):
        from server.app.routers.hub_modulos_router import router

        con_token.append("actividad:write")
        app = FastAPI()
        app.include_router(router, prefix="/api/v1")

        async def _sin_bd():
            yield None

        app.dependency_overrides[deps.get_session] = _sin_bd
        rutas = [
            (m, r.path)
            for r in router.routes
            for m in getattr(r, "methods", ())
            if m in {"POST", "PUT", "DELETE"}
        ]
        assert rutas, "hub_modulos_router no tiene rutas que escriban: el test no mira nada"
        cliente = TestClient(app, raise_server_exceptions=False)
        for metodo, ruta in rutas:
            url = "/api/v1" + ruta.replace("{", "").replace("}", "")
            r = cliente.request(metodo, url, headers=_TOKEN, json={})
            assert r.status_code == 403, f"{metodo} {ruta} → {r.status_code} {r.text[:200]}"


#: Lo que usa el servidor MCP, con el alcance que documenta cada herramienta. Si una ruta deja de
#: declararlo, la herramienta deja de funcionar con su token, y es mejor saberlo aquí.
LO_QUE_USA_EL_MCP = {
    ("GET", "/hub/chatbots"): "chatbots:read",
    ("GET", "/hub/chatbots/{chatbot_id}/corpus-stats"): "chatbots:read",
    ("GET", "/hub/chatbots/{chatbot_id}/children"): "chatbots:read",
    ("GET", "/hub/prompt-templates/"): "chatbots:read",
    ("POST", "/hub/chatbots"): "chatbots:write",
    ("PATCH", "/hub/chatbots/{chatbot_id}"): "chatbots:write",
    ("POST", "/hub/chatbots/{chatbot_id}/children"): "chatbots:write",
    ("DELETE", "/hub/chatbots/{chatbot_id}/children/{child_chatbot_id}"): "chatbots:write",
    ("PATCH", "/hub/prompt-templates/{template_id}"): "chatbots:write",
    ("GET", "/hub/redaccion/templates"): "redaccion:templates:read",
    ("POST", "/redaccion/llm-drafts/validate"): "redaccion:templates:read",
    ("POST", "/redaccion/llm-drafts/approve-as-template"): "redaccion:templates:write",
    ("GET", "/actividad/categorias"): "actividad:write",
}


def _rutas():
    from fastapi.routing import APIRoute

    from server.app.main import app

    def todas(rs):
        for r in rs:
            if isinstance(r, APIRoute):
                yield r
            elif hasattr(r, "original_router"):
                yield from todas(r.original_router.routes)
            elif hasattr(r, "routes"):
                yield from todas(r.routes)

    return list(todas(app.routes))


def test_lo_que_usa_el_mcp_declara_su_alcance():
    declaradas: dict[tuple[str, str], set[str]] = {}
    for ruta in _rutas():
        for metodo in ruta.methods:
            declaradas[(metodo, ruta.path)] = deps.alcances_de_la_ruta(ruta)
    faltan = {
        clave: alcance
        for clave, alcance in LO_QUE_USA_EL_MCP.items()
        if alcance not in declaradas.get(clave, set())
    }
    assert not faltan, f"rutas del MCP sin su alcance declarado: {faltan}"
