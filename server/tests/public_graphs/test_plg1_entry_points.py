"""PLG.1 — perfiles y pipelines descubiertos por *entry points*, y el núcleo entra por ahí.

**La regla que gobierna este fichero es «un solo camino de registro».** El cargador de *entry
points* y el núcleo usan la misma función; no hay un registro «de plugins» aparte. Si el núcleo
tuviera un atajo, el motor podría acabar dependiendo de algo que un tercero no puede aportar, y
nadie se enteraría hasta que llegara el primer tercero.

Lo que se fija aquí, y cada cosa viene de un modo de fallo concreto:

* **Registrar dos veces el mismo nombre falla.** Hoy `register_profile` **sobrescribe en
  silencio**: dos paquetes con el mismo nombre y gana el último cargado, que depende del orden de
  `importlib.metadata`. O sea, no determinista y sin síntoma.
* **Un *entry point* que no carga aborta el arranque nombrando su distribución.** La alternativa
  —avisar y seguir— deja un servidor en pie al que le falta un perfil, y el usuario ve «perfil
  desconocido» sin saber que había un paquete roto.
* **Los nombres son cadenas validadas contra el registro, no un `Enum`.** Un `Enum` cerrado en el
  núcleo es incompatible por construcción con que alguien aporte un perfil: no puede añadir un
  miembro. Es la regla «el vocabulario es dato» aplicada aquí.
* **El perfil registrado se comprueba AL ARRANCAR, no en la primera petición.** Es lo que ya hace
  `test_profile_contract` para lo que está en el árbol, llevado al arranque para lo instalado.
"""

from __future__ import annotations

import pytest

from server.app.modules.agents_hub.agent.public_graphs import registry


@pytest.fixture(autouse=True)
def registro_limpio():
    """Cada test parte de un registro propio y lo restaura al salir.

    El registro es un singleton de módulo. Sin esto, un test que registra «demo» se lo deja
    puesto al siguiente, que es exactamente la clase de estado filtrado que `-n0` en CI existe
    para cazar — y que ya costó un rojo en esta sesión con la semilla global de Faker.
    """
    original = dict(registry._default_registry._registry)
    yield
    registry._default_registry._registry.clear()
    registry._default_registry._registry.update(original)


# ---------------------------------------------------------------------------
# 1. El registro: nombres de cadena y sin sobrescritura silenciosa
# ---------------------------------------------------------------------------


def test_should_register_a_profile_by_string_name() -> None:
    """El nombre es `str`. Un perfil instalado no puede ser miembro de un enum del núcleo."""
    registry.register_profile("PERFIL_DE_PRUEBA", lambda cfg, deps, llm=None: object())

    assert "PERFIL_DE_PRUEBA" in registry.list_profiles()
    assert callable(registry.get_profile("PERFIL_DE_PRUEBA"))


def test_should_reject_registering_the_same_name_twice() -> None:
    """Hoy sobrescribe en silencio, y eso hace que gane el último en cargarse."""
    registry.register_profile("DUPLICADO", lambda cfg, deps, llm=None: object())

    with pytest.raises(ValueError, match="DUPLICADO") as exc:
        registry.register_profile("DUPLICADO", lambda cfg, deps, llm=None: object())

    assert "DUPLICADO" in str(exc.value), (
        "El error tiene que nombrar el perfil en conflicto: si dos paquetes chocan, lo primero "
        "que hace falta saber es cuál."
    )


def test_should_keep_the_core_profiles_registered() -> None:
    """Regresión: el núcleo sigue aportando sus tres perfiles, entre por donde entre."""
    perfiles = registry.list_profiles()

    for esperado in ("PUBLIC_KB_RICH", "PUBLIC_PORTAL_AGGREGATOR", "PUBLIC_PORTAL_ROUTER"):
        assert esperado in perfiles, (
            f"Falta el perfil del núcleo {esperado!r}. Si el descubrimiento por entry points "
            f"no llega a ejecutarse, el servidor arranca sin perfiles y el síntoma aparece en "
            f"la primera petición, no al arrancar."
        )


# ---------------------------------------------------------------------------
# 2. El enum se retira
# ---------------------------------------------------------------------------


def test_should_not_expose_a_closed_enum_of_profiles() -> None:
    """`PublicGraphProfile` desaparece: un tercero no cabe en un enum del núcleo."""
    from server.app.modules.agents_hub.agent.public_graphs import types

    assert not hasattr(types, "PublicGraphProfile"), (
        "`PublicGraphProfile` sigue existiendo. Mientras esté, el nombre de un perfil es un "
        "vocabulario cerrado en el código y la regla del proyecto dice que el vocabulario es "
        "dato. Sin shims ni re-exports: se retira."
    )


def test_should_keep_perfiles_sin_configurar_as_strings() -> None:
    """Sigue significando lo mismo, pero con cadenas."""
    from server.app.modules.agents_hub.agent.public_graphs.core.graph_factory import (
        PERFILES_SIN_CONFIGURAR,
    )

    assert PERFILES_SIN_CONFIGURAR == frozenset(
        {"PUBLIC_PORTAL_AGGREGATOR", "PUBLIC_PORTAL_ROUTER"}
    )
    assert all(isinstance(p, str) for p in PERFILES_SIN_CONFIGURAR)


# ---------------------------------------------------------------------------
# 3. Los pipelines: de cadena de `if` a registro
# ---------------------------------------------------------------------------


def test_should_list_the_core_retrieval_modes() -> None:
    from server.app.modules.agents_hub.agent.public_graphs.strategies import (
        retrieval_pipeline_factory as fabrica,
    )

    modos = fabrica.list_modes()

    for esperado in ("RAG", "MD_LONG_CONTEXT", "MD_AGENT_SELECTOR"):
        assert esperado in modos


def test_should_build_each_core_pipeline_from_the_registry() -> None:
    """Regresión: los tres modos del núcleo siguen construyendo su clase de siempre."""
    from server.app.modules.agents_hub.agent.public_graphs.strategies import (
        retrieval_pipeline_factory as fabrica,
    )

    assert type(fabrica.get_pipeline("RAG")).__name__ == "RagVectorPipeline"
    assert type(fabrica.get_pipeline("MD_LONG_CONTEXT")).__name__ == "MdLongContextPipeline"
    assert type(fabrica.get_pipeline("MD_AGENT_SELECTOR")).__name__ == "MdAgentSelectorPipeline"


def test_should_reject_an_unknown_mode_listing_the_available_ones() -> None:
    from server.app.modules.agents_hub.agent.public_graphs.strategies import (
        retrieval_pipeline_factory as fabrica,
    )

    with pytest.raises(ValueError, match="NO_EXISTE") as exc:
        fabrica.get_pipeline("NO_EXISTE")

    mensaje = str(exc.value)
    assert "NO_EXISTE" in mensaje
    assert "RAG" in mensaje, (
        "El error lista los modos disponibles. Un «modo desconocido» a secas obliga a ir al "
        "código a ver cuáles hay."
    )


# ---------------------------------------------------------------------------
# 4. El cargador
# ---------------------------------------------------------------------------


def test_should_expose_one_loader_with_a_list_of_discoverers() -> None:
    """PLG.2 añade estrategias al MISMO cargador: el punto de extensión es una lista.

    Tres llamadas sueltas invitan a que la cuarta se registre en otro sitio, y entonces vuelve a
    haber dos caminos.
    """
    from server.app.modules.agents_hub.agent.public_graphs import plugins

    assert isinstance(plugins.DESCUBRIDORES, (list, tuple))
    assert plugins.descubrir_perfiles in plugins.DESCUBRIDORES
    assert plugins.descubrir_pipelines in plugins.DESCUBRIDORES
    assert callable(plugins.descubrir_todo)


def test_should_fail_loudly_when_an_entry_point_does_not_load(monkeypatch) -> None:
    """Un paquete roto aborta el arranque y NOMBRA su distribución."""
    from server.app.modules.agents_hub.agent.public_graphs import plugins

    class _PuntoRoto:
        name = "PERFIL_ROTO"
        value = "paquete_roto:no_existe"
        dist = type("D", (), {"name": "paquete-roto"})()

        def load(self):
            raise ImportError("no such module")

    monkeypatch.setattr(plugins, "_puntos_de_entrada", lambda grupo: [_PuntoRoto()])

    with pytest.raises(RuntimeError) as exc:
        plugins.descubrir_perfiles()

    mensaje = str(exc.value)
    assert "paquete-roto" in mensaje, (
        "El error tiene que nombrar la DISTRIBUCIÓN, no sólo el perfil: quien lee el fallo "
        "necesita saber qué paquete desinstalar o arreglar."
    )
    assert "PERFIL_ROTO" in mensaje


def test_should_fail_loudly_when_two_entry_points_share_a_name(monkeypatch) -> None:
    """Y nombra las DOS distribuciones, que es lo que permite decidir cuál sobra."""
    from server.app.modules.agents_hub.agent.public_graphs import plugins

    def _punto(nombre: str, distribucion: str):
        class _P:
            name = nombre
            dist = type("D", (), {"name": distribucion})()

            def load(self):
                return lambda cfg, deps, llm=None: object()

        return _P()

    monkeypatch.setattr(
        plugins,
        "_puntos_de_entrada",
        lambda grupo: [_punto("CHOCA", "paquete-uno"), _punto("CHOCA", "paquete-dos")],
    )

    with pytest.raises(RuntimeError) as exc:
        plugins.descubrir_perfiles()

    mensaje = str(exc.value)
    assert "paquete-uno" in mensaje
    assert "paquete-dos" in mensaje


def test_should_reject_a_pipeline_that_does_not_satisfy_the_protocol(monkeypatch) -> None:
    """El objeto cargado tiene que cumplir `RetrievalPipeline`, y se comprueba al descubrir."""
    from server.app.modules.agents_hub.agent.public_graphs import plugins

    class _NoEsPipeline:
        """No tiene el método del protocolo."""

    class _Punto:
        name = "PIPELINE_MALO"
        dist = type("D", (), {"name": "paquete-malo"})()

        def load(self):
            return _NoEsPipeline

    monkeypatch.setattr(plugins, "_puntos_de_entrada", lambda grupo: [_Punto()])

    with pytest.raises(RuntimeError) as exc:
        plugins.descubrir_pipelines()

    assert "paquete-malo" in str(exc.value)


# ---------------------------------------------------------------------------
# 5. La verificación de arranque
# ---------------------------------------------------------------------------


def test_should_verify_registered_profiles_at_startup() -> None:
    """Un perfil que no construye tiene que romper el arranque, no la primera petición."""
    from server.app.modules.agents_hub.agent.public_graphs import plugins

    registry.register_profile(
        "PERFIL_QUE_REVIENTA",
        lambda cfg, deps, llm=None: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    with pytest.raises(RuntimeError) as exc:
        plugins.verificar_perfiles_registrados()

    assert "PERFIL_QUE_REVIENTA" in str(exc.value)


def test_should_not_verify_profiles_that_are_declared_unconfigured() -> None:
    """Los de `PERFILES_SIN_CONFIGURAR` lanzan `NotImplementedError` a propósito.

    Verificarlos rompería el arranque por un caso que está documentado y es deliberado.
    """
    from server.app.modules.agents_hub.agent.public_graphs import plugins

    plugins.verificar_perfiles_registrados()  # no lanza: el núcleo está sano


# ---------------------------------------------------------------------------
# 6. La validación de los routers, contra el registro y no contra un `Literal`
# ---------------------------------------------------------------------------


def test_should_reject_an_unknown_profile_listing_the_available_ones() -> None:
    from fastapi import HTTPException

    from server.app.modules.agents_hub.agent.public_graphs.validacion import validar_perfil

    with pytest.raises(HTTPException) as exc:
        validar_perfil("PERFIL_INVENTADO")

    assert exc.value.status_code == 422
    assert "PUBLIC_KB_RICH" in exc.value.detail["disponibles"], (
        "El 422 lista las opciones. Quien configura un chatbot desde el panel no tiene el "
        "código delante para averiguar cuáles hay."
    )


def test_should_reject_a_registered_but_unconfigured_profile() -> None:
    """Registrado y ofrecido, pero su factoría no construye: guardarlo es el hallazgo I5."""
    from fastapi import HTTPException

    from server.app.modules.agents_hub.agent.public_graphs.validacion import validar_perfil

    with pytest.raises(HTTPException) as exc:
        validar_perfil("PUBLIC_PORTAL_ROUTER")

    assert exc.value.status_code == 422
    assert "PUBLIC_PORTAL_ROUTER" not in exc.value.detail["disponibles"], (
        "Un perfil sin configurar no puede aparecer en la lista de alternativas que se ofrece "
        "justo al rechazarlo."
    )


def test_should_accept_none_as_inherit() -> None:
    """`None` es «hereda», y quién hereda de quién lo decide la cascada, no la validación."""
    from server.app.modules.agents_hub.agent.public_graphs.validacion import (
        validar_modo,
        validar_perfil,
    )

    validar_perfil(None)
    validar_modo(None)


def test_should_reject_an_unknown_retrieval_mode() -> None:
    from fastapi import HTTPException

    from server.app.modules.agents_hub.agent.public_graphs.validacion import validar_modo

    with pytest.raises(HTTPException) as exc:
        validar_modo("MODO_INVENTADO")

    assert exc.value.status_code == 422
    assert "RAG" in exc.value.detail["disponibles"]


# ---------------------------------------------------------------------------
# 7. El paquete demo: el camino de un tercero, ejercitado de verdad
# ---------------------------------------------------------------------------


def test_should_discover_a_profile_from_an_installed_package() -> None:
    """`govgenai-demo-perfil` está instalado en el entorno de tests y aporta un perfil.

    Se instala de verdad en vez de simular `importlib.metadata` con mocks, y la diferencia no es
    de pureza: simulándolo quedaría sin probar justo lo que puede fallar —que un paquete REAL se
    encuentre, se cargue y se registre—, que es todo el camino que este bloque construye.
    """
    assert "DEMO_KB_RICH" in registry.list_profiles(), (
        "El perfil del paquete demo no aparece. O no está instalado (`uv sync`) o el "
        "descubrimiento no llegó a ejecutarse."
    )


def test_should_build_a_graph_from_the_installed_package_profile() -> None:
    """Descubrirlo no basta: tiene que construir un grafo utilizable."""
    from server.app.modules.agents_hub.agent.public_graphs.core.config_resolver import (
        PublicGraphConfig,
    )

    factoria = registry.get_profile("DEMO_KB_RICH")
    grafo = factoria(
        PublicGraphConfig(
            profile="DEMO_KB_RICH",
            retrieval_mode="RAG",
            language_mode="prefer",
            quality_threshold=0.6,
            min_retrieval_results=1,
            min_retrieval_score=0.25,
            reranker_enabled=False,
            answer_template="generic",
        ),
        None,
        None,
    )

    for eje in ("retrieval_strategy", "merge_strategy", "template_strategy", "language_policy"):
        assert getattr(grafo, eje, None) is not None, f"El eje {eje} quedó sin asignar."


def test_should_discover_a_pipeline_from_an_installed_package() -> None:
    from server.app.modules.agents_hub.agent.public_graphs.strategies import (
        retrieval_pipeline_factory as fabrica,
    )

    assert "DEMO_PIPELINE" in fabrica.list_modes()
    assert type(fabrica.get_pipeline("DEMO_PIPELINE")).__name__ == "PipelineDemo"


def test_should_accept_the_installed_package_profile_in_validation() -> None:
    """El camino entero: un perfil instalado es seleccionable desde el panel."""
    from server.app.modules.agents_hub.agent.public_graphs.validacion import (
        validar_modo,
        validar_perfil,
    )

    validar_perfil("DEMO_KB_RICH")
    validar_modo("DEMO_PIPELINE")


def test_plg1_el_ejemplo_de_la_guia_es_el_del_paquete_demo() -> None:
    """La guía enseña un `pyproject.toml`; este test comprueba que es el que de verdad funciona.

    **Ampliación acordada con el usuario al planificar el bloque**, sobre el alcance escrito. El
    prompt comprometía documentar «descriptor, grupos, qué valida el arranque, colisiones», y
    faltaba lo que alguien necesita para empezar: **un ejemplo copiable**. El material ya existía
    —la fixture del paquete demo— pero vivía en los tests, así que la guía podía divergir de él
    sin que nada lo dijera.

    Es la clase de documentación que envejece peor: nadie la ejecuta. Aquí sí, y con el mismo
    criterio que `test_repo3_el_indice_de_docs_no_miente.py` — lo que un documento promete se
    comprueba, no se supone.
    """
    from pathlib import Path

    raiz = Path(__file__).resolve().parents[3]
    guia = (raiz / "docs" / "GRAPH_PROFILES.md").read_text(encoding="utf-8")
    manifiesto = (
        raiz / "server" / "tests" / "fixtures" / "paquete_perfil_demo" / "pyproject.toml"
    ).read_text(encoding="utf-8")

    # Las líneas que de verdad enseñan algo: los dos grupos y sus dos entry points. Si el
    # paquete demo cambia de nombre o de grupo, la guía deja de servir para copiar y este test
    # se pone rojo — que es justo cuando hace falta.
    for linea in (
        '[project.entry-points."govgenai.graph_profiles"]',
        'DEMO_KB_RICH = "govgenai_demo_perfil:construir_perfil_demo"',
        '[project.entry-points."govgenai.retrieval_pipelines"]',
        'DEMO_PIPELINE = "govgenai_demo_perfil:PipelineDemo"',
    ):
        assert linea in manifiesto, (
            f"La fixture del paquete demo ya no declara {linea!r}. Si ha cambiado a propósito, "
            f"hay que actualizar el ejemplo de `docs/GRAPH_PROFILES.md` con ella."
        )
        assert linea in guia, (
            f"`docs/GRAPH_PROFILES.md` enseña un ejemplo que NO coincide con el paquete demo: "
            f"falta {linea!r}. Un ejemplo que nadie ejecuta envejece en silencio, y quien lo "
            f"copie se encontrará con que no funciona."
        )


def test_should_not_close_the_retrieval_mode_in_the_dto() -> None:
    """El `Literal` cerrado se retira: un modo de un paquete instalado no habría pasado nunca."""
    import inspect

    from server.app.routers import hub_chatbots_router

    fuente = inspect.getsource(hub_chatbots_router)
    assert 'Literal["RAG"' not in fuente, (
        "Queda un `Literal` cerrado de modos en el router. Mientras esté, FastAPI rechaza un "
        "modo aportado por un paquete antes de que la validación pueda verlo, y el bloque "
        "entero deja de servir para lo que se hizo."
    )
