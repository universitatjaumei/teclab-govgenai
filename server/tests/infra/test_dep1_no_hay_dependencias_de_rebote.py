"""Lo que `server/app` importa está declarado en su manifiesto (DEP.1).

**Por qué existe, y cuánto costó no tenerlo.** DEP.1 sacó `browser-use` y `ragas` del conjunto
por defecto, y al hacerlo destapó **tres** paquetes que la aplicación usaba y nadie declaraba,
porque llegaban de rebote como transitivas suyas:

* `python-multipart` — lo exige FastAPI para `UploadFile`/`Form(`. Falla al *atender* la
  petición, no al importar: un 500 subiendo un PDF con el arranque en verde.
* `langchain` — lo necesita `observability.py`, que hace
  `from langfuse.langchain import CallbackHandler` en el nivel superior.
* `beautifulsoup4` — import de nivel superior en `html_analyzer_service.py` y en
  `normativa_spider.py`.

Y uno más que no rompía la importación pero sí una capacidad: `langchain-community`, que
sostiene el proveedor **Ollama** desde un import perezoso y sin guarda.

Los tres primeros se encontraron **de uno en uno, a golpe de suite roja**.

**De esos cuatro, este fichero caza dos, y conviene decirlo aquí para que nadie lo crea más
ancho de lo que es.** Comprobado mutando el manifiesto:

* `beautifulsoup4` ✓ y `langchain-community` ✓ — nuestro código los importa por su nombre.
* `langchain` ✗ — llega por `from langfuse.langchain import CallbackHandler`, y el módulo raíz
  que ve el análisis es `langfuse`, que sí está declarado.
* `python-multipart` ✗ — **nuestro código no lo importa nunca**: lo carga FastAPI por dentro
  cuando encuentra un `UploadFile`. Es invisible a cualquier análisis de imports, y por eso
  tiene su propio test en `test_dep1_lo_que_se_usa_esta_declarado.py`.

Lo que sí cazaría los cuatro es **importar la aplicación con sólo el conjunto base instalado**,
que es lo que hace el `Dockerfile` (`uv sync --frozen --no-dev`) y lo que NO hace la integración
continua, que instala con `--all-extras`. Un paso de humo en la imagen construida está
pendiente; hasta que exista, este fichero cubre la mitad y el otro test cubre el caso concreto.

**Se comprueba el MANIFIESTO y no el entorno**, y eso es una corrección de la primera versión:
miraba qué estaba instalado, y CI instala con `uv sync --locked --all-extras`, así que allí no
falta nada nunca y el test o era vacuo o —como pasó— afirmaba lo contrario de lo que el entorno
de CI tiene. Lo que se quiere fijar no depende de cómo se sincronizó esta máquina: **se depende
de lo que se importa**, y eso se lee en `pyproject.toml`.
"""

from __future__ import annotations

import ast
import sys
import tomllib
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
APP = RAIZ / "server" / "app"
MANIFIESTO = RAIZ / "server" / "pyproject.toml"

#: Nombres que no son paquetes de terceros.
PROPIOS = {"server", "app", "tests"}

#: Módulos cuyo nombre de import NO coincide con el de su distribución.
DISTRIBUCION = {
    "bs4": "beautifulsoup4",
    "yaml": "pyyaml",
    "jwt": "pyjwt",
    "dotenv": "python-dotenv",
    "docx": "python-docx",
    "fitz": "pymupdf",
    "onelogin": "python3-saml",
    "multipart": "python-multipart",
    "dateutil": "python-dateutil",
    "PIL": "pillow",
    "sklearn": "scikit-learn",
    "cv2": "opencv-python",
    "camelot": "camelot-py",
    "odf": "odfpy",
}

#: Transitivas que se importan y **no** se declaran, con el padre que las trae. Tolerarlas es
#: una decisión: son paquetes que ningún cambio razonable va a dejar de arrastrar, y declararlas
#: todas sería ruido sin dueño. Lo que NO se tolera es una transitiva cuyo padre se puede ir,
#: que es justo lo que pasó con `langchain` (por ragas) y `beautifulsoup4` (por browser-use).
TOLERADAS = {
    "sqlalchemy": "sqlmodel",
    "starlette": "fastapi",
    "httpx": "fastapi / langchain",
    "numpy": "pandas / matplotlib",
    "typing_extensions": "pydantic",
    "langchain_core": "langchain",
    "pydantic_core": "pydantic",
    "pydantic_settings": "langchain-community",
    "google": "google-genai / google-cloud-storage",
    "jinja2": "fastapi",
    "anyio": "starlette",
}


def _modulos_importados() -> set[str]:
    encontrados: set[str] = set()
    for py in APP.rglob("*.py"):
        try:
            arbol = ast.parse(py.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:  # pragma: no cover
            continue
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.Import):
                for alias in nodo.names:
                    encontrados.add(alias.name.split(".")[0])
            elif isinstance(nodo, ast.ImportFrom) and nodo.level == 0 and nodo.module:
                encontrados.add(nodo.module.split(".")[0])
    return {
        m
        for m in encontrados
        if m not in sys.stdlib_module_names and m not in PROPIOS and not m.startswith("_")
    }


def _declaradas() -> set[str]:
    """Todo lo que el manifiesto declara: base y extras. Un extra cuenta como declarado."""
    m = tomllib.loads(MANIFIESTO.read_text(encoding="utf-8"))
    listas = [m["project"]["dependencies"]]
    listas += list(m["project"].get("optional-dependencies", {}).values())
    nombres: set[str] = set()
    for lista in listas:
        for d in lista:
            n = d.split(";")[0].split("[")[0]
            for sep in (">=", "<=", "==", "~=", "!=", ">", "<"):
                n = n.split(sep)[0]
            nombres.add(n.strip().lower().replace("_", "-"))
    return nombres


def test_todo_lo_que_se_importa_esta_declarado() -> None:
    """Lo que no está declarado llega de rebote, y se rompe cuando su padre cambie."""
    declaradas = _declaradas()
    huerfanos = sorted(
        m
        for m in _modulos_importados()
        if m not in TOLERADAS
        and DISTRIBUCION.get(m, m).lower().replace("_", "-") not in declaradas
    )
    assert not huerfanos, (
        f"Estos módulos se importan y su paquete no está declarado en "
        f"`server/pyproject.toml`: {huerfanos}.\n"
        "O se declaran —en las dependencias base, o en un extra si la capacidad es opcional y "
        "su consumidor maneja la ausencia con un `try/except ImportError`— o se añaden a "
        "`TOLERADAS` con el padre que los trae, y eso es una decisión que hay que poder "
        "defender: sólo vale para transitivas que ningún cambio razonable va a dejar de "
        "arrastrar. `langchain` y `beautifulsoup4` parecían de ésas y no lo eran."
    )


def test_las_toleradas_siguen_sin_estar_declaradas() -> None:
    """Una tolerancia que ya no aplica tapa el próximo caso."""
    declaradas = _declaradas()
    sobran = sorted(
        m for m in TOLERADAS if DISTRIBUCION.get(m, m).lower().replace("_", "-") in declaradas
    )
    assert not sobran, (
        f"{sobran} están en TOLERADAS y además declaradas en el manifiesto. La entrada sobra: "
        f"quítala, o la lista irá acumulando excepciones que ya no excusan nada."
    )


def test_el_recorrido_mira_de_verdad() -> None:
    """Un árbol vacío pasaría los dos tests de arriba sin comprobar nada."""
    modulos = _modulos_importados()
    assert len(modulos) >= 30, (
        f"Sólo se han encontrado {len(modulos)} módulos de terceros importados por "
        f"`server/app`. Eran 44 al escribir esto. Un recorrido que deja de encontrar ficheros "
        f"pasa en verde sin mirar nada, y es la avería que este proyecto ya ha pagado."
    )
    assert len(_declaradas()) >= 30, (
        "El manifiesto declara menos de 30 paquetes: o se ha vaciado, o el análisis no lo está "
        "leyendo bien y el test compararía contra un conjunto vacío."
    )
