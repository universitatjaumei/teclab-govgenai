"""#270 — `gcp_provision_vigilancia.sh` no pone el token en la línea de órdenes.

Pasaba `Authorization: Bearer <token>` como argumento de `curl`, que cualquiera en la máquina ve
con `ps` mientras dura la llamada. Además detectaba los errores buscando `"error"` en el cuerpo
—un cuerpo bueno puede contener la palabra y uno malo puede no traerla— y metía el correo en la
URL del filtro sin codificar.

Se prueba ejecutando el guion de verdad con un `gcloud` y un `curl` falsos delante en el PATH:
el falso apunta cada argumento que recibe y contesta lo que el caso necesita.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[3]
VIGILANCIA = RAIZ / "scripts" / "gcp_provision_vigilancia.sh"
_BASH = shutil.which("bash") or "bash"
TOKEN = "tok-secreto-que-no-se-ve"

_GCLOUD = f"""#!/usr/bin/env bash
echo {TOKEN}
"""

#: Contesta según método y ruta; `RESPUESTA_POST` y `CODIGO_POST` deciden qué devuelve un POST.
_CURL = r"""#!/usr/bin/env bash
printf '%s\n' "$@" >> "$REGISTRO"
metodo=GET; ruta=""; salida=""; formato=""
while [ $# -gt 0 ]; do
  case "$1" in
    -X) metodo="$2"; shift ;;
    -o) salida="$2"; shift ;;
    -w) formato="$2"; shift ;;
    -H|--data-binary) shift ;;
    https://*) ruta="$1" ;;
  esac
  shift
done
codigo=200
case "$metodo $ruta" in
  "GET "*notificationChannels*) cuerpo='{"notificationChannels":[{"name":"projects/p/notificationChannels/1"}]}' ;;
  "POST "*) cuerpo="$RESPUESTA_POST"; codigo="$CODIGO_POST" ;;
  *) cuerpo='{}' ;;
esac
if [ -n "$salida" ]; then printf '%s' "$cuerpo" > "$salida"; else printf '%s' "$cuerpo"; fi
[ -n "$formato" ] && printf '%s' "$codigo"
exit 0
"""


@pytest.fixture
def falsos(tmp_path: Path) -> Path:
    carpeta = tmp_path / "bin"
    carpeta.mkdir()
    for nombre, contenido in (("gcloud", _GCLOUD), ("curl", _CURL)):
        fichero = carpeta / nombre
        fichero.write_bytes(contenido.encode("utf-8"))
        fichero.chmod(0o755)
    return carpeta


def _run(falsos: Path, *, correo="a+b@uji.es", codigo="200", respuesta='{"name":"x"}'):
    registro = falsos.parent / "registro.txt"
    entorno = {
        **os.environ,
        "PATH": f"{falsos}{os.pathsep}{os.environ['PATH']}",
        "REGISTRO": str(registro),
        "CODIGO_POST": codigo,
        "RESPUESTA_POST": respuesta,
    }
    resultado = subprocess.run(
        [_BASH, str(VIGILANCIA), "--project", "p", "--host", "h.example", "--email", correo],
        cwd=RAIZ, capture_output=True, text=True, timeout=60, env=entorno,
        check=False,
    )
    argumentos = registro.read_text(encoding="utf-8") if registro.exists() else ""
    return resultado, argumentos


def test_el_falso_curl_recibe_las_llamadas(falsos) -> None:
    """Sanidad del medidor: si el guion no llamara al `curl` falso, todo lo de abajo pasaría."""
    _, argumentos = _run(falsos)
    assert "notificationChannels" in argumentos


def test_el_token_no_va_en_ningun_argumento(falsos) -> None:
    _, argumentos = _run(falsos)
    assert TOKEN not in argumentos


def test_el_correo_va_codificado_en_la_url(falsos) -> None:
    _, argumentos = _run(falsos, correo="a+b@uji.es")
    assert "a%2Bb%40uji.es" in argumentos
    assert "a+b@uji.es%22" not in argumentos


def test_un_post_rechazado_es_un_error_aunque_no_diga_error(falsos) -> None:
    resultado, _ = _run(falsos, codigo="403", respuesta='{"message":"Permission denied"}')
    assert "[ERROR]" in resultado.stderr, resultado.stdout + resultado.stderr
    assert "[creada]" not in resultado.stdout


def test_un_post_aceptado_no_es_un_error_aunque_diga_error(falsos) -> None:
    resultado, _ = _run(falsos, respuesta='{"name":"x","displayName":"error"}')
    assert "[ERROR]" not in resultado.stderr, resultado.stderr
    assert "[creada]" in resultado.stdout
