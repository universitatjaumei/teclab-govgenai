"""El registro de actividad IA: lo que ocurre fuera de la plataforma (REG.2).

Deploy: edge
Módulo: —

**Por qué existe.** La plataforma sabe todo de las conversaciones que pasan por ella y nada de las
que no. Una organización que use además asistentes de escritorio, agentes de código o
integraciones propias no puede responder «qué IA se usó aquí» sin ir a preguntar a cada
herramienta. Este endpoint le da un sitio donde esas herramientas lo declaren.

Sirve a la conservación de registros del AI Act y al registro de actividades de tratamiento del
RGPD. **No** es trazado técnico: metadatos de gobernanza, y el detalle de cada conversación se
queda en la herramienta que la tuvo.

**Dos decisiones que condicionan la forma del endpoint:**

**La organización se deriva del token, no viaja en el payload.** Un agente externo no elige en
nombre de qué organización registra. Si lo eligiera, un token de una organización podría escribir
en el registro de otra, y entonces el registro no daría cuenta de nada.

**Escribe un PAT, no una sesión.** Por eso `require_pat_scopes` y no `require_scopes`: aquélla
deja pasar a los principales humanos, y una sesión de navegador con permiso de escritura aquí
permitiría fabricar entradas del registro desde el panel.

**Y la lectura es lo contrario: sesión, no PAT** (REG.5). Es para personas —el panel de
administración—, con rol admin o superadmin y acotada a las organizaciones del principal. No es
simetría descuidada: darle a un PAT capacidad de leer el registro sería regalar a cada integración
una ventana a la actividad de toda la organización.
"""
from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.api.deps import (
    get_current_user,
    require_admin,
    require_module,
    require_pat_scopes,
    require_scopes,
)
from server.app.core.auth.models import UserInfo
from server.app.core.auth.pat.scopes import ACTIVIDAD_WRITE
from server.app.core.auth.tenancy import (
    assert_org_access,
    organizacion_unica_de,
    scope_query_to_orgs,
)
from server.app.modules.agents_hub.contracts.actividad import ActividadIAEvent
from server.app.modules.agents_hub.database.connection import get_async_session
from server.app.modules.agents_hub.database.operational_models import HubActividadIA

#: Tope de la página. Sin él, `size=100000` pide la tabla entera por un endpoint paginado; quien
#: necesite todo tiene la exportación, que es lo que existe para eso.
MAXIMO_POR_PAGINA = 200

#: Las columnas del CSV, en orden, con los nombres del contrato. Nombres del contrato y no
#: rótulos traducidos: un fichero que alguien va a cruzar con otra fuente necesita nombres
#: estables, y las etiquetas legibles son cosa del panel, que sabe en qué idioma está su lector.
COLUMNAS_CSV = (
    "ocurrido_en",
    "registrado_en",
    "actor",
    "herramienta",
    "agente",
    "finalidad",
    "modelo_usado",
    "categorias_datos",
    "payload_hash",
    "funcion_sha256",
)

#: El módulo que abre la lectura del registro. **Solo la lectura**: el POST lo autentica un PAT
#: de máquina, y un token de máquina no tiene módulos concedidos —los módulos son de personas—.
MODULO_REGISTRO = "registro"

router = APIRouter(prefix="/actividad", tags=["actividad"])


class ActividadRegistrada(BaseModel):
    """El acuse: qué id tiene el evento y cuándo quedó registrado.

    Se devuelve `registrado_en` y no sólo el id porque es el dato que quien integra necesita para
    conciliar: su reloj y el nuestro no son el mismo, y la marca que vale en una auditoría es la
    nuestra.
    """

    id: uuid.UUID
    registrado_en: datetime


@router.post(
    "",
    response_model=ActividadRegistrada,
    status_code=status.HTTP_201_CREATED,
    operation_id="registrarActividad",
)
async def registrar_actividad(
    evento: ActividadIAEvent,
    user: UserInfo = Depends(require_pat_scopes(ACTIVIDAD_WRITE)),
    session: AsyncSession = Depends(get_async_session),
) -> ActividadRegistrada:
    """Registra un uso de IA declarado por una herramienta externa.

    El contrato rechaza los campos que no declara, así que un intento de colar el contenido
    —`payload`, `prompt`, `content`— llega aquí como 422 y no como una fila con datos personales
    dentro.
    """
    organizacion_id = organizacion_unica_de(user)
    if organizacion_id is None:
        # Un principal sin organización única no tiene dónde registrar: puede ser un
        # superadministrador (lista vacía = «todas») o un token con varias. En los dos casos la
        # respuesta honesta es pedir un token de organización, no elegir una por él.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "ORGANIZACION_INDETERMINADA",
                "message": (
                    "El token tiene que pertenecer a una sola organización: el registro se "
                    "acota por ella y no se puede elegir en la petición."
                ),
            },
        )

    fila = HubActividadIA(
        organizacion_id=organizacion_id,
        ocurrido_en=evento.ocurrido_en,
        actor=evento.actor,
        herramienta=evento.herramienta,
        agente=evento.agente,
        finalidad=evento.finalidad,
        modelo_usado=evento.modelo_usado,
        categorias_datos=evento.categorias_datos,
        payload_hash=evento.payload_hash,
        funcion_sha256=evento.funcion_sha256,
    )
    session.add(fila)
    await session.commit()
    await session.refresh(fila)

    return ActividadRegistrada(id=fila.id, registrado_en=fila.registrado_en)


# ─────────────────────────── La lectura (REG.5) ────────────────────────────


class EventoRegistrado(BaseModel):
    """Un evento tal como lo lee el panel.

    Lleva el `id` porque la tabla lo necesita como clave de fila, y `registrado_en` porque es la
    marca que pone la plataforma: en una auditoría, la diferencia entre cuándo ocurrió algo y
    cuándo se declaró es un dato, no ruido.
    """

    id: uuid.UUID
    ocurrido_en: datetime
    registrado_en: datetime
    actor: str
    herramienta: str
    agente: str | None
    finalidad: str
    modelo_usado: str | None
    categorias_datos: list[str]
    payload_hash: str | None
    #: AUT.5 — con qué función registrada del catálogo se corresponde, si con alguna.
    funcion_sha256: str | None = None


class PaginaDeActividad(BaseModel):
    """`total` cuenta lo que hay tras los filtros, no lo que cabe en la página."""

    items: list[EventoRegistrado]
    total: int
    page: int
    size: int


def _consulta(
    user: UserInfo,
    herramienta: str | None,
    desde: datetime | None,
    hasta: datetime | None,
):
    """El SELECT acotado y filtrado, compartido por el listado y la exportación.

    Compartido y no copiado a propósito: si divergieran, el CSV podría enseñar filas que el
    listado esconde, y la acotación por organización es justo lo que no puede tener dos
    versiones.
    """
    stmt = scope_query_to_orgs(select(HubActividadIA), user, HubActividadIA)
    if herramienta:
        stmt = stmt.where(HubActividadIA.herramienta == herramienta)
    if desde is not None:
        stmt = stmt.where(HubActividadIA.ocurrido_en >= desde)
    if hasta is not None:
        # Cerrado por arriba: quien pide «del 1 al 3» cuenta con el 3, y un rango abierto
        # dejaría fuera el último día sin decirlo.
        stmt = stmt.where(HubActividadIA.ocurrido_en <= hasta)
    return stmt


def _ordenada(stmt):
    """Más reciente primero, y con desempate.

    `ocurrido_en` lo declara quien registra, así que los empates son normales —un lote que se
    manda de golpe trae el mismo instante repetido—. Ordenar sólo por esa columna deja el orden
    dentro del empate en manos del planificador, y entonces paginar puede devolver una fila en
    dos páginas y otra en ninguna. Es el defecto que DET.1 arregló en el retriever; aquí caería
    sobre una tabla que alguien va a auditar.
    """
    return stmt.order_by(HubActividadIA.ocurrido_en.desc(), HubActividadIA.id.desc())


@router.get(
    "",
    response_model=PaginaDeActividad,
    operation_id="listarActividad",
    dependencies=[Depends(require_module(MODULO_REGISTRO))],
)
async def listar_actividad(
    herramienta: str | None = Query(default=None),
    desde: datetime | None = Query(default=None),
    hasta: datetime | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=25, ge=1, le=MAXIMO_POR_PAGINA),
    user: UserInfo = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
) -> PaginaDeActividad:
    """Página del registro de actividad de las organizaciones del principal."""
    base = _consulta(user, herramienta, desde, hasta)

    total = (
        await session.execute(select(func.count()).select_from(base.subquery()))
    ).scalar_one()

    filas = (
        (
            await session.execute(
                _ordenada(base).offset((page - 1) * size).limit(size)
            )
        )
        .scalars()
        .all()
    )

    return PaginaDeActividad(
        items=[EventoRegistrado.model_validate(f, from_attributes=True) for f in filas],
        total=total,
        page=page,
        size=size,
    )


@router.get(
    "/export",
    operation_id="exportarActividad",
    dependencies=[Depends(require_module(MODULO_REGISTRO))],
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}}},
)
async def exportar_actividad(
    herramienta: str | None = Query(default=None),
    desde: datetime | None = Query(default=None),
    hasta: datetime | None = Query(default=None),
    user: UserInfo = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
) -> Response:
    """El mismo registro filtrado, en CSV, para llevárselo a otra herramienta."""
    filas = (
        (await session.execute(_ordenada(_consulta(user, herramienta, desde, hasta))))
        .scalars()
        .all()
    )

    buffer = io.StringIO()
    escritor = csv.writer(buffer)
    escritor.writerow(COLUMNAS_CSV)
    for fila in filas:
        escritor.writerow(
            [
                fila.ocurrido_en.isoformat(),
                fila.registrado_en.isoformat(),
                fila.actor,
                fila.herramienta,
                fila.agente or "",
                fila.finalidad,
                fila.modelo_usado or "",
                # Una lista en JSON es una celda en CSV: el formato no anida. Separadas por `;`
                # y no por `,`, que es el separador de campos del propio fichero y partiría la
                # celda en dos columnas al abrirla en una hoja de cálculo.
                ";".join(fila.categorias_datos or ()),
                fila.payload_hash or "",
                fila.funcion_sha256 or "",
            ]
        )

    return Response(
        content=buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            # Sin esto el navegador lo pinta en una pestaña en vez de ofrecer guardarlo.
            "Content-Disposition": 'attachment; filename="actividad_ia.csv"'
        },
    )


# ─────────────────────────── El catálogo de categorías (REG.8) ─────────────


class CategoriaDeDatos(BaseModel):
    """Una categoría del catálogo de la organización.

    Lleva `nombre` para que el panel no tenga que inventar la etiqueta, y `sustituida_por` para
    que quien tenga que reetiquetar lo ya registrado sepa a dónde fue una categoría renombrada.
    """

    codigo: str
    nombre: str
    nombre_secundario: str | None
    vigente: bool
    sustituida_por: str | None


@router.get(
    "/categorias",
    response_model=list[CategoriaDeDatos],
    operation_id="categoriasDeDatos",
    # #214 — quien registra con un token tiene que poder leer el catálogo que el contrato le
    # pide usar; la descripción de `registrar_actividad` en el MCP le manda aquí.
    dependencies=[Depends(require_scopes(ACTIVIDAD_WRITE))],
)
async def categorias_de_datos(
    incluir_retiradas: bool = Query(
        default=False,
        description=(
            "Incluye las categorías retiradas, con su sustituta. Para reetiquetar lo ya "
            "registrado; para elegir al registrar, no hacen falta."
        ),
    ),
    organizacion_id: uuid.UUID | None = Query(
        default=None,
        description=(
            "Obligatorio sólo si el principal no pertenece a una sola organización "
            "(superadministrador o token de varias)."
        ),
    ),
    user: UserInfo = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> list[CategoriaDeDatos]:
    """Los códigos de `categorias_datos` que usa esta organización.

    **Se anuncia, no se impone**: el `POST` sigue aceptando cualquier código. Rechazar uno que no
    esté aquí convertiría «esta categoría todavía no está dada de alta» en «este uso de IA no
    queda registrado», y perder el registro es peor que tenerlo con una etiqueta imperfecta. Lo
    que este catálogo compra es que las herramientas **converjan**: sin él, cada una inventa sus
    códigos y el registro deja de poder agregarse, que es para lo que existe.

    **Sin exigir rol ni módulo**, a diferencia de la lectura del registro. Saber cómo se llaman
    las categorías de tu propia organización no es privilegiado, y exigir el módulo `registro`
    dejaría fuera al consumidor principal: el token de máquina que sólo tiene `actividad:write`.
    """
    org = organizacion_id or organizacion_unica_de(user)
    if org is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "ORGANIZACION_NO_INDICADA",
                "message": (
                    "Indica `organizacion_id`: el catálogo es de cada organización y este "
                    "principal no pertenece a una sola."
                ),
            },
        )
    # Con `organizacion_id` explícito hay que comprobarlo: si no, cualquiera con sesión leería
    # el catálogo de cualquier organización pasando su id.
    assert_org_access(user, org)

    # Vía `ConfigProvider` y no importando el modelo: `hub_vocabulary_terms` es configuración
    # cloud y este router es edge. Es la única puerta (ING.0.1).
    from server.app.modules.agents_hub.services.config_provider import (
        LocalConfigProvider,
    )
    from server.app.modules.agents_hub.services.vocabulary_service import VocabularyAxis

    terminos = await LocalConfigProvider(session).list_vocabulary(
        VocabularyAxis.CATEGORIA_DADES, org
    )

    # El orden lo decide quien mantiene el catálogo (`ordre`), con el código como desempate para
    # que dos términos del mismo orden no salgan hoy en un sitio y mañana en otro.
    return [
        CategoriaDeDatos(
            codigo=t.codi,
            nombre=t.nom_primari,
            nombre_secundario=t.nom_secundari,
            vigente=t.vigent,
            sustituida_por=t.substituit_per_codi,
        )
        for t in sorted(terminos, key=lambda t: (t.ordre, t.codi))
        if incluir_retiradas or t.vigent
    ]
