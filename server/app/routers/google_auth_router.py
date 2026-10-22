"""Login con la cuenta institucional de Google (OIDC), issue #95.

Deploy: cloud

Dos rutas: una que manda a Google y otra que recibe la vuelta. Todo lo que decide está en
`core/auth/google_oidc.py`; aquí sólo se cablea.

**Apagado significa 404.** Es la convención de `/user/login`: un 403 confirmaría que la ruta está
ahí, apagada, y eso es información que no hace falta dar. Y hacen falta las **cuatro** piezas
—identificador, secreto, dominio y URL de vuelta— porque un login a medio configurar es peor
que ninguno: sin dominio no habría autorización que comprobar, y sin URL de vuelta declarada
Google rechazaría el canje.

**El aprovisionamiento no se duplica.** `SamlIdentityService.resolve_session` ya resuelve un
correo en una `UserInfo`: busca superadministrador, luego administrador con sus organizaciones, y
si no es ninguno crea la persona *Just-In-Time*. Recibe los atributos con los nombres que el IdP
declara, así que aquí se le pasa un diccionario con esos mismos nombres. El nombre de la clase
dice `Saml` y lo que hace es resolver una identidad federada; renombrarla es otro cambio, y
mientras no se haga queda dicho aquí para que nadie crea que esto entra por SAML.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.api.deps import get_session
from server.app.core.auth import google_oidc
from server.app.core.auth.jwt_handler import create_token
from server.app.core.auth.saml.identity_service import SamlIdentityService
from server.app.core.config import get_settings

router = APIRouter(prefix="/auth/google", tags=["auth-google"])


def _ajustes_o_404():
    ajustes = get_settings()
    if not ajustes.google_login_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
    return ajustes


def _url_de_vuelta() -> str:
    """El `redirect_uri` que se registró en Google, **declarado y no derivado**.

    Derivarlo de la petición con `request.url_for()` era la primera versión y **estaba mal**:
    esta aplicación no arranca con `--proxy-headers` ni `FORWARDED_ALLOW_IPS`, y el defecto de
    uvicorn sólo confía en `127.0.0.1` mientras Caddy conecta desde la red de Docker. Las
    cabeceras reenviadas no se honran, así que el esquema derivado es `http://` — y Google
    rechaza un `redirect_uri` sin TLS que no sea `localhost`, además de exigir coincidencia
    carácter a carácter con lo registrado.

    Declararlo es lo que hace el SAML con `SAML_SP_ACS_URL`, por este mismo motivo.
    """
    return get_settings().google_oauth_redirect_uri


@router.get("/login", operation_id="loginConGoogle")
async def google_login():
    """Manda a Google. La respuesta es una redirección, no un JSON."""
    ajustes = _ajustes_o_404()
    state, vinculo, nonce = google_oidc.crear_state()
    respuesta = RedirectResponse(
        url=google_oidc.url_de_autorizacion(
            client_id=ajustes.google_oauth_client_id,
            redirect_uri=_url_de_vuelta(),
            dominio=ajustes.google_oauth_allowed_domain,
            state=state,
            nonce=nonce,
        ),
        status_code=302,
    )
    # El `state` sólo vale con esta cookie: es lo que impide terminar en este navegador un login
    # que empezó otro. `Lax` y no `Strict`, porque la vuelta de Google es una navegación desde
    # otro sitio; `Secure` en producción, que es donde hay TLS. Vive lo que vive el `state`.
    respuesta.set_cookie(
        google_oidc.COOKIE_DEL_VINCULO,
        vinculo,
        max_age=600,
        path="/api/v1/auth/google",
        httponly=True,
        samesite="lax",
        secure=ajustes.environment == "production",
    )
    return respuesta


@router.get("/callback", name="google_callback", operation_id="callbackDeGoogle")
async def google_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    """Recibe la vuelta de Google, comprueba el dominio y emite el token de la plataforma."""
    ajustes = _ajustes_o_404()

    # Quien cancela en la pantalla de Google vuelve con `error` y sin `code`. No es un fallo
    # nuestro y no merece un 500.
    if error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "GOOGLE_OAUTH_CANCELADO", "reason": error},
        )

    try:
        nonce = google_oidc.validar_state(
            state, request.cookies.get(google_oidc.COOKIE_DEL_VINCULO)
        )
    except google_oidc.ErrorDeIdentidad as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "GOOGLE_OAUTH_STATE_INVALIDO", "reason": str(exc)},
        ) from exc

    if not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "GOOGLE_OAUTH_SIN_CODIGO"},
        )

    # Por atributo del módulo y no por el nombre importado: es la costura de los tests, y con
    # `from ... import canjear_codigo` la sustitución no llegaría aquí.
    try:
        claims = await google_oidc.canjear_codigo(
            code,
            client_id=ajustes.google_oauth_client_id,
            client_secret=ajustes.google_oauth_client_secret,
            redirect_uri=_url_de_vuelta(),
        )
    except google_oidc.ErrorDeIdentidad as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "GOOGLE_OAUTH_CANJE_FALLIDO", "reason": str(exc)},
        ) from exc

    try:
        google_oidc.comprobar_nonce(claims, nonce)
    except google_oidc.ErrorDeIdentidad as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "GOOGLE_OAUTH_NONCE_INVALIDO", "reason": str(exc)},
        ) from exc

    # 403 y no 401, por lo mismo que el ACS de SAML: Google la autenticó bien; es esta
    # plataforma la que no la deja pasar. Con un 401 se buscaría el fallo donde no está.
    try:
        correo, nombre = google_oidc.identidad_de_las_claims(
            claims, dominio_admitido=ajustes.google_oauth_allowed_domain
        )
    except google_oidc.ErrorDeIdentidad as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "GOOGLE_OAUTH_DOMINIO_NO_ADMITIDO", "reason": str(exc)},
        ) from exc

    identidad = SamlIdentityService(session)
    user_info = await identidad.resolve_session(
        correo,
        {
            ajustes.saml_attr_email: [correo],
            ajustes.saml_attr_name: [nombre],
        },
    )

    token = create_token(user_info)
    return_url = ajustes.saml_frontend_return_url
    if not return_url:
        return {
            "access_token": token,
            "token_type": "bearer",
            "user": user_info.to_dict(),
        }
    # En el *fragment*, como el ACS de SAML: así el token no queda en los registros del servidor
    # ni del proxy, que sí guardan la cadena de consulta.
    respuesta = RedirectResponse(url=f"{return_url}#token={token}", status_code=302)
    # El vínculo ya sirvió: un `state` se usa una vez.
    respuesta.delete_cookie(google_oidc.COOKIE_DEL_VINCULO, path="/api/v1/auth/google")
    return respuesta
