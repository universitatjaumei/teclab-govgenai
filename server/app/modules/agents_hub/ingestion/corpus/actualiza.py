"""Actualizar el corpus de varios asistentes con un comando (ACT.6). Deploy: edge.

**Por qué existe.** `load.py` carga UN paquete en UNO o varios chatbots, y eso obliga a
recordar el orden, los UUID y qué flags llevaba cada llamada. La actualización del 27-08-2026
eran dos paquetes y cuatro asistentes; hacerla a mano es donde se cuela un `--chatbot-id`
equivocado o se olvida el segundo paquete y un asistente se queda atrás sin que nadie lo note
—que es exactamente lo que `detectar_divergencias` lleva denunciando desde DER.2—.

**Las tres cosas que hace y `load.py` no.**

1. **Todo en seco primero.** Los dos paquetes, los cuatro asistentes, antes de escribir nada.
   Descubrir un problema del segundo paquete con el primero ya cargado deja una pasada que no
   se puede repetir limpia.
2. **La confirmación separa lo que cambia de estado.** Un `= (metadatos)` se lee igual tanto si
   se corrige un resumen como si una norma se apaga o deja de estar vigente. Aquí van en su
   propio bloque, uno a uno. Es como las 22 normas externas volvieron a encenderse en el
   asistente normativo sin que nadie lo hubiera decidido.
3. **El orden del descriptor manda, y ese orden ahorra.** Con Normativa delante, Gerencia copia
   sus fragmentos en vez de embeberlos (ACT.5). Al revés se paga dos veces.

El descriptor lleva UUID de una instancia concreta, así que vive fuera del repositorio —en
`_local/`— y se pasa por argumento:

    paquetes:
      - nom: normatiu
        dir: <ruta>/generat/ingesta/normatiu
        chatbots: [d18ffad7-...]
      - nom: gerencia
        dir: <ruta>/generat/ingesta/gerencia
        chatbots: [722aaa10-..., 31847e6f-..., a47f8f83-...]

Uso:
    uv run python -m server.app.modules.agents_hub.ingestion.corpus.actualiza \\
        --descriptor _local/corpus_uji.yaml
    uv run python -m ... --descriptor _local/corpus_uji.yaml --confirmar
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

import yaml

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


@dataclass(frozen=True)
class Paquete:
    nom: str
    dir: Path
    chatbots: tuple[uuid.UUID, ...]


class DescriptorInvalido(Exception):
    """El descriptor no dice lo que hace falta para actualizar nada."""


def leer_descriptor(path: Path | str) -> list[Paquete]:
    """Los paquetes en el ORDEN en que se van a aplicar. El orden es parte del descriptor."""
    datos = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    crudos = datos.get("paquetes")
    if not crudos:
        raise DescriptorInvalido("el descriptor no declara ningun paquete")

    paquetes: list[Paquete] = []
    vistos: set[uuid.UUID] = set()
    for i, crudo in enumerate(crudos):
        nom = str(crudo.get("nom") or f"paquete-{i + 1}")
        directorio = crudo.get("dir")
        if not directorio:
            raise DescriptorInvalido(f"{nom}: falta `dir`")
        if not Path(directorio).is_dir():
            raise DescriptorInvalido(f"{nom}: `dir` no es un directorio: {directorio}")
        chatbots = crudo.get("chatbots") or []
        if not chatbots:
            raise DescriptorInvalido(f"{nom}: no declara ningun chatbot")
        try:
            ids = tuple(uuid.UUID(str(c)) for c in chatbots)
        except ValueError as exc:
            raise DescriptorInvalido(f"{nom}: un chatbot no es un UUID ({exc})") from exc
        # Un chatbot en dos paquetes es casi siempre un error de copiar y pegar, y su efecto
        # —la segunda pasada retira lo que la primera acaba de poner, si alguna lleva censo—
        # no se ve hasta que alguien echa en falta media normativa.
        repetidos = vistos.intersection(ids)
        if repetidos:
            raise DescriptorInvalido(
                f"{nom}: {sorted(map(str, repetidos))} ya estaba en un paquete anterior"
            )
        vistos.update(ids)
        paquetes.append(Paquete(nom=nom, dir=Path(directorio), chatbots=ids))
    return paquetes


def resumen(nom: str, chatbot_id, informe) -> str:
    """Los cuatro bloques, separados. Es lo que se lee antes de decir que si."""
    lineas = [f"  {nom} → {chatbot_id}"]
    nuevos = [d for d in informe.detalle if d.startswith("+ ")]
    copiados = [d for d in informe.detalle if d.startswith("≈ ")]
    cambiados = [d for d in informe.detalle if d.startswith("~ ")]

    def bloque(titulo: str, filas: list[str], limite: int = 12) -> None:
        if not filas:
            return
        lineas.append(f"    {titulo} ({len(filas)})")
        for fila in filas[:limite]:
            lineas.append(f"      {fila}")
        if len(filas) > limite:
            lineas.append(f"      … y {len(filas) - limite} mas")

    bloque("NUEVOS, se embeben", nuevos)
    bloque("NUEVOS, se copian de un gemelo", copiados)
    bloque("CUERPO CAMBIADO, se vuelven a embeber", cambiados)
    # Sin limite: es el bloque por el que se mira el plan.
    bloque("CAMBIOS DE ESTADO — que se recupera o como se cita",
           informe.cambios_de_estado, limite=10_000)
    if informe.metadatos_actualizados:
        lineas.append(
            f"    metadatos sin efecto en la recuperacion: {informe.metadatos_actualizados}"
        )
    lineas.append(f"    {informe.render()}")
    return "\n".join(lineas)


async def _pasada(
    paquetes: list[Paquete], *, dry_run: bool, verbose: bool, sense_diari: bool = False
):
    """Reconcilia todos los paquetes y devuelve {(nom, chatbot_id): informe}."""
    from server.app.core import config  # noqa: F401
    from server.app.modules.agents_hub.database.config_models import HubChatbot
    from server.app.modules.agents_hub.database.connection import (
        create_async_engine,
        create_session_factory,
    )
    from server.app.modules.agents_hub.ingestion.corpus.manifest import (
        CorpusValidationError,
        assert_vocabulary,
    )
    from server.app.modules.agents_hub.ingestion.corpus.reconciler import CorpusReconciler
    from server.app.modules.agents_hub.ingestion.corpus.source import LocalDirectorySource
    from server.app.modules.agents_hub.ingestion.watcher import IngestionWatcher
    from server.app.modules.agents_hub.services.config_provider import LocalConfigProvider
    from server.app.modules.agents_hub.services.embedding_resolver import (
        resolve_embedding_service,
    )
    from server.app.modules.agents_hub.services.vocabulary_service import VocabularyService

    engine = create_async_engine()
    session_factory = create_session_factory(engine)
    informes: dict[tuple[str, uuid.UUID], object] = {}
    try:
        async with session_factory() as session:
            provider = LocalConfigProvider(session)
            for paquete in paquetes:
                fuente = LocalDirectorySource(paquete.dir)
                entradas = await fuente.list_entries()
                print(f"{paquete.nom}: {len(entradas)} entradas de {paquete.dir}")

                for chatbot_id in paquete.chatbots:
                    chatbot = await session.get(HubChatbot, chatbot_id)
                    if chatbot is None:
                        raise DescriptorInvalido(f"no existe el chatbot {chatbot_id}")
                    vocabulario = VocabularyService(
                        source=provider, organizacion_id=chatbot.organizacion_id
                    )
                    try:
                        await assert_vocabulary(entradas, vocabulario)
                    except CorpusValidationError as exc:
                        raise DescriptorInvalido(f"{paquete.nom}: {exc}") from exc

                    servicio = await resolve_embedding_service(session, chatbot_id)
                    reconciler = CorpusReconciler(
                        session,
                        IngestionWatcher(session, servicio, chatbot_provider=provider),
                    )
                    informe = await reconciler.reconcile(
                        fuente, chatbot_id, dry_run=dry_run
                    )
                    informes[(paquete.nom, chatbot_id)] = informe
                    print(resumen(paquete.nom, chatbot_id, informe))
                    if not dry_run and not sense_diari:
                        print(
                            "      "
                            + (await _anclas_del_diario(session, chatbot_id)).resumen
                        )
                    if verbose:
                        for linea in informe.detalle:
                            print(f"      {linea}")
                    if not dry_run:
                        # Se confirma por asistente: la reconciliacion es incremental, asi que
                        # conservar lo que si funciono hace que repetir la pasada solo rehaga
                        # lo que falta.
                        await session.commit()
    finally:
        await engine.dispose()
    return informes


async def _divergencias(paquetes: list[Paquete]) -> int:
    """Copias que quedan atrasadas entre los chatbots de la organizacion (DER.2)."""
    from sqlalchemy import select

    from server.app.core import config  # noqa: F401
    from server.app.modules.agents_hub.database.config_models import HubChatbot
    from server.app.modules.agents_hub.database.connection import (
        create_async_engine,
        create_session_factory,
    )
    from server.app.modules.agents_hub.ingestion.divergence_detector import (
        detectar_divergencias,
        render_divergencias,
    )

    engine = create_async_engine()
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            alguno = paquetes[0].chatbots[0]
            organizacion = await session.scalar(
                select(HubChatbot.organizacion_id).where(HubChatbot.id == alguno)
            )
            de_la_organizacion = list(
                (
                    await session.execute(
                        select(HubChatbot.id).where(
                            HubChatbot.organizacion_id == organizacion
                        )
                    )
                ).scalars().all()
            )
            divergencias = await detectar_divergencias(session, de_la_organizacion)
            if divergencias:
                print(render_divergencias(divergencias))
                print("  (nada se propaga solo: recarga el chatbot atrasado)")
            return len(divergencias)
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--descriptor", required=True, type=Path)
    parser.add_argument(
        "--confirmar",
        action="store_true",
        help="Aplica. Sin esto solo se ensena el plan y no se escribe nada",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument(
        "--sense-diari",
        action="store_true",
        help=(
            "no leer el diario oficial para refrescar el mapa de anclas (issue #157). "
            "Para ingerir sin salida a internet: las normas externas se citaran sin "
            "fragmento, como antes de la #157."
        ),
    )
    args = parser.parse_args(argv)

    try:
        paquetes = leer_descriptor(args.descriptor)
    except DescriptorInvalido as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print("=== EL PLAN (nada escrito) ===")
    try:
        informes = asyncio.run(
        _pasada(paquetes, dry_run=True, verbose=args.verbose, sense_diari=args.sense_diari)
    )
    except DescriptorInvalido as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    cambios = [c for i in informes.values() for c in i.cambios_de_estado]
    if cambios:
        print(f"\n*** {len(cambios)} CAMBIOS DE ESTADO. Leelos antes de confirmar. ***")

    if not args.confirmar:
        print("\nEn seco. Para aplicarlo: --confirmar")
        return 0

    print("\n=== APLICANDO, en el orden del descriptor ===")
    asyncio.run(
        _pasada(paquetes, dry_run=False, verbose=args.verbose, sense_diari=args.sense_diari)
    )
    print("\n=== COPIAS ATRASADAS ENTRE ASISTENTES ===")
    asyncio.run(_divergencias(paquetes))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


async def _anclas_del_diario(session, chatbot_id):
    """Lee del diario oficial el mapa `artículo → ancla` de las normas externas (issue #157).

    **Va aquí, en la ingesta, y no al componer la cita**: se lee una vez por pasada en vez de en
    cada respuesta, y lo que se guarda es un mapa y no una fórmula, porque para uno de los dos
    esquemas del BOE no existe ninguna fórmula.

    **Y no puede tumbar la ingesta.** Si el diario no responde, la norma entra igual y sus citas
    van sin fragmento, que es lo que hacían antes de esto. Acoplar la disponibilidad del corpus a
    la de una web ajena sería peor que la imprecisión que se viene a arreglar; por eso se cuenta
    en el informe en vez de levantar.

    **Cada cuánto se revisa el mapa**: cada pasada de ingesta, que es cuando ya se está mirando
    el corpus. Entre pasada y pasada lo vigila `verificar_enlaces`, que desde la #157 comprueba
    que el ancla etiquete el artículo que la cita dice — y ésa es la respuesta honrada, porque un
    calendario no detecta nada y el detector sí.
    """
    from sqlalchemy import select

    from server.app.modules.agents_hub.database.operational_models import HubDocument
    from server.app.modules.agents_hub.ingestion.ancores_del_diari import (
        refrescar_ancores,
        url_del_diari,
    )

    documentos = [
        d
        for d in (
            await session.execute(
                select(HubDocument).where(HubDocument.chatbot_id == chatbot_id)
            )
        )
        .scalars()
        .all()
        if url_del_diari(d)
    ]
    if not documentos:
        from server.app.modules.agents_hub.ingestion.ancores_del_diari import Refresco

        return Refresco()

    import httpx

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as cliente:

        async def fetch(url: str) -> tuple[int, str]:
            respuesta = await cliente.get(url)
            return respuesta.status_code, respuesta.text

        refresco = await refrescar_ancores(documentos, fetch)

    for url, motivo in refresco.no_se_pudo.items():
        print(f"      AVISO: no se pudo leer {url}: {motivo}", file=sys.stderr)
    for url in refresco.sin_articulos:
        print(f"      AVISO: sin artículos en {url}", file=sys.stderr)
    return refresco
