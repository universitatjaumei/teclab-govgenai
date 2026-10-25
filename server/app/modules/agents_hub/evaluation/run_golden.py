"""CLI de evaluación del retriever contra un dataset dorado (RAG.1). Deploy: edge.

Es la **vía manual/nocturna** del prompt: mide el retriever real —con BGE-M3 y el corpus
cargado— contra un dataset dorado, y no bloquea CI. El gate de CI es otra cosa: corre sobre
el corpus de fixture con embedding determinista y vive en
`tests/modules/agents_hub/evaluation/test_golden_gate.py`.

    uv run python -m server.app.modules.agents_hub.evaluation.run_golden \
        --dataset <ruta.json> --chatbot-id <uuid> [--baseline <ruta.json>] [--update-baseline]

`--update-baseline` reescribe la línea base con las cifras de esta ejecución. Es deliberado
y nunca debe correr en CI: si la baseline se regenera sola, el gate deja de detectar nada.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

# torch antes que asyncpg: en Windows el orden inverso aborta el proceso (ver el conftest
# de tests/modules/agents_hub).
from server.app.modules.agents_hub.ingestion.chunker import MarkdownChunker  # noqa: F401

from server.app.modules.agents_hub.evaluation.golden_dataset import (
    fingerprint_matches,
    load_golden_dataset,
)
from server.app.modules.agents_hub.evaluation.retrieval_eval import (
    check_gate,
    run_golden_eval,
)


async def _run(args: argparse.Namespace) -> int:
    from sqlalchemy import select

    from server.app.modules.agents_hub.database.connection import (
        create_async_engine,
        create_session_factory,
    )
    from server.app.modules.agents_hub.database.operational_models import HubDocument
    from server.app.modules.agents_hub.services.embedding_service import (
        LocalEmbeddingService,
    )
    from server.app.modules.agents_hub.services.retriever import HybridRetriever

    dataset = load_golden_dataset(args.dataset)
    engine = create_async_engine()
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            hashes = list(
                (
                    await session.execute(
                        select(HubDocument.content_hash).where(
                            HubDocument.chatbot_id == args.chatbot_id
                        )
                    )
                ).scalars()
            )
            if not hashes:
                print(
                    f"ERROR: el chatbot {args.chatbot_id} no tiene documentos cargados",
                    file=sys.stderr,
                )
                return 1
            if not fingerprint_matches(dataset, hashes):
                # No es fatal en la vía manual, pero hay que decirlo: comparar contra una
                # baseline medida sobre otro corpus no compara nada.
                print(
                    f"AVISO: el dataset se midio sobre otro corpus "
                    f"({len(hashes)} documentos ahora). Las cifras no son comparables "
                    "con la baseline."
                )

            informe = await run_golden_eval(
                HybridRetriever(session),
                LocalEmbeddingService(),
                dataset,
                args.chatbot_id,
                top_k=args.top_k,
            )
    finally:
        await engine.dispose()

    print(f"\n{informe.render()}\n")
    print(f"{'recall@5':>9} {'mrr':>6}  consulta")
    for r in informe.per_query:
        marca = " " if r.recall_at_5 > 0 else "!"
        print(f"{marca}{r.recall_at_5:>8.2f} {r.mrr:>6.2f}  {r.query[:64]}")

    fallos = [r for r in informe.per_query if r.recall_at_5 == 0.0]
    if fallos:
        print(f"\n{len(fallos)} consulta(s) sin acierto en el top-5:")
        for r in fallos:
            print(f"  {r.query[:70]}")
            print(f"    esperaba: {r.expected}")
            print(f"    recupero: {r.retrieved[:5]}")

    baseline = None
    if args.baseline and Path(args.baseline).is_file():
        baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    veredicto = check_gate(informe, baseline, tolerance=args.tolerance)
    print(f"\ngate: {'OK' if veredicto.passed else 'REGRESION'} — {veredicto.summary}")
    for r in veredicto.regressions:
        print(f"  - {r}")

    if args.update_baseline:
        destino = Path(args.baseline or f"baseline_{dataset.name}.json")
        destino.write_text(
            json.dumps(informe.to_baseline(), ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        print(f"\nbaseline reescrita en {destino}")

    return 0 if veredicto.passed else 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").strip().splitlines()[0])
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--chatbot-id", required=True, type=uuid.UUID, dest="chatbot_id")
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--top-k", type=int, default=10, dest="top_k")
    parser.add_argument("--tolerance", type=float, default=0.02)
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        dest="update_baseline",
        help="Reescribe la baseline con esta ejecucion. Deliberado, NUNCA en CI",
    )
    return asyncio.run(_run(parser.parse_args(argv)))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
