"""Qué datos llegan al piloto: lista explícita, y la guarda sobre el fichero (D.7).

Antes de esto la pregunta «¿qué pasa al piloto?» sólo tenía dos respuestas y las dos eran
malas: un volcado completo —que arrastra 29 informes de prueba y toda la basura de test— o
empezar de cero, tirando el corpus curado y los hallazgos ya revisados por una persona.

Tres invariantes, y el orden importa:

- **Lista de inclusión, no de exclusión.** Una lista de «todo menos X» se queda corta el día
  que alguien añade una tabla, y los datos de más viajan sin que nadie lo decida. Con inclusión,
  una tabla nueva se queda fuera por omisión — el lado seguro del error.
- **La comprobación va sobre el FICHERO, no sobre la consulta.** Un filtro mal escrito produce
  un `WHERE` que pasa los tests de la consulta y datos de más en el volcado. Esa diferencia es
  justo la que importa.
- **El catálogo del producto no viaja como filas.** Las plantillas demo se exportan a ficheros
  versionados y las siembra `bootstrap.py --con-demo`: así la demo se revisa en un diff y es la
  misma en todos los despliegues. Es la regla que ya rige el vocabulario del corpus.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
VOLCADO = RAIZ / "scripts" / "volcado_piloto.sh"

_BASH = shutil.which("bash") or "bash"

#: Tablas que son catálogo de PLATAFORMA y no cuelgan de ninguna organización, así que su
#: filtro no puede mencionarla. Se enumeran para que la excepción sea una decisión escrita y no
#: un hueco: una tabla con datos de cliente colada aquí viajaría entera.
_DE_PLATAFORMA = {
    "hub_providers": (
        "el catálogo de proveedores de modelo. No tiene columna de organización y la "
        "configuración de embeddings apunta a uno: sin él, el resolutor no sabe si es Vertex."
    ),
}

#: Entradas "tabla|razón" de la lista de prohibidas.
_ENTRADA = re.compile(r'^\s*"(hub_[a-z_]+)\|([^"|]*)"\s*$', re.MULTILINE)

#: Entradas "tabla|filtro|razón" de la lista de las que viajan.
_ENTRADA_CON_FILTRO = re.compile(
    r'^\s*"(hub_[a-z_]+)\|([^"]*?)\|([^"|]*)"\s*$', re.MULTILINE
)


def _texto() -> str:
    assert VOLCADO.is_file(), f"Falta {VOLCADO.relative_to(RAIZ).as_posix()}"
    return VOLCADO.read_text(encoding="utf-8")


def _bloque(nombre: str) -> str:
    """El cuerpo del array `nombre=( … )` del guion."""
    texto = _texto()
    inicio = texto.index(f"{nombre}=(")
    return texto[inicio : texto.index("\n)", inicio)]


def _expandir(filtro: str) -> str:
    """Sustituye las variables que el propio guion define para los subconsultas repetidas.

    El test lee las definiciones del guion en vez de duplicarlas: si mañana el filtro de las
    páginas deja de pasar por los sitios de la organización, esto lo verá.
    """
    texto = _texto()
    for variable in ("_CHATBOTS_DE_LA_ORG", "_SITIOS_DE_LA_ORG"):
        m = re.search(rf'^{variable}="([^"]+)"', texto, re.MULTILINE)
        if m:
            filtro = filtro.replace(f"${variable}", m.group(1))
    return filtro


def _tablas(nombre: str) -> dict[str, str]:
    """{tabla: razón}. Las que viajan llevan tres campos (con el filtro); las prohibidas, dos."""
    bloque = _bloque(nombre)
    if nombre == "TABLAS":
        return {t: r for t, _f, r in _ENTRADA_CON_FILTRO.findall(bloque)}
    return {t: r for t, r in _ENTRADA.findall(bloque)}


def _run(*args: str, env: dict[str, str] | None = None):
    return subprocess.run(
        [_BASH, str(VOLCADO), *args],
        cwd=RAIZ, capture_output=True, text=True, timeout=60,
        env={**os.environ, **(env or {})},
        check=False,
    )


# ---------------------------------------------------------------------------
# Las dos listas
# ---------------------------------------------------------------------------


def test_las_dos_listas_son_explicitas_y_cada_tabla_dice_por_que() -> None:
    viajan = _tablas("TABLAS")
    no_viajan = _tablas("PROHIBIDAS")
    assert viajan, "La lista de tablas que viajan está vacía."
    assert no_viajan, "La lista de tablas prohibidas está vacía."
    for tabla, razon in {**viajan, **no_viajan}.items():
        assert razon.strip(), f"{tabla} no dice por qué está en su lista"


def test_ninguna_tabla_esta_en_las_dos_listas() -> None:
    solapan = set(_tablas("TABLAS")) & set(_tablas("PROHIBIDAS"))
    assert not solapan, f"Tablas en las dos listas a la vez: {sorted(solapan)}"


def test_las_listas_no_llevan_acentos_graves() -> None:
    """Dentro de comillas dobles, bash trata el acento grave como sustitución de comandos.

    Una razón escrita con acentos graves alrededor de `purpose='embedding' AND is_default` hizo
    que el guion muriera con «AND: command not found»: un error de sintaxis provocado por un
    **comentario**. Lo cazó el test que ejecuta el plan en seco, no leer el fichero.
    """
    for nombre in ("TABLAS", "PROHIBIDAS"):
        con_acento = [linea for linea in _bloque(nombre).splitlines() if "`" in linea]
        assert not con_acento, (
            f"Acento grave en {nombre}: bash lo ejecutaría como orden. {con_acento}"
        )


def test_no_viaja_ningun_informe_ni_ninguna_persona() -> None:
    """Los dos grupos que el prompt saca por decisión, no por descuido."""
    viajan = set(_tablas("TABLAS"))
    no_viajan = set(_tablas("PROHIBIDAS"))
    for tabla in ("hub_workspaces", "hub_workspace_blocks", "hub_workspace_audit_events",
                  "hub_run_manifests", "hub_users", "hub_personal_access_tokens"):
        assert tabla not in viajan, f"{tabla} NO puede viajar al piloto"
        assert tabla in no_viajan, (
            f"{tabla} tiene que estar en la lista de prohibidas, para que se COMPRUEBE que no "
            "está en el fichero — no basta con no listarla"
        )


def test_no_viajan_las_conversaciones() -> None:
    """Son de quien preguntó, no del despliegue."""
    assert "hub_interactions" in _tablas("PROHIBIDAS")
    assert "hub_interactions" not in _tablas("TABLAS")


def test_el_catalogo_de_plantillas_no_viaja_como_filas() -> None:
    """Se exporta a ficheros versionados y lo siembra `bootstrap.py --con-demo`."""
    for tabla in ("hub_report_templates", "hub_report_template_versions"):
        assert tabla in _tablas("PROHIBIDAS"), (
            f"{tabla} tiene que quedar fuera: el catálogo del producto es dato versionado, no "
            "una fila que alguien tenía en su portátil"
        )


def test_viaja_lo_que_costaria_rehacer() -> None:
    """El corpus, sus vectores, el vocabulario y el trabajo humano de la curación."""
    viajan = _tablas("TABLAS")
    for tabla in ("hub_organizaciones", "hub_chatbots", "hub_documents", "hub_document_chunks",
                  "hub_vocabulary_terms", "hub_web_sites", "hub_crawled_pages",
                  "hub_content_findings"):
        assert tabla in viajan, f"Falta {tabla}: es lo que costaría rehacer"


def test_viaja_la_configuracion_que_hace_usable_el_corpus() -> None:
    """El corpus sin su modelo de embeddings es un montón de vectores que nadie puede consultar.

    Pasó de verdad: el volcado llevaba sólo las `hub_llm_configs` que los chatbots referencian,
    y **la de embeddings no la referencia ningún chatbot** — se resuelve por
    `purpose='embedding' AND is_default`, a nivel de plataforma. Sin ella, producción caía al
    modelo local por defecto y el guardarraíl de espacio vectorial rechazaba toda consulta:
    «vectores de gemini-embedding-001 … y el modelo activo es BAAI/bge-m3».
    """
    filtros = {
        t: _expandir(f) for t, f, _ in _ENTRADA_CON_FILTRO.findall(_bloque("TABLAS"))
    }
    assert "hub_llm_configs" in filtros, "Falta la configuración de modelos"
    assert "organizacion_id IS NULL" in filtros["hub_llm_configs"], (
        "Las configuraciones de PLATAFORMA (organización nula) tienen que viajar: el modelo "
        "de embeddings es una de ellas y no la referencia nadie."
    )
    assert "hub_providers" in filtros, (
        "Los proveedores también: la configuración de embeddings apunta a uno, y el resolutor "
        "mira su `provider_type`."
    )


def test_los_fragmentos_viajan_porque_reembeber_cuesta() -> None:
    razon = _tablas("TABLAS").get("hub_document_chunks", "")
    assert "reembeber" in razon.lower() or "gpu" in razon.lower(), (
        "La razón de llevarse los fragmentos tiene que estar dicha: un vector se regenera con "
        "GPU y horas, no con un UPDATE."
    )


# ---------------------------------------------------------------------------
# La guarda, que va sobre el fichero
# ---------------------------------------------------------------------------


def test_cada_tabla_lleva_su_filtro_y_ninguna_se_volca_entera() -> None:
    """`pg_dump --table=…` **no filtra filas**.

    La primera versión del guion lo usaba y volcaba cada tabla entera: 3,2 GB con datos de tres
    organizaciones ajenas. Y como imprimía antes un recuento por organización, *parecía*
    filtrado. Sólo la comprobación sobre el fichero lo destapó.
    """
    texto = _texto()
    activas = [
        linea for linea in texto.splitlines()
        if "pg_dump" in linea and not linea.strip().startswith("#")
    ]
    assert not activas, f"`pg_dump` no puede filtrar filas; usa `\\copy` con WHERE: {activas}"
    assert "\\\\copy (SELECT $seleccion FROM $tabla WHERE $filtro)" in texto, (
        "Cada tabla se exporta con su propio filtro y con lista de columnas explícita: sin la "
        "lista, un `COPY` entre dos bases con distinto orden físico desplaza los campos."
    )

    # Y cada entrada declara su filtro: tres campos, no dos.
    for entrada in _ENTRADA_CON_FILTRO.findall(_bloque("TABLAS")):
        tabla, filtro, razon = entrada
        assert filtro.strip(), f"{tabla} no declara filtro: se volcaría entera"
        if tabla not in _DE_PLATAFORMA:
            assert ":ORG" in _expandir(filtro), (
                f"{tabla} tiene un filtro que no acaba llegando a la organización. Si es "
                "catálogo de plataforma, decláralo en _DE_PLATAFORMA con su razón."
            )
        assert razon.strip(), f"{tabla} no dice por qué viaja"


def test_las_dos_caras_del_sitio_sin_organizacion() -> None:
    """`Escola de Doctorat (RAS.5)` se dio de alta con `organizacion_id` a NULO, así que el
    filtro lo dejaba fuera y con él sus 351 páginas y sus 292 hallazgos.

    Las dos caras: las páginas y los hallazgos cuelgan del **sitio**, no de la organización, así
    que un sitio sin organización se lleva su contenido al silencio. Que asignarlo sea un paso
    consciente es la mitad del arreglo; la otra es que el recuento lo delate.
    """
    filtros = {
        t: _expandir(f) for t, f, _ in _ENTRADA_CON_FILTRO.findall(_bloque("TABLAS"))
    }
    for tabla in ("hub_crawled_pages", "hub_content_findings"):
        assert "hub_web_sites" in filtros[tabla], (
            f"{tabla} tiene que filtrarse por su sitio, no por la organización directamente"
        )
    assert "organizacion_id = ':ORG'" in filtros["hub_web_sites"]

    # El guion imprime el recuento por tabla antes de escribir, así que un 0 en `hub_web_sites`
    # es visible en vez de silencioso.
    texto = _texto()
    assert "Recuento en origen" in texto


def test_el_copy_lleva_lista_de_columnas_y_excluye_las_generadas() -> None:
    """Dos cosas que costaron dos intentos de restauración, y las dos con mensajes engañosos.

    **Sin lista de columnas**, `COPY` usa el orden físico de la tabla destino — y dos bases en
    la **misma revisión de Alembic** pueden tenerlo distinto: la de desarrollo evolucionó con
    migraciones y `create_all`, la de producción nació de cero, y `document_id` es la tercera
    columna en una y la duodécima en la otra. El síntoma fue un hash aterrizando en la columna
    del vector.

    **Y las columnas generadas** no admiten valores en `COPY FROM`: `hub_document_chunks.tsv`
    hacía fallar la carga con «extra data after last expected column», que suena a fichero
    corrupto y era una columna de más.
    """
    texto = _texto()
    assert "COPY $tabla ($columnas)" in texto, (
        "El `COPY` tiene que llevar la lista de columnas: sin ella depende del orden físico."
    )
    assert "is_generated <> 'ALWAYS'" in texto, (
        "Las columnas generadas se excluyen; `COPY FROM` no acepta valores para ellas."
    )


def test_las_autorreferencias_se_cargan_en_dos_pasos() -> None:
    """138 documentos apuntan a otro documento (`versio_idiomatica_de`). En un `COPY` la
    comprobación es por fila, así que si el documento al que se apunta viene después, falla.
    Se cargan a nulo y se rellenan con `UPDATE` al final, cuando ya existen todas las filas.
    """
    texto = _texto()
    assert "AUTORREFERENCIAS" in texto
    assert "NULL AS $auto" in texto, (
        "La columna que se autorreferencia sale como NULL en el COPY."
    )
    assert "UPDATE $tabla SET $auto" in texto, (
        "Y su valor real viaja como UPDATE al final del fichero."
    )


def test_no_desactiva_las_comprobaciones_de_la_base() -> None:
    """`session_replication_role = replica` estaba tapando tres errores de la propia lista: una
    tabla que faltaba, un orden mal puesto y las autorreferencias. Cloud SQL lo prohíbe —exige
    superusuario— y eso fue una suerte: desactivar una comprobación es una forma de no
    enterarse.
    """
    texto = _texto()
    activas = [
        linea for linea in texto.splitlines()
        if "session_replication_role" in linea
        and not linea.strip().startswith("#")
        and "echo" not in linea
    ]
    assert not activas, f"No se desactivan los disparadores: {activas}"


def test_la_verificacion_se_hace_sobre_el_fichero_generado() -> None:
    texto = _texto()
    assert re.search(r'grep -qE "COPY \(public\\?\.\)\?\$tabla ', texto), (
        "Las tablas prohibidas se buscan en el volcado ya generado: un filtro mal escrito pasa "
        "los tests de la consulta y deja datos de más en el fichero."
    )
    assert "hub_organizaciones WHERE id <> " in texto, (
        "Hay que comprobar que no aparece ninguna OTRA organización en el fichero."
    )


def test_un_volcado_con_datos_de_mas_se_borra() -> None:
    """Dejarlo en el disco es dejar el fichero que alguien restaura por error."""
    texto = _texto()
    assert re.search(r'rm -f "\$SALIDA"', texto), (
        "Si la verificación falla, el fichero tiene que borrarse."
    )


def test_se_cuenta_antes_de_escribir() -> None:
    texto = _texto()
    assert "Recuento en origen" in texto
    # La generación de verdad, que ahora es el `\copy` por tabla.
    invocacion = texto.index("\\\\copy (SELECT $seleccion FROM $tabla")
    assert texto.index("Recuento en origen") < invocacion, (
        "El recuento va ANTES de generar el fichero: si las cifras no son las esperadas, se "
        "para sin haber escrito nada."
    )


# ---------------------------------------------------------------------------
# Interfaz
# ---------------------------------------------------------------------------


def test_exige_organizacion_y_salida() -> None:
    for argumentos in (("--salida", "x.sql"), ("--organizacion", "u")):
        resultado = _run(*argumentos, "--dry-run")
        assert resultado.returncode == 2, f"Debería negarse con {argumentos}"


def test_la_organizacion_tiene_que_ser_un_uuid() -> None:
    """#270 — se interpola en `sed` y en SQL: cualquier otra cosa es código, no un dato."""
    for organizacion in ("x' OR '1'='1", "u", "00000000-0000-0000-0000-00000000000g"):
        resultado = _run("--organizacion", organizacion, "--salida", "x.sql", "--dry-run")
        assert resultado.returncode == 2, f"Debería negarse con {organizacion!r}"
        assert "UUID" in resultado.stderr


def test_la_conexion_no_esta_cableada() -> None:
    texto = _texto()
    assert "DATABASE_URL_SYNC" in texto
    assert "postgres:5432" not in texto, "El DSN se lee del entorno; cablearlo apunta al portátil de quien lo escribió."
    assert "localhost" not in texto, "El DSN se lee del entorno; cablearlo apunta al portátil de quien lo escribió."


def test_el_plan_en_seco_enumera_las_dos_listas_y_no_toca_la_base() -> None:
    solo_bash = str(Path(_BASH).parent)
    resultado = _run("--organizacion", "5d0c6a7e-3b1f-4c2a-9e8d-1a2b3c4d5e6f", "--salida", "x.sql",
                     "--dry-run", env={"PATH": solo_bash, "DATABASE_URL_SYNC": ""})
    assert resultado.returncode == 0, resultado.stderr
    assert "Viajan" in resultado.stdout
    assert "NO viajan" in resultado.stdout
    for tabla in ("hub_documents", "hub_workspaces"):
        assert tabla in resultado.stdout, f"{tabla} no aparece en el plan"
