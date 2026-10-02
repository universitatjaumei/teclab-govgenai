"""Qué módulos tiene concedidos quien pregunta (INF.7, ampliado en IDE.5).

Deploy: cloud

El servidor decide y el cliente itera: el menú y las rutas del frontend se generan desde esta
lista, no de un `role ===` escrito en React. Es la misma regla que `acciones_permitidas` en los
bloques y en expedientes.

**Dos vías, y basta con una** (IDE.5). Una concesión apunta a una persona (`subject_type =
'usuario'`, el UUID derivado del claim) o a un **grupo del IdP** (`'grupo'`, el nombre que
declara el atributo de `SAML_ATTR_GROUPS`). La unión es la semántica que `assert_chatbot_access`
ya usa para los chatbots `restricted` —rol **o** grupo, lo que case primero— y arrastra su regla
documentada: **el vacío es «nadie», no «todos»**. Sin fila que case, no hay módulo.

**Los grupos se comparan plegando la caja, y es una decisión.** Los IdP no se ponen de acuerdo, y
los que va a mandar la UJI son acrónimos —`PDI`, `PTGAS`— que cualquiera teclea en minúscula al
configurarlos. Se guarda lo que se escribió, para que la pantalla lo muestre tal cual, y se
compara plegado. El precio: dos filas que solo difieran en la caja pueden coexistir; como se
devuelve un conjunto, no conceden dos veces.
"""
from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.core.auth.models import UserInfo
from server.app.core.auth.modulos import ROL_CON_ACCESO_TOTAL
from server.app.modules.agents_hub.database.config_models import (
    HubModuleGrant as ModuleGrant,
    HubPlatformModule as PlatformModule,
)
from server.app.core.identidad import user_to_uuid

TIPO_USUARIO = "usuario"
TIPO_GRUPO = "grupo"


async def _vigentes(session: AsyncSession) -> set[str]:
    return set(
        (
            await session.execute(
                select(PlatformModule.code).where(PlatformModule.vigente.is_(True))
            )
        ).scalars().all()
    )


async def _de_oficio(session: AsyncSession) -> set[str]:
    """Los módulos vigentes que tiene cualquier persona, sin concesión (UTL, 2026-10-02).

    Es la única excepción a «sin fila no hay acceso», y por eso es una marca del catálogo y no
    una regla escrita aquí: qué es de oficio lo dice la tabla, que se cambia sin desplegar.
    """
    return set(
        (
            await session.execute(
                select(PlatformModule.code).where(
                    PlatformModule.vigente.is_(True), PlatformModule.de_oficio.is_(True)
                )
            )
        ).scalars().all()
    )


def _condicion_del_sujeto(user: UserInfo):
    """Las dos vías por las que una concesión alcanza a esta persona.

    Devuelve `None` cuando no hay ninguna vía posible —ni sujeto ni grupos—, para que quien
    llame no lance una consulta cuyo resultado ya se conoce.
    """
    vias = [
        (ModuleGrant.subject_type == TIPO_USUARIO)
        & (ModuleGrant.subject_id == str(user_to_uuid(user.user_id)))
    ]

    grupos = [g.strip().lower() for g in user.saml_groups if g and g.strip()]
    if grupos:
        vias.append(
            (ModuleGrant.subject_type == TIPO_GRUPO)
            & (func.lower(ModuleGrant.subject_id).in_(grupos))
        )

    return or_(*vias) if len(vias) > 1 else vias[0]


def _condicion_del_ambito(organizacion_id):
    """Las concesiones que valen en esta organización (MT.5).

    **Nulo en la fila significa «en todas»**, que es lo que significan las concesiones de hoy, así
    que siempre entran. Y `organizacion_id=None` en la pregunta significa «sin acotar»: devuelve
    todo lo que la persona tenga en cualquier sitio, que es como preguntaban los sitios que aún
    no saben la organización — y es lo que hace que MT.5 no cambie comportamiento.

    `is_(None)` y no `== None`: en SQL `NULL = NULL` es nulo y no verdadero, así que un `==`
    dejaría fuera precisamente las filas de hoy.
    """
    if organizacion_id is None:
        return None
    return or_(
        ModuleGrant.organizacion_id.is_(None),
        ModuleGrant.organizacion_id == organizacion_id,
    )


def _condiciones(user: UserInfo, organizacion_id) -> list:
    condiciones = [_condicion_del_sujeto(user)]
    del_ambito = _condicion_del_ambito(organizacion_id)
    if del_ambito is not None:
        condiciones.append(del_ambito)
    return condiciones


async def modulos_del_usuario(
    session: AsyncSession, user: UserInfo, *, organizacion_id=None
) -> list[str]:
    """Los códigos de módulo que este usuario puede usar **en una organización**, en orden estable.

    El superadmin entra en todos los módulos vigentes **sin concesión explícita**: es el rol de
    la plataforma, y hacerlo depender de una fila deja una instalación recién creada con un
    superadmin encerrado fuera —`bootstrap` crea la cuenta, no sus permisos—. Para cualquier
    otro rol, sin fila no hay acceso.

    Un módulo retirado del catálogo (`vigente = false`) no se concede a nadie aunque la fila de
    la concesión siga ahí: la fila es el histórico de quién tuvo acceso, no un permiso vivo.
    """
    vigentes = await _vigentes(session)

    if user.role == ROL_CON_ACCESO_TOTAL:
        return sorted(vigentes)

    concedidos = set(
        (
            await session.execute(
                select(ModuleGrant.module_code).where(*_condiciones(user, organizacion_id))
            )
        ).scalars().all()
    )
    return sorted((concedidos & vigentes) | await _de_oficio(session))


async def modulos_con_origen(
    session: AsyncSession, user: UserInfo, *, organizacion_id=None
) -> dict[str, list[dict[str, str]]]:
    """Cada módulo concedido y **de dónde le viene** (IDE.5).

    Un permiso cuyo origen no se ve es un permiso que nadie se atreve a retirar: quien mira una
    ficha tiene que poder distinguir «se lo concedí yo» de «le llega por ser PDI», porque
    retirar lo segundo afecta a todo el grupo.

    En un superadmin el origen es el **rol**, y se dice así en vez de inventar una fila que no
    existe: buscarla luego en la tabla y no encontrarla es peor que saber que no está.
    """
    vigentes = await _vigentes(session)

    if user.role == ROL_CON_ACCESO_TOTAL:
        return {
            codigo: [
                {"tipo": "rol", "sujeto": ROL_CON_ACCESO_TOTAL, "organizacion": ""}
            ]
            for codigo in sorted(vigentes)
        }

    filas = (
        await session.execute(
            select(
                ModuleGrant.module_code,
                ModuleGrant.subject_type,
                ModuleGrant.subject_id,
                ModuleGrant.organizacion_id,
            ).where(*_condiciones(user, organizacion_id))
        )
    ).all()

    origen: dict[str, list[dict[str, str]]] = {}
    for modulo, tipo, sujeto, organizacion in filas:
        if modulo not in vigentes:
            continue
        # MT.5 — el origen dice también **dónde** vale. Con dos ejes, «informes por ser PDI» no
        # se puede retirar a ciegas: hay que saber si afecta a un ayuntamiento o a los veinte.
        # Cadena vacía y no `None` para que el contrato no cambie de tipo por fila.
        origen.setdefault(modulo, []).append(
            {
                "tipo": tipo,
                "sujeto": sujeto,
                "organizacion": str(organizacion) if organizacion else "",
            }
        )
    # Lo de oficio se dice como tal, y no como una concesión que no existe: buscarla después en la
    # tabla y no encontrarla es peor que saber que no está.
    for modulo in await _de_oficio(session):
        origen.setdefault(modulo, []).append({"tipo": "de_oficio", "sujeto": "", "organizacion": ""})
    return dict(sorted(origen.items()))


async def tiene_modulo(session: AsyncSession, user: UserInfo, codigo: str) -> bool:
    return codigo in await modulos_del_usuario(session, user)
