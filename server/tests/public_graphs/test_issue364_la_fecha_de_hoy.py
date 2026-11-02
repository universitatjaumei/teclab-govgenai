"""#364 — el asistente sabe qué día es y en qué curso estamos.

**El defecto**: el prompt no llevaba ni la fecha ni el curso académico. Con un corpus de plazos y
calendarios, el modelo no puede saber si un plazo ya pasó ni qué curso es «este». Los técnicos de
la OPAQ lo vieron en el DOCENTIA, y se reprodujo el 2026-11-02 con los tres modelos de producción:

- a «¿contarán para el DOCENTIA 2025/2026 unas ponencias pendientes de validar?», los tres
  contestaban «sí, si se validan antes del 31 de julio de 2026», con esa fecha ya pasada;
- a una profesora que preguntaba el 29 de octubre si podía ir un encuestador «mañana», se le
  contestó con fechas de 2024.

**Lo pone el `CoreGraph`, no una plantilla**, para que llegue a todas —también a las de terceros
(PLG)—; lo señaló la revisión de la PR. **Y va al final del contexto**: la caché implícita de
Gemini reutiliza el prefijo, que en el contexto largo son unos 75.000 tokens de corpus, y el 2 de
noviembre se sirvió desde caché el 74 % de la entrada. Una línea que cambia cada día puesta delante
invalidaría el prefijo entero cada mañana.
"""
from __future__ import annotations

import uuid
from datetime import date

import pytest

from server.app.modules.agents_hub.agent.public_graphs.strategies.retrieval_contract import (
    EvidenceItem,
)


async def _prompt(hoy: date, plantilla=None) -> str:
    from server.app.modules.agents_hub.agent.public_graphs.core.config_resolver import (
        PublicGraphConfig,
    )
    from server.app.modules.agents_hub.agent.public_graphs.core.core_graph import CoreGraph
    from server.app.modules.agents_hub.agent.public_graphs.profiles.public_kb_rich import (
        GenericAnswerTemplateStrategy,
    )
    from server.app.modules.agents_hub.agent.public_graphs.strategies.protocols import (
        NeutralLanguagePolicy,
        RetrievalOutput,
        RetrievalResult,
    )

    class _Retrieval:
        async def retrieve(self, query, chatbot_id, cfg, deps, language=None):
            return RetrievalOutput(
                buckets=[
                    RetrievalResult(items=[EvidenceItem(source_id="d", content="t")], debug={})
                ]
            )

    class _Merge:
        def merge(self, output):
            return [i for b in output.buckets for i in b.items]

    cfg = PublicGraphConfig(
        profile="PUBLIC_KB_RICH", retrieval_mode="RAG", language_mode="prefer",
        quality_threshold=0.0, min_retrieval_results=1, min_retrieval_score=0.0,
        reranker_enabled=False, answer_template="generic",
    )
    grafo = CoreGraph(
        retrieval_strategy=_Retrieval(), merge_strategy=_Merge(),
        template_strategy=plantilla or GenericAnswerTemplateStrategy(base_system_prompt="Assistent"),
        language_policy=NeutralLanguagePolicy(), cfg=cfg, deps=object(), llm=None,
        hoy=lambda: hoy,
    )
    estado = await grafo.run("pregunta", str(uuid.uuid4()), debug_bypass=True)
    return estado["bypass"]["system_prompt"]


class TestLaFechaEstaEnElPrompt:

    @pytest.mark.asyncio
    async def test_should_include_todays_date_written_out(self):
        assert "2 de noviembre de 2026" in await _prompt(date(2026, 11, 2))

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("hoy", "curso"),
        [
            (date(2026, 11, 2), "2026-27"),
            (date(2027, 1, 15), "2026-27"),
            (date(2026, 9, 1), "2026-27"),
            (date(2026, 8, 31), "2025-26"),
            (date(2099, 12, 31), "2099-00"),
        ],
    )
    async def test_should_include_the_academic_year_from_september_to_august(self, hoy, curso):
        assert f"curso académico {curso}" in await _prompt(hoy)

    @pytest.mark.asyncio
    async def test_should_go_last_after_the_documents_so_the_cached_prefix_survives(self):
        prompt = await _prompt(date(2026, 11, 2))

        assert prompt.index("DOCUMENTOS DISPONIBLES") < prompt.index("FECHA DE HOY")
        assert prompt.rstrip().endswith("a qué curso se refiere quien pregunta.")

    @pytest.mark.asyncio
    async def test_should_reach_any_template_not_only_the_generic_one(self):
        class _PlantillaDeTerceros:
            def build_prompt_context(self, items, language, query):
                return "SYSTEM DE OTRO PERFIL"

        prompt = await _prompt(date(2026, 11, 2), plantilla=_PlantillaDeTerceros())

        assert prompt.startswith("SYSTEM DE OTRO PERFIL")
        assert "2 de noviembre de 2026" in prompt


class TestElRelojPorDefecto:

    def test_should_use_the_date_in_madrid(self):
        """La fecha es la de la institución, no la del servidor: el contenedor corre en UTC, y
        entre las 0:00 y la 1:00 (las 2:00 en verano) serían días distintos."""
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from server.app.modules.agents_hub.agent.public_graphs.core.fecha import fecha_de_hoy

        assert fecha_de_hoy() == datetime.now(ZoneInfo("Europe/Madrid")).date()

    def test_should_be_the_default_clock_of_the_graph(self):
        import inspect

        from server.app.modules.agents_hub.agent.public_graphs.core.core_graph import CoreGraph
        from server.app.modules.agents_hub.agent.public_graphs.core.fecha import fecha_de_hoy

        assert inspect.signature(CoreGraph).parameters["hoy"].default is fecha_de_hoy
