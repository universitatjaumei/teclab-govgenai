"""CI construye la imagen que se despliega, y la arranca.

**El agujero que este job tapa, medido el 2026-09-15 con producción caída 35 minutos**: el
único conjunto de dependencias que se despliega —el base, `uv sync --frozen --no-dev`, sin
extras— era el único que no probaba nadie. `Lint & Test` instala con `--all-extras`, así que
`uvicorn` estaba ahí; el guardarraíl de DEP.1 busca *imports* y `uvicorn` no se importa, se
invoca; y comprobar que la aplicación **importa** con el conjunto base pasa en verde, porque
importar funcionaba — lo que faltaba era el proceso que la arranca.

`test_dep8_los_ejecutables_del_dockerfile_estan_declarados.py` cerró la rendija del `CMD`
leyendo el manifiesto. Esto cierra la pregunta entera por el único camino que no admite
interpretación: **construir la imagen y levantarla**.

Lo que este fichero fija, y por qué cada cosa:

* **Los mismos `Dockerfile` y contextos que el despliegue**, leídos de `deploy.yml` y no
  escritos aquí a mano. Un `Dockerfile.test` que «se parece» al de producción mide otra cosa y
  no da ningún síntoma de estarlo haciendo.
* **Sin `--all-extras` ni `--dev` en ninguna parte del job.** Es el punto entero del bloque: con
  extras, el fallo del 2026-09-15 vuelve a ser invisible.
* **Las migraciones con la imagen recién construida**, como el servicio `migrate` de
  `docker-compose.prod.yml`. Sin ellas el contenedor arranca contra una base vacía y el job se
  pondría rojo por una razón distinta de la que existe para vigilar.
* **Arrancar y esperar a `/health`**, con el mismo criterio que el paso «Comprobar que sirve, y
  volver atrás si no» de `deploy.yml`: reintentos y 200. Dos definiciones de «sirve» acabarían
  divergiendo, y la que manda es la del despliegue.
* **Ningún paso en `continue-on-error`.** Un job que no bloquea se degrada sin síntoma: sigue
  en verde y ya no comprueba nada. Es la avería que este proyecto persigue.

Lo que **no** comprueba, porque vive fuera del árbol: cuánto tarda y si las imágenes llegan a
construirse en la máquina de GitHub. Eso se ve en la ejecución, y la medida se escribe en
`planificacion/fase1/75_BLOQUE_IMG.md` cuando exista.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[3]
CI = RAIZ / ".github" / "workflows" / "ci.yml"
DESPLIEGUE = RAIZ / ".github" / "workflows" / "deploy.yml"

JOB = "imagen"

#: Lo que delata que se está instalando algo que el despliegue no instala.
CONJUNTOS_QUE_NO_SON_EL_DESPLEGADO = ("--all-extras", "--extra ", "--dev")


@pytest.fixture(scope="module")
def flujo() -> dict[str, Any]:
    assert CI.is_file(), f"Falta {CI.relative_to(RAIZ).as_posix()}"
    return yaml.safe_load(CI.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def job(flujo: dict[str, Any]) -> dict[str, Any]:
    assert JOB in flujo["jobs"], (
        f"El job «{JOB}» no está en ci.yml. Es el que construye y arranca la imagen que se "
        f"despliega; sin él, el conjunto base de dependencias vuelve a ser el único que nadie "
        f"prueba, que es lo que costó 35 minutos de producción el 2026-09-15."
    )
    return flujo["jobs"][JOB]


def _script(job: dict[str, Any]) -> str:
    """Todo lo que el job ejecuta, en un solo texto."""
    return "\n".join(paso.get("run", "") for paso in job.get("steps", []))


def _pasos_que_no_bloquean(job: dict[str, Any]) -> list[str]:
    sueltos = [
        paso.get("name", "<sin nombre>")
        for paso in job.get("steps", [])
        if paso.get("continue-on-error")
    ]
    if job.get("continue-on-error"):
        sueltos.append("<el job entero>")
    return sueltos


def _conjuntos_ajenos_al_despliegue(script: str) -> list[str]:
    return [marca.strip() for marca in CONJUNTOS_QUE_NO_SON_EL_DESPLEGADO if marca in script]


def _imagenes_del_despliegue() -> list[tuple[str, str, str]]:
    """Los `(nombre, contexto, dockerfile)` que `deploy.yml` construye, leídos de él.

    Se leen y no se copian: si el despliegue añade una imagen o mueve un `Dockerfile`, este
    guardarraíl tiene que enterarse. Copiar la lista aquí es cómo empiezan las dos verdades.
    """
    texto = DESPLIEGUE.read_text(encoding="utf-8")
    # Los tres primeros argumentos son `(nombre, contexto, dockerfile)` y eso no ha cambiado;
    # lo que viene detrás sí puede crecer. APER.18 le añadió la etiqueta y los argumentos de
    # construcción —para que los modelos locales se elijan al desplegar— y esta expresión
    # exigía que la línea **acabara** en el tercero, así que dejó de casar. Eso fue el
    # guardarraíl funcionando: avisó de que el despliegue había cambiado de forma.
    #
    # **`[^\S\n]` y no `\s`, y esto costó un rato.** `\s` incluye el salto de línea, así que un
    # `(?:\s+\S+)*` tolerante se comía las tres líneas siguientes: cada llamada casaba por
    # separado pero `findall` devolvía **una**. Lo cazó el auto-chequeo de abajo, que compara
    # contra cuatro; sin él, los tests de este fichero habrían pasado en verde comparando una
    # imagen y dando por buenas las otras tres.
    encontradas = re.findall(
        r"^[^\S\n]*construir_si_falta[^\S\n]+(\S+)[^\S\n]+(\S+)[^\S\n]+(\S+)"
        r"(?:[^\S\n]+\S+)*[^\S\n]*$",
        texto,
        re.MULTILINE,
    )
    assert encontradas, (
        "No se ha encontrado ninguna llamada a `construir_si_falta` en deploy.yml. O el "
        "despliegue cambió de forma, o este lector dejó de casar — y entonces la comprobación "
        "de abajo pasaría en verde sin comparar nada."
    )
    return encontradas


def _dockerfiles_construidos(script: str) -> set[str]:
    """Los `-f <ruta>` de los `docker build` del job, normalizados a `a/b/c`."""
    rutas = re.findall(r"docker\s+build[^\n]*?-f\s+(\S+)", script)
    return {ruta.lstrip("./").replace("\\", "/") for ruta in rutas}


def _etiquetas_construidas(script: str) -> set[str]:
    return set(re.findall(r"docker\s+build[^\n]*?-t\s+(\S+)", script))


def _arranca_en_segundo_plano_una_imagen_construida(script: str) -> bool:
    """¿Hay un `docker run -d` de una de las imágenes que este job acaba de construir?

    **El detalle que parece pedante y es el fondo del asunto**: la primera versión de esto
    preguntaba si el script contenía `docker run`, y se quedó VERDE al quitar el paso que
    levanta la aplicación — porque el paso de migraciones también ejecuta `docker run --rm`. El
    guardarraíl veía la pregunta que le hicieron y no la que importaba. Lo que distingue
    «arrancar un servidor» de «ejecutar una orden y salir» es `-d`, y lo que distingue
    «arrancar lo que se despliega» de «arrancar cualquier cosa» es que la etiqueta sea una de
    las construidas aquí.
    """
    arranque = re.search(r"docker\s+run\s+-d\b((?:.|\n)*?)(?:\n\s*\n|\Z)", script)
    if arranque is None:
        return False
    return any(etiqueta in arranque.group(1) for etiqueta in _etiquetas_construidas(script))


def test_el_job_construye_los_mismos_dockerfile_que_el_despliegue(job: dict[str, Any]) -> None:
    construidos = _dockerfiles_construidos(_script(job))
    esperados = {
        dockerfile.lstrip("./").replace("\\", "/")
        for _, _, dockerfile in _imagenes_del_despliegue()
    }
    faltan = sorted(esperados - construidos)
    assert not faltan, (
        f"El job «{JOB}» no construye {faltan}, que `deploy.yml` sí construye. Construir es "
        f"barato y caza un `Dockerfile` roto antes de que lo haga el despliegue: la imagen del "
        f"frontend dejó de construir el 2026-09-16 por un `[build-system]` añadido en otro "
        f"sitio, y se descubrió a mano, a un paso del merge."
    )


def test_el_job_construye_con_el_dockerfile_del_despliegue_y_no_con_uno_de_prueba(
    job: dict[str, Any],
) -> None:
    sospechosos = [
        ruta
        for ruta in _dockerfiles_construidos(_script(job))
        if "test" in ruta.lower() or "ci" in Path(ruta).name.lower()
    ]
    assert not sospechosos, (
        f"El job construye {sospechosos}, que no es el `Dockerfile` del despliegue. Una imagen "
        f"«de test» mide otra cosa —otro conjunto de dependencias, otro `CMD`— y lo hace sin "
        f"dar ningún síntoma de estarlo haciendo."
    )


def test_el_job_no_instala_extras_ni_dependencias_de_desarrollo(job: dict[str, Any]) -> None:
    ajenos = _conjuntos_ajenos_al_despliegue(_script(job))
    assert not ajenos, (
        f"El job usa {ajenos}, y eso es exactamente lo que lo dejaría ciego: con extras, "
        f"`uvicorn` vuelve a estar presente y el fallo del 2026-09-15 no se ve. El despliegue "
        f"instala el conjunto base; aquí se mide ese, o no se mide lo que se despliega."
    )


def test_la_imagen_de_la_aplicacion_instala_el_conjunto_base() -> None:
    """La otra mitad: el job puede ser correcto y el `Dockerfile` instalar de más."""
    dockerfile = (RAIZ / "Dockerfile").read_text(encoding="utf-8")
    instalaciones = [
        linea
        for linea in dockerfile.splitlines()
        # Sólo lo que la imagen EJECUTA. Los comentarios del `Dockerfile` explican por qué se
        # instala así y mencionan `uv sync`: leerlos como instalaciones ponía este test rojo
        # contra un párrafo de prosa, que es ruido con aspecto de hallazgo.
        if "uv sync" in linea and linea.strip().upper().startswith("RUN")
    ]
    assert instalaciones, (
        "Ningún `RUN` del Dockerfile de la aplicación instala con `uv sync`. O cambió la forma "
        "de instalar, o este lector dejó de casar — y entonces la comprobación de abajo no "
        "miraría nada."
    )
    for linea in instalaciones:
        assert "--frozen" in linea, (
            f"«{linea.strip()}» no instala el conjunto base. El despliegue usa "
            f"`uv sync --frozen --no-dev`, y si la imagen se aparta de eso, lo que CI arranca "
            f"deja de ser lo que se despliega."
        )
        assert "--no-dev" in linea, (
            f"«{linea.strip()}» no instala el conjunto base. El despliegue usa "
            f"`uv sync --frozen --no-dev`, y si la imagen se aparta de eso, lo que CI arranca "
            f"deja de ser lo que se despliega."
        )
        assert not _conjuntos_ajenos_al_despliegue(linea), (
            f"«{linea.strip()}» mete extras o dependencias de desarrollo en la imagen."
        )


def test_el_job_migra_con_la_imagen_antes_de_arrancarla(job: dict[str, Any]) -> None:
    script = _script(job)
    assert "alembic" in script, (
        "El job no aplica las migraciones. El arranque consulta la base —siembra y trabajos "
        "zombis— así que contra una base vacía el contenedor moriría por una razón distinta de "
        "la que este job vigila. El despliegue lo hace con el servicio `migrate` de "
        "`docker-compose.prod.yml`, que usa esta misma imagen."
    )
    assert "upgrade" in script, (
        "El job no aplica las migraciones. El arranque consulta la base —siembra y trabajos "
        "zombis— así que contra una base vacía el contenedor moriría por una razón distinta de "
        "la que este job vigila. El despliegue lo hace con el servicio `migrate` de "
        "`docker-compose.prod.yml`, que usa esta misma imagen."
    )


def test_el_job_arranca_el_contenedor_y_espera_a_que_responda(job: dict[str, Any]) -> None:
    script = _script(job)
    assert _arranca_en_segundo_plano_una_imagen_construida(script), (
        "El job construye la imagen y no la deja corriendo. Construir demuestra que la imagen "
        "existe, no que sirve: el 2026-09-15 la imagen se construyó perfectamente y el "
        "contenedor murió con `executable file not found in $PATH`. Hace falta un "
        "`docker run -d` de una de las etiquetas que este mismo job construye."
    )
    assert "/health" in script, (
        "El job no comprueba `/health`. Es el criterio que usa el paso «Comprobar que sirve, y "
        "volver atrás si no» del despliegue, y tener dos definiciones de «sirve» acaba en que "
        "una de las dos miente."
    )
    assert re.search(r"\bfor\b[^\n]*\n(?:.*\n)*?.*\bsleep\b", script), (
        "La comprobación de `/health` necesita reintentos con espera. El arranque refresca la "
        "caché de modelos y los precios antes de servir, así que una sola llamada inmediata "
        "daría rojo por prisa y no por avería."
    )


def test_ningun_paso_del_job_deja_de_bloquear(job: dict[str, Any]) -> None:
    sueltos = _pasos_que_no_bloquean(job)
    assert not sueltos, (
        f"{sueltos} no bloquea. Un job que no bloquea se degrada en silencio: sigue en verde y "
        f"ya no comprueba nada. Si algún día hay que desatascar un build, se arregla la causa o "
        f"se quita el job entero con su razón escrita, pero no se deja el decorado."
    )


def test_el_job_corre_en_cada_ejecucion_del_flujo(job: dict[str, Any]) -> None:
    """Sin `if`: lo que corre a veces no protege de lo que pasa el resto de las veces.

    Si la medición del tiempo obligara a acotarlo —sólo `main` y sus *pull requests*—, esto se
    pone rojo a propósito: la decisión se toma con la medida delante y se escribe en el bloque,
    no se cuela en una línea.
    """
    assert "if" not in job, (
        f"El job «{JOB}» lleva un `if`, así que hay ejecuciones en las que la imagen no se "
        f"construye. Si es lo que se ha decidido, la medida que lo justifica va escrita en "
        f"`planificacion/fase1/75_BLOQUE_IMG.md` y este guardarraíl se actualiza con ella."
    )


# ---------------------------------------------------------------------------------------
# Las mutaciones, una a una. Un guardarraíl que nadie ha visto ponerse rojo no es un
# guardarraíl: es una afirmación sobre sí mismo.
# ---------------------------------------------------------------------------------------


def test_mutacion_con_all_extras_el_guardarrail_se_pone_rojo() -> None:
    mutado = "docker build -f Dockerfile .\nuv sync --locked --all-extras"
    assert _conjuntos_ajenos_al_despliegue(mutado) == ["--all-extras"]


def test_mutacion_con_continue_on_error_el_guardarrail_se_pone_rojo() -> None:
    mutado = {"steps": [{"name": "Arrancar", "continue-on-error": True, "run": "docker run"}]}
    assert _pasos_que_no_bloquean(mutado) == ["Arrancar"]


def test_mutacion_con_un_dockerfile_de_prueba_el_guardarrail_se_pone_rojo() -> None:
    mutado = "docker build -t x -f Dockerfile.test ."
    construidos = _dockerfiles_construidos(mutado)
    esperados = {d.lstrip("./") for _, _, d in _imagenes_del_despliegue()}
    assert esperados - construidos, (
        "Construyendo otro Dockerfile, la comparación con el despliegue tiene que faltar algo."
    )
    assert [r for r in construidos if "test" in r.lower()] == ["Dockerfile.test"]


def test_mutacion_sin_arrancar_el_contenedor_el_guardarrail_se_pone_rojo() -> None:
    """La mutación que dejó VERDE a la primera versión de este fichero.

    Se quitó el paso que levanta la aplicación y el job siguió pasando, porque el paso de
    migraciones ejecuta `docker run --rm` y la comprobación se conformaba con eso. Aquí está
    escrito ese script exacto: migra, no arranca, y tiene que salir rojo.
    """
    mutado = (
        "docker build -t govgenai/app:ci -f Dockerfile .\n"
        "docker run --rm --network host govgenai/app:ci alembic upgrade head\n"
        "\n"
        "curl -s http://localhost:8000/health\n"
    )
    assert "docker run" in mutado, "El caso sólo vale si el script conserva un `docker run`."
    assert not _arranca_en_segundo_plano_una_imagen_construida(mutado)


def test_mutacion_arrancar_una_imagen_ajena_el_guardarrail_se_pone_rojo() -> None:
    """Arrancar algo que no es lo que se acaba de construir tampoco mide el despliegue."""
    mutado = (
        "docker build -t govgenai/app:ci -f Dockerfile .\n"
        "docker run -d --name x nginx:latest\n"
    )
    assert not _arranca_en_segundo_plano_una_imagen_construida(mutado)


def test_el_lector_de_deploy_encuentra_las_cuatro_imagenes() -> None:
    """Si esto deja de casar, los tests de arriba pasan en verde sin comparar nada."""
    imagenes = _imagenes_del_despliegue()
    assert len(imagenes) == 4, f"Se esperaban 4 imágenes en deploy.yml y hay {len(imagenes)}."
    assert {nombre for nombre, _, _ in imagenes} == {"app", "frontend", "sandbox", "mcp"}
