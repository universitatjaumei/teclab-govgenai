"""APER.3 — un `ENVIRONMENT` sin poner no puede significar «sin protecciones».

**Hallazgo M4 de la auditoría previa a abrir el repositorio.** `ENVIRONMENT` se lee con
`os.getenv("ENVIRONMENT", "development")` en **dos** sitios, y el valor por omisión es el
permisivo:

- `core/config.py` — con `development` no corre **ninguno** de los cuatro gates de producción:
  ni el del secreto de ejemplo, ni el del sandbox local, ni el de `TESTING=1`, ni el de la
  válvula del rastreador que añadió APER.1.
- `database/seeds.py` — siembra `admin@example.local` con la contraseña `admin1234`, que está
  escrita en el propio módulo. El comentario de AIS.2 dice que la protección «no es que sea
  secreta, es el gate», y el gate tiene el mismo valor por omisión permisivo.

**El despliegue de la UJI no está afectado**: los dos composes y el job `imagen` de CI fijan
`ENVIRONMENT: production`. El riesgo es de **quien despliegue desde el repositorio público** sin
leer `.env.example`: un `docker run` con sólo `JWT_SECRET_KEY` arrancaba en modo desarrollo, con
la cuenta de administración conocida y sin sandbox aislado.

**Por qué el arreglo va en la imagen y no en el valor por omisión del código.** Darle la vuelta al
defecto —que un `ENVIRONMENT` ausente signifique `production`— pondría los cuatro gates a correr
en la suite y en el desarrollo en el host, que es donde `TESTING=1` y `SANDBOX_MODE=local` son
correctos: rompería todo para arreglar un caso que sólo ocurre en la imagen. La imagen es el
camino real de despliegue, y ahí el valor se ancla. En el host, que es donde el defecto es
deliberado, lo que se añade es que **se diga en voz alta**.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

DOCKERFILE = Path(__file__).resolve().parents[3] / "Dockerfile"


class TestLaImagenNoHeredaElDefectoPermisivo:
    """Lo que arregla el caso real: nada que salga de la imagen arranca en modo desarrollo."""

    def test_el_dockerfile_declara_el_entorno_de_produccion(self) -> None:
        lineas = [
            linea.strip()
            for linea in DOCKERFILE.read_text(encoding="utf-8").splitlines()
            if linea.strip().startswith("ENV ")
        ]
        assert any("ENVIRONMENT=production" in linea for linea in lineas), (
            "El Dockerfile no fija ENVIRONMENT. Sin esto, un `docker run` con sólo "
            "JWT_SECRET_KEY arranca en modo desarrollo: sin los cuatro gates y sembrando "
            "admin@example.local con una contraseña que está escrita en el repositorio."
        )

    def test_los_composes_lo_siguen_diciendo_explicitamente(self) -> None:
        """La redundancia es a propósito: quien lee el compose ve en qué entorno corre.

        Si un día se quita del Dockerfile, estos dos siguen protegiendo el despliegue de la
        UJI — y al revés. Es la única parte de esto que ya estaba bien.
        """
        raiz = DOCKERFILE.parent
        for ruta in (
            raiz / "docker-compose.prod.yml",
            raiz / "deploy" / "vm" / "docker-compose.vm.yml",
        ):
            texto = ruta.read_text(encoding="utf-8")
            assert "ENVIRONMENT: production" in texto, f"{ruta.name} no fija el entorno"


class TestEnElHostElDefectoSeDiceEnVozAlta:
    """En el host el valor por omisión sigue siendo `development`, y eso es deliberado.

    Lo que no puede seguir siendo es **silencioso**: un despliegue accidentalmente permisivo
    funciona perfectamente hasta que alguien lo aprovecha, y lo único que lo delataría es un
    registro que nadie escribió.
    """

    def test_avisa_cuando_el_entorno_no_esta_declarado(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        from server.app.core.config import get_settings

        monkeypatch.delenv("ENVIRONMENT", raising=False)
        monkeypatch.setenv("JWT_SECRET_KEY", "clave-de-desarrollo")

        with caplog.at_level(logging.WARNING):
            ajustes = get_settings()

        assert ajustes.environment == "development"
        assert any(
            "ENVIRONMENT" in registro.message for registro in caplog.records
        ), "un entorno sin declarar no deja ni una línea en el registro"

    def test_no_avisa_cuando_esta_declarado(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Un aviso que sale siempre no avisa de nada."""
        from server.app.core.config import get_settings

        monkeypatch.setenv("ENVIRONMENT", "development")
        monkeypatch.setenv("JWT_SECRET_KEY", "clave-de-desarrollo")

        with caplog.at_level(logging.WARNING):
            get_settings()

        assert not [r for r in caplog.records if "ENVIRONMENT" in r.message]


class TestLaSemillaSigueCerradaFueraDeDesarrollo:
    """El gate de SEC.8.0 no cambia; lo que se comprueba es que sigue ahí y por qué importa."""

    async def test_no_siembra_con_el_entorno_de_la_imagen(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Por el registro y no por la salida estándar (issue #18).

        Esto leía `capsys`, y era correcto mientras el sembrado imprimía. No lo era que
        imprimiera: `main.py` llama a estas semillas **en el arranque del servidor**, así que en
        producción la decisión de no sembrar salía por la salida estándar sin nivel ni marca de
        tiempo. Es justo la línea que hay que poder encontrar cuando alguien pregunta por qué su
        instalación no tiene el SuperAdmin de desarrollo.

        Lo que el test comprueba no cambia: que el gate de SEC.8.0 sigue ahí y que **lo dice**.
        """
        from server.app.database.seeds import seed_multitenancy_defaults

        monkeypatch.setenv("ENVIRONMENT", "production")
        with caplog.at_level(logging.INFO):
            await seed_multitenancy_defaults()

        assert any(
            "se omiten los datos de desarrollo" in registro.message
            for registro in caplog.records
        ), "el gate no deja ni una línea en el registro: nadie puede saber por qué no sembró"
