"""Tests — importación de un lote de escenarios de prueba desde un fichero JSON.

Los escenarios de RAG.13 se crean de uno en uno por la API, que es lo correcto cuando alguien
piensa una prueba mientras usa el asistente. Pero un lote —decenas de consultas reales con el
veredicto que les puso un informador— no se teclea a mano sin que alguien se equivoque en la
número 19.

Los lotes reales no viven en el repositorio (son datos de un cliente y el repositorio es
público), así que estos tests construyen el suyo: lo que hay que fijar es el mecanismo.

Dos propiedades que estos tests fijan:

- **Idempotente por nombre dentro del chatbot.** Importar dos veces no duplica: actualiza. Un
  lote de escenarios se corrige (se afina una nota, se añade una fuente esperada) y hay que
  poder reimportarlo sin dejar dos copias que el que juzga no sabe distinguir.
- **`meta` no entra en la base de datos.** El análisis de procedencia —qué informador, qué
  veredicto puso, qué modo de fallo— es del fichero, no de la tabla. `HubTestScenario` no
  tiene dónde guardarlo y no se le añade una columna por esto: lo que el humano necesita al
  juzgar ya está redactado dentro de `expectation_note`.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from server.app.modules.agents_hub.evaluation.import_scenarios import (
    cargar_lote,
    importar_escenarios,
)

async def _chatbot(session):
    from server.tests.modules.agents_hub.integration.test_embedding_resolution import (
        _organizacion_y_chatbot,
    )

    _, chatbot = await _organizacion_y_chatbot(session)
    chatbot.name = f"Bot {uuid.uuid4().hex[:8]}"
    await session.flush()
    return chatbot


def _lote_minimo(tmp_path: Path) -> Path:
    datos = {
        "name": "prueba",
        "scenarios": [
            {
                "name": "A · primera",
                "prompt": "quantes convocatòries tinc?",
                "history": None,
                "expectation_note": "Debe citar el reglamento vigente.",
                "meta": {"informer": "Unitat d'Orientació"},
            },
            {
                "name": "B · seguimiento",
                "prompt": "i si és a l'estranger?",
                "history": ["usuario: quant cobro de dieta?", "asistente: 53,34 euros."],
                "expectation_note": None,
            },
        ],
    }
    ruta = tmp_path / "lote.json"
    ruta.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    return ruta


class TestCargaDelFichero:

    def test_should_load_a_batch_preserving_history_and_expectation(self, tmp_path):
        lote = cargar_lote(_lote_minimo(tmp_path))

        assert lote.name == "prueba"
        assert [e.name for e in lote.scenarios] == ["A · primera", "B · seguimiento"]
        assert lote.scenarios[1].history[0].startswith("usuario:")
        assert lote.scenarios[0].expectation_note

    def test_should_reject_a_batch_with_repeated_names(self, tmp_path):
        """Dos escenarios con el mismo nombre harían que el segundo pisara al primero al
        importar, y el lote parecería completo con uno menos."""
        ruta = _lote_minimo(tmp_path)
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        datos["scenarios"][1]["name"] = datos["scenarios"][0]["name"]
        ruta.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")

        with pytest.raises(ValueError, match="repetidos"):
            cargar_lote(ruta)

    def test_should_reject_a_scenario_without_prompt(self, tmp_path):
        ruta = _lote_minimo(tmp_path)
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        datos["scenarios"][0]["prompt"] = "   "
        ruta.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")

        with pytest.raises(ValueError, match="sin consulta"):
            cargar_lote(ruta)


class TestImportacion:

    @pytest.mark.asyncio
    async def test_should_create_every_scenario_of_the_batch(self, db_session, tmp_path):
        from sqlalchemy import select

        from server.app.modules.agents_hub.database.operational_models import (
            HubTestScenario,
        )

        chatbot = await _chatbot(db_session)
        lote = cargar_lote(_lote_minimo(tmp_path))

        resumen = await importar_escenarios(
            db_session, chatbot.id, lote, created_by="admin@uji.es"
        )

        assert (resumen.creados, resumen.actualizados) == (2, 0)
        filas = (
            (
                await db_session.execute(
                    select(HubTestScenario).where(
                        HubTestScenario.chatbot_id == chatbot.id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert {f.name for f in filas} == {"A · primera", "B · seguimiento"}
        seguimiento = next(f for f in filas if f.name == "B · seguimiento")
        assert seguimiento.history[0].startswith("usuario:")
        assert all(f.created_by == "admin@uji.es" for f in filas)

    @pytest.mark.asyncio
    async def test_should_not_store_the_meta_block(self, db_session, tmp_path):
        """`meta` es procedencia y análisis, no un campo del modelo. Si se colara, entraría
        como atributo suelto y el commit reventaría o —peor— lo ignoraría en silencio."""
        from sqlalchemy import select

        from server.app.modules.agents_hub.database.operational_models import (
            HubTestScenario,
        )

        chatbot = await _chatbot(db_session)
        lote = cargar_lote(_lote_minimo(tmp_path))

        await importar_escenarios(db_session, chatbot.id, lote)

        fila = (
            (
                await db_session.execute(
                    select(HubTestScenario).where(
                        HubTestScenario.name == "A · primera",
                        HubTestScenario.chatbot_id == chatbot.id,
                    )
                )
            )
            .scalars()
            .one()
        )
        assert not hasattr(fila, "meta")

    @pytest.mark.asyncio
    async def test_should_update_instead_of_duplicating_on_reimport(
        self, db_session, tmp_path
    ):
        """La propiedad que hace que el lote sea mantenible: se corrige la nota, se vuelve a
        importar y sigue habiendo un escenario, no dos."""
        from sqlalchemy import func, select

        from server.app.modules.agents_hub.database.operational_models import (
            HubTestScenario,
        )

        chatbot = await _chatbot(db_session)
        ruta = _lote_minimo(tmp_path)
        await importar_escenarios(db_session, chatbot.id, cargar_lote(ruta))

        datos = json.loads(ruta.read_text(encoding="utf-8"))
        datos["scenarios"][0]["expectation_note"] = "Nota corregida."
        ruta.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
        resumen = await importar_escenarios(db_session, chatbot.id, cargar_lote(ruta))

        assert (resumen.creados, resumen.actualizados) == (0, 2)
        total = await db_session.scalar(
            select(func.count())
            .select_from(HubTestScenario)
            .where(HubTestScenario.chatbot_id == chatbot.id)
        )
        assert total == 2
        fila = (
            (
                await db_session.execute(
                    select(HubTestScenario).where(
                        HubTestScenario.name == "A · primera",
                        HubTestScenario.chatbot_id == chatbot.id,
                    )
                )
            )
            .scalars()
            .one()
        )
        assert fila.expectation_note == "Nota corregida."

    @pytest.mark.asyncio
    async def test_should_not_touch_scenarios_of_another_chatbot(
        self, db_session, tmp_path
    ):
        """La unicidad es por (chatbot, nombre). Dos chatbots pueden tener el mismo lote
        importado —es justo lo que se quiere para comparar dos configuraciones— y reimportar
        en uno no puede pisar el del otro."""
        from sqlalchemy import func, select

        from server.app.modules.agents_hub.database.operational_models import (
            HubTestScenario,
        )

        uno = await _chatbot(db_session)
        otro = await _chatbot(db_session)
        lote = cargar_lote(_lote_minimo(tmp_path))

        await importar_escenarios(db_session, uno.id, lote)
        resumen = await importar_escenarios(db_session, otro.id, lote)

        assert (resumen.creados, resumen.actualizados) == (2, 0)
        total = await db_session.scalar(
            select(func.count()).select_from(HubTestScenario)
        )
        assert total == 4
