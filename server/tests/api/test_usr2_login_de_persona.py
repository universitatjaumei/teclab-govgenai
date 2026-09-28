"""USR.2 — `POST /auth/user/login`: una persona entra con su contraseña y su rol.

**Este prompt existe separado del USR.1 porque aquí está el riesgo.** El login de Admin nació
comprobando sólo que el correo existiera (SEC.1, hallazgo A1) y el de superadmin tuvo que
aprender por separado el hash señuelo y el límite de intentos. Un tercer login escrito de memoria
repite esa curva, así que estos tests son la lista de sus tres defensas:

1. **`limitar_login` lo primero**, antes de mirar la cuenta (SEC.4): comprobar la contraseña de
   una cuenta que ya gastó su cupo es hacerle el trabajo a quien prueba diccionarios.
2. **`verify_password` siempre**, contra el hash guardado o contra el señuelo: sin eso, una
   cuenta inexistente responde sin pagar bcrypt y el cronómetro delata qué correos existen.
3. **El mismo 401 en los cuatro casos** —no existe, sin hash, inactiva, contraseña mala—.
   Distinguirlos convierte el formulario en un oráculo para enumerar personas.

Y una cuarta cosa que no es defensa sino frontera: **una persona no es un administrador**. El
JWT lleva su rol real y su organización, con los grupos de SAML vacíos como el resto de logins
locales, así que no pasa los guardas de superadmin ni de admin. Es el fallo que convertiría a un
probador del piloto en administrador de la plataforma, y por eso tiene un test por cada guarda.
"""
from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from server.app.api.deps import get_session
from server.app.core.security import hash_password
from server.app.main import app

PASSWORD = "C0ntrasenya-de-persona!"
CORREO = "probador@uji.es"
ORG = str(uuid.uuid4())


def _persona(
    *,
    con_password: bool = True,
    activo: bool = True,
    role: str = "user",
    organizacion_id: str | None = ORG,
    pendiente: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        email=CORREO,
        display_name="Probador del piloto",
        role=role,
        organizacion_id=uuid.UUID(organizacion_id) if organizacion_id else None,
        is_active=activo,
        hashed_password=hash_password(PASSWORD) if con_password else None,
        origen="manual",
        last_login_at=None,
        # Issue #94 — la fila real lo tiene siempre, así que el doble también. Sin el campo,
        # el login responde 500 y el motivo no aparece por ninguna parte.
        debe_cambiar_contrasena=pendiente,
    )


def _sesion(persona=None):
    """Sesión falsa: el login lee con `.first()` sobre `HubUser`."""
    session = MagicMock()

    resultado = MagicMock()
    resultado.first = MagicMock(return_value=persona)
    resultado.scalar_one_or_none = MagicMock(return_value=persona)
    resultado.scalars.return_value.all.return_value = []
    resultado.scalars.return_value.first.return_value = persona

    async def _exec(stmt, *args, **kwargs):
        return resultado

    session.exec = AsyncMock(side_effect=_exec)
    session.execute = AsyncMock(side_effect=_exec)
    session.get = AsyncMock(return_value=None)
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return session


def _override(session):
    async def _dep():
        yield session

    return _dep


@pytest.fixture(autouse=True)
def _sin_cupo_gastado():
    """El limitador es del proceso y el cupo del login son 10 por minuto y por IP.

    Este fichero hace más de veinte entradas desde la misma IP, así que sin reiniciar el
    limitador los tests a partir del décimo reciben **429** y el rojo parece de la lógica que
    se está probando. Es el mismo aviso que ya está escrito para comprobar cuentas a mano: más
    de cuatro seguidas dan 429 y no 401.
    """
    from server.app.core.rate_limit import limitador

    limitador.reiniciar()
    yield
    limitador.reiniciar()


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


def _login(client, session, password: str | None = PASSWORD, correo: str = CORREO):
    cuerpo: dict = {"email": correo}
    if password is not None:
        cuerpo["password"] = password
    app.dependency_overrides[get_session] = _override(session)
    try:
        return client.post("/api/v1/auth/user/login", json=cuerpo)
    finally:
        app.dependency_overrides.pop(get_session, None)


def _sesion_del_token(token: str):
    """El `UserInfo` que sale del JWT.

    `decode_token` devuelve el objeto y no el diccionario de claims: dentro del token se
    llaman `orgs` y `groups`, y el objeto los expone como `organizacion_ids` y `saml_groups`.
    """
    from server.app.core.auth import decode_token

    return decode_token(token)


class TestEntraQuienDebe:

    def test_should_let_a_person_in_with_their_own_role(self, client):
        r = _login(client, _sesion(_persona()))

        assert r.status_code == 200, r.text
        sesion = _sesion_del_token(r.json()["access_token"])
        assert sesion.role == "user", f"el JWT lleva {sesion.role!r}"
        assert sesion.role != "admin", "un probador no es un administrador"

    def test_should_carry_their_organization_and_no_saml_groups(self, client):
        r = _login(client, _sesion(_persona()))

        sesion = _sesion_del_token(r.json()["access_token"])
        assert sesion.organizacion_ids == (ORG,)
        assert not sesion.saml_groups, (
            "los grupos se leen de la aserción, así que en un login local van vacíos"
        )

    def test_should_keep_the_informer_role_too(self, client):
        """El rol se copia de la fila, no se decide aquí."""
        r = _login(client, _sesion(_persona(role="informer")))

        assert _sesion_del_token(r.json()["access_token"]).role == "informer"

    def test_should_record_the_login(self, client):
        """`last_login_at` existe desde AUTH.2 y hasta ahora sólo la escribía el ACS."""
        sesion = _sesion(_persona())
        _login(client, sesion)

        assert sesion.commit.await_count >= 1, "no se ha guardado la entrada"


class TestElMismo401:

    def test_should_reject_a_person_that_does_not_exist(self, client):
        r = _login(client, _sesion(None))

        assert r.status_code == 401
        assert "access_token" not in r.text

    def test_should_reject_a_person_without_hash(self, client):
        """El caso que reabriría el hallazgo A1: NULL no es «pasa sin comprobar»."""
        r = _login(client, _sesion(_persona(con_password=False)))

        assert r.status_code == 401
        assert "access_token" not in r.text

    def test_should_reject_an_inactive_person(self, client):
        """401 y no 403: un 403 diría que el correo existe."""
        r = _login(client, _sesion(_persona(activo=False)))

        assert r.status_code == 401

    def test_should_reject_a_wrong_password(self, client):
        r = _login(client, _sesion(_persona()), password="la-que-no-es")

        assert r.status_code == 401

    def test_should_answer_exactly_the_same_in_the_four_cases(self, client):
        respuestas = [
            _login(client, _sesion(None)),
            _login(client, _sesion(_persona(con_password=False))),
            _login(client, _sesion(_persona(activo=False))),
            _login(client, _sesion(_persona()), password="la-que-no-es"),
        ]

        assert {r.status_code for r in respuestas} == {401}
        cuerpos = {r.text for r in respuestas}
        assert len(cuerpos) == 1, f"el 401 distingue casos: {cuerpos}"


class TestLasTresDefensas:

    def test_should_hash_even_when_the_person_does_not_exist(self, monkeypatch, client):
        """Con espía y no con cronómetro, que el cronómetro es flaky.

        Sin el hash señuelo, el caso «no existe» responde sin pagar bcrypt y la diferencia de
        tiempo delata qué correos son de personas dadas de alta.
        """
        import server.app.routers.auth_router as modulo

        llamadas: list[tuple] = []
        real = modulo.verify_password

        def _espia(plano, hash_):
            llamadas.append((plano, hash_))
            return real(plano, hash_)

        monkeypatch.setattr(modulo, "verify_password", _espia)

        _login(client, _sesion(None))
        sin_cuenta = len(llamadas)
        _login(client, _sesion(_persona()), password="la-que-no-es")
        con_cuenta = len(llamadas) - sin_cuenta

        assert sin_cuenta == 1, "no se ha comparado contra el hash señuelo"
        assert con_cuenta == 1

    def test_should_rate_limit_before_looking_at_the_account(self, monkeypatch, client):
        """`limitar_login` lo PRIMERO (SEC.4): si va después, ya se ha pagado la consulta."""
        import server.app.routers.auth_router as modulo

        orden: list[str] = []
        monkeypatch.setattr(modulo, "limitar_login", lambda request: orden.append("limite"))

        sesion = _sesion(_persona())
        original = sesion.exec.side_effect

        async def _exec(stmt, *args, **kwargs):
            orden.append("consulta")
            return await original(stmt, *args, **kwargs)

        sesion.exec = AsyncMock(side_effect=_exec)
        sesion.execute = AsyncMock(side_effect=_exec)

        _login(client, sesion)

        assert orden and orden[0] == "limite", f"orden real: {orden}"


class TestLaContrasenaQuePusoOtro:
    """Issue #94 — entrar con ella se puede; hacer cualquier otra cosa, no."""

    def test_should_say_so_in_the_response(self, client):
        """El panel lo lee de aquí: no lo deduce de nada."""
        r = _login(client, _sesion(_persona(pendiente=True)))

        assert r.status_code == 200, r.text
        assert r.json()["cambio_pendiente"] is True

    def test_should_carry_it_inside_the_token(self, client):
        """Y va dentro del token, que es lo que el servidor mira en cada petición."""
        r = _login(client, _sesion(_persona(pendiente=True)))

        assert _sesion_del_token(r.json()["access_token"]).cambio_pendiente is True

    def test_should_leave_an_ordinary_login_alone(self, client):
        """Sin esto, lo de arriba se cumpliría marcando a todo el mundo."""
        r = _login(client, _sesion(_persona()))

        assert r.json()["cambio_pendiente"] is False
        assert _sesion_del_token(r.json()["access_token"]).cambio_pendiente is False


class TestElInterruptor:

    def test_should_answer_404_when_local_login_is_disabled(self, monkeypatch, client):
        """Provisional por definición: sin interruptor, «hasta que llegue el SSO» es «siempre»."""
        monkeypatch.setenv("LOCAL_USER_LOGIN_ENABLED", "false")

        r = _login(client, _sesion(_persona()))

        assert r.status_code == 404, r.text
        assert "access_token" not in r.text

    def test_should_be_enabled_by_default(self, monkeypatch, client):
        monkeypatch.delenv("LOCAL_USER_LOGIN_ENABLED", raising=False)

        r = _login(client, _sesion(_persona()))

        assert r.status_code == 200, r.text


class TestUnaPersonaNoEsUnAdministrador:
    """Los dos guardas, uno por test: es el fallo que ascendería a un probador."""

    def _actor(self, sesion):
        from server.app.core.auth.delegated_actor import EffectiveActor

        return EffectiveActor(
            subject_id=sesion.user_id,
            email=sesion.email,
            role=sesion.role,
            organizacion_ids=sesion.organizacion_ids,
            saml_groups=sesion.saml_groups,
            delegated=False,
        )

    def test_should_not_pass_the_superadmin_gate(self, client):
        from fastapi import HTTPException

        from server.app.api.deps import require_role
        from server.app.core.auth.models import UserRole

        sesion = _sesion_del_token(
            _login(client, _sesion(_persona())).json()["access_token"]
        )
        guarda = require_role(UserRole.SUPERADMIN.value)

        with pytest.raises(HTTPException) as exc:
            asyncio.run(guarda(sesion))
        assert exc.value.status_code == 403

    def test_should_not_pass_the_admin_gate(self, client):
        from fastapi import HTTPException

        from server.app.api.deps import require_role
        from server.app.core.auth.models import UserRole

        sesion = _sesion_del_token(
            _login(client, _sesion(_persona())).json()["access_token"]
        )
        guarda = require_role(UserRole.SUPERADMIN.value, UserRole.ADMIN.value)

        with pytest.raises(HTTPException) as exc:
            asyncio.run(guarda(sesion))
        assert exc.value.status_code == 403

    def test_should_open_no_organization_chatbot_without_an_organization(self, client):
        """Se comprueba llamando a `assert_chatbot_access`, no razonando sobre el claim.

        Una persona sin organización entra —puede tener sentido: alguien recién dado de alta a
        quien todavía no se le ha asignado— pero con la lista vacía no abre ningún chatbot de
        organización, que es lo que dice `puede_acceder` de un no-superadmin.
        """
        from fastapi import HTTPException

        from server.app.core.auth.chatbot_access import assert_chatbot_access

        r = _login(client, _sesion(_persona(organizacion_id=None)))
        assert r.status_code == 200, r.text

        sesion = _sesion_del_token(r.json()["access_token"])
        assert not sesion.organizacion_ids

        chatbot = SimpleNamespace(
            access_mode="authenticated",
            organizacion_id=uuid.UUID(ORG),
            allowed_roles=(),
            allowed_saml_groups=(),
        )
        with pytest.raises(HTTPException) as exc:
            assert_chatbot_access(self._actor(sesion), chatbot, via="session")
        assert exc.value.status_code == 403
