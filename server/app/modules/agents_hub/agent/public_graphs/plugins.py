"""Descubrimiento de perfiles y pipelines por *entry points*.

Deploy: edge

**Un solo camino de registro.** Este cargador y el núcleo usan la misma función de registro; no
hay un registro «de plugins» aparte. El argumento a favor no es de simetría sino de garantía: si
el núcleo entra por donde entran los terceros, el motor queda **obligado** a no depender de nada
que no pase por el registro. Con dos caminos, esa dependencia se cuela y no se nota hasta que
llega el primer tercero — y entonces ya está en el diseño.

Tres grupos, y el tercero lo añade PLG.2:

* ``govgenai.graph_profiles`` — nombre del perfil → factoría ``(cfg, deps, llm) -> CoreGraph``.
* ``govgenai.retrieval_pipelines`` — nombre del modo → clase que cumple ``RetrievalPipeline``.
* ``govgenai.strategies`` — ``<eje>.<nombre>`` → factoría de estrategia (PLG.2).

**Se falla en alto, nunca «avisar y seguir».** Un paquete que no carga deja un servidor en pie al
que le falta un perfil, y quien lo eligiera vería «perfil desconocido» sin ninguna pista de que
había un paquete roto. Un nombre duplicado es peor todavía: gana el último que cargue
``importlib.metadata``, o sea un orden que nadie controla, y **sin síntoma**.

**La frontera de confianza, dicha sin rodeos**: un perfil o pipeline instalado corre **en el
proceso del servidor y con los datos del cliente**. No hay *sandbox*. La confianza está en quien
instala, igual que en un plugin de pytest o de Airflow, y así lo dice `docs/GRAPH_PROFILES.md`.
No se finge otra cosa.
"""

from __future__ import annotations

import importlib.metadata as md
from collections.abc import Callable, Iterable
from typing import Any

from server.app.modules.agents_hub.agent.public_graphs import registry
from server.app.modules.agents_hub.agent.public_graphs.strategies import (
    retrieval_pipeline_factory,
)
from server.app.modules.agents_hub.agent.public_graphs.strategies.retrieval_pipeline_protocol import (
    RetrievalPipeline,
)

GRUPO_PERFILES = "govgenai.graph_profiles"
GRUPO_PIPELINES = "govgenai.retrieval_pipelines"
GRUPO_ESTRATEGIAS = "govgenai.strategies"


def _puntos_de_entrada(grupo: str) -> Iterable[Any]:
    """Aislado en una función a propósito: es la costura por la que los tests inyectan.

    Simular un paquete roto o dos que chocan instalando distribuciones de verdad sería lento y
    frágil; lo que importa comprobar es el comportamiento del cargador ante lo que
    `importlib.metadata` devuelva.
    """
    return md.entry_points(group=grupo)


def _nombre_de_distribucion(punto: Any) -> str:
    """De qué paquete viene el *entry point*, para poder nombrarlo en los errores.

    `dist` es opcional en la API de `importlib.metadata` y puede no estar; cuando falta se dice
    «distribución desconocida» en vez de reventar mientras se construye un mensaje de error, que
    convertiría un fallo legible en un `AttributeError` sin contexto.
    """
    dist = getattr(punto, "dist", None)
    nombre = getattr(dist, "name", None) if dist is not None else None
    return nombre or "distribución desconocida"


def _cargar(punto: Any, grupo: str) -> Any:
    try:
        return punto.load()
    except Exception as exc:  # se reenvía con contexto y se aborta
        raise RuntimeError(
            f"El entry point '{punto.name}' del grupo '{grupo}', aportado por "
            f"'{_nombre_de_distribucion(punto)}', no se puede cargar: {exc}. El arranque se "
            f"detiene a propósito: seguir dejaría el servidor sin ese perfil y el síntoma "
            f"aparecería como «perfil desconocido», sin pista del paquete roto."
        ) from exc


def _comprobar_sin_duplicados(puntos: list[Any], grupo: str) -> None:
    vistos: dict[str, str] = {}
    for punto in puntos:
        distribucion = _nombre_de_distribucion(punto)
        if punto.name in vistos:
            raise RuntimeError(
                f"Dos entry points del grupo '{grupo}' declaran el nombre '{punto.name}': "
                f"'{vistos[punto.name]}' y '{distribucion}'. El que ganara dependería del orden "
                f"de carga, que nadie controla. Desinstala uno de los dos."
            )
        vistos[punto.name] = distribucion


def descubrir_perfiles() -> list[str]:
    """Registra los perfiles declarados por *entry points*. Devuelve los nombres registrados."""
    puntos = list(_puntos_de_entrada(GRUPO_PERFILES))
    _comprobar_sin_duplicados(puntos, GRUPO_PERFILES)

    registrados: list[str] = []
    for punto in puntos:
        factoria = _cargar(punto, GRUPO_PERFILES)
        if not callable(factoria):
            raise RuntimeError(
                f"El perfil '{punto.name}' de '{_nombre_de_distribucion(punto)}' no apunta a "
                f"algo invocable. Un entry point de perfil tiene que ser una factoría "
                f"`(cfg, deps, llm) -> CoreGraph`."
            )
        try:
            registry.register_profile(punto.name, factoria)
        except ValueError as exc:
            raise RuntimeError(
                f"El perfil '{punto.name}' de '{_nombre_de_distribucion(punto)}' choca con uno "
                f"ya registrado. {exc}"
            ) from exc
        registrados.append(punto.name)
    return registrados


def descubrir_pipelines() -> list[str]:
    """Registra los pipelines declarados por *entry points*. Devuelve los modos registrados."""
    puntos = list(_puntos_de_entrada(GRUPO_PIPELINES))
    _comprobar_sin_duplicados(puntos, GRUPO_PIPELINES)

    registrados: list[str] = []
    for punto in puntos:
        clase = _cargar(punto, GRUPO_PIPELINES)
        if not (isinstance(clase, type) and issubclass(clase, RetrievalPipeline)):
            raise RuntimeError(
                f"El pipeline '{punto.name}' de '{_nombre_de_distribucion(punto)}' no cumple el "
                f"protocolo `RetrievalPipeline`. Se comprueba AL DESCUBRIR y no en la primera "
                f"petición, para que el fallo salga al arrancar y no delante de un usuario."
            )
        try:
            retrieval_pipeline_factory.register_pipeline(punto.name, clase)
        except ValueError as exc:
            raise RuntimeError(
                f"El pipeline '{punto.name}' de '{_nombre_de_distribucion(punto)}' choca con uno "
                f"ya registrado. {exc}"
            ) from exc
        registrados.append(punto.name)
    return registrados


def descubrir_estrategias() -> list[str]:
    """Registra las estrategias declaradas, con nombre `<eje>.<nombre>` (PLG.2).

    El eje va **en el nombre del *entry point*** y no en el objeto cargado, a propósito: así el
    cargador sabe en qué eje va antes de importar nada, y puede rechazar un eje inventado sin
    ejecutar código del paquete. Lo contrario —preguntarle al objeto— obligaría a cargar primero
    y a fiarse de lo que conteste.
    """
    from server.app.modules.agents_hub.agent.public_graphs.strategies import registry as sreg

    puntos = list(_puntos_de_entrada(GRUPO_ESTRATEGIAS))
    _comprobar_sin_duplicados(puntos, GRUPO_ESTRATEGIAS)

    registrados: list[str] = []
    for punto in puntos:
        distribucion = _nombre_de_distribucion(punto)
        eje, _, nombre = punto.name.partition(".")
        if not nombre:
            raise RuntimeError(
                f"El entry point de estrategia '{punto.name}', de '{distribucion}', no tiene la "
                f"forma '<eje>.<nombre>' (por ejemplo 'merge.dedup_por_documento')."
            )
        try:
            eje_valido = sreg.EjeDeEstrategia(eje)
        except ValueError:
            raise RuntimeError(
                f"La estrategia '{punto.name}' de '{distribucion}' declara el eje '{eje}', que "
                f"no existe. Los ejes son {[e.value for e in sreg.EjeDeEstrategia]} y son "
                f"estructura: añadir uno exige escribir el nodo del CoreGraph que lo consuma."
            ) from None

        factoria = _cargar(punto, GRUPO_ESTRATEGIAS)
        if not callable(factoria):
            raise RuntimeError(
                f"La estrategia '{punto.name}' de '{distribucion}' no apunta a algo invocable. "
                f"Tiene que ser una factoría `(cfg, deps, llm) -> instancia`."
            )
        try:
            sreg.register_strategy(eje_valido, nombre, factoria)
        except ValueError as exc:
            raise RuntimeError(
                f"La estrategia '{punto.name}' de '{distribucion}' choca con una ya "
                f"registrada. {exc}"
            ) from exc
        registrados.append(punto.name)
    return registrados


#: **El punto de extensión es una LISTA, no tres llamadas sueltas.** Con llamadas sueltas, la
#: cuarta acaba registrándose en otro sitio y vuelve a haber dos caminos, que es justo lo que
#: este módulo existe para evitar.
DESCUBRIDORES: list[Callable[[], list[str]]] = [
    descubrir_perfiles,
    descubrir_pipelines,
    descubrir_estrategias,
]


#: Lo que se descubrió en este proceso, o `None` si todavía no se ha descubierto.
_YA_DESCUBIERTO: dict[str, list[str]] | None = None


def descubrir_todo(*, forzar: bool = False) -> dict[str, list[str]]:
    """Ejecuta todos los descubridores. **Idempotente por proceso.**

    Lo idempotente no es cosmética: **el registro falla en alto ante duplicados**, que es lo que
    se quiere cuando dos paquetes chocan, pero un segundo descubrimiento en el mismo proceso no
    es un choque — es el mismo paquete otra vez. Sin esta guarda, cualquier cosa que ejecute el
    *lifespan* dos veces revienta con «PUBLIC_KB_RICH choca con uno ya registrado», que además
    **oculta el error de verdad**: lo destapó `test_el_fallo_de_arranque_se_puede_leer.py`, donde
    el fallo que se quería leer en el log quedó tapado por éste.

    Y no es sólo de tests: `uvicorn --reload` reimporta, `importlib.reload(server.app.main)` es lo
    que hacen los tests de `DEPLOY_MODE`, y un arranque que falla y se reintenta pasaría por aquí
    dos veces.

    `forzar=True` existe para los tests que necesitan volver a descubrir con *entry points*
    simulados; nadie más debería usarlo.
    """
    global _YA_DESCUBIERTO

    if _YA_DESCUBIERTO is not None and not forzar:
        return _YA_DESCUBIERTO

    _YA_DESCUBIERTO = {d.__name__: d() for d in DESCUBRIDORES}
    return _YA_DESCUBIERTO


def verificar_perfiles_registrados() -> None:
    """Construye cada perfil configurable y comprueba que sale un grafo utilizable.

    Es lo que ya hace `tests/public_graphs/test_profile_contract.py` para lo que está en el árbol,
    llevado al arranque para **lo instalado**: un perfil de un paquete no lo cubre ningún test de
    este repositorio, así que si no se comprueba aquí, se comprueba en la primera petición de un
    usuario.

    Los de `PERFILES_SIN_CONFIGURAR` se saltan: lanzan `NotImplementedError` a propósito y
    verificarlos rompería el arranque por un caso documentado y deliberado.
    """
    from server.app.modules.agents_hub.agent.public_graphs.core.config_resolver import (
        PublicGraphConfig,
    )
    from server.app.modules.agents_hub.agent.public_graphs.core.graph_factory import (
        PERFILES_SIN_CONFIGURAR,
    )

    #: La configuración real, con los valores por defecto del perfil operativo. No se inventa un
    #: tipo «mínimo» para esto: construir con el mismo objeto que usa producción es lo que hace
    #: que la comprobación signifique algo.
    cfg_minima = PublicGraphConfig(
        profile="",
        retrieval_mode="RAG",
        language_mode="prefer",
        quality_threshold=0.6,
        min_retrieval_results=1,
        min_retrieval_score=0.25,
        reranker_enabled=False,
        answer_template="generic",
    )

    for nombre in registry.list_profiles():
        if nombre in PERFILES_SIN_CONFIGURAR:
            continue
        factoria = registry.get_profile(nombre)
        try:
            import dataclasses

            grafo = factoria(dataclasses.replace(cfg_minima, profile=nombre), None, None)
        except Exception as exc:  # se reenvía con contexto y se aborta
            raise RuntimeError(
                f"El perfil '{nombre}' está registrado pero no construye: {exc}. El arranque se "
                f"detiene: un perfil que revienta al construirse lo haría en la primera "
                f"petición de quien lo tenga seleccionado."
            ) from exc

        faltan = [
            eje
            for eje in ("retrieval_strategy", "merge_strategy", "template_strategy",
                        "language_policy")
            if getattr(grafo, eje, None) is None
        ]
        if faltan:
            raise RuntimeError(
                f"El perfil '{nombre}' construye un grafo con estrategias sin asignar: {faltan}. "
                f"Un CoreGraph con un eje nulo falla al ejecutarse, no al construirse."
            )


def verificar_estrategias_registradas() -> None:
    """Instancia cada estrategia y comprueba que cumple el protocolo de SU eje (PLG.2).

    Que esté registrada en el eje `merge` no significa que sea una `MergeStrategy`: el nombre del
    *entry point* lo pone quien empaqueta, y equivocarse de eje es fácil. Sin esta comprobación,
    el error saldría como un `AttributeError` a mitad de una conversación, con la estrategia ya
    montada en el grafo y sin ninguna pista del paquete que la aportó.
    """
    import dataclasses

    from server.app.modules.agents_hub.agent.public_graphs.core.config_resolver import (
        PublicGraphConfig,
    )
    from server.app.modules.agents_hub.agent.public_graphs.strategies.registry import (
        PROTOCOLO_DE_EJE,
        EjeDeEstrategia,
        get_strategy,
        list_strategies,
    )

    cfg = PublicGraphConfig(
        profile="",
        retrieval_mode="RAG",
        language_mode="prefer",
        quality_threshold=0.6,
        min_retrieval_results=1,
        min_retrieval_score=0.25,
        reranker_enabled=False,
        answer_template="generic",
    )

    for eje in EjeDeEstrategia:
        protocolo = PROTOCOLO_DE_EJE[eje]
        for nombre in list_strategies(eje):
            try:
                instancia = get_strategy(eje, nombre)(dataclasses.replace(cfg), None, None)
            except Exception as exc:  # se reenvía con contexto y se aborta
                raise RuntimeError(
                    f"La estrategia '{eje.value}.{nombre}' no se puede instanciar: {exc}."
                ) from exc
            if not isinstance(instancia, protocolo):
                raise RuntimeError(
                    f"La estrategia '{eje.value}.{nombre}' no cumple el protocolo "
                    f"'{protocolo.__name__}' de su eje. O está declarada en el eje equivocado, o "
                    f"le falta algún método del contrato."
                )
