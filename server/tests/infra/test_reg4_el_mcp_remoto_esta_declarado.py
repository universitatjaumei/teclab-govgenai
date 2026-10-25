"""REG.4 — el MCP remoto queda declarado en el despliegue, y sin token propio.

Los tests del transporte y de las tools viven en `mcp_server/tests/`, que corre con su propio
venv. Aquí se comprueba lo otro: que el servicio existe en la pila de la VM, que el proxy le
manda `/mcp`, que CI construye y publica su imagen, y que **no se le pasa ningún PAT**.

Ese último es el que justifica el fichero. El resto de la pila lleva credenciales por entorno con
naturalidad, así que añadir `GOVGENAI_PAT` aquí sería el cambio más razonable del mundo para
alguien que no sepa por qué no está — y dejaría a todos los clientes del MCP remoto actuando con
la misma identidad, con lo que el registro de actividad diría que todo lo hizo un solo token. Un
guardarraíl es más barato que descubrirlo en una auditoría.
"""
from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
VM = RAIZ / "deploy" / "vm"
COMPOSE = VM / "docker-compose.vm.yml"
CADDYFILE = VM / "Caddyfile"
DESPLIEGUE = RAIZ / ".github" / "workflows" / "deploy.yml"
DOCKERFILE = RAIZ / "mcp_server" / "Dockerfile"
RUNBOOK = RAIZ / "docs" / "DESPLIEGUE_PROTOTIPO_GCP.md"


def _texto(ruta: Path) -> str:
    assert ruta.is_file(), f"Falta {ruta.relative_to(RAIZ).as_posix()}"
    return ruta.read_text(encoding="utf-8")


def _activas(ruta: Path, aguja: str) -> list[str]:
    """Líneas que contienen `aguja` sin ser comentario.

    Los comentarios de estos ficheros explican precisamente lo que no se hace, así que buscar la
    cadena a secas daría por infringida cada regla que se documenta.
    """
    return [
        linea
        for linea in _texto(ruta).splitlines()
        if aguja in linea and not linea.strip().startswith("#")
    ]


# ---------------------------------------------------------------------------
# El servicio existe y no lleva credencial
# ---------------------------------------------------------------------------


def test_el_servicio_del_mcp_esta_en_la_pila_de_la_vm() -> None:
    texto = _texto(COMPOSE)
    assert re.search(r"^  mcp:\s*$", texto, re.MULTILINE), (
        "El MCP remoto se declara como servicio propio: no importa `server.app` y no necesita "
        "ni el venv del servidor ni el socket de la base."
    )
    assert "GOVGENAI_MCP_IMAGE" in texto, "Su imagen llega por variable, como las otras tres."


def test_el_mcp_remoto_no_recibe_ningun_pat_por_entorno() -> None:
    """La decisión del bloque: el token es el que presenta cada cliente.

    Con un PAT aquí, todos los clientes actuarían con la misma identidad y el registro de
    actividad diría que todo lo hizo un solo token.
    """
    assert _activas(COMPOSE, "GOVGENAI_PAT") == [], (
        "El MCP remoto es multi-cliente: cada uno presenta su PAT en la petición. Un token de "
        "entorno los uniformaría a todos y vaciaría de sentido el registro de actividad."
    )


def test_los_hosts_admitidos_se_derivan_de_los_que_sirve_el_proxy() -> None:
    """Y no son una variable aparte que pueda quedarse atrás.

    El SDK valida la cabecera `Host` contra esta lista y Caddy reenvía la original: un nombre
    que falte recibe 421 en todo `/mcp`.
    """
    lineas = _activas(COMPOSE, "GOVGENAI_MCP_ALLOWED_HOSTS")
    assert lineas, "Sin hosts admitidos el transporte responde 421 a todo."
    (linea,) = lineas
    assert "GOVGENAI_HOST" in linea, (
        "Los dos nombres que sirve el proxy tienen que estar, y derivados de las mismas "
        "variables que usa Caddy para no divergir."
    )
    assert "GOVGENAI_HOST_INSTITUCIONAL" in linea, (
        "Los dos nombres que sirve el proxy tienen que estar, y derivados de las mismas "
        "variables que usa Caddy para no divergir."
    )


def test_el_mcp_habla_con_la_aplicacion_por_la_red_interna() -> None:
    lineas = _activas(COMPOSE, "GOVGENAI_API_BASE_URL")
    assert lineas, "Falta la URL de la API."
    (linea,) = lineas
    assert "http://app:8000" in linea, (
        "Por la red interna del Compose: salir al proxy y volver a entrar añade un salto y una "
        "dependencia del certificado para una llamada que no sale de la máquina."
    )


# ---------------------------------------------------------------------------
# El proxy y la imagen
# ---------------------------------------------------------------------------


def test_el_proxy_manda_mcp_al_servicio_sin_despojar_el_prefijo() -> None:
    texto = _texto(CADDYFILE)
    assert "@mcp path /mcp /mcp/*" in texto, (
        "`handle` acepta un solo argumento: las dos rutas van en un matcher con nombre."
    )
    assert "reverse_proxy mcp:8080" in texto
    assert "handle_path /mcp" not in texto, (
        "El SDK sirve el transporte en `/mcp`; despojar el prefijo dejaría al contenedor "
        "funcionando sólo detrás del proxy."
    )


def test_la_imagen_del_mcp_se_construye_y_se_publica_en_el_despliegue() -> None:
    texto = _texto(DESPLIEGUE)
    assert "construir_si_falta mcp ./mcp_server ./mcp_server/Dockerfile" in texto
    assert "GOVGENAI_MCP_IMAGE=" in texto, (
        "Sin escribirla en la configuración del despliegue, el compose no arranca: la variable "
        "es obligatoria a propósito."
    )


def test_la_imagen_del_mcp_no_arrastra_el_servidor() -> None:
    """Lo que la hace pequeña es no llevar lo que no usa."""
    texto = _texto(DOCKERFILE)
    assert "COPY server/" not in texto
    assert "--frozen" in texto, "El lock manda: una imagen no vuelve a resolver dependencias."


def test_el_despliegue_esta_escrito_en_el_runbook() -> None:
    """Quien lo despliegue no tiene por qué deducirlo del compose."""
    texto = _texto(RUNBOOK)
    assert "/mcp" in texto, (
        "El runbook de despliegue tiene que decir que existe esta superficie y cómo se conecta "
        "un cliente."
    )
    assert "MCP" in texto, (
        "El runbook de despliegue tiene que decir que existe esta superficie y cómo se conecta "
        "un cliente."
    )
    assert "claude mcp add" in texto, (
        "Y con el comando concreto: es lo que convierte «existe un endpoint» en «alguien lo usa»."
    )
