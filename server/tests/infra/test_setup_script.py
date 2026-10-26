"""Tests 11.3 — scripts/setup.sh (instalación de primera vez).

Invocan el script vía subprocess. Ninguno levanta contenedores ni toca la base
de datos: la orquestación real se ejerce con `--dry-run`, que imprime el plan sin
ejecutarlo. El sembrado idempotente se prueba aparte, contra BD, en
test_bootstrap_seed.py.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.parent.parent.parent
_SCRIPT = _ROOT / "scripts" / "setup.sh"

# Ruta absoluta al intérprete, resuelta con el PATH real del proceso de tests.
# Los tests que simulan "docker no instalado" pasan un PATH vacío al hijo, y en
# POSIX es ese PATH —no el del padre— el que `exec` usa para localizar el
# ejecutable: con `["bash", ...]` el propio bash dejaba de encontrarse y el test
# moría con FileNotFoundError antes de ejercer nada del script.
_BASH = shutil.which("bash") or "bash"


def _run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [_BASH, str(_SCRIPT), *args],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, **(env or {})},
        check=False,
    )


# ---------------------------------------------------------------------------
# Interfaz
# ---------------------------------------------------------------------------

def test_should_print_help_and_exit_zero() -> None:
    result = _run("--help")
    assert result.returncode == 0, result.stderr
    for flag in ("--non-interactive", "--dry-run", "--skip-checks", "--skip-stack"):
        assert flag in result.stdout, f"--help debe documentar {flag}"


def test_should_reject_unknown_flag() -> None:
    result = _run("--flag-que-no-existe")
    assert result.returncode != 0
    assert "flag-que-no-existe" in (result.stderr + result.stdout)


# ---------------------------------------------------------------------------
# Paso 1 — verificación de requisitos
# ---------------------------------------------------------------------------

def test_should_check_docker_and_required_ports() -> None:
    result = _run("--dry-run")
    salida = result.stdout + result.stderr
    # El script comprueba Docker ANTES que los puertos y aborta si el demonio no responde, así
    # que con Docker Desktop parado esto daba rojo afirmando que «no comprueba el puerto 80» —
    # y sí lo comprueba: nunca llega. Un rojo que dice algo falso sobre el código es peor que
    # uno que no dice nada, porque se arregla el sitio equivocado.
    if "el demonio de Docker no responde" in salida:
        pytest.skip("el demonio de Docker no está en marcha: el script aborta antes de los puertos")
    for puerto in ("80", "443"):
        assert puerto in salida, f"debe comprobar el puerto {puerto}"
    # #269: el compose de producción no publica Postgres, así que exigir el 5432 libre
    # rechazaba máquinas que sí podían instalar.
    assert "5432" not in salida
    assert "docker" in salida.lower()


def test_should_fail_when_docker_is_missing(tmp_path: Path) -> None:
    """Con un PATH sin docker, el script debe abortar con un mensaje claro y no
    seguir adelante hasta las migraciones."""
    vacio = tmp_path / "bin"
    vacio.mkdir()
    result = _run("--dry-run", env={"PATH": str(vacio)})

    assert result.returncode != 0
    assert "docker" in (result.stdout + result.stderr).lower()


def test_should_skip_requirement_checks_with_flag(tmp_path: Path) -> None:
    vacio = tmp_path / "bin"
    vacio.mkdir()
    result = _run("--dry-run", "--skip-checks", env={"PATH": str(vacio)})
    assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------------------
# Pasos 2-4 — el plan cubre migraciones, superadmin y chatbot de ejemplo
# ---------------------------------------------------------------------------

def test_dry_run_plans_migrations_superadmin_and_example_chatbot() -> None:
    result = _run("--dry-run", "--skip-checks")
    salida = result.stdout

    assert "alembic" in salida.lower(), "el plan debe incluir las migraciones"
    assert "superadmin" in salida.lower(), "el plan debe incluir el SuperAdmin"
    assert "bootstrap" in salida.lower(), "el plan debe invocar el sembrado idempotente"


def test_dry_run_does_not_execute_anything() -> None:
    """`--dry-run` no debe arrancar contenedores ni aplicar migraciones."""
    result = _run("--dry-run", "--skip-checks")
    assert result.returncode == 0, result.stderr
    assert "DRY-RUN" in result.stdout


# ---------------------------------------------------------------------------
# Paso 3 — modo no interactivo (necesario para CI y para reinstalaciones)
# ---------------------------------------------------------------------------

def test_should_require_credentials_when_non_interactive() -> None:
    result = _run(
        "--non-interactive", "--dry-run", "--skip-checks",
        env={"SUPERADMIN_EMAIL": "", "SUPERADMIN_PASSWORD": ""},
    )
    assert result.returncode != 0
    assert "SUPERADMIN_EMAIL" in (result.stdout + result.stderr)


def test_should_accept_credentials_from_environment_when_non_interactive() -> None:
    result = _run(
        "--non-interactive", "--dry-run", "--skip-checks",
        env={
            "SUPERADMIN_EMAIL": "admin@uji.es",
            "SUPERADMIN_PASSWORD": "una-clave-larga",
        },
    )
    assert result.returncode == 0, result.stderr
    assert "admin@uji.es" in result.stdout
    assert "una-clave-larga" not in (result.stdout + result.stderr), \
        "la contraseña nunca debe aparecer en la salida"


# ---------------------------------------------------------------------------
# Paso 5 — resumen final
# ---------------------------------------------------------------------------

def test_should_show_access_urls_in_summary() -> None:
    result = _run("--dry-run", "--skip-checks")
    salida = result.stdout
    assert "http://localhost" in salida, "el resumen debe mostrar las URLs de acceso"
    assert "/hub" in salida, "debe indicar la URL del panel de administración"


# ---------------------------------------------------------------------------
# Portabilidad Linux + macOS (criterio de aceptación del prompt)
# ---------------------------------------------------------------------------

def test_should_not_use_bash4_only_features() -> None:
    """macOS trae bash 3.2 por licencia. Arrays asociativos, `mapfile`,
    `readarray` y las expansiones `${x,,}` / `${x^^}` son de bash 4+ y romperían
    la instalación en un Mac."""
    contenido = _SCRIPT.read_text(encoding="utf-8")
    prohibido = ("declare -A", "mapfile", "readarray", "${_,,}", ",,}", "^^}")
    encontrados = [p for p in prohibido if p in contenido]
    assert not encontrados, f"construcciones de bash 4+ en setup.sh: {encontrados}"


def test_should_declare_bash_shebang_and_strict_mode() -> None:
    contenido = _SCRIPT.read_text(encoding="utf-8")
    assert contenido.startswith("#!/usr/bin/env bash"), \
        "shebang portable (no /bin/bash: en macOS con Homebrew bash vive en otra ruta)"
    assert "set -euo pipefail" in contenido
