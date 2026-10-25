"""APER.20 — al subir `torch`, `setuptools` sube con él y su aceptación se retira.

**Las tres cosas van juntas, y por eso van en un solo test.** APER.5 aceptó el aviso de
`setuptools` (PYSEC-2026-3447) con una razón medida: la corrección está en la 83, pero `torch`
2.11.0 declaraba `setuptools<82`, así que subirla obligaba a subir la dependencia más pesada del
proyecto para cerrar un aviso que no alcanza a este código. Se dejó por escrito la **condición de
salida**: «cuando torch suba por cualquier otra razón, `setuptools` sube con él».

Ese día llegó: `torch` tiene su propio aviso (GHSA-rrmf-rvhw-rf47, corregido en 2.13.0) y
**2.13.0 declara `setuptools>=77.0.3`, sin tope superior** — comprobado contra PyPI antes de
tocar el lock. Así que la misma subida cierra tres cosas:

1. el aviso de `torch`;
2. el de `setuptools`, que deja de estar bloqueado;
3. y **la aceptación**, que se retira en vez de renovarse en diciembre.

**Lo que este fichero vigila es el 3.** Que la aceptación desaparezca es lo fácil de olvidar: una
aceptación caducada vuelve a bloquear y se renueva sin mirar, y así una decisión con fecha se
convierte en una exclusión permanente con otro nombre. Lo mismo con la exclusión de
`dependabot.yml`, que se puso «hasta que torch levante el techo».

**Y una corrección a lo que yo mismo escribí aquí primero**: no es verdad que «esto sólo toca un
extra». `setuptools` llega al árbol base por `spacy` y `thinc`, así que el conjunto desplegado
cambió en una línea —`setuptools` 81.0.0 → 84.0.0— y era la del aviso. `torch` sí se queda fuera
del despliegue. Está medido en `TestQueLLegaAlDespliegueYQueNo`.

Lo que **no** se movió, y era el riesgo real de saltar `sentence-transformers` de la 5 a la 6: el
vector de `bge-m3` sale **idéntico bit a bit** —1024 de 1024 componentes, diferencia máxima 0—
con la pila nueva. Se midió encodando las mismas frases antes y después, porque un cambio ahí
dejaría los embeddings ya indexados sin poder compararse con los nuevos, y eso ningún registro de
cambios lo dice.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[3]
LOCK = RAIZ / "server" / "uv.lock"
ACEPTADOS = RAIZ / "avisos_aceptados.toml"
DEPENDABOT = RAIZ / ".github" / "dependabot.yml"


def _version_en_el_lock(paquete: str) -> str | None:
    """La versión de un paquete en el lock del servidor, o `None` si no está."""
    texto = LOCK.read_text(encoding="utf-8")
    m = re.search(
        rf'^name = "{re.escape(paquete)}"\nversion = "([^"]+)"', texto, re.MULTILINE
    )
    return m.group(1) if m else None


def _tupla(version: str) -> tuple[int, ...]:
    """`2.13.0+cpu` → `(2, 13, 0)`. Comparar versiones como texto daría 2.9 > 2.13."""
    limpia = version.split("+")[0]
    return tuple(int(p) for p in re.findall(r"\d+", limpia)[:3])


class TestElTechoEstaLevantado:

    def test_torch_esta_al_menos_en_2_13(self) -> None:
        version = _version_en_el_lock("torch")
        assert version is not None, "`torch` ha desaparecido del lock: eso no es esta subida"
        assert _tupla(version) >= (2, 13, 0), (
            f"`torch` está en {version}. Hasta la 2.13.0 declaraba `setuptools<82`, que es lo "
            "que mantenía abierta la aceptación de APER.5."
        )

    def test_setuptools_esta_al_menos_en_83(self) -> None:
        version = _version_en_el_lock("setuptools")
        assert version is not None, "`setuptools` ha desaparecido del lock"
        assert _tupla(version) >= (83, 0, 0), (
            f"`setuptools` está en {version}, y la corrección de PYSEC-2026-3447 es la 83.0.0. "
            "Con torch ≥ 2.13 ya no hay techo que lo impida."
        )

    def test_transformers_esta_al_menos_en_5_10(self) -> None:
        version = _version_en_el_lock("transformers")
        assert version is not None, "`transformers` ha desaparecido del lock"
        assert _tupla(version) >= (5, 10, 0), (
            f"`transformers` está en {version}; su aviso se corrige en la 5.10.0."
        )


class TestLaAceptacionSeRetira:
    """Lo que de verdad vigila este fichero: que una decisión con fecha no sobreviva a su razón."""

    # `staticmethod` y no método de instancia: `pytest` 9.1 deprecó las *fixtures* de ámbito
    # de clase declaradas como método de instancia, y además ésta no usa `self`.
    @staticmethod
    @pytest.fixture(scope="class")
    def aceptados() -> list[dict]:
        if not ACEPTADOS.is_file():
            return []
        return tomllib.loads(ACEPTADOS.read_text(encoding="utf-8")).get("aviso", [])

    def test_setuptools_ya_no_esta_aceptado(self, aceptados: list[dict]) -> None:
        de_setuptools = [a for a in aceptados if a.get("paquete") == "setuptools"]
        assert not de_setuptools, (
            "`setuptools` sigue en `avisos_aceptados.toml`. Su aviso ya se puede corregir "
            "subiendo el paquete, así que la aceptación no describe la realidad: renovarla en "
            "diciembre convertiría una decisión con fecha en una exclusión permanente."
        )

    def test_la_exclusion_de_dependabot_ya_no_esta(self) -> None:
        """Se puso «hasta que torch levante el techo», y lo levantó."""
        texto = DEPENDABOT.read_text(encoding="utf-8")
        activas = [
            linea for linea in texto.splitlines()
            if "setuptools" in linea and not linea.lstrip().startswith("#")
        ]
        assert not activas, (
            f"Dependabot sigue ignorando `setuptools`: {activas}. La exclusión existía para no "
            "recibir cada semana una PR que no se podía aplicar; ahora sí se puede."
        )


class TestQueLLegaAlDespliegueYQueNo:
    """Lo que la medición corrigió de lo que yo había supuesto.

    Al escribir esto dije que la subida era «de un extra, y el despliegue estándar no la nota».
    **Falso, y justo al revés de lo que importa**: `setuptools` llega al árbol base por `spacy` y
    `thinc`; sólo `torch` le ponía el techo. El conjunto desplegado cambió en **una** línea,
    `setuptools` 81.0.0 → 84.0.0, y ésa era precisamente la del aviso. `torch` sí se queda fuera.
    """

    def test_la_imagen_no_instala_extras(self) -> None:
        """`torch` no entra en el despliegue por mucho que el lock lo describa.

        Se comprueba sobre el `Dockerfile`, que es lo que decide qué se instala. Desde APER.18 el
        extra se elige al desplegar con `EXTRAS_APP`, así que lo que se exige es que el valor
        **por defecto** siga siendo vacío: quien quiera modelos locales lo pide.
        """
        dockerfile = (RAIZ / "Dockerfile").read_text(encoding="utf-8")
        sync = next(
            linea for linea in dockerfile.splitlines() if linea.startswith("RUN uv sync")
        )
        assert "--all-extras" not in sync, (
            f"El `uv sync` de la imagen instala extras a pelo: «{sync}». Con `torch` dentro la "
            "imagen pasa de 1,84 a 3,14 GB en disco y de 421 a 686 MB de capas que transferir "
            "—medido el 2026-09-19 construyendo las dos—, así que hace falta una VM mayor. Eso "
            "se decide al desplegar con `EXTRAS_APP`, no aquí."
        )
        assert "--extra" not in sync, (
            f"El `uv sync` de la imagen instala extras a pelo: «{sync}». Con `torch` dentro la "
            "imagen pasa de 1,84 a 3,14 GB en disco y de 421 a 686 MB de capas que transferir "
            "—medido el 2026-09-19 construyendo las dos—, así que hace falta una VM mayor. Eso "
            "se decide al desplegar con `EXTRAS_APP`, no aquí."
        )
        assert 'ARG EXTRAS_APP=""' in dockerfile, (
            "`EXTRAS_APP` ha dejado de tener el vacío por defecto. Ese vacío es lo que mantiene "
            "el despliegue estándar sin la pila de modelos locales."
        )

    def test_setuptools_si_llega_al_conjunto_desplegado(self) -> None:
        """Y por eso su aviso no era teórico.

        Si algún día `setuptools` deja de estar en el árbol base, este test se pone rojo y hay
        que releer la historia: querrá decir que `spacy` dejó de pedirlo, y entonces el aviso que
        APER.20 cerró era menos grave de lo que se dijo.
        """
        lock = LOCK.read_text(encoding="utf-8")
        pedido_por_spacy = 'name = "spacy"' in lock and 'name = "thinc"' in lock
        assert pedido_por_spacy, (
            "`spacy`/`thinc` ya no están en el lock. Eran la vía por la que `setuptools` llegaba "
            "al despliegue estándar, que es lo que hacía que su aviso contara."
        )
