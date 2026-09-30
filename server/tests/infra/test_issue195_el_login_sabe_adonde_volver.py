"""Issue #195 — si el despliegue enciende el login con Google, también le dice adónde volver.

**El defecto.** El callback de Google redirige a `SAML_FRONTEND_RETURN_URL` con el token en el
*fragment*; sin ella, devuelve la sesión **como JSON** y el usuario se queda mirando su token en
una pantalla en blanco. `deploy.yml` escribía las dos variables no secretas del login y el compose
las cableaba, pero **ésta no estaba en ninguno de los dos**. Se vio probando a mano el login tras
subir `oauthlib` a 4.0.0, y no fue oauthlib: fue la última redirección.

**Por qué no lo vio el guardarraíl que ya había.**
`test_lo_que_el_despliegue_escribe_llega_al_contenedor` comprueba que lo que `deploy.yml`
**escribe** llegue al contenedor. Una variable que no se escribe no la puede ver. Éste mira lo
contrario: qué tiene que estar escrito para que una función encendida funcione **entera**.

La misma variable la usa el ACS de SAML, así que el SAML habría salido igual al encenderlo.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parents[3]
DEPLOY = RAIZ / ".github" / "workflows" / "deploy.yml"
COMPOSE = RAIZ / "deploy" / "vm" / "docker-compose.vm.yml"

_BLOQUE = re.compile(
    r"tee \$\{DESTINO\}/\.env\.despliegue[^\n]*<<'EOF'\n(.*?)^\s*EOF$",
    re.DOTALL | re.MULTILINE,
)


def _bloque_del_despliegue() -> str:
    bloque = _BLOQUE.search(DEPLOY.read_text(encoding="utf-8"))
    assert bloque, "no se encuentra el bloque que escribe `.env.despliegue` en deploy.yml"
    return bloque.group(1)


def _entorno_de_app() -> dict:
    compose = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    return compose["services"]["app"].get("environment") or {}


def test_el_medidor_ve_el_login_con_google_cableado() -> None:
    """Si el login dejara de cablearse, este test pasaría sin mirar nada: que lo diga."""
    assert "GOOGLE_OAUTH_REDIRECT_URI=" in _bloque_del_despliegue()
    assert "GOOGLE_OAUTH_REDIRECT_URI" in _entorno_de_app()


def test_el_despliegue_escribe_adonde_volver_desde_una_variable_del_repositorio() -> None:
    """Desde `vars.` y no como constante: el dominio es de quien despliega, no del código."""
    assert re.search(
        r"^\s*SAML_FRONTEND_RETURN_URL=\$\{\{ vars\.SAML_FRONTEND_RETURN_URL \}\}\s*$",
        _bloque_del_despliegue(),
        re.MULTILINE,
    ), "deploy.yml no escribe SAML_FRONTEND_RETURN_URL en `.env.despliegue`"


def test_y_llega_al_contenedor() -> None:
    entorno = _entorno_de_app()
    assert "SAML_FRONTEND_RETURN_URL" in entorno, (
        "el servicio `app` del compose de la VM no recibe SAML_FRONTEND_RETURN_URL: el callback "
        "de Google devolvería la sesión como JSON en vez de volver al panel"
    )
    # Sin tope de obligatoriedad (`:?`), como las otras dos del login: vacía, el login con Google
    # sigue apagándose entero por sus cuatro piezas, y un despliegue sin login no debe fallar.
    assert entorno["SAML_FRONTEND_RETURN_URL"] == "${SAML_FRONTEND_RETURN_URL:-}"
