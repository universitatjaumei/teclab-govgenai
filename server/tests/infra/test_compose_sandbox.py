"""Tests SBX.4 — verifican el hardening del servicio script-sandbox en docker-compose.

Parsean los ficheros YAML y el Dockerfile; no levantan contenedores.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

# Raíz del monorepo (AI_agents_hub/)
_ROOT = Path(__file__).parent.parent.parent.parent


def _load_compose(filename: str) -> dict:
    path = _ROOT / filename
    assert path.exists(), f"No existe {path}"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 1. docker-compose.yml (dev) — el sandbox está definido con hardening mínimo
# ---------------------------------------------------------------------------

def test_compose_dev_defines_sandbox_service() -> None:
    """El compose dev incluye script-sandbox con cap_drop, read_only, security_opt, user y red."""
    compose = _load_compose("docker-compose.yml")
    services = compose.get("services", {})

    assert "script-sandbox" in services, "Falta el servicio script-sandbox en docker-compose.yml"
    svc = services["script-sandbox"]

    assert svc.get("read_only") is True, "read_only debe ser true"

    cap_drop = svc.get("cap_drop", [])
    assert "ALL" in cap_drop, "cap_drop debe incluir ALL"

    security_opt = svc.get("security_opt", [])
    assert any("no-new-privileges" in o for o in security_opt), \
        "security_opt debe incluir no-new-privileges:true"

    user = str(svc.get("user", ""))
    assert "65534" in user, "user debe ser 65534 (nobody)"

    networks = compose.get("networks", {})
    assert "sandbox-net" in networks, "Falta la red sandbox-net en docker-compose.yml"

    svc_networks = svc.get("networks", [])
    svc_networks_list = (
        list(svc_networks.keys()) if isinstance(svc_networks, dict) else list(svc_networks)
    )
    assert "sandbox-net" in svc_networks_list, \
        "script-sandbox debe estar conectado a sandbox-net"


# ---------------------------------------------------------------------------
# 2. docker-compose.prod.yml — el sandbox NO expone puertos
# ---------------------------------------------------------------------------

def test_compose_prod_sandbox_has_no_ports() -> None:
    """En producción el sandbox no tiene sección ports (no accesible desde el host)."""
    compose = _load_compose("docker-compose.prod.yml")
    services = compose.get("services", {})

    assert "script-sandbox" in services, "Falta script-sandbox en docker-compose.prod.yml"
    svc = services["script-sandbox"]

    assert not svc.get("ports"), \
        "script-sandbox NO debe exponer ports en producción"


# ---------------------------------------------------------------------------
# 3. docker-compose.prod.yml — sandbox-net es internal: true
# ---------------------------------------------------------------------------

def test_compose_prod_sandbox_net_is_internal() -> None:
    """En producción sandbox-net tiene internal: true (sin egress a internet)."""
    compose = _load_compose("docker-compose.prod.yml")
    networks = compose.get("networks", {})

    assert "sandbox-net" in networks, "Falta la red sandbox-net en docker-compose.prod.yml"
    net = networks["sandbox-net"] or {}
    assert net.get("internal") is True, "sandbox-net debe tener internal: true en producción"


# ---------------------------------------------------------------------------
# 4. docker-compose.prod.yml — app conectada a sandbox-net
# ---------------------------------------------------------------------------

def test_compose_prod_app_connected_to_sandbox_net() -> None:
    """El servicio app en prod está conectado a sandbox-net para hablar con el sandbox."""
    compose = _load_compose("docker-compose.prod.yml")
    services = compose.get("services", {})

    assert "app" in services, "Falta el servicio app en docker-compose.prod.yml"
    app_svc = services["app"]

    app_networks = app_svc.get("networks", [])
    app_networks_list = (
        list(app_networks.keys()) if isinstance(app_networks, dict) else list(app_networks)
    )
    assert "sandbox-net" in app_networks_list, \
        "El servicio app debe estar conectado a sandbox-net en producción"


# ---------------------------------------------------------------------------
# 5. Dockerfile del sandbox — corre como usuario no-root 65534
# ---------------------------------------------------------------------------

def test_sandbox_dockerfile_runs_as_non_root_user() -> None:
    """El Dockerfile del sandbox tiene USER 65534 para evitar escalada de privilegios."""
    dockerfile = _ROOT / "services" / "script_sandbox" / "Dockerfile"
    assert dockerfile.exists(), f"No existe {dockerfile}"

    content = dockerfile.read_text(encoding="utf-8")
    user_lines = [line.strip() for line in content.splitlines() if line.strip().startswith("USER")]

    assert user_lines, "El Dockerfile no tiene instrucción USER"
    assert any("65534" in line for line in user_lines), \
        f"USER debe ser 65534, encontrado: {user_lines}"


# ---------------------------------------------------------------------------
# 6. Dockerfile del sandbox — el CMD arranca uvicorn directo del venv, sin `uv run`
# ---------------------------------------------------------------------------

def test_sandbox_dockerfile_cmd_does_not_invoke_uv_run() -> None:
    """`uv run` re-resuelve/reconstruye el proyecto en cada arranque (necesita
    red para el build backend) y el sandbox corre sin red ni $HOME escribible
    (regresión 11.2: con `uv run` como CMD el contenedor nunca pasa el
    healthcheck). El venv ya está sincronizado en build-time; el CMD debe
    invocar uvicorn directamente desde él vía PATH."""
    dockerfile = _ROOT / "services" / "script_sandbox" / "Dockerfile"
    content = dockerfile.read_text(encoding="utf-8")

    cmd_lines = [line.strip() for line in content.splitlines() if line.strip().startswith("CMD")]
    assert cmd_lines, "El Dockerfile no tiene instrucción CMD"
    assert not any("uv run" in line for line in cmd_lines), \
        f"El CMD no debe usar 'uv run' en runtime: {cmd_lines}"
    assert "PATH=" in content, "El venv del sandbox debe estar en PATH para que uvicorn se resuelva directo"
    assert ".venv/bin" in content, "El venv del sandbox debe estar en PATH para que uvicorn se resuelva directo"


# ---------------------------------------------------------------------------
# 7. Ambos compose fijan SANDBOX_TMP_DIR al punto de montaje del tmpfs
# ---------------------------------------------------------------------------

def test_compose_files_set_sandbox_tmp_dir_env_var() -> None:
    """sandbox/main.py usa SANDBOX_TMP_DIR con fallback a tempfile.gettempdir(),
    que falla bajo read_only:true si no apunta al tmpfs montado (regresión
    11.2: sin esta variable el sandbox nunca arranca, en dev ni en prod)."""
    for filename in ("docker-compose.yml", "docker-compose.prod.yml"):
        compose = _load_compose(filename)
        svc = compose["services"]["script-sandbox"]
        env = svc.get("environment", {})
        assert env.get("SANDBOX_TMP_DIR") == "/tmp/sandbox", \
            f"{filename}: script-sandbox debe fijar SANDBOX_TMP_DIR=/tmp/sandbox"


# ---------------------------------------------------------------------------
# 8. sandbox/main.py no evalúa tempfile.gettempdir() si SANDBOX_TMP_DIR existe
# ---------------------------------------------------------------------------

def test_sandbox_main_does_not_call_gettempdir_when_env_var_set() -> None:
    """`os.environ.get(k, tempfile.gettempdir())` evalúa el default SIEMPRE,
    aunque la clave exista (no hay cortocircuito en argumentos de función).
    Regresión 11.2: con SANDBOX_TMP_DIR puesta, gettempdir() se llamaba igual
    y fallaba bajo el filesystem read_only del contenedor. Se comprueba
    importando el módulo con TMPDIR apuntando a una ruta inexistente (para
    que gettempdir() reviente si se invoca) y SANDBOX_TMP_DIR a una válida.

    Usa el venv propio del microservicio (dependencias distintas al server
    principal); si no está instalado localmente, se salta."""
    import subprocess

    sandbox_root = _ROOT / "services" / "script_sandbox"
    python = sandbox_root / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        python = sandbox_root / ".venv" / "bin" / "python"
    if not python.exists():
        pytest.skip("venv de services/script_sandbox no instalado localmente")

    script = (
        "import os; "
        "os.environ['TMPDIR'] = '/nonexistent/broken/tmp'; "
        "os.environ.setdefault('SANDBOX_TMP_DIR', '/tmp'); "
        "import sandbox.main"
    )
    result = subprocess.run(
        [str(python), "-c", script],
        cwd=sandbox_root,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, (
        "Importar sandbox.main con SANDBOX_TMP_DIR puesta no debe fallar "
        f"aunque TMPDIR sea inválida:\n{result.stderr}"
    )
