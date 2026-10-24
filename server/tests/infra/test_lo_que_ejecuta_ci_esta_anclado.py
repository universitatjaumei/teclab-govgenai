"""#268 — lo que CI y el despliegue ejecutan se ancla a una versión que no se mueve sola.

Una etiqueta de acción (`@v3`) la puede mover quien controla el repositorio de la acción, y
`google-github-actions/auth` corre con `id-token: write` y una cuenta de servicio que publica
imágenes y entra en la VM: una etiqueta movida ahí es la que más daño haría. Lo mismo vale para
`uv:latest` en la imagen y para las herramientas que CI lanza con `uvx` y `npx` sin versión.

Se ancla por SHA con la versión en un comentario, que es lo que Dependabot lee para seguir
proponiendo subidas. Y Dependabot tiene que vigilar las acciones, los Dockerfile y los compose.
"""
from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
FLUJOS = sorted((RAIZ / ".github" / "workflows").glob("*.yml"))
USES = re.compile(r"uses:\s*([^\s#]+)(\s*#\s*(\S+))?")


def _lineas_activas(fichero: Path) -> list[str]:
    return [
        linea for linea in fichero.read_text(encoding="utf-8").splitlines()
        if not linea.strip().startswith("#")
    ]


def test_hay_flujos_que_mirar() -> None:
    """Sanidad del medidor: sin flujos, los tests de abajo pasarían sin mirar nada."""
    assert len(FLUJOS) >= 4


def test_cada_accion_se_ancla_por_sha_con_su_version_en_un_comentario() -> None:
    sueltas = []
    for flujo in FLUJOS:
        for linea in _lineas_activas(flujo):
            m = USES.search(linea)
            if not m or m.group(1).startswith("./"):
                continue
            ref = m.group(1).rsplit("@", 1)[-1]
            if not re.fullmatch(r"[0-9a-f]{40}", ref) or not (m.group(3) or "").startswith("v"):
                sueltas.append(f"{flujo.name}: {linea.strip()}")
    assert not sueltas, "acciones sin anclar por SHA:\n" + "\n".join(sueltas)


def test_uv_tiene_version_fija_en_ci_y_en_las_imagenes() -> None:
    for flujo in FLUJOS:
        texto = flujo.read_text(encoding="utf-8")
        assert 'version: "latest"' not in texto, flujo.name
    assert "uv:latest" not in (RAIZ / "Dockerfile").read_text(encoding="utf-8")
    assert re.search(r"astral-sh/uv:\d+\.\d+\.\d+", (RAIZ / "Dockerfile").read_text(encoding="utf-8"))
    for dockerfile in ("mcp_server/Dockerfile", "services/script_sandbox/Dockerfile"):
        for linea in _lineas_activas(RAIZ / dockerfile):
            if "pip install" in linea and " uv" in linea:
                assert re.search(r"\buv==\d+\.\d+\.\d+", linea), f"{dockerfile}: {linea.strip()}"


def test_las_herramientas_que_ci_lanza_al_vuelo_tienen_version() -> None:
    sueltas = []
    for flujo in FLUJOS:
        for linea in _lineas_activas(flujo):
            for m in re.finditer(r"uvx\s+(?:--from\s+)?(\S+)", linea):
                if not re.search(r"(==|@)\d", m.group(1)):
                    sueltas.append(f"{flujo.name}: {linea.strip()}")
            for m in re.finditer(r"npx\s+--yes\s+(\S+)", linea):
                if not re.search(r"@\d", m.group(1)):
                    sueltas.append(f"{flujo.name}: {linea.strip()}")
    assert not sueltas, "herramientas sin versión:\n" + "\n".join(sueltas)


def test_dependabot_vigila_acciones_imagenes_y_compose() -> None:
    texto = (RAIZ / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    ecosistemas = set(re.findall(r"package-ecosystem:\s*([\w-]+)", texto))
    assert {"github-actions", "docker", "docker-compose"} <= ecosistemas
