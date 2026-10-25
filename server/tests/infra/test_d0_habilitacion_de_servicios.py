"""Los servicios de GCP se habilitan con un script, y la lista no se cree: se comprueba (D.0).

La lista vivía en prosa dentro de un «requisito previo», estaba **incompleta** —no incluía
Vertex AI ni Discovery Engine— y nadie la ejecutaba: los prompts de despliegue daban por
hecho que las APIs estaban encendidas. Una API que falta no falla al desplegar; falla como
un 403 en producción la primera vez que alguien usa la función que la necesita.

El test que importa es el primero: **cruza la lista del script con los hosts de Google que
el código llama de verdad**. Así, el día que alguien añada una llamada a un servicio nuevo,
el rojo sale aquí y no en producción. Los demás fijan lo que el prompt decidió: el destino
es una VM (así que `run.googleapis.com` no entra), cada servicio dice quién lo necesita, y
el proyecto es un parámetro y no un valor cableado.

Se invocan con `--dry-run`, que imprime el plan sin llamar a `gcloud`: un test no habilita
APIs en la nube de nadie. Como `test_setup_script.py`, esto necesita `bash` de verdad —desde
PowerShell el lanzador de WSL lo rompe—, así que la suite se corre desde Git Bash.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
SCRIPT = RAIZ / "scripts" / "gcp_enable_services.sh"
APP = RAIZ / "server" / "app"

_BASH = shutil.which("bash") or "bash"

#: Entradas de la lista del script: "servicio|razón".
_ENTRADA = re.compile(r'^\s*"([a-z0-9.-]+\.googleapis\.com)\|([^"]*)"\s*$', re.MULTILINE)

#: Cualquier host de Google que el código llame directamente.
_HOST_EN_CODIGO = re.compile(r"https://([a-z0-9-]+\.googleapis\.com)")

#: Hosts que aparecen en el código y **no son servicios habilitables**, así que no pertenecen
#: a la lista. Se excluyen aquí y no en la expresión regular para que la exclusión tenga que
#: justificarse.
#:
#: - `www.googleapis.com` — `https://www.googleapis.com/auth/cloud-platform` es el **ámbito** de
#:   OAuth con el que se pide el token (`reranker.py`), no una API que se enciende.
#: - `oauth2.googleapis.com` — el endpoint de canje de token de OAuth 2.0
#:   (`core/auth/google_oidc.py`, issue #95). Es infraestructura **global** de identidad de
#:   Google, disponible siempre y sin nada que habilitar por proyecto: lo que se aprovisiona para
#:   ese login es un cliente OAuth y su pantalla de consentimiento, que no son APIs. Si algún día
#:   apareciera aquí un 403, no se arregla habilitando un servicio.
_NO_SON_SERVICIOS = frozenset({"www.googleapis.com", "oauth2.googleapis.com"})


def _run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [_BASH, str(SCRIPT), *args],
        cwd=RAIZ,
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, **(env or {})},
        check=False,
    )


def _entradas() -> list[tuple[str, str]]:
    return _ENTRADA.findall(SCRIPT.read_text(encoding="utf-8"))


def _servicios() -> set[str]:
    return {servicio for servicio, _ in _entradas()}


def test_el_script_existe_y_es_ejecutable_por_bash() -> None:
    assert SCRIPT.is_file(), f"No existe {SCRIPT.relative_to(RAIZ).as_posix()}"
    resultado = _run("--help")
    assert resultado.returncode == 0, resultado.stderr


def test_la_lista_cubre_los_hosts_de_google_que_el_codigo_llama() -> None:
    """Un host de `googleapis.com` en el código y ausente de la lista es un 403 futuro."""
    llamados: dict[str, str] = {}
    for fuente in APP.rglob("*.py"):
        for host in _HOST_EN_CODIGO.findall(fuente.read_text(encoding="utf-8")):
            llamados.setdefault(host, fuente.relative_to(RAIZ).as_posix())

    faltan = {
        host: donde
        for host, donde in llamados.items()
        if host not in _servicios() and host not in _NO_SON_SERVICIOS
    }

    assert not faltan, (
        "El código llama a estos servicios de Google y el script no los habilita:\n"
        + "\n".join(f"  {host}  ← {donde}" for host, donde in sorted(faltan.items()))
        + "\n\nAñádelos a SERVICIOS en scripts/gcp_enable_services.sh con su razón, o el "
        "primer uso en producción será un 403."
    )


def test_la_lista_incluye_lo_que_los_prompts_del_bloque_deploy_necesitan() -> None:
    """Lo que no se ve en el código porque lo usa la infraestructura, no la aplicación."""
    exigidos = {
        "compute.googleapis.com": "la VM (D.4-VM)",
        "oslogin.googleapis.com": "SSH por IAM (D.4-VM)",
        "iap.googleapis.com": "el despliegue entra por IAP (D.5-VM)",
        "sqladmin.googleapis.com": "Cloud SQL (D.3)",
        "secretmanager.googleapis.com": "los secretos (D.2)",
        "storage.googleapis.com": "StorageService con backend gcs",
        "artifactregistry.googleapis.com": "la imagen por SHA (D.5-VM)",
        "iamcredentials.googleapis.com": "Workload Identity (D.5-VM)",
        "sts.googleapis.com": "Workload Identity (D.5-VM)",
        "aiplatform.googleapis.com": "embeddings de Vertex",
        "generativelanguage.googleapis.com": "proveedor google_genai",
        "logging.googleapis.com": "logs fuera de la máquina (D.6-VM)",
        "monitoring.googleapis.com": "uptime y alertas (D.6-VM)",
    }
    presentes = _servicios()
    faltan = {s: por_que for s, por_que in exigidos.items() if s not in presentes}
    assert not faltan, "Faltan en la lista: " + ", ".join(
        f"{s} ({por_que})" for s, por_que in sorted(faltan.items())
    )


def test_no_habilita_cloud_run_porque_el_destino_es_una_vm() -> None:
    """El destino cambió el 2026-08-10; habilitar Cloud Run sería declarar otro despliegue."""
    assert "run.googleapis.com" not in _servicios(), (
        "El despliegue es una VM con Docker Compose "
        "(docs/DECISION_EXTRACCION_Y_DESPLIEGUE.md §2). Si vuelve a hacer falta Cloud Run, "
        "el cambio empieza por esa decisión, no por esta lista."
    )


def test_cada_servicio_declara_quien_lo_necesita() -> None:
    """Sin la razón, nadie sabe qué se rompe al quitar una línea, y se quita."""
    sin_razon = [s for s, razon in _entradas() if not razon.strip()]
    assert not sin_razon, f"Servicios sin razón declarada: {sin_razon}"


def test_el_proyecto_es_un_parametro_y_no_esta_cableado() -> None:
    texto = SCRIPT.read_text(encoding="utf-8")
    assert "--project" in texto
    assert "uji-teclab" not in texto, (
        "El proyecto no puede estar cableado en el script: se pasa con --project."
    )


def test_exige_el_proyecto_en_vez_de_heredar_el_configurado() -> None:
    """Heredar el proyecto de `gcloud config` habilita APIs donde nadie mira."""
    resultado = _run("--dry-run")
    assert resultado.returncode == 2, (
        "Sin --project el script tiene que negarse, no adivinar el proyecto.\n"
        f"salida: {resultado.stdout}\nerror: {resultado.stderr}"
    )
    assert "--project" in resultado.stderr


def test_dry_run_no_llama_a_gcloud() -> None:
    """Se ejerce con un PATH sin `gcloud`: si lo llamara, fallaría."""
    solo_bash = str(Path(_BASH).parent)
    resultado = _run("--project", "proyecto-de-prueba", "--dry-run", env={"PATH": solo_bash})
    assert resultado.returncode == 0, resultado.stderr
    assert "proyecto-de-prueba" in resultado.stdout
    assert "dry-run" in resultado.stdout


def test_es_idempotente() -> None:
    """Dos ejecuciones seguidas dan el mismo plan y salen con 0.

    La habilitación real también lo es —`gcloud services enable` sobre un servicio ya
    habilitado devuelve 0—, y por eso el script se puede repetir cuando la propagación
    tarda.
    """
    primera = _run("--project", "proyecto-de-prueba", "--dry-run")
    segunda = _run("--project", "proyecto-de-prueba", "--dry-run")
    assert primera.returncode == 0
    assert segunda.returncode == 0
    assert primera.stdout == segunda.stdout


def test_avisa_de_la_cuota_del_ranking_api() -> None:
    """La cuota por defecto de Discovery Engine puede ser baja, y eso se sabe antes o duele."""
    texto = SCRIPT.read_text(encoding="utf-8")
    assert "AVISOS_DE_CUOTA" in texto
    assert "discoveryengine" in texto.split("AVISOS_DE_CUOTA", 1)[1][:400]
