"""El guion de emergencia para restablecer al superadministrador (issue #96).

**El hueco.** Si el superadministrador pierde su contraseña no hay camino de vuelta por producto:
`bootstrap` **no** rehashea —a propósito, para que reejecutar `setup.sh` no revierta un cambio
posterior—, `PATCH /admins/{id}/password` es sólo superadmin y por tanto no puede ayudarle a él
mismo, y la plataforma **no puede enviar correo**, así que no hay autoservicio posible. La única
salida era escribir un hash de bcrypt a mano en la base de producción.

Y no lo arregla el login con Google: el login local del superadministrador se conserva **como
reserva**, justo para poder entrar cuando Google o su configuración fallen. Es esa reserva la que
no tenía recuperación.

**Por qué es un guion y no un endpoint.** Su autorización no es un rol: es **tener acceso a la
máquina** —SSH por IAP, `sudo`, `docker`—. Añadir un rol no añadiría seguridad, porque quien puede
ejecutar `docker exec` ahí ya puede escribir en la base. Conviene decirlo porque alguien preguntará.

**Las tres reglas que lo separan de `bootstrap`**, y cada una tiene su test:

1. **Se niega a crear.** Es exactamente lo contrario que `bootstrap`, y la razón de que sea un
   guion aparte: si el correo no existe, error, nunca una cuenta nueva.
2. **La contraseña entra por entrada estándar, nunca por `argv`.** Un `--password` queda en el
   historial del *shell* y se ve en `ps` mientras corre.
3. **No la imprime**, ni ella ni su hash.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg2
import pytest

_SERVER_ROOT = Path(__file__).resolve().parents[2]

_CORREO = "superadmin@example.local"
_OTRO = "otro@example.local"
_VIEJA = "la-contrasena-vieja-y-larga"
_NUEVA = "la-contrasena-nueva-y-mas-larga"

_GUION = "server.app.scripts.restablecer_superadmin"


def _sync_url() -> str:
    url = os.environ.get("DATABASE_URL_SYNC") or os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("sin DATABASE_URL")
    return url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")


@pytest.fixture
def base_con_dos_superadmins():
    """Base desechable, migrada, con dos superadministradores.

    Dos y no uno: sin el segundo no se puede comprobar que el guion **no toca a los demás**, que
    es una de las cuatro cosas que promete.
    """
    from server.app.core.security import hash_password

    sync_url = _sync_url()
    partes = urlsplit(sync_url.replace("postgresql+psycopg2", "postgresql"))
    dsn_admin = urlunsplit(partes._replace(path="/postgres"))

    try:
        conexion_admin = psycopg2.connect(dsn_admin)
    except Exception:  # pragma: no cover - entorno sin BD
        pytest.skip("BD Postgres no disponible")

    conexion_admin.autocommit = True
    nombre = f"test_issue96_{uuid.uuid4().hex[:12]}"
    with conexion_admin.cursor() as cur:
        cur.execute(f'CREATE DATABASE "{nombre}"')

    sync_nueva = urlunsplit(urlsplit(sync_url)._replace(path=f"/{nombre}"))
    plano = sync_nueva.replace("postgresql+psycopg2", "postgresql")

    conexion = psycopg2.connect(plano)
    conexion.autocommit = True
    with conexion.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
    conexion.close()

    migrar = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=_SERVER_ROOT,
        env={**os.environ, "DATABASE_URL_SYNC": sync_nueva},
        capture_output=True, text=True, timeout=180,
        check=False,
    )
    assert migrar.returncode == 0, f"migraciones fallaron:\n{migrar.stderr}"

    with psycopg2.connect(plano) as c, c.cursor() as cur:
        for correo in (_CORREO, _OTRO):
            cur.execute(
                "INSERT INTO superadminaccount "
                "(name, email, hashed_password, is_active, created_at) "
                "VALUES (%s, %s, %s, true, now())",
                (f"Cuenta {correo}", correo, hash_password(_VIEJA)),
            )
        c.commit()

    yield plano, plano.replace("postgresql://", "postgresql+asyncpg://")

    with conexion_admin.cursor() as cur:
        cur.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()",
            (nombre,),
        )
        cur.execute(f'DROP DATABASE IF EXISTS "{nombre}"')
    conexion_admin.close()


def _restablecer(async_url: str, correo: str, nueva: str | None):
    """Lanza el guion pasándole la contraseña **por entrada estándar**."""
    return subprocess.run(
        [sys.executable, "-m", _GUION, "--email", correo],
        cwd=_SERVER_ROOT.parent,
        env={**os.environ, "DATABASE_URL": async_url},
        input=None if nueva is None else f"{nueva}\n{nueva}\n",
        capture_output=True, text=True, timeout=180,
        check=False,
    )


def _hash_de(dsn: str, correo: str) -> str:
    with psycopg2.connect(dsn) as conexion, conexion.cursor() as cur:
        cur.execute("SELECT hashed_password FROM superadminaccount WHERE email = %s", (correo,))
        fila = cur.fetchone()
        return fila[0] if fila else ""


def _cuantos(dsn: str) -> int:
    with psycopg2.connect(dsn) as conexion, conexion.cursor() as cur:
        cur.execute("SELECT count(*) FROM superadminaccount")
        return cur.fetchone()[0]


class TestRestableceAQuienExiste:
    def test_la_contrasena_nueva_sirve_para_entrar(self, base_con_dos_superadmins) -> None:
        """Lo que hace útil el guion, comprobado con el verificador de la aplicación.

        No basta con que el hash cambie: tiene que **validar** con la contraseña nueva. Un hash
        distinto pero inservible dejaría la cuenta igual de perdida y el guion pareciendo que
        funcionó.
        """
        from server.app.core.security import verify_password

        dsn, async_url = base_con_dos_superadmins

        resultado = _restablecer(async_url, _CORREO, _NUEVA)

        assert resultado.returncode == 0, f"{resultado.stdout}\n{resultado.stderr}"
        assert verify_password(_NUEVA, _hash_de(dsn, _CORREO))

    def test_la_contrasena_vieja_deja_de_servir(self, base_con_dos_superadmins) -> None:
        from server.app.core.security import verify_password

        dsn, async_url = base_con_dos_superadmins

        _restablecer(async_url, _CORREO, _NUEVA)

        assert not verify_password(_VIEJA, _hash_de(dsn, _CORREO))

    def test_no_toca_a_los_demas(self, base_con_dos_superadmins) -> None:
        """Con dos cuentas en la base: la otra queda exactamente como estaba."""
        dsn, async_url = base_con_dos_superadmins
        antes = _hash_de(dsn, _OTRO)

        _restablecer(async_url, _CORREO, _NUEVA)

        assert _hash_de(dsn, _OTRO) == antes
        assert _cuantos(dsn) == 2


class TestSeNiegaACrear:
    """Lo contrario que `bootstrap`, y la razón de que sea un guion aparte."""

    def test_un_correo_que_no_existe_es_un_error(self, base_con_dos_superadmins) -> None:
        _, async_url = base_con_dos_superadmins

        resultado = _restablecer(async_url, "no.existe@example.local", _NUEVA)

        assert resultado.returncode != 0, (
            "ha salido con éxito para un correo que no existe: quien se equivoque al teclear "
            "creerá que ha restablecido algo"
        )

    def test_y_no_crea_ninguna_cuenta(self, base_con_dos_superadmins) -> None:
        """El agujero que este guion **no** puede tener, y que `bootstrap` sí tenía."""
        dsn, async_url = base_con_dos_superadmins

        _restablecer(async_url, "no.existe@example.local", _NUEVA)

        assert _cuantos(dsn) == 2, "ha creado una cuenta nueva a partir de una errata"


class TestLaContrasenaNoViajaPorDondeSeVe:
    def test_no_hay_ninguna_opcion_para_pasarla_como_argumento(self) -> None:
        """Un `--password` queda en el historial del *shell* y se ve en `ps` mientras corre."""
        ayuda = subprocess.run(
            [sys.executable, "-m", _GUION, "--help"],
            cwd=_SERVER_ROOT.parent,
            capture_output=True, text=True, timeout=60,
            check=False,
        ).stdout

        for prohibida in ("--password", "--contrasena", "--contraseña"):
            assert prohibida not in ayuda, (
                f"el guion acepta {prohibida}: una contraseña en `argv` queda en el historial "
                "y es visible en `ps`"
            )

    def test_no_la_imprime_ni_a_ella_ni_a_su_hash(self, base_con_dos_superadmins) -> None:
        dsn, async_url = base_con_dos_superadmins

        resultado = _restablecer(async_url, _CORREO, _NUEVA)
        todo = resultado.stdout + resultado.stderr

        assert _NUEVA not in todo, "ha impreso la contraseña"
        assert _hash_de(dsn, _CORREO) not in todo, "ha impreso el hash"

    def test_dos_contrasenas_distintas_no_pasan(self, base_con_dos_superadmins) -> None:
        """Se teclea a ciegas, así que se pide dos veces y tienen que coincidir."""
        from server.app.core.security import verify_password

        dsn, async_url = base_con_dos_superadmins

        resultado = subprocess.run(
            [sys.executable, "-m", _GUION, "--email", _CORREO],
            cwd=_SERVER_ROOT.parent,
            env={**os.environ, "DATABASE_URL": async_url},
            input=f"{_NUEVA}\notra-cosa-completamente-distinta\n",
            capture_output=True, text=True, timeout=180,
            check=False,
        )

        assert resultado.returncode != 0
        assert verify_password(_VIEJA, _hash_de(dsn, _CORREO)), "la ha cambiado igualmente"


class TestDejaTraza:
    """Un uso de emergencia sin rastro es indistinguible de un acceso no autorizado.

    **Desviación documentada**: la issue pedía «el registro de actividad», y no hay ninguna tabla
    de auditoría en el esquema —`hub_actividad_ia` es para usos de IA **externos** y exige
    `organizacion_id`, así que no encaja—. La traza va al registro de la aplicación, que es lo
    que producción recoge con el *ops-agent*. Crear una tabla exigiría migración y excede esta
    issue; queda dicho aquí para que se decida a la vista.
    """

    def test_dice_a_quien_ha_restablecido_y_cuando(self, base_con_dos_superadmins) -> None:
        _, async_url = base_con_dos_superadmins

        resultado = _restablecer(async_url, _CORREO, _NUEVA)
        todo = resultado.stdout + resultado.stderr

        assert _CORREO in todo, "no dice a quién se le ha restablecido"
