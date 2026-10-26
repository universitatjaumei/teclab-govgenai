"""Issue #44 — la imagen del frontend no corre como root, y su puerto es una sola verdad.

`frontend/Dockerfile` no declaraba `USER`, así que nginx corría como root dentro del contenedor.
Las otras tres imágenes del proyecto sí lo declaran —`appuser`, `65534`—, o sea que ésta era la
excepción. **No es un agujero, es defensa en profundidad**: el día que una vulnerabilidad de
nginx permita ejecutar algo, la diferencia entre hacerlo como root o como un usuario sin
privilegios es la diferencia entre un susto y un incidente. Y para un proyecto que se publica
como ejemplo de despliegue para administraciones, una imagen que corre como root es lo que
copiará quien lo tome de plantilla.

**Por qué cambia el puerto, y no sólo se añade `USER`.** Dentro de un contenedor, escuchar en el
80 exige privilegios —root o `CAP_NET_BIND_SERVICE`—, así que «mantener nginx y añadir `USER`»
no es una alternativa más barata: no arranca. La imagen `nginxinc/nginx-unprivileged` existe
exactamente por eso y escucha en el **8080**.

**Y ahí está el riesgo de este cambio**: el puerto aparece en cuatro sitios que tienen que decir
lo mismo —`nginx.conf`, el `EXPOSE` y la sonda del `Dockerfile`, el `reverse_proxy` del
`Caddyfile` y el mapeo del compose de producción—. Si uno se queda atrás, el panel devuelve 502
y el fallo aparece en el despliegue, no aquí. Es el mismo patrón de «tres ficheros y una sola
verdad» que ya vigila DOM.2 para el prefijo del panel.

Lo que este fichero **no** puede comprobar es que el proceso corra sin privilegios: eso se
ejecuta, y lo ejecuta el job `imagen` de CI, que ahora arranca también el frontend y le pregunta
`id`. Aquí se comprueba que ese paso siga existiendo.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[3]
DOCKERFILE = RAIZ / "frontend" / "Dockerfile"
NGINX_CONF = RAIZ / "frontend" / "nginx.conf"
CADDYFILE = RAIZ / "deploy" / "vm" / "Caddyfile"
COMPOSE_PROD = RAIZ / "docker-compose.prod.yml"
CI = RAIZ / ".github" / "workflows" / "ci.yml"

#: El puerto en el que escucha la imagen sin privilegios.
PUERTO = 8080


@pytest.fixture(scope="module")
def dockerfile() -> str:
    return DOCKERFILE.read_text(encoding="utf-8")


class TestLaImagenNoEsPrivilegiada:

    def test_el_runtime_es_la_imagen_sin_privilegios(self, dockerfile: str) -> None:
        etapas = re.findall(r"^FROM\s+(\S+)", dockerfile, re.MULTILINE)
        assert etapas, "el `Dockerfile` no declara ninguna etapa"
        runtime = etapas[-1]
        assert runtime.startswith("nginxinc/nginx-unprivileged:"), (
            f"la etapa de ejecución usa «{runtime}». La imagen oficial de nginx arranca como "
            "root, y añadirle `USER` sin más no vale: dentro del contenedor, escuchar en el 80 "
            "exige privilegios."
        )

    def test_la_imagen_sigue_anclada_por_version(self, dockerfile: str) -> None:
        """Lo mismo que pide la issue #43, que no se pierda al cambiar de imagen."""
        runtime = re.findall(r"^FROM\s+(\S+)", dockerfile, re.MULTILINE)[-1]
        assert ":latest" not in runtime, f"«{runtime}» no fija versión"
        assert ":" in runtime, f"«{runtime}» no fija versión"


class TestElPuertoEsUnaSolaVerdad:
    """Cuatro ficheros, un número. Si uno se queda atrás, el panel da 502 en el despliegue."""

    def test_nginx_escucha_en_el_puerto_sin_privilegios(self) -> None:
        conf = NGINX_CONF.read_text(encoding="utf-8")
        escuchas = re.findall(r"^\s*listen\s+(\d+)", conf, re.MULTILINE)
        assert escuchas == [str(PUERTO)], (
            f"`nginx.conf` escucha en {escuchas} y tiene que ser [{PUERTO}]: por debajo del "
            "1024 hacen falta privilegios que esta imagen ya no tiene."
        )

    def test_el_dockerfile_expone_y_sondea_ese_puerto(self, dockerfile: str) -> None:
        assert f"EXPOSE {PUERTO}" in dockerfile, (
            f"el `Dockerfile` no expone el {PUERTO}"
        )
        sonda = next(
            (linea for linea in dockerfile.splitlines() if "healthz" in linea), ""
        )
        assert f":{PUERTO}/healthz" in sonda, (
            f"la sonda de salud apunta a «{sonda.strip()}». Si sigue llamando al 80, el "
            "contenedor se declara enfermo para siempre y el compose no lo da por listo."
        )

    def test_caddy_reenvia_a_ese_puerto(self) -> None:
        caddy = CADDYFILE.read_text(encoding="utf-8")
        destinos = re.findall(r"reverse_proxy\s+frontend:(\d+)", caddy)
        assert destinos, (
            f"el `Caddyfile` reenvía al frontend por {destinos or 'ningún puerto'}. Es lo que "
            "sirve `/panel/` en producción: con el puerto viejo, 502."
        )
        assert set(destinos) == {str(PUERTO)}, (
            f"el `Caddyfile` reenvía al frontend por {destinos or 'ningún puerto'}. Es lo que "
            "sirve `/panel/` en producción: con el puerto viejo, 502."
        )

    def test_el_compose_de_produccion_publica_contra_ese_puerto(self) -> None:
        datos = yaml.safe_load(COMPOSE_PROD.read_text(encoding="utf-8"))
        puertos = (datos["services"]["frontend"] or {}).get("ports") or []
        assert any(str(p).endswith(f":{PUERTO}") for p in puertos), (
            f"el compose de producción mapea {puertos}. El contenedor ya no escucha en el 80, "
            f"así que el lado derecho tiene que ser {PUERTO}."
        )

    def test_nada_del_servicio_frontend_sigue_hablando_del_puerto_viejo(self) -> None:
        """Y aquí la lección, que vale más que el arreglo.

        La primera versión de esta clase **enumeraba** los sitios donde vive el puerto y se dejó
        uno: el `healthcheck` del propio compose, que sobreescribe el del `Dockerfile` y seguía
        llamando al 80. El panel habría funcionado y el servicio habría quedado `unhealthy` para
        siempre — nada falla, pero todo lo que dependa de `service_healthy` se queda esperando.
        Lo encontró la revisión de la PR #73.

        Así que esto **no enumera**: mira el bloque entero del servicio y exige que ningún
        puerto que no sea el bueno aparezca en él.
        """
        datos = yaml.safe_load(COMPOSE_PROD.read_text(encoding="utf-8"))
        bloque = yaml.safe_dump(datos["services"]["frontend"], allow_unicode=True)
        sospechosas = [
            linea
            for linea in bloque.splitlines()
            if re.search(r"127\.0\.0\.1(?::(\d+))?/|localhost(?::(\d+))?/", linea)
            and f":{PUERTO}/" not in linea
        ]
        assert not sospechosas, (
            f"en el servicio `frontend` hay direcciones que no usan el {PUERTO}: {sospechosas}. "
            "Dentro del contenedor, una URL sin puerto es el 80, y ahí ya no escucha nadie."
        )


def test_ci_arranca_el_frontend_y_le_pregunta_quien_es() -> None:
    """Lo único que demuestra que no corre como root es ejecutarlo.

    Un test que lea el `Dockerfile` comprueba la intención; que el proceso acabe sin
    privilegios depende también de la imagen base y de si algo la sobreescribe. Eso se ejecuta
    en el job `imagen`, que ya construye las cuatro y ahora arranca también ésta.
    """
    datos = yaml.safe_load(CI.read_text(encoding="utf-8"))
    pasos = datos["jobs"]["imagen"]["steps"]
    guiones = " ".join(p.get("run") or "" for p in pasos)
    assert "govgenai/frontend:ci" in guiones, (
        "el job `imagen` construye la imagen del frontend pero no la arranca, así que nadie "
        "comprueba de verdad como qué usuario corre."
    )
    assert "docker run" in guiones, (
        "el job `imagen` construye la imagen del frontend pero no la arranca, así que nadie "
        "comprueba de verdad como qué usuario corre."
    )
    assert "uid=0" in guiones, (
        "el job no comprueba el usuario del contenedor del frontend. La comprobación es "
        "`docker exec … id` y que **no** diga `uid=0`."
    )
