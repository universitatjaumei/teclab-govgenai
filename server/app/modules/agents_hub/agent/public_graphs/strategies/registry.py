"""Registro de estrategias por eje.

Deploy: edge

**Los ejes son ESTRUCTURA; los nombres de estrategia son VOCABULARIO.** Por eso `EjeDeEstrategia`
es un `StrEnum` cerrado y los nombres son cadenas registradas: añadir un eje exige de todos modos
escribir el nodo del `CoreGraph` que lo consuma, así que un eje nuevo no puede llegar por
instalación; una estrategia nueva sí. Es la regla del proyecto —«el vocabulario es dato»—
aplicada con su matiz, no a bulto.

**Qué compra esto.** Antes, cambiar cómo se fusionan los resultados de un chatbot exigía un
perfil nuevo: una factoría, su registro, sus tests. Ahora es **una clave** en la columna
`estrategias` del chatbot, y la estrategia puede venir de un paquete instalado. Un chatbot de
normativa que quiera deduplicar por documento cambia `{"merge": "dedup_por_documento"}` y nada
más.

**Y lo que NO es un eje: el bucle agéntico.** Lo monta `build_agentic_loop_if_needed` a partir del
modo de recuperación y de sus dependencias, y convertirlo en enchufe exigiría antes separar sus
tres colaboradores —lector, buscador y puntuador—, que hoy se construyen juntos. Queda anotado
como candidato; meterlo ahora sería declarar un eje que no se puede sustituir de verdad.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from typing import Any

from server.app.modules.agents_hub.agent.public_graphs.strategies.protocols import (
    LanguagePolicy,
    MergeStrategy,
    RetrievalStrategy,
    TemplateStrategy,
)


class EjeDeEstrategia(StrEnum):
    """Los cuatro protocolos que compone un `CoreGraph`. Estructura, no vocabulario."""

    RETRIEVAL = "retrieval"
    MERGE = "merge"
    TEMPLATE = "template"
    LANGUAGE = "language"


#: Qué protocolo tiene que cumplir una estrategia según el eje en el que se registre. Es lo que
#: permite rechazar **al arrancar** una estrategia puesta en el eje equivocado, en vez de dejar
#: que reviente al ejecutarse con un `AttributeError` sin contexto.
PROTOCOLO_DE_EJE: dict[EjeDeEstrategia, type] = {
    EjeDeEstrategia.RETRIEVAL: RetrievalStrategy,
    EjeDeEstrategia.MERGE: MergeStrategy,
    EjeDeEstrategia.TEMPLATE: TemplateStrategy,
    EjeDeEstrategia.LANGUAGE: LanguagePolicy,
}

#: Eje -> atributo del `CoreGraph` que ese eje ocupa. Vive aquí y no en la factoría para que la
#: correspondencia esté en un solo sitio: es lo que se consulta al aplicar una sobreescritura.
ATRIBUTO_DE_EJE: dict[EjeDeEstrategia, str] = {
    EjeDeEstrategia.RETRIEVAL: "retrieval_strategy",
    EjeDeEstrategia.MERGE: "merge_strategy",
    EjeDeEstrategia.TEMPLATE: "template_strategy",
    EjeDeEstrategia.LANGUAGE: "language_policy",
}

EstrategiaFactory = Callable[..., Any]


class UnknownStrategyError(KeyError):
    pass


class DuplicateStrategyError(ValueError):
    """Mismo nombre, mismo eje. Igual que en perfiles: nunca sobrescribir en silencio."""


class StrategyRegistry:
    def __init__(self) -> None:
        self._por_eje: dict[EjeDeEstrategia, dict[str, EstrategiaFactory]] = {
            eje: {} for eje in EjeDeEstrategia
        }

    @staticmethod
    def _eje(eje: str | EjeDeEstrategia) -> EjeDeEstrategia:
        try:
            return EjeDeEstrategia(eje)
        except ValueError as exc:
            raise ValueError(
                f"'{eje}' no es un eje de estrategia. Los ejes son "
                f"{[e.value for e in EjeDeEstrategia]}, y son estructura: añadir uno exige "
                f"escribir el nodo del CoreGraph que lo consuma, así que no puede llegar por "
                f"instalación."
            ) from exc

    def register_strategy(
        self, eje: str | EjeDeEstrategia, nombre: str, factoria: EstrategiaFactory
    ) -> None:
        eje_ = self._eje(eje)
        if nombre in self._por_eje[eje_]:
            raise DuplicateStrategyError(
                f"Ya hay una estrategia '{nombre}' registrada en el eje '{eje_.value}'. El que "
                f"ganara dependería del orden de carga, que nadie controla."
            )
        self._por_eje[eje_][nombre] = factoria

    def get_strategy(self, eje: str | EjeDeEstrategia, nombre: str) -> EstrategiaFactory:
        eje_ = self._eje(eje)
        try:
            return self._por_eje[eje_][nombre]
        except KeyError as exc:
            raise UnknownStrategyError(
                f"No hay ninguna estrategia '{nombre}' en el eje '{eje_.value}'. Disponibles: "
                f"{sorted(self._por_eje[eje_])}."
            ) from exc

    def list_strategies(self, eje: str | EjeDeEstrategia) -> list[str]:
        return sorted(self._por_eje[self._eje(eje)])


_default_registry = StrategyRegistry()


def register_strategy(
    eje: str | EjeDeEstrategia, nombre: str, factoria: EstrategiaFactory
) -> None:
    _default_registry.register_strategy(eje, nombre, factoria)


def get_strategy(eje: str | EjeDeEstrategia, nombre: str) -> EstrategiaFactory:
    return _default_registry.get_strategy(eje, nombre)


def list_strategies(eje: str | EjeDeEstrategia) -> list[str]:
    return _default_registry.list_strategies(eje)


def todas_las_estrategias() -> dict[str, list[str]]:
    """Todo el catálogo, por eje. Lo consume el endpoint de opciones de PLG.3."""
    return {eje.value: list_strategies(eje) for eje in EjeDeEstrategia}
