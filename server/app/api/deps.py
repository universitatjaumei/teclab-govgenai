from typing import AsyncGenerator

from fastapi import Depends, Header, HTTPException, Request, status
from sqlmodel.ext.asyncio.session import AsyncSession

from server.app.core.auth import AuthenticationError, UserInfo, decode_token
from server.app.core.auth.models import UserRole
from server.app.core.auth.pat.service import PatInvalidError, PatService
from server.app.database.db import server_engine

_PAT_PREFIX = "pat_"


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for obtaining a database session."""
    async with AsyncSession(server_engine) as session:
        yield session


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


#: Lo único que se puede hacer con una contraseña que puso otra persona (issue #94).
#:
#: `/auth/me` entra en la lista y no la debilita: leer quién eres no es hacer nada, y sin ella el
#: panel se queda ciego al recargar la página —la marca viaja dentro del token y el cliente no lo
#: abre—, así que no sabría ni que tiene que pedir el cambio.
_RUTAS_CON_CAMBIO_PENDIENTE = ("/auth/me/password", "/auth/me")


def _exigir_el_cambio_pendiente(request: Request, principal: UserInfo) -> None:
    """Corta la sesión que arrastra una contraseña ajena, salvo para cambiarla.

    **Se hace aquí y no en la pantalla** porque el aviso en el panel dejaría la contraseña viva
    para quien llame a la API a mano — que es justo quien preocupa. Con esto, el conocimiento de
    quien restableció queda acotado a un solo uso de verdad.

    Es un 403 y no un 401: la credencial es válida, lo que no es válido es seguir sin cambiarla.
    Un 401 haría que el panel la tomara por caducada y mandara a iniciar sesión otra vez, que es
    exactamente el bucle del que no se sale.
    """
    if not getattr(principal, "cambio_pendiente", False):
        return
    if any(request.url.path.endswith(ruta) for ruta in _RUTAS_CON_CAMBIO_PENDIENTE):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="CAMBIO_DE_CONTRASENA_PENDIENTE",
    )


async def get_current_user(
    request: Request,
    authorization: str | None = Header(default=None, alias="Authorization"),
    session: AsyncSession = Depends(get_session),
) -> UserInfo:
    """Valida el credencial del header Authorization (JWT de sesión o PAT).

    Discrimina por prefijo: ``pat_…`` se valida contra la BD (PatService) y adjunta
    los scopes del token en ``request.state.pat_scopes``; cualquier otro Bearer se
    trata como JWT de sesión humana (``pat_scopes = None`` → sin filtrado por scope).
    """
    if authorization is None:
        raise _unauthorized("Missing Authorization header. Use: Bearer <token>")
    if not authorization.startswith("Bearer "):
        raise _unauthorized("Invalid authorization header. Use: Bearer <token>")

    token = authorization.removeprefix("Bearer ").strip()

    if token.startswith(_PAT_PREFIX):
        try:
            principal = await PatService(session).verify(token)
        except PatInvalidError as e:
            raise _unauthorized(str(e))
        request.state.pat_scopes = principal.scopes
        return principal.user_info

    request.state.pat_scopes = None
    try:
        principal = decode_token(token)
    except AuthenticationError as e:
        raise _unauthorized(str(e))

    _exigir_el_cambio_pendiente(request, principal)
    return principal


async def get_current_user_optional(
    request: Request,
    authorization: str | None = Header(default=None, alias="Authorization"),
    session: AsyncSession = Depends(get_session),
) -> UserInfo | None:
    """Como `get_current_user`, pero devuelve `None` en vez de 401 si no hay credencial.

    SEC.8.5: los endpoints que consume el widget público admiten dos vías —sesión o
    credencial de sitio—, y con `get_current_user` la petición moría en un 401 antes de
    poder mirar la segunda. Es justamente por eso que un chatbot `public_anon` era
    inalcanzable sin token, y por lo que el widget acababa embebiendo uno privilegiado.

    **Un Authorization presente pero inválido sigue siendo 401**: sin eso, un token
    caducado degradaría a anónimo en silencio y la petición seguiría adelante como si
    nadie hubiera intentado identificarse.
    """
    if authorization is None:
        request.state.pat_scopes = None
        return None
    return await get_current_user(request, authorization, session)


def require_role(*roles: str):
    """Dependency factory que exige uno de los roles dados."""

    async def _check(user: UserInfo = Depends(get_current_user)) -> UserInfo:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user.role}' is not allowed. Required: {', '.join(roles)}",
            )
        return user

    return _check


# Gates nombrados con jerarquía superadmin > admin > user.
# `require_superadmin` solo acepta superadmin (plataforma global).
# `require_admin` acepta admin y superadmin (superadmin puede todo lo que un admin).
require_superadmin = require_role(UserRole.SUPERADMIN.value)
require_admin = require_role(UserRole.SUPERADMIN.value, UserRole.ADMIN.value)


def require_scopes_allowing_widget(*needed: str):
    """Como `require_scopes`, pero no exige credencial (SEC.8.5).

    El endpoint de chat admite dos vías: sesión/PAT, o credencial de sitio del widget. Con
    `require_scopes` a nivel de ruta la petición del widget moría en un 401 antes de que
    nadie mirara la cabecera de la credencial.

    **No relaja el filtro de scopes**: si viene un PAT, sus scopes se exigen igual. Lo que
    cambia es que la ausencia de credencial no es un rechazo aquí — quien decide si eso
    vale es el endpoint, que resuelve la credencial de sitio y aplica
    `assert_chatbot_access`, y este solo abre chatbots `public_anon`.
    """

    async def _check(
        request: Request, user: UserInfo | None = Depends(get_current_user_optional)
    ) -> UserInfo | None:
        scopes = getattr(request.state, "pat_scopes", None)
        if scopes is None:
            return user
        missing = [s for s in needed if s not in scopes]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "PAT_SCOPE_MISSING", "missing": missing},
            )
        return user

    return _check


def require_scopes(*needed: str):
    """Dependency factory que exige scopes a los principales PAT.

    Una sesión humana (JWT) no se filtra por scope (``pat_scopes`` es ``None``); un
    PAT debe portar todos los scopes requeridos o se rechaza con 403.
    """

    async def _check(
        request: Request, user: UserInfo = Depends(get_current_user)
    ) -> UserInfo:
        scopes = getattr(request.state, "pat_scopes", None)
        if scopes is None:
            return user
        missing = [s for s in needed if s not in scopes]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "PAT_SCOPE_MISSING", "missing": missing},
            )
        return user

    return _check


def require_sesion_humana():
    """Dependency factory que **rechaza los PAT**: la operación es de una persona con sesión.

    `require_scopes` deja pasar a un token que lleve el alcance pedido, y un endpoint que no pide
    ninguno deja pasar a **cualquier** token. Para lo que un token no debe poder hacer —publicar,
    retirar, emitir otros tokens—, esto (#174: el token del guion de un agente vive en las
    propiedades del guion, que ve cualquiera que pueda editarlo).
    """

    async def _check(
        request: Request, user: UserInfo = Depends(get_current_user)
    ) -> UserInfo:
        if getattr(request.state, "pat_scopes", None) is not None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "PAT_NO_PERMITIDO",
                    "message": "Esto lo hace una persona con su sesión, no un token.",
                },
            )
        return user

    return _check


def require_pat_scopes(*needed: str):
    """Como `require_scopes`, pero **exige además que el principal sea un PAT** (REG.2).

    `require_scopes` deja pasar una sesión JWT a propósito: un principal humano no se filtra por
    scope porque su autorización viene del rol. Para las superficies que existen **para clientes
    máquina** eso no vale: el registro de actividad y la anonimización como servicio los consumen
    agentes externos, y una sesión de navegador que pudiera escribir en el registro permitiría
    fabricar entradas desde el panel — que es exactamente lo que un registro de gobernanza no
    puede admitir.

    El 403 dice qué falta en cada caso, porque son dos problemas distintos de cara a quien
    integra: «esto necesita un token de máquina» y «a tu token le falta este scope».
    """

    async def _check(
        request: Request, user: UserInfo = Depends(get_current_user)
    ) -> UserInfo:
        scopes = getattr(request.state, "pat_scopes", None)
        if scopes is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "PAT_REQUIRED",
                    "message": (
                        "Esta operación es para clientes máquina: hace falta un Personal "
                        "Access Token, no una sesión."
                    ),
                    "scopes_requeridos": list(needed),
                },
            )
        missing = [s for s in needed if s not in scopes]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "PAT_SCOPE_MISSING", "missing": missing},
            )
        return user

    return _check


async def modulos_concedidos(
    user: UserInfo = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[str]:
    """Los módulos que tiene concedidos quien hace esta petición (INF.7).

    Existe como dependencia propia, y no dentro de `require_module`, por dos razones. Una es
    que así se calcula **una vez** por petición aunque varias guardas la consulten. La otra es
    que es **un solo punto que los tests pueden sobreescribir**: un test de chatbots que
    mockea la sesión con `AsyncMock` no puede responder a una consulta real, y sin este punto
    de sustitución la guarda devolvía 500 en vez de 403 — un fallo de infraestructura
    disfrazado de decisión de autorización.
    """
    from server.app.core.auth.modulos_service import modulos_del_usuario

    return await modulos_del_usuario(session, user)


def require_module(codigo: str):
    """Dependencia que exige tener concedido un módulo (INF.7).

    Antes, los routers de un módulo entero solo pedían `get_current_user`: cualquier cuenta
    autenticada podía listar y editar los chatbots institucionales y la configuración de LLM.
    Con el módulo de informes abierto a toda la organización, eso deja de ser teórico.

    El 403 dice **qué módulo** falta: quien lo recibe tiene que poder pedirlo, no adivinar.
    """

    async def _comprobar(
        user: UserInfo = Depends(get_current_user),
        concedidos: list[str] = Depends(modulos_concedidos),
    ) -> UserInfo:
        if codigo not in concedidos:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "message": f"Sin acceso al modulo '{codigo}'",
                    "modulo_requerido": codigo,
                },
            )
        return user

    return _comprobar
