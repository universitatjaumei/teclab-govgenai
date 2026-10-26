"""El HTML del panel y del sitio se sirve con cabeceras de seguridad, no sólo el JSON de la API.

`SecurityHeadersMiddleware` envuelve la aplicación FastAPI, y por eso cada respuesta de `/api/*`
llevaba CSP, `X-Frame-Options` y `nosniff`. Pero el documento del panel lo sirve el nginx de la
imagen del frontend, y el sitio del corpus el bucket a través de Caddy, y ninguno ponía ninguna:
comprobado en producción el 2026-10-21, `/panel/` y `/` respondían sin una sola. Proteger contra
el enmarcado una respuesta JSON no sirve de nada; lo que se enmarca es el documento.

Se lee la configuración tal cual se despliega:

* cada `location` del panel en `frontend/nginx.conf` lleva las cuatro cabeceras —en nginx, un
  `add_header` dentro de una `location` anula los heredados, así que se mira cada una—, con una
  CSP que no admite `unsafe-eval` ni scripts de otro origen y que prohíbe el enmarcado;
* la ruta del bucket en el Caddyfile lleva `nosniff` y `Referrer-Policy`. Sin CSP a propósito:
  las páginas del sitio se generan en otro repositorio y una política escrita a ciegas las
  rompería.
"""
from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
NGINX = RAIZ / "frontend" / "nginx.conf"
CADDY = RAIZ / "deploy" / "vm" / "Caddyfile"

CABECERAS_DEL_PANEL = (
    "Content-Security-Policy",
    "X-Frame-Options",
    "X-Content-Type-Options",
    "Referrer-Policy",
)


def _bloques_location(texto: str) -> dict[str, str]:
    """`{ruta: cuerpo}` de cada `location`, con llaves anidadas de un nivel."""
    bloques = {}
    for coincidencia in re.finditer(r"location\s+(=\s+)?(\S+)\s*\{", texto):
        inicio = coincidencia.end()
        profundidad, i = 1, inicio
        while profundidad:
            profundidad += {"{": 1, "}": -1}.get(texto[i], 0)
            i += 1
        bloques[coincidencia.group(2)] = texto[inicio:i - 1]
    return bloques


def _csp(cuerpo: str) -> str:
    encontrada = re.search(r'add_header\s+Content-Security-Policy\s+"([^"]+)"', cuerpo)
    assert encontrada, "sin CSP"
    return encontrada.group(1)


class TestElPanel:

    def test_should_find_the_panel_locations(self):
        bloques = _bloques_location(NGINX.read_text(encoding="utf-8"))
        assert "/panel/" in bloques, sorted(bloques)
        assert "/panel/assets/" in bloques, sorted(bloques)

    def test_should_send_the_four_headers_from_every_panel_location(self):
        bloques = _bloques_location(NGINX.read_text(encoding="utf-8"))
        for ruta in ("/panel/", "/panel/assets/"):
            for cabecera in CABECERAS_DEL_PANEL:
                assert re.search(rf"add_header\s+{cabecera}\s", bloques[ruta]), (
                    f"`location {ruta}` no pone `{cabecera}`. En nginx, un `add_header` dentro de "
                    "una location anula los del bloque `server`: cada location lleva las suyas."
                )

    def test_should_send_them_always_and_not_only_on_success(self):
        """Sin `always`, nginx no las pone en un 404 ni en un 500."""
        bloques = _bloques_location(NGINX.read_text(encoding="utf-8"))
        for ruta in ("/panel/", "/panel/assets/"):
            lineas = [
                linea.strip()
                for linea in bloques[ruta].splitlines()
                if re.match(r"\s*add_header\s+(Content-Security|X-Frame|X-Content|Referrer)", linea)
            ]
            assert len(lineas) == 4, lineas
            for linea in lineas:
                assert linea.endswith("always;"), linea

    def test_should_forbid_framing_and_foreign_or_evaluated_scripts(self):
        csp = _csp(_bloques_location(NGINX.read_text(encoding="utf-8"))["/panel/"])
        assert "frame-ancestors 'none'" in csp
        assert "script-src 'self'" in csp
        assert "unsafe-eval" not in csp
        assert "object-src 'none'" in csp


class TestElSitioDelCorpus:

    def test_should_send_nosniff_and_referrer_policy_from_the_bucket_route(self):
        texto = CADDY.read_text(encoding="utf-8")
        inicio = texto.index("# Todo lo demás, el sitio del corpus publicado en el bucket.")
        ruta = texto[inicio:inicio + 6000]
        assert re.search(r'X-Content-Type-Options\s+"?nosniff', ruta)
        assert re.search(r"Referrer-Policy\s", ruta)
