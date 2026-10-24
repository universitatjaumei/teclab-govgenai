"""Las verificaciones de la plataforma, como servicio (Bloque VAS).

Deploy: edge
Módulo: —

**Por qué existe.** La posición de desarrollo era «gobernanza y experimentación sí; desarrollar es
cosa nuestra». La respuesta es que, definidos los parámetros de gobernanza de un caso de uso, la
UADTI puede desarrollar fuera **con registro por API dentro** — y para que eso sea literal hacen
falta servicios que hoy sólo existen como función interna. Este router presta tres, y todos son
deterministas: la misma entrada da la misma salida, así que exponerlos no crea una segunda fuente
de verdad.

**La regla dura del bloque: no hay segunda implementación.** Cada endpoint envuelve la función que
ya usa el motor. Si el servicio necesita algo que la función no da, se cambia la función y el motor
lo hereda; nunca una copia «para la API». Un test de paridad por servicio compara el veredicto de
aquí con el de la función directamente.

**El texto no se guarda.** Ni la respuesta que se verifica ni el código que se audita tocan logs ni
base de datos — la misma regla que REG.3 para la anonimización, y por el mismo motivo: aquí llega,
por definición, material que no es nuestro.

La forma de garantizarlo cambia por endpoint, y conviene saber cuál protege a cuál. `POST /citas`
y `POST /codigo` **no piden sesión de base de datos**: no hay dónde escribir, que es más fuerte que
recordar no hacerlo. `GET /vigencia` sí la recibe —tiene que leer el corpus—, y ahí la garantía es
que sólo hace `SELECT`; lo que se manda es un identificador, no texto ajeno.

**Y la asimetría del registro, escrita para que nadie la «arregle»**: la auditoría de código sí
deja un evento REG (VAS.3) porque auditar es un acto de gobernanza —la revisión posterior del
nivel 2 de la Instrucció 02/2026—, y verificar citas o consultar vigencia no, porque son
comprobaciones sin estado: la aplicación externa ya registra **su** actividad por REG.2, y un
evento por cada comprobación duplicaría el registro sin decir nada nuevo.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.api.deps import require_pat_scopes
from server.app.core.auth.models import UserInfo
from server.app.core.auth.pat.scopes import VERIFICACIONES_USE
from server.app.core.auth.tenancy import organizacion_unica_de, scope_query_to_orgs
from server.app.core.urls import normalizar_url
from server.app.modules.agents_hub.agent.citation_validator import aplicar_contrato
from server.app.modules.agents_hub.contracts.actividad import ActividadIAEvent
from server.app.modules.agents_hub.database.config_models import HubChatbot
from server.app.api.deps import get_session
from server.app.modules.agents_hub.database.operational_models import (
    HubActividadIA,
    HubDocument,
)
from server.app.modules.agents_hub.services.retrieval.metadata_filter import (
    MetadataFilter,
)
from server.app.modules.agents_hub.services.retrieval.vigencia import (
    aviso_para,
    marca_de_vigencia,
)
from server.app.modules.redaccion.services.script_auditor import (
    AuditFinding,
    CajaDeHerramientas,
    ScriptSecurityAuditor,
    caja_de_herramientas,
)

#: Con qué nombre consta la auditoría en el registro de actividad. Fijo y no el cliente del PAT:
#: lo que el registro tiene que poder contar es «esta plataforma auditó este hash», y el nombre
#: del cliente que lo pidió ya va en `actor`.
_HERRAMIENTA_DE_AUDITORIA = "govgenai-auditoria-estatica"

#: Tope del texto que se acepta, en bytes. No hay límite de entrada del sandbox del que heredarlo
#: —FUN.6 aún no existe—, así que se fija aquí y ese bloque lo heredará de este sitio en vez de
#: inventar otro. Sin tope, una petición tiene al proceso analizando megabytes.
MAXIMO_BYTES = 64 * 1024

router = APIRouter(prefix="/verificaciones", tags=["verificaciones"])

_exige_scope = require_pat_scopes(VERIFICACIONES_USE)


class FuenteDeVerificacion(BaseModel):
    """Una fuente que quien llama declara como entregada al modelo.

    Habla el dialecto de la evidencia del motor a propósito: `source_url` y `title` son los
    atributos que `citation_validator` lee, así que este objeto se le pasa **tal cual** y no hay
    conversión que pueda perder algo por el camino.
    """

    model_config = {"extra": "forbid"}

    url: str = Field(min_length=1, max_length=2048)
    titulo: str | None = Field(default=None, max_length=500)

    @property
    def source_url(self) -> str:
        return self.url

    @property
    def title(self) -> str | None:
        return self.titulo


class PeticionDeCitas(BaseModel):
    """El texto a verificar y las fuentes que se le entregaron a quien lo escribió."""

    model_config = {"extra": "forbid"}

    texto: str
    fuentes_permitidas: list[FuenteDeVerificacion] = Field(default_factory=list)
    #: El modo del motor. Se acepta por estabilidad del contrato y porque el grafo lo pasa; hoy
    #: el contrato de citas se comporta igual en los tres, y decirlo aquí es más honesto que
    #: sugerir con un parámetro ausente que no existe la distinción.
    modo: str = "RAG"
    #: El mensaje de rendición del asistente que llama. Si no viene, el del motor. UX.4: el texto
    #: fijo en castellano contestando a una pregunta en valenciano fue un defecto real.
    mensaje_sin_respuesta: str | None = Field(default=None, max_length=2000)


class VeredictoDeCitas(BaseModel):
    """Qué dice el contrato, y qué hizo para decirlo.

    El desglose importa tanto como el veredicto: quien integra necesita saber **por qué** su
    respuesta no cumple para poder arreglar la generación, no sólo que no cumple.
    """

    cumple: bool
    texto_resultante: str
    citas_validas: list[str]
    citas_invalidas: list[str]
    remisiones_despojadas: int
    anclas_degradadas: int


def _dentro_del_limite(texto: str) -> None:
    if len(texto.encode("utf-8")) > MAXIMO_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail={
                "code": "TEXTO_DEMASIADO_GRANDE",
                "message": f"El texto no puede pasar de {MAXIMO_BYTES} bytes.",
                "maximo_bytes": MAXIMO_BYTES,
            },
        )


@router.post(
    "/citas",
    response_model=VeredictoDeCitas,
    operation_id="verificarCitas",
)
async def verificar_citas(
    peticion: PeticionDeCitas,
    _=Depends(_exige_scope),
) -> VeredictoDeCitas:
    """Aplica el contrato de citas de la plataforma a una respuesta generada fuera.

    La regla es «ninguna afirmación sin fuente resoluble», y tiene tres movimientos que importan
    en este orden: una cita al documento correcto con un ancla que nadie recuperó **baja al
    documento y sobrevive**; lo que apunta fuera del conjunto entregado **pierde el enlace, no la
    mención**; y sólo entonces se comprueba si queda alguna cita válida.

    Si no queda ninguna, se devuelve el mensaje de rendición: es lo que hace el asistente, y el
    sentido de prestar el servicio es que quien desarrolle fuera pueda hacer lo mismo.
    """
    _dentro_del_limite(peticion.texto)

    resultado = aplicar_contrato(
        peticion.texto,
        list(peticion.fuentes_permitidas),
        peticion.modo,
        peticion.mensaje_sin_respuesta,
    )

    return VeredictoDeCitas(
        cumple=resultado.cumple,
        texto_resultante=resultado.texto,
        citas_validas=resultado.citas_validas,
        citas_invalidas=resultado.citas_invalidas,
        remisiones_despojadas=resultado.remisiones_despojadas,
        anclas_degradadas=resultado.anclas_degradadas,
    )


# ─────────────────────────── La vigencia (VAS.2) ───────────────────────────


class VersionEnOtraLengua(BaseModel):
    document_id: uuid.UUID
    url: str
    lengua: str


class DocumentoDesplazado(BaseModel):
    document_id: uuid.UUID
    url: str


class EstadoDeVigencia(BaseModel):
    """Lo que la plataforma sabe de la vigencia de un documento, y qué diría de él.

    `aviso` no es un booleano: es **el texto**. Si cada cliente redactara el suyo a partir de
    `necesita_aviso`, dos superficies de la misma institución acabarían diciendo cosas distintas
    de la misma norma.
    """

    document_id: uuid.UUID
    titulo: str
    url: str
    estat_vigencia: str | None
    vigencia_validada: bool
    vigencia_validada_el: datetime | None
    vigencia_validada_por: str | None
    necesita_aviso: bool
    aviso: str | None
    superseded_por: DocumentoDesplazado | None
    lengua: str
    version_pareja: VersionEnOtraLengua | None


class _ItemParaElAviso:
    """Lo mínimo que `aviso_para` necesita: un título y los metadatos de vigencia.

    Se le pasa un objeto sintético en vez de reimplementar el texto del aviso. Es lo que hace
    que el aviso sea **byte a byte** el del grafo: no hay dos redacciones, hay una función.
    """

    __slots__ = ("title", "metadata")

    def __init__(self, titulo: str, metadatos: dict) -> None:
        self.title = titulo
        self.metadata = metadatos


@router.get(
    "/vigencia",
    response_model=EstadoDeVigencia,
    operation_id="consultarVigencia",
)
async def consultar_vigencia(
    document_id: uuid.UUID | None = Query(default=None),
    url: str | None = Query(default=None, max_length=2048),
    user: UserInfo = Depends(_exige_scope),
    session: AsyncSession = Depends(get_session),
) -> EstadoDeVigencia:
    """Si la plataforma pondría un aviso sobre este documento, y cuál.

    **Acotado por tenencia y por el filtro cerrado.** Sólo documentos de chatbots visibles para
    la organización del token y que pasen `MetadataFilter()` por defecto: público, no desplazado,
    apto para asistentes, y de los que rigen hoy.

    **Lo que no cumple eso devuelve 404, no «no validado».** Un 403 o un «existe pero no puedo
    decirte» confirmarían que el documento existe, y el propio título de la respuesta sería la
    fuga. Es la misma razón por la que la lectura del registro acota en vez de responder «no
    autorizado» con datos dentro.
    """
    if (document_id is None) == (url is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "IDENTIFICA_UN_DOCUMENTO",
                "message": (
                    "Indica `document_id` o `url`, exactamente uno de los dos: con los dos no "
                    "se sabe cuál manda si no coinciden, y sin ninguno no hay nada que mirar."
                ),
            },
        )

    documento = await _documento_verificable(session, user, document_id, url)
    if documento is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "DOCUMENTO_NO_VERIFICABLE",
                "message": (
                    "No hay ningún documento verificable con esa referencia. Puede que no "
                    "exista, que no sea de tu organización o que el corpus no lo ofrezca a los "
                    "asistentes."
                ),
            },
        )

    # El aviso, del motor y no de una copia: `marca_de_vigencia` decide si hace falta y
    # `aviso_para` lo redacta, que son las dos funciones que el grafo usa para hidratar la
    # respuesta.
    metadatos = marca_de_vigencia(documento)
    aviso = aviso_para([_ItemParaElAviso(documento.title, metadatos)])

    return EstadoDeVigencia(
        document_id=documento.id,
        titulo=documento.title,
        url=documento.canonical_url,
        estat_vigencia=documento.estat_vigencia,
        vigencia_validada=documento.vigencia_validada_el is not None,
        vigencia_validada_el=documento.vigencia_validada_el,
        vigencia_validada_por=documento.vigencia_validada_per,
        necesita_aviso=aviso is not None,
        aviso=aviso,
        superseded_por=await _lo_desplaza(session, documento),
        lengua=documento.language,
        version_pareja=await _pareja_de(session, documento),
    )


async def _documento_verificable(
    session: AsyncSession,
    user: UserInfo,
    document_id: uuid.UUID | None,
    url: str | None,
):
    """El documento, si el principal puede recuperarlo. `None` si no, sin distinguir por qué.

    No se distingue a propósito: «no existe», «no es tuyo» y «el corpus no lo ofrece» tienen que
    dar la misma respuesta, porque distinguirlas es decir cuál de las tres es.
    """
    consulta = scope_query_to_orgs(
        select(HubDocument).join(
            HubChatbot, HubChatbot.id == HubDocument.chatbot_id
        ),
        user,
        HubChatbot,
    ).where(*MetadataFilter().document_conditions())

    if document_id is not None:
        consulta = consulta.where(HubDocument.id == document_id)
        return (await session.execute(consulta)).scalars().first()

    # Por URL hace falta normalizar los dos lados: el corpus guarda la canónica tal como la
    # publicó el portal, y quien pregunta trae la que copió de una cita. La barra final, el
    # esquema y el ancla no cambian de qué norma se habla.
    buscada = normalizar_url(url)
    for documento in (await session.execute(consulta)).scalars().all():
        if normalizar_url(documento.canonical_url) == buscada:
            return documento
    return None


async def _pareja_de(session: AsyncSession, documento) -> VersionEnOtraLengua | None:
    """La versión en la otra lengua, mirando **los dos sentidos** de `versio_idiomatica_de`.

    El corpus la declara en un solo lado y cuál es depende de qué se ingirió primero, que no es
    una afirmación sobre nada. Resolverlo en un sentido dejaría la mitad de las parejas sin
    hermana según el orden de la ingesta.
    """
    hermana = (
        (
            await session.execute(
                select(HubDocument).where(
                    or_(
                        HubDocument.id == documento.versio_idiomatica_de,
                        HubDocument.versio_idiomatica_de == documento.id,
                    ),
                    HubDocument.id != documento.id,
                )
            )
        )
        .scalars()
        .first()
    )
    if hermana is None:
        return None
    return VersionEnOtraLengua(
        document_id=hermana.id, url=hermana.canonical_url, lengua=hermana.language
    )


async def _lo_desplaza(session: AsyncSession, documento) -> DocumentoDesplazado | None:
    """Qué norma lo desplaza, si el corpus lo declara.

    Se lee de `doc_metadata['superseded_per']` porque es donde el corpus lo escribe; un
    documento **desplazado entero** no llega aquí —el filtro cerrado lo excluye y la respuesta
    es 404—, así que esto informa del caso en que lo desplazado es una parte.
    """
    referencia = (documento.doc_metadata or {}).get("superseded_per")
    if not isinstance(referencia, dict):
        return None
    otro_id = referencia.get("document_id")
    if not otro_id:
        return None
    try:
        otro_uuid = uuid.UUID(str(otro_id))
    except (ValueError, TypeError):
        return None
    otro = (
        (await session.execute(select(HubDocument).where(HubDocument.id == otro_uuid)))
        .scalars()
        .first()
    )
    if otro is None:
        return None
    return DocumentoDesplazado(document_id=otro.id, url=otro.canonical_url)


# ─────────────────────────── La auditoría de código (VAS.3) ────────────────


class PeticionDeAuditoria(BaseModel):
    """El código a auditar y, si se quiere, para qué.

    `finalidad` va al registro, no al veredicto: la auditoría es determinista y no depende de
    para qué se pida.
    """

    model_config = {"extra": "forbid"}

    codigo: str
    finalidad: str | None = Field(default=None, max_length=500)


class VeredictoDeCodigo(BaseModel):
    """El `AuditResult` del auditor, tal cual, más el hash de lo que se auditó.

    Sin añadir ni quitar nada: la revisión de fuera tiene que ser **la misma** que la de dentro,
    porque si no, pasar por aquí no prueba nada sobre si ese código pasaría el catálogo de
    funciones.
    """

    approved: bool
    risk_level: str
    puede_revisarse: bool
    findings: list[AuditFinding]
    confidence: float
    code_sha256: str


@router.post(
    "/codigo",
    response_model=VeredictoDeCodigo,
    operation_id="auditarCodigo",
)
async def auditar_codigo(
    peticion: PeticionDeAuditoria,
    user: UserInfo = Depends(_exige_scope),
    session: AsyncSession = Depends(get_session),
) -> VeredictoDeCodigo:
    """Audita código que va a correr fuera, con la vara del catálogo de funciones.

    Es la **revisión posterior del nivel 2 de la Instrucció 02/2026** para código que no corre en
    la plataforma: análisis del AST contra una lista blanca de módulos y las capacidades que
    ninguna revisión humana acepta.

    **Esto sí deja evento en el registro de actividad**, a diferencia de las otras dos
    verificaciones. Auditar es un acto de gobernanza y tiene que constar —quién auditó qué hash,
    con qué nivel de riesgo y cuándo—; verificar citas o consultar vigencia son comprobaciones
    sin estado, y un evento por cada una duplicaría el registro sin decir nada nuevo.

    **El código no se guarda: sólo su SHA-256.** Aquí llega, por definición, código que alguien
    está a punto de ejecutar en otro sitio, y guardarlo convertiría el servicio en un repositorio
    de código ajeno que nadie ha decidido tener. El hash permite cotejar después que un fichero
    concreto es el que se auditó, sin tenerlo.
    """
    _dentro_del_limite(peticion.codigo)

    organizacion_id = organizacion_unica_de(user)
    if organizacion_id is None:
        # Sin organización no hay dónde registrar, y auditar sin registrar no es esta operación:
        # el evento es parte del servicio, no un efecto secundario.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "ORGANIZACION_INDETERMINADA",
                "message": (
                    "El token tiene que pertenecer a una sola organización: la auditoría deja "
                    "constancia en su registro de actividad, y no se elige en la petición."
                ),
            },
        )

    resultado = ScriptSecurityAuditor().audit(peticion.codigo)
    huella = hashlib.sha256(peticion.codigo.encode("utf-8")).hexdigest()

    await _registra_la_auditoria(
        session, user, organizacion_id, peticion.finalidad, resultado, huella
    )

    return VeredictoDeCodigo(
        approved=resultado.approved,
        risk_level=resultado.risk_level.value,
        puede_revisarse=resultado.puede_revisarse,
        findings=resultado.findings,
        confidence=resultado.confidence,
        code_sha256=huella,
    )


async def _registra_la_auditoria(
    session: AsyncSession,
    user: UserInfo,
    organizacion_id: uuid.UUID,
    finalidad: str | None,
    resultado,
    huella: str,
) -> None:
    """Escribe el evento REG de la auditoría, con el hash y el nivel de riesgo.

    **El nivel va en `finalidad`, y conviene decir por qué.** El contrato de REG.1 no tiene un
    campo de nivel de riesgo, y el prompt preveía añadirlo. No se añade: sería un campo que sólo
    esta operación rellena, y el contrato es el mismo para toda herramienta que registre — un
    campo específico de un caso de uso lo convierte en un formulario con huecos. Lo que hace
    falta es que el nivel **conste y se pueda buscar**, y la finalidad declarada es exactamente
    el sitio donde un registro de gobernanza cuenta qué pasó.

    Si algún día hay tres consumidores que necesiten el mismo metadato estructurado, entonces sí
    es un campo del contrato y se añade con su migración.
    """
    evento = ActividadIAEvent(
        ocurrido_en=datetime.now(timezone.utc),
        actor=user.user_id,
        herramienta=_HERRAMIENTA_DE_AUDITORIA,
        agente=None,
        finalidad=(
            f"[{resultado.risk_level.value}] "
            f"{finalidad or 'auditoría estática de código'}"
        ),
        modelo_usado=None,
        categorias_datos=[],
        payload_hash=huella,
    )
    session.add(
        HubActividadIA(
            organizacion_id=organizacion_id,
            ocurrido_en=evento.ocurrido_en,
            actor=evento.actor,
            herramienta=evento.herramienta,
            agente=evento.agente,
            finalidad=evento.finalidad,
            modelo_usado=evento.modelo_usado,
            categorias_datos=evento.categorias_datos,
            payload_hash=evento.payload_hash,
        )
    )
    await session.commit()


@router.get(
    "/codigo/reglas",
    response_model=CajaDeHerramientas,
    operation_id="reglasDeAuditoria",
)
async def reglas_de_auditoria(
    _=Depends(_exige_scope),
) -> CajaDeHerramientas:
    """Con qué se puede escribir código que pase la auditoría, y con qué no.

    Se compone **leyendo los `frozenset` del auditor**, no una copia: es lo que permite pedirle a
    la UADTI que contraste la caja de herramientas con las Guías Operativas Técnicas sin que el
    documento y el sistema puedan divergir. Con una lista paralela, se contrastaría un documento
    contra otro documento.

    `version_auditor` cambia si cambia el contenido, para que un cliente sepa si tiene que volver
    a leerla.
    """
    return caja_de_herramientas()
