"""HIB.I — la traza que permite volver atrás.

`hub_chat.py` guardaba `interaction_metadata={"usage_source": ...}` y nada más. Con el piloto
en marcha ya es tarde para los datos que no se guardaron: sin los identificadores y las
puntuaciones de lo recuperado no se puede saber, meses después, si una respuesta mala fue de
recuperación o de redacción, ni re-ejecutar una ablación contra las mismas consultas.

Lo que NO se guarda es el contenido de los fragmentos: ya está en `hub_document_chunks` por
`chunk_id`, y duplicarlo multiplicaría la tabla por el tamaño del contexto.

Las claves se fijan por snapshot a propósito. Son campos de diagnóstico cuya lista va a crecer
con cada prompt de medición —una migración por campo es lo que hace que dejen de añadirse—, así
que van en JSONB; el precio de esa flexibilidad es que un cambio silencioso de nombre rompería
el instrumental sin que nadie se enterase, y el snapshot es lo que lo impide.

Deploy: edge
"""
from __future__ import annotations

import uuid


from server.app.modules.agents_hub.evaluation.traza import (
    CLAVES_DE_TRAZA,
    construye_traza,
)


def _fuente(**kw) -> dict:
    base = {
        "document_id": str(uuid.uuid4()),
        "url": "https://www.uji.es/norma/permanencia#art-4",
        "title": "Reglament de permanencia",
        "score": 0.7683,
    }
    base.update(kw)
    return base


class TestLaConfiguracionEfectivaViajaConLaRespuesta:

    def test_should_store_the_effective_configuration_of_the_answer(self):
        """La configuración VIGENTE en esa respuesta, no un puntero a la del chatbot.

        La del chatbot cambia: si la traza guardara sólo el identificador, una respuesta de
        hace tres semanas se leería con el umbral de hoy y la comparación entre tandas
        quedaría muda sin dar ningún error.
        """
        traza = construye_traza(
            cfg={
                "retrieval_mode": "RAG",
                "chunking_strategy": "parent_child",
                "retrieval_top_k": 3,
                "candidate_k": None,
                "quality_threshold": 0.6,
                "reranker_enabled": False,
            },
            fuentes=[_fuente()],
            best_score=0.7683,
            gate_passed=True,
            usage_source="provider",
        )

        assert traza["retrieval_mode"] == "RAG"
        assert traza["chunking_strategy"] == "parent_child"
        assert traza["retrieval_top_k"] == 3
        assert traza["quality_threshold"] == 0.6
        assert traza["reranker_enabled"] is False

    def test_should_keep_the_usage_source_that_sec4_already_wrote(self):
        """No se pisa lo que ya había: `usage_source` es de SEC.4 y sigue siendo suyo."""
        traza = construye_traza(cfg={}, fuentes=[], usage_source="estimated")
        assert traza["usage_source"] == "estimated"


class TestLoRecuperadoQuedaIdentificado:

    def test_should_store_retrieved_ids_scores_and_anchors_in_order(self):
        primero, segundo = _fuente(score=0.81), _fuente(score=0.42)
        traza = construye_traza(cfg={}, fuentes=[primero, segundo])

        recuperado = traza["retrieved"]
        assert [r["score"] for r in recuperado] == [0.81, 0.42]
        assert recuperado[0]["document_id"] == primero["document_id"]
        assert recuperado[0]["anchor"] == "art-4"

    def test_should_not_store_the_content_of_the_chunks(self):
        """Ya está en `hub_document_chunks`; duplicarlo multiplica la tabla."""
        traza = construye_traza(
            cfg={}, fuentes=[_fuente(excerpt="El 20% de los creditos matriculados...")]
        )
        serializada = str(traza)
        assert "20% de los creditos" not in serializada
        for clave in traza["retrieved"][0]:
            assert clave in ("document_id", "url", "anchor", "score", "title")

    def test_should_leave_the_anchor_null_when_the_url_has_none(self):
        traza = construye_traza(
            cfg={}, fuentes=[_fuente(url="https://www.uji.es/norma/permanencia")]
        )
        assert traza["retrieved"][0]["anchor"] is None

    def test_should_record_how_many_evidences_the_packer_dropped(self):
        """`dropped_count` es lo que dice que la respuesta se construyó sobre parte del
        fundamento. Sin él, un contexto recortado y uno completo se leen igual."""
        traza = construye_traza(cfg={}, fuentes=[_fuente()], dropped_count=2)
        assert traza["dropped_count"] == 2


class TestLaDecisionDeLaPuertaQuedaExplicada:

    def test_should_store_the_best_score_and_whether_the_gate_passed(self):
        traza = construye_traza(
            cfg={"quality_threshold": 0.6},
            fuentes=[_fuente()],
            best_score=0.55,
            gate_passed=False,
        )
        assert traza["best_score"] == 0.55
        assert traza["gate_passed"] is False

    def test_should_store_the_turn_index_and_the_rewritten_query(self):
        traza = construye_traza(
            cfg={},
            fuentes=[],
            turn_index=2,
            rewritten_query="requisits addicionals acte de defensa tesi",
            reformulada=False,
        )
        assert traza["turn_index"] == 2
        assert traza["rewritten_query"].startswith("requisits")
        assert traza["reformulada"] is False

    def test_should_store_the_languages_and_the_translation_warning(self):
        traza = construye_traza(
            cfg={},
            fuentes=[],
            language="ca",
            source_language="es",
            translation_warning=True,
        )
        assert traza["language"] == "ca"
        assert traza["source_language"] == "es"
        assert traza["translation_warning"] is True

    def test_should_store_the_index_level_of_the_agentic_mode(self):
        traza = construye_traza(cfg={}, fuentes=[], last_index_level="ambit")
        assert traza["last_index_level"] == "ambit"

    def test_should_store_latency_and_time_to_first_token(self):
        traza = construye_traza(
            cfg={}, fuentes=[], latency_ms=2140, first_token_ms=780
        )
        assert traza["latency_ms"] == 2140
        assert traza["first_token_ms"] == 780


class TestElContratoDeLaTrazaNoCambiaEnSilencio:

    def test_should_keep_the_metadata_keys_stable(self):
        """Snapshot. JSONB permite añadir campos sin migrar, y ese es el motivo de usarlo;
        el precio es que un cambio de nombre rompería el instrumental sin avisar."""
        traza = construye_traza(cfg={}, fuentes=[])
        assert set(traza) == set(CLAVES_DE_TRAZA)

    def test_should_not_duplicate_the_fallback_reason_column(self):
        """`fallback_reason` ya es columna de `hub_interactions` y se filtra por ella."""
        assert "fallback_reason" not in CLAVES_DE_TRAZA


class TestElEndpointLaEscribeDeVerdad:
    """Que el constructor sea correcto no prueba que el chat lo use con datos reales.

    Se comprueba sobre el código del endpoint, siguiendo el precedente de
    `test_should_mark_usage_source_when_estimated` (SEC.4): el valor se escribe en el mismo
    sitio donde se decide, y separarlo para poder probarlo inventaría una indirección que
    sólo existiría para el test. La alternativa —levantar el grafo entero con el modelo
    mockeado— probaría sobre todo los mocks.
    """

    def test_should_call_the_trace_builder_when_persisting_the_interaction(self):
        from pathlib import Path

        texto = Path("app/modules/agents_hub/services/turno_de_chat.py").read_text(encoding="utf-8")

        assert "construye_traza(" in texto
        # Y con los valores reales, no con los que ya tenía a mano.
        for argumento in (
            "cfg=turno.grafo.cfg",
            "fuentes=final_sources",
            "best_score=best_score",
            "gate_passed=gate_passed",
            "turn_index=numero_de_turno",
            "latency_ms=",
            "first_token_ms=primer_token_ms",
        ):
            assert argumento in texto, argumento

    def test_should_measure_the_first_token_from_before_the_graph_starts(self):
        """La latencia que importa es la que espera quien pregunta."""
        from pathlib import Path

        texto = Path("app/modules/agents_hub/services/turno_de_chat.py").read_text(encoding="utf-8")
        inicio = texto.index("inicio = perf_counter()")
        primer_evento = texto.index("async for event in turno.compilado.astream_events")

        assert inicio < primer_evento
