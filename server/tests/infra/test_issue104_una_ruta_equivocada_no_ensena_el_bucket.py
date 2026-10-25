"""Una dirección que no existe da una página nuestra, no el XML de Google Cloud Storage.

**Lo medido (issue #104).** `https://normativa.uji.es/hub`, `/login`, `/admin` o cualquier ruta
que no esté en el *bucket* devolvían esto, en los dos hosts:

```xml
<Error><Code>NoSuchKey</Code><Message>The specified key does not exist.</Message>
<Details>No such object: govgenai-normativa-uji/hub</Details></Error>
```

El `handle` final del `Caddyfile` manda al *bucket* todo lo que no sea `/api/*`, `/health`,
`@panel` o `@mcp`, y el *bucket* responde su propio error. Es correcto para una página del corpus
que no existe; lo que no es correcto es **cómo se ve**.

Tres razones, y la segunda es la que lo trae a este bloque:

1. **Lo ve cualquiera que se equivoque de enlace** — un marcador viejo, un correo, escribir la
   dirección de memoria. Pasó buscando la pantalla de módulos.
2. **Filtra el nombre del *bucket***, que es justo el identificador que REPO.5 saca de la
   documentación para no repartir el inventario de qué sondear. Que el guardarraíl limpie los
   documentos y el servidor lo publique en cada 404 deja la medida a medias.
3. Un XML de error de un proveedor de nube en un dominio institucional **parece una avería**.

**El 404 se conserva.** Devolver 200 con una página bonita sería peor: diría a los buscadores y a
quien enlaza que la dirección existe.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[3]
CADDYFILE = RAIZ / "deploy" / "vm" / "Caddyfile"

#: Lo que no puede salir en una respuesta al público. Es el mismo criterio de REPO.5, aplicado
#: a lo que el servidor emite y no a lo que la documentación escribe.
_NO_SE_ENSENA = re.compile(r"CORPUS_BUCKET|govgenai-normativa-uji|storage\.googleapis\.com")


def _bloque_de_respuesta_de_error() -> str:
    """El `handle_response` que intercepta los errores del *bucket*, con su cuerpo."""
    texto = CADDYFILE.read_text(encoding="utf-8")
    inicio = texto.find("handle_response")
    if inicio == -1:
        return ""
    # Hasta el cierre de su llave, contando anidamiento.
    profundidad = 0
    for i in range(inicio, len(texto)):
        if texto[i] == "{":
            profundidad += 1
        elif texto[i] == "}":
            profundidad -= 1
            if profundidad == 0:
                return texto[inicio : i + 1]
    return texto[inicio:]


class TestElErrorEsNuestro:
    def test_los_errores_del_bucket_se_interceptan(self) -> None:
        bloque = _bloque_de_respuesta_de_error()
        assert bloque, (
            "el `Caddyfile` no intercepta la respuesta del *bucket*, así que una ruta que no "
            "existe devuelve el XML de Google Cloud Storage tal cual"
        )

    def test_la_respuesta_no_nombra_la_infraestructura(self) -> None:
        """Lo que REPO.5 saca de los documentos no puede salir por el servidor."""
        bloque = _bloque_de_respuesta_de_error()
        encontrado = _NO_SE_ENSENA.findall(bloque)
        assert encontrado == [], (
            f"la página de error nombra infraestructura: {encontrado}. Es el mismo identificador "
            "que el guardarraíl de REPO.5 quita de la documentación."
        )

    def test_conserva_el_codigo_de_error(self) -> None:
        """Un 200 con una página bonita diría que la dirección existe, y es peor.

        Vale el literal o `{rp.status_code}`, que **propaga** el del *bucket*: así un 404 sigue
        siendo 404 y un 403 sigue siendo 403, en vez de aplanarlos a uno solo. Mi primera
        versión de este test exigía el literal `404` y ponía roja la implementación mejor.
        """
        bloque = _bloque_de_respuesta_de_error()
        assert re.search(r"\b404\b|\{rp\.status_code\}", bloque), (
            "la respuesta no conserva el código de error: con un 200, buscadores y enlazadores "
            "creerían que la dirección existe"
        )

    def test_no_aplana_el_error_a_un_200(self) -> None:
        """Lo que de verdad no puede pasar, dicho aparte de cómo se consiga."""
        bloque = _bloque_de_respuesta_de_error()
        assert not re.search(r"HTML\s+200\b|respond[^\n]*\b200\b", bloque), (
            "la página de error se devuelve con 200"
        )

    def test_esta_en_la_lengua_del_sitio(self) -> None:
        """El sitio del corpus es `<html lang="ca">`; una página de error en inglés desentona."""
        bloque = _bloque_de_respuesta_de_error()
        assert 'lang="ca"' in bloque, "la página de error no declara la lengua del sitio"


class TestElCaddyfileSigueSiendoValido:
    """Un `Caddyfile` inválido **no arranca**, y eso se paga con el servicio caído.

    Se valida con la misma imagen que corre en producción, no con una lectura a ojo: la sintaxis
    de `handle_response` es fácil de escribir casi bien.
    """

    def test_la_configuracion_es_valida(self) -> None:
        if shutil.which("docker") is None:  # pragma: no cover - depende de la máquina
            pytest.skip("hace falta docker para validar el Caddyfile")

        resultado = subprocess.run(
            [
                "docker", "run", "--rm",
                "-v", f"{CADDYFILE.as_posix()}:/etc/caddy/Caddyfile:ro",
                "-e", "GOVGENAI_HOST=ejemplo.test",
                "-e", "GOVGENAI_HOST_INSTITUCIONAL=otro.test",
                "-e", "CORPUS_BUCKET=un-bucket",
                "caddy:2.8-alpine",
                "caddy", "validate", "--config", "/etc/caddy/Caddyfile",
            ],
            capture_output=True, text=True, timeout=300,
            check=False,
        )
        if resultado.returncode != 0 and "Cannot connect to the Docker daemon" in (
            resultado.stderr or ""
        ):  # pragma: no cover - depende de la máquina
            pytest.skip("Docker no está en marcha")

        assert resultado.returncode == 0, (
            f"el `Caddyfile` no valida:\n{resultado.stdout}\n{resultado.stderr}"
        )
