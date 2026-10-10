"""Cuotas de consumo en cascada y contabilidad de tokens (SEC.4). Deploy: edge.

Antes de esto no había cuota posible, solo conteo de peticiones: nadie guardaba cuántos
tokens gastaba una conversación, y una petición puede costar mil veces más que otra.

**Cinco sujetos, en este orden**: usuario/día → usuario/mes → chatbot/día →
organización/mes → IP/día (solo anónimo). Se devuelve **el primero agotado**, con su nombre
en el cuerpo: un 429 que no dice qué cuota se acabó obliga a adivinar a quien lo recibe, y
quien lo recibe no siempre puede preguntar.

**`NULL` hereda, `0` es sin límite.** Son cosas distintas y confundirlas es el fallo caro:
si `0` significara «bloqueado», poner un límite a cero para levantar la restricción dejaría
al chatbot mudo. Tiene test.

**Se comprueba ANTES de invocar al modelo y se contabiliza DESPUÉS**, así que la petición que
cruza el límite se desborda: no se pre-reserva presupuesto. Es una decisión, no un descuido
—reservar exigiría estimar el coste de una respuesta que todavía no existe, y una estimación
de más bloquearía a gente con cuota disponible—. El desbordamiento está acotado por
`max_tokens` del modelo y se cobra en la ventana siguiente.

**La IP no se guarda** (#250): el sujeto del anónimo es `huella_de_ip`, no la dirección.
"""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from server.app.core.config import get_settings
from server.app.modules.agents_hub.database.operational_models import HubUsageCounter

SUJETO_USUARIO = "user"
SUJETO_CHATBOT = "chatbot"
SUJETO_ORGANIZACION = "organizacion"
SUJETO_IP = "ip"

VENTANA_DIA = "day"
VENTANA_MES = "month"
VENTANA_TOTAL = "total"


def clave_de_ventana(ventana: str, momento: datetime | None = None) -> str:
    """`'2026-08-02'`, `'2026-08'` o `'total'`. En texto: las tres comparten columna."""
    ahora = momento or datetime.now(timezone.utc)
    if ventana == VENTANA_DIA:
        return ahora.date().isoformat()
    if ventana == VENTANA_MES:
        return ahora.strftime("%Y-%m")
    return VENTANA_TOTAL


def huella_de_ip(ip: str, momento: datetime | None = None) -> str:
    """El sujeto de la cuota del anónimo: una huella de su IP que cambia cada día (#250).

    Para contar una cuota diaria basta con reconocer la misma IP el mismo día, y una IP es dato
    personal. Antes el contador la guardaba tal cual, una fila por IP y día, sin plazo.

    - **Con el día dentro**: la misma IP da otra huella mañana, así que la tabla no sigue a
      nadie de un día a otro. Es la ventana del único límite que la usa, `anon_ip` diario.
    - **Con clave**: un hash sin ella se deshace probando las IPv4, que caben en minutos. La
      clave es `JWT_SECRET_KEY`, que el servidor ya exige; rotarla pone a cero los contadores
      por IP del día, que es lo mismo que pasa a medianoche.
    """
    clave = get_settings().jwt_secret_key.encode()
    mensaje = f"cuota-ip:{clave_de_ventana(VENTANA_DIA, momento)}:{ip}".encode()
    return hmac.new(clave, mensaje, hashlib.sha256).hexdigest()[:32]


@dataclass(frozen=True)
class Limite:
    """Un sujeto, su ventana y cuánto tiene concedido."""

    subject_type: str
    subject_id: str
    ventana: str
    limite: int  # 0 = sin límite


def _primero_no_nulo(*valores):
    """La cascada: el primer nivel que se pronuncia manda. `None` es «no me pronuncio»."""
    for valor in valores:
        if valor is not None:
            return valor
    return None


def limites_aplicables(actor, chatbot, organizacion, *, ip: str | None = None) -> list[Limite]:
    """Los límites que le tocan a esta petición, en el orden en que se comprueban.

    `organizacion` puede ser `None` si no se pudo cargar: en ese caso solo se pierden los
    defaults heredables, no la comprobación de los límites propios del chatbot.
    """
    limites: list[Limite] = []

    def _añadir(subject_type, subject_id, ventana, valor):
        # `None` tras la cascada = nadie ha puesto límite en ningún nivel. `0` = sin límite.
        if valor is None or valor == 0 or subject_id is None:
            return
        limites.append(Limite(subject_type, str(subject_id), ventana, int(valor)))

    actor_id = getattr(actor, "subject_id", None) if actor else None

    if actor_id:
        _añadir(
            SUJETO_USUARIO,
            actor_id,
            VENTANA_DIA,
            _primero_no_nulo(
                getattr(chatbot, "user_daily_token_quota", None),
                getattr(organizacion, "default_user_daily_token_quota", None),
            ),
        )
        _añadir(
            SUJETO_USUARIO,
            actor_id,
            VENTANA_MES,
            getattr(organizacion, "default_user_monthly_token_quota", None),
        )

    _añadir(
        SUJETO_CHATBOT,
        getattr(chatbot, "id", None),
        VENTANA_DIA,
        _primero_no_nulo(
            getattr(chatbot, "chatbot_daily_token_quota", None),
            getattr(organizacion, "default_chatbot_daily_token_quota", None),
        ),
    )
    _añadir(
        SUJETO_ORGANIZACION,
        getattr(chatbot, "organizacion_id", None),
        VENTANA_MES,
        getattr(organizacion, "monthly_token_quota", None),
    )

    if ip:
        # Solo para el anónimo del widget: con sesión, el sujeto es la persona, y limitar
        # además por IP castigaría a media facultad detrás del mismo NAT.
        _añadir(
            SUJETO_IP,
            huella_de_ip(ip),
            VENTANA_DIA,
            getattr(chatbot, "anon_ip_daily_token_quota", None),
        )

    return limites


async def consumo_de(session, subject_type: str, subject_id: str, ventana: str) -> int:
    fila = (
        await session.execute(
            select(HubUsageCounter.tokens).where(
                HubUsageCounter.subject_type == subject_type,
                HubUsageCounter.subject_id == str(subject_id),
                HubUsageCounter.window_key == clave_de_ventana(ventana),
            )
        )
    ).scalars().first()
    return int(fila or 0)


def _agotada(limite: Limite, usados: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={
            "code": "QUOTA_EXCEEDED",
            "subject": limite.subject_type,
            "window": limite.ventana,
            "limit": limite.limite,
            "used": usados,
        },
        headers={"Retry-After": str(_segundos_hasta_el_reinicio(limite.ventana))},
    )


def _segundos_hasta_el_reinicio(ventana: str, momento: datetime | None = None) -> int:
    """Cuánto falta para que la ventana se renueve. Aproximado a propósito.

    El mes se calcula como 31 días desde el día 1 en el peor caso; afinar al día exacto no
    cambia lo que hace el cliente —esperar o pedir más cuota— y sí añade aritmética de
    calendario que habría que probar.
    """
    ahora = momento or datetime.now(timezone.utc)
    if ventana == VENTANA_DIA:
        fin = ahora.replace(hour=23, minute=59, second=59, microsecond=0)
        return max(1, int((fin - ahora).total_seconds()))
    if ventana == VENTANA_MES:
        dias_restantes = 31 - ahora.day
        return max(1, dias_restantes * 86_400)
    return 3600


async def assert_within_quota(session, actor, chatbot, organizacion=None, *, ip=None) -> None:
    """429 en el **primer** sujeto agotado, diciendo cuál es.

    Único punto de decisión, igual que `assert_chatbot_access`: la comparten el chat, el
    adaptador compatible-OpenAI (OWUI.1) y el endpoint del widget (D.1).
    """
    for limite in limites_aplicables(actor, chatbot, organizacion, ip=ip):
        usados = await consumo_de(
            session, limite.subject_type, limite.subject_id, limite.ventana
        )
        if usados >= limite.limite:
            raise _agotada(limite, usados)


async def registrar_consumo(
    session, subject_type: str, subject_id, ventana: str, tokens: int, cost: float = 0.0
) -> None:
    """Suma al contador con un UPSERT atómico.

    `ON CONFLICT ... DO UPDATE` y no leer-sumar-escribir: el chat es concurrente y dos
    respuestas simultáneas del mismo usuario se pisarían el contador, que es justo el hueco
    por donde se salta una cuota.
    """
    if not subject_id or tokens <= 0:
        return

    sentencia = pg_insert(HubUsageCounter).values(
        subject_type=subject_type,
        subject_id=str(subject_id),
        window_key=clave_de_ventana(ventana),
        tokens=tokens,
        cost=cost,
        updated_at=datetime.now(timezone.utc),
    )
    await session.execute(
        sentencia.on_conflict_do_update(
            constraint="uq_usage_counter_subject_window",
            set_={
                "tokens": HubUsageCounter.tokens + tokens,
                "cost": HubUsageCounter.cost + cost,
                "updated_at": datetime.now(timezone.utc),
            },
        )
    )


async def contabilizar_interaccion(
    session, actor, chatbot, tokens: int, cost: float = 0.0, *, ip: str | None = None
) -> None:
    """Reparte el consumo entre todos los sujetos, tengan cuota o no.

    Se cuenta **siempre**, también cuando nadie ha puesto un límite: sin histórico no hay
    forma de elegir el límite el día que haga falta ponerlo, y activar una cuota sobre un
    contador a cero regalaría el primer periodo entero.
    """
    if tokens <= 0:
        return

    actor_id = getattr(actor, "subject_id", None) if actor else None
    if actor_id:
        await registrar_consumo(session, SUJETO_USUARIO, actor_id, VENTANA_DIA, tokens, cost)
        await registrar_consumo(session, SUJETO_USUARIO, actor_id, VENTANA_MES, tokens, cost)

    chatbot_id = getattr(chatbot, "id", None)
    await registrar_consumo(session, SUJETO_CHATBOT, chatbot_id, VENTANA_DIA, tokens, cost)
    # `total` es el acumulado que consume el presupuesto por chatbot de SEC.4.1.
    await registrar_consumo(session, SUJETO_CHATBOT, chatbot_id, VENTANA_TOTAL, tokens, cost)

    await registrar_consumo(
        session,
        SUJETO_ORGANIZACION,
        getattr(chatbot, "organizacion_id", None),
        VENTANA_MES,
        tokens,
        cost,
    )

    if ip:
        await registrar_consumo(session, SUJETO_IP, huella_de_ip(ip), VENTANA_DIA, tokens, cost)
