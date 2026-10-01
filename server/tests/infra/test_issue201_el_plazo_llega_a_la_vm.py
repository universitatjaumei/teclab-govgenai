"""Issue #201 — el plazo de la revisión posterior se puede cambiar en la VM, como promete.

`docs/CATALOGO_FUNCIONES.md` dice que «cada despliegue lo cambia con
`PLAZO_REVISION_POSTERIOR_DIAS`, sin tocar código». En la VM no se podía: la configuración no
secreta llega al contenedor por la lista explícita del `environment:` del compose, y
`.env.runtime` sólo lleva lo de `secretos.tsv`. La variable no estaba en esa lista ni la escribía
`deploy.yml`, así que producción usaba siempre los 30 días, configurara lo que configurara la
institución.

Es el mismo hueco que #195, del día anterior. **No se generaliza a un guardarraíl de «todo lo que
el código lee llega a la VM»**, y la razón se midió: son 50 variables, casi todas con un valor por
defecto que ningún despliegue toca, sólo de desarrollo o del SAML apagado. Sería una lista de 50
exenciones, y una lista así es la que nadie mantiene. Lo que sí se ata es la promesa escrita.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parents[3]
DEPLOY = RAIZ / ".github" / "workflows" / "deploy.yml"
COMPOSE = RAIZ / "deploy" / "vm" / "docker-compose.vm.yml"
CATALOGO = RAIZ / "docs" / "CATALOGO_FUNCIONES.md"

VARIABLE = "PLAZO_REVISION_POSTERIOR_DIAS"

_BLOQUE = re.compile(
    r"tee \$\{DESTINO\}/\.env\.despliegue[^\n]*<<'EOF'\n(.*?)^\s*EOF$",
    re.DOTALL | re.MULTILINE,
)


def test_la_documentacion_lo_sigue_prometiendo() -> None:
    """Si la promesa se retira, este fichero sobra: que lo diga en vez de vigilar nada."""
    assert VARIABLE in CATALOGO.read_text(encoding="utf-8")


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
    # Sin tope de obligatoriedad: sin la variable del repositorio, llega vacía y vale el plazo
    # por defecto. Un despliegue que no decide nada no tiene por qué fallar.
    assert entorno.get(VARIABLE) == f"${{{VARIABLE}:-}}"


def test_vacia_vale_el_plazo_por_defecto(monkeypatch) -> None:
    """Es lo que llega al contenedor cuando la institución no ha fijado nada."""
    from server.app.modules.redaccion.funciones_acciones import (
        PLAZO_REVISION_POR_DEFECTO,
        plazo_de_revision_en_dias,
    )

    monkeypatch.setenv(VARIABLE, "")

    assert plazo_de_revision_en_dias() == PLAZO_REVISION_POR_DEFECTO
