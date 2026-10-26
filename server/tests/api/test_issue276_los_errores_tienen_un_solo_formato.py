"""#276 — todo error de la API sale como `{"detail": {"code", "message", …}}`.

Había 210 errores con `detail` de texto y 85 con objeto, unos con `message`, otros con `reason`
y otros sin ninguno, y tres sitios que devolvían al cliente el mensaje de una excepción genérica.
Decisión del usuario del 2026-10-25: un formato único en el cable.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

from server.app.core.errores import (
    MENSAJE_DE_ERROR_INTERNO,
    instalar_errores,
    normalizar_detalle,
)

APP = Path(__file__).resolve().parents[2] / "app"


class Cuerpo(BaseModel):
    n: int


def _app() -> FastAPI:
    app = FastAPI()
    instalar_errores(app)

    @app.get("/texto")
    async def texto():
        raise HTTPException(status_code=404, detail="Función no encontrada")

    @app.get("/con-reason")
    async def con_reason():
        raise HTTPException(status_code=401, detail={"code": "SAML_X", "reason": "no vale"})

    @app.get("/con-extras")
    async def con_extras():
        raise HTTPException(status_code=422, detail={"missing_slots": ["a"], "message": "faltan"})

    @app.get("/sin-mensaje")
    async def sin_mensaje():
        raise HTTPException(status_code=409, detail={"pending_block_ids": ["b1"]})

    @app.get("/con-cabeceras")
    async def con_cabeceras():
        raise HTTPException(status_code=429, detail="despacio", headers={"Retry-After": "7"})

    @app.get("/revienta")
    async def revienta():
        raise RuntimeError("SELECT * FROM secreto WHERE ruta='/app/x'")

    @app.post("/valida")
    async def valida(cuerpo: Cuerpo):
        return cuerpo

    return app


@pytest.fixture(scope="module")
def cliente() -> TestClient:
    return TestClient(_app(), raise_server_exceptions=False)


def test_un_texto_pasa_a_message_con_el_codigo_del_estado(cliente: TestClient) -> None:
    r = cliente.get("/texto")
    assert r.status_code == 404
    assert r.json() == {"detail": {"code": "NOT_FOUND", "message": "Función no encontrada"}}


def test_reason_pasa_a_message_y_el_codigo_propio_se_conserva(cliente: TestClient) -> None:
    assert cliente.get("/con-reason").json()["detail"] == {"code": "SAML_X", "message": "no vale"}


def test_los_campos_extra_se_conservan(cliente: TestClient) -> None:
    detalle = cliente.get("/con-extras").json()["detail"]
    assert detalle["missing_slots"] == ["a"]
    assert detalle["message"] == "faltan"
    assert detalle["code"] == "UNPROCESSABLE_CONTENT" or detalle["code"].startswith("UNPROCESSABLE")


def test_un_objeto_sin_mensaje_gana_uno(cliente: TestClient) -> None:
    detalle = cliente.get("/sin-mensaje").json()["detail"]
    assert detalle["pending_block_ids"] == ["b1"]
    assert detalle["code"] == "CONFLICT"
    assert detalle["message"]


def test_las_cabeceras_del_error_se_conservan(cliente: TestClient) -> None:
    r = cliente.get("/con-cabeceras")
    assert r.headers["Retry-After"] == "7"
    assert r.json()["detail"]["code"] == "TOO_MANY_REQUESTS"


def test_una_ruta_que_no_existe_tambien(cliente: TestClient) -> None:
    assert cliente.get("/no-existe").json()["detail"]["code"] == "NOT_FOUND"


def test_un_fallo_sin_capturar_no_lleva_el_texto_de_la_excepcion(cliente: TestClient) -> None:
    r = cliente.get("/revienta")
    assert r.status_code == 500
    assert r.json() == {
        "detail": {"code": "INTERNAL_SERVER_ERROR", "message": MENSAJE_DE_ERROR_INTERNO}
    }


def test_la_validacion_de_entrada_conserva_su_forma(cliente: TestClient) -> None:
    """De ella saca el panel el error de cada campo del formulario."""
    detalle = cliente.post("/valida", json={"n": "x"}).json()["detail"]
    assert isinstance(detalle, list)
    assert detalle[0]["loc"] == ["body", "n"]


def test_una_lista_se_devuelve_tal_cual() -> None:
    lista = [{"loc": ["x"], "msg": "m", "type": "value_error"}]
    assert normalizar_detalle(422, lista) == lista


def test_la_aplicacion_lo_instala() -> None:
    from starlette.exceptions import HTTPException as StarletteHTTPException

    from server.app.main import app

    assert StarletteHTTPException in app.exception_handlers
    assert Exception in app.exception_handlers


def test_el_contrato_declara_el_esquema() -> None:
    from server.app.main import app

    esquema = app.openapi()
    assert "ErrorDeLaApi" in esquema["components"]["schemas"]
    operacion = esquema["paths"]["/api/v1/instancia"]["get"]
    assert operacion["responses"]["4XX"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/RespuestaDeError"
    }


#: Los tres sitios que la auditoría encontró devolviendo el texto de una excepción genérica.
SITIOS = (
    "routers/hub_llm_configs_router.py",
    "routers/redaccion/llm_drafts_router.py",
    "routers/saml_auth_router.py",
)


def _textos_de_excepciones_genericas(ruta: Path) -> list[str]:
    """`detail` construido con el texto de un `except Exception as x`."""
    arbol = ast.parse(ruta.read_text(encoding="utf-8"))
    culpables = []
    for manejador in ast.walk(arbol):
        if not (isinstance(manejador, ast.ExceptHandler) and manejador.name):
            continue
        if not (isinstance(manejador.type, ast.Name) and manejador.type.id == "Exception"):
            continue
        for nodo in ast.walk(manejador):
            if isinstance(nodo, ast.keyword) and nodo.arg == "detail":
                nombres = {n.id for n in ast.walk(nodo.value) if isinstance(n, ast.Name)}
                if manejador.name in nombres:
                    culpables.append(f"{ruta.name}:{nodo.value.lineno}")
    return culpables


@pytest.mark.parametrize("relativa", SITIOS)
def test_ningun_detalle_lleva_el_texto_de_una_excepcion_generica(relativa: str) -> None:
    assert not _textos_de_excepciones_genericas(APP / relativa)


def test_el_auditor_no_lleva_el_texto_del_fallo_al_cliente() -> None:
    """Que el auditor falle no impide registrar la función —es informativo— pero se registra en
    el log y el cliente no recibe el texto de la excepción."""
    texto = (APP / "routers/redaccion/funciones_router.py").read_text(encoding="utf-8")
    assert '"no_se_pudo_auditar": f"{type(fallo).__name__}: {fallo}"' not in texto


# Revisión de la PR #311 — la lista se dejaba pasar entera: sólo la de forma de validación
# (`[{loc, msg, type}]`) es un contrato conocido; otra cualquiera se saltaba el formato único y
# quien lee `detail.message` —panel, extensión, MCP— mostraba un fallo genérico.
def test_una_lista_con_forma_de_validacion_se_conserva() -> None:
    errores = [{"loc": ["nombre"], "msg": "obligatorio", "type": "value_error"}]
    assert normalizar_detalle(422, errores) == errores


def test_una_lista_cualquiera_entra_en_el_formato_unico() -> None:
    detalle = normalizar_detalle(400, ["a", "b"])
    assert detalle["code"] == "BAD_REQUEST"
    assert detalle["message"] == "Bad Request"
    assert detalle["errores"] == ["a", "b"]
