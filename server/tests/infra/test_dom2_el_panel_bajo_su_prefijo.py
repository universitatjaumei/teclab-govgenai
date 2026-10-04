"""El panel servido bajo un prefijo, y el prefijo dicho en un solo sitio por capa (DOM.2).

La raíz de `normativa.uji.es` pasa a ser la portada pública del corpus (DOM.1), así que el panel
necesita una dirección propia: `/panel/`. Eso toca **tres capas** y ninguna se puede mirar sola:

* **Compilación.** Vite escribe las URL de los recursos en el HTML en tiempo de `build`, así que
  el prefijo es un `base`. Consecuencia que no es opinable: la imagen del frontend referencia
  `/panel/assets/…` sea quien sea el que la sirva, y por eso el panel vive bajo el mismo prefijo
  en los dos nombres —el provisional y el institucional—. Servirlo en la raíz de uno pediría una
  segunda imagen.
* **Encaminamiento del cliente.** `BrowserRouter` necesita `basename`, o cada `<Link>` apunta
  fuera del prefijo. Se toma de `import.meta.env.BASE_URL`, que Vite deriva de `base`: así el
  mismo código sirve en desarrollo (raíz) y en la imagen (`/panel/`) sin ningún literal, y los
  tests siguen montando en la raíz.
* **Servidor de estáticos.** El nginx de la imagen tiene que servir el panel en `/panel/` **de
  verdad**, no gracias a que el proxy le quite el prefijo por delante. Con un `handle_path` que
  lo despoje, el contenedor abierto directo sirve en la raíz mientras su HTML pide
  `/panel/assets/…`: funciona sólo con el proxy puesto, y esa diferencia se descubre depurando.

Y de ahí el test que da más valor de todos los de este fichero: **los tres prefijos son el
mismo**. Son tres ficheros distintos y una sola verdad; cuando divergen no hay error en ningún
log, hay una pantalla en blanco con 404 en la consola del navegador.
"""

from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
FRONTEND = RAIZ / "frontend"
VITE = FRONTEND / "vite.config.ts"
APP = FRONTEND / "src" / "App.tsx"
DOCKERFILE = FRONTEND / "Dockerfile"
NGINX = FRONTEND / "nginx.conf"
CADDYFILE = RAIZ / "deploy" / "vm" / "Caddyfile"

PREFIJO = "/panel/"


def _texto(ruta: Path) -> str:
    assert ruta.is_file(), f"Falta {ruta.relative_to(RAIZ).as_posix()}"
    return ruta.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. Compilación: el prefijo es configuración, y el defecto es la raíz
# ---------------------------------------------------------------------------


def test_vite_toma_la_base_de_una_variable_con_la_raiz_por_defecto() -> None:
    """El defecto es `/` para no invalidar lo que ya dice `localhost:5173`.

    `arranque.bat`, `.env.example`, la documentación de metodología y una docena de guiones de
    pruebas manuales de bloques ya cerrados dan por hecho que en desarrollo el panel está en la
    raíz. Quien la necesite igual que en producción, pone `VITE_BASE_PATH` en `.env.local`.
    """
    texto = _texto(VITE)
    assert re.search(r"\bbase\s*:", texto), (
        "Sin `base`, Vite emite `/assets/…` y esas URL, servidas bajo `/panel/`, caen en el "
        "catch-all del proxy — o sea en el bucket del corpus, que devuelve 404."
    )
    assert "VITE_BASE_PATH" in texto, "El prefijo llega por variable, no escrito en el código."
    reserva = re.search(r"VITE_BASE_PATH[^\n]*(?:\|\||\?\?)\s*(?:'(/[^']*)'|(\w+))", texto)
    assert reserva, (
        "`VITE_BASE_PATH` necesita valor de reserva: sin él, un `.env.local` sin la variable "
        "deja `base` en `undefined` y Vite emite rutas relativas, que rompen las rutas "
        "profundas del router."
    )
    literal, constante = reserva.group(1), reserva.group(2)
    if constante:
        declarada = re.search(rf"const {constante}\s*=\s*'(/[^']*)'", texto)
        assert declarada, f"No se puede leer el valor de {constante}."
        literal = declarada.group(1)
    assert literal == "/", (
        f"El defecto tiene que ser la raíz y es {literal!r}: es lo que espera el servidor de "
        f"desarrollo y lo que dan por hecho `arranque.bat` y los guiones de pruebas manuales."
    )


def test_el_router_toma_su_base_del_entorno_y_no_de_un_literal() -> None:
    texto = _texto(APP)
    assert re.search(r"basename=\{import\.meta\.env\.BASE_URL\}", texto), (
        "El `basename` del BrowserRouter sale de `import.meta.env.BASE_URL`, que Vite deriva "
        "de `base`. Con el prefijo escrito a mano, los tests —que montan en la raíz— dejarían "
        "de encontrar sus rutas, y el día que el prefijo cambie hay que acordarse de dos."
    )
    literales = [
        linea
        for linea in texto.splitlines()
        if PREFIJO.strip("/") in linea and "basename" in linea
    ]
    assert not literales, f"El prefijo escrito en el router: {literales}"


def test_no_queda_ninguna_navegacion_absoluta_en_el_frontend() -> None:
    """Una `window.location.href = '/algo'` se salta el `basename` y sale del panel.

    Se permite la que va a la API: `/api/v1/…` NO está bajo el prefijo —la sirve la aplicación,
    no el frontend—, así que ahí la ruta absoluta es la correcta.

    Y la vuelta a la extensión del navegador (#176): va a otro origen, `https://<id>.chromiumapp.org/`,
    que el servidor ha validado contra `AGENTES_EXTENSION_IDS`. No es una ruta del panel, así que
    el prefijo no le aplica. Se exceptúa el fichero, no el patrón: otra navegación en él saltaría.
    """
    vuelta_a_la_extension = "frontend/src/agentes/ConectarExtensionPage.tsx"
    sospechosas: list[str] = []
    for fichero in (FRONTEND / "src").rglob("*.tsx"):
        if "__tests__" in fichero.parts:
            continue
        if fichero.relative_to(RAIZ).as_posix() == vuelta_a_la_extension:
            texto = fichero.read_text(encoding="utf-8")
            assert len(re.findall(r"location\.(href\s*=|replace\(|assign\()", texto)) == 1, (
                f"{vuelta_a_la_extension} sólo puede navegar a la extensión, una vez"
            )
            assert "location.assign(`${r.destino}#token=" in texto
            continue
        for numero, linea in enumerate(fichero.read_text(encoding="utf-8").splitlines(), 1):
            if not re.search(r"(window\.)?location\.(href\s*=|replace\(|assign\()", linea):
                continue
            if "/api/" in linea or "API_BASE" in linea or "apiBaseUrl" in linea:
                continue
            sospechosas.append(f"{fichero.relative_to(RAIZ).as_posix()}:{numero}: {linea.strip()}")
    assert not sospechosas, (
        "Navegación absoluta que no pasa por el router y por tanto ignora el prefijo:\n"
        + "\n".join(sospechosas)
    )


# ---------------------------------------------------------------------------
# 2. La imagen sirve el panel en su prefijo, con proxy y sin él
# ---------------------------------------------------------------------------


def test_la_imagen_se_construye_con_el_prefijo_de_produccion() -> None:
    texto = _texto(DOCKERFILE)
    assert re.search(r'ARG VITE_BASE_PATH="?/panel/"?', texto), (
        "La imagen ES producción, así que su `ARG` trae el prefijo por defecto: `deploy.yml` "
        "construye con `docker build ./frontend` a secas, sin pasar build-args."
    )
    assert re.search(r"ENV VITE_BASE_PATH=\$\{?VITE_BASE_PATH\}?", texto), (
        "El `ARG` tiene que llegar al `npm run build` como variable de entorno; un ARG a solas "
        "no lo ve Vite."
    )
    assert re.search(r"/usr/share/nginx/html/panel", texto), (
        "El `dist` va al subdirectorio, no a la raíz: así `/panel/assets/x.js` es un fichero "
        "que existe de verdad y no un fallback del SPA."
    )


def test_nginx_sirve_el_panel_desde_su_subdirectorio() -> None:
    texto = _texto(NGINX)
    assert "location /panel/" in texto, (
        "Sin su `location`, `/panel/algo` cae en el de la raíz y su `try_files` devuelve el "
        "`index.html` de la raíz, que ya no existe."
    )
    assert re.search(r"try_files\s+\$uri\s+/panel/index\.html", texto), (
        "El fallback del SPA tiene que ser el `index.html` DE DENTRO. Con el de la raíz, un "
        "`/panel/assets/x.js` que no exista devolvería HTML con tipo de contenido de "
        "JavaScript: la consola dice «Unexpected token '<'» y nadie mira nginx."
    )
    assert re.search(r"location\s*=\s*/panel\b", texto), (
        "Quien escriba la dirección corta sin barra final tiene que acabar en `/panel/`."
    )
    assert "/healthz" in texto, (
        "La sonda del HEALTHCHECK de la imagen no se mueve: no está bajo el panel."
    )


def test_las_redirecciones_de_nginx_no_inventan_el_esquema() -> None:
    """`https://…/panel` no puede contestar `Location: http://…/panel/`.

    nginx compone la URL absoluta con su propio esquema, y el suyo es `http` porque el TLS lo
    termina Caddy. Medido en producción el 2026-09-02 al verificar DOM.5: el 301 de la
    dirección corta salía en claro. Funciona —Caddy devuelve a https y el HSTS de la
    aplicación hace que el navegador ni salga—, pero es un salto que no hace falta, y la
    forma de no tenerlo es que la `Location` sea relativa.
    """
    assert "absolute_redirect off" in _texto(NGINX), (
        "Falta `absolute_redirect off;`. Es una línea y evita que cada `return 301` de este "
        "fichero degrade el esquema."
    )


def test_el_proxy_no_le_quita_el_prefijo_a_la_imagen() -> None:
    """Es la comprobación que mantiene el contenedor honesto abierto directo."""
    activas = [
        linea
        for linea in _texto(CADDYFILE).splitlines()
        if "handle_path" in linea and not linea.strip().startswith("#")
    ]
    assert not activas, f"El prefijo lo sirve nginx; no se despoja por delante: {activas}"


# ---------------------------------------------------------------------------
# 3. Tres ficheros, un solo prefijo
# ---------------------------------------------------------------------------


def test_el_prefijo_es_el_mismo_en_la_imagen_en_nginx_y_en_el_proxy() -> None:
    """Divergen en silencio: no hay log, hay una pantalla en blanco.

    Este es el test que de verdad protege el cambio. El prefijo se dice una vez por capa
    —porque cada capa lo necesita en su propio lenguaje— y aquí se comprueba que las tres
    dicen lo mismo.
    """
    dockerfile = _texto(DOCKERFILE)
    en_imagen = re.search(r'ARG VITE_BASE_PATH="?(/[^"\s]*/)"?', dockerfile)
    assert en_imagen, "No se puede leer el prefijo del Dockerfile."
    prefijo = en_imagen.group(1)

    assert f"location {prefijo}" in _texto(NGINX), (
        f"nginx no sirve {prefijo}, que es el prefijo con el que se compila la imagen."
    )
    assert f"/usr/share/nginx/html{prefijo.rstrip('/')}" in dockerfile, (
        f"El `dist` no se copia al subdirectorio {prefijo}."
    )

    caddy = _texto(CADDYFILE)
    matchers = re.findall(r"^\t@\w+\s+path\s+([^\n]+)$", caddy, re.M)
    rutas = [ruta for linea in matchers for ruta in linea.split()]
    corto = prefijo.rstrip("/")
    assert corto in rutas and f"{prefijo}*" in rutas, (
        f"El proxy no encamina {corto} y {prefijo}* al frontend. Rutas encontradas: {rutas}"
    )
