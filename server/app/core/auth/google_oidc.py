"""Entrar con la cuenta institucional de Google (OIDC). Deploy: cloud.

**Por qué esto y no el SAML.** `/user/login` está declarado «provisional por definición» porque
el IdP institucional no estaba configurado y no tenía fecha. La UJI está en Google Workspace y el
proyecto del piloto cuelga de esa misma organización, así que el IdP **ya estaba disponible** por
otra puerta. Esto es el IdP, con llaves que ya se tienen.

**Y por qué no hace falta validar la firma del ID token.** En el flujo de código de autorización,
el token se recoge **directamente del endpoint de Google por HTTPS**, autenticándose con el
secreto de cliente. Google documenta que en ese caso la firma no hay que verificarla: el canal ya
dice quién lo emitió. Eso quita el trabajo de JWKS y RS256 entero.

Dos condiciones para que esa exención siga siendo cierta, y si alguna se rompe hay que volver a
verificar firma, emisor y audiencia:

1. el token llega del canje y **no** de un parámetro que traiga el navegador;
2. el flujo sigue siendo el de código de autorización, **no** implícito.

**El dominio es la autorización.** Sin comprobar `hd` cualquier cuenta de Google del mundo entra,
y se comprueba en el servidor **aunque** la pantalla de consentimiento esté en «Interna»: eso es
configuración de una consola que alguien puede cambiar, y una decisión de autorización no se
delega a una casilla.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
import jwt as pyjwt

#: Los dos extremos de Google. Constantes y no configurables: apuntar este login a otro sitio no
#: es configuración, es otro proveedor de identidad.
URL_AUTORIZACION = "https://accounts.google.com/o/oauth2/v2/auth"
URL_TOKEN = "https://oauth2.googleapis.com/token"

#: Lo único que se pide. Nada de aquí es un ámbito sensible, y por eso la pantalla de
#: consentimiento interna no pasa por ningún proceso de verificación de Google. Añadir uno
#: cambiaría ese régimen, así que ampliar esta tupla es una decisión, no un detalle.
AMBITOS = ("openid", "email", "profile")

#: Vida del `state`. Es el tiempo que alguien tarda en elegir cuenta en Google, no una sesión.
_VIDA_DEL_STATE = timedelta(minutes=10)

_ALGORITMO = "HS256"

#: Los dos valores de `iss` que Google emite, con y sin esquema. Son los dos válidos y hay que
#: admitir ambos: fijar sólo uno rechazaría tokens buenos.
_EMISORES_DE_GOOGLE = frozenset(
    {"https://accounts.google.com", "accounts.google.com"}
)


class ErrorDeIdentidad(Exception):
    """La cuenta no puede entrar. El motivo va en el mensaje, para el registro, no para quien entra."""


def _secreto() -> str:
    secreto = os.environ.get("JWT_SECRET_KEY", "")
    if not secreto:
        raise ErrorDeIdentidad("falta JWT_SECRET_KEY para firmar el `state`")
    return secreto


#: La cookie que liga el `state` al navegador que empezó el login.
COOKIE_DEL_VINCULO = "govgenai_google_vinculo"


def _huella(vinculo: str) -> str:
    return hashlib.sha256(vinculo.encode("utf-8")).hexdigest()


def crear_state() -> tuple[str, str, str]:
    """`(state, vinculo, nonce)`: un `state` firmado, de vida corta y **ligado a un navegador**.

    Se firma con `JWT_SECRET_KEY` y PyJWT, que es la forma que este proyecto ya usa para un valor
    corto que viaja por un canal que no controla (`delegated_actor.py`, SEC.2.1). Sin almacén de
    sesiones a propósito: el contenedor puede destruirse entre la ida y la vuelta, y un `state`
    guardado en memoria lo convertiría en un login que falla al azar.

    **El `vinculo` va en una cookie y su huella dentro del `state`** (2026-10-22). Sin eso el
    `state` sólo probaba que lo habíamos emitido nosotros, no a quién: cualquiera pedía uno,
    completaba el login con su cuenta y mandaba a otra persona el enlace de vuelta, que acababa
    con la sesión del atacante. El `nonce` va a Google y tiene que volver en el ID token.
    """
    ahora = datetime.now(timezone.utc)
    vinculo = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(16)
    state = pyjwt.encode(
        {
            "uso": "google-oauth-state",
            "nonce": nonce,
            "vinculo": _huella(vinculo),
            "iat": ahora,
            "exp": ahora + _VIDA_DEL_STATE,
        },
        _secreto(),
        algorithm=_ALGORITMO,
    )
    return state, vinculo, nonce


def validar_state(state: str | None, vinculo: str | None) -> str:
    """El `nonce` del `state` si lo emitimos nosotros, no ha caducado y viene del mismo navegador."""
    if not state:
        raise ErrorDeIdentidad("sin `state`")
    try:
        datos = pyjwt.decode(state, _secreto(), algorithms=[_ALGORITMO])
    except pyjwt.PyJWTError as exc:
        raise ErrorDeIdentidad(f"`state` inválido: {exc}") from exc
    # El `uso` impide que sirva aquí un token emitido para otra cosa con la misma clave — por
    # ejemplo un token de sesión, que también está firmado con `JWT_SECRET_KEY`.
    if datos.get("uso") != "google-oauth-state":
        raise ErrorDeIdentidad("`state` emitido para otro uso")
    if not vinculo or not hmac.compare_digest(datos.get("vinculo", ""), _huella(vinculo)):
        raise ErrorDeIdentidad("el login no se empezó en este navegador")
    return str(datos.get("nonce", ""))


def comprobar_nonce(claims: dict, nonce: str) -> None:
    """El ID token tiene que traer el `nonce` que mandamos a Google."""
    if not nonce or not hmac.compare_digest(str(claims.get("nonce", "")), nonce):
        raise ErrorDeIdentidad("el ID token no trae el `nonce` de este login")


def url_de_autorizacion(
    *, client_id: str, redirect_uri: str, dominio: str, state: str, nonce: str
) -> str:
    """A dónde se manda a quien entra."""
    return f"{URL_AUTORIZACION}?" + urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(AMBITOS),
            "state": state,
            "nonce": nonce,
            # `hd` aquí es **una pista de interfaz**: hace que Google enseñe directamente las
            # cuentas de la organización. No es la autorización — ésa la decide
            # `identidad_de_las_claims` sobre lo que Google responda.
            "hd": dominio,
            # Sin esto, quien ya tenga una sesión de Google entra con ella sin poder elegir, y
            # en un equipo compartido eso es entrar como otra persona.
            "prompt": "select_account",
        }
    )


async def canjear_codigo(
    code: str, *, client_id: str, client_secret: str, redirect_uri: str
) -> dict:
    """Canjea el código por el ID token y devuelve sus *claims*.

    **Es la única función que habla con Google**, y por eso es la costura por la que los tests
    entran: sustituyéndola se prueba la comprobación del dominio de verdad, sin red.
    """
    async with httpx.AsyncClient(timeout=10) as cliente:
        resp = await cliente.post(
            URL_TOKEN,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
    if resp.status_code != 200:
        raise ErrorDeIdentidad(f"Google rechazó el canje del código ({resp.status_code})")

    id_token = resp.json().get("id_token")
    if not id_token:
        raise ErrorDeIdentidad("la respuesta de Google no trae `id_token`")

    return claims_del_id_token(id_token, client_id=client_id)


def claims_del_id_token(id_token: str, *, client_id: str) -> dict:
    """Las *claims* del ID token, con `aud` e `iss` comprobados.

    **La firma no se verifica**, y está razonado en el docstring del módulo: el token viene del
    canje por HTTPS contra Google, autenticado con el secreto de cliente.

    **Pero `aud` e `iss` sí**, y precisamente *porque* la firma no se verifica. Si la exención se
    apoya en «este token vino de Google para nosotros», comprobar que lo dice el propio token es
    barato y cierra el hueco de que algún día llegue por otra vía: un token emitido para **otro
    cliente** no vale aquí aunque sea legítimo.

    En el camino bueno no puede fallar —Google pone nuestro `client_id` en `aud` por
    construcción—, y ése es el punto: una comprobación que sólo se activa cuando algo va mal.

    Nota sobre PyJWT, medida y no supuesta: con `verify_signature` en `False`, PyJWT **también
    apaga** el resto de comprobaciones, así que un `aud` presente sin `audience` **no** levanta
    (comprobado con 2.14.0). O sea que esto no arregla un fallo: añade una comprobación que no
    había.
    """
    try:
        claims = pyjwt.decode(
            id_token,
            options={"verify_signature": False, "verify_aud": True},
            audience=client_id,
        )
    except pyjwt.PyJWTError as exc:
        raise ErrorDeIdentidad(f"el ID token no es para este cliente: {exc}") from exc

    # `iss` se comprueba a mano porque Google emite **dos** valores válidos y el parámetro de
    # PyJWT admite uno.
    emisor = claims.get("iss", "")
    if emisor not in _EMISORES_DE_GOOGLE:
        raise ErrorDeIdentidad(f"el ID token no lo emitió Google, sino «{emisor}»")

    return claims


def identidad_de_las_claims(claims: dict, *, dominio_admitido: str) -> tuple[str, str]:
    """`(correo, nombre)` si la cuenta puede entrar. Levanta si no.

    **El dominio se lee de `hd`, no del correo.** Comprobar que el correo termina en el dominio
    **no** es comprobar que la cuenta pertenece a la organización, y confundir las dos cosas es
    el fallo que deja entrar a cualquiera con un correo que acabe bien.
    """
    correo = (claims.get("email") or "").strip().lower()
    if not correo:
        raise ErrorDeIdentidad("el ID token no trae `email`")

    if claims.get("email_verified") is not True:
        raise ErrorDeIdentidad(f"correo sin verificar en Google: {correo}")

    hd = (claims.get("hd") or "").strip().lower()
    if not hd:
        # Una cuenta personal de Google no trae `hd`. Ausente es rechazo, nunca «cualquiera».
        raise ErrorDeIdentidad(f"la cuenta {correo} no pertenece a ninguna organización")
    if hd != dominio_admitido.strip().lower():
        raise ErrorDeIdentidad(
            f"la cuenta {correo} pertenece a «{hd}» y no a «{dominio_admitido}»"
        )

    return correo, (claims.get("name") or correo)
