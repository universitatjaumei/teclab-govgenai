"""Carga del vocabulario controlado desde CSV (ING.0.1).

Deploy: cloud — escribe configuración institucional.

Uso:
    uv run python -m server.app.modules.agents_hub.vocabulary.load \
        --axis ambit --csv <ruta>/vocabulari/ambits.csv --organizacion-id <uuid>
    uv run python -m server.app.modules.agents_hub.vocabulary.load \
        --axis submateria --csv <ruta>/vocabulari/submateries.csv --organizacion-id <uuid>

Idempotente por la clave natural (organizacion_id, axis, codi): la segunda pasada no
duplica y reporta «sin cambios». Un CSV con un `parent_codi` inexistente se rechaza
ENTERO, sin escribir nada: cargar a medias dejaría el vocabulario incoherente y la
validación de documentos empezaría a fallar de forma aleatoria.
"""
from __future__ import annotations

import argparse
from collections.abc import Sequence
import asyncio
import csv
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.modules.agents_hub.services.vocabulary_service import (
    VocabularyAxis,
    VocabularyTermDTO,
)

_RESTKEY = "__extra__"

# Columnas de nombre según el eje. El resto del CSV (asistente, propietario,
# recuentos, normas de ejemplo) es documentación del informe de materias y no
# entra en el hub.
_DESCRIPTION_COLUMNS = ("descripcio_router", "abast")


class VocabularyCsvError(Exception):
    """El CSV o la operación de carga no son válidos."""


@dataclass(frozen=True)
class VocabularyLoadReport:
    created: int = 0
    updated: int = 0
    unchanged: int = 0

    def render(self) -> str:
        return (
            f"creados={self.created} actualizados={self.updated} "
            f"sin_cambios={self.unchanged}"
        )


class VocabularyStore(Protocol):
    """Persistencia de términos. Aísla la carga de SQLAlchemy para poder testearla."""

    async def fetch(
        self, axis: str, organizacion_id: uuid.UUID
    ) -> list[VocabularyTermDTO]: ...

    async def create(self, term: VocabularyTermDTO, organizacion_id: uuid.UUID) -> None: ...

    async def update(self, term: VocabularyTermDTO, organizacion_id: uuid.UUID) -> None: ...


# ───────────────────────── Parseo ─────────────────────────


def _pick(row: dict[str, str | None], *names: str) -> str | None:
    for name in names:
        value = row.get(name)
        if value and value.strip():
            return value.strip()
    return None


def parse_vocabulary_csv(path: Path | str, axis: str) -> list[VocabularyTermDTO]:
    """Lee un CSV de vocabulario (`;` como separador) y devuelve los términos.

    El `ordre` sale del orden del fichero: es el que decide cómo se presenta el
    índice del router.
    """
    path = Path(path)
    terms: list[VocabularyTermDTO] = []

    # utf-8-sig: los CSV vienen de Excel y traen BOM.
    # restkey: 'normes_exemple' lleva comas sin comillas en el fichero real, así que
    # la última columna se desborda en campos extra que hay que absorber sin romper.
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";", restkey=_RESTKEY)
        if not reader.fieldnames or "codi" not in reader.fieldnames:
            raise VocabularyCsvError(
                f"{path.name}: falta la columna obligatoria 'codi' "
                f"(cabeceras: {reader.fieldnames})"
            )

        for position, row in enumerate(reader):
            codi = _pick(row, "codi")
            if not codi:
                raise VocabularyCsvError(
                    f"{path.name}: fila {position + 2} sin 'codi'"
                )
            nom_primari = _pick(row, "nom_val", "nom", "nom_primari")
            if not nom_primari:
                raise VocabularyCsvError(
                    f"{path.name}: el término '{codi}' no tiene nombre"
                )
            terms.append(
                VocabularyTermDTO(
                    axis=axis,
                    codi=codi,
                    nom_primari=nom_primari,
                    nom_secundari=_pick(row, "nom_es", "nom_secundari"),
                    parent_codi=_pick(row, "ambit", "parent_codi"),
                    descripcio_router=_pick(row, *_DESCRIPTION_COLUMNS),
                    ordre=position,
                )
            )

    if not terms:
        raise VocabularyCsvError(f"{path.name}: no contiene ningún término")

    duplicados = {t.codi for t in terms if [x.codi for x in terms].count(t.codi) > 1}
    if duplicados:
        raise VocabularyCsvError(
            f"{path.name}: códigos duplicados: {sorted(duplicados)}"
        )
    return terms


# ───────────────────────── Aplicación ─────────────────────────


def _differs(new: VocabularyTermDTO, old: VocabularyTermDTO) -> bool:
    return (
        new.nom_primari != old.nom_primari
        or new.nom_secundari != old.nom_secundari
        or new.parent_codi != old.parent_codi
        or new.descripcio_router != old.descripcio_router
        or new.ordre != old.ordre
    )


async def _assert_parents_exist(
    store: VocabularyStore, terms: list[VocabularyTermDTO], organizacion_id: uuid.UUID
) -> None:
    parents = {t.parent_codi for t in terms if t.parent_codi}
    if not parents:
        return
    known = {t.codi for t in await store.fetch(VocabularyAxis.AMBIT, organizacion_id)}
    dangling = sorted(parents - known)
    if dangling:
        raise VocabularyCsvError(
            "Los siguientes 'parent_codi' no existen en el eje 'ambit' y el CSV se "
            f"rechaza entero: {dangling}. Carga primero los ámbitos."
        )


async def apply_terms(
    store: VocabularyStore,
    terms: list[VocabularyTermDTO],
    organizacion_id: uuid.UUID,
    dry_run: bool = False,
) -> VocabularyLoadReport:
    """Reconcilia los términos del CSV contra los almacenados.

    Valida los padres ANTES de escribir nada: un vocabulario a medias es peor que
    uno no cargado.
    """
    await _assert_parents_exist(store, terms, organizacion_id)

    axis = terms[0].axis
    existing = {t.codi: t for t in await store.fetch(axis, organizacion_id)}

    created = updated = unchanged = 0
    for term in terms:
        current = existing.get(term.codi)
        if current is None:
            created += 1
            if not dry_run:
                await store.create(term, organizacion_id)
        elif _differs(term, current):
            updated += 1
            if not dry_run:
                # Se preserva el estado de vigencia/sustitución: lo gobierna
                # supersede_term, no el CSV.
                await store.update(
                    VocabularyTermDTO(
                        **{
                            **term.__dict__,
                            "vigent": current.vigent,
                            "substituit_per_codi": current.substituit_per_codi,
                        }
                    ),
                    organizacion_id,
                )
        else:
            unchanged += 1

    return VocabularyLoadReport(created=created, updated=updated, unchanged=unchanged)


async def supersede_term(
    store: VocabularyStore,
    axis: str,
    codi_antic: str,
    codi_nou: str,
    organizacion_id: uuid.UUID,
) -> None:
    """Marca `codi_antic` como sustituido por `codi_nou` (renombrado o fusión).

    **No toca los documentos, y por eso casi nunca se llama a solas**: para eso está
    `sustituir_termino`, que hace las dos mitades. Dejar el vocabulario marcado y los documentos
    sin barrer es la avería silenciosa de la issue #153 — la búsqueda por el código nuevo no los
    encuentra, la del viejo apunta a un término retirado, y nada da error.
    """
    if codi_antic == codi_nou:
        raise VocabularyCsvError("Un término no puede sustituirse por sí mismo")

    terms = {t.codi: t for t in await store.fetch(axis, organizacion_id)}
    if codi_antic not in terms:
        raise VocabularyCsvError(f"El término '{codi_antic}' no existe en '{axis}'")
    if codi_nou not in terms:
        raise VocabularyCsvError(
            f"El sustituto '{codi_nou}' no existe en '{axis}': créalo antes de "
            "retirar el término antiguo"
        )

    old = terms[codi_antic]
    await store.update(
        VocabularyTermDTO(
            **{**old.__dict__, "vigent": False, "substituit_per_codi": codi_nou}
        ),
        organizacion_id,
    )



async def sustituir_termino(
    session: AsyncSession,
    *,
    axis: str,
    codi_antic: str,
    codi_nou: str,
    organizacion_id: uuid.UUID,
    chatbot_ids: Sequence[uuid.UUID],
) -> int:
    """Renombra o fusiona un término **y reclasifica los documentos que lo usaban**.

    Devuelve cuántos documentos se tocaron. Las dos mitades existían desde ING.0.1 e ING.0.2 y
    **ninguna tenía quien la llamara** (issue #153): la guía de carga mandaba al operador a
    `supersede_term`, que no es alcanzable desde ningún CLI ni router. Van juntas aquí porque
    separadas vuelven a poder correr a medias, y correr a medias no da ningún error: el término
    queda retirado y los documentos siguen clasificados con el código viejo.

    **El orden no es indiferente.** Primero el vocabulario, que es quien valida que el sustituto
    existe; después el barrido. Al revés, un código mal escrito dejaría los documentos apuntando
    a un término inexistente, y eso no se nota hasta que una consulta no devuelve nada.

    Los ejes que no gobiernan columnas de `hub_documents` —`rang`, `colectiu`, que viven en
    `doc_metadata` y no dirigen la recuperación— se sustituyen igual y devuelven 0: que no haya
    nada que barrer no puede impedir renombrar.

    **El ámbito entra por parámetro y no se descubre aquí** (segunda revisión de la PR #179). La
    versión anterior consultaba `HubChatbot` —un modelo de **configuración**— para resolver los
    chatbots de la organización, y a continuación escribía `HubDocument`, que es **operacional**.
    En un despliegue partido cloud/edge esas dos bases no son la misma, así que esa función sólo
    podía correr donde están las dos: en modo `all`. Recibiendo el ámbito, la parte que barre
    documentos se puede ejecutar donde están los documentos.

    Quien compone la operación —hoy el CLI— es quien resuelve el ámbito y lo pasa. Es también
    mejor diseño al margen de la frontera: **el ámbito de un `UPDATE` masivo es una entrada de la
    operación, no algo que la operación averigua**.

    **Precondición que esta función no puede comprobar**: `chatbot_ids` tiene que ser el ámbito
    de `organizacion_id`. Aquí no hay forma de validarlo sin leer configuración, que es lo que la
    frontera prohíbe, así que lo garantiza quien compone. Hoy sólo compone el CLI, y lo resuelve
    por consulta; no hay manera de pasarle un ámbito a mano, y el motivo está en `_chatbots_de`.
    """
    from server.app.modules.agents_hub.services.corpus_reclassifier import (
        AXES_BARRIBLES,
        reclassify_documents,
    )

    await supersede_term(
        SqlAlchemyVocabularyStore(session), axis, codi_antic, codi_nou, organizacion_id
    )

    if axis not in AXES_BARRIBLES:
        return 0

    return await reclassify_documents(
        session, axis, codi_antic, codi_nou, chatbot_ids=list(chatbot_ids)
    )


# ───────────────────────── Store real ─────────────────────────


class SqlAlchemyVocabularyStore:
    """Implementación de `VocabularyStore` sobre la BD de configuración."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def fetch(
        self, axis: str, organizacion_id: uuid.UUID
    ) -> list[VocabularyTermDTO]:
        from server.app.modules.agents_hub.database.config_models import (
            HubVocabularyTerm,
        )

        result = await self.session.execute(
            select(HubVocabularyTerm).where(
                HubVocabularyTerm.organizacion_id == organizacion_id,
                HubVocabularyTerm.axis == axis,
            )
        )
        return [_to_dto(row) for row in result.scalars().all()]

    async def create(
        self, term: VocabularyTermDTO, organizacion_id: uuid.UUID
    ) -> None:
        from server.app.modules.agents_hub.database.config_models import (
            HubVocabularyTerm,
        )

        self.session.add(
            HubVocabularyTerm(
                organizacion_id=organizacion_id,
                axis=term.axis,
                codi=term.codi,
                nom_primari=term.nom_primari,
                nom_secundari=term.nom_secundari,
                parent_codi=term.parent_codi,
                descripcio_router=term.descripcio_router,
                ordre=term.ordre,
                vigent=term.vigent,
                substituit_per_codi=term.substituit_per_codi,
            )
        )
        await self.session.flush()

    async def update(
        self, term: VocabularyTermDTO, organizacion_id: uuid.UUID
    ) -> None:
        from datetime import datetime, timezone

        from server.app.modules.agents_hub.database.config_models import (
            HubVocabularyTerm,
        )

        result = await self.session.execute(
            select(HubVocabularyTerm).where(
                HubVocabularyTerm.organizacion_id == organizacion_id,
                HubVocabularyTerm.axis == term.axis,
                HubVocabularyTerm.codi == term.codi,
            )
        )
        row = result.scalars().first()
        if row is None:
            raise VocabularyCsvError(f"No existe el término '{term.codi}' a actualizar")

        row.nom_primari = term.nom_primari
        row.nom_secundari = term.nom_secundari
        row.parent_codi = term.parent_codi
        row.descripcio_router = term.descripcio_router
        row.ordre = term.ordre
        row.vigent = term.vigent
        row.substituit_per_codi = term.substituit_per_codi
        row.updated_at = datetime.now(timezone.utc)
        await self.session.flush()


def _to_dto(row) -> VocabularyTermDTO:
    return VocabularyTermDTO(
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


# ───────────────────────── CLI ─────────────────────────


async def _run(args: argparse.Namespace) -> int:
    # Mismo patrón que app/scripts/bootstrap.py (11.3): motor y factoría propios,
    # porque el CLI vive fuera del ciclo de vida de FastAPI.
    from server.app.modules.agents_hub.database.connection import (
        create_async_engine,
        create_session_factory,
    )

    if args.substituir:
        return await _run_sustitucion(args)

    try:
        terms = parse_vocabulary_csv(args.csv, args.axis)
    except VocabularyCsvError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"{Path(args.csv).name}: {len(terms)} términos leídos (eje '{args.axis}')")

    engine = create_async_engine()
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            store = SqlAlchemyVocabularyStore(session)
            try:
                report = await apply_terms(
                    store, terms, args.organizacion_id, dry_run=args.dry_run
                )
            except VocabularyCsvError as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 1
            if args.dry_run:
                print(f"[dry-run] {report.render()} (nada escrito)")
            else:
                await session.commit()
                print(report.render())
    finally:
        await engine.dispose()
    return 0


async def _chatbots_de(session: AsyncSession, organizacion_id: uuid.UUID) -> list[uuid.UUID]:
    """Los chatbots de la organización, que es el ámbito de sus documentos.

    Vive en el CLI y no en `sustituir_termino` porque aquí es donde se compone la operación: la
    consulta toca **configuración** y el barrido toca lo **operacional**.

    **Hubo un `--chatbot-id` para saltarse esta consulta y se retiró en cuanto se escribió**
    (revisión de la PR #181). La idea era que un despliegue partido cloud/edge pudiera barrer
    desde donde están los documentos, sin leer configuración. Pero `reclassify_documents` filtra
    **sólo** por los UUID que recibe y `hub_documents` no lleva `organizacion_id`, así que
    `--organizacion-id A --chatbot-id B` marcaba el término de A y reescribía los documentos de
    B: la fuga entre organizaciones que la ronda anterior había cerrado, reabierta por la puerta
    de atrás.

    Y comprobar que esos chatbots son de esa organización exige leer configuración, que es
    precisamente lo que aquel despliegue no tiene a mano. La bandera no podía ser a la vez
    «ejecutable sin configuración» y «comprobada contra la configuración».

    Así que el ámbito sale de aquí y de ningún otro sitio. El día que exista un despliegue
    partido de verdad, esta operación necesita un diseño en la frontera de sincronización, no una
    bandera — y ese día no ha llegado, así que no se anticipa.
    """
    from server.app.modules.agents_hub.database.config_models import HubChatbot

    filas = await session.execute(
        select(HubChatbot.id).where(HubChatbot.organizacion_id == organizacion_id)
    )
    return list(filas.scalars().all())


async def _run_sustitucion(args: argparse.Namespace) -> int:
    """El modo «renombrar o fusionar», que es el que no existía (issue #153).

    En `--dry-run` no se escribe nada: la transacción se deshace después de contar, que es la
    única forma de decir cuántos documentos se tocarían sin tocarlos.
    """
    from server.app.modules.agents_hub.database.connection import (
        create_async_engine,
        create_session_factory,
    )

    engine = create_async_engine()
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            try:
                chatbot_ids = await _chatbots_de(session, args.organizacion_id)
                tocados = await sustituir_termino(
                    session,
                    axis=args.axis,
                    codi_antic=args.substituir,
                    codi_nou=args.per,
                    organizacion_id=args.organizacion_id,
                    chatbot_ids=chatbot_ids,
                )
            except VocabularyCsvError as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 1
            if args.dry_run:
                await session.rollback()
                print(
                    f"[dry-run] '{args.substituir}' → '{args.per}' en el eje '{args.axis}': "
                    f"{tocados} documento(s) se reclasificarían (nada escrito)"
                )
            else:
                await session.commit()
                print(
                    f"'{args.substituir}' → '{args.per}' en el eje '{args.axis}': "
                    f"término marcado como sustituido y {tocados} documento(s) reclasificados"
                )
    finally:
        await engine.dispose()
    return 0


def _construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Vocabulario controlado del corpus: carga un CSV, o renombra/fusiona un término "
            "reclasificando los documentos que lo usaban."
        )
    )
    parser.add_argument(
        "--axis",
        required=True,
        choices=[a.value for a in VocabularyAxis],
        help="Eje del vocabulario",
    )
    parser.add_argument("--csv", help="Ruta del CSV a cargar")
    parser.add_argument(
        "--organizacion-id",
        required=True,
        type=uuid.UUID,
        dest="organizacion_id",
        help="Organización destino",
    )
    parser.add_argument(
        "--substituir",
        metavar="CODI_ANTIC",
        help="Código a retirar. Exige `--per` y excluye `--csv`",
    )
    parser.add_argument(
        "--per",
        metavar="CODI_NOU",
        help="Código que sustituye al anterior",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Reporta el plan sin escribir"
    )
    return parser


def _validar_modo(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    """Un modo o el otro, nunca los dos ni ninguno.

    Se comprueba a mano y no con `add_mutually_exclusive_group` porque `--substituir` necesita
    además a `--per`, y eso argparse no lo sabe expresar.
    """
    if bool(args.csv) == bool(args.substituir):
        parser.error("elige `--csv` para cargar o `--substituir ... --per ...` para renombrar")
    if args.substituir and not args.per:
        parser.error("`--substituir` necesita `--per CODI_NOU`")
    if args.per and not args.substituir:
        parser.error("`--per` sólo tiene sentido con `--substituir`")


def main(argv: list[str] | None = None) -> int:
    parser = _construir_parser()
    args = parser.parse_args(argv)
    _validar_modo(parser, args)
    return asyncio.run(_run(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
