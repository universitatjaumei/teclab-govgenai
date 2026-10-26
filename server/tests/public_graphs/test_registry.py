"""Tests del registry de perfiles de grafo público — TDD RED (9B.1)."""
import pytest


from server.app.modules.agents_hub.agent.public_graphs.registry import (
    GraphProfileRegistry,
    UnknownProfileError,
)


def _make_factory(name: str):
    def factory():
        return f"graph:{name}"
    return factory


class TestGraphProfileRegistry:

    def setup_method(self):
        self.registry = GraphProfileRegistry()

    def test_registry_lists_profiles(self) -> None:
        self.registry.register_profile("PUBLIC_KB_RICH", _make_factory("kb_rich"))
        self.registry.register_profile("PUBLIC_PORTAL_AGGREGATOR", _make_factory("aggregator"))

        profiles = self.registry.list_profiles()

        assert "PUBLIC_KB_RICH" in profiles
        assert "PUBLIC_PORTAL_AGGREGATOR" in profiles

    def test_registry_raises_on_unknown_profile(self) -> None:
        with pytest.raises(UnknownProfileError, match="unknown_profile"):
            self.registry.get_profile("unknown_profile")

    def test_registry_can_register_and_get_profile(self) -> None:
        factory = _make_factory("kb_rich")
        self.registry.register_profile("PUBLIC_KB_RICH", factory)

        retrieved = self.registry.get_profile("PUBLIC_KB_RICH")

        assert retrieved is factory

    def test_registry_lists_empty_when_no_profiles_registered(self) -> None:
        assert self.registry.list_profiles() == []

    def test_registry_rejects_duplicate_registration(self) -> None:
        """PLG.1 invierte esto a propósito: antes sobrescribía en silencio.

        El test anterior se llamaba `..._overwrites_on_duplicate_registration` y afirmaba que
        ganaba el último. Con el descubrimiento por *entry points* eso deja de ser una curiosidad
        y pasa a ser un fallo: **quién gana depende del orden en que `importlib.metadata`
        devuelva los paquetes**, que nadie controla, y el síntoma sería un perfil que se comporta
        distinto según la máquina. Un choque de nombres se resuelve fuera del código
        —desinstalando algo— así que lo que toca es decirlo, no elegir por el usuario.
        """
        import pytest

        factory_a = _make_factory("a")
        factory_b = _make_factory("b")
        self.registry.register_profile("PUBLIC_KB_RICH", factory_a)

        with pytest.raises(ValueError, match="PUBLIC_KB_RICH"):
            self.registry.register_profile("PUBLIC_KB_RICH", factory_b)

        assert self.registry.get_profile("PUBLIC_KB_RICH") is factory_a, (
            "El primero registrado se queda: rechazar el segundo no puede dejar el registro a "
            "medias."
        )
