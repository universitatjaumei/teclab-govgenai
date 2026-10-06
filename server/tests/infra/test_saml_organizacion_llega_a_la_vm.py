"""Quien entra con su cuenta institucional queda en la organización de la institución.

El alta automática —la de Google y la de SAML comparten `SamlIdentityService`— pone a cada
persona nueva en la organización de `SAML_ORGANIZACION_ID`, y en cada entrada se la vuelve a
poner. **En la VM esa variable no llegaba**: no está en `secretos.tsv`, no la escribía
`deploy.yml` ni la pasaba el `environment:` del compose. Resultado: todo el que entraba con
`@uji.es` quedaba sin organización, y el catálogo de agentes —acotado por organización— le decía
que no había ninguno. Asignársela a mano no servía: la siguiente entrada se la quitaba.

Lo destapó el 2026-10-06 la primera invitación al piloto del agente de pliegos: al superadmin le
funcionaba, porque el superadmin ve todas las organizaciones.

El nombre dice SAML y sirve igual para Google; es la misma regla que el docstring de
`google_auth_router.py` deja escrita. Patrón de #201: se ata la promesa escrita, no todas las
variables que el código lee.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parents[3]
DEPLOY = RAIZ / ".github" / "workflows" / "deploy.yml"
COMPOSE = RAIZ / "deploy" / "vm" / "docker-compose.vm.yml"
DESPLIEGUE = RAIZ / "docs" / "DESPLIEGUE_PROTOTIPO_GCP.md"

VARIABLE = "SAML_ORGANIZACION_ID"

_BLOQUE = re.compile(
    r"tee \$\{DESTINO\}/\.env\.despliegue[^\n]*<<'EOF'\n(.*?)^\s*EOF$",
    re.DOTALL | re.MULTILINE,
)


def test_la_documentacion_del_despliegue_lo_dice() -> None:
    assert VARIABLE in DESPLIEGUE.read_text(encoding="utf-8")


def test_el_despliegue_lo_escribe_desde_una_variable_del_repositorio() -> None:
    bloque = _BLOQUE.search(DEPLOY.read_text(encoding="utf-8"))
    assert bloque, "no se encuentra el bloque que escribe `.env.despliegue` en deploy.yml"
    assert re.search(
        rf"^\s*{VARIABLE}=\$\{{\{{ vars\.{VARIABLE} \}}\}}\s*$",
        bloque.group(1),
        re.MULTILINE,
    ), f"deploy.yml no escribe {VARIABLE} en `.env.despliegue`"


def test_y_llega_al_contenedor() -> None:
    compose = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    entorno = compose["services"]["app"].get("environment") or {}
    # Sin tope de obligatoriedad: vacía, la persona entra sin organización, que es el fallo
    # seguro de SEC.2.1. Un despliegue sin login institucional no tiene por qué fallar.
    assert entorno.get(VARIABLE) == f"${{{VARIABLE}:-}}"
