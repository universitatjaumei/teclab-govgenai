"""Una persona sin acceso a ningún módulo es un estado visible (issue #100).

**Lo que pasó.** `hub_module_grants` estaba **completamente vacía** en producción el 2026-09-22,
con la pantalla de concesiones —`ModulosPage`, desde IDE.5— existiendo desde hacía semanas. No
faltaba la pantalla: faltaba que el estado se viera.

Dar de alta a una persona ocurre en **Personas** y concederle módulos en **Plataforma → Módulos**.
Son dos viajes, el segundo se olvida, y una persona recién creada y una persona sin acceso a nada
**se ven exactamente igual** en el listado. Esa ambigüedad es la que dejó la tabla vacía durante
semanas sin que nadie lo notara, incluido el mantenedor, que fue a buscar la pantalla y no la
encontró teniéndola en el menú.

**Por qué el servidor lo calcula y no la pantalla.** Es la regla maestra de `AGENTS.md`: el
frontend no calcula qué está permitido. Un `if (role !== 'superadmin' && modulos.length === 0)` en
React sería la regla escrita por segunda vez, y se rompería el día que otro rol entre por su rol
—hoy sólo el superadministrador, pero eso es una decisión del servidor, no del React—. Es la
misma forma que ya tienen `puede_borrarse` y `puede_fijar_contrasena`.

**Y el superadministrador no está sin acceso.** `modulos.py` lo dice: «El superadmin no necesita
concesión. Es el rol de la plataforma». Sin esta distinción el aviso saltaría en la única cuenta
que existe en una instalación recién creada, y un aviso que siempre miente se aprende a ignorar.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from server.app.core.auth.models import UserInfo, UserRole


def _persona(role: str = "user", **cambios):
    """Una fila de `hub_users` mínima, con lo que `_a_lectura` necesita."""
    from server.app.modules.agents_hub.database.config_models import HubUser

    campos = {
        "id": uuid.uuid4(),
        "email": "persona@uji.es",
        "display_name": "Una Persona",
        "role": role,
        "organizacion_id": uuid.uuid4(),
        "is_active": True,
        "origen": "local",
        "created_at": datetime.now(timezone.utc),
        "created_by": None,
        "last_login_at": None,
    }
    campos.update(cambios)
    return HubUser(**campos)


_QUIEN_PREGUNTA = UserInfo(
    user_id="00000000-0000-0000-0000-0000000000f1",
    email="plataforma@test.com",
    role=UserRole.SUPERADMIN.value,
)


class TestElContratoLoDiceElServidor:
    def test_la_lectura_de_una_persona_publica_sus_modulos(self) -> None:
        from server.app.routers.hub_users_router import _a_lectura

        lectura = _a_lectura(
            _persona(), quien=_QUIEN_PREGUNTA, modulos=["chatbots", "informes"]
        )

        assert lectura.modulos_concedidos == ["chatbots", "informes"]

    def test_una_persona_sin_concesiones_sale_marcada(self) -> None:
        """El estado que era indistinguible de una recién creada."""
        from server.app.routers.hub_users_router import _a_lectura

        lectura = _a_lectura(_persona(), quien=_QUIEN_PREGUNTA, modulos=[])

        assert lectura.modulos_concedidos == []
        assert lectura.sin_concesion_directa is True, (
            "una persona con rol y sin ninguna concesión no se distingue de una recién creada, "
            "que es cómo `hub_module_grants` llegó a estar vacía en producción sin que nadie "
            "lo notara"
        )

    def test_con_una_concesion_ya_no_esta_marcada(self) -> None:
        """El camino bueno, sin el cual «marcar» y «marcar siempre» se parecen demasiado."""
        from server.app.routers.hub_users_router import _a_lectura

        lectura = _a_lectura(_persona(), quien=_QUIEN_PREGUNTA, modulos=["informes"])

        assert lectura.sin_concesion_directa is False


class TestElSuperadministradorNoEstaSinAcceso:
    """Entra por su rol, no por concesión. Si saltara aquí, el aviso mentiría siempre."""

    def test_no_se_marca_aunque_no_tenga_ninguna_concesion(self) -> None:
        from server.app.routers.hub_users_router import _a_lectura

        lectura = _a_lectura(
            _persona(role=UserRole.SUPERADMIN.value), quien=_QUIEN_PREGUNTA, modulos=[]
        )

        assert lectura.sin_concesion_directa is False, (
            "el superadministrador entra en todo por su rol —`modulos.py`: «no necesita "
            "concesión»— y marcarlo haría saltar el aviso en la única cuenta que existe en una "
            "instalación recién creada"
        )


class TestSinDatosNoSeInventaUnAviso:
    """`modulos` es opcional para no obligar a los llamadores que sólo describen la fila.

    Sin él **no se marca**, que es el fallo seguro y el mismo criterio que
    `puede_fijar_contrasena`: un aviso que no aparece se puede añadir; uno que aparece sin
    fundamento enseña a ignorarlos.
    """

    def test_sin_el_argumento_no_se_marca_ni_se_inventan_modulos(self) -> None:
        from server.app.routers.hub_users_router import _a_lectura

        lectura = _a_lectura(_persona(), quien=_QUIEN_PREGUNTA)

        assert lectura.modulos_concedidos == []
        assert lectura.sin_concesion_directa is False


class TestDarDeAltaConcedeEnElMismoActo:
    """Lo que evita el segundo viaje, que es la causa de que la tabla estuviera vacía.

    El contrato: `UsuarioCreate` admite `modulos`, y `extra="forbid"` hace que enviarlos sin
    que el campo exista sea un 422 y no un campo que se traga y se pierde — que sería la peor
    versión de este defecto, porque la pantalla parecería funcionar.
    """

    def test_el_contrato_de_alta_admite_modulos(self) -> None:
        from server.app.routers.hub_users_router import UsuarioCreate

        alta = UsuarioCreate(email="nueva@uji.es", modulos=["informes", "chatbots"])

        assert alta.modulos == ["informes", "chatbots"]

    def test_sin_modulos_el_alta_sigue_siendo_valida(self) -> None:
        """No se rompe a quien ya llamaba, ni se obliga a conceder para crear."""
        from server.app.routers.hub_users_router import UsuarioCreate

        assert UsuarioCreate(email="nueva@uji.es").modulos == []

    def test_un_modulo_repetido_no_se_concede_dos_veces(self) -> None:
        """`conceder` da 409 con el duplicado, así que el alta reventaría a medias."""
        from server.app.routers.hub_users_router import UsuarioCreate

        alta = UsuarioCreate(email="nueva@uji.es", modulos=["informes", "informes"])

        assert alta.modulos == ["informes"]

    def test_un_codigo_vacio_no_pasa(self) -> None:
        from server.app.routers.hub_users_router import UsuarioCreate

        with pytest.raises(ValueError):
            UsuarioCreate(email="nueva@uji.es", modulos=["informes", "  "])


class TestElListadoLosResuelveDeUnaVez:
    """Y no una consulta por persona, que es como un listado de treinta se vuelve lento."""

    @pytest.mark.asyncio
    async def test_las_concesiones_se_leen_en_una_sola_consulta(self) -> None:
        from server.app.routers.hub_users_router import _concesiones_por_sujeto

        vistas: list[object] = []

        class _SesionQueCuenta:
            async def execute(self, consulta):
                vistas.append(consulta)

                class _R:
                    @staticmethod
                    def all():
                        return []

                return _R()

        await _concesiones_por_sujeto(
            _SesionQueCuenta(), [uuid.uuid4() for _ in range(5)]
        )

        assert len(vistas) == 1, (
            f"cinco personas han producido {len(vistas)} consultas: es N+1, y el listado de "
            "personas se abre en cada sesión"
        )

    @pytest.mark.asyncio
    async def test_sin_personas_no_consulta_nada(self) -> None:
        """Una lista vacía no tiene que ir a la base: `IN ()` es un error en algunos motores."""
        from server.app.routers.hub_users_router import _concesiones_por_sujeto

        class _SesionQueFalla:
            async def execute(self, consulta):  # pragma: no cover - no debe llamarse
                raise AssertionError("ha consultado con la lista vacía")

        assert await _concesiones_por_sujeto(_SesionQueFalla(), []) == {}
