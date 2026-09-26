"""Reconciliador de corpus curado (ING.0.5). Deploy: edge.

**Una sola implementación de la reconciliación, dos fuentes** (`CorpusSource`): la carpeta
local de hoy y el servicio MCP que añade SYNC.1. Si SYNC.1 reimplementa emparejamiento,
deltas o poda, está mal.

Dos ideas gobiernan el módulo:

- **Lo incremental no es un modo: emerge del hash.** El mismo comando sobre la misma
  carpeta omite lo no cambiado, actualiza metadatos sin re-trocear y re-ingiere solo lo
  modificado.
- **El censo sí es un modo, y es peligroso.** Detectar una retirada exige saber que la
  fuente es el corpus COMPLETO; un `--prune` sobre una subcarpeta retiraría cientos de
  normas. De ahí que la poda exija `is_census()`, sea opt-in y lleve salvaguarda de
  proporción. Y **nunca borra**: marca, porque retirada de la fuente ≠ derogación y esa
  distinción la hace una persona.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.modules.agents_hub.database.operational_models import (
    HubDocument,
    HubIngestionJob,
)
from server.app.modules.agents_hub.ingestion.bilingual_bridge import (
    refrescar_puente_bilingue,
)
from server.app.modules.agents_hub.ingestion.chunk_copier import (
    incoherentes,
    remapea,
    se_puede_copiar,
)
from server.app.modules.agents_hub.ingestion.corpus.frontmatter import hash_markdown_body
from server.app.modules.agents_hub.ingestion.corpus.manifest import CorpusDocumentEntry
from server.app.modules.agents_hub.ingestion.corpus.source import CorpusSource

MOTIU_RETIRADA = "retirada_de_la_font"
UMBRAL_PODA_POR_DEFECTO = 0.10
# SYNC.2: cuánto vale una revisión cuando el front-matter no dice otra cosa. Las normas de
# vigencia anual —el Presupuesto— traen la suya, explícita y más corta.
DIAS_REVISION_POR_DEFECTO = 365

# Campos de la entrada que se materializan como columna en HubDocument (ING.0.2).
_COLUMNAS = (
    "content_class",
    "ambit_principal",
    "nivell_acces",
    "us_assistents",
    "estat_vigencia",
    "revisat_per",
    "revisat_el",
    "vigencia_validada_el",
    "data_revisio_prevista",
    "id_publicacio",
)
_COLUMNAS_ARRAY = ("ambits_secundaris", "submateries", "submateries_internes")
# Campos de la entrada que van a doc_metadata y no a columna.
_A_METADATA = (
    # PUB.3: el nombre del `.md` es el slug de su página en el sitio publicado, y es la
    # única forma de construir `html/<slug>.html#<ancla>`. No se puede derivar de
    # `canonical_url`, que para los documentos publicados es la URL del PDF del portal.
    "relative_path",
    "motiu_exclusio",
    "vigencia_validada_per",
    # ACT.4: la causa de la no vigencia no necesita columna porque NADA filtra por
    # ella. La lee `read_document` para que el asistente pueda decir «derogada por X»
    # en vez de «ya no esta vigente», que son respuestas distintas.
    "motiu_no_vigencia",
    "original_pdf_sha256",
    "converter",
)


#: Columnas del fragmento que se COPIAN tal cual. Fuera quedan `id` (se genera), los tres
#: identificadores que `remapea` reescribe, y `tsv`, que es una columna generada por Postgres.
#: `bilingual_terms` tambien se copia: es del documento, y el mismo documento tiene los mismos.
_COLUMNAS_DEL_FRAGMENTO = (
    "content",
    "source_url",
    "content_hash",
    "embedding",
    "chunk_metadata",
    "language",
    "is_temporary",
    "owner_id",
    "bilingual_terms",
    "embedding_model",
    "embedding_dim",
    "parent_content",
    "embedding_text",
    "embedding_task_type",
)


def _fragmento_a_dict(fragmento) -> dict:
    """El fragmento como lo espera `chunk_copier`, sin los identificadores del origen."""
    return {campo: getattr(fragmento, campo) for campo in _COLUMNAS_DEL_FRAGMENTO}


class CopiaIncoherente(Exception):
    """La copia dejo fragmentos que apuntan al documento de otro chatbot.

    No se continua: una cita con el titulo equivocado no da ningun error y se lee como buena.
    Fueron 14.198 fragmentos del banco agentico antes de que HIB.U lo destapara.
    """


class PruneThresholdExceeded(Exception):
    """La poda afectaría a más documentos de los que el umbral permite sin confirmar."""


@dataclass
class ReconcileReport:
    ingeridos: int = 0
    reingeridos: int = 0
    #: ACT.5 — documentos cuyos fragmentos se copiaron de un gemelo en vez de embeberse.
    copiados: int = 0
    metadatos_actualizados: int = 0
    omitidos: int = 0
    rechazados: int = 0
    retirados: int = 0
    poda_omitida_por_no_censo: bool = False
    motivos_omision: list[str] = field(default_factory=list)
    #: ACT.6 — los cambios que alteran QUE se recupera, uno a uno, para poder confirmarlos.
    cambios_de_estado: list[str] = field(default_factory=list)
    detalle: list[str] = field(default_factory=list)

    def render(self) -> str:
        return (
            f"ingeridos={self.ingeridos} copiados={self.copiados} "
            f"reingeridos={self.reingeridos} "
            f"metadatos={self.metadatos_actualizados} omitidos={self.omitidos} "
            f"rechazados={self.rechazados} retirados={self.retirados}"
        )


def _a_utc(valor):
    """Un `datetime` siempre con zona, en UTC. Lo demás, tal cual.

    ACT.1 — **el defecto que hacía mentir al informe.** Las columnas de fecha son
    `timestamp with time zone` y el front-matter trae fechas desnudas (`revisat_el:
    '2026-08-10'`), así que la comparación era *aware* contra *naive*, y en Python eso NUNCA
    es igual: `datetime(2026,8,10) != datetime(2026,8,10, tzinfo=utc)`. No es un desfase que
    se cure aplicando la pasada, es estructural.

    Medido sobre el corpus real el 2026-08-28: **292 de 292 «actualizaciones de metadatos»
    eran esto**, y con ese ruido las 24 diferencias reales no se veían. No costaba embeddings
    —el hash es del cuerpo—, pero volvía a escribir el puente bilingüe del corpus entero en
    cada pasada y dejaba el informe inservible como instrumento.

    Naive se interpreta como UTC y no como hora local: la fecha viene de un `.md` que declara
    un día, no un instante, y hacerla depender de la zona de la máquina que reconcilia
    convertiría el mismo paquete en dos resultados distintos.
    """
    if isinstance(valor, datetime):
        return (
            valor.replace(tzinfo=timezone.utc)
            if valor.tzinfo is None
            else valor.astimezone(timezone.utc)
        )
    return valor


#: Metadatos que NO vienen del `.md`, y **de que depende conservar cada uno**. Los escribe el
#: panel de vigencia o la propagacion entre hermanas idiomaticas (ACT.6, ACT.9). Sin conservarlos,
#: cada pasada los quitaria y la siguiente los volveria a poner: el ruido que ACT.1 elimino.
#:
#: La condicion es POR CAMPO y no una sola para todos, y ahi hubo un defecto: `data_revisio_des_de`
#: colgaba de «el corpus no declara validacion», que no tiene nada que ver con el. En PLA-003-val
#: —validada Y con la fecha heredada— la condicion se cumplia al reves y la marca se perdia y se
#: reponia en cada pasada.
_METADATOS_QUE_NO_VIENEN_DEL_CORPUS = {
    "vigencia_validada_per": "vigencia_validada_per",
    "vigencia_validada_des_de": "vigencia_validada_per",
    "data_revisio_des_de": "data_revisio_prevista",
}


def _corpus_declara_validacion(entry: CorpusDocumentEntry) -> bool:
    """Si la validación de vigencia viaja con el corpus, o la puso una persona en el panel.

    Los dos sistemas escriben el mismo campo: el panel (`hub_ingestion_router.validar_vigencia`)
    y el front-matter. Hasta ACT.1 ganaba el último en pasar, que era siempre el reconciliador,
    así que **cada pasada borraba la validación humana** y la sustituía por la fecha del `.md`
    —249 documentos del corpus real—. Ahora la regla se dice en voz alta: manda el corpus cuando
    trae `vigencia_validada_per` (es la firma de Secretaría General viajando con el documento);
    si no lo trae, no hay nada que imponer y se conserva lo que hay.
    """
    # Es un campo DECLARADO del contrato (`manifest.py`), no una clave de `extra`:
    # buscarlo en `extra` devolvia siempre False y el corpus nunca ganaba.
    return bool(getattr(entry, "vigencia_validada_per", None))


def _metadata_objetivo(entry: CorpusDocumentEntry, doc: HubDocument | None = None) -> dict:
    """`doc_metadata` que le corresponde a la entrada: `extra` + los campos no-columna."""
    salida = dict(entry.extra)
    for campo in _A_METADATA:
        valor = getattr(entry, campo, None)
        if valor is not None:
            salida[campo] = valor.isoformat() if hasattr(valor, "isoformat") else valor
    if doc is not None:
        for campo, lo_declara_el_corpus in _METADATOS_QUE_NO_VIENEN_DEL_CORPUS.items():
            if getattr(entry, lo_declara_el_corpus, None) is not None:
                continue  # el corpus habla de eso: manda el corpus
            anterior = (doc.doc_metadata or {}).get(campo)
            if anterior:
                salida[campo] = anterior
    return salida


#: Campos cuyo cambio altera QUE se recupera o COMO se cita, y por tanto merecen verse uno a uno
#: antes de aplicar una actualizacion. El resto de metadatos es reetiquetado y no cambia respuestas.
CAMBIOS_QUE_SE_NOTAN = ("us_assistents", "estat_vigencia", "nivell_acces", "content_class")


def cambios_de_estado(doc: HubDocument, entry: CorpusDocumentEntry) -> list[str]:
    """Los cambios que una persona tiene que ver antes de decir que si.

    Sin esto, el informe dice «= (metadatos)» y una norma que se apaga o que deja de estar
    vigente se lee igual que una a la que se le corrige el resumen. Es como las 22 normas
    externas volvieron a encenderse sin que nadie lo decidiera.
    """
    fuera = []
    for campo in CAMBIOS_QUE_SE_NOTAN:
        antes, ahora = getattr(doc, campo, None), getattr(entry, campo, None)
        if antes != ahora:
            fuera.append(f"{campo}: {antes} -> {ahora}")
    return fuera


def _difiere(doc: HubDocument, entry: CorpusDocumentEntry, title: str) -> bool:
    if doc.title != title:
        return True
    for campo in _COLUMNAS:
        # SYNC.2: si la fuente no declara fecha de revisión, no puede estar en desacuerdo
        # con la que el documento ya tiene. Sin esta excepción, el default que se pone al
        # ingerir haría que cada pasada viera una diferencia, la «corrigiera» renovando la
        # fecha y nada venciera jamás.
        if campo == "data_revisio_prevista" and entry.data_revisio_prevista is None:
            continue
        if campo == "vigencia_validada_el" and not _corpus_declara_validacion(entry):
            continue
        if _a_utc(getattr(doc, campo)) != _a_utc(getattr(entry, campo)):
            return True
    for campo in _COLUMNAS_ARRAY:
        if list(getattr(doc, campo) or []) != list(getattr(entry, campo) or []):
            return True
    return (doc.doc_metadata or {}) != _metadata_objetivo(entry, doc)


def _aplicar(doc: HubDocument, entry: CorpusDocumentEntry, title: str) -> None:
    doc.title = title
    for campo in _COLUMNAS:
        if campo == "vigencia_validada_el" and not _corpus_declara_validacion(entry):
            continue
        setattr(doc, campo, _a_utc(getattr(entry, campo)))
    for campo in _COLUMNAS_ARRAY:
        setattr(doc, campo, list(getattr(entry, campo) or []))
    doc.doc_metadata = _metadata_objetivo(entry, doc)
    doc.source_kind = entry.extra.get("source_kind", "publicacio")


def _caducidad_por_defecto(documentos: list[HubDocument]) -> None:
    """SYNC.2 — sin fecha de revision no hay caducidad posible y el documento envejeceria en
    silencio, que es el riesgo nº1 del informe (312 de 314 fichas decian «vigent?»).

    **Va al FINAL, y eso importa (ACT.9).** Estaba dentro de `_aplicar`, asi que se ponia
    documento a documento ANTES de que las hermanas idiomaticas se emparejaran: cuando la
    propagacion llegaba, la hermana ya tenia el defecto de 365 dias puesto y la regla «solo se
    comparte cuando una de las dos lo tiene» la saltaba. `PLA-003` declaraba caducar el
    31-12-2026 y su version valenciana se quedaba con agosto del año siguiente.

    Aqui se aplica cuando ya se ha dicho todo lo que el corpus y el emparejamiento tenian que
    decir, y solo a lo que sigue sin fecha. Renovarla en cada pasada equivaldria a no tenerla,
    asi que nunca se pisa una que ya exista.
    """
    caduca = date.today() + timedelta(days=DIAS_REVISION_POR_DEFECTO)
    for doc in documentos:
        if doc.data_revisio_prevista is None:
            doc.data_revisio_prevista = caduca


def _compartir_lo_que_es_de_la_norma(
    parejas: list[tuple[HubDocument, HubDocument]],
) -> None:
    """Lo que es de la NORMA y no del texto de una lengua, compartido entre las dos versiones.

    Son dos hechos, y los dos se descubrieron por el mismo camino:

    - **Quien la valido y cuando** (ACT.6). Lo que una persona confirma es que la norma rige, y
      eso no depende de en que idioma estaba el ejemplar que tenia delante.
    - **Cuando caduca** (ACT.9). Al declarar que `PLA-003` caduca el 31-12-2026, su version
      valenciana se quedo con el plazo por defecto de 365 dias: nadie la habria vuelto a mirar
      el dia que toca.

    En los dos casos se comparte SOLO cuando una de las dos lo tiene: con las dos declaradas se
    respeta cada una —manda el corpus— y con ninguna, compartir seria fabricar un dato.

    Queda escrito de DONDE viene, para que una auditoria no lo confunda con un dato puesto sobre
    ese ejemplar.
    """
    _compartir(parejas, "vigencia_validada_el", "vigencia_validada_des_de",
               tambien="vigencia_validada_per")
    _compartir(parejas, "data_revisio_prevista", "data_revisio_des_de")


def _compartir(
    parejas: list[tuple[HubDocument, HubDocument]],
    campo: str,
    marca: str,
    tambien: str | None = None,
) -> None:
    """Copia `campo` de la hermana que lo tiene a la que no, y anota de donde vino."""
    for uno, otro in parejas:
        for origen, destino in ((uno, otro), (otro, uno)):
            if getattr(origen, campo) is None or getattr(destino, campo) is not None:
                continue
            setattr(destino, campo, getattr(origen, campo))
            metadatos = dict(destino.doc_metadata or {})
            if tambien:
                valor = (origen.doc_metadata or {}).get(tambien)
                if valor:
                    metadatos[tambien] = valor
            metadatos[marca] = origen.id_publicacio
            destino.doc_metadata = metadatos


class CorpusReconciler:
    """Reconcilia una fuente de corpus contra los documentos de un chatbot."""

    def __init__(self, session: AsyncSession, watcher) -> None:
        self._session = session
        self._watcher = watcher

    async def _buscar(
        self, chatbot_id: uuid.UUID, entry: CorpusDocumentEntry, url: str
    ) -> HubDocument | None:
        """Empareja por `id_publicacio`; si no viene, por url oficial + idioma.

        Y si viene y no encuentra nada, **repesca un documento a medio construir**: ver abajo.
        """
        if entry.id_publicacio:
            stmt = select(HubDocument).where(
                HubDocument.chatbot_id == chatbot_id,
                HubDocument.id_publicacio == entry.id_publicacio,
            )
            doc = (await self._session.execute(stmt.limit(1))).scalar_one_or_none()
            return doc if doc is not None else await self._repescar(chatbot_id, entry, url)
        stmt = select(HubDocument).where(
            HubDocument.chatbot_id == chatbot_id,
            HubDocument.canonical_url == url,
            HubDocument.language == entry.language,
        )
        return (await self._session.execute(stmt.limit(1))).scalar_one_or_none()

    async def _repescar(
        self, chatbot_id: uuid.UUID, entry: CorpusDocumentEntry, url: str
    ) -> HubDocument | None:
        """Un documento que una interrupción dejó a medias, para terminarlo en vez de duplicarlo.

        POR QUÉ HACE FALTA. `_ingerir_nuevo` crea el documento llamando al watcher —la tubería
        compartida con el crawler—, y **el watcher hace `commit` antes de volver**. Sólo después
        se le aplican los metadatos del corpus con `_aplicar`, que es quien pone `id_publicacio`,
        `relative_path` y `source_kind`. Entre las dos cosas hay una ventana, y un proceso que se
        corta ahí deja el documento escrito, con sus fragmentos, y **sin los campos por los que
        aquí se le buscaría**.

        Lo que pasaba entonces era peor que perder el trabajo: ninguna pasada posterior lo
        encontraba, intentaba insertar el suyo y chocaba contra `uq_document_chatbot_hash`. El
        asistente se quedaba con un documento sin metadatos —invisible para los filtros de
        vigencia, ámbito y lengua— y su reingesta no volvía a completarse nunca. Pasó el
        29-08-2026, y la única salida fue borrar el huérfano a mano.

        SÓLO ALCANZA A LOS HUÉRFANOS. La condición `id_publicacio IS NULL` no es una precaución
        de más: sin ella, una entrada podría adoptar el documento de otra que comparta url e
        idioma, y el corpus perdería uno de los dos sin decir nada.
        """
        stmt = select(HubDocument).where(
            HubDocument.chatbot_id == chatbot_id,
            HubDocument.canonical_url == url,
            HubDocument.language == entry.language,
            HubDocument.id_publicacio.is_(None),
        )
        return (await self._session.execute(stmt.limit(1))).scalar_one_or_none()

    async def reconcile(
        self,
        source: CorpusSource,
        chatbot_id: uuid.UUID,
        dry_run: bool = False,
        prune: bool = False,
        force_prune: bool = False,
        prune_threshold: float = UMBRAL_PODA_POR_DEFECTO,
    ) -> ReconcileReport:
        informe = ReconcileReport()

        # list_entries() valida el paquete y aborta ENTERO si algo no cumple el contrato:
        # un corpus a medias hace fallar la validación de documentos de forma aleatoria.
        entradas = await source.list_entries()

        # Los emparejados se llevan en memoria y NO se deducen de last_seen_at: en
        # --dry-run no se estampa nada, y una poda que dependiera del sello creería que
        # no se ha visto ningún documento y propondría retirar el corpus entero.
        emparejados: set[uuid.UUID] = set()
        pendientes_de_enlazar: list[tuple[HubDocument, str]] = []

        for entry in entradas:
            url = entry.source_url
            title = entry.title or entry.relative_path

            if entry.us_assistents == "no":
                informe.omitidos += 1
                informe.motivos_omision.append(
                    f"{entry.relative_path}: us_assistents=no ({entry.motiu_exclusio})"
                )
                continue

            existente = await self._buscar(chatbot_id, entry, url)

            # SYNC.1: si la fuente sabe declarar el hash del cuerpo sin entregarlo —el
            # índice del servicio de publicación lo trae— y coincide con el que ya está
            # guardado, no hay nada que descargar. Es lo que hace que una pasada cueste en
            # proporción a los cambios y no al tamaño del corpus: sin esto, cada sync
            # bajaría los ~10 MB del corpus entero para descubrir que no ha cambiado nada.
            #
            # El atajo es seguro porque compara el hash declarado contra el NUESTRO, que se
            # calculó con `hash_markdown_body`. Un publicador que hashee de otra forma
            # simplemente no acierta nunca: se descarga el cuerpo y se decide con el hash
            # real. Se pierde el ahorro, no la corrección.
            if (
                existente is not None
                and entry.content_hash is not None
                and existente.content_hash == entry.content_hash
            ):
                body, content_hash = None, existente.content_hash
            else:
                body = await source.read_body(entry)
                content_hash = hash_markdown_body(body)

            if existente is None:
                # ACT.5 — si un gemelo de la misma organización ya lo tiene embebido, se copia.
                # En seco no se consulta: el plan diría «copiado» y luego el gemelo podría no
                # estar (el orden del descriptor manda), y prometer un ahorro que no se cumple
                # es peor que no prometerlo.
                copiado = None
                if not dry_run:
                    copiado, motivo = await self._copiar_fragmentos(
                        entry, chatbot_id, content_hash, title, url
                    )
                    if motivo:
                        informe.motivos_omision.append(
                            f"{entry.relative_path}: no se pudo copiar ({motivo}); se embebe"
                        )
                if copiado is not None:
                    informe.copiados += 1
                    informe.detalle.append(f"≈ {entry.relative_path} (copiado de un gemelo)")
                    _aplicar(copiado, entry, title)
                    await self._session.flush()
                    await refrescar_puente_bilingue(self._session, copiado)
                    copiado.last_seen_at = datetime.now(timezone.utc)
                    emparejados.add(copiado.id)
                    if entry.versio_idiomatica_de:
                        pendientes_de_enlazar.append((copiado, entry.versio_idiomatica_de))
                    continue

                informe.ingeridos += 1
                informe.detalle.append(f"+ {entry.relative_path}")
                if not dry_run:
                    doc = await self._ingerir(entry, chatbot_id, body, title, url)
                    emparejados.add(doc.id)
                    if entry.versio_idiomatica_de:
                        pendientes_de_enlazar.append((doc, entry.versio_idiomatica_de))
                continue

            emparejados.add(existente.id)

            if body is not None and existente.content_hash != content_hash:
                informe.reingeridos += 1
                informe.detalle.append(f"~ {entry.relative_path} (contenido)")
                if not dry_run:
                    doc = await self._ingerir(entry, chatbot_id, body, title, url)
                    emparejados.add(doc.id)
                    if entry.versio_idiomatica_de:
                        pendientes_de_enlazar.append((doc, entry.versio_idiomatica_de))
                continue

            # Hash igual: o solo metadatos, o nada. En ninguno de los dos casos se
            # vuelve a trocear ni a embeber — es el invariante de CLAUDE.md §5.
            if _difiere(existente, entry, title):
                informe.metadatos_actualizados += 1
                notables = cambios_de_estado(existente, entry)
                if notables:
                    informe.cambios_de_estado.append(
                        f"{entry.id_publicacio or entry.relative_path}: {'; '.join(notables)}"
                    )
                    informe.detalle.append(
                        f"! {entry.relative_path} ({'; '.join(notables)})"
                    )
                else:
                    informe.detalle.append(f"= {entry.relative_path} (metadatos)")
                if not dry_run:
                    _aplicar(existente, entry, title)
                    # El puente bilingüe vive denormalizado en los chunks (RAG.4). Aquí es
                    # donde se ve que reetiquetar cuesta un UPDATE: ni se trocea ni se
                    # embebe de nuevo.
                    await refrescar_puente_bilingue(self._session, existente)
            else:
                informe.omitidos += 1

            if not dry_run:
                existente.last_seen_at = datetime.now(timezone.utc)
                emparejados.add(existente.id)
                if entry.versio_idiomatica_de:
                    pendientes_de_enlazar.append((existente, entry.versio_idiomatica_de))

        if not dry_run:
            await self._session.flush()
            await self._enlazar_versiones(chatbot_id, pendientes_de_enlazar)
            await self._cerrar_caducidades(emparejados)

        if prune:
            await self._podar(
                chatbot_id, emparejados, informe, dry_run, force_prune,
                prune_threshold, source,
            )

        if not dry_run:
            self._session.add(
                HubIngestionJob(
                    chatbot_id=chatbot_id,
                    status="completed",
                    source_url=f"corpus:{informe.render()}",
                    chunks_processed=informe.ingeridos + informe.reingeridos,
                    error_message=informe.render(),
                )
            )
            await self._session.flush()

        return informe

    async def _gemelo_con_fragmentos(
        self, chatbot_id: uuid.UUID, content_hash: str
    ) -> tuple[HubDocument, list[dict]] | None:
        """Un documento IDENTICO ya embebido en otro chatbot de la MISMA organizacion.

        El corpus no se comparte entre chatbots —cada uno tiene sus filas, y es una decision
        tomada—, pero cuando el documento es el mismo el vector tambien lo es, y volver a
        calcularlo cuesta GPU y horas para obtener el mismo numero.

        **Nunca entre organizaciones**: el corpus de una no alimenta a otra ni para ahorrar.
        """
        from server.app.modules.agents_hub.database.config_models import HubChatbot
        from server.app.modules.agents_hub.database.operational_models import (
            HubDocumentChunk,
        )

        organizacion = await self._session.scalar(
            select(HubChatbot.organizacion_id).where(HubChatbot.id == chatbot_id)
        )
        if organizacion is None:
            return None

        hermanos = select(HubChatbot.id).where(
            HubChatbot.organizacion_id == organizacion, HubChatbot.id != chatbot_id
        )
        candidato = (
            await self._session.execute(
                select(HubDocument)
                .where(
                    HubDocument.content_hash == content_hash,
                    HubDocument.chatbot_id.in_(hermanos),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if candidato is None:
            return None

        # recorrido-acotado: los fragmentos de UN documento, no de la tabla. El mayor del
        # corpus es la Ley 9/2017 con 4.330, y hacen falta todos porque lo que se copia al
        # gemelo es el documento entero: partirlo dejaria una copia incompleta, que es peor
        # que no copiarla (issue #159).
        filas = (
            await self._session.execute(
                select(HubDocumentChunk).where(
                    HubDocumentChunk.document_id == candidato.id
                )
            )
        ).scalars().all()
        if not filas:
            return None
        return candidato, [_fragmento_a_dict(f) for f in filas]

    async def _copiar_fragmentos(
        self,
        entry: CorpusDocumentEntry,
        chatbot_id: uuid.UUID,
        content_hash: str,
        title: str,
        url: str,
    ) -> tuple[HubDocument | None, str | None]:
        """El documento destino con los fragmentos del gemelo, o (None, motivo)."""
        from server.app.modules.agents_hub.agent.public_graphs.core.config_resolver import (
            get_effective_public_graph_config,
        )
        from server.app.modules.agents_hub.database.operational_models import (
            HubDocumentChunk,
        )

        gemelo = await self._gemelo_con_fragmentos(chatbot_id, content_hash)
        if gemelo is None:
            return None, None
        origen, fragmentos = gemelo

        # El permiso se decide sobre los DATOS y no sobre la configuracion (HIB.N): la
        # configuracion de Normativa dice 8.000 tokens y sus fragmentos tienen padres de
        # 59.172, porque se trocearon antes de que HIB.L fijara ese techo.
        try:
            cfg = await get_effective_public_graph_config(chatbot_id, self._session)
            estrategia = str(cfg.chunking_strategy)
            techo = int(getattr(cfg, "parent_max_tokens", 8000) or 8000)
        except Exception:  # pragma: no cover - sin config no se arriesga una copia
            return None, "no se pudo resolver la configuracion de troceado del destino"

        veredicto = se_puede_copiar(
            hash_origen=origen.content_hash,
            hash_destino=content_hash,
            estrategia_destino=estrategia,
            techo_destino=techo,
            fragmentos=fragmentos,
        )
        if not veredicto.copiable:
            return None, veredicto.motivo

        doc = HubDocument(
            chatbot_id=chatbot_id,
            title=title,
            canonical_url=url,
            markdown_content=origen.markdown_content,
            content_hash=content_hash,
            language=entry.language,
            source_kind=entry.extra.get("source_kind", "publicacio"),
            token_count=origen.token_count,
        )
        self._session.add(doc)
        await self._session.flush()

        copiados = [
            remapea(fragmento, chatbot_id=chatbot_id, document_id=doc.id)
            for fragmento in fragmentos
        ]
        # HIB.U — «un invariante que solo se comprueba donde se sospecha no es un invariante»:
        # se comprueba SIEMPRE, y aqui es donde de verdad puede romperse. Va ANTES del `add`,
        # asi que un fallo no llega ni a escribirse.
        malos = incoherentes(copiados)
        if malos:
            raise CopiaIncoherente(
                f"{len(malos)} de {len(copiados)} fragmentos copiados de "
                f"{origen.id_publicacio} a {chatbot_id} apuntan al documento del origen. "
                "La agrupacion por documento leeria las filas del otro corpus y la cita saldria "
                "con el titulo equivocado, sin ningun error."
            )
        for fragmento in copiados:
            self._session.add(HubDocumentChunk(**fragmento))
        await self._session.flush()
        return doc, None

    async def _ingerir(
        self,
        entry: CorpusDocumentEntry,
        chatbot_id: uuid.UUID,
        body: str,
        title: str,
        url: str,
    ) -> HubDocument:
        """Passthrough: el cuerpo ya viene sin front-matter y NO se llama a Docling."""
        doc, _ = await self._watcher.process_source(
            source_url=url,
            chatbot_id=chatbot_id,
            language=entry.language,
            citation_url=url,
            prefetched_content=body,
            title=title,
        )
        # Los metadatos se aplican aquí y no en el watcher: el watcher es la tubería
        # compartida con el crawler y no tiene por qué conocer el contrato del corpus.
        _aplicar(doc, entry, title)
        # Y por eso mismo hay que refrescar el puente bilingüe después: al trocear, el
        # documento todavía no tenía `termes_bilingues`, así que los chunks nacieron sin él.
        await self._session.flush()
        await refrescar_puente_bilingue(self._session, doc)
        doc.last_seen_at = datetime.now(timezone.utc)
        return doc

    async def _enlazar_versiones(
        self, chatbot_id: uuid.UUID, pendientes: list[tuple[HubDocument, str]]
    ) -> None:
        """Resuelve `versio_idiomatica_de` de referencia (id_publicacio) a UUID."""
        if not pendientes:
            return
        referencias = {ref for _, ref in pendientes}
        filas = await self._session.execute(
            select(HubDocument).where(
                HubDocument.chatbot_id == chatbot_id,
                HubDocument.id_publicacio.in_(referencias),
            )
        )
        por_id_completo = list(filas.scalars().all())
        por_id_completo_por_publicacio = {d.id_publicacio: d for d in por_id_completo}
        emparejadas: list[tuple[HubDocument, HubDocument]] = []
        for doc, ref in pendientes:
            hermana = por_id_completo_por_publicacio.get(ref)
            if hermana is not None and hermana.id != doc.id:
                doc.versio_idiomatica_de = hermana.id
                emparejadas.append((doc, hermana))
        await self._session.flush()
        _compartir_lo_que_es_de_la_norma(emparejadas)
        await self._session.flush()

    async def _cerrar_caducidades(self, ids: set[uuid.UUID]) -> None:
        """El defecto de SYNC.2, ya con el emparejamiento resuelto."""
        if not ids:
            return
        filas = await self._session.execute(
            select(HubDocument).where(HubDocument.id.in_(ids))
        )
        _caducidad_por_defecto(list(filas.scalars().all()))
        await self._session.flush()

    async def _podar(
        self,
        chatbot_id: uuid.UUID,
        emparejados: set[uuid.UUID],
        informe: ReconcileReport,
        dry_run: bool,
        force_prune: bool,
        umbral: float,
        source: CorpusSource,
    ) -> None:
        if not source.is_census():
            # Un delta no puede distinguir «retirada» de «no tocada».
            informe.poda_omitida_por_no_censo = True
            return

        todos = (
            await self._session.execute(
                select(HubDocument).where(HubDocument.chatbot_id == chatbot_id)
            )
        ).scalars().all()
        candidatos = [
            d for d in todos if d.us_assistents != "no" and d.id not in emparejados
        ]
        if not candidatos:
            return

        if not force_prune and len(candidatos) > umbral * max(1, len(todos)):
            raise PruneThresholdExceeded(
                f"La poda afectaria a {len(candidatos)} de {len(todos)} documentos "
                f"({len(candidatos) / len(todos):.0%}), por encima del umbral "
                f"({umbral:.0%}). Si es correcto, repite con --force-prune. Si no lo es, "
                "revisa que --dir apunte al corpus completo."
            )

        informe.retirados = len(candidatos)
        for doc in candidatos:
            informe.detalle.append(f"- {doc.id_publicacio or doc.canonical_url} (retirado)")
            if dry_run:
                continue
            # NUNCA se borra: retirada de la fuente ≠ derogación.
            doc.us_assistents = "no"
            doc.doc_metadata = {**(doc.doc_metadata or {}), "motiu_exclusio": MOTIU_RETIRADA}
        if not dry_run:
            await self._session.flush()
