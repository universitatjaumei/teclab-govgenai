"""#236 — un agente de código registra con su token los cuadernos que escribe.

Decisión del usuario (2026-10-06). Desde #214 un token sólo entra donde el endpoint declara su
alcance, y `POST /api/v1/funciones/externas` no declaraba ninguno: registrar un cuaderno exigía la
sesión de una persona, y el caso para el que existe AUT.3 —el agente que acaba de escribir el
cuaderno lo registra— se quedaba fuera.

- **Alcance nuevo, `funciones:register`.** Aparte de `funciones:execute`: ejecutar lo que hay y
  añadir al catálogo son dos capacidades, y un token que sólo ejecuta no tiene por qué registrar.
- **Lo emite un administrador.** #236 lo abría también al módulo `automatizacion`, como `agentes`
  da `agentes:indice`, pero ningún camino lo emitía: `/auth/pats` no pasa módulos y un `user` no
  tiene techo de rol. Se retiró en #239 (decisión del usuario, 2026-10-09) en vez de abrir otro
  endpoint de emisión: no hay hoy unidad que escriba cuadernos con su propio agente. Si la hay, se
  hace como en `agentes`, con su endpoint, y este test es el que hay que cambiar.
- **Leer el catálogo** —para encontrar lo registrado y no duplicarlo, o el `funcion_id` que se
  quiere ejecutar— lo admite cualquiera de los dos alcances.
"""
from __future__ import annotations

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient

from server.app.api import deps
from server.app.core.auth.models import UserInfo
from server.app.core.auth.pat import scopes as alcances
from server.app.core.auth.pat.service import PatPrincipal, PatService
from server.tests.api.test_issue214_un_token_solo_donde_se_declara import _rutas

REGISTRAR = "funciones:register"
EJECUTAR = "funciones:execute"


def test_el_alcance_esta_en_el_catalogo():
    assert alcances.FUNCIONES_REGISTER == REGISTRAR
    assert REGISTRAR in alcances.ALL_SCOPES


def test_lo_emite_un_administrador_y_no_el_modulo_automatizacion():
    assert REGISTRAR in alcances.allowed_scopes_for("admin")
    assert REGISTRAR not in alcances.allowed_scopes_for("user", ["automatizacion"])
    assert REGISTRAR not in alcances.allowed_scopes_for("user", ["informes"])


def _declarados(metodo: str, ruta: str) -> set[str]:
    for r in _rutas():
        if r.path == ruta and metodo in r.methods:
            return deps.alcances_de_la_ruta(r)
    raise AssertionError(f"no existe {metodo} {ruta}")


def test_registrar_un_cuaderno_admite_el_token_con_su_alcance():
    assert REGISTRAR in _declarados("POST", "/funciones/externas")


@pytest.mark.parametrize("ruta", ["/funciones", "/funciones/{funcion_id}"])
def test_leer_el_catalogo_lo_admite_cualquiera_de_los_dos(ruta):
    assert {REGISTRAR, EJECUTAR} <= _declarados("GET", ruta)


SUPERADMIN = UserInfo(user_id="dueno", email="admin@uji.es", role="superadmin")


@pytest.fixture
def con_token(monkeypatch):
    lista: list[str] = []

    async def _verifica(self, token):
        return PatPrincipal(user_info=SUPERADMIN, scopes=list(lista))

    monkeypatch.setattr(PatService, "verify", _verifica)
    return lista


def _app() -> TestClient:
    app = FastAPI()
    r = APIRouter()

    @r.get("/uno-de-dos")
    def uno_de_dos(user: UserInfo = Depends(deps.require_alguno_de(REGISTRAR, EJECUTAR))):
        return {"ok": True}

    app.include_router(r, prefix="/api/v1")

    async def _sin_bd():
        yield None

    app.dependency_overrides[deps.get_session] = _sin_bd
    return TestClient(app)


_TOKEN = {"Authorization": "Bearer pat_abc_secreto"}


class TestAlgunoDe:

    @pytest.mark.parametrize("alcance", [REGISTRAR, EJECUTAR])
    def test_basta_con_uno(self, con_token, alcance):
        con_token.append(alcance)
        assert _app().get("/api/v1/uno-de-dos", headers=_TOKEN).status_code == 200

    def test_sin_ninguno_no(self, con_token):
        con_token.append("actividad:write")
        r = _app().get("/api/v1/uno-de-dos", headers=_TOKEN)
        assert r.status_code == 403
        assert r.json()["detail"]["code"] == "PAT_SCOPE_MISSING"

    def test_una_sesion_no_se_filtra_por_alcance(self, monkeypatch):
        monkeypatch.setattr(deps, "decode_token", lambda t: SUPERADMIN)
        r = _app().get("/api/v1/uno-de-dos", headers={"Authorization": "Bearer jwt.de.sesion"})
        assert r.status_code == 200
