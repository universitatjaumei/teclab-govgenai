"""CRUD de chatbots del Hub + jerarquía router->hijos.

Deploy: cloud
Módulo: chatbots — ya lo declaraba a nivel de router.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete as sql_delete
from sqlalchemy import func
from sqlalchemy import select

from server.app.api.deps import require_module, require_role, require_scopes
from server.app.core.auth.models import UserInfo
from server.app.modules.agents_hub.agent.public_graphs.validacion import (
    validar_estrategias,
    validar_modo,
    validar_perfil,
)
from server.app.core.auth.tenancy import assert_org_access, scope_query_to_orgs
from server.app.modules.agents_hub.database.config_models import HubChatbot, HubLLMConfig
from server.app.modules.agents_hub.database.connection import get_async_session
from server.app.modules.agents_hub.database.operational_models import HubDocument
from server.app.modules.agents_hub.ingestion.watcher import IngestionWatcher
from server.app.modules.agents_hub.services.corpus_purge import purgar_corpus_del_chatbot
from server.app.modules.agents_hub.services.corpus_recalculator import recalculate_corpus
from server.app.modules.agents_hub.services.corpus_recommender import recommend_retrieval_mode
from server.app.modules.agents_hub.ingestion.watcher import (
    MODOS_QUE_BUSCAN_POR_FRAGMENTOS,
)
from server.app.modules.agents_hub.services.embedding_resolver import (
    resolve_embedding_service,
)
from server.app.modules.agents_hub.services.embedding_space import (
    EmbeddingSpaceMismatch,
    assert_embedding_space_matches,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/hub/chatbots", tags=["hub-chatbots"],
    # INF.7 — el modulo se exige a nivel de router: asi no se puede olvidar en un
    # endpoint nuevo del mismo fichero, que es como se abrieron los agujeros que SEC.8.1
    # tuvo que cerrar uno a uno.
    dependencies=[Depends(require_module("chatbots"))],
)

_require_admin = require_role("superadmin", "admin")


class DisponibilidadOut(BaseModel):
    """Estado derivado del chatbot (SEC.4.1). No se guarda: se calcula al pedirlo."""

    state: Literal["available", "expired", "not_yet_open", "budget_exhausted"]
    reason: str | None
    tokens_used: int
    total_token_budget: int | None


class ChatbotRead(BaseModel):
    id: uuid.UUID
    name: str
    organizacion_id: uuid.UUID
    llm_config_id: uuid.UUID
    system_prompt: str
    sources: list[str]
    is_active: bool
    retrieval_mode: str
    retrieval_top_k: int
    use_prompt_caching: bool
    cache_ttl: int
    kind: str
    parent_chatbot_id: uuid.UUID | None
    # SEC.2.1: para quién es este chatbot. Lo aplica `assert_chatbot_access`, nunca el
    # frontend: aquí viaja para poder mostrarlo y editarlo, no para decidir con ello.
    access_mode: Literal["public_anon", "authenticated", "restricted"]
    allowed_roles: list[str]
    allowed_saml_groups: list[str]
    # SEC.4.1: la ventana y el techo son configuración; `availability` es **derivado y de
    # solo lectura**. Lo calcula el servidor y el frontend lo pinta: recalcular la fecha en
    # el cliente sería tener dos máquinas de estado que se pueden contradecir.
    valid_from: datetime | None
    valid_until: datetime | None
    total_token_budget: int | None
    unavailable_message: str
    no_answer_message: str | None = None
    # SEC.4: los tres techos de consumo. NULL = heredar de la organizacion; 0 = sin limite.
    # `anon_ip_daily_token_quota` NO hereda: un chatbot publico y uno interno no comparten
    # criterio sobre lo que es razonable para un anonimo.
    #
    # Estaban en la base de datos y los aplicaba `core/quotas.py` desde SEC.4, pero **no los
    # exponia ni la API ni la interfaz**: solo se podian fijar por SQL, asi que en la practica
    # se quedaban en NULL. Para un chatbot `public_anon` eso significa sin limite por IP, que
    # es justo el sujeto para el que se construyo la cuenta.
    user_daily_token_quota: int | None = None
    chatbot_daily_token_quota: int | None = None
    anon_ip_daily_token_quota: int | None = None
    availability: "DisponibilidadOut | None" = None
    public_graph_profile: str
    language_mode: str
    quality_threshold: float
    min_retrieval_results: int
    min_retrieval_score: float
    reranker_enabled: bool
    answer_template: str
    # VIS.2: None = heredar de la organización y, en su defecto, del default de plataforma
    context_token_budget: int | None
    # RAG.8: parámetros de troceado. None = heredar. Cambiar `chunking_strategy` exige
    # recalcular el corpus para que surta efecto (POST /recalculate-corpus).
    chunk_size: int | None
    chunk_overlap: int | None
    chunking_strategy: Literal["structural", "parent_child"] | None
    # RAG.10: None = heredar. Un False no nulo pisaria a la organizacion.
    query_rewriting_enabled: bool | None
    # PLG.2 — lo que el chatbot tiene PUESTO, `{eje: nombre}`. Puede estar a medias: las
    # claves ausentes se heredan.
    estrategias: dict[str, str] | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ChatbotCreate(BaseModel):
    name: str
    organizacion_id: uuid.UUID
    llm_config_id: uuid.UUID
    system_prompt: str
    sources: list[str] = []
    is_active: bool = True
    retrieval_mode: str = "RAG"
    retrieval_top_k: int = 8
    use_prompt_caching: bool = False
    cache_ttl: int = 3600
    kind: str = "atomic"
    # SEC.2.1: se crea cerrado. Abrir un chatbot al público es una decisión explícita.
    access_mode: Literal["public_anon", "authenticated", "restricted"] = "authenticated"
    allowed_roles: list[str] = []
    allowed_saml_groups: list[str] = []
    # SEC.4.1: sin ventana ni techo por defecto. `availability` no se acepta al crear —es
    # derivado— y por eso no está aquí.
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    total_token_budget: int | None = None
    unavailable_message: str = ""
    no_answer_message: str | None = None
    user_daily_token_quota: int | None = None
    chatbot_daily_token_quota: int | None = None
    anon_ip_daily_token_quota: int | None = None
    public_graph_profile: str = "PUBLIC_KB_RICH"
    language_mode: str = "prefer"
    # RES.1: se compara contra el MEJOR fragmento, no contra la media. El texto va en el contrato
    # porque es lo que lee quien ajusta el número desde el panel, y el significado cambió.
    quality_threshold: float = Field(
        default=0.6,
        description=(
            "Nota mínima para responder. Se compara contra la puntuación del mejor fragmento "
            "recuperado: «¿tengo al menos una fuente buena?». Hasta el 2026-08-25 se comparaba "
            "contra la media de todos los fragmentos, así que con el mismo número el filtro es "
            "ahora más permisivo."
        ),
    )
    min_retrieval_results: int = 2
    min_retrieval_score: float = 0.0
    reranker_enabled: bool = False
    answer_template: str = "generic"
    context_token_budget: int | None = None
    chunk_size: int | None = None
    chunk_overlap: int | None = None
    chunking_strategy: Literal["structural", "parent_child"] | None = None
    query_rewriting_enabled: bool | None = None
    # PLG.2 — sobreescritura por eje. Clave ausente = hereda de la organizacion y, en su
    # defecto, de la composicion del perfil.
    estrategias: dict[str, str] | None = None

    # LANG.1 — `language_mode` era `String(20)` libre, así que «castellano» se guardaba tal cual
    # y la factoría lo trataba como `prefer` **sin avisar a nadie**. La regla vive en
    # `core/language_mode.py` y no aquí: la comparten los dos routers y la factoría del grafo.
    @field_validator("language_mode")
    @classmethod
    def _modo_de_lengua_conocido(cls, valor):
        from server.app.core.language_mode import valida_language_mode

        return valida_language_mode(valor)


class ChatbotUpdate(BaseModel):
    # FIX.3: un campo que el servidor no conoce es un **error**, no algo que se ignora.
    #
    # Por defecto Pydantic descarta lo que no reconoce, y eso convierte un desajuste de
    # versiones en el peor fallo posible: un 200 que no guarda nada. Pasó de verdad —un
    # servidor anterior a SEC.4.1 recibía `valid_until`, lo tiraba y contestaba «guardado»,
    # así que la fecha «no se guardaba» sin ningún error a la vista, ni en el navegador ni
    # en el log—. Con `forbid`, el mismo caso responde 422 diciendo qué campo sobra.
    model_config = {"extra": "forbid"}

    name: str | None = None
    # FIX.1: sin esto no había forma de cambiar el modelo de un chatbot. Cuando Google retiró
    # `gemini-2.0-flash` hubo que repuntarlo por SQL, porque el formulario hardcodeaba el id y
    # la API ni siquiera aceptaba el campo.
    llm_config_id: uuid.UUID | None = None
    system_prompt: str | None = None
    sources: list[str] | None = None
    is_active: bool | None = None
    retrieval_mode: str | None = None
    retrieval_top_k: int | None = None
    use_prompt_caching: bool | None = None
    cache_ttl: int | None = None
    kind: str | None = None
    parent_chatbot_id: uuid.UUID | None = None
    access_mode: Literal["public_anon", "authenticated", "restricted"] | None = None
    allowed_roles: list[str] | None = None
    allowed_saml_groups: list[str] | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    total_token_budget: int | None = None
    unavailable_message: str | None = None
    no_answer_message: str | None = None
    user_daily_token_quota: int | None = None
    chatbot_daily_token_quota: int | None = None
    anon_ip_daily_token_quota: int | None = None
    public_graph_profile: str | None = None
    language_mode: str | None = None
    quality_threshold: float | None = None
    min_retrieval_results: int | None = None
    min_retrieval_score: float | None = None
    reranker_enabled: bool | None = None
    answer_template: str | None = None
    context_token_budget: int | None = None
    chunk_size: int | None = None
    chunk_overlap: int | None = None
    chunking_strategy: Literal["structural", "parent_child"] | None = None
    query_rewriting_enabled: bool | None = None
    # PLG.2 — sobreescritura por eje. Clave ausente = hereda de la organizacion y, en su
    # defecto, de la composicion del perfil.
    estrategias: dict[str, str] | None = None

    # LANG.1 — `language_mode` era `String(20)` libre, así que «castellano» se guardaba tal cual
    # y la factoría lo trataba como `prefer` **sin avisar a nadie**. La regla vive en
    # `core/language_mode.py` y no aquí: la comparten los dos routers y la factoría del grafo.
    @field_validator("language_mode")
    @classmethod
    def _modo_de_lengua_conocido(cls, valor):
        from server.app.core.language_mode import valida_language_mode

        return valida_language_mode(valor)


class AssignChildIn(BaseModel):
    child_chatbot_id: uuid.UUID


class CorpusStatsOut(BaseModel):
    total_documents: int
    total_tokens: int
    by_language: dict[str, int]
    recommended_mode: str
    recommendation_reason: str


class RegenerateChunksOut(BaseModel):
    task_id: str
    message: str
    documents_processed: int
    chunks_created: int

class RecalculateCorpusOut(BaseModel):
    task_id: str
    message: str
    documents_queued: int
    chunks_created: int
    chunks_deleted: int


async def _get_chatbot_or_404(session, chatbot_id: uuid.UUID, principal=None) -> HubChatbot:
    """Único punto de lectura de un chatbot, y por eso el único sitio donde comprobar.

    SEC.2: `principal` es opcional por compatibilidad con las llamadas internas que no vienen
    de una petición, pero **todo endpoint debe pasarlo**. Hay un guardarraíl en
    `tests/api/test_tenant_isolation.py` que falla si aparece una segunda lectura directa de
    `HubChatbot` en este fichero, porque saltarse esta función es reabrir el hallazgo A2.
    """
    chatbot = await session.get(HubChatbot, chatbot_id)
    if not chatbot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Chatbot not found"
        )
    if principal is not None:
        assert_org_access(principal, chatbot.organizacion_id)
    return chatbot


async def _leer_con_disponibilidad(session, chatbot) -> ChatbotRead:
    """`ChatbotRead` con el estado derivado ya calculado (SEC.4.1).

    Se calcula en el servidor y viaja en el contrato: si el frontend comparase las fechas
    por su cuenta habría dos máquinas de estado —la suya y la del chat— y se contradirían
    en cuanto una de las dos cambiara.
    """
    from server.app.core.chatbot_availability import calcular_disponibilidad

    estado = await calcular_disponibilidad(session, chatbot)
    return ChatbotRead.model_validate(chatbot).model_copy(
        update={
            "availability": DisponibilidadOut(
                state=estado.state,
                reason=estado.reason,
                tokens_used=estado.tokens_used,
                total_token_budget=estado.total_token_budget,
            )
        }
    )


class EstrategiaOut(BaseModel):
    nombre: str
    descripcion: str | None = None
    #: `nucleo` o `paquete`. Que el panel pueda distinguirlas importa: una estrategia de un
    #: paquete desaparece si alguien lo desinstala, y quien la elige debería saberlo.
    origen: str
    distribucion: str | None = None


class PerfilOut(BaseModel):
    nombre: str
    #: False para los de `PERFILES_SIN_CONFIGURAR`: se ofrecen, pero no se pueden seleccionar.
    configurable: bool
    descripcion: str | None = None
    composicion: dict[str, str] | None = None


class ModoOut(BaseModel):
    nombre: str
    descripcion: str | None = None


class OpcionesDeGrafoOut(BaseModel):
    """Lo que el panel puede ofrecer **en esta instalación**.

    Existe porque desde PLG.1 la lista no se puede conocer en tiempo de compilación: depende de
    qué paquetes haya instalados. El frontend llevaba los cuatro nombres *hardcodeados* en tres
    ficheros, que además de violar la regla maestra de contrato era lo primero con lo que un
    perfil instalado se habría dado de bruces.
    """

    perfiles: list[PerfilOut]
    modos: list[ModoOut]
    estrategias: dict[str, list[EstrategiaOut]]
    #: Los ejes, en orden. El panel pinta un select por cada uno sin conocerlos de antemano.
    ejes: list[str]


def _primera_linea(objeto: object) -> str | None:
    """La descripción de una opción sale de su *docstring*, y es opcional a propósito.

    No se inventa i18n para nombres de terceros: si un paquete no documenta su estrategia, el
    panel enseña el nombre y ya. Traducir lo que no controlamos sería prometer una calidad que
    no podemos sostener.
    """
    doc = (getattr(objeto, "__doc__", None) or "").strip()
    return doc.splitlines()[0].strip() if doc else None


@router.get("/opciones-de-grafo", response_model=OpcionesDeGrafoOut)
async def opciones_de_grafo(user: UserInfo = Depends(_require_admin)):
    """Perfiles, modos y estrategias disponibles, con su origen.

    Acotado a admin/superadmin como el resto del router. No lleva datos de ninguna organización
    —es el catálogo de la instalación— pero enumerar qué paquetes hay instalados es información
    del despliegue, y ésa no es pública.
    """
    from server.app.modules.agents_hub.agent.public_graphs.core.graph_factory import (
        COMPOSICION_PUBLIC_KB_RICH,
        PERFILES_SIN_CONFIGURAR,
    )
    from server.app.modules.agents_hub.agent.public_graphs.registry import (
        get_profile,
        list_profiles,
    )
    from server.app.modules.agents_hub.agent.public_graphs.strategies.registry import (
        EjeDeEstrategia,
        get_strategy,
        list_strategies,
    )
    from server.app.modules.agents_hub.agent.public_graphs.strategies.retrieval_pipeline_factory import (
        list_modes,
    )

    perfiles = [
        PerfilOut(
            nombre=nombre,
            configurable=nombre not in PERFILES_SIN_CONFIGURAR,
            descripcion=_primera_linea(get_profile(nombre)),
            composicion=dict(COMPOSICION_PUBLIC_KB_RICH) if nombre == "PUBLIC_KB_RICH" else None,
        )
        for nombre in sorted(list_profiles())
    ]

    estrategias: dict[str, list[EstrategiaOut]] = {}
    for eje in EjeDeEstrategia:
        del_eje = []
        for nombre in list_strategies(eje):
            factoria = get_strategy(eje, nombre)
            modulo = getattr(factoria, "__module__", "") or ""
            # El origen se deduce del módulo: lo del núcleo vive bajo `server.app`. Es una
            # heurística y se dice; la alternativa —guardar la distribución al registrar— añade
            # estado al registro para un dato que sólo usa el panel.
            del_nucleo = modulo.startswith("server.app")
            del_eje.append(
                EstrategiaOut(
                    nombre=nombre,
                    descripcion=_primera_linea(factoria),
                    origen="nucleo" if del_nucleo else "paquete",
                    distribucion=None if del_nucleo else modulo.split(".")[0],
                )
            )
        estrategias[eje.value] = del_eje

    return OpcionesDeGrafoOut(
        perfiles=perfiles,
        modos=[ModoOut(nombre=m) for m in list_modes()],
        estrategias=estrategias,
        ejes=[e.value for e in EjeDeEstrategia],
    )


@router.get("", response_model=list[ChatbotRead], dependencies=[Depends(require_scopes("chatbots:read"))])
async def list_chatbots(
    organizacion_id: uuid.UUID | None = Query(default=None),
    user: UserInfo = Depends(_require_admin),
    session=Depends(get_async_session),
):
    """Los chatbots que este principal puede ver, opcionalmente los de una organización.

    **El filtro es la elección de la cabecera** (issue #11, MT.8). Desde REV.10 la organización
    se elige una vez en el panel, y hasta ahora esa elección no llegaba aquí: quien administra
    varias seguía viendo los chatbots de todas en cada desplegable. Casi ninguna pantalla lista
    «lo suyo» —listan chatbots para elegir uno y pedir después sus documentos, sus escenarios o
    sus interacciones—, así que el acotado aquí llega a casi todas.

    **Opcional a propósito**: hay consumidores que necesitan ver todos los que la tenencia
    permita, y convertirlo en obligatorio los rompería sin avisar.

    **Y el orden importa**: la tenencia primero, el filtro después. `scope_query_to_orgs` decide
    lo que se *puede* ver y no se negocia; el filtro sólo estrecha dentro de eso. Pedir una
    organización ajena no es una consulta legítima, así que es un 403 y no un listado vacío —lo
    segundo se leería como «esa organización no tiene chatbots». Es el mismo patrón que
    `list_sites` desde SEC.8.1.
    """
    # SEC.2: acotado en SQL y no en memoria. Filtrar despues de leer con LIMIT deja
    # fuera resultados propios y de todos modos trae los ajenos al proceso.
    consulta = scope_query_to_orgs(
        select(HubChatbot).order_by(HubChatbot.created_at.desc()), user, HubChatbot
    )
    if organizacion_id is not None:
        assert_org_access(user, organizacion_id)
        consulta = consulta.where(HubChatbot.organizacion_id == organizacion_id)
    result = await session.execute(consulta)
    return [
        await _leer_con_disponibilidad(session, chatbot)
        for chatbot in result.scalars().all()
    ]


@router.post(
    "",
    response_model=ChatbotRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_scopes("chatbots:write"))],
)
async def create_chatbot(
    body: ChatbotCreate,
    user: UserInfo = Depends(_require_admin),
    session=Depends(get_async_session),
):
    # SEC.2: no se puede crear un chatbot en una organizacion ajena. Va delante de la
    # comprobación de embeddings: a quien no gestiona la organización no se le contesta
    # con el estado del servicio de embeddings, que es información de la instalación.
    assert_org_access(user, body.organizacion_id)

    # PLG.1: perfil y modo se validan contra los registros VIVOS, no contra un `Literal` del
    # DTO. El `Literal` cerraba el vocabulario en el código —un modo de un paquete instalado no
    # habría pasado nunca— y el perfil no se validaba en absoluto, así que un valor inventado se
    # guardaba y el fallo salía en el primer mensaje del usuario, lejos del formulario.
    validar_perfil(body.public_graph_profile)
    validar_modo(body.retrieval_mode)
    validar_estrategias(body.estrategias)

    # RAG.9: fallar al crear es barato; fallar a mitad de una ingesta de miles de documentos
    # no. Sólo para los modos que CONSULTAN el índice vectorial (ACT.8): a `MD_LONG_CONTEXT`,
    # que inyecta documentos enteros, exigirle un servicio de embeddings operativo sería
    # inventarle un requisito que no tiene.
    if body.retrieval_mode in MODOS_QUE_BUSCAN_POR_FRAGMENTOS:
        try:
            await resolve_embedding_service(session)
        except Exception as fallo:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "El servicio de embeddings configurado no está operativo, y un chatbot "
                    f"en modo RAG no puede ingerir nada sin él: {fallo}"
                ),
            ) from fallo

    chatbot = HubChatbot(
        organizacion_id=body.organizacion_id,
        llm_config_id=body.llm_config_id,
        name=body.name,
        system_prompt=body.system_prompt,
        sources=body.sources,
        is_active=body.is_active,
        retrieval_mode=body.retrieval_mode,
        retrieval_top_k=body.retrieval_top_k,
        use_prompt_caching=body.use_prompt_caching,
        cache_ttl=body.cache_ttl,
        kind=body.kind,
        access_mode=body.access_mode,
        allowed_roles=body.allowed_roles,
        allowed_saml_groups=body.allowed_saml_groups,
        valid_from=body.valid_from,
        valid_until=body.valid_until,
        total_token_budget=body.total_token_budget,
        unavailable_message=body.unavailable_message,
        no_answer_message=body.no_answer_message,
        user_daily_token_quota=body.user_daily_token_quota,
        chatbot_daily_token_quota=body.chatbot_daily_token_quota,
        anon_ip_daily_token_quota=body.anon_ip_daily_token_quota,
        public_graph_profile=body.public_graph_profile,
        language_mode=body.language_mode,
        quality_threshold=body.quality_threshold,
        min_retrieval_results=body.min_retrieval_results,
        min_retrieval_score=body.min_retrieval_score,
        reranker_enabled=body.reranker_enabled,
        answer_template=body.answer_template,
        context_token_budget=body.context_token_budget,
        chunk_size=body.chunk_size,
        chunk_overlap=body.chunk_overlap,
        chunking_strategy=body.chunking_strategy,
        query_rewriting_enabled=body.query_rewriting_enabled,
    )
    session.add(chatbot)
    await session.commit()
    await session.refresh(chatbot)
    return chatbot


@router.patch("/{chatbot_id}", response_model=ChatbotRead, dependencies=[Depends(require_scopes("chatbots:write"))])
async def update_chatbot(
    chatbot_id: uuid.UUID,
    body: ChatbotUpdate,
    user: UserInfo = Depends(_require_admin),
    session=Depends(get_async_session),
):
    chatbot = await _get_chatbot_or_404(session, chatbot_id, user)

    # PLG.1: mismo criterio que al crear. `None` pasa y significa «heredar», que es lo que
    # distingue este endpoint del de creación.
    validar_perfil(body.public_graph_profile)
    validar_modo(body.retrieval_mode)
    validar_estrategias(body.estrategias)

    payload = body.model_dump(exclude_none=True)

    # FIX.3: en la ventana de vigencia, `null` significa **quitar la fecha**, no «no tocar».
    # Con `exclude_none` a secas no había forma de volver a abrir un chatbot caducado desde
    # la API: se mandaba `valid_until: null`, el campo se descartaba y la fecha seguía ahí.
    #
    # `model_fields_set` distingue lo que el cliente **envió** de lo que simplemente no
    # venía, que es la diferencia que hace falta aquí y que `exclude_none` no puede ver. No
    # se cambia el criterio del resto de campos —donde `None` sí es «heredar»— porque ahí el
    # comportamiento actual es el correcto.
    for campo in ("valid_from", "valid_until", "total_token_budget", "no_answer_message",
              "user_daily_token_quota", "chatbot_daily_token_quota",
              "anon_ip_daily_token_quota"):
        if campo in body.model_fields_set:
            payload[campo] = getattr(body, campo)

    # FIX.1: se comprueba que la configuración existe antes de asignarla. Dejar que reviente
    # la FK daría un 500 opaco a mitad de la petición en vez de decir qué falta.
    if "llm_config_id" in payload:
        if await session.get(HubLLMConfig, payload["llm_config_id"]) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"LLM config {payload['llm_config_id']} not found",
            )

    next_mode = payload.get("retrieval_mode", chatbot.retrieval_mode)

    if next_mode == "MD_LONG_CONTEXT":
        total_tokens_row = await session.execute(
            select(func.coalesce(func.sum(HubDocument.token_count), 0)).where(
                HubDocument.chatbot_id == chatbot_id
            )
        )
        total_tokens = int(total_tokens_row.scalar_one() or 0)
        if total_tokens > 128_000:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "El corpus excede el límite del modo MD_LONG_CONTEXT (128K tokens). "
                    "Reduce el corpus o cambia a MD_AGENT_SELECTOR."
                ),
            )

    for field, value in payload.items():
        setattr(chatbot, field, value)
    chatbot.updated_at = datetime.now(timezone.utc)

    await session.commit()
    await session.refresh(chatbot)
    return chatbot


@router.delete("/{chatbot_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chatbot(
    chatbot_id: uuid.UUID,
    user: UserInfo = Depends(_require_admin),
    session=Depends(get_async_session),
):
    await _get_chatbot_or_404(session, chatbot_id, user)
    # PIL.2: primero el corpus y luego el chatbot, en la MISMA transacción.
    #
    # `hub_documents.chatbot_id` no tiene FK —se cayó con el split edge/cloud y la frontera
    # pide que no vuelva—, así que Postgres no cascadea aquí. Sin esta llamada, borrar un
    # chatbot dejaba sus documentos y sus embeddings en la base sin dueño: ocupando,
    # falseando recuentos y sin forma de encontrarlos.
    #
    # El orden importa: purgar después del `DELETE` del chatbot dejaría, ante un fallo a
    # mitad, exactamente el corpus huérfano que esto viene a impedir.
    retirado = await purgar_corpus_del_chatbot(session, chatbot_id)
    await session.execute(sql_delete(HubChatbot).where(HubChatbot.id == chatbot_id))
    await session.commit()

    # Lo que se llevó por delante queda dicho. La purga siempre lo contaba y lo devolvía —su
    # docstring pedía «poder decirlo en voz alta»— y aquí se descartaba: un borrado
    # irreversible del que no quedaba constancia de cuánto destruyó. Tres meses después, «se
    # perdieron cuántos documentos» no tenía respuesta.
    #
    # Se registra después del commit, a propósito: antes se anunciaría un borrado que aún puede
    # no ocurrir.
    logger.info(
        "Chatbot %s eliminado por %s; corpus retirado: %d documentos, %d fragmentos",
        chatbot_id,
        user.email,
        retirado.documentos,
        retirado.fragmentos,
    )


@router.get("/{chatbot_id}/corpus-stats", response_model=CorpusStatsOut, dependencies=[Depends(require_scopes("chatbots:read"))])
async def get_corpus_stats(
    chatbot_id: uuid.UUID,
    user: UserInfo = Depends(_require_admin),
    session=Depends(get_async_session),
):
    await _get_chatbot_or_404(session, chatbot_id, user)

    total_docs_row = await session.execute(
        select(func.count(HubDocument.id)).where(HubDocument.chatbot_id == chatbot_id)
    )
    total_documents = int(total_docs_row.scalar_one() or 0)

    total_tokens_row = await session.execute(
        select(func.coalesce(func.sum(HubDocument.token_count), 0)).where(
            HubDocument.chatbot_id == chatbot_id
        )
    )
    total_tokens = int(total_tokens_row.scalar_one() or 0)

    by_lang_rows = await session.execute(
        select(HubDocument.language, func.coalesce(func.sum(HubDocument.token_count), 0))
        .where(HubDocument.chatbot_id == chatbot_id)
        .group_by(HubDocument.language)
    )
    by_language = {str(lang): int(tokens or 0) for lang, tokens in by_lang_rows.all()}

    context_window = 128_000

    recommended_mode, recommendation_reason = recommend_retrieval_mode(
        total_tokens=total_tokens,
        context_window=context_window,
    )

    return CorpusStatsOut(
        total_documents=total_documents,
        total_tokens=total_tokens,
        by_language=by_language,
        recommended_mode=recommended_mode,
        recommendation_reason=recommendation_reason,
    )


@router.post("/{chatbot_id}/regenerate-chunks", response_model=RegenerateChunksOut)
async def regenerate_chunks(
    chatbot_id: uuid.UUID,
    user: UserInfo = Depends(_require_admin),
    session=Depends(get_async_session),
):
    chatbot = await _get_chatbot_or_404(session, chatbot_id, user)
    if chatbot.retrieval_mode != "RAG":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Solo se puede regenerar chunks cuando retrieval_mode == 'RAG'.",
        )

    docs_result = await session.execute(
        select(HubDocument).where(HubDocument.chatbot_id == chatbot_id)
    )
    docs = list(docs_result.scalars().all())

    watcher = IngestionWatcher(
        session=session,
        embedding_service=await resolve_embedding_service(session, chatbot_id),
    )
    created = 0
    for doc in docs:
        created += await watcher._regenerate_chunks_for_document(doc)

    task_id = str(uuid.uuid4())
    return RegenerateChunksOut(
        task_id=task_id,
        message="Regeneración completada",
        documents_processed=len(docs),
        chunks_created=created,
    )

@router.post(
    "/{chatbot_id}/recalculate-corpus",
    response_model=RecalculateCorpusOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def recalculate_corpus_endpoint(
    chatbot_id: uuid.UUID,
    user: UserInfo = Depends(_require_admin),
    session=Depends(get_async_session),
):
    chatbot = await _get_chatbot_or_404(session, chatbot_id, user)

    embedding_service = await resolve_embedding_service(session, chatbot_id)

    # MOD.1: esta guarda existía y NO PODÍA SALTAR. Comparaba `getattr(servicio,
    # "dimensions", 1024)` con `getattr(llm_config, "embedding_dimensions", 1024)`, y ninguno
    # de los dos atributos existía: los dos caían al default y la comparación era 1024 !=
    # 1024. Ahora compara el espacio vectorial REAL del corpus contra el del modelo activo,
    # que es lo que importa — misma dimensión no significa mismo espacio.
    try:
        await assert_embedding_space_matches(session, chatbot_id, embedding_service)
    except EmbeddingSpaceMismatch as desajuste:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(desajuste)
        ) from desajuste

    documents_processed, chunks_created, chunks_deleted = await recalculate_corpus(
        session=session,
        chatbot_id=chatbot_id,
        retrieval_mode=chatbot.retrieval_mode,
        embedding_service=embedding_service,
    )
    await session.commit()

    task_id = str(uuid.uuid4())
    return RecalculateCorpusOut(
        task_id=task_id,
        message=f"Recálculo completado. {documents_processed} documentos procesados.",
        documents_queued=documents_processed,
        chunks_created=chunks_created,
        chunks_deleted=chunks_deleted,
    )


@router.get("/{chatbot_id}/children", response_model=list[ChatbotRead], dependencies=[Depends(require_scopes("chatbots:read"))])
async def list_children(
    chatbot_id: uuid.UUID,
    user: UserInfo = Depends(_require_admin),
    session=Depends(get_async_session),
):
    router_cb = await _get_chatbot_or_404(session, chatbot_id, user)
    if router_cb.kind != "router":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Solo los chatbots de tipo router pueden tener hijos",
        )

    result = await session.execute(
        select(HubChatbot).where(HubChatbot.parent_chatbot_id == chatbot_id)
    )
    return result.scalars().all()


@router.post("/{chatbot_id}/children", response_model=ChatbotRead, dependencies=[Depends(require_scopes("chatbots:write"))])
async def assign_child(
    chatbot_id: uuid.UUID,
    body: AssignChildIn,
    user: UserInfo = Depends(_require_admin),
    session=Depends(get_async_session),
):
    router_cb = await _get_chatbot_or_404(session, chatbot_id, user)
    if router_cb.kind != "router":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Solo los chatbots de tipo router pueden tener hijos",
        )
    if router_cb.parent_chatbot_id is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se permite jerarquía de más de 2 niveles",
        )

    child_cb = await _get_chatbot_or_404(session, body.child_chatbot_id, user)

    if child_cb.id == router_cb.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Un chatbot no puede ser hijo de sí mismo",
        )
    if child_cb.kind == "router":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se puede asignar un hijo de tipo router",
        )
    if child_cb.organizacion_id != router_cb.organizacion_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El hijo debe pertenecer a la misma organización que el router",
        )
    if (
        child_cb.parent_chatbot_id is not None
        and child_cb.parent_chatbot_id != router_cb.id
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se permite crear nietos ni reparentar desde otro router",
        )

    child_cb.parent_chatbot_id = router_cb.id
    child_cb.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(child_cb)
    return child_cb


@router.delete(
    "/{chatbot_id}/children/{child_chatbot_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_scopes("chatbots:write"))],
)
async def unassign_child(
    chatbot_id: uuid.UUID,
    child_chatbot_id: uuid.UUID,
    user: UserInfo = Depends(_require_admin),
    session=Depends(get_async_session),
):
    router_cb = await _get_chatbot_or_404(session, chatbot_id, user)
    if router_cb.kind != "router":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Solo los chatbots de tipo router pueden tener hijos",
        )

    child_cb = await _get_chatbot_or_404(session, child_chatbot_id, user)
    if child_cb.parent_chatbot_id != router_cb.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ese chatbot no está asignado a este router",
        )

    child_cb.parent_chatbot_id = None
    child_cb.updated_at = datetime.now(timezone.utc)
    await session.commit()


# ─────────────────── Credenciales de sitio del widget (SEC.8.5) ───────────────────


class WidgetKeyOut(BaseModel):
    id: uuid.UUID
    name: str
    created_at: datetime
    revoked_at: datetime | None = None

    model_config = {"from_attributes": True}


class WidgetKeyCreated(WidgetKeyOut):
    """La clave EN CLARO viaja una sola vez, en la respuesta de creación.

    Después solo queda su hash, así que no hay endpoint que la devuelva: quien la pierda
    crea otra y revoca la anterior. Es el mismo trato que un PAT.
    """

    key: str


class WidgetKeyCreate(BaseModel):
    name: str


@router.post(
    "/{chatbot_id}/widget-keys",
    response_model=WidgetKeyCreated,
    status_code=status.HTTP_201_CREATED,
)
async def create_widget_key(
    chatbot_id: uuid.UUID,
    body: WidgetKeyCreate,
    user: UserInfo = Depends(_require_admin),
    session=Depends(get_async_session),
):
    """Emite una credencial de sitio para incrustar el widget de este chatbot."""
    from server.app.core.auth.widget_key import crear_widget_key

    chatbot = await _get_chatbot_or_404(session, chatbot_id, user)
    clave, fila = await crear_widget_key(
        session, chatbot_id=chatbot.id, name=body.name, created_by=user.user_id
    )
    await session.commit()
    await session.refresh(fila)
    return WidgetKeyCreated(
        id=fila.id,
        name=fila.name,
        created_at=fila.created_at,
        revoked_at=fila.revoked_at,
        key=clave,
    )


@router.get("/{chatbot_id}/widget-keys", response_model=list[WidgetKeyOut])
async def list_widget_keys(
    chatbot_id: uuid.UUID,
    user: UserInfo = Depends(_require_admin),
    session=Depends(get_async_session),
):
    from server.app.modules.agents_hub.database.config_models import HubWidgetKey

    await _get_chatbot_or_404(session, chatbot_id, user)
    filas = (
        await session.execute(
            select(HubWidgetKey)
            .where(HubWidgetKey.chatbot_id == chatbot_id)
            .order_by(HubWidgetKey.created_at.desc())
        )
    ).scalars().all()
    return list(filas)


@router.delete(
    "/{chatbot_id}/widget-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def revoke_widget_key(
    chatbot_id: uuid.UUID,
    key_id: uuid.UUID,
    user: UserInfo = Depends(_require_admin),
    session=Depends(get_async_session),
):
    """Revoca en vez de borrar: la fila deja constancia de que la credencial existió."""
    from server.app.modules.agents_hub.database.config_models import HubWidgetKey

    await _get_chatbot_or_404(session, chatbot_id, user)
    fila = (
        await session.execute(
            select(HubWidgetKey).where(
                HubWidgetKey.id == key_id, HubWidgetKey.chatbot_id == chatbot_id
            )
        )
    ).scalar_one_or_none()
    if fila is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Widget key not found"
        )
    fila.revoked_at = datetime.now(timezone.utc)
    await session.commit()
