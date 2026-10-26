"""Issue #49 — hay comprobación de tipos, su alcance está escrito y dice cuál es el siguiente.

**Por qué esta herramienta y no otra, en este código concreto.** La frontera edge/cloud se
expresa con **protocolos** —`ConfigProvider`, `EmbeddingService`—, y un protocolo que nadie
comprueba es una promesa de firma que sólo se verifica ejecutando el camino: una implementación
que no la cumple del todo falla **en el despliegue donde ese camino sí se recorre**, que es el
peor sitio para enterarse. Hay precedente directo en el repositorio: la regla de leer el
contenido del modelo con `texto_de` nació de un defecto de tipos —Gemini devuelve `content` como
lista de bloques cuando hay más de una parte, y quien asumía `str` fallaba más tarde y en otro
fichero—.

**Y por qué por módulo.** Encender `pyright` sobre el árbol entero daría cientos de avisos y
acabaría desactivado, que es como mueren estas herramientas. Se empieza por `app/core/`, que es
lo compartido, y se amplía con su commit. Lo que este fichero vigila **no es que el alcance sea
grande**, sino que esté **declarado** y que el siguiente paso esté **escrito**: una ampliación
que dependa de que alguien se acuerde no ocurre.

**Lo que encontró la primera pasada**, que es la prueba de que no es ceremonia: nueve errores en
38 ficheros, y ninguno era ruido de configuración una vez resuelto el `extraPaths`.

* Una función que **siempre lanza** y lo declaraba como `-> None`, así que quien la leyera —y el
  comprobador— creía que la ejecución seguía después. Ahora dice `NoReturn`.
* Un `dict(...)` desplegado con `**` que **borraba el tipo de cada campo**: el diccionario se
  tipa como la unión de sus valores, así que nadie podía comprobar que `delegated` recibía un
  booleano y no una tupla.
* Dos comparaciones de SQLModel que se tipan como `bool` en vez de como expresión de columna, y
  que `col()` arregla sin cambiar lo que hacen.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parents[3]
MANIFIESTO = RAIZ / "server" / "pyproject.toml"
CI = RAIZ / ".github" / "workflows" / "ci.yml"


def _pyright() -> dict:
    datos = tomllib.loads(MANIFIESTO.read_text(encoding="utf-8"))
    return datos.get("tool", {}).get("pyright", {})


def test_hay_configuracion_y_declara_su_alcance() -> None:
    config = _pyright()
    assert config, (
        "`server/pyproject.toml` no tiene sección `[tool.pyright]`. Sin alcance declarado, "
        "«comprobamos tipos» no quiere decir nada: hay que poder responder **de qué**."
    )
    assert config.get("include"), (
        "la configuración no declara `include`. Un comprobador sin alcance explícito o lo mira "
        "todo —y acaba apagado— o mira lo que le parezca."
    )
    assert config.get("typeCheckingMode") == "basic", (
        f"el modo es «{config.get('typeCheckingMode')}». Se empieza en `basic` a propósito: "
        "`strict` sobre código que nunca se comprobó da cientos de avisos de golpe."
    )


def test_el_alcance_de_hoy_es_el_nucleo() -> None:
    incluido = _pyright().get("include", [])
    excluido = _pyright().get("exclude", [])
    # Desde #275 el alcance es `app` entero, que contiene el núcleo; lo que no puede pasar es que
    # el núcleo acabe en la lista de excluidos.
    mensaje = (
        f"`app/core` ha salido del alcance ({incluido}, sin {excluido}). Es lo compartido y lo "
        "que más se importa: si se reduce el alcance, que sea una decisión escrita y no un descuido."
    )
    assert any(ruta in ("app", "app/core") for ruta in incluido), mensaje
    assert not any("app/core" in ruta for ruta in excluido), mensaje


def test_pyright_resuelve_los_imports_del_proyecto() -> None:
    """La línea sin la cual el informe no dice nada, y lo parece igual.

    El código se importa como `server.app.…` y el manifiesto vive **dentro** de `server/`, así
    que sin `extraPaths` pyright no resuelve ni uno de sus propios imports: devolvía 51 errores
    de `reportMissingImports` que no eran errores. Un informe así se lee como «esto está fatal»
    y lleva a apagar la herramienta.
    """
    assert ".." in _pyright().get("extraPaths", []), (
        "falta la raíz del repositorio en `extraPaths`. Sin ella, pyright no encuentra el "
        "paquete `server` y todo el informe es ruido."
    )


def test_ci_lo_ejecuta() -> None:
    datos = yaml.safe_load(CI.read_text(encoding="utf-8"))
    guiones = " ".join(
        paso.get("run") or ""
        for cuerpo in datos["jobs"].values()
        for paso in cuerpo.get("steps", [])
    )
    assert "pyright" in guiones, (
        "ningún trabajo de CI ejecuta `pyright`. Un comprobador que sólo corre en local avisa "
        "únicamente a quien se acuerda de ejecutarlo, que es la misma avería que tenía ESLint."
    )


def test_esta_escrito_cual_es_el_siguiente_modulo() -> None:
    """El criterio de cierre que evita que esto se quede donde está.

    Sin un siguiente paso escrito, ampliar depende de que alguien se acuerde, y nadie se acuerda.
    """
    texto = MANIFIESTO.read_text(encoding="utf-8")
    inicio = texto.find("[tool.pyright]")
    assert inicio > 0
    # El comentario que precede a la sección es donde vive la razón y el plan.
    cabecera = texto[max(0, inicio - 2000) : inicio]
    assert "SIGUIENTE" in cabecera.upper(), (
        "el comentario de `[tool.pyright]` no dice cuál es el módulo siguiente. Es el criterio "
        "de cierre de la issue #49: ampliar no puede depender de que alguien se acuerde."
    )
