"""PLG.3 — el catálogo de lo que ESTA instalación ofrece.

El endpoint existe porque desde PLG.1 la lista **no se puede conocer en tiempo de compilación**:
depende de qué paquetes haya instalados. El frontend llevaba los cuatro nombres escritos en tres
ficheros, que además de violar la regla maestra de contrato —la UI no conoce las opciones a
priori— era lo primero con lo que un perfil instalado se habría dado de bruces.

Lo que se fija aquí es **qué tiene que llegar para que el panel pueda pintarse sin saber nada**:
los ejes (para poner un select por cada uno), qué perfiles no son seleccionables y por qué, y de
dónde viene cada estrategia.
"""

from __future__ import annotations

import asyncio

from server.app.routers.hub_chatbots_router import opciones_de_grafo


def _opciones():
    return asyncio.run(opciones_de_grafo(user=None))


def test_should_list_the_core_profiles_and_modes() -> None:
    r = _opciones()

    nombres = {p.nombre for p in r.perfiles}
    assert {"PUBLIC_KB_RICH", "PUBLIC_PORTAL_AGGREGATOR", "PUBLIC_PORTAL_ROUTER"} <= nombres
    assert {"RAG", "MD_LONG_CONTEXT", "MD_AGENT_SELECTOR"} <= {m.nombre for m in r.modos}


def test_should_mark_unconfigured_profiles_as_not_selectable() -> None:
    """Se ofrecen pero no se pueden elegir, y el panel los enseña deshabilitados.

    Ocultarlos sería peor: dejaría sin explicar por qué un perfil que existe no aparece.
    """
    r = _opciones()
    por_nombre = {p.nombre: p for p in r.perfiles}

    assert por_nombre["PUBLIC_KB_RICH"].configurable is True
    assert por_nombre["PUBLIC_PORTAL_ROUTER"].configurable is False
    assert por_nombre["PUBLIC_PORTAL_AGGREGATOR"].configurable is False


def test_should_send_the_axes_so_the_panel_does_not_know_them() -> None:
    """El panel pinta un select por eje **iterando esta lista**, no una constante de React."""
    r = _opciones()

    assert r.ejes == ["retrieval", "merge", "template", "language"]
    assert set(r.estrategias) == set(r.ejes), (
        "Cada eje trae su lista, aunque esté vacía: si faltara la clave, el panel tendría que "
        "tratar ese caso y volvería a saber algo que no debe."
    )


def test_should_say_where_each_strategy_comes_from() -> None:
    """Una estrategia de un paquete desaparece si alguien lo desinstala. Quien la elige debería
    poder verlo."""
    r = _opciones()

    del_nucleo = [e for e in r.estrategias["merge"] if e.nombre == "passthrough"]
    assert del_nucleo
    assert del_nucleo[0].origen == "nucleo"

    de_paquete = [e for e in r.estrategias["merge"] if e.nombre == "dedup_por_documento"]
    assert de_paquete, "Falta la estrategia del paquete demo: ¿está instalado?"
    assert de_paquete[0].origen == "paquete"


def test_should_include_what_an_installed_package_contributes() -> None:
    r = _opciones()

    assert "DEMO_KB_RICH" in {p.nombre for p in r.perfiles}
    assert "DEMO_PIPELINE" in {m.nombre for m in r.modos}
    assert "con_cabecera" in {e.nombre for e in r.estrategias["template"]}


def test_should_expose_the_default_composition_of_the_operational_profile() -> None:
    """El panel enseña qué monta el perfil cuando no se sobreescribe nada."""
    r = _opciones()
    kb_rich = next(p for p in r.perfiles if p.nombre == "PUBLIC_KB_RICH")

    assert kb_rich.composicion == {
        "retrieval": "single_source",
        "merge": "passthrough",
        "template": "generic",
        "language": "default",
    }


def test_should_take_descriptions_from_docstrings_and_not_invent_i18n() -> None:
    """La descripción es opcional a propósito.

    No se traduce lo que aporta un tercero: sería prometer una calidad que no podemos sostener.
    Si un paquete no documenta su estrategia, el panel enseña el nombre y ya.
    """
    r = _opciones()
    generic = next(e for e in r.estrategias["template"] if e.nombre == "generic")

    assert generic.descripcion, "Las del núcleo sí están documentadas y su docstring se usa."
    assert isinstance(generic.descripcion, str)
