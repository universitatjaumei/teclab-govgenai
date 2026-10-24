"""Sembrar el catálogo no exige credenciales, y crear un segundo superadministrador no es silencioso.

**Lo que pasó (issue #97).** `bootstrap.main()` salía con código 2 sin `--superadmin-email` y
`--superadmin-password`, que por omisión vienen de `SUPERADMIN_EMAIL` / `SUPERADMIN_PASSWORD`. En
el contenedor de producción **ninguna de las dos existe**, así que `bootstrap --con-demo` no podía
ejecutarse sin que una persona aportara credenciales a mano por SSH — y ahí se quedó parada la
siembra. Producción llevaba desde el principio con **cero plantillas**.

Y no las necesita: las plantillas se firman con `AUTOR_DEL_SEMBRADO`, un UUID5 fijo derivado de un
nombre, **no con la cuenta del superadministrador**. Las pedía porque el trabajo principal de
`bootstrap` es crear esa cuenta: dos trabajos distintos compartiendo una puerta de credenciales.

Con `--solo-demo` la puerta desaparece, y sembrar el catálogo pasa a poder ser **un paso del
despliegue**, idempotente y sin que nadie entre por SSH.

**Y el riesgo que se endurece de paso.** `bootstrap` busca al superadministrador por correo: si no
existe, **lo crea**. O sea que **una errata en el correo crea un segundo superadministrador en
silencio**, con la contraseña que tecleó quien se equivocó. Con un solo superadministrador en la
instalación, el segundo pasaría desapercibido hasta que alguien mirase la tabla.

La instalación nueva no se toca —ahí no hay ninguno y crear el primero es el trabajo—; lo que se
niega es crear **otro** cuando ya hay alguno, salvo que se pida explícitamente. Es la misma
distinción que pide #96 para su guion de emergencia, en el sentido contrario.
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

SUPERADMIN_EMAIL = "arranque@example.local"
SUPERADMIN_PASSWORD = "una-contrasena-de-prueba-larga"
_CON_CLAVE = {"SUPERADMIN_PASSWORD": SUPERADMIN_PASSWORD}


def _sync_url() -> str:
    url = os.environ.get("DATABASE_URL_SYNC") or os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("sin DATABASE_URL")
    return url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")


@pytest.fixture
def base_desechable():
    """Una base con nombre único y las migraciones aplicadas.

    Con nombre único **a propósito**: la regla del proyecto es que nada destructivo toque la base
    de desarrollo, y este fichero crea y borra la suya.
    """
    sync_url = _sync_url()
    partes = urlsplit(sync_url.replace("postgresql+psycopg2", "postgresql"))
    dsn_admin = urlunsplit(partes._replace(path="/postgres"))

    try:
        conexion_admin = psycopg2.connect(dsn_admin)
    except Exception:  # pragma: no cover - entorno sin BD
        pytest.skip("BD Postgres no disponible")

    conexion_admin.autocommit = True
    nombre = f"test_issue97_{uuid.uuid4().hex[:12]}"
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
    )
    assert migrar.returncode == 0, f"migraciones fallaron:\n{migrar.stderr}"

    yield plano, plano.replace("postgresql://", "postgresql+asyncpg://")

    with conexion_admin.cursor() as cur:
        cur.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()",
            (nombre,),
        )
        cur.execute(f'DROP DATABASE IF EXISTS "{nombre}"')
    conexion_admin.close()


def _bootstrap(async_url: str, *argumentos: str, entorno_extra: dict | None = None):
    """Lanza el guion **sin** pasarle credenciales salvo que el test las ponga."""
    entorno = {**os.environ, "DATABASE_URL": async_url}
    # Que el entorno de la máquina no cuele las credenciales por la puerta de atrás: lo que se
    # está probando es justo que no hagan falta.
    entorno.pop("SUPERADMIN_EMAIL", None)
    entorno.pop("SUPERADMIN_PASSWORD", None)
    entorno.update(entorno_extra or {})
    return subprocess.run(
        [sys.executable, "-m", "server.app.scripts.bootstrap", *argumentos],
        cwd=_SERVER_ROOT.parent,
        env=entorno,
        # #270: sin entorno, el guion lee la contraseña de aquí; cerrado, no espera a nadie.
        stdin=subprocess.DEVNULL,
        capture_output=True, text=True, timeout=180,
    )


def _cuenta(dsn: str, sql: str):
    with psycopg2.connect(dsn) as conexion, conexion.cursor() as cur:
        cur.execute(sql)
        return cur.fetchone()[0]


class TestSembrarElCatalogoNoPideCredenciales:
    def test_solo_demo_siembra_sin_correo_ni_contrasena(self, base_desechable) -> None:
        """El caso que no se podía ejecutar en producción."""
        dsn, async_url = base_desechable

        resultado = _bootstrap(async_url, "--solo-demo")

        assert resultado.returncode == 0, (
            f"`--solo-demo` sigue exigiendo credenciales:\n{resultado.stdout}\n{resultado.stderr}"
        )
        assert _cuenta(dsn, "SELECT count(*) FROM hub_report_templates") > 0, (
            "no ha sembrado ninguna plantilla"
        )

    def test_solo_demo_no_crea_ningun_superadministrador(self, base_desechable) -> None:
        """Sembrar un catálogo no es instalar: no debe tocar las cuentas."""
        dsn, async_url = base_desechable

        _bootstrap(async_url, "--solo-demo")

        assert _cuenta(dsn, "SELECT count(*) FROM superadminaccount") == 0

    def test_solo_demo_es_idempotente(self, base_desechable) -> None:
        """Va a ser un paso del despliegue, así que corre en cada uno."""
        dsn, async_url = base_desechable

        _bootstrap(async_url, "--solo-demo")
        antes = _cuenta(dsn, "SELECT count(*) FROM hub_report_templates")
        segunda = _bootstrap(async_url, "--solo-demo")

        assert segunda.returncode == 0
        assert _cuenta(dsn, "SELECT count(*) FROM hub_report_templates") == antes

    def test_sin_solo_demo_las_credenciales_siguen_haciendo_falta(self, base_desechable) -> None:
        """No se afloja la instalación: crear la cuenta sigue exigiendo con qué."""
        _, async_url = base_desechable

        resultado = _bootstrap(async_url)

        assert resultado.returncode == 2, (
            "el arranque completo ha dejado de pedir credenciales, y ésas sí las necesita"
        )


class TestUnSegundoSuperadministradorNoEsSilencioso:
    def test_la_primera_instalacion_crea_el_suyo(self, base_desechable) -> None:
        """El camino bueno, que un endurecimiento mal hecho rompería."""
        dsn, async_url = base_desechable

        resultado = _bootstrap(
            async_url,
            "--superadmin-email", SUPERADMIN_EMAIL,
            entorno_extra=_CON_CLAVE,
        )

        assert resultado.returncode == 0, resultado.stderr
        assert _cuenta(dsn, "SELECT count(*) FROM superadminaccount") == 1

    def test_una_errata_en_el_correo_no_crea_un_segundo(self, base_desechable) -> None:
        """**El agujero.** Antes creaba una cuenta nueva con la contraseña que se tecleara."""
        dsn, async_url = base_desechable
        _bootstrap(
            async_url,
            "--superadmin-email", SUPERADMIN_EMAIL,
            entorno_extra=_CON_CLAVE,
        )

        resultado = _bootstrap(
            async_url,
            "--superadmin-email", "arrranque@example.local",  # la errata
            entorno_extra=_CON_CLAVE,
        )

        assert _cuenta(dsn, "SELECT count(*) FROM superadminaccount") == 1, (
            "una errata en el correo ha creado un segundo superadministrador en silencio"
        )
        assert resultado.returncode != 0, "y además ha salido con éxito, así que nadie se entera"

    def test_se_puede_crear_otro_si_se_pide_explicitamente(self, base_desechable) -> None:
        """La decisión de tener dos es legítima; lo que no vale es tomarla sin querer."""
        dsn, async_url = base_desechable
        _bootstrap(
            async_url,
            "--superadmin-email", SUPERADMIN_EMAIL,
            entorno_extra=_CON_CLAVE,
        )

        resultado = _bootstrap(
            async_url,
            "--superadmin-email", "segundo@example.local",
            "--permitir-otro-superadmin",
            entorno_extra=_CON_CLAVE,
        )

        assert resultado.returncode == 0, resultado.stderr
        assert _cuenta(dsn, "SELECT count(*) FROM superadminaccount") == 2

    def test_reejecutar_con_el_mismo_correo_sigue_siendo_idempotente(
        self, base_desechable
    ) -> None:
        """`setup.sh` se reejecuta, y eso no puede empezar a fallar."""
        dsn, async_url = base_desechable
        credenciales = ("--superadmin-email", SUPERADMIN_EMAIL)
        _bootstrap(async_url, *credenciales, entorno_extra=_CON_CLAVE)

        segunda = _bootstrap(async_url, *credenciales, entorno_extra=_CON_CLAVE)

        assert segunda.returncode == 0, (
            f"reejecutar con el mismo correo ha fallado:\n{segunda.stdout}\n{segunda.stderr}"
        )
        assert _cuenta(dsn, "SELECT count(*) FROM superadminaccount") == 1
