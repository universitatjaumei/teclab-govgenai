"""
Deploy: cloud

Service Provider SAML 2.0 (AUTH.1): inicia el login contra el IdP institucional,
consume la respuesta firmada (ACS) y publica la metadata del SP. La emisión del JWT
de sesión y el provisioning de la identidad llegan en AUTH.2.
"""

import logging
import threading
import time

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse, Response

from onelogin.saml2.auth import OneLogin_Saml2_Auth
from onelogin.saml2.settings import OneLogin_Saml2_Settings

from server.app.api.deps import get_saml_identity_service
from server.app.core.auth import create_token
from server.app.core.auth.saml import (
    InvalidSamlConfigError,
    build_saml_settings,
    prepare_saml_request,
)
from server.app.core.auth.saml.identity_service import (
    SamlIdentityService,
    SamlMissingEmailError,
    SamlUserInactiveError,
)
from server.app.core.config import get_settings

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/saml", tags=["auth-saml"])

#: El ID del `AuthnRequest`, en el navegador que empezó el login. La vuelta del IdP es un POST
#: desde otro sitio, así que en producción la cookie va con `SameSite=None` (y por tanto `Secure`):
#: con `Lax` el navegador no la mandaría y ningún login funcionaría.
COOKIE_DE_LA_PETICION = "govgenai_saml_peticion"
_RUTA_DE_LA_COOKIE = "/api/v1/auth/saml"

#: Aserciones ya consumidas, hasta su `NotOnOrAfter`: una capturada no vale otra vez. En memoria
#: del proceso, que basta con una sola instancia de la aplicación; con varias, cada una tendría la
#: suya y habría que llevarlo a un almacén compartido.
_ASERCIONES_USADAS: dict[str, float] = {}
_CERROJO_DE_ASERCIONES = threading.Lock()


def _ya_se_uso(id_asercion: str | None, caduca_en: float | None) -> bool:
    """Anota la aserción y dice si ya estaba. Sin ID no se puede comprobar: se trata como usada."""
    if not id_asercion:
        return True
    ahora = time.time()
    with _CERROJO_DE_ASERCIONES:
        for viejo in [k for k, v in _ASERCIONES_USADAS.items() if v < ahora]:
            del _ASERCIONES_USADAS[viejo]
        if id_asercion in _ASERCIONES_USADAS:
            return True
        _ASERCIONES_USADAS[id_asercion] = caduca_en or (ahora + 600)
        return False


def _ensure_enabled() -> None:
    if not get_settings().saml_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SAML SSO is not enabled",
        )


async def _build_auth(request: Request) -> OneLogin_Saml2_Auth:
    req = await prepare_saml_request(request)
    return OneLogin_Saml2_Auth(req, build_saml_settings())


@router.get("/login")
async def saml_login(request: Request, relay_state: str | None = None):
    """Redirige (302) al IdP con el AuthnRequest."""
    _ensure_enabled()
    auth = await _build_auth(request)
    respuesta = RedirectResponse(url=auth.login(return_to=relay_state), status_code=302)
    produccion = get_settings().environment == "production"
    respuesta.set_cookie(
        COOKIE_DE_LA_PETICION,
        auth.get_last_request_id() or "",
        max_age=600,
        path=_RUTA_DE_LA_COOKIE,
        httponly=True,
        samesite="none" if produccion else "lax",
        secure=produccion,
    )
    return respuesta


@router.post("/acs")
async def saml_acs(
    request: Request,
    identity: SamlIdentityService = Depends(get_saml_identity_service),
):
    """Assertion Consumer Service: valida la aserción, resuelve la identidad y emite JWT."""
    _ensure_enabled()
    auth = await _build_auth(request)
    peticion = request.cookies.get(COOKIE_DE_LA_PETICION)

    try:
        # Con el ID de la petición python3-saml compara `InResponseTo`; sin él, no compara nada.
        auth.process_response(request_id=peticion)
    except Exception as exc:  # cualquier fallo de parseo => 401
        # #276 — el texto de python3-saml puede llevar trozos de la aserción: al registro.
        _log.warning("La respuesta SAML no se pudo validar", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "SAML_VALIDATION_FAILED", "message": "La respuesta del proveedor de identidad no es válida."},
        ) from exc

    errors = auth.get_errors()
    if errors:
        # Igual que el `except` de arriba: los códigos y el motivo de python3-saml, al registro.
        _log.warning("La respuesta SAML no es válida: %s (%s)", errors, auth.get_last_error_reason())
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "SAML_VALIDATION_FAILED", "message": "La respuesta del proveedor de identidad no es válida."},
        )
    if not auth.is_authenticated():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "SAML_NOT_AUTHENTICATED"},
        )
    # Una respuesta que no contesta a una petición de este navegador no se acepta, aunque esté
    # bien firmada: es como alguien termina en otro navegador un login que empezó él.
    if not peticion or auth.get_last_response_in_response_to() != peticion:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "SAML_NO_SOLICITADA"},
        )
    if _ya_se_uso(auth.get_last_assertion_id(), auth.get_last_assertion_not_on_or_after()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "SAML_REUTILIZADA"},
        )

    try:
        user_info = await identity.resolve_session(
            auth.get_nameid() or "", auth.get_attributes()
        )
    except SamlMissingEmailError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "SAML_MISSING_EMAIL", "reason": str(exc)},
        ) from exc
    except SamlUserInactiveError as exc:
        # 403 y no 401: el IdP la autenticó bien, es esta plataforma la que no la deja pasar.
        # Con un 401 quien lo vea buscará el fallo en el IdP, que es donde no está.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "USER_INACTIVE", "reason": str(exc)},
        ) from exc

    token = create_token(user_info)
    return_url = get_settings().saml_frontend_return_url
    if not return_url:
        # Sin frontend configurado (p. ej. clientes API): devolver el token directamente.
        return {
            "access_token": token,
            "token_type": "bearer",
            "user": user_info.to_dict(),
        }
    # El token viaja en el fragment para no quedar registrado en logs de servidor/proxy.
    respuesta = RedirectResponse(url=f"{return_url}#token={token}", status_code=302)
    respuesta.delete_cookie(COOKIE_DE_LA_PETICION, path=_RUTA_DE_LA_COOKIE)
    return respuesta


@router.get("/metadata")
async def saml_metadata():
    """Publica la metadata XML del SP."""
    _ensure_enabled()
    try:
        saml_settings = OneLogin_Saml2_Settings(
            build_saml_settings(sp_only=True), sp_validation_only=True
        )
    except InvalidSamlConfigError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    metadata = saml_settings.get_sp_metadata()
    errors = saml_settings.validate_metadata(metadata)
    if errors:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_SP_METADATA", "errors": errors},
        )
    return Response(content=metadata, media_type="application/xml")


@router.get("/logout")
async def saml_logout(request: Request):
    """Inicia el Single Logout si el SP tiene SLS configurado (stub mínimo)."""
    _ensure_enabled()
    if not get_settings().saml_sp_sls_url:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Single Logout (SLO) is not configured (SAML_SP_SLS_URL)",
        )
    auth = await _build_auth(request)
    return RedirectResponse(url=auth.logout(), status_code=302)
