"""#277 — lo que se puede hacer con una fila lo dice el servidor; el panel itera.

La auditoría encontró pantallas con la máquina de estado copiada en la interfaz:

* la cola de hallazgos ofrecía «confirmar» y «descartar» si `status == 'new'` y «resolver» si
  `'confirmed'` — y se equivocaba, porque el servidor también deja descartar uno confirmado y
  reabrir uno descartado;
* la tabla de trabajos de ingesta desactivaba «borrar» con `pending || running`, la misma regla
  que el servidor aplica con un 409;
* el formulario del chatbot comparaba el corpus con `128_000` escrito en el cliente, y filtraba
  los hijos asignables a un enrutador con la regla de la jerarquía de dos niveles.

Ahora cada DTO trae lo que hace falta, calculado con la misma regla que el endpoint aplica.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest


def _hallazgo(estado: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(), site_id=uuid.uuid4(), finding_type="duplicate", severity="warning",
        status=estado, confidence=1.0, source_url=None, page_id=None, related_page_id=None,
        signal_json={}, detected_at=datetime.now(timezone.utc), reviewed_at=None,
    )


@pytest.mark.parametrize(
    ("estado", "acciones"),
    [
        ("new", ["confirmed", "dismissed"]),
        ("confirmed", ["dismissed", "resolved"]),
        ("dismissed", ["new"]),
        ("resolved", []),
    ],
)
def test_un_hallazgo_trae_las_transiciones_que_el_servidor_admite(estado, acciones) -> None:
    from server.app.routers.hub_content_quality_router import HallazgoOut

    salida = HallazgoOut.model_validate(_hallazgo(estado)).model_dump()
    assert salida["acciones_permitidas"] == acciones


@pytest.mark.parametrize(
    ("estado", "acciones"),
    [("pending", []), ("running", []), ("done", ["borrar"]), ("failed", ["borrar"])],
)
def test_un_trabajo_de_ingesta_dice_si_se_puede_borrar(estado, acciones) -> None:
    from server.app.routers.hub_ingestion_router import IngestionJob

    fila = SimpleNamespace(
        id=uuid.uuid4(), chatbot_id=uuid.uuid4(), source_url="u", original_filename=None,
        canonical_url=None, language=None, status=estado, chunks_processed=0, error_message=None,
        created_at=datetime.now(timezone.utc),
    )
    assert IngestionJob.model_validate(fila).model_dump()["acciones_permitidas"] == acciones


def test_las_estadisticas_del_corpus_dicen_si_cabe_en_contexto_largo() -> None:
    from server.app.routers.hub_chatbots_corpus_router import CorpusStatsOut

    campos = CorpusStatsOut.model_fields
    assert "limite_contexto_largo" in campos
    assert "cabe_en_contexto_largo" in campos


@pytest.mark.parametrize(
    ("kind", "padre", "puede"),
    [("atomic", None, True), ("router", None, False), ("atomic", uuid.uuid4(), False)],
)
def test_un_chatbot_dice_si_puede_ser_hijo_de_un_enrutador(kind, padre, puede) -> None:
    from server.app.routers.hub_chatbots_router import _puede_ser_hijo

    assert _puede_ser_hijo(SimpleNamespace(kind=kind, parent_chatbot_id=padre)) is puede


def test_el_limite_de_contexto_largo_es_uno_solo() -> None:
    """El endpoint que rechaza y las estadísticas que lo anuncian leen la misma constante."""
    from pathlib import Path

    texto = (Path(__file__).resolve().parents[2] / "app" / "routers" / "hub_chatbots_router.py").read_text(
        encoding="utf-8"
    )
    assert "128_000" not in texto
