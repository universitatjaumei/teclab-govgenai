"""Un solo formato de error para toda la API: `{"detail": {"code", "message", …}}` (#276).

**Lo que había.** 210 errores con `detail` de texto, 85 con objeto, y entre los objetos unos con
`message`, otros con `reason` y otros sin ninguno de los dos —`{"pending_block_ids": […]}`—.
Cada cliente —el panel, la extensión, el servidor MCP, quien integra por API— tenía que adivinar
qué forma le tocaba, y el panel acabó con cinco funciones distintas para sacar el motivo de un
fallo. Decisión del usuario, 2026-10-25: un formato único en el cable, aunque cambie lo que
recibe quien leía `detail` como texto; la plataforma es `0.x` y no promete compatibilidad.

**Cómo.** No se reescriben los trescientos `raise HTTPException(...)`: un manejador central
normaliza lo que salga, que es la única forma de que el siguiente que se escriba no rompa la
regla. El texto pasa a `message` con un `code` que sale del estado HTTP; un objeto conserva sus
campos —`missing_slots`, `problemas`…, que es lo que una pantalla necesita para señalar el
campo— y gana el `message` que le falte. Las cabeceras del error se conservan: el
`WWW-Authenticate` de un 401 y el `Retry-After` de un 429 son parte de la respuesta.

**Lo que se queda como está**: la validación de entrada de FastAPI (`[{loc, msg, type}]`), que ya
tiene su esquema en el contrato (`HTTPValidationError`) y de la que el panel saca el error de
cada campo del formulario. Y una lista que un router devuelva en `detail` con esa misma forma.

**Un fallo sin capturar** responde 500 con un mensaje fijo y no con el de la excepción: el widget
es público, y el texto de una excepción puede llevar una consulta, una ruta del contenedor o la
respuesta cruda de un proveedor (issue #147). El detalle va al registro, que es donde lo necesita
quien lo arregla.
"""
from __future__ import annotations

import logging
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from starlette.exceptions import HTTPException as StarletteHTTPException

_log = logging.getLogger(__name__)

#: Lo que recibe el cliente cuando el fallo no lo previó nadie. Fijo a propósito.
MENSAJE_DE_ERROR_INTERNO = "Error interno del servidor."


class ErrorDeLaApi(BaseModel):
    """El cuerpo de `detail` en toda respuesta de error que no sea de validación de entrada.

    `code` es estable y se puede comparar; `message` es para una persona. Los demás campos son
    los que el endpoint añada para que el cliente actúe —qué campo falta, qué bloque espera—.
    """

    model_config = ConfigDict(extra="allow")

    code: str
    message: str


class RespuestaDeError(BaseModel):
    detail: ErrorDeLaApi


def _codigo_del_estado(estado: int) -> str:
    try:
        return HTTPStatus(estado).name
    except ValueError:
        return "ERROR"


def _frase_del_estado(estado: int) -> str:
    try:
        return HTTPStatus(estado).phrase
    except ValueError:
        return "Error"


def _tiene_forma_de_validacion(detalle: list[Any]) -> bool:
    return bool(detalle) and all(
        isinstance(error, dict) and "loc" in error and "msg" in error for error in detalle
    )


def normalizar_detalle(estado: int, detalle: Any) -> Any:
    """`detail` en la forma única. Una lista con forma de validación se devuelve tal cual.

    Cualquier otra lista va entera a `errores`, dentro del formato: si pasara sin envolver,
    quien lee `detail.message` no tendría nada que leer.
    """
    if isinstance(detalle, list):
        if _tiene_forma_de_validacion(detalle):
            return detalle
        return {"code": _codigo_del_estado(estado), "message": _frase_del_estado(estado), "errores": detalle}
    if isinstance(detalle, dict):
        normalizado = dict(detalle)
        mensaje = normalizado.pop("message", None) or normalizado.pop("reason", None)
        if not isinstance(mensaje, str) or not mensaje:
            mensaje = _frase_del_estado(estado)
        normalizado["code"] = str(normalizado.get("code") or _codigo_del_estado(estado))
        normalizado["message"] = mensaje
        return normalizado
    mensaje = str(detalle) if detalle not in (None, "") else _frase_del_estado(estado)
    return {"code": _codigo_del_estado(estado), "message": mensaje}


async def _error_http(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": normalizar_detalle(exc.status_code, exc.detail)},
        headers=getattr(exc, "headers", None),
    )


async def _error_sin_capturar(_request: Request, exc: Exception) -> JSONResponse:
    _log.error("Fallo sin capturar; el cliente recibe un 500 genérico", exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={"detail": {"code": "INTERNAL_SERVER_ERROR", "message": MENSAJE_DE_ERROR_INTERNO}},
    )


def _con_el_esquema_de_error(app: FastAPI):
    """`app.openapi` con `ErrorDeLaApi` en los componentes y en las respuestas 4XX y 5XX.

    Va en el contrato para que Orval genere el tipo y el panel no lo escriba a mano, que es la
    regla de AGENTS.md: el frontend usa los tipos que salen del servidor.
    """
    original = app.openapi

    def openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        esquema = original()
        componentes = esquema.setdefault("components", {}).setdefault("schemas", {})
        definicion = RespuestaDeError.model_json_schema(ref_template="#/components/schemas/{model}")
        componentes.update(definicion.pop("$defs", {}))
        componentes["RespuestaDeError"] = definicion
        referencia = {"$ref": "#/components/schemas/RespuestaDeError"}
        for operaciones in esquema.get("paths", {}).values():
            for operacion in operaciones.values():
                respuestas = operacion.setdefault("responses", {})
                for rango in ("4XX", "5XX"):
                    respuestas.setdefault(rango, {
                        "description": "Error con el formato único de la API",
                        "content": {"application/json": {"schema": referencia}},
                    })
        app.openapi_schema = esquema
        return esquema

    return openapi


def instalar_errores(app: FastAPI) -> None:
    """Los manejadores y el esquema. Se llama una vez, al construir la aplicación."""
    app.add_exception_handler(StarletteHTTPException, _error_http)
    app.add_exception_handler(Exception, _error_sin_capturar)
    app.openapi = _con_el_esquema_de_error(app)  # type: ignore[method-assign]
