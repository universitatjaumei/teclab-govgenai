"""Tests 11.1 — scripts/generate_env.sh (generador de configuración .env).

Invoca el script vía subprocess sobre un directorio temporal (--output-dir);
no toca el .env real del repo. No requiere Docker ni servicios levantados.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.parent.parent.parent
_SCRIPT = _ROOT / "scripts" / "generate_env.sh"

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _run(*args: str) -> subprocess.CompletedProcess:
    # 120 s y no 30: el script genera una clave RSA-2048 y, ejecutado junto al resto de la
    # suite, el subprocess de bash expiraba de forma intermitente —cada vez en un test
    # distinto— en Windows. Un fallo por tiempo que aparece según la carga de la máquina no
    # informa de nada y estropea cualquier comparación de la suite. Un cuelgue real sigue
    # fallando con este margen.
    return subprocess.run(
        ["bash", str(_SCRIPT), *args],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        values[key.strip()] = value.strip()
    return values


def test_should_create_env_files_when_none_exist(tmp_path: Path) -> None:
    result = _run("--output-dir", str(tmp_path))
    assert result.returncode == 0, result.stderr

    assert (tmp_path / ".env").exists()
    assert (tmp_path / "server" / ".env").exists()
    assert (tmp_path / "frontend" / ".env").exists()


def test_should_generate_unique_random_jwt_secret_each_run(tmp_path: Path) -> None:
    dir_a, dir_b = tmp_path / "a", tmp_path / "b"
    _run("--output-dir", str(dir_a))
    _run("--output-dir", str(dir_b))

    secret_a = _parse_env(dir_a / ".env")["JWT_SECRET_KEY"]
    secret_b = _parse_env(dir_b / ".env")["JWT_SECRET_KEY"]

    assert _HEX64.match(secret_a), secret_a
    assert _HEX64.match(secret_b), secret_b
    assert secret_a != secret_b


def test_should_not_overwrite_existing_env_without_force(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("SENTINEL=keep-me\n", encoding="utf-8")

    result = _run("--output-dir", str(tmp_path))
    assert result.returncode == 0, result.stderr

    content = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "SENTINEL=keep-me" in content
    assert "JWT_SECRET_KEY" not in content


def test_should_overwrite_existing_env_with_force(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("SENTINEL=keep-me\n", encoding="utf-8")

    result = _run("--output-dir", str(tmp_path), "--force")
    assert result.returncode == 0, result.stderr

    content = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "SENTINEL=keep-me" not in content
    assert "JWT_SECRET_KEY" in content


def test_should_default_to_local_mode_with_no_cost_storage(tmp_path: Path) -> None:
    _run("--output-dir", str(tmp_path))
    values = _parse_env(tmp_path / ".env")

    assert values["STORAGE_BACKEND"] in ("file", "s3")
    assert values.get("SAML_ENABLED") == "false"


def test_should_include_mcp_connectivity_section(tmp_path: Path) -> None:
    _run("--output-dir", str(tmp_path))
    content = (tmp_path / ".env").read_text(encoding="utf-8")

    assert "GOVGENAI_API_BASE_URL" in content
    assert "GOVGENAI_PAT" in content


def test_should_write_frontend_vite_api_url(tmp_path: Path) -> None:
    _run("--output-dir", str(tmp_path))
    values = _parse_env(tmp_path / "frontend" / ".env")

    assert values["VITE_API_URL"] == "http://localhost:8000"


def test_should_reject_unknown_mode(tmp_path: Path) -> None:
    result = _run("--output-dir", str(tmp_path), "--mode", "bogus")

    assert result.returncode != 0
    assert "bogus" in (result.stdout + result.stderr).lower() or "mode" in (result.stdout + result.stderr).lower()
    assert not (tmp_path / ".env").exists()


def test_should_generate_matching_root_and_server_env(tmp_path: Path) -> None:
    """server/.env debe ser copia del .env raíz (config.py lo lee desde ahí)."""
    _run("--output-dir", str(tmp_path))

    root_values = _parse_env(tmp_path / ".env")
    server_values = _parse_env(tmp_path / "server" / ".env")

    assert root_values["JWT_SECRET_KEY"] == server_values["JWT_SECRET_KEY"]
    assert root_values["DATABASE_URL"] == server_values["DATABASE_URL"]


_POSIX = pytest.mark.skipif(os.name != "posix", reason="los permisos de fichero sólo se ven en POSIX")


@_POSIX
def test_los_env_con_secretos_solo_los_lee_su_dueno(tmp_path: Path) -> None:
    """#270 — llevan la contraseña de Postgres, el secreto JWT y la clave privada RSA."""
    assert _run("--output-dir", str(tmp_path)).returncode == 0

    for env in (tmp_path / ".env", tmp_path / "server" / ".env"):
        assert env.stat().st_mode & 0o077 == 0, f"{env}: {oct(env.stat().st_mode)}"


@_POSIX
def test_regenerar_con_force_tambien_cierra_los_permisos(tmp_path: Path) -> None:
    """`umask` no toca un fichero que ya existe: un `.env` viejo con 644 seguiría legible."""
    (tmp_path / "server").mkdir()
    for env in (tmp_path / ".env", tmp_path / "server" / ".env"):
        env.write_text("VIEJO=1\n", encoding="utf-8")
        env.chmod(0o644)

    assert _run("--output-dir", str(tmp_path), "--force").returncode == 0

    for env in (tmp_path / ".env", tmp_path / "server" / ".env"):
        assert env.stat().st_mode & 0o077 == 0, f"{env}: {oct(env.stat().st_mode)}"
