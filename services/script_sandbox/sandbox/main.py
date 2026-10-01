"""FastAPI app del microservicio script-sandbox.

Endpoints:
  - GET  /health
  - POST /execute-extraction   → JSON {result, stdout_truncated}
  - POST /execute-chart        → bytes image/png o image/svg+xml
  - POST /execute-etl          → text/csv

Códigos de error normalizados (body: {"code": "<CODE>", ...}):
  - 422 SCRIPT_AUDIT_FAILED  (con findings: list[str])
  - 422 SCRIPT_EMPTY
  - 422 FILE_NOT_BASE64       (solo /execute-extraction)
  - 422 FILE_NAME_INVALID     (solo /execute-extraction: el nombre saldría de su carpeta)
  - 422 ETL_NO_TRANSFORM      (solo /execute-etl)
  - 504 SCRIPT_TIMEOUT
  - 500 SCRIPT_EXECUTION_ERROR (con stderr_truncated: str ≤ 500 chars)
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import mimetypes
import os
import sys
import tempfile
from pathlib import Path

from fastapi import FastAPI, Response
from fastapi.responses import JSONResponse

from sandbox.auditor import ScriptSecurityAuditor
from sandbox.contracts import (
    ExecuteChartRequest,
    ExecuteEtlRequest,
    ExecuteExtractionRequest,
)
from sandbox.runner import SubprocessTimeoutError, run_subprocess
from sandbox.wrappers import (
    build_chart_wrapper,
    build_etl_wrapper,
    build_extraction_wrapper,
)

app = FastAPI(title="script-sandbox", version="0.1.0")
_AUDITOR = ScriptSecurityAuditor()

# Directorio para ficheros temporales del sandbox. En producción se monta como
# tmpfs vía docker-compose (SBX.4) con tamaño máximo.
# `or` en vez de os.environ.get(k, tempfile.gettempdir()): el segundo
# argumento de .get() se evalúa siempre (aunque la clave exista), y
# tempfile.gettempdir() falla bajo el filesystem read_only del contenedor si
# SANDBOX_TMP_DIR no está definida — con `or` solo se llama si hace falta.
_TMP_DIR = Path(os.environ.get("SANDBOX_TMP_DIR") or tempfile.gettempdir()) / "sandbox"
_TMP_DIR.mkdir(parents=True, exist_ok=True)

_STDERR_CAP = 500


def _err(status: int, code: str, **extra) -> JSONResponse:
    body: dict = {"code": code}
    body.update(extra)
    return JSONResponse(status_code=status, content=body)


def _audit_or_error(code: str) -> JSONResponse | None:
    if not code or not code.strip():
        return _err(422, "SCRIPT_EMPTY")
    audit = _AUDITOR.audit(code)
    if not audit.approved:
        return _err(422, "SCRIPT_AUDIT_FAILED", findings=list(audit.findings))
    return None


def _truncate(text: str, max_chars: int = _STDERR_CAP) -> str:
    if not text:
        return ""
    return text[:max_chars]


def _write_script(content: str, suffix: str = ".py") -> Path:
    fd, name = tempfile.mkstemp(dir=str(_TMP_DIR), suffix=suffix, text=True)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
    return Path(name)


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


@app.get("/health")
def health() -> dict:
    return {"status": "healthy"}


@app.post("/execute-extraction")
def execute_extraction(req: ExecuteExtractionRequest):
    if (err := _audit_or_error(req.code)) is not None:
        return err

    # PRO.2 — con contenido, el fichero se materializa **aquí dentro** y el script lee esa
    # ruta. La que trae el caller es del host de la API y aquí no existe.
    with tempfile.TemporaryDirectory(dir=str(_TMP_DIR)) as tmpdir:
        ruta_del_fichero = req.file_path
        if req.file_bytes_b64:
            try:
                contenido = base64.b64decode(req.file_bytes_b64, validate=True)
            except (ValueError, binascii.Error):
                return _err(422, "FILE_NOT_BASE64")
            destino = _dentro_de(tmpdir, req.file_name)
            if destino is None:
                return _err(422, "FILE_NAME_INVALID")
            destino.write_bytes(contenido)
            ruta_del_fichero = str(destino)

        # AUT.7 — el sitio donde el guion puede dejar ficheros. Va **dentro** del temporal de
        # esta ejecución, así que se borra al salir del `with`: si persistiera, la siguiente
        # ejecución entregaría los ficheros de la anterior, que es como un directorio de trabajo
        # se convierte en una fuga entre organizaciones.
        #
        # Se crea siempre, aunque no se esperen artefactos: el guion referencia `output_dir` y
        # un directorio que no existe le daría un fallo de escritura en vez de un descarte con
        # su aviso.
        salida = Path(tmpdir) / "salida"
        salida.mkdir()

        # Issue #194 — los demás ficheros del contrato, cada uno en su sitio y con su nombre.
        #
        # Van a un subdirectorio **por slot** y no todos juntos: dos slots pueden traer ficheros
        # que se llamen igual —`datos.csv` de dos fuentes distintas— y uno pisaría al otro sin
        # que nada avisara.
        entradas = Path(tmpdir) / "entradas"
        rutas: dict[str, str] = {}
        if req.file_slot and req.file_bytes_b64:
            # El principal ya está escrito: su slot apunta ahí en vez de escribirlo otra vez.
            rutas[req.file_slot] = ruta_del_fichero
        for slot, fichero in (req.ficheros_b64 or {}).items():
            try:
                contenido = base64.b64decode(fichero.contenido_b64 or "", validate=True)
            except (ValueError, binascii.Error):
                return _err(422, "FILE_NOT_BASE64", slot=slot)
            carpeta = _dentro_de(entradas, _nombre_de_slot(slot))
            destino = _dentro_de(carpeta, fichero.nombre) if carpeta is not None else None
            if destino is None:
                return _err(422, "FILE_NAME_INVALID", slot=slot)
            carpeta.mkdir(parents=True, exist_ok=True)
            destino.write_bytes(contenido)
            rutas[slot] = str(destino)

        return _ejecutar_extraccion(req, ruta_del_fichero, salida, rutas)


def _recoger_artefactos(directorio: Path, req: ExecuteExtractionRequest):
    """Los ficheros que el guion dejó, o el error de tope. Devuelve `(lista, descartados, err)`.

    **Pasarse falla en alto y no recorta.** Entregar tres de los cinco ficheros que se
    escribieron sería un resultado parcial con aspecto de completo, y quien lo recibe no tiene
    cómo notarlo.
    """
    entradas = sorted(directorio.iterdir(), key=lambda p: p.name)
    if any(p.is_dir() for p in entradas):
        return [], 0, _err(
            422,
            "ARTEFACTOS_EN_SUBDIRECTORIO",
            detalle=(
                "sólo son artefactos los ficheros que quedan directamente en `output_dir`. "
                "Escribe ahí, sin crear subdirectorios: el nombre del artefacto no puede "
                "llevar ruta."
            ),
        )

    ficheros = [p for p in entradas if p.is_file()]

    if req.artefactos_maximo <= 0:
        # No se declararon: se descartan, **y se cuenta cuántos**.
        return [], len(ficheros), None

    if len(ficheros) > req.artefactos_maximo:
        return [], 0, _err(
            422,
            "ARTEFACTOS_DE_MAS",
            producidos=len(ficheros),
            maximo=req.artefactos_maximo,
        )

    total = sum(p.stat().st_size for p in ficheros)
    if total > req.artefactos_maximo_bytes:
        return [], 0, _err(
            422,
            "ARTEFACTOS_DEMASIADO_GRANDES",
            bytes=total,
            maximo_bytes=req.artefactos_maximo_bytes,
        )

    producidos = []
    for p in ficheros:
        contenido = p.read_bytes()
        producidos.append(
            {
                "nombre": p.name,
                "media_type": mimetypes.guess_type(p.name)[0] or "application/octet-stream",
                "bytes": len(contenido),
                "sha256": hashlib.sha256(contenido).hexdigest(),
                "contenido_b64": base64.b64encode(contenido).decode("ascii"),
            }
        )
    return producidos, 0, None


def _dentro_de(base: str | Path, nombre: str | None) -> Path | None:
    """La ruta de `nombre` dentro de `base`, o `None` si se saldría de ella.

    **El nombre llega en la petición y el sandbox no se fía de él.** Quitar los directorios con
    `Path(nombre).name` no basta: `Path("..").name` es `".."`, y `base / ".."` es la carpeta de
    arriba. Por eso se resuelve la ruta y se comprueba que sigue **estrictamente dentro** de la
    base, que es la única comprobación que no depende de enumerar las formas de escaparse (PR
    #210, CodeQL).

    Sin nombre vale `entrada.bin`, como hasta aquí.
    """
    raiz = os.path.realpath(base)
    limpio = os.path.basename(nombre or "") or "entrada.bin"
    destino = os.path.realpath(os.path.join(raiz, limpio))
    if not destino.startswith(raiz + os.sep):
        return None
    return Path(destino)


def _nombre_de_slot(slot: str) -> str:
    """El slot como nombre de carpeta: legible delante y **único** detrás.

    Delante, el slot sin lo que no sea letra, cifra, `-` o `_`, para que no se salga de
    `entradas/` y para que quien depure sepa de cuál se trata. Detrás, una huella del slot
    **original**, porque quitar caracteres no es inyectivo: `a/b` y `ab` daban la misma carpeta, y
    con ficheros del mismo nombre el segundo pisaba al primero sin que nada lo dijera (PR #210).

    El servidor hace lo mismo en modo local (`sandbox_client._carpeta_del_slot`).
    """
    limpio = "".join(c for c in slot if c.isalnum() or c in "-_")[:40] or "slot"
    return f"{limpio}-{hashlib.sha256(slot.encode('utf-8')).hexdigest()[:12]}"


def _ejecutar_extraccion(
    req: ExecuteExtractionRequest,
    file_path: str,
    output_dir: Path,
    rutas_de_entrada: dict[str, str] | None = None,
):
    # Las rutas reales sustituyen a lo que viniera en `options["ficheros"]`, que eran
    # referencias de almacenamiento inservibles aquí dentro (issue #194).
    options = dict(req.options or {})
    if rutas_de_entrada:
        options["ficheros"] = rutas_de_entrada

    wrapper_code = build_extraction_wrapper(
        req.code, file_path, req.raw_text, options, str(output_dir)
    )
    wrapper_path = _write_script(wrapper_code)
    try:
        try:
            result = run_subprocess(
                [sys.executable, str(wrapper_path)],
                timeout=req.timeout_seconds,
            )
        except SubprocessTimeoutError:
            return _err(504, "SCRIPT_TIMEOUT")

        if result.returncode != 0:
            return _err(
                500,
                "SCRIPT_EXECUTION_ERROR",
                stderr_truncated=_truncate(result.stderr),
            )

        try:
            data: dict = json.loads(result.stdout)
        except (json.JSONDecodeError, ValueError):
            data = {}

        # Se recogen **después** de comprobar el código de salida: un guion que revienta a mitad
        # puede haber dejado un fichero a medio escribir, y entregarlo sería peor que no
        # entregar nada.
        artefactos, descartados, err = _recoger_artefactos(output_dir, req)
        if err is not None:
            return err

        return JSONResponse(
            status_code=200,
            content={
                "result": {
                    "tables": data.get("tables", []),
                    "metrics": data.get("metrics", []),
                    "free_text": data.get("free_text"),
                },
                "stdout_truncated": result.stdout_truncated,
                "artefactos": artefactos,
                "artefactos_descartados": descartados,
            },
        )
    finally:
        _safe_unlink(wrapper_path)


@app.post("/execute-chart")
def execute_chart(req: ExecuteChartRequest):
    if (err := _audit_or_error(req.code)) is not None:
        return err

    with tempfile.TemporaryDirectory(dir=str(_TMP_DIR)) as tmpdir:
        csv_path = Path(tmpdir) / "data.csv"
        out_path = Path(tmpdir) / f"chart.{req.output_format}"
        script_path = Path(tmpdir) / "run.py"

        csv_path.write_text(req.data_csv, encoding="utf-8")
        script_path.write_text(
            build_chart_wrapper(req.code, str(csv_path), str(out_path), req.output_format),
            encoding="utf-8",
        )

        try:
            result = run_subprocess(
                [sys.executable, str(script_path)],
                timeout=req.timeout_seconds,
            )
        except SubprocessTimeoutError:
            return _err(504, "SCRIPT_TIMEOUT")

        if result.returncode != 0:
            return _err(
                500,
                "SCRIPT_EXECUTION_ERROR",
                stderr_truncated=_truncate(result.stderr),
            )
        if not out_path.exists():
            return _err(
                500,
                "SCRIPT_EXECUTION_ERROR",
                stderr_truncated="El script no generó imagen de salida.",
            )

        media_type = "image/png" if req.output_format == "png" else "image/svg+xml"
        return Response(content=out_path.read_bytes(), media_type=media_type)


@app.post("/execute-etl")
def execute_etl(req: ExecuteEtlRequest):
    if (err := _audit_or_error(req.code)) is not None:
        return err

    with tempfile.TemporaryDirectory(dir=str(_TMP_DIR)) as tmpdir:
        in_csv = Path(tmpdir) / "in.csv"
        out_csv = Path(tmpdir) / "out.csv"
        script_path = Path(tmpdir) / "run.py"

        in_csv.write_text(req.data_csv, encoding="utf-8")
        script_path.write_text(
            build_etl_wrapper(req.code, str(in_csv), str(out_csv)),
            encoding="utf-8",
        )

        try:
            result = run_subprocess(
                [sys.executable, str(script_path)],
                timeout=req.timeout_seconds,
            )
        except SubprocessTimeoutError:
            return _err(504, "SCRIPT_TIMEOUT")

        # Sentinel: exit code 7 ⇒ el script no definió transform().
        if result.returncode == 7:
            return _err(422, "ETL_NO_TRANSFORM")

        if result.returncode != 0:
            return _err(
                500,
                "SCRIPT_EXECUTION_ERROR",
                stderr_truncated=_truncate(result.stderr),
            )
        if not out_csv.exists():
            return _err(
                500,
                "SCRIPT_EXECUTION_ERROR",
                stderr_truncated="El script no generó CSV de salida.",
            )

        return Response(content=out_csv.read_bytes(), media_type="text/csv")
