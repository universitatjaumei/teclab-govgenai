"""Proveedor de configuración (Costura Edge-Cloud)."""

import uuid
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.core.ambito import (
    de_esta_organizacion,
    de_plataforma,
    resolver_cascada,
)
from server.app.modules.agents_hub.database.config_models import (
    HubActivityPrompt,
    HubChatbot,
    HubLLMConfig,
)
from server.app.modules.agents_hub.services.vocabulary_service import (
    VocabularyTermDTO,
)


@dataclass(frozen=True)
class ActivityPromptOverride:
    """La excepción guardada para una actividad — PRO.2.1.

    Sale de aquí y no del modelo ORM porque **los módulos edge no importan modelos de
    configuración**: la frontera dice que el acceso pasa por el `ConfigProvider`, y devolver
    la fila obligaría a `modules/redaccion` a conocer `HubActivityPrompt`.

    Los dos campos pueden ser None o vacío, y eso significa «usa lo que dice el código».
    """

    template_text: str | None
    override_tier: int | None


class ConfigProvider(Protocol):
    """Protocolo para acceder a la configuración desde módulos edge."""

    async def get_chatbot(self, chatbot_id: uuid.UUID) -> HubChatbot | None: ...
    async def get_llm_config(self, llm_config_id: uuid.UUID) -> HubLLMConfig | None: ...
    async def get_llm_config_for_tier(
        self, tier: int, *, organizacion_id: uuid.UUID | None
    ) -> HubLLMConfig | None: ...
    async def get_activity_prompt(
        self, activity: str, *, organizacion_id: uuid.UUID | None = None
    ) -> ActivityPromptOverride | None: ...
    async def list_active_chatbots(self, organizacion_id: uuid.UUID) -> list[HubChatbot]: ...
    async def get_retrieval_mode(self, chatbot_id: uuid.UUID) -> str: ...
    async def get_anonymization_mode(
        self, organizacion_id: uuid.UUID
    ) -> str | None: ...
    async def list_vocabulary(
        self, axis: str, organizacion_id: uuid.UUID
    ) -> list[VocabularyTermDTO]: ...


class LocalConfigProvider:
    """Implementación cloud-only: lee directamente de la base de datos."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_chatbot(self, chatbot_id: uuid.UUID) -> HubChatbot | None:
        """Obtiene un chatbot por su ID."""
        result = await self.session.execute(
            select(HubChatbot).where(HubChatbot.id == chatbot_id)
        )
        return result.scalars().first()

    async def get_llm_config(self, llm_config_id: uuid.UUID) -> HubLLMConfig | None:
        """Obtiene una configuración LLM por su ID."""
        result = await self.session.execute(
            select(HubLLMConfig)
            .options(selectinload(HubLLMConfig.provider_rel))
            .where(HubLLMConfig.id == llm_config_id)
        )
        return result.scalars().first()

    async def get_llm_config_for_tier(
        self, tier: int, *, organizacion_id: uuid.UUID | None
    ) -> HubLLMConfig | None:
        """Configuración de **conversación** marcada como default para un tier y organización.

        El filtro por `purpose` no es defensivo: sin él, la configuración de embeddings del
        piloto —marcada por defecto en el nivel 1 al montar Vertex— se devolvía a quien pedía
        un modelo para redactar, y el fallo salía mucho más lejos y acusando al proveedor
        (`ValueError: Provider type desconocido: google_vertexai`). Lo comparten todos los
        que resuelven modelo por nivel: el analizador de HTML de la ingesta y la redacción
        de bloques.
        """
        candidatas = (
            await self.session.execute(
                select(HubLLMConfig)
                .options(selectinload(HubLLMConfig.provider_rel))
                .where(
                    HubLLMConfig.tier == tier,
                    HubLLMConfig.is_default.is_(True),
                    HubLLMConfig.purpose == "chat",
                    # MT.3 — sólo las dos filas que pueden participar. `or_` y no
                    # `IN (org, None)`, porque `NULL IN (...)` en SQL es nulo y no traería la
                    # de plataforma, que es el caso normal.
                    or_(
                        HubLLMConfig.organizacion_id == organizacion_id,
                        HubLLMConfig.organizacion_id.is_(None),
                    )
                    if organizacion_id is not None
                    else HubLLMConfig.organizacion_id.is_(None),
                )
            )
        ).scalars().all()

        # MT.3 — la cascada de MT.1: la suya gana, y si no la de plataforma. Nunca la de otra:
        # el filtro de arriba ya las dejó fuera, y esto elige entre las dos que quedan.
        return de_esta_organizacion(candidatas, organizacion_id) or de_plataforma(candidatas)

    async def get_activity_prompt(
        self, activity: str, *, organizacion_id: uuid.UUID | None = None
    ) -> ActivityPromptOverride | None:
        """El override de una actividad, si alguien lo ha guardado (PRO.2.1, MT.6).

        `None` es el caso normal: qué actividades existen y con qué nivel y prompt corren lo
        dice el código, y esta tabla sólo guarda excepciones.

        **MT.6 — los dos campos se heredan por separado.** Un municipio puede querer el texto de
        la plataforma con un modelo más caro, y obligarle a copiar el texto para cambiar el nivel
        lo congelaría igual que copiarlo del código: a partir de ahí, mejorar el de plataforma no
        le llegaría. Por eso se resuelve campo a campo con la cascada de MT.1 y no eligiendo una
        fila entera.
        """
        consulta = select(HubActivityPrompt).where(HubActivityPrompt.activity == activity)
        if organizacion_id is None:
            consulta = consulta.where(HubActivityPrompt.organizacion_id.is_(None))
        else:
            # `or_` y no `IN (org, None)`: `NULL IN (...)` en SQL es nulo, así que no traería la
            # fila de plataforma — que es la que existe hoy y la que se hereda.
            consulta = consulta.where(
                or_(
                    HubActivityPrompt.organizacion_id == organizacion_id,
                    HubActivityPrompt.organizacion_id.is_(None),
                )
            )

        filas = list((await self.session.execute(consulta)).scalars())
        if not filas:
            return None
        resuelto = resolver_cascada(
            filas, organizacion_id, campos=("template_text", "override_tier")
        )
        return ActivityPromptOverride(
            template_text=resuelto["template_text"],
            override_tier=resuelto["override_tier"],
        )

    async def list_active_chatbots(self, organizacion_id: uuid.UUID) -> list[HubChatbot]:
        """Obtiene los chatbots activos de una organización."""
        result = await self.session.execute(
            select(HubChatbot).where(
                HubChatbot.organizacion_id == organizacion_id, HubChatbot.is_active.is_(True)
            )
        )
        return list(result.scalars().all())

    async def get_retrieval_mode(self, chatbot_id: uuid.UUID) -> str:
        """Devuelve el retrieval_mode del chatbot (default 'RAG' si no existe)."""
        chatbot = await self.get_chatbot(chatbot_id)
        return getattr(chatbot, "retrieval_mode", "RAG") if chatbot else "RAG"

    async def get_anonymization_mode(self, organizacion_id: uuid.UUID) -> str | None:
        """El suelo de anonimización que fijó la organización, o `None` si no fijó ninguno.

        Vive aquí y no en el servicio de anonimización porque `HubOrganizacion` es un modelo de
        **configuración** y aquel servicio es **edge**: la frontera prohíbe que un servicio edge
        importe modelos de config, justamente para que el despliegue partido pueda leerlos por
        sincronización en vez de por consulta local. Lo señaló la revisión de la PR #178.

        `None` no es un valor por omisión disfrazado: significa «esta organización no lo ha
        fijado», y quien decide qué hacer con eso es `politica.modo_efectivo`.
        """
        from server.app.modules.agents_hub.database.config_models import HubOrganizacion

        organizacion = await self.session.get(HubOrganizacion, organizacion_id)
        declarado = getattr(organizacion, "anonymization_mode", None)
        return declarado or None

    async def list_vocabulary(
        self, axis: str, organizacion_id: uuid.UUID
    ) -> list[VocabularyTermDTO]:
        """Términos del vocabulario de un eje, para consumo desde edge (ING.0.1).

        Es la única vía por la que los módulos edge acceden al vocabulario: no pueden
        importar HubVocabularyTerm, que es configuración cloud.
        """
        from server.app.modules.agents_hub.database.config_models import (
            HubVocabularyTerm,
        )

        result = await self.session.execute(
            select(HubVocabularyTerm).where(
                HubVocabularyTerm.organizacion_id == organizacion_id,
                HubVocabularyTerm.axis == axis,
            )
        )
        return [
            VocabularyTermDTO(
                axis=row.axis,
                codi=row.codi,
                nom_primari=row.nom_primari,
                nom_secundari=row.nom_secundari,
                parent_codi=row.parent_codi,
                descripcio_router=row.descripcio_router,
                ordre=row.ordre,
                vigent=row.vigent,
                substituit_per_codi=row.substituit_per_codi,
            )
            for row in result.scalars().all()
        ]
