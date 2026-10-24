"""Lo que los manifiestos declaran de Python es lo que de verdad se ejecuta (issue #19).

**El desajuste.** La suite corre en 3.13, las cuatro imágenes se construyen con `python:3.13-slim`
y CI usa 3.13. Pero `mcp_server` y `shared` declaraban `>=3.11` y `script_sandbox` `>=3.12`: una
compatibilidad con versiones en las que nadie ejecuta el proyecto.

**El riesgo es el inverso del que parece.** No rompe nada hoy; lo que rompe es que alguien lo
instale en 3.11 confiando en la declaración y se encuentre sintaxis o dependencias que allí no
existen. Con el repositorio abierto eso deja de ser hipotético.

**La cifra de la issue estaba desactualizada**, y es la comprobación que conviene hacer antes de
empezar: decía «los cinco `pyproject`» con `>=3.11`, y son **cuatro** —no hay manifiesto en la
raíz— y `server/` ya estaba en `>=3.13,<3.14`. Se mide, no se cuenta de memoria.

**Por qué también un techo y no sólo un suelo.** `server/` ya lo tenía, y por un motivo concreto
que este repositorio se encontró: sin fijar la versión, `uv` recrea el entorno en 3.14 y arrastra
resoluciones distintas. Un suelo solo declara «de aquí en adelante», que es justo lo que no se ha
probado.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[3]

#: Los proyectos de verdad. Los de `server/tests/fixtures/` quedan fuera: son material de test
#: —paquetes de mentira que se instalan para comprobar el cargador de funciones—, no cosas que
#: nadie ejecute.
PROYECTOS = (
    "server",
    "mcp_server",
    "services/script_sandbox",
)

#: La versión en la que esto se ejecuta de verdad: las cuatro imágenes y CI.
_ESPERADO = ">=3.13,<3.14"

_REQUIERE = re.compile(r'^requires-python\s*=\s*"([^"]+)"', re.MULTILINE)
_IMAGEN = re.compile(r"^FROM python:(\d+\.\d+)", re.MULTILINE)


def _declarado(proyecto: str) -> str:
    texto = (RAIZ / proyecto / "pyproject.toml").read_text(encoding="utf-8")
    encontrado = _REQUIERE.search(texto)
    assert encontrado, f"{proyecto}/pyproject.toml no declara `requires-python`"
    return encontrado.group(1)


def test_el_medidor_encuentra_los_cuatro() -> None:
    """Un guardarraíl que no encuentra manifiestos pasaría en verde sin comprobar nada."""
    for proyecto in PROYECTOS:
        assert (RAIZ / proyecto / "pyproject.toml").is_file(), f"no existe {proyecto}"


@pytest.mark.parametrize("proyecto", PROYECTOS)
def test_declara_la_version_que_se_ejecuta(proyecto: str) -> None:
    assert _declarado(proyecto) == _ESPERADO, (
        f"{proyecto} declara «{_declarado(proyecto)}» y todo se ejecuta en 3.13. Declarar de "
        "más invita a instalarlo en una versión que nadie ha probado."
    )


def test_las_imagenes_construyen_esa_misma_version() -> None:
    """El otro lado del cruce: de nada sirve declarar 3.13 si la imagen trae otra cosa."""
    imagenes = {
        "Dockerfile": RAIZ / "Dockerfile",
        "mcp_server": RAIZ / "mcp_server" / "Dockerfile",
        "script_sandbox": RAIZ / "services" / "script_sandbox" / "Dockerfile",
    }
    discrepan = []
    for nombre, ruta in imagenes.items():
        versiones = set(_IMAGEN.findall(ruta.read_text(encoding="utf-8")))
        if versiones != {"3.13"}:
            discrepan.append(f"{nombre} construye con {sorted(versiones)}")
    assert discrepan == [], (
        "hay imágenes que no construyen con la versión declarada:\n  " + "\n  ".join(discrepan)
    )


def test_todos_los_proyectos_tienen_su_lock() -> None:
    """Estrechar `requires-python` obliga a re-resolver, y CI instala con `--locked`.

    Sin el lock al día, el fallo no aparece aquí sino en el *push*, que es donde más caro sale.
    """
    faltan = [p for p in PROYECTOS if not (RAIZ / p / "uv.lock").is_file()]
    assert faltan == [], f"proyectos sin `uv.lock`: {faltan}"


def _admite(especificador: str, version: str) -> bool:
    from packaging.specifiers import SpecifierSet

    return SpecifierSet(especificador).contains(version)


@pytest.mark.parametrize("proyecto", PROYECTOS)
def test_el_lock_admite_exactamente_la_misma_version(proyecto: str) -> None:
    """Y el lock lo dice también: es lo que demuestra que se re-resolvió tras estrecharlo.

    **Se compara el significado y no la cadena.** `uv` normaliza `>=3.13,<3.14` a `==3.13.*` al
    escribir el lock, así que un test que comparase texto pondría rojo un lock correcto — y eso
    fue lo que hizo su primera versión.
    """
    lock = (RAIZ / proyecto / "uv.lock").read_text(encoding="utf-8")
    encontrado = re.search(r'requires-python\s*=\s*"([^"]+)"', lock)
    assert encontrado, f"{proyecto}/uv.lock no declara `requires-python`"
    escrito = encontrado.group(1)

    for version, admitida in (("3.12.0", False), ("3.13.0", True), ("3.13.9", True), ("3.14.0", False)):
        assert _admite(escrito, version) is admitida, (
            f"{proyecto}/uv.lock dice «{escrito}», que {'admite' if not admitida else 'rechaza'} "
            f"Python {version}. El manifiesto dice «{_declarado(proyecto)}»: el lock no se ha "
            "regenerado, y `uv sync --locked` de CI se pondrá rojo."
        )
