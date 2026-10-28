"""Lo que la gestión, la consulta y la calidad de los agentes de unidad leen y escriben. Deploy: edge (#274).

Vivía en los handlers de `routers/agentes_router.py`, que con 2.024 líneas consultaba, decidía y
confirmaba en el mismo sitio. Allí se quedan los DTO, quién puede hacer qué (`acciones`) y los
códigos de estado; aquí, la base. Las reglas —qué cuenta como revisar, cómo se selecciona del
índice— siguen en `acciones`, `indice` y `datos`.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Callable, TypeVar

from fastapi import HTTPException, status
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.core.auth.models import UserInfo
from server.app.modules.agentes import indice
from server.app.modules.agents_hub.database.operational_models import (
    HubActividadIA,
    HubAgenteConsulta,
    HubAgenteFicha,
    HubAgenteUnidad,
    HubAgenteUnidadVersion,
    HubAsistenteAdaptador,
)

_Vista = TypeVar("_Vista")

# ───────────────────────── Los agentes ─────────────────────────


async def vigentes(session: AsyncSession, filtro) -> list[tuple[HubAgenteUnidad, HubAgenteUnidadVersion]]:
    """Cada agente con su última versión, que es la que se ofrece."""
    ultima = (
        select(
            HubAgenteUnidadVersion.agente_id,
            func.max(HubAgenteUnidadVersion.version).label("version"),
        )
        .group_by(HubAgenteUnidadVersion.agente_id)
        .subquery()
    )
    consulta = (
        select(HubAgenteUnidad, HubAgenteUnidadVersion)
        .join(ultima, ultima.c.agente_id == HubAgenteUnidad.id)
        .join(
            HubAgenteUnidadVersion,
            (HubAgenteUnidadVersion.agente_id == ultima.c.agente_id)
            & (HubAgenteUnidadVersion.version == ultima.c.version),
        )
        .order_by(HubAgenteUnidad.nombre, HubAgenteUnidad.id)
    )
    if filtro is not None:
        consulta = consulta.where(filtro)
    return [(a, v) for a, v in (await session.execute(consulta)).all()]


def de_sus_organizaciones(user: UserInfo):
    """El acotado del listado, **en el `WHERE`**. La lista vacía significa «ninguna» (I8)."""
    if user.is_superadmin:
        return None
    ids = [uuid.UUID(str(o)) for o in user.organizacion_ids]
    return HubAgenteUnidad.organizacion_id.in_(ids)


async def el_agente(
    session: AsyncSession, agente_id: uuid.UUID, user: UserInfo
) -> tuple[HubAgenteUnidad, HubAgenteUnidadVersion]:
    filtro = HubAgenteUnidad.id == agente_id
    acotado = de_sus_organizaciones(user)
    if acotado is not None:
        filtro = filtro & acotado
    encontrados = await vigentes(session, filtro)
    if not encontrados:
        # 404 y no 403: lo de otra organización no existe para quien pregunta.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agente no encontrado")
    return encontrados[0]


async def fichas_por_agente(
    session: AsyncSession, vigentes_: dict[uuid.UUID, HubAgenteUnidadVersion]
) -> dict[uuid.UUID, tuple[int, int]]:
    """Por agente: cuántas fichas y cuántas resumidas con otra versión del prompt.

    Una ficha sin versión no está desfasada: la escribió una persona, no un prompt. **La versión
    con que se compara es la del agente** (#220): con datos que extraer, su prompt no es el común.
    """
    if not vigentes_:
        return {}
    suya = {aid: indice.prompt_de_resumen(v.datos_consulta)[0] for aid, v in vigentes_.items()}
    filas = await session.execute(
        select(HubAgenteFicha.agente_id, HubAgenteFicha.version_prompt_resumen, func.count())
        .where(HubAgenteFicha.agente_id.in_(list(vigentes_)))
        .group_by(HubAgenteFicha.agente_id, HubAgenteFicha.version_prompt_resumen)
    )
    cuentas: dict[uuid.UUID, tuple[int, int]] = {}
    for agente_id, version_resumen, n in filas.all():
        total, viejas = cuentas.get(agente_id, (0, 0))
        desfasada = version_resumen is not None and version_resumen != suya[agente_id]
        cuentas[agente_id] = (total + n, viejas + (n if desfasada else 0))
    return cuentas


async def calidad_por_agente(
    session: AsyncSession, ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[int, int, int]]:
    """#217 — por agente: consultas, respuestas leídas e informes sin revisar."""
    if not ids:
        return {}
    filas = await session.execute(
        select(
            HubAgenteConsulta.agente_id,
            func.count(),
            func.count().filter(HubAgenteConsulta.respuesta.is_not(None)),
            func.count().filter((HubAgenteConsulta.puntuacion == -1) & HubAgenteConsulta.veredicto.is_(None)),
        )
        .where(HubAgenteConsulta.agente_id.in_(ids))
        .group_by(HubAgenteConsulta.agente_id)
    )
    return {agente_id: (n, leidas, abiertos) for agente_id, n, leidas, abiertos in filas.all()}


async def guardar(
    session: AsyncSession,
    agente: HubAgenteUnidad,
    version: HubAgenteUnidadVersion,
    vista: Callable[[tuple[int, int], tuple[int, int, int]], _Vista],
) -> _Vista:
    """Confirma lo cambiado en el agente y devuelve su vista con las cuentas al día.

    La vista se construye antes del commit: la sesión de los routers expiraba los atributos al
    commitear, y leerlos después costaba un 500.
    """
    await session.flush()
    cuentas = (await fichas_por_agente(session, {agente.id: version})).get(agente.id, (0, 0))
    calidad = (await calidad_por_agente(session, [agente.id])).get(agente.id, (0, 0, 0))
    construida = vista(cuentas, calidad)
    await session.commit()
    return construida


async def dar_de_alta(
    session: AsyncSession, agente: HubAgenteUnidad, version: HubAgenteUnidadVersion
) -> None:
    session.add(agente)
    await session.flush()
    session.add(version)


async def anadir_version(
    session: AsyncSession,
    agente: HubAgenteUnidad,
    version: HubAgenteUnidadVersion,
    *,
    otra_carpeta: bool,
) -> None:
    """Corregir es versionar: lo revisado sigue siendo lo que se revisó.

    Otra carpeta, otro índice: el de la anterior no puede seguir sirviéndose hasta que el guion
    corra sobre la nueva (revisión de la PR #221). El índice es derivado: se rehace.
    """
    session.add(version)
    if otra_carpeta:
        await session.execute(delete(HubAgenteFicha).where(HubAgenteFicha.agente_id == agente.id))
        agente.indice_actualizado_en = None
        agente.indice_origen = None
        agente.documentos_en_carpeta = None
    agente.updated_at = datetime.now(timezone.utc)


# ───────────────────────── El índice ─────────────────────────


async def apuntar_carga(
    session: AsyncSession, agente_id: uuid.UUID, *, origen: str, documentos_en_carpeta: int | None
) -> None:
    """La fecha se apunta **también sin cambios**: es la prueba de que el guion sigue vivo."""
    await session.execute(
        update(HubAgenteUnidad)
        .where(HubAgenteUnidad.id == agente_id)
        .values(
            indice_actualizado_en=datetime.now(timezone.utc),
            indice_origen=origen,
            documentos_en_carpeta=documentos_en_carpeta,
        )
    )
    await session.commit()


async def fichas(session: AsyncSession, agente_id: uuid.UUID) -> list[HubAgenteFicha]:
    return list(
        (
            await session.execute(
                select(HubAgenteFicha)
                .where(HubAgenteFicha.agente_id == agente_id)
                .order_by(HubAgenteFicha.titulo, HubAgenteFicha.url)
            )
        ).scalars()
    )


# ───────────────────────── Registro de actividad y consultas ─────────────────────────


async def anotar_actividad(session: AsyncSession, actividad: HubActividadIA) -> None:
    session.add(actividad)
    await session.commit()


async def registrar_consulta(
    session: AsyncSession,
    *,
    actividad: HubActividadIA,
    agente: HubAgenteUnidad,
    version: HubAgenteUnidadVersion,
    actor: str,
    consulta_id: uuid.UUID,
    elegidas: list[Any],
    pregunta: str,
    datos_dados: dict[str, str],
    consulta_madre_id: uuid.UUID | None = None,
) -> None:
    """El uso en el registro de actividad y la consulta con lo que se ofreció, en un `commit`.

    #216 — en validación se guarda la pregunta; el registro de actividad, nunca.
    """
    session.add(actividad)
    session.add(
        HubAgenteConsulta(
            id=consulta_id,
            agente_id=agente.id,
            version=version.version,
            actor=actor,
            documentos=[{"url": e.url, "score": e.score} for e in elegidas],
            actividad_id=actividad.id,
            modo=agente.modo_registro,
            pregunta=pregunta if agente.modo_registro == "validacion" else None,
            datos=datos_dados if agente.modo_registro == "validacion" and datos_dados else None,
            consulta_madre_id=consulta_madre_id,
        )
    )
    await session.commit()


async def urls_ofrecidas(session: AsyncSession, madre_id: uuid.UUID) -> frozenset[str]:
    """Lo ofrecido en toda la conversación: la consulta madre y sus ampliaciones (#225)."""
    ofrecidas = (
        await session.execute(
            select(HubAgenteConsulta.documentos).where(
                or_(HubAgenteConsulta.id == madre_id, HubAgenteConsulta.consulta_madre_id == madre_id)
            )
        )
    ).scalars()
    return frozenset(d["url"] for documentos in ofrecidas for d in (documentos or []))


async def la_consulta(session: AsyncSession, consulta_id: uuid.UUID, user: UserInfo) -> HubAgenteConsulta:
    """La consulta de **quien pregunta**: la de otra persona no existe para él (404)."""
    fila = (
        await session.execute(
            select(HubAgenteConsulta)
            .where(HubAgenteConsulta.id == consulta_id, HubAgenteConsulta.actor == user.user_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if fila is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Consulta no encontrada")
    return fila


async def consulta_o_404(session: AsyncSession, consulta_id: uuid.UUID) -> HubAgenteConsulta:
    fila = (
        await session.execute(select(HubAgenteConsulta).where(HubAgenteConsulta.id == consulta_id))
    ).scalar_one_or_none()
    if fila is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Consulta no encontrada")
    return fila


async def guardar_respuesta(
    session: AsyncSession,
    fila: HubAgenteConsulta,
    *,
    texto: str | None,
    fuentes: list[str],
    no_capturada: str | None,
) -> None:
    fila.respuesta = texto
    fila.fuentes = fuentes if texto is not None else None
    fila.respuesta_no_capturada = no_capturada
    fila.respuesta_en = datetime.now(timezone.utc)
    await session.commit()


async def valorar(
    session: AsyncSession,
    fila: HubAgenteConsulta,
    *,
    puntuacion: int,
    motivo: str | None,
    comentario: str | None,
    pregunta: str | None,
    respuesta: str | None,
) -> None:
    """En incidencias, el informe es lo único que se guarda, y por eso trae la pregunta y la
    respuesta; una valoración buena guarda la puntuación y nada más. En validación ya estaban: no
    se pisan."""
    fila.puntuacion = puntuacion
    fila.motivo = motivo
    fila.comentario = (comentario or "").strip() or None
    fila.valorada_en = datetime.now(timezone.utc)
    if fila.modo == "incidencias":
        # En incidencias sólo se guarda lo informado como inadecuado: si deja de serlo, se borra.
        fila.pregunta = pregunta if puntuacion == -1 else None
        fila.respuesta = respuesta if puntuacion == -1 else None
    await session.commit()


async def conversaciones(
    session: AsyncSession,
    agente_id: uuid.UUID,
    *,
    modo: str | None,
    puntuacion: int | None,
    motivo: str | None,
    sin_revisar: bool,
    limite: int,
) -> tuple[list[HubAgenteConsulta], dict[str, str]]:
    """Las consultas del agente, más recientes primero, y el título actual de cada documento."""
    consulta_sql = select(HubAgenteConsulta).where(HubAgenteConsulta.agente_id == agente_id)
    if modo:
        consulta_sql = consulta_sql.where(HubAgenteConsulta.modo == modo)
    if puntuacion is not None:
        consulta_sql = consulta_sql.where(HubAgenteConsulta.puntuacion == puntuacion)
    if motivo:
        consulta_sql = consulta_sql.where(HubAgenteConsulta.motivo == motivo)
    if sin_revisar:
        consulta_sql = consulta_sql.where(HubAgenteConsulta.veredicto.is_(None))
    filas = list(
        (
            await session.execute(
                consulta_sql.order_by(HubAgenteConsulta.ocurrido_en.desc()).limit(limite)
            )
        )
        .scalars()
        .all()
    )
    urls = {d["url"] for f in filas for d in (f.documentos or [])}
    titulos = (
        dict(
            (
                await session.execute(
                    select(HubAgenteFicha.url, HubAgenteFicha.titulo).where(
                        HubAgenteFicha.agente_id == agente_id, HubAgenteFicha.url.in_(urls)
                    )
                )
            ).all()
        )
        if urls
        else {}
    )
    return filas, titulos


async def revisar_conversacion(
    session: AsyncSession,
    fila: HubAgenteConsulta,
    *,
    veredicto: str,
    nota: str | None,
    revisada_por: str,
    vista: Callable[[], _Vista],
) -> _Vista:
    fila.veredicto = veredicto
    fila.nota_revision = (nota or "").strip() or None
    fila.revisada_por = revisada_por
    fila.revisada_en = datetime.now(timezone.utc)
    await session.flush()
    construida = vista()
    await session.commit()
    return construida


# ───────────────────────── Los adaptadores de la extensión ─────────────────────────


async def el_adaptador(
    session: AsyncSession, asistente: str, *, bloquear: bool = False
) -> HubAsistenteAdaptador:
    consulta = select(HubAsistenteAdaptador).where(HubAsistenteAdaptador.asistente == asistente)
    if bloquear:
        consulta = consulta.with_for_update()
    adaptador = (await session.execute(consulta)).scalar_one_or_none()
    if adaptador is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asistente no encontrado")
    return adaptador


async def adaptadores(session: AsyncSession) -> list[HubAsistenteAdaptador]:
    return list(
        (
            await session.execute(
                select(HubAsistenteAdaptador).order_by(HubAsistenteAdaptador.asistente)
            )
        ).scalars()
    )


async def anotar_fallo(
    session: AsyncSession, adaptador: HubAsistenteAdaptador, *, version: int, selector: str
) -> None:
    """El de una versión que ya no es la vigente no cuenta: ya se corrigió."""
    if version != adaptador.version:
        return
    adaptador.fallos_de_la_version += 1
    adaptador.ultimo_fallo_en = datetime.now(timezone.utc)
    adaptador.ultimo_fallo_selector = selector
    await session.commit()


async def cambiar_adaptador(
    session: AsyncSession, adaptador: HubAsistenteAdaptador, *, selectores: dict[str, str], por: str
) -> HubAsistenteAdaptador:
    """Una versión nueva, con los fallos a cero."""
    adaptador.selectores = selectores
    adaptador.version += 1
    adaptador.fallos_de_la_version = 0
    adaptador.ultimo_fallo_en = None
    adaptador.ultimo_fallo_selector = None
    adaptador.actualizado_en = datetime.now(timezone.utc)
    adaptador.actualizado_por = por
    await session.commit()
    await session.refresh(adaptador)
    return adaptador
