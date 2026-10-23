"""Issue #42 — toda variable de entorno que lee el código está declarada en algún inventario.

Hay dos inventarios y cada uno responde a una pregunta distinta:

* **`.env.example`** dice **qué se puede configurar** y qué pasa si se deja en blanco. Es lo que
  lee quien instala esto por primera vez.
* **`scripts/lib/secretos.tsv`** dice **qué hay que crear y rotar** en el despliegue. Lo leen
  `gcp_create_secrets.sh` y `vm_fetch_secrets.sh`.

Una variable que el código lee y que no está en ninguno de los dos **no se crea al aprovisionar
y no se documenta a quien instala**. No es una brecha: es deriva entre el inventario y el código,
que es el tipo de cosa que la próxima vez sí abre algo.

**El caso que lo destapó.** `DELEGATED_ACTOR_SECRET` estaba en `.env.example` pero **no** en
`secretos.tsv`, y `delegated_actor.py` **falla cerrado** si falta. O sea que la actuación «en
nombre de» —que usan seis módulos— estaba muerta en el despliegue y el síntoma sólo aparecía
cuando alguien la usara. Fallar cerrado es lo correcto; lo que no lo es, es que nadie se entere.

**Y al medirlo salieron siete sin declarar, no seis.** La issue listaba `LOG_LEVEL`,
`DEV_ADMIN_EMAIL`, `DEV_ADMIN_PASSWORD`, `CRAWLER_CONTACT`, `SUPERADMIN_EMAIL` y
`SUPERADMIN_PASSWORD`; faltaba `SUPERADMIN_NAME`, que se lee en el mismo sitio que las otras dos.
De regalo, el docstring de `main.py` afirmaba que `LOG_LEVEL` «ya está en `.env.example`» y no
estaba: una frase que se escribió a la vez que la intención y nadie volvió a comprobar.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
APP = RAIZ / "server" / "app"
ENV_EJEMPLO = RAIZ / ".env.example"
SECRETOS = RAIZ / "scripts" / "lib" / "secretos.tsv"

_DECLARACION = re.compile(r"^#?\s*([A-Z][A-Z0-9_]*)=", re.MULTILINE)
#: Un nombre de variable de entorno tal y como se escriben aquí.
_NOMBRE = re.compile(r"^[A-Z][A-Z0-9_]*$")

#: Variables del **sistema operativo** que el sandbox reenvía al subproceso, no configuración de
#: nadie. `sandbox_client.py` construye el entorno del intérprete **por lista blanca** (SEC.9.6):
#: éstas son lo poco que hace falta para arrancar, y todo lo demás —secretos incluidos— se queda
#: fuera. Declararlas en `.env.example` sería pedirle a quien instala que configure el `PATH`.
#:
#: Se listan aquí una a una, y no se excluye el fichero entero, porque el día que ese módulo lea
#: una variable **suya** tiene que aparecer.
DEL_SISTEMA = frozenset({
    "PATH", "SYSTEMROOT", "TEMP", "TMP", "LANG", "LC_ALL", "PYTHONIOENCODING",
    "MPLCONFIGDIR", "HOME", "USERPROFILE", "XDG_CACHE_HOME",
})


def _es_lectura_de_entorno(nodo: ast.AST) -> bool:
    """`os.getenv(...)`, `os.environ.get(...)` o `os.environ[...]`."""
    if isinstance(nodo, ast.Subscript):
        valor = nodo.value
        return (
            isinstance(valor, ast.Attribute)
            and valor.attr == "environ"
            and isinstance(valor.value, ast.Name)
            and valor.value.id == "os"
        )
    if not isinstance(nodo, ast.Call):
        return False
    funcion = nodo.func
    if isinstance(funcion, ast.Attribute) and funcion.attr == "getenv":
        return isinstance(funcion.value, ast.Name) and funcion.value.id == "os"
    if isinstance(funcion, ast.Attribute) and funcion.attr == "get":
        interior = funcion.value
        return (
            isinstance(interior, ast.Attribute)
            and interior.attr == "environ"
            and isinstance(interior.value, ast.Name)
            and interior.value.id == "os"
        )
    return False


def _argumento(nodo: ast.AST) -> ast.AST | None:
    if isinstance(nodo, ast.Subscript):
        return nodo.slice
    if isinstance(nodo, ast.Call) and nodo.args:
        return nodo.args[0]
    return None


#: Una asignación cuyo nombre habla de variables de entorno. Acotar así es lo que separa
#: recoger los nombres buenos de barrer **todas** las cadenas en mayúsculas del módulo: eso
#: último señalaba `MANIFEST_SIGNATURE` y `RATE_LIMITED`, que son un campo y un código de error.
_ASIGNACION_DE_ENTORNO = re.compile(r"(?i)(env|var)")


def _constantes_escalares(arbol: ast.Module) -> dict[str, str]:
    """`{nombre_de_la_constante: valor}` para las cadenas asignadas a nivel de módulo.

    Es lo que permite resolver `citations.py` **exactamente**: guarda
    `BASE_DEL_SITIO = "CORPUS_SITE_BASE_URL"` y luego lee con esa constante.
    """
    constantes: dict[str, str] = {}
    # `ast.walk` y no sólo `arbol.body`: `manifest_signature_service.py` lo guarda en un
    # **atributo de clase**, que es igual de resoluble y estaba un nivel más adentro.
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.Assign) or len(nodo.targets) != 1:
            continue
        destino = nodo.targets[0]
        if isinstance(destino, ast.Name) and isinstance(nodo.value, ast.Constant):
            if isinstance(nodo.value.value, str):
                constantes[destino.id] = nodo.value.value
    return constantes


def _resuelve(nodo: ast.AST | None, constantes: dict[str, str]) -> str | None:
    """El valor de `NOMBRE` o de `self.NOMBRE` si es una constante declarada."""
    if isinstance(nodo, ast.Name):
        return constantes.get(nodo.id)
    if isinstance(nodo, ast.Attribute):
        return constantes.get(nodo.attr)
    return None


def _colecciones_de_nombres(arbol: ast.Module) -> set[str]:
    """Los nombres de una colección de literales **asignada a algo que habla de entorno**.

    Las dos formas que existen aquí: la tupla `VARIABLES` de `sync.py` y el diccionario
    `env_mapping` de `api_key_service.py`. Sin esto, esas variables no las veía nadie: añadir una
    a la tupla sin declararla en ningún inventario pasaba en verde.
    """
    nombres: set[str] = set()
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, (ast.Assign, ast.AnnAssign)):
            continue
        destinos = nodo.targets if isinstance(nodo, ast.Assign) else [nodo.target]
        etiquetas = [d.id for d in destinos if isinstance(d, ast.Name)]
        if not any(_ASIGNACION_DE_ENTORNO.search(e) for e in etiquetas):
            continue
        valor = nodo.value
        if isinstance(valor, (ast.Tuple, ast.List, ast.Set)):
            elementos = list(valor.elts)
        elif isinstance(valor, ast.Dict):
            elementos = [v for v in valor.values if v is not None]
        else:
            continue
        for elemento in elementos:
            if isinstance(elemento, ast.Constant) and isinstance(elemento.value, str):
                if _NOMBRE.match(elemento.value):
                    nombres.add(elemento.value)
    return nombres


def _leidas_por_el_codigo() -> dict[str, str]:
    """`{VARIABLE: primer fichero donde se lee}`, con las dos formas de leer.

    **Se lee el árbol sintáctico y no una expresión regular** (revisión de la PR #73). La
    versión anterior sólo reconocía el nombre escrito como literal dentro de la llamada, y
    `sync.py` lo hace al revés: `os.environ.get(nombre)` iterando una tupla estática. Añadir una
    variable a esa tupla sin declararla en ningún inventario pasaba en verde, que es justo lo
    que este fichero existe para impedir.
    """
    encontradas: dict[str, str] = {}
    for fichero in APP.rglob("*.py"):
        if "__pycache__" in fichero.parts:
            continue
        try:
            arbol = ast.parse(fichero.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:  # pragma: no cover - no debería haberlos
            continue

        constantes = _constantes_escalares(arbol)
        dinamica = False
        for nodo in ast.walk(arbol):
            if not _es_lectura_de_entorno(nodo):
                continue
            argumento = _argumento(nodo)
            if isinstance(argumento, ast.Constant) and isinstance(argumento.value, str):
                encontradas.setdefault(argumento.value, str(fichero.relative_to(RAIZ)))
            elif _resuelve(argumento, constantes) is not None:
                # `os.getenv(BASE_DEL_SITIO)` o `os.environ.get(self.SIGNING_KEY_ENV)`: la
                # constante está declarada y se resuelve sin adivinar nada.
                encontradas.setdefault(
                    _resuelve(argumento, constantes), str(fichero.relative_to(RAIZ))
                )
            else:
                dinamica = True

        if dinamica:
            for nombre in _colecciones_de_nombres(arbol):
                encontradas.setdefault(nombre, str(fichero.relative_to(RAIZ)))
    return encontradas


def _modulos_con_lectura_dinamica() -> dict[str, bool]:
    """`{fichero: tiene una colección de nombres}` para los que leen sin literal."""
    resultado: dict[str, bool] = {}
    for fichero in APP.rglob("*.py"):
        if "__pycache__" in fichero.parts:
            continue
        try:
            arbol = ast.parse(fichero.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:  # pragma: no cover
            continue
        constantes = _constantes_escalares(arbol)
        for nodo in ast.walk(arbol):
            if not _es_lectura_de_entorno(nodo):
                continue
            argumento = _argumento(nodo)
            if isinstance(argumento, ast.Constant) and isinstance(argumento.value, str):
                continue
            if _resuelve(argumento, constantes) is not None:
                continue
            resultado[str(fichero.relative_to(RAIZ))] = bool(_colecciones_de_nombres(arbol))
            break
    return resultado


def _declaradas_en_el_ejemplo() -> set[str]:
    return set(_DECLARACION.findall(ENV_EJEMPLO.read_text(encoding="utf-8")))


def _declaradas_como_secreto() -> set[str]:
    nombres = set()
    for linea in SECRETOS.read_text(encoding="utf-8").splitlines():
        if linea.startswith("#") or "|" not in linea:
            continue
        variable = linea.split("|")[1]
        nombres.add(variable.removeprefix("FICHERO:"))
    return nombres


def test_el_codigo_no_lee_nada_que_no_este_declarado() -> None:
    leidas = _leidas_por_el_codigo()
    declaradas = _declaradas_en_el_ejemplo() | _declaradas_como_secreto() | DEL_SISTEMA
    huerfanas = sorted(n for n in leidas if n not in declaradas)

    assert not huerfanas, (
        "El código lee variables que no declara ningún inventario:\n  - "
        + "\n  - ".join(f"{n}  (en {leidas[n]})" for n in huerfanas)
        + "\n\nUna variable que no está en `.env.example` no se la documenta a quien instala, y "
        "una que no está en `secretos.tsv` no se crea ni se rota al aprovisionar."
    )


def test_el_secreto_de_la_delegacion_se_crea_al_aprovisionar() -> None:
    """El caso concreto, con nombre, porque su síntoma es el peor: silencio.

    `delegated_actor.py` rechaza la cabecera si el secreto falta, que es lo correcto. Pero si el
    despliegue nunca lo crea, la funcionalidad está muerta y sólo se nota cuando alguien intenta
    usarla — y entonces parece un fallo de quien la usa.
    """
    assert "DELEGATED_ACTOR_SECRET" in _declaradas_como_secreto(), (
        "`DELEGATED_ACTOR_SECRET` no está en `secretos.tsv`, así que `gcp_create_secrets.sh` no "
        "lo crea y `vm_fetch_secrets.sh` no lo baja. La actuación «en nombre de» queda muerta en "
        "el despliegue sin que nada lo diga."
    )


def test_el_guardarrail_encuentra_algo_que_mirar() -> None:
    """Un test que cruza dos listas vacías pasa en verde sin comprobar nada.

    Se fijan cotas bajas a propósito: no son cifras que haya que mantener, son el mínimo por
    debajo del cual este fichero habría dejado de leer lo que cree leer.
    """
    assert len(_leidas_por_el_codigo()) >= 40, "apenas se ven lecturas de entorno en el código"
    assert len(_declaradas_en_el_ejemplo()) >= 40, "`.env.example` casi no declara nada"
    assert len(_declaradas_como_secreto()) >= 5, "`secretos.tsv` casi no declara nada"


#: Lo que este guardarraíl **no puede ver**, declarado en vez de callado.
#:
#: `credenciales_llm.py` lee `os.getenv(nombre)` donde el nombre **viene de la base de datos**:
#: la fila de la credencial declara qué variable guarda su secreto. Eso es una decisión de
#: diseño —cada organización elige el nombre— y no se puede enumerar desde el código. Fingir que
#: sí sería peor que decirlo.
CIEGOS_A_PROPOSITO = {
    # El nombre **viene de la base de datos**: la fila de la credencial declara qué variable
    # guarda su secreto, y cada organización elige la suya. No se puede enumerar desde el código.
    "server/app/modules/agents_hub/services/credenciales_llm.py",
    # El nombre llega como **parámetro** a `_regla(variable, por_defecto)`. Resolverlo exigiría
    # seguir el flujo de datos, y un analizador de flujo dentro de un test es más código del que
    # vigila. Sus variables están en la sección «Limite de peticiones» de `.env.example`,
    # comprobado a mano el 2026-09-20.
    "server/app/core/rate_limit.py",
}


def test_lo_que_no_se_puede_ver_esta_declarado() -> None:
    """Un guardarraíl tiene que decir dónde deja de mirar.

    Si aparece un módulo nuevo que lee el entorno por un nombre que no se puede resolver, este
    test se pone rojo y hay que **decidir**: o el nombre pasa a una constante o una colección
    —y entonces se cubre—, o se añade aquí con su razón. Lo que no vale es que crezca solo.
    """
    ciegos = {
        f.replace("\\", "/")
        for f, tiene_lista in _modulos_con_lectura_dinamica().items()
        if not tiene_lista
    }
    sin_declarar = sorted(ciegos - CIEGOS_A_PROPOSITO)
    assert not sin_declarar, (
        f"Estos módulos leen el entorno por un nombre que no se puede resolver: {sin_declarar}. "
        "Sus variables no las cubre ningún inventario ni este guardarraíl. O el nombre pasa a "
        "una constante o una colección, o se declara aquí con su razón."
    )
    sobran = sorted(CIEGOS_A_PROPOSITO - ciegos)
    assert not sobran, (
        f"Estos ya no leen el entorno dinámicamente: {sobran}. La excepción sobra, y una "
        "excepción que sobra es la que nadie vuelve a mirar."
    )
