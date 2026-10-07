"""Cliente HTTP autenticado por PAT (MCP.1).

Envuelve ``httpx.AsyncClient`` añadiendo el header ``Authorization: Bearer <PAT>``
a cada petición y traduciendo los códigos de error del backend a excepciones
legibles (ver ``errors.py``). NO importa nada de ``server/app``: es un cliente más
de la API HTTP, igual que el frontend.

La cabecera se pone **en cada petición** y no al construir el cliente ``httpx``
(REG.4). Así el MCP remoto puede compartir un solo pool de conexiones entre
clientes que presentan tokens distintos, y deja de existir la trampa de que
pasar ``client=`` descartara el PAT en silencio.
"""
from __future__ import annotations

from typing import Any

import httpx

from errors import ApiError, AuthError, ScopeError, ServerError, ValidationError

_DEFAULT_TIMEOUT = 30.0


class ApiClient:
    """Cliente async de la API de Gov Gen AI Platform autenticado con un PAT."""

    def __init__(
        self,
        base_url: str,
        pat: str,
        *,
        client: httpx.AsyncClient | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._pat = pat
        self._client = client or httpx.AsyncClient(
            base_url=self._base_url,
            timeout=timeout,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "ApiClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    # -- verbos HTTP -------------------------------------------------------

    async def get(self, path: str, **kwargs: Any) -> Any:
        return await self._request("GET", path, **kwargs)

    async def post(self, path: str, **kwargs: Any) -> Any:
        return await self._request("POST", path, **kwargs)

    async def patch(self, path: str, **kwargs: Any) -> Any:
        return await self._request("PATCH", path, **kwargs)

    async def put(self, path: str, **kwargs: Any) -> Any:
        return await self._request("PUT", path, **kwargs)

    async def delete(self, path: str, **kwargs: Any) -> Any:
        return await self._request("DELETE", path, **kwargs)

    # -- internos ----------------------------------------------------------

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        cabeceras = {
            "Authorization": f"Bearer {self._pat}",
            **(kwargs.pop("headers", None) or {}),
        }
        response = await self._client.request(
            method, path, headers=cabeceras, **kwargs
        )
        self._raise_for_status(response)
        return self._parse(response)

    @staticmethod
    def _body(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            return response.text or None

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.is_success:
            return

        status = response.status_code
        detail = self._body(response)

        if status == 401:
            raise AuthError(
                "Autenticación rechazada (401): el PAT es inválido, está revocado "
                "o ha expirado.",
                status_code=status,
                detail=detail,
            )
        if status == 403:
            # #214 — un endpoint que no admite tokens no es «te falta un alcance»: decirlo así
            # manda a buscar un alcance que no existe (revisión de la PR #235).
            interno = detail.get("detail") if isinstance(detail, dict) else None
            codigo = interno.get("code") if isinstance(interno, dict) else None
            mensaje = (
                "Permiso denegado (403): este endpoint no admite tokens; es de una persona con "
                "su sesión."
                if codigo == "PAT_NO_PERMITIDO"
                else "Permiso denegado (403): el PAT no porta el scope necesario para esta operación."
            )
            raise ScopeError(mensaje, status_code=status, detail=detail)
        if status in (400, 422):
            # 400 Bad Request y 422 Unprocessable Entity comparten familia: entrada
            # rechazada por el servidor (reglas de negocio o validación de esquema).
            raise ValidationError(
                f"Validación fallida ({status}): el servidor rechazó la petición.",
                status_code=status,
                detail=detail,
            )
        if status >= 500:
            raise ServerError(
                f"Error del servidor remoto ({status}).",
                status_code=status,
                detail=detail,
            )
        raise ApiError(
            f"Respuesta HTTP inesperada ({status}).",
            status_code=status,
            detail=detail,
        )

    @staticmethod
    def _parse(response: httpx.Response) -> Any:
        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            return response.text
