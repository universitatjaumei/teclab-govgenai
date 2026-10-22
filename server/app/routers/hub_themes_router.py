"""Router para gestión de temas del chatbot.

Deploy: cloud
Módulo: plataforma — con **tres excepciones**, y ninguna es un descuido (PLAT.5).

`require_module` depende de `get_current_user`, así que a nivel de router responderia 401 a lo
que hoy funciona sin sesión. Va por endpoint, y estos tres se quedan fuera:

- `get_theme_for_chatbot` y `get_theme_logo`: los consume el **widget público**, que no tiene
  sesión ninguna — y un `<img>` no manda cabecera de autorización aunque la hubiera.
- `get_resolved_theme`: es de donde sale la **marca de la cabecera del panel**, que pinta para
  todo el mundo. Exigirle `plataforma` dejaría sin logotipo a quien solo tenga `informes`.
- `get_preset_themes` se queda como estaba, sin auth: son cuatro etiquetas fijas y no revela nada.


`get_theme_for_chatbot` es la excepción: la consume el widget público, que es tráfico
edge (mismo consumidor que `hub_chat_router`). Se queda aquí porque hoy `DEPLOY_MODE=all`
registra los dos bloques igual. **Pendiente si se llega a desplegar `edge` sin `cloud`**:
hoy ese endpoint 404earía porque este router no se registra en `_register_edge`. Desde
SEC.8.6 el obstáculo es menor de lo que era —los temas viven en `hub_themes`, una tabla de
`HubConfigBase` que se sincroniza cloud→edge, y no en un almacén propiedad de este módulo—.
"""
import re
import uuid
from datetime import datetime, timezone

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.api.deps import (
    get_current_user,
    get_current_user_optional,
    require_module,
    require_role,
)
from server.app.core.auth.chatbot_access import VIA_WIDGET, assert_chatbot_access
from server.app.core.auth.widget_key import (
    CABECERA as CABECERA_WIDGET,
    resolver_widget_key,
)
from server.app.core.auth.delegated_actor import resolve_effective_actor
from server.app.core.auth.models import UserInfo
from server.app.core.auth.tenancy import assert_org_access, puede_acceder
from server.app.core.storage import StorageService, get_storage_service
from server.app.core.uploads import UploadKind, tipo_de_imagen, validate_upload
from server.app.modules.agents_hub.database.config_models import HubChatbot, HubTheme
from server.app.modules.agents_hub.database.connection import get_async_session

router = APIRouter(prefix="/hub/themes", tags=["hub-themes"])

# Un logotipo institucional cabe de sobra en 1 MB. El tope se declara aquí y no se toma
# del `max_upload_mb` general: ese está dimensionado para un PDF del corpus.
_MAX_LOGO_BYTES = 1024 * 1024

_require_admin = require_role("superadmin", "admin")
#: La guarda de módulo, por endpoint. Ver las tres excepciones en el docstring.
_de_plataforma = Depends(require_module("plataforma"))
_require_superadmin = require_role("superadmin")


# ============================================
# Modelos Pydantic
# ============================================

class ThemeColors(BaseModel):
    """La paleta de la institución, para el widget **y para el panel** (REV.9).

    Hasta REV.9 esta paleta no pintaba el panel: sus dieciséis colores servían al widget, y el
    panel se dibujaba con las variables Tailwind de `frontend/src/index.css`, escritas a mano.
    O sea que había **dos fuentes de verdad que no se hablaban**, y la consecuencia era que se
    podía cambiar cualquier color en «Identidad visual» y no cambiaba nada: el único consumidor
    de la cascada era el logotipo. El usuario lo notó por el sitio por el que se nota —«el color
    de fondo de la barra lateral no aparece en la selección»—, y no aparecía porque no existía.

    Dos cambios, por eso:

    - **Los valores por omisión son los de `index.css`**, no los de antes. `primary` era
      `#0066cc` y el panel lleva `#0b5394` desde UX.5: con el default viejo, la pantalla enseñaba
      un azul que no era el de la aplicación y aplicarlo habría cambiado la identidad sin que
      nadie lo pidiera. Lo vigila un test que compara este fichero con `index.css`.
    - **Los tokens del panel entran en la paleta** (`sidebar` y compañía). No van en un grupo
      aparte: la identidad de una institución es una, y partirla en «colores del widget» y
      «colores del panel» obliga a elegir dos veces el mismo azul.
    """

    primary: str = "#0b5394"
    primaryHover: str = "#0a4a85"
    primaryLight: str = "#e8f0f8"
    secondary: str = "#6c757d"
    background: str = "#ffffff"
    surface: str = "#f8f9fa"
    text: str = "#212529"
    textSecondary: str = "#6c757d"
    border: str = "#dee2e6"
    error: str = "#dc3545"
    success: str = "#28a745"
    warning: str = "#ffc107"
    botMessage: str = "#f1f3f4"
    botMessageText: str = "#212529"
    userMessage: str = "#0b5394"
    userMessageText: str = "#ffffff"
    # --- El panel de administración (REV.9). Los nombres son los de la variable Tailwind que
    # cada uno alimenta, para que la correspondencia se lea sin tener que buscarla.
    primaryForeground: str = "#ffffff"
    accent: str = "#e8f0f8"
    accentForeground: str = "#0b5394"
    ring: str = "#0b5394"
    sidebar: str = "#0b5394"
    sidebarForeground: str = "#eaf1f8"
    sidebarPrimary: str = "#ffffff"
    sidebarAccent: str = "#1266b3"
    sidebarAccentForeground: str = "#ffffff"
    sidebarBorder: str = "#2a6fae"

    model_config = {"extra": "allow"}


class ThemeTypography(BaseModel):
    fontFamily: str = "'Inter', sans-serif"
    fontSize: str = "1rem"
    fontSizeSmall: str = "0.875rem"
    fontSizeLarge: str = "1.125rem"
    fontWeight: int = 400
    fontWeightBold: int = 600
    lineHeight: float = 1.5


class ThemeSpacing(BaseModel):
    xs: str = "0.25rem"
    sm: str = "0.5rem"
    md: str = "1rem"
    lg: str = "1.5rem"
    xl: str = "2rem"


class ThemeBranding(BaseModel):
    """La marca de la institución, **como dato de configuración**.

    Existía la cascada visual entera —colores, tipografía, espaciado— y la marca era lo
    único que no viajaba por ella: el panel importaba `@/assets/logo-uji.png` como código
    fuente, así que cualquier institución que clonara el repositorio arrancaba con el
    logotipo de otra. Es la misma regla que ya rige el vocabulario del corpus: la identidad
    de una organización es dato revisable, no una línea del programa.

    `logoContentType` lo deduce el servidor de la firma real del fichero, nunca del
    `content_type` que manda el cliente.
    """

    logoUrl: str | None = None
    logoAlt: str | None = None
    logoContentType: str | None = None


class ThemeConfig(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    version: str = "1.0.0"
    colors: ThemeColors = Field(default_factory=ThemeColors)
    typography: ThemeTypography = Field(default_factory=ThemeTypography)
    spacing: ThemeSpacing = Field(default_factory=ThemeSpacing)
    branding: ThemeBranding = Field(default_factory=ThemeBranding)
    customCSS: str | None = None

    model_config = {"extra": "allow"}


class ThemeCreate(BaseModel):
    """Sistema de cascada visual:
    - organizacion_id solo: tema nivel cliente (hereda plataforma).
    - chatbot_id: tema nivel chatbot (hereda cliente → plataforma).
    - ninguno: tema de plataforma (solo Admin).
    """
    name: str = Field(..., min_length=1, max_length=100)
    organizacion_id: str | None = None
    chatbot_id: str | None = None
    config: ThemeConfig


class ThemeUpdate(BaseModel):
    config: ThemeConfig


class ThemeResponse(BaseModel):
    id: str
    name: str
    organizacion_id: str | None
    chatbot_id: str | None
    config: dict
    is_default: bool
    created_at: str
    updated_at: str


class ChatbotThemeOut(BaseModel):
    """Solo `config` -- sin owner_id/theme_id/name: ver `get_theme_for_chatbot`."""

    config: dict = Field(default_factory=dict)


class TemaResueltoOut(BaseModel):
    """La cascada ya resuelta para quien pregunta. Misma disciplina que
    `ChatbotThemeOut`: solo `config`, nunca el id ni el nombre del tema ni la
    organización a la que pertenece."""

    config: dict = Field(default_factory=dict)


class LogoSubidoOut(BaseModel):
    logoUrl: str
    logoAlt: str | None = None


# ============================================
# Almacenamiento en base de datos (SEC.8.6)
# ============================================
#
# Antes eran ficheros `.json` bajo `data/themes`, una ruta relativa al directorio de
# trabajo. En Cloud Run el contenedor es efímero y hay varias instancias, así que el tema
# creado en una no existía para las demás y desaparecía al reciclarse — arrastrando al
# widget, que resuelve su contenido desde el puntero `theme_config`.
#
# La validación de forma del identificador se conserva: ya no protege una ruta, pero un
# `theme_id` que no es un UUID no puede corresponder a ningún tema, y rechazarlo antes de
# consultar es más claro que un 404 desde la capa de datos.

_ID_DE_TEMA = re.compile(r"^[a-z0-9-]{1,64}$")


def _assert_id_de_tema(theme_id: str) -> uuid.UUID:
    if not _ID_DE_TEMA.match(theme_id or ""):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Identificador de tema inválido",
        )
    try:
        return uuid.UUID(theme_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Identificador de tema inválido",
        ) from None


def _a_dict(tema: HubTheme) -> dict:
    """La forma que ya devolvía el router, para no tocar el contrato de la API."""
    return {
        "id": str(tema.id),
        "name": tema.name,
        # Cadenas y no UUID: es lo que declara `ThemeResponse` y con lo que comparan los
        # filtros del listado, que reciben el id por query.
        "organizacion_id": str(tema.organizacion_id) if tema.organizacion_id else None,
        "chatbot_id": str(tema.chatbot_id) if tema.chatbot_id else None,
        "config": tema.config or {},
        "is_default": tema.is_default,
        "created_at": tema.created_at.isoformat() if tema.created_at else None,
        "updated_at": tema.updated_at.isoformat() if tema.updated_at else None,
        "created_by": tema.created_by,
    }


async def _load_theme(session, theme_id: str) -> dict | None:
    tema = await session.get(HubTheme, _assert_id_de_tema(theme_id))
    return _a_dict(tema) if tema is not None else None


async def _list_themes(session) -> list[dict]:
    filas = (await session.execute(select(HubTheme))).scalars().all()
    return [_a_dict(t) for t in filas]


def _fusionar(base: dict, encima: dict) -> dict:
    """Fusión en profundidad: la cascada añade, no reemplaza.

    Con un reemplazo plano, una organización que solo quiere poner su logotipo tendría
    que volver a declarar la paleta entera para no perderla — y en cuanto la plataforma
    cambiara un color, el suyo se quedaría congelado sin que nadie lo notara.
    """
    resultado = dict(base)
    for clave, valor in encima.items():
        anterior = resultado.get(clave)
        if isinstance(anterior, dict) and isinstance(valor, dict):
            resultado[clave] = _fusionar(anterior, valor)
        elif valor is not None:
            resultado[clave] = valor
    return resultado


async def _tema_mas_reciente(session, *, organizacion_id: uuid.UUID | None) -> HubTheme | None:
    """El tema de un nivel de la cascada: plataforma si `organizacion_id` es `None`.

    `chatbot_id IS NULL` porque el tema de un asistente concreto no entra en la cascada
    del panel: ese lo resuelve `get_theme_for_chatbot` para el widget.

    Se ordena por `updated_at` en vez de mirar `is_default`: los temas predefinidos
    (`is_default`) y el que cree un superadministrador para la plataforma ocupan el mismo
    nivel, y el criterio intuitivo es que gane el último configurado.
    """
    consulta = (
        select(HubTheme)
        .where(HubTheme.chatbot_id.is_(None))
        .order_by(HubTheme.updated_at.desc())
        .limit(1)
    )
    if organizacion_id is None:
        consulta = consulta.where(HubTheme.organizacion_id.is_(None))
    else:
        consulta = consulta.where(HubTheme.organizacion_id == organizacion_id)
    return (await session.execute(consulta)).scalars().first()


def _clave_del_logo(theme_id: uuid.UUID | str) -> str:
    """Clave de almacenamiento del logotipo.

    Sin extensión a propósito: el tipo real se guarda en `branding.logoContentType`, así
    que servirlo no depende de adivinar el sufijo ni de que el nombre que puso quien subió
    el fichero diga la verdad.
    """
    return f"branding/{theme_id}/logo"


# ============================================
# Endpoints
# ============================================

@router.get("/presets")
async def get_preset_themes() -> list[dict]:
    """Obtiene los temas predefinidos (no requiere auth)."""
    return [
        {"name": "default", "label": "Predeterminado"},
        {"name": "dark", "label": "Oscuro"},
        {"name": "university", "label": "Universitario"},
        {"name": "high-contrast", "label": "Alto Contraste"},
    ]


@router.get("/defaults", response_model=TemaResueltoOut)
async def get_theme_defaults(
    _: UserInfo = Depends(_require_admin),
    _modulo=_de_plataforma,
) -> TemaResueltoOut:
    """Los valores por omisión del contrato, para que la pantalla sepa **qué campos existen**.

    Lo destapó la verificación en navegador de PLAT.6: en el nivel de plataforma de una
    instalación recién levantada no hay tema propio ni nivel padre del que heredar, así que la
    pantalla iteraba un conjunto vacío y no ofrecía ni un campo — justo en el estado en el que
    alguien entra por primera vez a poner los colores de su institución.

    La alternativa era escribir la lista de campos en el frontend, que es lo que PLAT.6 prohíbe:
    se desincroniza del contrato en cuanto se añade un color. Aquí la lista **es** el modelo, así
    que añadir un campo a `ThemeColors` lo hace aparecer en la pantalla sin tocar TypeScript.

    Va antes de `/{theme_id}` porque si no, «defaults» se leería como un identificador.
    """
    return TemaResueltoOut(config=ThemeConfig(name="defaults").model_dump())


@router.get("", response_model=list[ThemeResponse])
async def get_themes(
    organizacion_id: str | None = None,
    chatbot_id: str | None = None,
    user: UserInfo = Depends(_require_admin),
    session: AsyncSession = Depends(get_async_session),
    _modulo=_de_plataforma,
) -> list[dict]:
    """Lista los temas disponibles para el partner.

    Cascada de resolución: plataforma (defaults) → cliente → chatbot.
    """
    themes = await _list_themes(session)
    # SEC.2: el listado se acota a lo que el principal gestiona. Los temas de
    # plataforma (`is_default`) los ve todo el mundo: son la base de la cascada.
    themes = [
        t for t in themes
        if t.get("is_default") or puede_acceder(user, t.get("organizacion_id"))
    ]
    if chatbot_id:
        themes = [
            t for t in themes
            if t.get("chatbot_id") == chatbot_id
            or t.get("organizacion_id") == organizacion_id
            or t.get("is_default")
        ]
    elif organizacion_id:
        themes = [t for t in themes if t.get("organizacion_id") == organizacion_id or t.get("is_default")]
    return themes


@router.get("/for-chatbot/{chatbot_id}", response_model=ChatbotThemeOut)
async def get_theme_for_chatbot(
    chatbot_id: uuid.UUID,
    http_request: Request,
    user: UserInfo | None = Depends(get_current_user_optional),
    session: AsyncSession = Depends(get_async_session),
) -> ChatbotThemeOut:
    """Tema resuelto de un chatbot, para pintar el widget público.

    SEC.5 cerró `GET /{theme_id}` porque un tema lleva `organizacion_id`: servido sin más
    era un censo de qué organizaciones existen. Este endpoint no reabre ese hueco -- solo
    devuelve `config` (colores/tipografía), nunca el `theme_id`, el `organizacion_id` ni el
    nombre del tema -- y exige el mismo acceso que conversar con el chatbot (SEC.2.1): quien
    no podría abrir el chat tampoco ve de qué color lo pintarían.
    """
    chatbot = await session.get(HubChatbot, chatbot_id)
    if chatbot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chatbot not found")

    # SEC.8.5: dos vías, y la diferencia la marca `via`. Con sesión decide la identidad;
    # con credencial de sitio no hay identidad ninguna, así que `assert_chatbot_access`
    # solo deja pasar `public_anon`. Antes el widget mandaba un Bearer privilegiado por
    # esta misma ruta, que es lo que se viene a quitar.
    clave = await resolver_widget_key(session, http_request.headers.get(CABECERA_WIDGET))
    if clave is not None and clave.chatbot_id == chatbot_id:
        assert_chatbot_access(None, chatbot, via=VIA_WIDGET)
    else:
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
            )
        actor = resolve_effective_actor(http_request, user)
        assert_chatbot_access(actor, chatbot, via="session")

    # **Los tres niveles, no solo el del asistente.** Antes devolvía el tema apuntado tal
    # cual: mientras todo se almacenaba completo no se notaba, pero un tema de asistente que
    # solo pusiera un color ya servía al widget ese color y nada más — ni la paleta de su
    # organización ni la de la plataforma. Con el almacenamiento disperso que exige la cascada
    # (ver `create_theme`), eso pasaría de rareza a norma.
    config: dict = {}
    plataforma = await _tema_mas_reciente(session, organizacion_id=None)
    if plataforma is not None:
        config = _fusionar(config, plataforma.config or {})
    if chatbot.organizacion_id is not None:
        de_la_organizacion = await _tema_mas_reciente(
            session, organizacion_id=chatbot.organizacion_id
        )
        if de_la_organizacion is not None:
            config = _fusionar(config, de_la_organizacion.config or {})

    theme_id = (chatbot.theme_config or {}).get("theme_id")
    if theme_id:
        theme = await _load_theme(session, theme_id)
        if theme:
            config = _fusionar(config, theme.get("config", {}))
    return ChatbotThemeOut(config=config)


@router.get("/resolved", response_model=TemaResueltoOut)
async def get_resolved_theme(
    organizacion: uuid.UUID | None = None,
    user: UserInfo = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> TemaResueltoOut:
    """La cascada visual resuelta para quien pregunta: plataforma → organización.

    Es lo que consume el panel de administración para pintar su cabecera. Antes no
    consumía nada: el logotipo estaba importado como código, así que el panel llevaba la
    marca de una institución concreta en cualquier despliegue.

    **Va registrado antes de `/{theme_id}`.** FastAPI resuelve por orden de registro y
    `_assert_id_de_tema` rechaza lo que no sea un UUID: al revés, esta ruta contestaría
    «Identificador de tema inválido» y el fallo parecería del cliente.

    La organización se toma del token y solo cuando es **una sola**. Con varias no hay
    forma de saber cuál de ellas es «la casa» de quien mira, y en un superadministrador la
    lista vacía significa «todas» (ver `UserInfo.organizacion_ids`): en los dos casos se
    responde con la marca de la plataforma, que es la respuesta honesta.
    """
    plataforma = await _tema_mas_reciente(session, organizacion_id=None)
    config: dict = dict(plataforma.config or {}) if plataforma is not None else {}

    organizacion_id: uuid.UUID | None = None

    if organizacion is not None:
        # REV.12 — la organización que se está mirando, y no la del token.
        #
        # El usuario configuró el logotipo de la UJI y no lo veía, y preguntó si tenía que
        # reiniciar. No: la rama de abajo funde el nivel de organización sólo cuando quien
        # pregunta pertenece a **una sola**, y en un superadministrador la lista vacía significa
        # «todas». Era una decisión razonada —con varias no había forma de saber cuál es «su
        # casa»— y lo que ha cambiado es que ahora sí la hay: REV.10 puso una organización
        # elegida en la cabecera del panel.
        #
        # **Se comprueba el acceso y se responde 403**, en vez de caer a la marca de
        # plataforma: devolver algo distinto de lo pedido escondería el fallo de permisos, y
        # parecería que esa organización no tiene marca cuando lo que pasa es que no se puede
        # mirar.
        assert_org_access(user, organizacion)
        organizacion_id = organizacion
    elif len(user.organizacion_ids) == 1:
        try:
            organizacion_id = uuid.UUID(user.organizacion_ids[0])
        except ValueError:
            organizacion_id = None

    if organizacion_id is not None:
        propio = await _tema_mas_reciente(session, organizacion_id=organizacion_id)
        if propio is not None:
            config = _fusionar(config, propio.config or {})

    return TemaResueltoOut(config=config)


@router.get("/{theme_id}", response_model=ThemeResponse)
async def get_theme(
    theme_id: str,
    user: UserInfo = Depends(_require_admin),
    session: AsyncSession = Depends(get_async_session),
    _modulo=_de_plataforma,
) -> dict:
    """Obtiene un tema específico por ID.

    SEC.5: hasta aquí era **público**. Un tema no es un secreto de estado, pero lleva los
    colores, el logotipo y el nombre de la organización a la que pertenece, así que la lista
    de temas es un censo de clientes servido sin pedir nada.

    Los temas de plataforma (`is_default`) los ve cualquier administrador: son la base de la
    cascada y no pertenecen a nadie. Los de una organización, solo quien la gestiona.
    """
    theme = await _load_theme(session, theme_id)
    if not theme:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Theme {theme_id} not found")
    if not theme.get("is_default") and theme.get("organizacion_id"):
        assert_org_access(user, theme["organizacion_id"])
    return theme


@router.post("", response_model=ThemeResponse, status_code=status.HTTP_201_CREATED)
async def create_theme(
    data: ThemeCreate,
    user: UserInfo = Depends(_require_admin),
    session: AsyncSession = Depends(get_async_session),
    _modulo=_de_plataforma,
) -> dict:
    """Crea un nuevo tema para un cliente o chatbot del partner."""
    # SEC.2: la organización viene del CUERPO de la petición, así que sin esto un admin
    # podía crear un tema en la organización que escribiera. Se comprueba contra el
    # token: el cliente propone, el token dispone.
    #
    # Sin organización, el tema es **de plataforma** y lo ven todas: eso es un superadmin.
    # Antes de SEC.2 cualquier admin podía crear uno, y un tema de plataforma se cuela en la
    # cascada de todas las organizaciones.
    if data.organizacion_id is None:
        if not user.is_superadmin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Un tema sin organización es de plataforma y lo hereda todo el mundo: "
                    "solo un superadministrador puede crearlo. Indica `organizacion_id`."
                ),
            )
    else:
        assert_org_access(user, data.organizacion_id)
    ahora = datetime.now(timezone.utc)
    tema = HubTheme(
        id=uuid.uuid4(),
        name=data.name,
        organizacion_id=uuid.UUID(data.organizacion_id) if data.organizacion_id else None,
        chatbot_id=uuid.UUID(data.chatbot_id) if data.chatbot_id else None,
        # `exclude_unset` y no `model_dump()` a secas: con los valores por omisión del
        # contrato materializados, el primer guardado de una organización se llevaba los
        # dieciséis colores de la plataforma como valores **propios**, y a partir de ahí un
        # cambio en la plataforma ya no le llegaba. La cascada quedaba de adorno. Lo destapó
        # la verificación en navegador de PLAT.6, no un test unitario: hacía falta seguir la
        # secuencia entera —crear el tema y luego cambiar el de arriba— para verlo.
        config=data.config.model_dump(exclude_unset=True),
        is_default=False,
        created_by=user.user_id,
        # Explícitas y no delegadas al default de la columna: el objeto queda completo
        # antes del INSERT, así que la respuesta no depende de que el `refresh` recargue.
        created_at=ahora,
        updated_at=ahora,
    )
    session.add(tema)
    await session.commit()
    await session.refresh(tema)
    return _a_dict(tema)


@router.put("/{theme_id}", response_model=ThemeResponse)
async def update_theme(
    theme_id: str,
    data: ThemeUpdate,
    user: UserInfo = Depends(_require_superadmin),
    session: AsyncSession = Depends(get_async_session),
    _modulo=_de_plataforma,
) -> dict:
    """Actualiza un tema existente."""
    tema = await session.get(HubTheme, _assert_id_de_tema(theme_id))
    if tema is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Theme {theme_id} not found")
    if tema.is_default:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot modify default themes")
    # Mismo motivo que en el alta: sin `exclude_unset`, el segundo guardado volvería a
    # congelar la paleta que el primero dejó heredable.
    tema.config = data.config.model_dump(exclude_unset=True)
    tema.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(tema)
    return _a_dict(tema)


@router.delete("/{theme_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_theme(
    theme_id: str,
    user: UserInfo = Depends(_require_superadmin),
    session: AsyncSession = Depends(get_async_session),
    _modulo=_de_plataforma,
) -> None:
    """Elimina un tema personalizado."""
    tema = await session.get(HubTheme, _assert_id_de_tema(theme_id))
    if tema is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Theme {theme_id} not found")
    if tema.is_default:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete default themes")
    await session.delete(tema)
    await session.commit()


@router.post("/{theme_id}/apply/{chatbot_id}")
async def apply_theme_to_chatbot(
    theme_id: str,
    chatbot_id: uuid.UUID,
    user: UserInfo = Depends(_require_superadmin),
    session: AsyncSession = Depends(get_async_session),
    _modulo=_de_plataforma,
) -> dict:
    """Aplica un tema a un chatbot específico.

    `HubChatbot.theme_config` no llevaba lector ni escritor en ningún sitio: se reutiliza
    como puntero (`{"theme_id": ...}`) a la fila de `hub_themes`, en vez de duplicar la
    configuración de colores en dos sitios. `get_theme_for_chatbot` es quien lo resuelve.
    """
    theme = await _load_theme(session, theme_id)
    if not theme:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Theme {theme_id} not found")
    chatbot = await session.get(HubChatbot, chatbot_id)
    if not chatbot:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chatbot not found")
    chatbot.theme_config = {"theme_id": theme_id}
    await session.commit()
    return {"message": f"Theme {theme_id} applied to chatbot {chatbot_id}", "theme_name": theme["name"]}


# ============================================
# La marca de la institución
# ============================================


@router.post("/{theme_id}/logo", response_model=LogoSubidoOut)
async def upload_theme_logo(
    theme_id: str,
    http_request: Request,
    file: UploadFile = File(...),
    logoAlt: str | None = Form(None),
    user: UserInfo = Depends(_require_admin),
    session: AsyncSession = Depends(get_async_session),
    storage: StorageService = Depends(get_storage_service),
    _modulo=_de_plataforma,
) -> LogoSubidoOut:
    """Sube el logotipo de un tema y lo deja apuntado en su `config`.

    El fichero va por `StorageService` y no al disco: la regla de portabilidad del
    proyecto, y además el contenedor de producción es reemplazable.

    La validación es la de SEC.6 (`validate_upload`), que mira extensión y **firma real**
    —el `content_type` del multipart lo elige quien sube— y corta la lectura al pasarse de
    tamaño en vez de tragarse el fichero para luego rechazarlo.
    """
    tema = await session.get(HubTheme, _assert_id_de_tema(theme_id))
    if tema is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Theme {theme_id} not found"
        )

    # Mismo criterio que `create_theme`: un tema sin organización es de plataforma y lo
    # hereda todo el mundo, así que su marca la pone un superadministrador.
    if tema.organizacion_id is None:
        if not user.is_superadmin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "La marca de un tema de plataforma la hereda todo el mundo: "
                    "solo un superadministrador puede cambiarla."
                ),
            )
    else:
        assert_org_access(user, str(tema.organizacion_id))

    # Los temas predefinidos son la base de estilo que comparten todas las
    # organizaciones, igual que en `update_theme`: la marca va en un tema propio.
    if tema.is_default:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot modify default themes",
        )

    buffer = await validate_upload(file, kind=UploadKind.IMAGE, max_bytes=_MAX_LOGO_BYTES)
    contenido = buffer.read()
    buffer.close()

    tipo = tipo_de_imagen(contenido)
    if tipo is None:  # pragma: no cover - `validate_upload` ya lo habría rechazado
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="El contenido no corresponde a una imagen admitida.",
        )

    await storage.put(_clave_del_logo(tema.id), contenido)

    # Ruta relativa y calculada, no interpolada: un `<img src>` con ruta relativa funciona
    # detrás de cualquier proxy, y `url_path_for` la deriva del prefijo real de montaje.
    url = http_request.app.url_path_for("get_theme_logo", theme_id=str(tema.id))
    branding = dict((tema.config or {}).get("branding") or {})
    branding.update(
        {
            "logoUrl": str(url),
            "logoContentType": tipo,
            **({"logoAlt": logoAlt} if logoAlt is not None else {}),
        }
    )
    # Reasignación completa: mutar el dict en sitio no marca la columna JSONB como sucia
    # y el UPDATE no llegaría a salir.
    tema.config = {**(tema.config or {}), "branding": branding}
    tema.updated_at = datetime.now(timezone.utc)
    await session.commit()

    return LogoSubidoOut(logoUrl=str(url), logoAlt=branding.get("logoAlt"))


@router.get("/{theme_id}/logo")
async def get_theme_logo(
    theme_id: str,
    session: AsyncSession = Depends(get_async_session),
    storage: StorageService = Depends(get_storage_service),
) -> Response:
    """Sirve el logotipo de un tema. **Sin autenticación, y es deliberado.**

    Un `<img src>` no manda la cabecera `Authorization`, así que exigirla convertiría la
    marca en un icono roto —y en el widget público no hay sesión ninguna que exigir—. No
    reabre el hueco que cerró SEC.5: devuelve los bytes de una imagen y nada más, sin el
    nombre del tema, sin la organización a la que pertenece y sin forma de enumerar cuáles
    existen, porque la clave es el UUID del tema.
    """
    tema = await session.get(HubTheme, _assert_id_de_tema(theme_id))
    if tema is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Theme {theme_id} not found"
        )

    branding = (tema.config or {}).get("branding") or {}
    if not branding.get("logoUrl"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Este tema no tiene logotipo"
        )

    try:
        contenido = await storage.get(_clave_del_logo(tema.id))
    except FileNotFoundError:
        # El puntero está en la configuración y el objeto no: es el mismo fallo que SEC.8.6
        # arregló con los temas en ficheros, así que se dice como un 404 y no como un 500.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Este tema no tiene logotipo"
        ) from None

    # El tipo sale de los bytes, no de `branding.logoContentType`: ese campo llega en el cuerpo
    # de la edición del tema, y usarlo como tipo de una respuesta pública dejaba servir un PNG
    # con HTML detrás como `text/html` desde el origen de la API. Lo que no es PNG ni JPEG —los
    # dos formatos que admite la subida— no se sirve.
    from server.app.core.uploads import tipo_de_imagen

    tipo = tipo_de_imagen(contenido)
    if tipo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Este tema no tiene logotipo"
        )
    return Response(
        content=contenido,
        media_type=tipo,
        headers={"Cache-Control": "public, max-age=300"},
    )
