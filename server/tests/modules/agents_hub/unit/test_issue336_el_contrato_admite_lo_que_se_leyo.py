"""#336 — el contrato de citas admite dos cosas que no son invenciones.

1. **Un ancla que el modelo tenía delante.** En contexto largo el documento llega entero, con
   sus encabezados `{#art-3}`, pero la URL citable era la del documento sin ancla y la regla 5
   del prompt prohibía añadirla: el contexto largo no podía citar el artículo aunque lo leyera.
   Ahora la estrategia declara qué anclas se pueden citar —sólo si la cita va a la página de
   nuestro sitio, que es la que las sirve— y el contrato las admite.
2. Se propuso también conservar el enlace de una URL escrita en el texto de la evidencia —el de
   la aplicación que tramita un certificado—. **La revisión de la PR #338 lo retiró**: el
   artículo entregado entero trae sus remisiones enlazadas, y conservarlas deshacía la regla de
   HIB.0 (no se enlazan las normas citadas por las normas). La mención se conserva.

Lo que sigue fuera: un ancla que no está en lo que se entregó (componerla sería fabricar un
puntero, HIB.D), y cualquier URL que no se entregó como documento.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from server.app.modules.agents_hub.agent.citation_validator import aplicar_contrato
from server.app.modules.agents_hub.agent.public_graphs.strategies.retrieval_contract import (
    EvidenceItem,
)
from server.app.modules.agents_hub.services.retrieval.citations import (
    ANCLAS_CITABLES,
    BASE_DEL_SITIO,
)

PAGINA = "https://normativa.example.org/html/val_Reglament.html"
APP = "https://tramits.example.org/certificat?id=1"


def _evidencia(content: str = "Text", anclas: list[str] | None = None, url: str = PAGINA):
    return EvidenceItem(
        source_id=str(uuid.uuid4()),
        content=content,
        source_url=url,
        title="Reglament",
        metadata={ANCLAS_CITABLES: anclas} if anclas is not None else {},
    )


# --- El contrato ---------------------------------------------------------------------------------


def test_un_ancla_citable_del_documento_se_conserva() -> None:
    r = aplicar_contrato(f"Es X [Reglament, art. 3]({PAGINA}#art-3).", [_evidencia(anclas=["art-3"])], "MD_LONG_CONTEXT")

    assert f"({PAGINA}#art-3)" in r.texto
    assert r.anclas_degradadas == 0


def test_un_ancla_que_no_esta_en_el_documento_sigue_bajando_a_la_pagina() -> None:
    r = aplicar_contrato(f"Es X [Reglament, art. 9]({PAGINA}#art-9).", [_evidencia(anclas=["art-3"])], "MD_LONG_CONTEXT")

    assert f"({PAGINA})" in r.texto
    assert r.anclas_degradadas == 1


def test_sin_anclas_declaradas_nada_cambia() -> None:
    """El vectorial no declara anclas: su evidencia ya trae la del fragmento en la URL."""
    r = aplicar_contrato(f"Es X [Reglament]({PAGINA}#art-3).", [_evidencia(url=f"{PAGINA}#art-1")], "RAG")

    assert f"({PAGINA})" in r.texto


def test_una_url_escrita_en_la_evidencia_pierde_el_enlace() -> None:
    """HIB.0: lo que la evidencia remite no se entregó; se nombra, no se enlaza (PR #338)."""
    evidencia = _evidencia(content=f"Segons la [Llei 9/2017]({APP}).", url=f"{PAGINA}#art-1")

    r = aplicar_contrato(
        f"Ho diu la [Llei 9/2017]({APP}) [Reglament]({PAGINA}#art-1).", [evidencia], "RAG"
    )

    assert f"({APP})" not in r.texto
    assert "Llei 9/2017" in r.texto
    assert r.remisiones_despojadas == 1


def test_una_url_que_no_se_entrego_pierde_el_enlace() -> None:
    r = aplicar_contrato(
        f"Demana-ho a [l'aplicació]({APP}) [Reglament]({PAGINA}).", [_evidencia()], "RAG"
    )

    assert f"({APP})" not in r.texto
    assert r.remisiones_despojadas == 1


def test_una_url_escrita_en_la_evidencia_no_basta_para_cumplir() -> None:
    """Enlazar la aplicación no es citar el fundamento: sin cita a un documento, no cumple."""
    evidencia = _evidencia(content=f"Aplicació: {APP}")

    r = aplicar_contrato(f"Demana-ho a [l'aplicació]({APP}).", [evidencia], "RAG")

    assert r.cumple is False


# --- Qué anclas declara el contexto largo --------------------------------------------------------


def _documento(**cambios):
    datos = dict(
        id=uuid.uuid4(), title="Reglament", canonical_url="https://example.org/r.pdf",
        doc_metadata={"relative_path": "val_Reglament.md"}, source_kind="corpus",
        markdown_content="## Article 3. Objecte {#art-3 .modificat}\nText\n### FAQ {#faq-1}\nX",
        language="ca", token_count=10, created_at=None,
    )
    datos.update(cambios)
    return SimpleNamespace(**datos)


async def _anclas(documento) -> list[str]:
    from server.app.modules.agents_hub.services.retrieval.long_context_strategy import (
        LongContextRetrievalStrategy,
    )

    resultado = MagicMock()
    resultado.scalars.return_value.all.return_value = [documento]
    sesion = AsyncMock()
    sesion.execute = AsyncMock(return_value=resultado)
    sesion.get = AsyncMock(return_value=SimpleNamespace(use_prompt_caching=False, cache_ttl=3600))
    ctx = await LongContextRetrievalStrategy(sesion).get_context("p", uuid.uuid4())
    return ctx.sources[0].metadata[ANCLAS_CITABLES]


@pytest.mark.asyncio
async def test_el_contexto_largo_declara_las_anclas_de_la_pagina(monkeypatch) -> None:
    monkeypatch.setenv(BASE_DEL_SITIO, "https://normativa.example.org")

    assert await _anclas(_documento()) == ["art-3", "faq-1"]


@pytest.mark.asyncio
async def test_sin_sitio_no_hay_anclas_que_citar(monkeypatch) -> None:
    """El PDF no tiene anclas (#15): componer una sobre él no lleva a ninguna parte."""
    monkeypatch.delenv(BASE_DEL_SITIO, raising=False)

    assert await _anclas(_documento()) == []


@pytest.mark.asyncio
async def test_una_norma_externa_no_declara_anclas(monkeypatch) -> None:
    """El BOE no ancla por número de artículo (#157): `art-18` no es su `#a1-10`."""
    monkeypatch.setenv(BASE_DEL_SITIO, "https://normativa.example.org")
    externa = _documento(
        canonical_url="https://www.boe.es/buscar/act.php?id=BOE-A-2017-12902",
        doc_metadata={"relative_path": "LCSP.md", "tipus_document": "norma_externa"},
    )

    assert await _anclas(externa) == []


# --- El prompt ------------------------------------------------------------------------------------


def test_el_prompt_del_contexto_largo_explica_como_citar_el_apartado() -> None:
    from server.app.modules.agents_hub.agent.public_graphs.profiles.public_kb_rich import (
        GenericAnswerTemplateStrategy,
    )

    prompt = GenericAnswerTemplateStrategy(retrieval_mode="MD_LONG_CONTEXT").build_prompt_context(
        [_evidencia(anclas=["art-3"])], "ca", "q"
    )

    assert "{#art-3}" in prompt
    assert "NO le anadas un ancla" not in prompt


def test_solo_el_documento_con_anclas_lleva_la_marca() -> None:
    """Revisión de la PR #338: un PDF o una página del BOE no sirven nuestras anclas, y la regla
    no puede invitar a ponérselas."""
    from server.app.modules.agents_hub.agent.public_graphs.profiles.public_kb_rich import (
        MARCA_DE_ANCLAS,
        GenericAnswerTemplateStrategy,
    )

    con = _evidencia(anclas=["art-3"])
    sin = EvidenceItem(source_id="x", content="Text", source_url="https://boe.example/l.pdf", title="Llei")

    prompt = GenericAnswerTemplateStrategy(retrieval_mode="MD_LONG_CONTEXT").build_prompt_context(
        [con, sin], "ca", "q"
    )

    bloque_sin = prompt.split("## Llei")[1]
    assert MARCA_DE_ANCLAS in prompt.split("## Llei")[0].split("## Reglament")[1]
    assert MARCA_DE_ANCLAS not in bloque_sin


def test_el_prompt_del_vectorial_no_cambia() -> None:
    from server.app.modules.agents_hub.agent.public_graphs.profiles.public_kb_rich import (
        CITATION_RULES,
        GenericAnswerTemplateStrategy,
    )

    prompt = GenericAnswerTemplateStrategy(retrieval_mode="RAG").build_prompt_context(
        [_evidencia(url=f"{PAGINA}#art-1")], "ca", "q"
    )

    assert CITATION_RULES.strip() in prompt
