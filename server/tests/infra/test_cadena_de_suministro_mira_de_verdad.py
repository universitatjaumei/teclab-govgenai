"""El job de cadena de suministro mira de verdad, y lo único que bloquea sigue bloqueando.

El job `supply-chain` de `ci.yml` prepara la auditoría de seguridad independiente que la OIATI
pide antes de la puesta en explotación: inventario de dependencias (SBOM), vulnerabilidades
conocidas y escaneo de secretos.

**Desde DEP.7 (2026-09-15) ya no informa sólo: tres pasos bloquean** —el escaneo de secretos del
árbol, la puerta de avisos de Python y `npm audit` en `high`— y el resto sigue informando a
propósito, con la razón escrita en el propio fichero. El criterio de la puerta de Python no es un
umbral por severidad, porque `pip-audit` no la informa: bloquea lo que **tiene corrección
publicada y no está aceptado** en `avisos_aceptados.toml`. Lo que no se puede arreglar informa,
que era la condición para que el guardarraíl no acabe desactivado.

Eso es justo lo que lo hace frágil de una manera silenciosa. Un job casi entero en
`continue-on-error` se degrada sin dar ningún síntoma: sigue en verde, sigue subiendo su
artefacto, y ya no comprueba nada. Los cuatro casos que este fichero fija son los cuatro que
he visto o que el proyecto ya ha pagado en otro sitio:

* **`fetch-depth: 0`.** Sin él el clon es superficial y `gitleaks git` recorre un historial de
  un commit. No falla: pasa en verde sin mirar nada, que es la forma de avería que este
  proyecto ya se comió con un guardarraíl que recorría un directorio inexistente.
* **El escaneo del árbol de trabajo no lleva `continue-on-error`.** Es el único paso que
  bloquea. El día que alguien lo ponga para desatascar un build, el job entero pasa a ser
  decorativo y nada lo dirá.
* **`uv export --locked`.** Sin el flag, uv vuelve a resolver en silencio y se audita un
  conjunto de dependencias que el lock no describe. Es la misma lección que costó 17 días con
  el lock de la raíz, y auditar el conjunto equivocado es peor que no auditar: da un informe.
* **La versión de gitleaks está pinada.** `latest` en la herramienta que vigila la cadena de
  suministro es la contradicción que el job existe para no cometer.

Lo que este fichero **no** comprueba, porque vive fuera del árbol: que el job llegue a
ejecutarse en GitHub y que las herramientas se descarguen. Eso se ve en la primera ejecución.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[3]
CI = RAIZ / ".github" / "workflows" / "ci.yml"

JOB = "supply-chain"


@pytest.fixture(scope="module")
def job() -> dict[str, Any]:
    assert CI.is_file(), f"Falta {CI.relative_to(RAIZ).as_posix()}"
    flujo = yaml.safe_load(CI.read_text(encoding="utf-8"))
    assert JOB in flujo["jobs"], (
        f"El job «{JOB}» no está en ci.yml. Si se ha renombrado, este fichero se actualiza "
        f"con él; si se ha quitado, se quita también la promesa de tener SBOM que le hemos "
        f"hecho a quien vaya a auditar."
    )
    return flujo["jobs"][JOB]


def _paso(job: dict[str, Any], *fragmentos: str) -> dict[str, Any]:
    """El paso cuyo nombre contiene TODOS los fragmentos. Exige que sea exactamente uno.

    Los dos detalles son deliberados y salieron de que la primera versión, que devolvía el
    primer nombre que casara con un fragmento suelto, afirmaba cosas sobre el paso equivocado:
    «full history» aparece también en el nombre del checkout, así que el test del escaneo del
    historial estaba comprobando el `continue-on-error` de un `actions/checkout`. Un buscador
    de pasos laxo convierte un guardarraíl en un generador de afirmaciones sobre cualquier
    cosa, y eso no se ve en el verde.
    """
    encontrados = [
        p
        for p in job["steps"]
        if all(f.lower() in p.get("name", "").lower() for f in fragmentos)
    ]
    if len(encontrados) == 1:
        return encontrados[0]
    nombres = "\n  - ".join(p.get("name", "<sin nombre>") for p in job["steps"])
    raise AssertionError(
        f"Se esperaba un único paso que contuviera {fragmentos!r} y hay {len(encontrados)}. "
        f"Los pasos del job:\n  - {nombres}"
    )


def test_el_clon_trae_el_historial_entero(job: dict[str, Any]) -> None:
    """Con un clon superficial el escaneo del historial pasa en verde sin mirar nada."""
    checkout = _paso(job, "Checkout")
    assert checkout.get("with", {}).get("fetch-depth") == 0, (
        "El checkout de este job necesita `fetch-depth: 0`. Con el clon superficial que traen "
        "los demás jobs, `gitleaks git` recorre un solo commit y no encuentra nada — y no da "
        "error, que es lo peor: informa de cero hallazgos sobre un historial que no ha leído."
    )


def test_el_escaneo_del_arbol_bloquea(job: dict[str, Any]) -> None:
    """Es el único paso que bloquea. Si deja de hacerlo, el job entero es decorativo."""
    paso = _paso(job, "Secret scan", "working tree")
    assert not paso.get("continue-on-error", False), (
        "El escaneo de secretos del árbol de trabajo es el ÚNICO paso que bloquea de este "
        "job; todo lo demás informa a propósito. Ponerle `continue-on-error` lo deja todo en "
        "verde permanente. Si está rojo por un falso positivo, la salida es un `.gitleaksignore` "
        "con el hallazgo concreto y su motivo, no apagar el paso."
    )
    assert "gitleaks dir" in paso["run"], (
        "El paso que bloquea escanea el árbol (`gitleaks dir`), no el historial: lo que hay en "
        "el árbol se arregla quitándolo y rotándolo, y lo del historial no."
    )


def test_el_escaneo_del_historial_informa(job: dict[str, Any]) -> None:
    """Y no bloquea: estaría rojo hasta que alguien reescribiera el pasado."""
    paso = _paso(job, "Secret scan", "full history")
    assert paso.get("continue-on-error", False), (
        "El escaneo del historial informa y no bloquea. Ponerlo a bloquear deja el check rojo "
        "hasta que se reescriba el historial, que no es una acción que un CI pueda pedir — y "
        "un guardarraíl siempre rojo se acaba desactivando entero."
    )
    assert paso.get("if") == "always()", (
        "Necesita `if: always()`, y no basta `continue-on-error`: el primero dice «ejecútalo "
        "aunque algo anterior fallara» y el segundo sólo «si falla, no tumbes el job». Sin él, "
        "cuando el escaneo del árbol se pone rojo este paso sale `skipped` — el día en que más "
        "falta hace saber qué hay en el historial. Pasó en la primera ejecución."
    )
    assert "gitleaks git" in paso["run"]


def test_los_dos_escaneos_usan_la_lista_de_permitidos(job: dict[str, Any]) -> None:
    """Sin `--config`, los 58 falsos positivos vuelven y el paso que bloquea es inútil."""
    config = RAIZ / ".gitleaks.toml"
    assert config.is_file(), (
        "Falta `.gitleaks.toml`. Es lo que evita que los 58 hallazgos de ficheros de prueba "
        "dejen el único paso que bloquea permanentemente en rojo."
    )
    for fragmento in ("working tree", "full history"):
        paso = _paso(job, "Secret scan", fragmento)
        assert "--config .gitleaks.toml" in paso["run"], (
            f"El escaneo «{fragmento}» tiene que pasar `--config .gitleaks.toml` explícitamente. "
            f"Sin él gitleaks usa sólo sus reglas por defecto y vuelven los falsos positivos de "
            f"los árboles de prueba."
        )


def _proyectos_con_lock() -> list[str]:
    """Los proyectos con `uv.lock`, **recorriendo el árbol** y no una lista escrita a mano.

    APER.9 lo cambió a esto, y la razón es que la cifra escrita a mano ya falló: decía «los dos
    proyectos con lock propio» cuando había cuatro, y los dos que faltaban —`shared` y
    `services/script_sandbox`— eran precisamente donde estaban los 30 avisos que encontró
    Dependabot. Una lista que alguien tiene que acordarse de ampliar se queda corta; un recorrido
    del árbol pone rojo el guardarraíl el día que nace el lock.
    """
    raiz = Path(__file__).resolve().parents[3]
    rutas = {
        lock.parent.relative_to(raiz).as_posix()
        for patron in ("*/uv.lock", "*/*/uv.lock")
        for lock in raiz.glob(patron)
    }
    return sorted(rutas)


def test_las_dependencias_auditadas_son_las_del_lock(job: dict[str, Any]) -> None:
    """`uv export` sin `--locked` vuelve a resolver, y se audita otro conjunto."""
    export = _paso(job, "Export the locked dependency sets")
    run = export["run"]
    proyectos = _proyectos_con_lock()
    cuantos = len(proyectos)

    faltan = [p for p in proyectos if f"--directory {p} " not in run]
    assert not faltan, (
        f"Estos proyectos tienen `uv.lock` y este job no los exporta: {faltan}. Su árbol de "
        "dependencias no lo audita nadie — y así estuvieron `shared` y "
        "`services/script_sandbox` hasta APER.9, con 30 avisos que sólo vio Dependabot."
    )
    # APER.17 — se exportan **dos** conjuntos: el que se despliega (bloquea) y el completo del
    # lock (informa). El segundo va en un bucle sobre los proyectos, así que contar ocurrencias
    # dejó de decir nada: lo que importa es que estén los dos, y que cada uno se reconozca por
    # el flag que lo define.
    assert run.count("uv export") >= cuantos, (
        f"Se esperaban al menos {cuantos} exports, uno por proyecto con lock "
        f"({', '.join(proyectos)})."
    )
    assert "--no-dev" in run, (
        "Falta el conjunto que se despliega: es el único que puede bloquear, porque es el que "
        "corre en producción."
    )
    assert "--all-extras" in run, (
        "Falta el conjunto completo del lock (APER.17). Sin él el job audita las dependencias "
        "base y el verde no dice su alcance — 200 paquetes de 438 en `server`—, que es cómo "
        "Dependabot informó de un `authlib` crítico con este job en verde."
    )
    assert run.count("--locked") >= cuantos, (
        "Cada `uv export` lleva `--locked`. Sin él uv **vuelve a resolver en silencio** y el "
        "informe describiría un conjunto de dependencias que el lock no declara: un informe "
        "que parece bueno y mide otra cosa. Es la misma avería que vivió 17 días con el lock "
        "de la raíz."
    )
    assert "--no-emit-project" in run, (
        "Nuestro propio código se excluye del fichero auditado: un paquete propio no tiene "
        "CVE. Sus dependencias sí están, resueltas en el mismo export."
    )


def test_todos_los_proyectos_se_auditan_aunque_el_primero_encuentre_algo(
    job: dict[str, Any],
) -> None:
    """El agujero real de la primera ejecución: `mcp_server` no se auditó y nada lo dijo."""
    paso = _paso(job, "pip-audit")
    run = paso["run"]
    cuantos = len(_proyectos_con_lock())
    assert run.count("uvx pip-audit") >= cuantos, (
        f"Se auditan al menos los {cuantos} proyectos con lock. Exportar uno y no auditarlo "
        "deja el fichero en el artefacto y el aviso sin mirar."
    )
    # APER.17 — el conjunto completo se audita en un bucle, así que la cuenta exacta ya no
    # significa nada; lo que no puede faltar es que cada `pip-audit` capture su propio fallo.
    assert "pip-audit-completo-" in run, (
        "No se audita el conjunto completo del lock, sólo el que se despliega."
    )
    assert run.count("|| rc=1") >= cuantos, (
        "Cada `pip-audit` tiene que capturar su propio fallo. Encadenados sin más, el shell "
        "aborta el paso en cuanto el primero encuentra algo —pip-audit sale con 1— y el "
        "segundo no llega a correr. Con `continue-on-error` encima, el job sigue en verde y el "
        "único síntoma es un fichero que falta en el artefacto. Pasó en la primera ejecución: "
        "`mcp_server` no se auditó."
    )
    assert "exit $rc" in run, (
        "Y el paso tiene que acabar propagando el resultado, o su `outcome` diría «success» "
        "siempre y la tabla del resumen estaría mintiendo."
    )


def test_el_paso_que_audita_sigue_sin_bloquear_porque_bloquea_el_siguiente(
    job: dict[str, Any],
) -> None:
    """DEP.7 separó producir los informes de juzgarlos, y la separación es el diseño.

    Si `pip-audit` bloqueara directamente, tumbaría el job por CUALQUIER aviso, incluidos los que
    nadie puede arreglar porque no tienen versión corregida — el guardarraíl siempre rojo que se
    acaba desactivando, que es la razón por la que el job nació informando. El juicio vive en el
    paso siguiente, que sí sabe distinguir.
    """
    auditar = _paso(job, "pip-audit")
    assert auditar.get("continue-on-error", False), (
        "El paso que ejecuta `pip-audit` NO bloquea, y no es un descuido: su trabajo es producir "
        "los dos informes. Quien decide es `Vulnerability gate — Python`, que lee "
        "`avisos_aceptados.toml` y distingue lo que tiene corrección de lo que no. Si este paso "
        "pasa a bloquear, esa distinción desaparece y vuelve el rojo inarreglable."
    )


def test_la_puerta_de_python_bloquea_y_corre_siempre(job: dict[str, Any]) -> None:
    """La pieza que DEP.7 añade: de informar a bloquear, con criterio escrito."""
    puerta = _paso(job, "Vulnerability gate", "Python")
    assert not puerta.get("continue-on-error", False), (
        "La puerta de avisos de Python BLOQUEA. Es la mitad de DEP.7: sin ella el bloque deja el "
        "árbol limpio hoy y sucio dentro de tres meses. Si está roja, la salida es subir el "
        "paquete o aceptar el aviso en `avisos_aceptados.toml` con motivo y caducidad."
    )
    assert puerta.get("if") == "always()", (
        "Necesita `if: always()`. El paso anterior sale con 1 en cuanto encuentra algo, que es "
        "exactamente cuando esta puerta hace falta; sin `always()` saldría `skipped` y el job "
        "quedaría verde con avisos sin juzgar. Es la misma avería que dejó el escaneo del "
        "historial sin ejecutar en la primera ejecución."
    )
    run = puerta["run"]
    assert "puerta_de_avisos.py" in run
    assert "--aceptados avisos_aceptados.toml" in run, (
        "La puerta tiene que leer el fichero de aceptados. Sin él bloquearía por avisos ya "
        "decididos, y la primera reacción de quien se lo encuentre será quitar el paso."
    )
    for informe in ("pip-audit-server.json", "pip-audit-mcp.json"):
        assert informe in run, (
            f"La puerta juzga los DOS informes. Si {informe} no está, ese árbol se audita y "
            f"nadie mira el resultado, que es el mismo agujero de la primera ejecución con otra "
            f"forma."
        )


def test_npm_audit_bloquea_y_conserva_su_informe(job: dict[str, Any]) -> None:
    """En JavaScript sí hay severidad, así que el umbral es real y no una aproximación."""
    paso = _paso(job, "npm audit")
    assert not paso.get("continue-on-error", False), (
        "`npm audit` bloquea desde DEP.7. Al revés que `pip-audit`, trae severidad, así que "
        "`--audit-level=high` es un umbral de verdad. Medido antes de encenderlo: el árbol de "
        "producción estaba en cero avisos."
    )
    run = paso["run"]
    assert "--audit-level=high" in run, "El umbral es `high`, decidido y no heredado."
    assert "--omit=dev" in run, (
        "Sobre el árbol de producción: una vulnerabilidad en la cadena de construcción no viaja "
        "al navegador de nadie. Mezclarlas hace que el número deje de significar algo."
    )
    assert "set -o pipefail" in run, (
        "El informe se conserva con `tee` y el código de salida se recupera con `PIPESTATUS`. "
        "Sin las dos cosas, encender la puerta cuesta perder el informe justo cuando el paso se "
        "pone rojo — que es cuando el artefacto tiene que llevarlo."
    )
    assert "PIPESTATUS" in run, (
        "El informe se conserva con `tee` y el código de salida se recupera con `PIPESTATUS`. "
        "Sin las dos cosas, encender la puerta cuesta perder el informe justo cuando el paso se "
        "pone rojo — que es cuando el artefacto tiene que llevarlo."
    )


def test_ningun_paso_se_salta_por_un_rojo_anterior(job: dict[str, Any]) -> None:
    """La avería que este job se ha comido TRES veces, fijada por fin como regla.

    En GitHub Actions un paso fallido salta todo lo que viene detrás salvo lo marcado con
    `if: always()`. Con un solo paso bloqueante eso casi no se notaba; con tres —la puerta de
    Python, `npm audit` y el escaneo del árbol— significa que **el primero que se pone rojo apaga
    los otros dos**, y el job informa de un problema ocultando los demás.

    Pasó de verdad en la primera ejecución de la puerta de DEP.7 (run 34974628381): la puerta
    bloqueó por `langchain-openai`, y con ella se saltaron `npm audit`, el SBOM y el escaneo de
    secretos del árbol de trabajo — el paso del que el docstring de este fichero dice que si deja
    de ejecutarse, el job entero es decorativo. Antes había pasado con `mcp_server` sin auditar y
    con el escaneo del historial saliendo `skipped`.

    La regla: desde el primer paso que puede bloquear, todos llevan `if: always()`. Se comprueba
    por posición y no por nombre, para que un paso nuevo quede cubierto sin tener que acordarse.
    """
    pasos = job["steps"]
    nombres_bloqueantes = [
        i
        for i, p in enumerate(pasos)
        if not p.get("continue-on-error", False)
        and "run" in p
        and "BLOCK" in p.get("name", "").upper()
    ]
    assert nombres_bloqueantes, (
        "Este job tiene que tener al menos un paso que bloquee, marcado «BLOCKS» en el nombre. "
        "Si no queda ninguno, la cadena de suministro se vigila sola y nadie se entera."
    )

    primero = min(nombres_bloqueantes)
    sin_guarda = [
        p.get("name", "<sin nombre>")
        for p in pasos[primero + 1 :]
        if p.get("if") != "always()"
    ]
    assert not sin_guarda, (
        "Estos pasos van DESPUÉS del primer paso que bloquea y no llevan `if: always()`, así que "
        "un rojo anterior los deja en `skipped` y su comprobación no se hace:\n  - "
        + "\n  - ".join(sin_guarda)
        + "\n\nLas comprobaciones de este job son independientes entre sí: que el árbol de Python "
        "tenga un aviso no dice nada sobre si hay un secreto en el árbol de trabajo. Enterarse de "
        "las dos cosas en la misma ejecución es lo que hace útil el job, y es la avería que ya se "
        "ha pagado tres veces aquí."
    )


def test_el_fichero_de_aceptados_existe_y_lo_vigila_un_test() -> None:
    """Aceptar tiene que costar algo, o la lista crece hasta cubrir el árbol."""
    aceptados = RAIZ / "avisos_aceptados.toml"
    assert aceptados.is_file(), (
        "Falta `avisos_aceptados.toml`. Es lo que permite que la puerta bloquee sin bloquear por "
        "cosas ya decididas."
    )
    vigilante = RAIZ / "server" / "tests" / "infra" / "test_dep7_las_aceptaciones_caducan.py"
    assert vigilante.is_file(), (
        "Falta el test que vigila las caducidades. Sin él, aceptar es gratis y para siempre, y "
        "el fichero de aceptados degenera en una lista de exclusiones con mejor prosa."
    )


def test_la_version_de_gitleaks_esta_pinada(job: dict[str, Any]) -> None:
    version = job.get("env", {}).get("GITLEAKS_VERSION", "")
    assert version, (
        "`GITLEAKS_VERSION` tiene que ser una versión concreta. Resolver «latest» en cada "
        "ejecución, en el job que vigila la cadena de suministro, es exactamente lo que este "
        "job existe para no hacer."
    )
    assert version[0].isdigit(), (
        "`GITLEAKS_VERSION` tiene que ser una versión concreta. Resolver «latest» en cada "
        "ejecución, en el job que vigila la cadena de suministro, es exactamente lo que este "
        "job existe para no hacer."
    )
    instalacion = _paso(job, "Install gitleaks")
    assert "sha256sum -c" in instalacion["run"], (
        "La descarga se comprueba contra el fichero de sumas de la misma release. No protege "
        "de una release comprometida —y así está dicho en el comentario— pero sí de una "
        "descarga truncada o alterada en tránsito."
    )


def test_el_sbom_se_conserva_lo_suficiente(job: dict[str, Any]) -> None:
    """Es la evidencia que se le entrega a quien audite, y eso pasa meses después."""
    subida = _paso(job, "Upload SBOM")
    assert subida.get("if") == "always()", (
        "El artefacto se sube pase lo que pase: cuando más falta hace es cuando algún paso ha "
        "fallado."
    )
    dias = subida.get("with", {}).get("retention-days", 0)
    assert int(dias) >= 90, (
        f"El SBOM se guarda {dias} días. Es evidencia con fecha para la auditoría de "
        f"seguridad, que llega meses después del commit; los 7 días de la cobertura no valen "
        f"aquí."
    )
