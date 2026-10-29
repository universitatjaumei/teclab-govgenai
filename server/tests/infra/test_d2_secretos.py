"""Los secretos del despliegue: un inventario, y dos guiones que no lo contradicen (D.2).

En producción no hay `.env`: los valores viven en Secret Manager y la VM los baja al arrancar.
El prompt original daba por hecho que la plataforma los inyectaba —era Cloud Run—; en una VM
eso lo hace `scripts/vm_fetch_secrets.sh`, y esa es la parte que había que escribir.

Lo que estos tests vigilan es lo que se rompe en silencio:

- **Que el inventario y los guiones no divergan.** La lista estaba destinada a vivir en tres
  sitios (crear, bajar, documentar); vive en uno, `scripts/lib/secretos.tsv`, y los dos
  guiones lo leen. Un test lo comprueba porque «fuente única» sólo es verdad mientras alguien
  no copie la lista.
- **Que ningún valor se imprima.** Un secreto en la salida del despliegue queda en el registro
  del workflow, y ahí lo ve cualquiera con acceso al repositorio.
- **Que no se rote sin querer.** Regenerar `JWT_SECRET_KEY` en una segunda pasada echaría a la
  calle todas las sesiones, y el síntoma no señalaría al script.

Se ejercen con `--dry-run`, sin tocar la nube. Necesitan `bash` de verdad, como
`test_setup_script.py`, así que la suite se corre desde Git Bash.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
INVENTARIO = RAIZ / "scripts" / "lib" / "secretos.tsv"
CREAR = RAIZ / "scripts" / "gcp_create_secrets.sh"
BAJAR = RAIZ / "scripts" / "vm_fetch_secrets.sh"

_BASH = shutil.which("bash") or "bash"

_ORIGENES = frozenset({"generado", "derivado", "humano"})


def _entradas() -> list[tuple[str, str, str, str]]:
    filas: list[tuple[str, str, str, str]] = []
    for linea in INVENTARIO.read_text(encoding="utf-8").splitlines():
        if not linea.strip() or linea.lstrip().startswith("#"):
            continue
        partes = linea.split("|")
        assert len(partes) == 4, f"El inventario exige 4 campos: {linea!r}"
        filas.append(tuple(p.strip() for p in partes))  # type: ignore[arg-type]
    return filas


def _run(guion: Path, *args: str, env: dict[str, str] | None = None):
    return subprocess.run(
        [_BASH, str(guion), *args],
        cwd=RAIZ,
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, **(env or {})},
        check=False,
    )


# ---------------------------------------------------------------------------
# El inventario
# ---------------------------------------------------------------------------


def test_el_inventario_existe_y_esta_bien_formado() -> None:
    assert INVENTARIO.is_file(), f"Falta {INVENTARIO.relative_to(RAIZ).as_posix()}"
    entradas = _entradas()
    assert entradas, "El inventario está vacío."
    for nombre, variable, origen, consumidor in entradas:
        assert nombre, f"Campos vacíos en {nombre!r}"
        assert variable, f"Campos vacíos en {nombre!r}"
        assert consumidor, f"Campos vacíos en {nombre!r}"
        assert origen in _ORIGENES, f"Origen desconocido {origen!r} en {nombre}"
        assert variable == variable.upper(), f"{variable} debería ir en mayúsculas"


def test_no_hay_secretos_repetidos_ni_variables_repetidas() -> None:
    """Dos entradas para la misma variable dejan el fichero de entorno a merced del orden."""
    entradas = _entradas()
    nombres = [n for n, _, _, _ in entradas]
    variables = [v for _, v, _, _ in entradas]
    assert len(nombres) == len(set(nombres)), "Nombres de secreto repetidos"
    assert len(variables) == len(set(variables)), "Variables de entorno repetidas"


def test_el_inventario_dice_lo_que_deja_fuera_y_por_que() -> None:
    """Un secreto ausente sin explicación se lee como olvido, y alguien lo añade «por si acaso»."""
    texto = INVENTARIO.read_text(encoding="utf-8")
    for ausente in ("LANGFUSE", "OPENAI", "S3_", "DEV_ADMIN"):
        assert ausente in texto, (
            f"El inventario no explica por qué {ausente} no está. Escríbelo: una credencial "
            "que nadie consume es una credencial que nadie rota."
        )


# ---------------------------------------------------------------------------
# Fuente única: los guiones leen el inventario, no una copia
# ---------------------------------------------------------------------------


def test_los_dos_guiones_leen_el_inventario_y_no_copian_la_lista() -> None:
    nombres = {n for n, _, _, _ in _entradas()}
    for guion in (CREAR, BAJAR):
        texto = guion.read_text(encoding="utf-8")
        assert "secretos.tsv" in texto, f"{guion.name} no lee el inventario"

        # `govgenai-db-password` sí puede aparecer en `gcp_create_secrets.sh`: el secreto
        # derivado necesita leer la contraseña para construir la URL. Cualquier OTRO nombre
        # escrito a mano es una copia de la lista.
        permitidos = {"govgenai-db-password"} if guion is CREAR else set()
        copiados = {n for n in nombres if n in texto} - permitidos
        assert not copiados, (
            f"{guion.name} escribe a mano nombres del inventario: {sorted(copiados)}. "
            "La lista tiene que salir del .tsv, o volverán a divergir."
        )


# ---------------------------------------------------------------------------
# Que no se escape un valor
# ---------------------------------------------------------------------------


def test_ningun_guion_imprime_el_valor_de_un_secreto() -> None:
    """Un secreto en la salida del despliegue queda en el registro del workflow.

    Lo que se prohíbe es que el valor llegue a **stdout**. Canalizarlo a `gcloud secrets
    versions add --data-file=-` sí vale, y es mejor que la alternativa: un `--data-file`
    de verdad dejaría el secreto escrito en el disco. Por eso el test no busca `printf`
    a secas —eso marcaría en rojo la forma correcta— sino un `printf` cuyo valor no acabe
    en una tubería.
    """
    # Une las continuaciones de línea: la tubería suele ir en la línea siguiente.
    unir = re.compile(r"\\\s*\n\s*")
    sospechosa = re.compile(r"^\s*(?:echo|printf)\b[^\n]*\$(?:valor|clave|url)\b")

    for guion in (CREAR, BAJAR):
        texto = unir.sub(" ", guion.read_text(encoding="utf-8"))
        for linea in texto.splitlines():
            if not sospechosa.match(linea):
                continue
            assert "| gcloud" in linea or ">>" in linea, (
                f"{guion.name} manda un valor de secreto a la salida:\n  {linea.strip()}\n"
                "Imprime el nombre de la variable, nunca su contenido; si hay que entregar "
                "el valor, que sea por tubería."
            )


def test_el_fichero_de_entorno_se_escribe_con_permisos_cerrados() -> None:
    texto = BAJAR.read_text(encoding="utf-8")
    assert "umask 077" in texto, "Falta `umask 077` antes de crear el temporal."
    assert "chmod 600" in texto, "Falta `chmod 600` sobre el fichero final."
    assert "mktemp" in texto, "Se escribe a un temporal y se mueve: si no, existe un instante con permisos abiertos."
    assert "mv " in texto, "Se escribe a un temporal y se mueve: si no, existe un instante con permisos abiertos."


def test_si_falta_un_secreto_no_se_escribe_un_entorno_a_medias() -> None:
    texto = BAJAR.read_text(encoding="utf-8")
    assert "No se escribe el fichero" in texto or "no se escribe el fichero" in texto.lower(), (
        "El guion tiene que negarse a escribir un entorno incompleto y decirlo."
    )


# ---------------------------------------------------------------------------
# Idempotencia sin rotar
# ---------------------------------------------------------------------------


def test_el_valor_generado_se_limpia_de_retorno_de_carro() -> None:
    """En Windows `openssl` termina con CRLF, y `tr -d '\\n'` deja el `\\r` dentro del secreto.

    Pasó de verdad al sembrar por primera vez: 97 caracteres donde tenían que haber 96. Un
    `\\r` en una contraseña no da error legible —falla la autenticación sin decir por qué— y en
    un fichero de entorno se lleva la línea entera.
    """
    texto = CREAR.read_text(encoding="utf-8")
    assert "openssl rand" in texto, "El valor generado tiene que ser aleatorio de verdad."
    assert re.search(r"tr -d ['\"]\\r\\n['\"]", texto), (
        "El valor generado tiene que limpiarse de CR y LF, no sólo de LF."
    )


def test_todo_valor_capturado_de_gcloud_se_limpia() -> None:
    """El mismo `\\r`, por otra puerta: `gcloud --format=value(...)` termina en CRLF en Windows
    y `$(...)` sólo quita el `\\n`, así que la URL de conexión salió con un retorno de carro
    dentro. Se limpia en un sitio (`limpiar`) y se exige aquí para que no vuelva.
    """
    crear = CREAR.read_text(encoding="utf-8")
    assert "limpiar()" in crear, "Falta la función que limpia lo capturado de gcloud."
    for captura in ("connectionName", "govgenai-db-password"):
        linea = next(
            (linea for linea in crear.splitlines() if captura in linea and "$(" in linea or captura in linea),
            "",
        )
        assert linea, f"No se encontró la captura de {captura}"
    # Las dos capturas que construyen la URL pasan por `limpiar`.
    assert crear.count("| limpiar)") >= 2, (
        "Las capturas de gcloud que entran en la URL tienen que pasar por `limpiar`."
    )

    bajar = BAJAR.read_text(encoding="utf-8")
    assert re.search(r"tr -d ['\"]\\r\\n['\"]", bajar), (
        "El valor que se escribe en el fichero de entorno tiene que limpiarse de CR."
    )


def test_crear_no_rota_un_secreto_que_ya_existe() -> None:
    """La condición está escrita como guarda; sin ella, la segunda pasada cierra sesiones."""
    texto = CREAR.read_text(encoding="utf-8")
    assert "tiene_version" in texto, "Falta la comprobación de si el secreto ya tiene valor."
    assert "no se rota" in texto, (
        "El guion debe decir explícitamente que no rota lo que ya existe: es la diferencia "
        "entre repetible y destructivo."
    )


# ---------------------------------------------------------------------------
# Interfaz
# ---------------------------------------------------------------------------


def test_los_dos_guiones_exigen_el_proyecto() -> None:
    for guion in (CREAR, BAJAR):
        resultado = _run(guion, "--dry-run")
        assert resultado.returncode == 2, (
            f"{guion.name} sin --project tiene que negarse.\nsalida: {resultado.stdout}"
        )


def test_dry_run_no_llama_a_gcloud() -> None:
    solo_bash = str(Path(_BASH).parent)
    for guion in (CREAR, BAJAR):
        resultado = _run(guion, "--project", "proyecto-de-prueba", "--dry-run",
                         env={"PATH": solo_bash})
        assert resultado.returncode == 0, f"{guion.name}: {resultado.stderr}"
        assert "dry-run" in resultado.stdout


def test_el_plan_en_seco_nombra_todas_las_variables() -> None:
    """Cada entrada del inventario la nombra el guion que la consume, y ninguna queda huérfana.

    Desde D.8 el inventario tiene dos clases de secreto: los que son **variable de entorno**,
    que baja `vm_fetch_secrets.sh`, y los que son **fichero** (`FICHERO:…`, el certificado del
    dominio y su clave), que baja `vm_fetch_tls.sh` porque un PEM multilínea no cabe en un
    fichero de entorno. La comprobación sigue siendo la misma en el fondo —que el inventario y
    los guiones no divergen— pero ahora pregunta al guion correcto.
    """
    plan_entorno = _run(BAJAR, "--project", "proyecto-de-prueba", "--dry-run")
    assert plan_entorno.returncode == 0

    tls = RAIZ / "scripts" / "vm_fetch_tls.sh"
    assert tls.is_file(), "Falta scripts/vm_fetch_tls.sh, que es quien baja los ficheros."
    plan_tls = _run(tls, "--project", "proyecto-de-prueba", "--host", "ejemplo.uji.es",
                    "--dry-run")
    assert plan_tls.returncode == 0, plan_tls.stderr

    for nombre, variable, _, _ in _entradas():
        if variable.startswith("FICHERO:"):
            assert nombre in plan_tls.stdout, (
                f"{nombre} es un fichero y no aparece en el plan de vm_fetch_tls.sh"
            )
            assert variable not in plan_entorno.stdout, (
                f"{variable} es un PEM multilínea y NO puede acabar en el fichero de entorno: "
                f"rompería todas las variables que vinieran detrás."
            )
        else:
            assert variable in plan_entorno.stdout, f"{variable} no aparece en el plan"


# ---------------------------------------------------------------------------
# Que el código siga fallando rápido, que es lo que hace segura la migración
# ---------------------------------------------------------------------------


def test_el_arranque_exige_el_secreto_del_jwt_y_no_tiene_valor_por_defecto() -> None:
    """Si `JWT_SECRET_KEY` tuviera defecto, un despliegue sin el secreto arrancaría firmando
    con un valor conocido — y no habría ningún síntoma hasta que alguien lo aprovechara."""
    config = (RAIZ / "server" / "app" / "core" / "config.py").read_text(encoding="utf-8")
    assert 'os.environ.get("JWT_SECRET_KEY")' in config
    assert "JWT_SECRET_KEY environment variable is required" in config
    assert 'os.getenv("JWT_SECRET_KEY"' not in config, (
        "Con `os.getenv(..., defecto)` el arranque dejaría de fallar y firmaría con el defecto."
    )
