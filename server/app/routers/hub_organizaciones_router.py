"""CRUD de organizaciones del Hub.

Deploy: cloud
Módulo: plataforma — con dos excepciones que **no** son un descuido (PLAT.5).

`require_module` va **por endpoint** y no a nivel de router, porque dos cosas de aquí las
consume otro módulo:

- **Leer la lista** de organizaciones la necesitan el selector de `ChatbotsPage` y el de la
  pantalla de valores por defecto, que viven en el módulo Chatbots. Administración de
  plataforma es **crear, renombrar y borrar** una organización, no leer las que gestionas; SEC.2
  ya acota la lista a las tuyas.
- **Los valores por defecto de RAG** son configuración del módulo Chatbots aplicada a una
  organización (PLAT.3), así que exigen `chatbots` y no `plataforma`. Su pantalla vive en
  `/hub`, que es coherente.
"""

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy import func, select, delete as sql_delete

from server.app.api.deps import require_module, require_role, require_scopes
from server.app.core.auth.models import UserInfo
from server.app.core.auth.tenancy import assert_org_access, scope_query_to_orgs
from server.app.modules.agents_hub.database.connection import get_async_session
from server.app.modules.agents_hub.database.config_models import HubChatbot, HubOrganizacion
from server.app.modules.agents_hub.database.operational_models import (
    HubAgenteUnidad,
    HubLexiconPair,
    HubWebSite,
)
from server.app.core.storage import StorageService, get_storage_service
from server.app.modules.agents_hub.services.corpus_purge import (
    borrar_fuentes_del_chatbot,
    purgar_corpus_del_chatbot,
)
from server.app.modules.redaccion.database.models import (
    HubFuncion,
    HubFuncionArtefacto,
    HubReportTemplate,
    HubWorkspace,
)
from server.app.modules.agents_hub.agent.public_graphs.validacion import (
    validar_estrategias,
    validar_modo,
    validar_perfil,
)

router = APIRouter(prefix="/hub/organizaciones", tags=["hub-organizaciones"])

_require_admin = require_role("superadmin", "admin")
# SEC.9.6 — dar de alta una organización es un acto de la plataforma: fija `partner_id`, que no
# se puede derivar del token porque ROL.1 retiró la dimensión de *partner* del principal.
_require_superadmin = require_role("superadmin")
#: Administrar la plataforma: crear, renombrar y borrar organizaciones.
logger = logging.getLogger(__name__)

#: #252 — lo que una organización tiene sin clave foránea y que, mientras exista, impide borrarla.
#: Borrarlo en cascada sería irreversible y alcanzaría ficheros del almacenamiento; para retirar una
#: organización con actividad está desactivarla (decisión del usuario, 2026-10-10). **Fuera, a
#: propósito, la traza**: el registro de actividad y los manifiestos cuentan lo que pasó, como las
#: interacciones, y no impiden nada. Los chatbots tampoco: cascadean y su corpus se purga.
LO_QUE_BLOQUEA_EL_BORRADO = (
    ("sitios", HubWebSite),
    ("informes", HubWorkspace),
    ("plantillas", HubReportTemplate),
    ("funciones", HubFuncion),
    ("artefactos", HubFuncionArtefacto),
    ("agentes", HubAgenteUnidad),
    ("pares_lexicos", HubLexiconPair),
)


async def _lo_que_le_queda(session, organizacion_id: uuid.UUID) -> dict[str, int]:
    """Cuánto le queda de cada cosa que bloquea el borrado; sólo lo que no es cero."""
    pendiente: dict[str, int] = {}
    for nombre, modelo in LO_QUE_BLOQUEA_EL_BORRADO:
        cuantos = (
            await session.execute(
                select(func.count()).select_from(modelo).where(
                    modelo.organizacion_id == organizacion_id
                )
            )
        ).scalar_one()
        if cuantos:
            pendiente[nombre] = int(cuantos)
    return pendiente


_de_plataforma = Depends(require_module("plataforma"))
#: Configuración del módulo Chatbots aplicada a una organización (PLAT.3).
_de_chatbots = Depends(require_module("chatbots"))


class OrganizacionRead(BaseModel):
    """La **identidad** del inquilino, y nada más (PLAT.3).

    Llevaba también catorce `default_*` de configuración de RAG. Por eso la pantalla acabó
    bajo el módulo Chatbots: la mayoría de sus campos sí eran de Chatbots. Ahora esos viven en
    `/{organizacion_id}/valores-por-defecto`, que es donde pertenecen.

    `theme_config` salió de aquí en **PLAT.7**, una vez PLAT.6 le dio sustituto: era una copia
    JSONB que no leía nadie —la cascada resuelve desde `hub_themes`— con un `<textarea>` a la
    vista que sí se veía. La identidad visual se configura en `/plataforma/identidad-visual`.
    """

    id: uuid.UUID
    name: str
    partner_id: str
    is_active: bool
    chatbot_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class OrganizacionCreate(BaseModel):
    """El alta de un inquilino: su identidad.

    Los `default_*` de RAG salieron de aquí y **no se pierden**: las columnas del modelo
    declaran exactamente los mismos valores por defecto que declaraba este DTO
    (`PUBLIC_KB_RICH`, `RAG`, `prefer`, 0.6, 2, 0.0, False, `generic`, y `None` en los
    heredables). Dar de alta una organización sigue dejándola con la misma configuración; lo
    que cambia es que ajustarla es otra pantalla y otra llamada.
    """

    name: str
    partner_id: str
    is_active: bool = True

    model_config = {"extra": "forbid"}


class OrganizacionUpdate(BaseModel):
    """Cambios sobre la identidad. `extra="forbid"` a propósito.

    Mandar aquí un campo de RAG es un error de quien llama, y decirlo con un 422 es mejor que
    ignorarlo: ignorado, quien lo mandó cree que se guardó.
    """

    name: str | None = None
    partner_id: str | None = None
    is_active: bool | None = None

    model_config = {"extra": "forbid"}


class ValoresPorDefectoRead(BaseModel):
    """Los valores por defecto de RAG de una organización.

    Son configuración del **módulo Chatbots** aplicada a una organización, no identidad de la
    organización: el perfil de grafo, el modo de recuperación, el troceado o el reranker no
    dicen nada de quién es el inquilino.
    """

    default_public_graph_profile: str
    default_retrieval_mode: str
    default_estrategias: dict[str, str] | None = None
    default_language_mode: str
    default_quality_threshold: float
    default_min_retrieval_results: int
    default_min_retrieval_score: float
    default_reranker_enabled: bool
    default_answer_template: str
    # VIS.2: None = heredar el default de plataforma (128.000 tokens)
    default_context_token_budget: int | None
    # RAG.8: troceado. None = heredar (1000 / 100 / 'structural')
    default_chunk_size: int | None
    default_chunk_overlap: int | None
    default_chunking_strategy: str | None
    # RAG.10: None = heredar el default de plataforma (False)
    default_query_rewriting_enabled: bool | None
    rewrite_llm_config_id: uuid.UUID | None

    model_config = {"from_attributes": True}


class ValoresPorDefectoUpdate(BaseModel):
    """Cambios sobre los valores por defecto.

    **Todos opcionales y `exclude_unset` al aplicarlos**, que es la diferencia que importa:
    seis de estos campos usan `None` con el significado «heredar el defecto de plataforma»
    —el presupuesto de contexto, los tres de troceado, la reescritura de consulta y el modelo
    que la hace—, así que hay que poder distinguir «no lo mandé» de «mándalo a null». El código
    anterior usaba `exclude_none`, que descartaba las dos cosas por igual: una vez fijado un
    valor propio, volver a heredar era imposible por API.
    """

    default_public_graph_profile: str | None = None
    default_retrieval_mode: str | None = None
    # PLG.2 — defectos de estrategia de la organizacion. Se fusionan CLAVE A CLAVE con los
    # del chatbot: fijar `merge` aqui no pisa el `template` que el chatbot haya elegido.
    default_estrategias: dict[str, str] | None = None
    default_language_mode: str | None = None
    default_quality_threshold: float | None = None
    default_min_retrieval_results: int | None = None
    default_min_retrieval_score: float | None = None
    default_reranker_enabled: bool | None = None
    default_answer_template: str | None = None
    default_context_token_budget: int | None = None
    default_chunk_size: int | None = None
    default_chunk_overlap: int | None = None
    default_chunking_strategy: str | None = None
    default_query_rewriting_enabled: bool | None = None
    rewrite_llm_config_id: uuid.UUID | None = None

    model_config = {"extra": "forbid"}

    # LANG.1 — `default_language_mode` era texto libre, así que «castellano» se guardaba tal
    # cual y la factoría lo trataba como `prefer` **sin avisar a nadie**. La regla vive en
    # `core/language_mode.py` y no aquí: la comparten los dos routers y la factoría del grafo.
    @field_validator("default_language_mode")
    @classmethod
    def _modo_de_lengua_conocido(cls, valor):
        from server.app.core.language_mode import valida_language_mode

        return valida_language_mode(valor)


_count_sq = (
    select(func.count(HubChatbot.id))
    .where(HubChatbot.organizacion_id == HubOrganizacion.id)
    .correlate(HubOrganizacion)
    .scalar_subquery()
)


# #234 — con un token, `chatbots:read`: `create_chatbot` del MCP pide la organización, y el
# agente tiene que poder saber cuáles hay. Sigue acotado a las suyas (`scope_query_to_orgs`).
@router.get(
    "",
    response_model=list[OrganizacionRead],
    dependencies=[Depends(require_scopes("chatbots:read"))],
)
async def list_organizaciones(
    user: UserInfo = Depends(_require_admin),
    session=Depends(get_async_session),
):
    # SEC.8.1: la organización ES la entidad, así que se acota por su propia clave y no
    # por una columna `organizacion_id` que aquí no existe.
    consulta = scope_query_to_orgs(
        select(HubOrganizacion, _count_sq.label("chatbot_count")),
        user,
        HubOrganizacion,
        columna="id",
    ).order_by(HubOrganizacion.created_at.desc())
    rows = (await session.execute(consulta)).all()
    return [
        OrganizacionRead.model_validate(o).model_copy(update={"chatbot_count": count})
        for o, count in rows
    ]


@router.post("", response_model=OrganizacionRead, status_code=status.HTTP_201_CREATED)
async def create_organizacion(
    body: OrganizacionCreate,
    user: UserInfo = Depends(_require_admin),
    session=Depends(get_async_session),
    _modulo=_de_plataforma,
):
    """Da de alta una organización. El `partner_id` **lo pone el token**, no el cuerpo (SEC.9.6).

    `partner_id` no es un campo descriptivo: es el que decide **quién verá esta organización**.
    `_orgs_del_admin` (`auth_router`) resuelve el claim `organizacion_ids` de un administrador
    con `WHERE HubOrganizacion.partner_id == <su partner>`, así que aceptarlo del cuerpo dejaba
    a un administrador **plantar una organización dentro del ámbito de otro** — que a partir del
    siguiente inicio de sesión aparecería en el listado del otro como suya.
    """
    # El partner de un administrador **es** su `user_id`: así lo emite `login_admin`
    # (`user_id=admin.partner_id`). O sea que no hay que inventarle un claim ni consultar la
    # tabla: ya viaja en el token. El superadministrador sí puede decir de quién es, porque es
    # la autoridad de la instalación y es el flujo que describe MT.13.
    partner_id = body.partner_id if user.is_superadmin else user.user_id

    organizacion = HubOrganizacion(
        name=body.name,
        partner_id=partner_id,
        is_active=body.is_active,
    )
    session.add(organizacion)
    await session.commit()
    await session.refresh(organizacion)
    return OrganizacionRead.model_validate(organizacion).model_copy(
        update={"chatbot_count": 0}
    )


@router.patch("/{organizacion_id}", response_model=OrganizacionRead)
async def update_organizacion(
    organizacion_id: uuid.UUID,
    body: OrganizacionUpdate,
    user: UserInfo = Depends(_require_admin),
    session=Depends(get_async_session),
    _modulo=_de_plataforma,
):
    organizacion = await session.get(HubOrganizacion, organizacion_id)
    if not organizacion:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Organización not found"
        )
    assert_org_access(user, organizacion.id)

    # `exclude_unset` y no `exclude_none`: distingue «no lo mandé» de «mándalo a null».
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(organizacion, field, value)
    organizacion.updated_at = datetime.now(timezone.utc)

    await session.commit()
    await session.refresh(organizacion)
    return OrganizacionRead.model_validate(organizacion).model_copy(
        update={"chatbot_count": 0}
    )


@router.get(
    "/{organizacion_id}/valores-por-defecto", response_model=ValoresPorDefectoRead
)
async def get_valores_por_defecto(
    organizacion_id: uuid.UUID,
    user: UserInfo = Depends(_require_admin),
    session=Depends(get_async_session),
    _modulo=_de_chatbots,
):
    """Los valores por defecto de RAG de una organización (PLAT.3).

    Endpoint propio y no un bloque del anterior: así la pantalla de identidad no tiene que
    devolver catorce campos que no muestra, y la de Chatbots no tiene que mandar el nombre del
    inquilino para cambiar un umbral.
    """
    organizacion = await session.get(HubOrganizacion, organizacion_id)
    if not organizacion:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Organización not found"
        )
    assert_org_access(user, organizacion.id)
    return ValoresPorDefectoRead.model_validate(organizacion)


@router.patch(
    "/{organizacion_id}/valores-por-defecto", response_model=ValoresPorDefectoRead
)
async def update_valores_por_defecto(
    organizacion_id: uuid.UUID,
    body: ValoresPorDefectoUpdate,
    user: UserInfo = Depends(_require_admin),
    session=Depends(get_async_session),
    _modulo=_de_chatbots,
):
    """Cambia los valores por defecto, y **permite volver a heredar**.

    `exclude_unset` es el punto del ejercicio: con `exclude_none` un `null` explícito se
    descartaba igual que un campo omitido, así que los seis campos cuyo `None` significa
    «heredar el defecto de plataforma» se quedaban con su valor propio para siempre.
    """
    organizacion = await session.get(HubOrganizacion, organizacion_id)
    if not organizacion:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Organización not found"
        )
    assert_org_access(user, organizacion.id)

    # PLG.1: los defectos de organización se validan contra los registros vivos, igual que los
    # del chatbot. Si no, un perfil inventado aquí lo heredan TODOS sus chatbots y el fallo
    # aparece multiplicado y lejos de donde se escribió.
    validar_perfil(body.default_public_graph_profile, "default_public_graph_profile")
    validar_modo(body.default_retrieval_mode, "default_retrieval_mode")
    validar_estrategias(body.default_estrategias, "default_estrategias")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(organizacion, field, value)
    organizacion.updated_at = datetime.now(timezone.utc)

    await session.commit()
    await session.refresh(organizacion)
    return ValoresPorDefectoRead.model_validate(organizacion)


@router.delete("/{organizacion_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_organizacion(
    organizacion_id: uuid.UUID,
    user: UserInfo = Depends(_require_admin),
    session=Depends(get_async_session),
    _modulo=_de_plataforma,
    storage: StorageService = Depends(get_storage_service),
):
    organizacion = await session.get(HubOrganizacion, organizacion_id)
    if not organizacion:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Organización not found"
        )
    # El borrado arrastra los chatbots por CASCADE: sin esta línea, un admin destruye los
    # datos de otra administración con un solo DELETE.
    assert_org_access(user, organizacion.id)
    pendiente = await _lo_que_le_queda(session, organizacion_id)
    if pendiente:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ORGANIZACION_CON_DATOS",
                "message": "La organización todavía tiene datos; desactívala en vez de borrarla.",
                "pendiente": pendiente,
            },
        )
    # #252 — la cascada llega a los chatbots y no a su corpus, que no cuelga de ellos por clave
    # foránea. Mismo camino que `delete_chatbot` (PIL.2) y en la misma transacción: borrar la
    # organización dejaba documentos y embeddings sin dueño. Las interacciones se quedan, como
    # al borrar un chatbot.
    chatbots = (
        await session.execute(
            select(HubChatbot.id).where(HubChatbot.organizacion_id == organizacion_id)
        )
    ).scalars().all()
    documentos = fragmentos = trabajos = 0
    for chatbot_id in chatbots:
        retirado = await purgar_corpus_del_chatbot(session, chatbot_id)
        documentos += retirado.documentos
        fragmentos += retirado.fragmentos
        trabajos += retirado.trabajos
    await session.execute(
        sql_delete(HubOrganizacion).where(HubOrganizacion.id == organizacion_id)
    )
    await session.commit()
    for chatbot_id in chatbots:
        await borrar_fuentes_del_chatbot(storage, chatbot_id)
    logger.info(
        "Organización %s eliminada por %s; %d chatbots, corpus retirado: %d documentos, "
        "%d fragmentos, %d trabajos de ingesta",
        organizacion_id,
        user.email,
        len(chatbots),
        documentos,
        fragmentos,
        trabajos,
    )
