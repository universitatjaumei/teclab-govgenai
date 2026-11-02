"""#364 — el asistente sabe qué día es y en qué curso estamos.

**El defecto**: el prompt no llevaba ni la fecha ni el curso académico. Con un corpus de plazos y
calendarios, el modelo no puede saber si un plazo ya pasó ni qué curso es «este». Los técnicos de
la OPAQ lo vieron en el DOCENTIA, y se reprodujo el 2026-11-02 con los tres modelos de producción:

- a «¿contarán para el DOCENTIA 2025/2026 unas ponencias pendientes de validar?», los tres
  contestaban «sí, si se validan antes del 31 de julio de 2026», con esa fecha ya pasada;
- a una profesora que preguntaba el 29 de octubre si podía ir un encuestador «mañana», se le
  contestó con fechas de 2024.

**Dónde va la línea, y por qué ahí**: al final del contexto, detrás de los documentos. La caché
implícita de Gemini reutiliza el **prefijo** del prompt; en el contexto largo el prefijo son unos
75.000 tokens de corpus, y el 2 de noviembre se sirvió desde caché el 74 % de la entrada. Una
línea que cambia cada día puesta delante invalidaría el prefijo entero cada mañana.
"""
from __future__ import annotations

from datetime import date

import pytest

from server.app.modules.agents_hub.agent.public_graphs.strategies.retrieval_contract import (
    EvidenceItem,
)


def _prompt(hoy: date, items=None) -> str:
    from server.app.modules.agents_hub.agent.public_graphs.profiles.public_kb_rich import (
        GenericAnswerTemplateStrategy,
    )

    return GenericAnswerTemplateStrategy(
        base_system_prompt="Assistent", hoy=lambda: hoy
    ).build_prompt_context(
        items if items is not None else [EvidenceItem(source_id="d", content="text")],
        "es",
        "pregunta",
    )


class TestLaFechaEstaEnElPrompt:

    def test_should_include_todays_date_written_out(self):
        assert "2 de noviembre de 2026" in _prompt(date(2026, 11, 2))

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
    def test_should_include_the_academic_year_from_september_to_august(self, hoy, curso):
        assert f"curso académico {curso}" in _prompt(hoy)

    def test_should_go_after_the_documents_so_the_cached_prefix_survives(self):
        prompt = _prompt(date(2026, 11, 2))

        assert prompt.index("DOCUMENTOS DISPONIBLES") < prompt.index("2 de noviembre de 2026")
        assert prompt.rstrip().endswith(prompt[prompt.index("FECHA DE HOY"):].rstrip())

    def test_should_be_there_also_without_evidence(self):
        assert "2 de noviembre de 2026" in _prompt(date(2026, 11, 2), items=[])


class TestElRelojPorDefecto:

    def test_should_use_the_date_in_madrid(self):
        """La fecha es la de la institución, no la del servidor: el contenedor corre en UTC, y
        entre las 0:00 y la 1:00 (las 2:00 en verano) serían días distintos."""
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from server.app.modules.agents_hub.agent.public_graphs.profiles.public_kb_rich import (
            fecha_de_hoy,
        )

        assert fecha_de_hoy() == datetime.now(ZoneInfo("Europe/Madrid")).date()

    def test_should_be_the_default_clock_of_the_template(self):
        from server.app.modules.agents_hub.agent.public_graphs.profiles.public_kb_rich import (
            GenericAnswerTemplateStrategy,
            fecha_de_hoy,
        )

        prompt = GenericAnswerTemplateStrategy(base_system_prompt="x").build_prompt_context(
            [], "es", "pregunta"
        )

        assert f"{fecha_de_hoy().year}" in prompt[prompt.index("FECHA DE HOY"):]
