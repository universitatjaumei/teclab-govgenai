"""PLG.2 — estrategias seleccionables por configuración, eje a eje.

**Lo que este prompt compra, dicho en una frase**: cambiar cómo fusiona un chatbot deja de ser un
perfil nuevo —factoría, registro, tests— y pasa a ser **una clave** en una columna. Y la
estrategia puede venir de un paquete instalado.

Los dos límites que fija este fichero, y los dos vienen de errores que este proyecto ya pagó:

* **La fusión es CLAVE A CLAVE.** Una organización que fija `merge` no puede borrar el `template`
  del chatbot. Con sustitución del valor entero —que es lo que hace `_apply_layer` para el resto
  de campos— pasaría justo eso, y en silencio.
* **Un nombre no registrado revienta en alto, nunca cae al defecto.** Es la lección del hallazgo
  I5: un asistente que responde «no encuentro información» con el corpus cargado cuesta días de
  encontrar; un error con el eje, el nombre y el chatbot se arregla en un minuto.
"""

from __future__ import annotations

import uuid

import pytest

from server.app.modules.agents_hub.agent.public_graphs.core.config_resolver import (
    PublicGraphConfig,
    _resolver_estrategias,
)
from server.app.modules.agents_hub.agent.public_graphs.core.graph_factory import (
    COMPOSICION_PUBLIC_KB_RICH,
    _aplicar_sobreescrituras,
    _make_public_kb_rich,
)
from server.app.modules.agents_hub.agent.public_graphs.strategies import registry as sreg


def _cfg(**extra) -> PublicGraphConfig:
    base = dict(
        profile="PUBLIC_KB_RICH",
        retrieval_mode="RAG",
        language_mode="prefer",
        quality_threshold=0.6,
        min_retrieval_results=1,
        min_retrieval_score=0.25,
        reranker_enabled=False,
        answer_template="generic",
        chatbot_id=uuid.uuid4(),
    )
    base.update(extra)
    return PublicGraphConfig(**base)


# ---------------------------------------------------------------------------
# 1. Los ejes son estructura; los nombres, vocabulario
# ---------------------------------------------------------------------------


def test_should_expose_exactly_four_axes() -> None:
    assert [e.value for e in sreg.EjeDeEstrategia] == [
        "retrieval",
        "merge",
        "template",
        "language",
    ]


def test_should_reject_an_axis_that_does_not_exist() -> None:
    """Un eje nuevo exige un nodo del CoreGraph que lo consuma: no llega por instalación."""
    with pytest.raises(ValueError, match="no es un eje") as exc:
        sreg.register_strategy("inventado", "x", lambda cfg, deps, llm=None: object())

    assert "retrieval" in str(exc.value), "El error enumera los ejes que sí existen."


def test_should_reject_the_same_strategy_name_twice_in_an_axis() -> None:
    sreg.register_strategy("merge", "_dup_test", lambda cfg, deps, llm=None: object())
    try:
        with pytest.raises(ValueError, match="_dup_test"):
            sreg.register_strategy("merge", "_dup_test", lambda cfg, deps, llm=None: object())
    finally:
        sreg._default_registry._por_eje[sreg.EjeDeEstrategia.MERGE].pop("_dup_test", None)


def test_should_allow_the_same_name_in_two_different_axes() -> None:
    """El nombre es único POR EJE, no globalmente: `merge.generic` y `template.generic` conviven."""
    sreg.register_strategy("merge", "_mismo_nombre", lambda cfg, deps, llm=None: object())
    sreg.register_strategy("template", "_mismo_nombre", lambda cfg, deps, llm=None: object())
    try:
        assert "_mismo_nombre" in sreg.list_strategies("merge")
        assert "_mismo_nombre" in sreg.list_strategies("template")
    finally:
        for eje in (sreg.EjeDeEstrategia.MERGE, sreg.EjeDeEstrategia.TEMPLATE):
            sreg._default_registry._por_eje[eje].pop("_mismo_nombre", None)


# ---------------------------------------------------------------------------
# 2. Regresión: sin sobreescrituras, el grafo es EXACTAMENTE el de antes
# ---------------------------------------------------------------------------


def test_should_build_the_same_four_classes_as_before_plg2() -> None:
    """El test que protege todo lo demás.

    Si componer por nombre cambiara aunque fuera una clase, PLG.2 habría cambiado el
    comportamiento de todos los asistentes en producción mientras decía que sólo añadía un
    mecanismo.
    """
    grafo = _make_public_kb_rich(_cfg(), None, None)

    assert type(grafo.retrieval_strategy).__name__ == "SingleSourceRetrievalStrategy"
    assert type(grafo.merge_strategy).__name__ == "PassthroughMergeStrategy"
    assert type(grafo.template_strategy).__name__ == "GenericAnswerTemplateStrategy"
    assert type(grafo.language_policy).__name__ == "DefaultLanguagePolicy"


def test_should_keep_the_default_composition_naming_the_core_strategies() -> None:
    assert COMPOSICION_PUBLIC_KB_RICH == {
        "retrieval": "single_source",
        "merge": "passthrough",
        "template": "generic",
        "language": "default",
    }


# ---------------------------------------------------------------------------
# 3. La cascada, clave a clave
# ---------------------------------------------------------------------------


def test_should_always_resolve_the_four_axes() -> None:
    resuelto = _resolver_estrategias("PUBLIC_KB_RICH", None, None)

    assert set(resuelto) == {"retrieval", "merge", "template", "language"}, (
        "El resultado trae siempre los cuatro. Quien lo lee no debe tener que tratar el caso "
        "«falta la clave»."
    )


def test_should_merge_organization_and_chatbot_key_by_key() -> None:
    """El test que da sentido al prompt: una capa no pisa a la otra entera."""
    resuelto = _resolver_estrategias(
        "PUBLIC_KB_RICH",
        de_organizacion={"template": "con_cabecera"},
        del_chatbot={"merge": "dedup_por_documento"},
    )

    assert resuelto["template"] == "con_cabecera", "La de la organización sobrevive."
    assert resuelto["merge"] == "dedup_por_documento", "La del chatbot también."
    assert resuelto["retrieval"] == "single_source", "Y lo no fijado hereda del perfil."


def test_should_let_the_chatbot_win_over_the_organization_on_the_same_key() -> None:
    resuelto = _resolver_estrategias(
        "PUBLIC_KB_RICH",
        de_organizacion={"merge": "passthrough"},
        del_chatbot={"merge": "dedup_por_documento"},
    )

    assert resuelto["merge"] == "dedup_por_documento"


def test_should_treat_null_and_empty_as_inherit() -> None:
    por_defecto = _resolver_estrategias("PUBLIC_KB_RICH", None, None)

    assert _resolver_estrategias("PUBLIC_KB_RICH", {}, {}) == por_defecto
    assert _resolver_estrategias("PUBLIC_KB_RICH", None, {"merge": ""}) == por_defecto, (
        "Una cadena vacía es «no he elegido», no «ninguna estrategia»: un CoreGraph con un eje "
        "vacío no se puede ejecutar."
    )


# ---------------------------------------------------------------------------
# 4. La sobreescritura se aplica al construir
# ---------------------------------------------------------------------------


def test_should_replace_only_the_overridden_axis() -> None:
    cfg = _cfg(estrategias={**COMPOSICION_PUBLIC_KB_RICH, "merge": "dedup_por_documento"})
    grafo = _make_public_kb_rich(cfg, None, None)
    template_antes = grafo.template_strategy

    _aplicar_sobreescrituras(grafo, cfg, None, None)

    assert type(grafo.merge_strategy).__name__ == "_DedupPorDocumento", (
        "El eje sobreescrito tiene que llevar la estrategia del paquete instalado."
    )
    assert grafo.template_strategy is template_antes, (
        "Y los demás ejes no se tocan: ni se reinstancian, que cambiaría su identidad."
    )


def test_should_apply_a_strategy_from_an_installed_package_and_it_does_something() -> None:
    """No basta con que sea la clase esperada: tiene que CAMBIAR la salida."""
    from server.app.modules.agents_hub.agent.public_graphs.strategies.retrieval_contract import (
        EvidenceItem,
    )

    cfg = _cfg(estrategias={**COMPOSICION_PUBLIC_KB_RICH, "template": "con_cabecera"})
    grafo = _make_public_kb_rich(cfg, None, None)
    _aplicar_sobreescrituras(grafo, cfg, None, None)

    salida = grafo.template_strategy.build_prompt_context(
        [EvidenceItem(source_id="d1", content="contenido", score=1.0)], "es", "consulta"
    )

    assert "[CABECERA DEL PAQUETE DEMO]" in salida


def test_should_fail_loudly_when_a_configured_strategy_is_not_registered() -> None:
    """Nunca caer al defecto en silencio — la lección del hallazgo I5."""
    cfg = _cfg(estrategias={**COMPOSICION_PUBLIC_KB_RICH, "merge": "no_existe"})
    grafo = _make_public_kb_rich(cfg, None, None)

    with pytest.raises(RuntimeError) as exc:
        _aplicar_sobreescrituras(grafo, cfg, None, None)

    mensaje = str(exc.value)
    assert "merge" in mensaje
    assert "no_existe" in mensaje
    assert str(cfg.chatbot_id) in mensaje, (
        "El error nombra el chatbot: con varios configurados, saber cuál es lo primero que hace "
        "falta."
    )


# ---------------------------------------------------------------------------
# 5. El cruce con LANG, que es el que puede confundir
# ---------------------------------------------------------------------------


def test_should_let_an_explicit_language_axis_win_over_language_mode() -> None:
    """`language_mode` elige el DEFECTO del eje; nombrar una estrategia manda sobre él.

    Lo más específico gana: quien escribe `{"language": "neutral"}` está pidiendo exactamente
    ésa, mientras que `language_mode` es un ajuste de organización que se hereda.
    """
    cfg = _cfg(
        language_mode="prefer",  # con esto, el defecto sería DefaultLanguagePolicy
        estrategias={**COMPOSICION_PUBLIC_KB_RICH, "language": "neutral"},
    )
    grafo = _make_public_kb_rich(cfg, None, None)
    _aplicar_sobreescrituras(grafo, cfg, None, None)

    assert type(grafo.language_policy).__name__ == "NeutralLanguagePolicy"


def test_should_follow_language_mode_when_the_axis_is_not_overridden() -> None:
    """Y sin sobreescritura explícita, LANG sigue mandando como hasta ahora."""
    cfg = _cfg(language_mode="none", estrategias=dict(COMPOSICION_PUBLIC_KB_RICH))
    grafo = _make_public_kb_rich(cfg, None, None)
    _aplicar_sobreescrituras(grafo, cfg, None, None)

    assert type(grafo.language_policy).__name__ == "NeutralLanguagePolicy"


# ---------------------------------------------------------------------------
# 6. Descubrimiento y verificación
# ---------------------------------------------------------------------------


def test_should_discover_strategies_from_an_installed_package() -> None:
    assert "dedup_por_documento" in sreg.list_strategies("merge")
    assert "con_cabecera" in sreg.list_strategies("template")


def test_should_reject_a_strategy_declared_in_the_wrong_axis(monkeypatch) -> None:
    """Estar en el eje `merge` no la convierte en una `MergeStrategy`."""
    from server.app.modules.agents_hub.agent.public_graphs import plugins

    class _Punto:
        name = "merge.impostora"
        dist = type("D", (), {"name": "paquete-impostor"})()

        def load(self):
            return lambda cfg, deps, llm=None: object()  # sin método `merge`

    monkeypatch.setattr(plugins, "_puntos_de_entrada", lambda grupo: [_Punto()])
    plugins.descubrir_estrategias()
    try:
        with pytest.raises(RuntimeError) as exc:
            plugins.verificar_estrategias_registradas()
        assert "merge.impostora" in str(exc.value)
    finally:
        sreg._default_registry._por_eje[sreg.EjeDeEstrategia.MERGE].pop("impostora", None)


def test_should_reject_an_entry_point_without_the_axis_prefix(monkeypatch) -> None:
    from server.app.modules.agents_hub.agent.public_graphs import plugins

    class _Punto:
        name = "sin_punto"
        dist = type("D", (), {"name": "paquete-raro"})()

        def load(self):
            return lambda cfg, deps, llm=None: object()

    monkeypatch.setattr(plugins, "_puntos_de_entrada", lambda grupo: [_Punto()])

    with pytest.raises(RuntimeError) as exc:
        plugins.descubrir_estrategias()

    assert "<eje>.<nombre>" in str(exc.value)


def test_should_name_the_distribution_when_the_axis_does_not_exist(monkeypatch) -> None:
    from server.app.modules.agents_hub.agent.public_graphs import plugins

    class _Punto:
        name = "inventado.x"
        dist = type("D", (), {"name": "paquete-con-eje-raro"})()

        def load(self):
            return lambda cfg, deps, llm=None: object()

    monkeypatch.setattr(plugins, "_puntos_de_entrada", lambda grupo: [_Punto()])

    with pytest.raises(RuntimeError) as exc:
        plugins.descubrir_estrategias()

    assert "paquete-con-eje-raro" in str(exc.value)


def test_the_loader_gained_the_third_discoverer() -> None:
    from server.app.modules.agents_hub.agent.public_graphs import plugins

    assert plugins.descubrir_estrategias in plugins.DESCUBRIDORES


# ---------------------------------------------------------------------------
# 7. El CHECK de la base, que cerraba el vocabulario donde más duele
# ---------------------------------------------------------------------------


def test_should_not_constrain_retrieval_mode_in_the_database() -> None:
    """Un CHECK no puede saber qué paquetes hay instalados; el registro sí.

    Mientras estuvo, el modo se validaba contra el registro vivo en el router, pasaba, y
    Postgres lo rechazaba al guardar: la funcionalidad entera era inalcanzable para un tercero.
    """
    from server.app.modules.agents_hub.database.config_models import HubChatbot

    nombres = {
        c.name for c in HubChatbot.__table__.constraints if getattr(c, "name", None)
    }
    assert "ck_chatbot_retrieval_mode" not in nombres

    # Y los tres que SÍ son estructura siguen ahí: cada uno tiene código que lo aplica.
    for esperado in ("ck_chatbot_kind", "ck_chatbot_access_mode"):
        assert esperado in nombres, f"Se ha perdido {esperado}, que sí es estructura."
