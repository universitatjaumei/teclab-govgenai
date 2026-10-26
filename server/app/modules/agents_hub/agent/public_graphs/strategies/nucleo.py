"""Las estrategias del núcleo, declaradas como factorías registrables.

Deploy: edge

**Por qué existe este módulo.** Las clases viven donde vivían —`profiles/public_kb_rich.py` y
`strategies/protocols.py`—; lo que hace falta es una **factoría** por estrategia, con la firma
`(cfg, deps, llm) -> instancia`, que es la que el registro guarda y la que un paquete de terceros
tendría que exponer. Ponerlas aquí evita meter *entry points* en ficheros que ya tienen otra
responsabilidad, y deja en un solo sitio la lista de lo que el núcleo aporta.

Se declaran como *entry points* del grupo `govgenai.strategies` en `server/pyproject.toml`, con el
nombre `<eje>.<nombre>` — el mismo camino que usaría cualquiera.
"""

from __future__ import annotations

from typing import Any


def single_source_retrieval(cfg: Any, deps: Any, llm: Any = None):
    from server.app.modules.agents_hub.agent.public_graphs.profiles.public_kb_rich import (
        SingleSourceRetrievalStrategy,
    )

    return SingleSourceRetrievalStrategy()


def passthrough_merge(cfg: Any, deps: Any, llm: Any = None):
    from server.app.modules.agents_hub.agent.public_graphs.profiles.public_kb_rich import (
        PassthroughMergeStrategy,
    )

    return PassthroughMergeStrategy()


def generic_template(cfg: Any, deps: Any, llm: Any = None):
    """La plantilla genérica **se configura desde `cfg`**, y por eso la factoría recibe `cfg`.

    Es la razón de que la firma sea `(cfg, deps, llm)` y no `()`: una estrategia puede necesitar
    la configuración efectiva del chatbot para construirse. Aquí son el prompt de sistema, el
    modo de recuperación y el índice del router.
    """
    from server.app.modules.agents_hub.agent.public_graphs.profiles.public_kb_rich import (
        GenericAnswerTemplateStrategy,
    )

    return GenericAnswerTemplateStrategy(
        base_system_prompt=getattr(cfg, "system_prompt", None),
        retrieval_mode=getattr(cfg, "retrieval_mode", None) or "RAG",
        router_index=getattr(cfg, "router_index", None),
    )


def default_language(cfg: Any, deps: Any, llm: Any = None):
    """La política que pide `cfg.language_mode` (LANG.1).

    **Aquí se cruzan dos mecanismos y conviene decir cuál manda.** `language_mode` elige la
    política POR DEFECTO del eje `language`; una sobreescritura explícita del eje —`estrategias:
    {"language": "..."}`— manda sobre él, porque es más específica: quien nombra una estrategia
    concreta está pidiendo exactamente ésa. Lo comprueba un test de PLG.2.
    """
    from server.app.modules.agents_hub.agent.public_graphs.core.graph_factory import (
        _politica_de_lengua,
    )

    return _politica_de_lengua(cfg)


def neutral_language(cfg: Any, deps: Any, llm: Any = None):
    """Sin política de lengua: `detect` a `None`, sin segunda búsqueda y sin aviso (LANG)."""
    from server.app.modules.agents_hub.agent.public_graphs.strategies.protocols import (
        NeutralLanguagePolicy,
    )

    return NeutralLanguagePolicy()


def strict_language(cfg: Any, deps: Any, llm: Any = None):
    """Sólo evidencia en la lengua detectada."""
    from server.app.modules.agents_hub.agent.public_graphs.strategies.protocols import (
        StrictLanguagePolicy,
    )

    return StrictLanguagePolicy()
