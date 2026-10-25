"""RetrievalPipelineFactory — devuelve el pipeline correcto según retrieval_mode.

Deploy: edge

**Registro, no cadena de `if`** (PLG.1). La cadena de `if` era un vocabulario cerrado en el
código: un pipeline aportado por un paquete instalado no tenía dónde entrar. Ahora los tres modos
del núcleo se registran por **la misma** función que usa el cargador de *entry points*, que es la
regla «un solo camino de registro»: si el núcleo tuviera un atajo, podría acabar dependiendo de
algo que un tercero no puede aportar sin que nadie se entere.

Los imports siguen siendo perezosos, dentro de cada fábrica: importar los tres pipelines al cargar
este módulo arrastraría sus dependencias —y las de sus dependencias— en cualquier proceso que sólo
quisiera listar los modos.
"""
from __future__ import annotations

from collections.abc import Callable

from server.app.modules.agents_hub.agent.public_graphs.strategies.retrieval_pipeline_protocol import (
    RetrievalPipeline,
)

#: nombre del modo -> algo que construye su pipeline.
_REGISTRO: dict[str, Callable[[], RetrievalPipeline]] = {}


class DuplicatePipelineError(ValueError):
    """Dos registros con el mismo modo. Mismo criterio que en el registro de perfiles."""


def register_pipeline(mode: str, factory: Callable[[], RetrievalPipeline]) -> None:
    if mode in _REGISTRO:
        raise DuplicatePipelineError(
            f"Ya hay un pipeline registrado para el modo '{mode}'. El que ganara dependería del "
            f"orden de carga; si vienen de paquetes distintos, desinstala uno."
        )
    _REGISTRO[mode] = factory


def get_pipeline(mode: str) -> RetrievalPipeline:
    """Devuelve una instancia del pipeline correspondiente a *mode*.

    Raises:
        ValueError: si *mode* no está registrado. El mensaje lista los disponibles, porque un
            «modo desconocido» a secas obliga a ir al código a ver cuáles hay.
    """
    try:
        fabrica = _REGISTRO[mode]
    except KeyError as exc:
        raise ValueError(
            f"Unknown retrieval mode: {mode!r}. Valid modes: {sorted(_REGISTRO)}"
        ) from exc
    return fabrica()


def list_modes() -> list[str]:
    return sorted(_REGISTRO)


# PLG.1 — **aquí ya no se registra nada.** Los tres modos del núcleo se declaran como *entry
# points* del grupo `govgenai.retrieval_pipelines` en `server/pyproject.toml` y los registra el
# cargador (`public_graphs/plugins.py`), igual que haría un paquete de terceros.
#
# Lo que se pierde y conviene decirlo: los imports perezosos que había aquí. Al descubrir, los
# tres módulos se importan. Es aceptable —el servidor los necesita de todas formas— y a cambio
# desaparece el segundo camino de registro, que era el problema.
#
# Si `list_modes()` sale vacío en un test, lo que falta es `plugins.descubrir_todo()`; importar
# este módulo ya no basta, a propósito.
