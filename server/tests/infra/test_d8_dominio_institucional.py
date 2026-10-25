"""El dominio institucional y su certificado propio (D.8).

Desarrollo entregó el 2026-09-01 el certificado de `normativa.uji.es` emitido por HARICA a
través de GÉANT, con su clave. El dominio **no existía todavía en el DNS**, así que el diseño
tenía que cumplir una condición incómoda: poder desplegarse **antes** de que el nombre resuelva
y sin que nada deje de funcionar.

De ahí las tres decisiones que estos tests fijan, porque las tres se rompen en silencio:

1. **El dominio nuevo es un sitio ADICIONAL, no un reemplazo.** El nombre provisional de
   `sslip.io` sigue sirviendo, porque las páginas del corpus ya publicadas apuntan a él: cambiar
   `GOVGENAI_HOST` de golpe dejaría el widget muerto hasta regenerar y volver a subir 313
   páginas. Los dos nombres sirven las MISMAS rutas, y eso se garantiza con un fragmento
   reutilizado y no copiando el bloque.

2. **El sitio del dominio sólo existe si su certificado está en disco.** Caddy **no arranca** si
   un `tls` apunta a ficheros que no están, y un Caddy que no arranca es el servicio entero
   caído. Así que el fichero del sitio lo escribe el guion de arranque *después* de comprobar
   que el certificado y la clave se han bajado, y el `import` es un glob —que en Caddy no falla
   cuando no casa nada—.

3. **La clave privada no entra en el repositorio ni en la imagen.** Va a Secret Manager como los
   otros seis secretos y la máquina la baja en cada arranque, con permisos 600. Un certificado
   caduca; una clave privada en un repositorio no se puede retirar.

Y una cuarta cosa que no es diseño sino calendario: este certificado **caduca el 19 de marzo de
2027** y su renovación es manual, al revés que el de Let's Encrypt del nombre provisional. El
test correspondiente no comprueba la fecha —cambiará— sino que quede escrita donde alguien la
vea.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
VM = RAIZ / "deploy" / "vm"
COMPOSE = VM / "docker-compose.vm.yml"
CADDYFILE = VM / "Caddyfile"
UNIDAD = VM / "govgenai.service"
PLANTILLA = VM / "sites.d" / "dominio.caddy.tpl"
FETCH_TLS = RAIZ / "scripts" / "vm_fetch_tls.sh"
INVENTARIO = RAIZ / "scripts" / "lib" / "secretos.tsv"

_BASH = shutil.which("bash") or "bash"

DOMINIO = "normativa.uji.es"


def _texto(ruta: Path) -> str:
    assert ruta.is_file(), f"Falta {ruta.relative_to(RAIZ).as_posix()}"
    return ruta.read_text(encoding="utf-8")


def _activas(texto: str, aguja: str) -> list[str]:
    """Líneas que contienen la aguja y NO son comentario."""
    return [
        linea
        for linea in texto.splitlines()
        if aguja in linea and not linea.strip().startswith("#")
    ]


# ---------------------------------------------------------------------------
# 1. Los dos nombres sirven lo mismo
# ---------------------------------------------------------------------------


def test_las_rutas_viven_en_un_fragmento_reutilizable() -> None:
    """Si cada sitio copia sus rutas, el día que cambie una se cambiará en uno solo."""
    texto = _texto(CADDYFILE)
    assert re.search(r"^\(\s*govgenai_rutas\s*\)\s*\{", texto, re.M), (
        "Las rutas comunes tienen que estar en un fragmento `(govgenai_rutas)`: los dos "
        "nombres —el provisional y el institucional— han de servir exactamente lo mismo."
    )
    assert _activas(texto, "import govgenai_rutas"), (
        "El bloque del host provisional tiene que importar el fragmento, no repetir las rutas."
    )


def test_el_host_provisional_sigue_llegando_por_entorno() -> None:
    """No se sustituye: las páginas ya publicadas apuntan a él."""
    texto = _texto(CADDYFILE)
    assert "{$GOVGENAI_HOST}" in texto, (
        "Quitar `GOVGENAI_HOST` dejaría sin servir el nombre al que apuntan las 313 páginas "
        "del corpus ya publicadas en el bucket."
    )


def test_el_caddyfile_importa_los_sitios_extra_con_un_glob() -> None:
    """Un `import` de fichero concreto falla si no está; un glob que no casa, no."""
    texto = _texto(CADDYFILE)
    lineas = _activas(texto, "import ")
    globs = [linea for linea in lineas if "sites.d" in linea and "*" in linea]
    assert globs, (
        "Falta `import /etc/caddy/sites.d/*.caddy`. Con un glob, Caddy arranca igual cuando "
        "todavía no hay ningún sitio extra, que es la situación mientras el DNS no exista."
    )


# ---------------------------------------------------------------------------
# 2. El sitio del dominio sólo existe con su certificado
# ---------------------------------------------------------------------------


def test_la_plantilla_del_dominio_usa_el_certificado_propio_y_no_acme() -> None:
    texto = _texto(PLANTILLA)
    assert _activas(texto, "tls "), (
        "Sin una directiva `tls` explícita, Caddy intentaría ACME para este nombre."
    )
    assert "import govgenai_rutas" in texto, (
        "El sitio del dominio sirve las mismas rutas que el provisional, por el fragmento."
    )
    assert "{{HOST}}" in texto or "__HOST__" in texto, (
        "El nombre se sustituye al instalar la plantilla; no se escribe a mano aquí."
    )


def test_el_guion_de_tls_no_instala_el_sitio_sin_certificado() -> None:
    """Es la guarda que evita tumbar el servicio entero: Caddy no arranca sin los ficheros."""
    texto = _texto(FETCH_TLS)
    assert _activas(texto, "chmod 600") or _activas(texto, "chmod 0600"), (
        "La clave privada se escribe con permisos 600."
    )
    # La guarda tiene que existir de forma explícita: comprobar los dos ficheros antes de
    # escribir el fichero del sitio.
    assert re.search(r"sites\.d", texto), "El guion es quien instala el sitio en sites.d/."
    assert re.search(r"\brm\b.*sites\.d|rm -f .*\.caddy", texto), (
        "Si el certificado no está, el sitio se RETIRA: dejarlo apuntando a ficheros que no "
        "existen impide que Caddy arranque, y eso tumba también el host provisional."
    )


def test_el_guion_de_tls_pasa_su_propia_comprobacion_de_sintaxis() -> None:
    assert FETCH_TLS.is_file()
    r = subprocess.run([_BASH, "-n", str(FETCH_TLS)], capture_output=True, text=True, check=False)
    assert r.returncode == 0, f"Error de sintaxis en vm_fetch_tls.sh: {r.stderr}"


def test_el_guion_de_tls_corre_en_seco_sin_llamar_a_gcloud() -> None:
    r = subprocess.run(
        [_BASH, str(FETCH_TLS), "--project", "proyecto-de-prueba", "--host", DOMINIO,
         "--dry-run"],
        capture_output=True, text=True,
        check=False,
    )
    assert r.returncode == 0, f"--dry-run debería salir 0: {r.stderr or r.stdout}"
    assert DOMINIO in r.stdout, "El --dry-run tiene que decir para qué nombre trabajaría."


# ---------------------------------------------------------------------------
# 3. La clave privada no entra en el repositorio
# ---------------------------------------------------------------------------


def test_los_dos_secretos_estan_en_el_inventario_unico() -> None:
    texto = _texto(INVENTARIO)
    for nombre in ("govgenai-tls-cert", "govgenai-tls-key"):
        assert nombre in texto, (
            f"{nombre} tiene que estar en el inventario: es la fuente única que leen los tres "
            f"guiones, y un secreto fuera de ella envejece sin que nadie lo note."
        )
    for linea in texto.splitlines():
        if linea.startswith("govgenai-tls-"):
            assert "|humano|" in linea, (
                "El certificado lo aporta una persona: no se puede generar ni derivar."
            )


def test_no_hay_material_criptografico_seguido_por_git() -> None:
    """Un certificado caduca; una clave privada commiteada no se puede retirar.

    Se pregunta a **git**, no al disco. La primera versión de este test recorría el árbol de
    ficheros y señalaba cuatro claves de desarrollo —`data/dev_keys/`, la de firma de
    artefactos— que los programas generan al arrancar y que `.gitignore` ya excluye. Medía el
    sitio equivocado: lo que no se puede retirar es lo que está en el historial.
    """
    r = subprocess.run(
        ["git", "ls-files", "-z"], cwd=RAIZ, capture_output=True, text=True
    , check=False)
    assert r.returncode == 0, f"git ls-files falló: {r.stderr}"
    seguidos = [p for p in r.stdout.split("\0") if p]
    sospechosos = [
        p for p in seguidos
        if Path(p).suffix.lower() in (".pem", ".key", ".pfx", ".p12")
    ]
    assert not sospechosos, (
        f"Material criptográfico seguido por git: {sospechosos}. El certificado y la clave van "
        f"a Secret Manager; la máquina los baja en cada arranque."
    )


def test_el_compose_monta_el_certificado_y_los_sitios_extra_en_caddy() -> None:
    texto = _texto(COMPOSE)
    assert _activas(texto, "sites.d"), (
        "Caddy necesita ver /etc/caddy/sites.d para que el glob encuentre el sitio."
    )
    assert _activas(texto, "/opt/govgenai/tls"), (
        "Y el directorio del certificado, en solo lectura."
    )
    for montaje in _activas(texto, "sites.d") + _activas(texto, "/opt/govgenai/tls"):
        assert montaje.rstrip().endswith(":ro"), (
            f"Montaje sin `:ro`; Caddy no tiene por qué poder escribir aquí: {montaje}"
        )


def test_la_unidad_baja_el_certificado_antes_de_levantar_la_pila() -> None:
    texto = _texto(UNIDAD)
    assert "vm_fetch_tls.sh" in texto, (
        "Si la pila arranca antes de tener el certificado, el sitio del dominio no se instala "
        "hasta el reinicio siguiente."
    )
    # Sobre las DIRECTIVAS, no sobre el texto: la unidad menciona `docker compose` en un
    # comentario mucho antes de arrancarlo, y comparar posiciones dentro del fichero completo
    # daba un rojo que no era del código.
    directivas = [
        linea.strip() for linea in texto.splitlines()
        if re.match(r"^(ExecStartPre|ExecStart)=", linea.strip())
    ]
    pre_tls = [i for i, d in enumerate(directivas) if "vm_fetch_tls.sh" in d]
    arranque = [i for i, d in enumerate(directivas) if d.startswith("ExecStart=")]
    assert pre_tls, "El certificado se baja en un ExecStartPre."
    assert arranque, "La unidad tiene que tener un ExecStart."
    assert pre_tls[0] < arranque[0], (
        f"El certificado se baja ANTES de `docker compose up`. Directivas: {directivas}"
    )
    pre_secretos = [i for i, d in enumerate(directivas) if "vm_fetch_secrets.sh" in d]
    assert pre_secretos, "Y después de los secretos, que es de donde sale el proyecto de GCP."
    assert pre_secretos[0] < pre_tls[0], "Y después de los secretos, que es de donde sale el proyecto de GCP."


# ---------------------------------------------------------------------------
# 4. La caducidad, escrita donde alguien la vea
# ---------------------------------------------------------------------------


def test_la_renovacion_manual_queda_advertida() -> None:
    """El de Let's Encrypt se renueva solo; este no, y esa diferencia hay que decirla."""
    textos = " ".join(
        _texto(r) for r in (PLANTILLA, FETCH_TLS) if r.is_file()
    )
    assert re.search(r"caduca|renovaci|renovar|2027", textos, re.I), (
        "En algún sitio que se lea al tocar esto tiene que constar que este certificado NO se "
        "renueva solo. Una renovación olvidada tumba el servicio."
    )
