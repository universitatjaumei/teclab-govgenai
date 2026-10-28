"""La configuración de los chatbots: leerla, guardarla, borrarla y su jerarquía. Deploy: cloud (#274).

Vivía en los handlers de `hub_chatbots_router`, que consultaban, decidían y escribían. Ahí se queda
lo que es HTTP —validar el cuerpo, elegir el código de estado—; lo que toca la base está aquí, y
el corpus del chatbot, que es dato del cliente, se pide a `DatosDelCliente` (#298).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import delete as sql_delete
from sqlalchemy import select

from server.app.core.auth.tenancy import assert_org_access, scope_query_to_orgs
from server.app.core.datos_del_cliente import CorpusRetirado, DatosDelCliente
from server.app.modules.agents_hub.database.config_models import (
    HubChatbot,
    HubLLMConfig,
    HubWidgetKey,
)


async def exigir_configuracion_utilizable(
    session, llm_config_id: uuid.UUID, organizacion_id: uuid.UUID | None
) -> None:
    """Un chatbot usa una configuración de LLM de plataforma o de su organización, no de otra.

    404 también para la de otra organización, como si no existiera: usarla es gastar su
    credencial, y decir que existe ya es contar algo de ella. FIX.1 comprobaba sólo la
    existencia, para dar un 404 claro en vez de un 500 de clave ajena.
    """
    config = await session.get(HubLLMConfig, llm_config_id)
    if config is None or (
        config.organizacion_id is not None and str(config.organizacion_id) != str(organizacion_id)
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"LLM config {llm_config_id} not found",
        )


async def chatbot_o_404(session, chatbot_id: uuid.UUID, principal=None) -> HubChatbot:
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


async def listar(session, principal, organizacion_id: uuid.UUID | None) -> list[HubChatbot]:
    """Los que el principal puede ver; si pide una organización, sólo los de ésa.

    La tenencia primero y el filtro después: `scope_query_to_orgs` decide lo que se *puede* ver
    y el filtro sólo estrecha dentro de eso. Acotado en SQL y no en memoria (SEC.2).
    """
    consulta = scope_query_to_orgs(
        select(HubChatbot).order_by(HubChatbot.created_at.desc()), principal, HubChatbot
    )
    if organizacion_id is not None:
        assert_org_access(principal, organizacion_id)
        consulta = consulta.where(HubChatbot.organizacion_id == organizacion_id)
    return list((await session.execute(consulta)).scalars().all())


async def crear(session, chatbot: HubChatbot) -> HubChatbot:
    session.add(chatbot)
    await session.commit()
    await session.refresh(chatbot)
    return chatbot


async def actualizar(session, chatbot: HubChatbot, cambios: dict[str, Any]) -> HubChatbot:
    for campo, valor in cambios.items():
        setattr(chatbot, campo, valor)
    chatbot.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(chatbot)
    return chatbot


async def borrar(session, chatbot_id: uuid.UUID, datos: DatosDelCliente) -> CorpusRetirado:
    """PIL.2: primero el corpus y luego el chatbot, en la MISMA transacción.

    `hub_documents.chatbot_id` no tiene FK —se cayó con el split edge/cloud y la frontera
    pide que no vuelva—, así que Postgres no cascadea aquí. Sin la purga, borrar un chatbot
    dejaba sus documentos y sus embeddings en la base sin dueño.

    El orden importa: purgar después del `DELETE` del chatbot dejaría, ante un fallo a mitad,
    exactamente el corpus huérfano que esto viene a impedir. La purga la hace el edge, por
    `DatosDelCliente` (#298); la local comparte esta sesión, así que es la misma transacción.
    Las fuentes van **después** del commit: el almacenamiento no es transaccional.
    """
    retirado = await datos.purgar_corpus([chatbot_id])
    await session.execute(sql_delete(HubChatbot).where(HubChatbot.id == chatbot_id))
    await session.commit()
    await datos.borrar_fuentes([chatbot_id])
    return retirado


async def hijos(session, chatbot_id: uuid.UUID) -> list[HubChatbot]:
    return list(
        (await session.execute(select(HubChatbot).where(HubChatbot.parent_chatbot_id == chatbot_id)))
        .scalars()
        .all()
    )


async def colgar_de(session, hijo: HubChatbot, padre_id: uuid.UUID | None) -> HubChatbot:
    """Asigna (o, con `None`, retira) el enrutador del que cuelga un chatbot."""
    return await actualizar(session, hijo, {"parent_chatbot_id": padre_id})


async def emitir_clave_del_widget(
    session, chatbot_id: uuid.UUID, nombre: str, emitida_por: str
) -> tuple[str, HubWidgetKey]:
    from server.app.core.auth.widget_key import crear_widget_key

    clave, fila = await crear_widget_key(
        session, chatbot_id=chatbot_id, name=nombre, created_by=emitida_por
    )
    await session.commit()
    await session.refresh(fila)
    return clave, fila


async def claves_del_widget(session, chatbot_id: uuid.UUID) -> list[HubWidgetKey]:
    return list(
        (
            await session.execute(
                select(HubWidgetKey)
                .where(HubWidgetKey.chatbot_id == chatbot_id)
                .order_by(HubWidgetKey.created_at.desc())
            )
        )
        .scalars()
        .all()
    )


async def revocar_clave_del_widget(session, chatbot_id: uuid.UUID, key_id: uuid.UUID) -> bool:
    """Revoca en vez de borrar: la fila deja constancia de que la credencial existió.

    False si la clave no es de ese chatbot.
    """
    fila = (
        await session.execute(
            select(HubWidgetKey).where(
                HubWidgetKey.id == key_id, HubWidgetKey.chatbot_id == chatbot_id
            )
        )
    ).scalar_one_or_none()
    if fila is None:
        return False
    fila.revoked_at = datetime.now(timezone.utc)
    await session.commit()
    return True
