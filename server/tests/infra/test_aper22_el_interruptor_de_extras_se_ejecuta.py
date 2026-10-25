"""APER.22 — el interruptor de modelos locales se comprueba **ejecutándolo**.

**El defecto.** `construir_si_falta` recibía los argumentos de construcción como **una cadena** y
los soltaba sin comillas para que el shell los partiera:

    construir_si_falta app . Dockerfile "$SHA$SUFIJO" "--build-arg EXTRAS_APP=$EXTRAS_APP"
    ...
    docker build $argumentos -t ...

Con el interruptor puesto, `EXTRAS_APP` vale `--extra local-models`, que **lleva un espacio
dentro**. El shell parte por espacios sin saber cuáles son separadores y cuáles no, así que
`docker build` recibía `--build-arg`, `EXTRAS_APP=--extra` y un `local-models` suelto: el valor
llegaba cortado por la mitad y sobraba un argumento posicional, o sea dos contextos de
construcción. `docker build` falla ahí mismo. **La función que APER.18 añadió para poder
desplegar con modelos locales no podía desplegar con modelos locales.**

**Por qué no lo cazó nadie.** Los seis guardarraíles de APER.18 comprueban que ciertas cadenas
**estén** en los ficheros: que el `Dockerfile` declare `ARG EXTRAS_APP`, que el workflow diga
`--build-arg`, que la etiqueta lleve `SUFIJO`. Todas ciertas, y todas verdes mientras el comando
estaba roto, porque ninguna **ejecuta** nada. Es el defecto que este proyecto ya tiene nombrado:
un guardarraíl que no mira nada pasa en verde.

Lo encontró la revisión automática de la PR #50, leyendo el diff.

**Qué hace este fichero, y por eso es distinto.** Saca del `deploy.yml` el bloque real que
construye las imágenes, le sustituye las expresiones de GitHub, y lo **ejecuta** con un `docker`
y un `gcloud` de mentira que apuntan qué argumentos reciben. Después mira la lista de argumentos,
que es el sitio donde el defecto vivía.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[3]
DEPLOY = RAIZ / ".github" / "workflows" / "deploy.yml"

#: Lo que el `docker` de mentira escribe por cada llamada: la lista de argumentos, en JSON.
STUB_DOCKER = """#!/bin/sh
python -c "import json,sys; print(json.dumps(sys.argv[1:]))" "$@" >> "$REGISTRO_DOCKER"
exit 0
"""

#: `gcloud artifacts docker images describe` tiene que fallar para que sí se construya.
STUB_GCLOUD = """#!/bin/sh
exit 1
"""


def _bloque_de_construccion() -> str:
    """El paso que construye, buscado por lo que hace y no por su nombre."""
    datos = yaml.safe_load(DEPLOY.read_text(encoding="utf-8"))
    for cuerpo in datos["jobs"].values():
        for paso in cuerpo.get("steps", []):
            if "docker build" in (paso.get("run") or ""):
                return paso["run"]
    raise AssertionError("no encuentro el paso que construye las imágenes")


def _ejecutable(guion: str, destino: Path) -> None:
    destino.write_text(guion, encoding="utf-8", newline="\n")
    destino.chmod(0o755)


def _construir(tmp_path: Path, extras: str) -> list[list[str]]:
    """Ejecuta el bloque real con `GOVGENAI_EXTRAS_APP=extras` y devuelve las llamadas a docker.

    Las expresiones `${{ ... }}` se sustituyen: la del interruptor por el valor que se prueba, y
    las demás por un relleno, porque lo que se mide aquí es cómo se parten los argumentos.
    """
    if shutil.which("bash") is None:  # pragma: no cover - depende de la máquina
        pytest.skip("hace falta bash; en Windows, Git Bash")

    bloque = _bloque_de_construccion()
    bloque = bloque.replace("${{ vars.GOVGENAI_EXTRAS_APP }}", extras)
    bloque = re.sub(r"\$\{\{[^}]*\}\}", "relleno", bloque)

    binarios = tmp_path / "bin"
    binarios.mkdir()
    _ejecutable(STUB_DOCKER, binarios / "docker")
    _ejecutable(STUB_GCLOUD, binarios / "gcloud")

    # El bloque se ejecuta con `cwd=tmp_path`, y desde VER lee el fichero `VERSION` de la raíz
    # para estamparlo en la imagen. Sin copiarlo aquí el bloque muere en esa línea con
    # `set -euo pipefail` y los seis tests de este fichero se caen por una causa que no es la
    # suya. Se copia **el real** y no un valor inventado: así el test también comprueba que lo
    # que llega al `--build-arg` es lo que dice la fuente única.
    (tmp_path / "VERSION").write_text(
        (RAIZ / "VERSION").read_text(encoding="utf-8"), encoding="utf-8"
    )

    registro = tmp_path / "docker.jsonl"
    registro.touch()
    guion = tmp_path / "bloque.sh"
    guion.write_text(bloque, encoding="utf-8", newline="\n")

    entorno = dict(os.environ)
    entorno["PATH"] = f"{binarios.as_posix()}{os.pathsep}{entorno['PATH']}"
    entorno["REGISTRO_DOCKER"] = registro.as_posix()
    entorno["GITHUB_OUTPUT"] = (tmp_path / "salida.txt").as_posix()

    resultado = subprocess.run(
        ["bash", guion.as_posix()],
        capture_output=True, text=True, env=entorno, cwd=tmp_path, timeout=120,
        check=False,
    )
    assert resultado.returncode == 0, (
        f"el bloque de construcción del workflow falló con extras=«{extras}»:\n"
        f"{resultado.stdout}\n{resultado.stderr}"
    )
    return [
        json.loads(linea)
        for linea in registro.read_text(encoding="utf-8").splitlines()
        if linea.strip()
    ]


def _build_de_la_app(llamadas: list[list[str]]) -> list[str]:
    for argv in llamadas:
        if argv and argv[0] == "build" and any("/app:" in a for a in argv):
            return argv
    raise AssertionError(f"ninguna llamada construye la imagen del servidor: {llamadas}")


class TestConElInterruptorPuesto:
    """El caso que estaba roto."""

    @staticmethod
    @pytest.fixture(scope="class")
    def argv(tmp_path_factory: pytest.TempPathFactory) -> list[str]:
        return _build_de_la_app(
            _construir(tmp_path_factory.mktemp("con"), "local-models")
        )

    def test_el_valor_del_build_arg_llega_entero(self, argv: list[str]) -> None:
        """Un solo argumento, con el espacio dentro: es el corazón del defecto."""
        assert "--build-arg" in argv, f"no se pasa `--build-arg`: {argv}"
        valor = argv[argv.index("--build-arg") + 1]
        assert valor == "EXTRAS_APP=--extra local-models", (
            f"`--build-arg` recibe «{valor}» en vez de «EXTRAS_APP=--extra local-models». Si "
            f"acaba en `--extra`, el valor se ha partido por el espacio y `local-models` anda "
            f"suelto por la lista: {argv}"
        )

    def test_la_version_llega_estampada_a_la_imagen(self, argv: list[str]) -> None:
        """Y **ejecutándolo**, que es distinto de que el YAML contenga la cadena.

        `test_ver_la_version_es_una_sola_y_se_puede_preguntar.py` comprueba que `deploy.yml`
        menciona `GOVGENAI_VERSION=`, y eso es un `grep`: pasó en verde mientras este bloque
        moría en la línea que lee el fichero. Un guardarraíl que lee texto no puede decir si el
        texto se ejecuta.
        """
        esperado = f"GOVGENAI_VERSION={(RAIZ / 'VERSION').read_text(encoding='utf-8').strip()}"
        assert esperado in argv, (
            f"la imagen del servidor no recibe «{esperado}», así que se construiría con el valor "
            f"por defecto y **mentiría sobre su versión**: {argv}"
        )

    def test_no_queda_ningun_argumento_suelto(self, argv: list[str]) -> None:
        """`docker build` admite **un** contexto; dos es un error de uso."""
        posicionales = []
        saltar = False
        for pieza in argv[1:]:
            if saltar:
                saltar = False
                continue
            if pieza in ("--build-arg", "-t", "-f"):
                saltar = True
                continue
            if pieza.startswith("-"):
                continue
            posicionales.append(pieza)
        assert posicionales == ["."], (
            f"`docker build` recibe {len(posicionales)} contextos, {posicionales}, y admite "
            f"uno. Sobra lo que se partió de un valor con espacios: {argv}"
        )

    def test_la_etiqueta_lleva_la_variante(self, argv: list[str]) -> None:
        etiqueta = argv[argv.index("-t") + 1]
        assert etiqueta.endswith("-local-models"), (
            f"la etiqueta «{etiqueta}» no distingue la variante, así que un redespliegue del "
            "mismo commit se llevaría la imagen sin modelos sin decir nada."
        )


class TestSinInterruptor:
    """El despliegue estándar, que es el que corre hoy y no puede cambiar."""

    @staticmethod
    @pytest.fixture(scope="class")
    def llamadas(tmp_path_factory: pytest.TempPathFactory) -> list[list[str]]:
        return _construir(tmp_path_factory.mktemp("sin"), "")

    def test_se_construyen_las_cuatro_imagenes(self, llamadas: list[list[str]]) -> None:
        construcciones = [a for a in llamadas if a and a[0] == "build"]
        assert len(construcciones) == 4, (
            f"se construyen {len(construcciones)} imágenes y son cuatro: servidor, frontend, "
            f"sandbox y mcp. {construcciones}"
        )

    def test_la_app_no_recibe_extras(self, llamadas: list[list[str]]) -> None:
        argv = _build_de_la_app(llamadas)
        if "--build-arg" in argv:
            valor = argv[argv.index("--build-arg") + 1]
            assert valor == "EXTRAS_APP=", (
                f"sin interruptor el build-arg debería ir vacío y vale «{valor}»: el despliegue "
                "estándar no puede engordar por una variable que nadie ha tocado."
            )

    def test_la_etiqueta_no_lleva_sufijo(self, llamadas: list[list[str]]) -> None:
        etiqueta = _build_de_la_app(llamadas)[
            _build_de_la_app(llamadas).index("-t") + 1
        ]
        assert not etiqueta.endswith("-local-models"), (
            f"la etiqueta «{etiqueta}» marca una variante que no se ha pedido."
        )
