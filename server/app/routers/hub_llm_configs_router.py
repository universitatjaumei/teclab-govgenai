"""CRUD de configuraciones de modelos del Hub: chat, embeddings y reranking.

MOD.1: la tabla dejó de ser implícitamente de chat. `purpose` distingue los tres usos y
`output_dimensionality` fija la dimensión que se le pide al proveedor de embeddings. Se
reutiliza todo lo que ya había —proveedores con su `base_url` y su clave, `available-models`,
test de conexión— en vez de construir un panel paralelo. Ver
`docs/DECISION_MODELOS_EMBEDDING_RERANKER.md`.

Deploy: cloud
Módulo: plataforma — ya lo declaraba; proveedores y niveles son globales. Con una excepción,
la misma que PLAT.5 hizo en organizaciones: **leer la lista** la necesita el selector de modelo de
`ChatbotsPage`, que vive en el módulo Chatbots (#319), así que exige `chatbots` o `plataforma`.
"""
import logging
import time
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from langchain_core.messages import HumanMessage
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from server.app.api.deps import require_role, require_module
from server.app.core.auth.models import UserInfo
from server.app.core.auth.tenancy import (
    assert_org_access,
    orgs_del_principal,
    organizacion_unica_de,
)
from server.app.api.deps import get_session
from server.app.modules.agents_hub.database.config_models import HubChatbot, HubLLMConfig, HubProvider
from server.app.modules.agents_hub.services.model_factory import _build_model
from server.app.services.model_fetcher import get_models_for_provider

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/hub/llm-configs", tags=["hub-llm-configs"])

# INF.7 lo exigía a nivel de router, para que no se pudiera olvidar en un endpoint nuevo. #319
# lo baja a cada endpoint porque el listado no es de la plataforma: elegir el modelo de un
# chatbot no es administrarla, y con el router entero bajo `plataforma` un administrador de
# Chatbots veía el selector vacío. Que no se olvide lo vigila ahora un test de #319.
_de_plataforma = Depends(require_module("plataforma"))
# Leer la lista la necesitan quien configura chatbots y quien administra la plataforma. Ni uno
# más (revisión de la PR #320): sin módulo, cualquier administrador —uno que sólo tuviera
# Informes— leía los modelos de la plataforma con sus proveedores.
_elige_modelo = Depends(require_module("chatbots", "plataforma"))

_require_admin = require_role("superadmin", "admin")
# SEC.9.2 — un proveedor es de ámbito `plataforma`: crearlo, cambiarlo o borrarlo afecta a TODAS
# las organizaciones. Leerlo lo necesita cualquier administrador (para elegirlo al configurar un
# modelo); escribirlo no es cosa de quien administra una sola.
_require_superadmin = require_role("superadmin")


def _ambito_de_escritura(user: UserInfo, pedido: uuid.UUID | None) -> uuid.UUID | None:
    """A qué organización pertenece lo que se está escribiendo (SEC.9.2).

    El cuerpo propone y el token dispone, con dos reglas:

    - **Nulo lo reserva el superadministrador**, porque una fila sin organización es la de
      plataforma y la heredan todas. Antes, `organizacion_id` venía del cuerpo sin comprobarse:
      un administrador podía crear el modelo por defecto de la instalación entera.
    - Un administrador que no la nombra escribe **en la suya**. Y si gestiona varias, no hay «la
      suya»: se le pregunta con un 400 en vez de elegir por él, que acabaría escribiendo en una
      organización que no ha nombrado — o, peor, en plataforma.
    """
    if getattr(user, "is_superadmin", False):
        return pedido
    if pedido is None:
        propia = organizacion_unica_de(user)
        if propia is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Indica la organización: tu cuenta gestiona varias, y la configuración "
                    "sin organización es la de plataforma."
                ),
            )
        return propia
    assert_org_access(user, pedido)
    return pedido


def _assert_puede_tocar(user: UserInfo, config: HubLLMConfig) -> None:
    """403 si la configuración no es suya (SEC.9.2).

    `organizacion_id` nulo significa «de la plataforma»: cambiarla o borrarla cambia el modelo
    de las demás organizaciones, así que es del superadministrador. Con `assert_org_access` a
    secas no bastaría, porque `None` allí sólo dice «no se puede decidir».
    """
    if getattr(user, "is_superadmin", False):
        return
    if config.organizacion_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="La configuración de plataforma la gestiona el superadministrador",
        )
    assert_org_access(user, config.organizacion_id)


class HubProviderOut(BaseModel):
    """Proveedor **sin su clave** (SEC.9.2).

    `api_key` estaba en este contrato, y como `hub_providers` es de plataforma, cualquier
    administrador de cualquier organización leía en claro la credencial de la instalación con un
    `GET`. Un secreto no vuelve por donde entró: para cambiarlo se manda uno nuevo, y para saber
    si hay uno puesto no hace falta verlo.
    """

    id: str
    name: str
    provider_type: str
    base_url: str | None

    model_config = {"from_attributes": True}


class HubProviderCreate(BaseModel):
    id: str
    name: str
    provider_type: str
    base_url: str | None = None
    api_key: str | None = None


class HubProviderUpdate(BaseModel):
    name: str | None = None
    provider_type: str | None = None
    base_url: str | None = None
    api_key: str | None = None


@router.get("/providers", response_model=list[HubProviderOut])
async def list_providers(
    _: UserInfo = Depends(_require_admin),
    _modulo=_de_plataforma,
    session=Depends(get_session),
):
    """Obtiene la lista de proveedores dinámicos."""
    result = await session.execute(select(HubProvider).order_by(HubProvider.name))
    return result.scalars().all()


@router.post("/providers", response_model=HubProviderOut, status_code=status.HTTP_201_CREATED)
async def create_provider(
    body: HubProviderCreate,
    _: UserInfo = Depends(_require_superadmin),
    _modulo=_de_plataforma,
    session=Depends(get_session),
):
    """Crea un nuevo proveedor."""
    existing = await session.get(HubProvider, body.id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Ya existe un proveedor con este ID"
        )
    provider = HubProvider(**body.model_dump())
    session.add(provider)
    await session.commit()
    await session.refresh(provider)
    return provider


@router.patch("/providers/{provider_id}", response_model=HubProviderOut)
async def update_provider(
    provider_id: str,
    body: HubProviderUpdate,
    _: UserInfo = Depends(_require_superadmin),
    _modulo=_de_plataforma,
    session=Depends(get_session),
):
    """Actualiza un proveedor existente."""
    provider = await session.get(HubProvider, provider_id)
    if not provider:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found")
    
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(provider, field, value)
        
    await session.commit()
    await session.refresh(provider)
    return provider


@router.delete("/providers/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider(
    provider_id: str,
    _: UserInfo = Depends(_require_superadmin),
    _modulo=_de_plataforma,
    session=Depends(get_session),
):
    """Elimina un proveedor si no está en uso."""
    provider = await session.get(HubProvider, provider_id)
    if not provider:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found")
        
    in_use = await session.execute(
        select(HubLLMConfig).where(HubLLMConfig.provider == provider_id)
    )
    if in_use.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No se puede eliminar: hay configuraciones usando este proveedor",
        )
        
    await session.delete(provider)
    await session.commit()


class AvailableModelsOut(BaseModel):
    """Modelos que ofrece un proveedor (CAL.2).

    Puebla el desplegable de modelos del diálogo de configuración LLM. Sin
    `response_model` el frontend recibía `unknown` y hacía `data.models || []`
    sobre un tipo que el contrato no respalda.
    """

    ok: bool
    models: list[str]


class LLMConnectionTestOut(BaseModel):
    """Resultado de probar la conexión con un modelo."""

    ok: bool
    latency_ms: int


@router.get("/available-models/{provider_id}", response_model=AvailableModelsOut)
async def list_available_models(
    provider_id: str,
    _: UserInfo = Depends(_require_admin),
    _modulo=_de_plataforma,
    session=Depends(get_session),
):
    """Obtiene la lista de modelos disponibles para un proveedor (usa caché)."""
    provider = await session.get(HubProvider, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
        
    models = await get_models_for_provider(provider_id) # Usamos provider_id que puede ser el tipo
    if not models:
        # Fallbacks just in case
        if provider.provider_type == "google_genai":
            models = ["gemini-1.5-flash", "gemini-2.5-flash", "gemini-1.5-pro"]
        elif provider.provider_type == "openai_compatible":
            models = ["gpt-4o", "gpt-4o-mini", "llama3.2"]
    return {"ok": True, "models": models}


class LLMConfigRead(BaseModel):
    id: uuid.UUID
    # MT.2 — de quién es este modelo. Nulo = de la plataforma, y lo heredan todas. Va en
    # el contrato porque sin él la columna sería inalcanzable desde la API; la pantalla
    # que lo deja elegir es MT.10, en la fase 2.
    organizacion_id: uuid.UUID | None = None
    provider: str
    model_name: str
    temperature: float
    top_p: float
    max_tokens: int
    api_key_secret_name: str | None
    tier: int
    purpose: Literal["chat", "embedding", "rerank"]
    output_dimensionality: int | None
    label: str
    is_default: bool

    model_config = {"from_attributes": True}


class LLMConfigCreate(BaseModel):
    # MT.2 — de quién es este modelo. Nulo = de la plataforma, y lo heredan todas. Va en
    # el contrato porque sin él la columna sería inalcanzable desde la API; la pantalla
    # que lo deja elegir es MT.10, en la fase 2.
    organizacion_id: uuid.UUID | None = None
    provider: str
    model_name: str
    temperature: float = 0.1
    top_p: float = 1.0
    max_tokens: int = 12000
    api_key_secret_name: str | None = None
    tier: int = 1
    purpose: Literal["chat", "embedding", "rerank"] = "chat"
    output_dimensionality: int | None = None
    label: str = ""
    is_default: bool = False


class LLMConfigUpdate(BaseModel):
    label: str | None = None
    tier: int | None = None
    purpose: Literal["chat", "embedding", "rerank"] | None = None
    output_dimensionality: int | None = None
    model_name: str | None = None
    api_key_secret_name: str | None = None
    is_default: bool | None = None
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None


@router.get("", response_model=list[LLMConfigRead])
async def list_llm_configs(
    user: UserInfo = Depends(_require_admin),
    session=Depends(get_session),
    _modulo=_elige_modelo,
):
    """Los modelos de sus organizaciones **y los de plataforma**, que se heredan (SEC.9.2).

    No se usa `scope_query_to_orgs`: `hub_llm_configs` es `heredable`, y acotar sólo a las
    organizaciones del principal escondería el nivel de plataforma —que hoy es el único que
    existe— y dejaría la pantalla vacía. El `or_` es el mismo patrón que `config_provider`, y por
    la misma razón: `NULL IN (...)` es nulo en SQL, así que un `IN` no trae la fila de plataforma.
    """
    stmt = select(HubLLMConfig).order_by(HubLLMConfig.tier, HubLLMConfig.label)
    if not user.is_superadmin:
        stmt = stmt.where(
            or_(
                HubLLMConfig.organizacion_id.in_(orgs_del_principal(user)),
                HubLLMConfig.organizacion_id.is_(None),
            )
        )
    result = await session.execute(stmt)
    return result.scalars().all()


async def _relevar_default(
    session,
    tier: int,
    *,
    purpose: str,
    organizacion_id: uuid.UUID | None,
    excepto: uuid.UUID | None = None,
) -> None:
    """Quita la marca de defecto a las demás del mismo tier, propósito y ámbito (FIX.1, MT.2).

    Antes esto era un 409: «ya existe una por defecto para el tier N». Convertía «quiero que
    esta sea la de por defecto» en dos peticiones y, entre la una y la otra, un momento sin
    ninguna. Peor aún, nadie documentaba el orden, así que en la BD de desarrollo acabaron
    conviviendo **dos** configuraciones tier 1 marcadas por defecto.

    El relevo ocurre en la misma transacción que la promoción, así que o hay exactamente una
    o no hay cambio.

    **MT.2 le añade los dos ejes que le faltaban, y el primero era un fallo real.** Degradaba
    por `tier` a secas, ignorando `purpose`: hoy conviven un chat nivel 1 y un embedding nivel 1
    marcados por defecto, así que promover uno de chat desde la pantalla dejaba la plataforma
    **sin modelo de embeddings**, y eso no se nota hasta la siguiente ingesta. El segundo eje es
    la organización: sin él, promover el nivel 1 de un municipio degradaría el del vecino.

    `organizacion_id` se compara con `is_(None)` y no con `==`, porque en SQL `NULL = NULL` es
    nulo y no verdadero: con `==` el relevo del nivel de plataforma —el único que existe hoy— no
    encontraría nada y dejaría dos por defecto.
    """
    condiciones = [
        HubLLMConfig.tier == tier,
        HubLLMConfig.purpose == purpose,
        HubLLMConfig.is_default.is_(True),
    ]
    if organizacion_id is None:
        condiciones.append(HubLLMConfig.organizacion_id.is_(None))
    else:
        condiciones.append(HubLLMConfig.organizacion_id == organizacion_id)
    if excepto is not None:
        condiciones.append(HubLLMConfig.id != excepto)

    anteriores = (await session.execute(select(HubLLMConfig).where(*condiciones))).scalars().all()
    for anterior in anteriores:
        anterior.is_default = False


@router.post("", response_model=LLMConfigRead, status_code=status.HTTP_201_CREATED)
async def create_llm_config(
    body: LLMConfigCreate,
    user: UserInfo = Depends(_require_admin),
    _modulo=_de_plataforma,
    session=Depends(get_session),
):
    # SEC.9.2: la organización se resuelve ANTES del relevo. Si no, un administrador degradaría
    # la marca de «por defecto» de una organización en la que no puede escribir, y el 403 llegaría
    # después de haber tocado sus filas.
    organizacion_id = _ambito_de_escritura(user, body.organizacion_id)

    if body.is_default:
        await _relevar_default(
            session,
            body.tier,
            purpose=body.purpose,
            organizacion_id=organizacion_id,
        )

    payload = body.model_dump()
    payload["organizacion_id"] = organizacion_id
    # Defaults operativos para precisión: Tier 1 => 0.1, Tier 2/3 => 0.0
    if "temperature" not in body.model_fields_set:
        payload["temperature"] = 0.1 if body.tier == 1 else 0.0

    config = HubLLMConfig(**payload)
    session.add(config)
    await session.commit()
    await session.refresh(config)
    return config


@router.patch("/{config_id}", response_model=LLMConfigRead)
async def update_llm_config(
    config_id: uuid.UUID,
    body: LLMConfigUpdate,
    user: UserInfo = Depends(_require_admin),
    _modulo=_de_plataforma,
    session=Depends(get_session),
):
    config = await session.get(HubLLMConfig, config_id)
    if not config:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Config not found")
    _assert_puede_tocar(user, config)

    target_tier = body.tier if body.tier is not None else config.tier
    if body.is_default is True:
        await _relevar_default(
            session,
            target_tier,
            purpose=body.purpose if body.purpose is not None else config.purpose,
            organizacion_id=config.organizacion_id,
            excepto=config_id,
        )

    for field, value in body.model_dump(exclude_none=True).items():
        setattr(config, field, value)

    await session.commit()
    await session.refresh(config)
    return config


@router.delete("/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_llm_config(
    config_id: uuid.UUID,
    user: UserInfo = Depends(_require_admin),
    _modulo=_de_plataforma,
    session=Depends(get_session),
):
    config = await session.get(HubLLMConfig, config_id)
    if not config:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Config not found")
    _assert_puede_tocar(user, config)

    in_use = await session.execute(
        select(HubChatbot).where(HubChatbot.llm_config_id == config_id)
    )
    if in_use.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No se puede eliminar: hay chatbots usando esta configuración",
        )

    await session.delete(config)
    await session.commit()


@router.post("/{config_id}/test", response_model=LLMConnectionTestOut)
async def test_llm_connection(
    config_id: uuid.UUID,
    user: UserInfo = Depends(_require_admin),
    _modulo=_de_plataforma,
    session=Depends(get_session),
):
    config = await session.scalar(
        select(HubLLMConfig)
        .options(selectinload(HubLLMConfig.provider_rel))
        .where(HubLLMConfig.id == config_id)
    )
    if not config:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Config not found")
    # El más caro de los cuatro: probar **gasta la credencial** de quien sea dueño de la fila, y
    # de paso confirma al llamante que esa clave es válida.
    _assert_puede_tocar(user, config)

    try:
        model = _build_model(config)
        t0 = time.monotonic()
        await model.ainvoke([HumanMessage(content="test")])
        latency_ms = int((time.monotonic() - t0) * 1000)
        return {"ok": True, "latency_ms": latency_ms}
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        # #276 — el texto del proveedor va al registro y no al cliente: puede llevar la clave, la
        # URL interna o la respuesta cruda. El `ValueError` de arriba sí es nuestro y se dice.
        _log.warning("La prueba de conexión del modelo %s falló", config_id, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "LLM_CONEXION_FALLIDA",
                "message": "El proveedor no respondió a la prueba de conexión. El motivo está en el registro del servidor.",
            },
        ) from exc
