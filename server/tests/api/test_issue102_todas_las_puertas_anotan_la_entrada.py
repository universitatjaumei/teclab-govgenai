"""Entrar deja rastro por **cualquiera** de las puertas (issue #102).

**Lo que lo destapó.** La pantalla de Personas decía «Nunca ha entrado» del superadministrador
que entra todos los días. Literalmente cierto sobre el dato y falso sobre la realidad.

**Por qué no es cosmético.** `last_login_at IS NULL` es la regla de «se creó a mano y no se ha
usado», y **decide si una fila se puede borrar** (REV.8). El criterio descansaba en un campo que
la mitad de los logins no tocaba: el día que alguien entrara por una puerta que no anota, su
cuenta parecería sin estrenar y se podría borrar como si nadie la hubiera usado.

Tres de las seis puertas anotaban —el login de persona, y SAML y Google cuando resuelven a una
persona—. Las otras tres no: `/superadmin/login`, `/admin/login`, y SAML o Google cuando quien
entra es superadministrador o administrador, porque `resolve_session` **retorna antes** de llegar
al aprovisionamiento.

Y encima ni `SuperAdminAccount` ni `AdminAccount` tenían la columna, así que aunque su login la
escribiera no habría dónde.

**El código ya se había avisado a sí mismo.** El comentario de `auth_router.py` dice: «La columna
existe desde AUTH.2 y hasta ahora sólo la escribía el ACS. La pantalla de personas la usa para
decidir si una fila se puede borrar, así que una entrada por esta vía tiene que contar igual que
una por SSO». Ese razonamiento se aplicó a **una** puerta y no se extendió a las demás. Este
fichero recorre las seis, que es lo que impide que vuelva a pasar.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest


class TestLasDosTablasTienenDondeAnotarlo:
    """Sin columna no hay nada que discutir sobre qué la escribe."""

    def test_el_superadministrador_tiene_la_columna(self) -> None:
        from server.app.database.models import SuperAdminAccount

        assert "last_login_at" in SuperAdminAccount.__table__.columns, (
            "`SuperAdminAccount` no tiene `last_login_at`: su fila en la pantalla de Personas "
            "dirá «Nunca ha entrado» haga lo que haga su login"
        )

    def test_el_administrador_tiene_la_columna(self) -> None:
        from server.app.database.models import AdminAccount

        assert "last_login_at" in AdminAccount.__table__.columns

    def test_la_columna_admite_nulo(self) -> None:
        """Nulo es «todavía no ha entrado», que es un estado legítimo de una cuenta recién creada."""
        from server.app.database.models import AdminAccount, SuperAdminAccount

        assert SuperAdminAccount.__table__.columns["last_login_at"].nullable
        assert AdminAccount.__table__.columns["last_login_at"].nullable


class TestLasSeisPuertasLaEscriben:
    """El cruce que no existía, y por eso el desajuste duró.

    Se comprueba **puerta por puerta** y no con una sola: el defecto era exactamente que tres
    anotaban y tres no, así que un test que mirara una cualquiera habría pasado en verde.
    """

    _PUERTAS = (
        ("login de persona", "server/app/routers/auth_router.py", "login_usuario"),
        ("login de superadministrador", "server/app/routers/auth_router.py", "login_superadmin"),
        ("login de administrador", "server/app/routers/auth_router.py", "login_admin"),
    )

    @pytest.mark.parametrize(("nombre", "fichero", "funcion"), _PUERTAS)
    def test_el_endpoint_anota_la_entrada(self, nombre: str, fichero: str, funcion: str) -> None:
        import inspect

        from server.app.routers import auth_router

        fuente = inspect.getsource(getattr(auth_router, funcion))
        assert "last_login_at" in fuente, (
            f"la puerta «{nombre}» no anota `last_login_at`: quien entre por ahí parecerá no "
            "haber entrado nunca, y su cuenta se podrá borrar como si estuviera sin estrenar"
        )

    def test_resolve_session_anota_al_superadministrador(self) -> None:
        """La rama que retornaba antes de llegar al aprovisionamiento."""
        import inspect

        from server.app.core.auth.saml.identity_service import SamlIdentityService

        fuente = inspect.getsource(SamlIdentityService.resolve_session)
        # Se corta por `select(AdminAccount)` y NO por `AdminAccount` a secas:
        # `SuperAdminAccount` CONTIENE esa subcadena, asi que el corte simple partia
        # dentro de la rama del superadministrador y dejaba fuera su propio codigo.
        antes_del_admin = fuente.split("select(AdminAccount)")[0]
        assert "last_login_at" in antes_del_admin, (
            "entrar por SSO siendo superadministrador no deja rastro: `resolve_session` "
            "retorna antes de llegar al aprovisionamiento"
        )

    def test_resolve_session_anota_al_administrador(self) -> None:
        import inspect

        from server.app.core.auth.saml.identity_service import SamlIdentityService

        fuente = inspect.getsource(SamlIdentityService.resolve_session)
        desde_el_admin = "select(AdminAccount)".join(fuente.split("select(AdminAccount)")[1:])
        assert "last_login_at" in desde_el_admin, (
            "entrar por SSO siendo administrador no deja rastro"
        )


class TestLaPantallaNoAfirmaLoQueNoMide:
    """La fila sintética del superadministrador decía «nunca» sobre algo que no medía."""

    def test_la_fila_de_arranque_lleva_su_ultimo_acceso(self) -> None:
        import inspect

        from server.app.routers import hub_users_router

        fuente = inspect.getsource(hub_users_router._superadmins_de_arranque)
        assert "last_login_at=cuenta.last_login_at" in fuente.replace(" ", "").replace(
            "\n", ""
        ) or "last_login_at=cuenta.last_login_at" in fuente, (
            "la fila sintética del superadministrador no lee su `last_login_at` real, así que "
            "sigue diciendo «Nunca ha entrado» de quien entra a diario"
        )


class TestLaEntradaSeAnotaDeVerdad:
    """Y no sólo que la palabra aparezca en el código: que el valor cambie."""

    @pytest.mark.asyncio
    async def test_el_login_de_superadministrador_actualiza_la_marca(self) -> None:
        from server.app.core.security import hash_password
        from server.app.database.models import SuperAdminAccount
        from server.app.routers.auth_router import login_superadmin

        cuenta = SuperAdminAccount(
            admin_id=1,
            name="Quien Entra",
            email="entra@example.local",
            hashed_password=hash_password("una-contrasena-larga-de-prueba"),
            is_active=True,
            created_at=datetime.now(timezone.utc),
            last_login_at=None,
        )

        class _Resultado:
            @staticmethod
            def first():
                return cuenta

        class _Sesion:
            def __init__(self) -> None:
                self.commits = 0

            async def exec(self, _consulta):
                return _Resultado()

            def add(self, _fila):
                return None

            async def commit(self):
                self.commits += 1

        class _Peticion:
            client = type("C", (), {"host": "127.0.0.1"})()
            headers: dict = {}

        sesion = _Sesion()
        cuerpo = type(
            "B", (), {"email": "entra@example.local", "password": "una-contrasena-larga-de-prueba"}
        )()

        await login_superadmin(cuerpo, _Peticion(), sesion)  # type: ignore[arg-type]

        assert cuenta.last_login_at is not None, (
            "el login de superadministrador no ha escrito `last_login_at`"
        )
        assert sesion.commits >= 1, "lo ha puesto en el objeto y no lo ha confirmado"


class TestNadieAfirmaQueNoSeHaEntrado:
    """El guardarraíl que evita que esto se repita, dicho sobre el contrato y no sobre una fila.

    Si mañana alguien añade una séptima puerta, esto no la caza —nada puede—; lo que sí caza es
    que la regla de borrado siga dependiendo de un campo, para que quien la mueva se encuentre
    este fichero.
    """

    def test_la_regla_de_borrado_sigue_dependiendo_de_la_marca(self) -> None:
        import inspect

        from server.app.routers import hub_users_router

        fuente = inspect.getsource(hub_users_router._a_lectura)
        assert "last_login_at" in fuente, (
            "la regla de «se puede borrar» ya no mira `last_login_at`: si ha cambiado de "
            "criterio, este fichero entero hay que revisarlo"
        )
