"""La pila de la VM: el estado fuera, el sandbox bajo gVisor y nada duplicado (D.4-VM).

**Por qué existe un compose aparte, que es el hallazgo del prompt.** El bloque Deploy decía que
en una VM esto era «prácticamente `docker compose up -d`» sobre `docker-compose.prod.yml`. No lo
era: ese fichero es la opción *autoinstalable* —lo dice su propia cabecera— y trae **su** Postgres,
**su** MinIO y un perfil de Ollama, con el `DATABASE_URL` del servicio `app` apuntando al
contenedor `postgres`. Levantarlo en GCP habría corrido una base de datos que nadie usa junto a
la que sí, con el mismo nombre de variable. De ahí `deploy/vm/docker-compose.vm.yml`.

Lo que estos tests vigilan es lo que se rompe sin ruido:

- Que el estado no vuelva a entrar en la máquina (ni Postgres, ni MinIO, ni Langfuse).
- Que `runtime: runsc` esté **y sólo** en el sandbox: es la capa 8 que D.0.doc decidió
  conservar, y ponerla en todo mataría el rendimiento sin añadir aislamiento donde importa.
- Que las cabeceras de seguridad no se dupliquen en el proxy. La primera versión del Caddyfile
  escribía `X-Frame-Options: SAMEORIGIN` donde la aplicación dice `DENY`: dos fuentes de verdad
  y la del proxy era la débil.
- Que el 22 no quede abierto al mundo.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
VM = RAIZ / "deploy" / "vm"
COMPOSE = VM / "docker-compose.vm.yml"
CADDYFILE = VM / "Caddyfile"
UNIDAD = VM / "govgenai.service"
STARTUP = VM / "startup.sh"
PROVISION = RAIZ / "scripts" / "gcp_provision_vm.sh"

_BASH = shutil.which("bash") or "bash"


def _texto(ruta: Path) -> str:
    assert ruta.is_file(), f"Falta {ruta.relative_to(RAIZ).as_posix()}"
    return ruta.read_text(encoding="utf-8")


def _servicios() -> list[str]:
    """Nombres de servicio del compose, por indentación (sin cargar YAML)."""
    dentro = False
    nombres: list[str] = []
    for linea in _texto(COMPOSE).splitlines():
        if re.match(r"^services:\s*$", linea):
            dentro = True
            continue
        if dentro:
            if re.match(r"^\S", linea):  # otra clave de primer nivel
                dentro = False
                continue
            m = re.match(r"^  ([a-z0-9][a-z0-9_-]*):\s*$", linea)
            if m:
                nombres.append(m.group(1))
    return nombres


# ---------------------------------------------------------------------------
# El estado vive fuera de la máquina
# ---------------------------------------------------------------------------


def test_la_pila_de_la_vm_no_levanta_base_de_datos_ni_almacenamiento_propios() -> None:
    servicios = _servicios()
    assert servicios, "No se han podido leer los servicios del compose."
    for prohibido in ("postgres", "s3", "langfuse", "ollama"):
        assert prohibido not in servicios, (
            f"El servicio «{prohibido}» no puede correr en la VM: la base está en Cloud SQL y "
            "los documentos en GCS. Si vuelve, el estado regresa al disco de la máquina y "
            "perderla deja de ser inocuo."
        )


def test_la_base_se_alcanza_por_el_auth_proxy_y_no_por_una_ip() -> None:
    texto = _texto(COMPOSE)
    assert "cloud-sql-proxy" in texto, "Falta el Cloud SQL Auth Proxy."
    assert "--unix-socket=/cloudsql" in texto, (
        "El proxy tiene que exponer el socket Unix que espera DATABASE_URL (?host=/cloudsql/...)."
    )
    assert "CLOUDSQL_CONNECTION_NAME" in texto


def test_el_almacenamiento_es_gcs_y_el_entorno_es_produccion() -> None:
    texto = _texto(COMPOSE)
    assert "STORAGE_BACKEND: gcs" in texto
    assert "ENVIRONMENT: production" in texto


def test_la_configuracion_entra_por_el_fichero_que_escribe_secret_manager() -> None:
    """Ningún `.env` mantenido a mano en la máquina: lo monta `vm_fetch_secrets.sh`."""
    texto = _texto(COMPOSE)
    assert "/opt/govgenai/.env.runtime" in texto
    assert "server/.env" not in texto, (
        "El compose de la VM no puede leer el .env del repositorio."
    )


# ---------------------------------------------------------------------------
# La capa 8, donde toca y sólo donde toca
# ---------------------------------------------------------------------------


def test_solo_el_sandbox_corre_bajo_gvisor() -> None:
    texto = _texto(COMPOSE)
    # Sólo líneas activas: el comentario que explica la decisión también nombra la directiva.
    activas = [
        linea for linea in texto.splitlines()
        if "runtime: runsc" in linea and not linea.strip().startswith("#")
    ]
    assert len(activas) == 1, (
        f"`runtime: runsc` está activo {len(activas)} veces. Va sólo en el sandbox: es el "
        "único servicio que ejecuta código que no hemos escrito, y ponerlo en todo cuesta "
        f"rendimiento sin añadir aislamiento donde importa. {activas}"
    )
    # …y que esa aparición esté dentro del bloque del sandbox. Se ancla a la clave del
    # servicio (dos espacios de indentación): «script-sandbox» a secas también aparece como
    # host en `SANDBOX_BASE_URL` del servicio `app`, y partir por ahí leía el bloque
    # equivocado — el primer intento de este test cayó justo en eso.
    bloque = re.split(r"\n  script-sandbox:\s*\n", texto, maxsplit=1)
    assert len(bloque) == 2, "No se encuentra el servicio script-sandbox."
    siguiente = re.split(r"\n  [a-z0-9][a-z0-9_-]*:\s*\n", bloque[1], maxsplit=1)[0]
    assert "runtime: runsc" in siguiente, "`runtime: runsc` no está en el sandbox."


def test_el_arranque_instala_gvisor_con_la_plataforma_que_funciona_en_una_vm() -> None:
    texto = _texto(STARTUP)
    assert "runsc" in texto, "El guion de arranque tiene que instalar gVisor."
    assert "systrap" in texto, (
        "La plataforma tiene que ser `systrap`: `kvm` exige /dev/kvm, o sea virtualización "
        "anidada, que GCE no da en todos los tipos de máquina."
    )


def test_el_arranque_autentica_docker_contra_artifact_registry() -> None:
    """Tener el rol de lectura NO basta: el demonio necesita el ayudante de credenciales.

    Sin él, el `pull` falla con «Unauthenticated request … no permission
    artifactregistry.repositories.downloadArtifacts», que suena a permiso ausente y es un
    ayudante ausente. El cuarto despliegue real murió ahí, con la imagen ya publicada.
    """
    texto = _texto(STARTUP)
    assert "configure-docker" in texto, (
        "El arranque tiene que instalar el ayudante de credenciales de Docker."
    )
    assert "docker.pkg.dev" in texto
    assert "/root/.docker/config.json" in texto, (
        "La pila se levanta con `sudo`, así que la credencial va en la configuración de root."
    )
    # La región llega por metadatos, no cableada: el aprovisionamiento ya la conoce.
    assert "ar-region" in texto
    assert "ar-region" in _texto(PROVISION), (
        "El aprovisionamiento tiene que pasar la región en los metadatos de la instancia."
    )


def test_el_socket_del_proxy_vive_en_un_directorio_del_anfitrion_con_su_dueno() -> None:
    """La imagen del proxy corre con uid 65532 y un volumen nuevo nace de root con 0755, así
    que el proxy no puede crear dentro el socket: muere con «Unable to mount socket: mkdir …
    permission denied» y reintenta en bucle, lo que lo declara *unhealthy* y tumba a quien
    depende de él. El quinto despliegue real murió ahí.
    """
    compose = _texto(COMPOSE)
    assert "/opt/govgenai/cloudsql:/cloudsql" in compose, (
        "El socket va en un directorio del anfitrión, no en un volumen con nombre."
    )
    assert "cloudsql:" not in compose.split("volumes:")[-1], (
        "No debe quedar declarado el volumen con nombre `cloudsql`."
    )

    startup = _texto(STARTUP)
    assert "chown 65532:65532 /opt/govgenai/cloudsql" in startup, (
        "El directorio tiene que crearse con el uid con el que corre la imagen del proxy."
    )


def test_la_limpieza_de_sockets_comprueba_que_no_haya_proxy_corriendo() -> None:
    """La guarda que no comprueba causó el fallo que venía a evitar.

    La primera versión limpiaba sin condición, razonando que en un `restart` systemd ya ha
    ejecutado `ExecStop`. Pero `ExecStop` es el **mismo** `docker compose`: cuando el fichero
    de entorno quedó a medias también falló, los contenedores siguieron vivos y la limpieza
    **borró el socket con el proxy funcionando**. El proxy siguió sano —ya estaba enlazado— y
    la aplicación murió con `FileNotFoundError` al conectar.
    """
    texto = _texto(UNIDAD)
    assert "/opt/govgenai/cloudsql" in texto, "Falta la limpieza de sockets huérfanos en ExecStartPre."
    assert "rm -rf" in texto, "Falta la limpieza de sockets huérfanos en ExecStartPre."
    limpieza = [linea for linea in texto.splitlines() if "rm -rf" in linea and "cloudsql" in linea]
    assert limpieza, "No se encuentra la línea de limpieza."
    for linea in limpieza:
        assert "govgenai_sql_proxy" in linea, (
            "La limpieza tiene que comprobar antes que no haya proxy corriendo: "
            f"{linea.strip()}"
        )
        assert "status=running" in linea, (
            "La limpieza tiene que comprobar antes que no haya proxy corriendo: "
            f"{linea.strip()}"
        )


def test_el_sandbox_conserva_las_capas_que_ya_tenia() -> None:
    """No se «mejoran» ni se pierden al copiar el servicio a otro fichero."""
    texto = _texto(COMPOSE)
    for capa in ('cap_drop: ["ALL"]', "no-new-privileges:true", 'user: "65534:65534"',
                 "read_only: true", "pids_limit: 128"):
        assert capa in texto, f"El sandbox de la VM ha perdido: {capa}"
    assert "internal: true" in texto, "La red del sandbox tiene que seguir sin salida."


# ---------------------------------------------------------------------------
# El proxy no duplica lo que ya hace la aplicación
# ---------------------------------------------------------------------------


def test_el_proxy_no_repite_las_cabeceras_de_seguridad_de_la_aplicacion() -> None:
    """Donde la aplicación pone las cabeceras, el proxy no las repite.

    **Salvo en la ruta del bucket** (2026-10-22): el sitio del corpus no pasa por la aplicación,
    así que ahí nadie más las pone, y la ruta lleva `nosniff` y `Referrer-Policy`. Hasta esa
    fecha este test suponía que la aplicación cubría todo lo que sirve el proxy, y no era así.
    """
    texto = _texto(CADDYFILE)
    inicio = texto.index("# Todo lo demás, el sitio del corpus publicado en el bucket.")
    fin = texto.index("reverse_proxy https://{$CORPUS_BUCKET}", inicio)
    fuera_del_bucket = texto[:inicio] + texto[fin:]
    for cabecera in ("X-Frame-Options", "Strict-Transport-Security",
                     "X-Content-Type-Options", "Referrer-Policy"):
        # Se permite nombrarla en un comentario que explica por qué NO se pone.
        activas = [
            linea for linea in fuera_del_bucket.splitlines()
            if cabecera in linea and not linea.strip().startswith("#")
        ]
        assert not activas, (
            f"{cabecera} la pone `server/app/core/security_headers.py`. Repetirla aquí crea "
            f"dos fuentes de verdad para la misma cabecera: {activas}"
        )


def test_el_proxy_pasa_la_api_y_la_salud_a_la_aplicacion() -> None:
    texto = _texto(CADDYFILE)
    assert "handle /api/*" in texto
    assert "reverse_proxy app:8000" in texto
    assert "handle /health" in texto
    assert "{$GOVGENAI_HOST}" in texto, (
        "El host tiene que llegar por entorno: hoy es un sslip.io y mañana el subdominio."
    )


def test_el_proxy_no_abre_docs_porque_lo_cierra_la_aplicacion() -> None:
    texto = _texto(CADDYFILE)
    activas = [linea for linea in texto.splitlines() if "/docs" in linea and not linea.strip().startswith("#")]
    assert not activas, f"`/docs` lo apaga SEC.7 en la aplicación; no se enruta aquí: {activas}"


# ---------------------------------------------------------------------------
# Arranque tras reinicio
# ---------------------------------------------------------------------------


def test_la_unidad_systemd_levanta_la_pila_y_baja_los_secretos_antes() -> None:
    texto = _texto(UNIDAD)
    assert "WantedBy=multi-user.target" in texto, (
        "Sin esto la máquina reinicia y el sistema se queda apagado hasta que alguien entra."
    )
    assert "vm_fetch_secrets.sh" in texto, (
        "Los secretos se rebajan en cada arranque: rotar es cambiar el secreto y reiniciar."
    )
    assert "docker compose" in texto
    assert "docker-compose.vm.yml" in texto
    assert "unless-stopped" in _texto(COMPOSE), (
        "Lo que mantiene los contenedores en pie entre fallos es `restart: unless-stopped`."
    )


# ---------------------------------------------------------------------------
# Aprovisionamiento
# ---------------------------------------------------------------------------


def test_el_22_no_queda_abierto_al_mundo() -> None:
    texto = _texto(PROVISION)
    assert "35.235.240.0/20" in texto, "El SSH tiene que entrar sólo por el rango de IAP."
    reglas_22 = [linea for linea in texto.splitlines() if "tcp:22" in linea]
    assert reglas_22, "No se encuentra la regla del 22."
    for linea in reglas_22:
        assert "0.0.0.0/0" not in linea, f"22 abierto a Internet: {linea.strip()}"


def test_la_maquina_usa_cuenta_propia_y_no_la_de_por_defecto_de_compute() -> None:
    texto = _texto(PROVISION)
    assert "--service-account=" in texto
    # El correo se compone en el guion, así que se comprueba en su plan y no como literal.
    solo_bash = str(Path(_BASH).parent)
    seco = subprocess.run(
        [_BASH, str(PROVISION), "--project", "proyecto-de-prueba", "--dry-run"],
        cwd=RAIZ, capture_output=True, text=True, timeout=60,
        env={**os.environ, "PATH": solo_bash},
        check=False,
    )
    assert "govgenai-vm@proyecto-de-prueba.iam.gserviceaccount.com" in seco.stdout, (
        f"El plan no declara la cuenta de servicio propia:\n{seco.stdout}"
    )
    for rol in ("roles/cloudsql.client", "roles/artifactregistry.reader"):
        assert rol in texto, f"Falta el rol mínimo {rol}"
    # Sin este, el asistente no responde: embeber la pregunta es una llamada a Vertex y el
    # fallo (403 aiplatform.endpoints.predict) no aparece hasta la primera consulta real, con
    # la máquina, el TLS y la base ya funcionando.
    assert "roles/aiplatform.user" in texto, (
        "Falta el rol de Vertex: sin él la recuperación falla con 403 en la primera consulta."
    )
    assert "roles/editor" not in texto
    assert "roles/owner" not in texto


def test_la_ip_es_estatica_porque_el_nombre_del_host_depende_de_ella() -> None:
    texto = _texto(PROVISION)
    assert "compute addresses create" in texto
    assert "sslip.io" in texto, (
        "El guion tiene que decir qué nombre usar con esa IP: es lo que va al certificado y "
        "al ASSISTENT_API de las páginas publicadas."
    )


def test_el_tamano_de_la_maquina_es_el_medido() -> None:
    """El tipo se comprueba en la ASIGNACIÓN, no como cadena suelta en el fichero.

    **Este test pasó en verde sobre una afirmación falsa el 2026-09-25.** Decía
    `assert "e2-small" in texto`, y cuando el aprovisionador pasó a crear una `e2-medium` siguió
    pasando: la cadena `e2-small` seguía en la prosa que explica por qué fue suficiente durante
    meses. O sea que el guardarraíl dejó de describir lo que el guion hace y nadie se enteró,
    porque un verde no llama la atención de nadie.

    Buscar una cadena en un fichero no es comprobar una configuración. Lo que manda es la línea
    que asigna, y es lo que se mira.
    """
    texto = _texto(PROVISION)
    asignado = re.search(r'^TIPO="([a-z0-9-]+)"', texto, re.MULTILINE)
    assert asignado, "no se encuentra la línea `TIPO=` del aprovisionador"
    assert asignado.group(1) == "e2-medium", (
        f"el aprovisionador crea una `{asignado.group(1)}` y el reparto de memoria del compose "
        f"está dimensionado para una `e2-medium` (ver "
        f"test_issue149_los_contenedores_tienen_techo_de_memoria.py, que deduce la RAM de aquí). "
        f"Si el tipo cambia a propósito, cambia los dos."
    )
    assert "345 MB" in texto, (
        "El tamaño se justifica con la medición de D.4.0, no con una estimación."
    )
    assert "4.330 fragmentos" in texto, (
        "Y el salto a `e2-medium` se justifica con lo que no cupo —la reingesta del corpus—, no "
        "con «por si acaso»."
    )


def test_el_tipo_de_maquina_no_se_puede_sobrescribir_a_uno_sin_medir() -> None:
    """El valor por defecto no basta: el guion acepta `--machine-type`.

    **Lo señaló la revisión de la PR #167.** De poco sirve que `TIPO=` sea el bueno si alguien
    recrea la máquina con `--machine-type e2-small`: saldría una VM de 1.976 MiB mientras el
    compose reparte techos para 3.924 y su guardarraíl deduce la RAM **de este mismo fichero**.
    Es el desajuste que la PR anterior arregló, reintroducido por la puerta de al lado.

    Que el tipo por defecto sea correcto es una cosa; que no se pueda pedir otro que nadie ha
    medido es la que de verdad sostiene el reparto.
    """
    texto = _texto(PROVISION)
    assert "TIPOS_SOPORTADOS" in texto, (
        "el guion acepta `--machine-type` sin comprobar que sea un tipo con la RAM medida. "
        "Un tipo desconocido deja el reparto de memoria del compose describiendo una máquina "
        "que no existe."
    )
    assert re.search(r"--machine-type \$TIPO no está soportado", texto), (
        "la validación tiene que fallar con un mensaje que diga qué pasa y por qué, no con un "
        "error genérico: quien recrea una VM no suele ser quien escribió el reparto."
    )


def test_el_aprovisionamiento_exige_proyecto_y_su_plan_en_seco_no_toca_nada() -> None:
    sin_proyecto = subprocess.run(
        [_BASH, str(PROVISION), "--dry-run"],
        cwd=RAIZ, capture_output=True, text=True, timeout=60,
        check=False,
    )
    assert sin_proyecto.returncode == 2, "Sin --project tiene que negarse."

    solo_bash = str(Path(_BASH).parent)
    seco = subprocess.run(
        [_BASH, str(PROVISION), "--project", "proyecto-de-prueba", "--dry-run"],
        cwd=RAIZ, capture_output=True, text=True, timeout=60,
        env={**os.environ, "PATH": solo_bash},
        check=False,
    )
    assert seco.returncode == 0, seco.stderr
    assert "dry-run" in seco.stdout
