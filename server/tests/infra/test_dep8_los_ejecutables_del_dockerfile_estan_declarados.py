"""Lo que un `CMD` invoca tiene que estar en el conjunto que la imagen instala.

**Esto nació de tumbar producción el 2026-09-15.** El `CMD` del `Dockerfile` es
`uvicorn server.app.main:app`, y `uvicorn` **no estaba declarado** en `pyproject.toml`: llegaba
de rebote por `browser-use → mcp → uvicorn`. Cuando DEP.1 mandó `browser-use` al extra
`agente-navegador`, `uvicorn` se fue con él del conjunto base, y como la imagen instala
`uv sync --frozen --no-dev` **sin extras**, el contenedor arrancó sin él y murió con:

    exec: "uvicorn": executable file not found in $PATH

Es el **cuarto** caso del defecto que DEP.1 destapó —un paquete usado y no declarado que llegaba
como transitiva de otro—, y el único que **ninguno de los guardarrailes que había podía ver**:

* `test_dep1_no_hay_dependencias_de_rebote.py` busca **imports** no declarados. `uvicorn` no se
  importa en ninguna parte del código: se invoca como ejecutable. Invisible.
* **CI no lo vio** porque `Lint & Test` instala con `--all-extras`, así que `uvicorn` estaba
  ahí. El conjunto que se despliega —base, sin extras— no lo probaba nadie **hasta IMG.1**, que
  añadió el job `imagen`: construye la imagen del despliegue y la arranca. Este fichero se
  queda porque contesta en milisegundos y sin Docker lo que allí cuesta una construcción
  entera, y porque señala el manifiesto en vez de un contenedor que murió.
* Y una comprobación de que la aplicación *importa* con el conjunto base tampoco lo habría
  cazado, porque importar funciona: lo que falta es el proceso que la arranca. Se comprobó ese
  día, pasó en verde, y producción seguía rota.

La lección de forma, que es la de siempre en este proyecto: **un guardarraíl sólo ve la pregunta
que le hicieron**. Aquí hacía falta una pregunta distinta —no «¿qué se importa?» sino «¿qué se
ejecuta?»— y por eso este fichero existe aparte en vez de ampliar el de DEP.1.
"""

from __future__ import annotations

import re
import shlex
import tomllib
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[3]

#: (Dockerfile, manifiesto cuyo conjunto base instala esa imagen).
#: El `frontend` no entra: su imagen sirve estáticos con nginx y no instala Python.
IMAGENES = [
    (RAIZ / "Dockerfile", RAIZ / "server" / "pyproject.toml"),
    (RAIZ / "mcp_server" / "Dockerfile", RAIZ / "mcp_server" / "pyproject.toml"),
]

#: Lo que trae la imagen base o se instala con `apt`, no el manifiesto de Python.
DEL_SISTEMA = {
    "sh", "bash", "curl", "python", "python3", "sleep", "exec", "sh -c",
    "nginx", "node", "npm",
}


def _ejecutables_de(dockerfile: Path) -> set[str]:
    """Los programas que `CMD`/`ENTRYPOINT` invocan, en forma exec (`["a", "b"]`) o shell."""
    encontrados: set[str] = set()
    for linea in dockerfile.read_text(encoding="utf-8").splitlines():
        limpia = linea.strip()
        m = re.match(r"^(CMD|ENTRYPOINT)\s+(.*)$", limpia, re.IGNORECASE)
        if not m:
            continue
        resto = m.group(2).strip()
        if resto.startswith("["):
            partes = re.findall(r'"([^"]*)"', resto)
        else:
            partes = shlex.split(resto)
        if partes:
            encontrados.add(partes[0])
    return encontrados


def _declarados_en_base(manifiesto: Path) -> set[str]:
    """Nombres normalizados de las dependencias BASE — sin extras y sin grupo dev.

    Sin extras a propósito: es exactamente lo que `uv sync --frozen --no-dev` mete en la imagen.
    Declarar el ejecutable en un extra no vale, porque el extra no se instala.
    """
    datos = tomllib.loads(manifiesto.read_text(encoding="utf-8"))
    brutos = datos.get("project", {}).get("dependencies", [])
    nombres = set()
    for bruto in brutos:
        nombre = re.split(r"[<>=!~\[;\s]", bruto.strip(), maxsplit=1)[0]
        if nombre:
            nombres.add(nombre.lower().replace("_", "-"))
    return nombres


@pytest.mark.parametrize(
    ("dockerfile", "manifiesto"), IMAGENES, ids=lambda p: p.parent.name or "raiz"
)
def test_lo_que_el_cmd_invoca_esta_en_las_dependencias_base(
    dockerfile: Path, manifiesto: Path
) -> None:
    if not dockerfile.is_file():
        pytest.skip(f"No hay {dockerfile.relative_to(RAIZ).as_posix()}")

    declarados = _declarados_en_base(manifiesto)
    faltan = [
        exe
        for exe in _ejecutables_de(dockerfile)
        if exe not in DEL_SISTEMA
        and exe.lower().replace("_", "-") not in declarados
        and not exe.startswith("/")
    ]

    assert not faltan, (
        f"{dockerfile.relative_to(RAIZ).as_posix()} invoca {faltan}, y no está en las "
        f"dependencias BASE de {manifiesto.relative_to(RAIZ).as_posix()}.\n\n"
        f"La imagen instala `uv sync --frozen --no-dev`, SIN extras. Si el ejecutable sólo llega "
        f"como transitiva de otro paquete —o está declarado en un extra— el contenedor arranca "
        f"sin él y muere con `executable file not found in $PATH`. Pasó el 2026-09-15 con "
        f"`uvicorn`, que venía por `browser-use → mcp` y se fue cuando DEP.1 movió `browser-use` "
        f"a un extra. CI no lo caza porque instala con `--all-extras`."
    )


def test_el_guardarrail_caza_el_caso_real() -> None:
    """El caso negativo, con el Dockerfile y el manifiesto que de verdad tumbaron producción."""
    declarados = {"fastapi", "pydantic"}  # sin uvicorn, como estaba el 2026-09-15
    ejecutables = {"uvicorn"}
    faltan = [e for e in ejecutables if e not in DEL_SISTEMA and e not in declarados]
    assert faltan == ["uvicorn"], (
        "Si esto no detecta el caso de uvicorn, el guardarraíl no sirve para lo que se escribió."
    )


def test_el_cmd_del_dockerfile_principal_se_lee_de_verdad() -> None:
    """Que el lector encuentre algo. Un parser que no casa nunca pasa en verde sin mirar."""
    ejecutables = _ejecutables_de(RAIZ / "Dockerfile")
    assert ejecutables, (
        "No se ha encontrado ningún `CMD`/`ENTRYPOINT` en el Dockerfile principal. O el fichero "
        "cambió de forma, o el lector dejó de casar — y entonces este guardarraíl pasaría en "
        "verde sin comprobar nada, que es la avería que este proyecto persigue."
    )
    assert "uvicorn" in ejecutables
