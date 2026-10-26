"""Registry de perfiles de grafo público.

Deploy: edge

**El nombre de un perfil es una cadena, no un miembro de un `Enum`.** Lo era hasta PLG.1, y un
enum cerrado en el núcleo es incompatible por construcción con que alguien aporte un perfil desde
un paquete instalado: no se le pueden añadir miembros desde fuera. Es la regla del proyecto «el
vocabulario es dato» aplicada aquí; lo que sigue siendo estructura —qué es un perfil, qué firma
tiene su factoría— vive en el código.

**Y registrar dos veces el mismo nombre falla en alto.** Antes sobrescribía en silencio: con dos
paquetes que declararan `PUBLIC_KB_RICH` ganaba el último que cargara `importlib.metadata`, o sea
un orden que nadie controla y sin ningún síntoma. Un conflicto de nombres es una situación que hay
que resolver desinstalando algo, así que se dice.
"""
from collections.abc import Callable
from typing import Any


class UnknownProfileError(KeyError):
    pass


class DuplicateProfileError(ValueError):
    """Dos registros con el mismo nombre. Se resuelve fuera del código, desinstalando."""


ProfileFactory = Callable[..., Any]


class GraphProfileRegistry:
    """Catálogo de perfiles de grafo público registrados en tiempo de ejecución."""

    def __init__(self) -> None:
        self._registry: dict[str, ProfileFactory] = {}

    def register_profile(self, profile: str, factory: ProfileFactory) -> None:
        if profile in self._registry:
            raise DuplicateProfileError(
                f"Ya hay un perfil registrado con el nombre '{profile}'. Dos perfiles no pueden "
                f"compartir nombre: el que gane dependería del orden de carga, que nadie "
                f"controla. Si vienen de paquetes distintos, desinstala uno; si uno es del "
                f"núcleo, el del paquete tiene que cambiar de nombre."
            )
        self._registry[profile] = factory

    def get_profile(self, profile_name: str) -> ProfileFactory:
        try:
            return self._registry[profile_name]
        except KeyError as exc:
            raise UnknownProfileError(profile_name) from exc

    def list_profiles(self) -> list[str]:
        return list(self._registry.keys())


_default_registry = GraphProfileRegistry()


def register_profile(profile: str, factory: ProfileFactory) -> None:
    _default_registry.register_profile(profile, factory)


def get_profile(profile_name: str) -> ProfileFactory:
    return _default_registry.get_profile(profile_name)


def list_profiles() -> list[str]:
    return _default_registry.list_profiles()
