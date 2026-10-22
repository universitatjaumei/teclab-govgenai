"""Runner de subprocesos con timeout y kill explícito.

REGLA DURA: no confiar en `subprocess.run(timeout=)` por sí solo. Implementamos
`Popen` + `wait(timeout=)` con los pipes leídos en hilos y, ante un `TimeoutExpired`,
llamamos explícitamente a `proc.kill()`, matamos el grupo y esperamos para que no quede
zombie. La excepción `SubprocessTimeoutError` carga el `Popen` ya terminado para que el
caller pueda verificar `poll() != None`.
"""
from __future__ import annotations

import os
import signal
import subprocess
import threading
from dataclasses import dataclass
from typing import Sequence


_DEFAULT_STDOUT_CAP_BYTES = 5_000_000  # 5 MB


@dataclass
class SubprocessResult:
    returncode: int
    stdout: str
    stderr: str
    stdout_truncated: bool = False


class SubprocessTimeoutError(Exception):
    """Lanzada cuando el subproceso supera el timeout; carga el `Popen` ya muerto."""

    def __init__(self, process: subprocess.Popen) -> None:
        super().__init__("Subprocess timed out")
        self.process = process


def _matar_el_grupo(proc: subprocess.Popen) -> None:
    """Mata lo que el guion dejó corriendo, siempre, haya acabado bien o no.

    Un guion puede lanzar un proceso y terminar: ese proceso sobrevivía, con el mismo uid y el
    mismo directorio temporal, y podía quedarse esperando a los ficheros de la ejecución
    siguiente —de otra organización—. Matar el grupo entero lo impide. Sólo POSIX: en Windows,
    donde corren los tests en local, no hay grupos de procesos y no hace falta.
    """
    if not hasattr(os, "killpg"):
        return
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def _lee(pipe, destino: list[str]) -> None:
    destino.append(pipe.read())


def run_subprocess(
    args: Sequence[str],
    timeout: int,
    *,
    stdout_cap_bytes: int = _DEFAULT_STDOUT_CAP_BYTES,
) -> SubprocessResult:
    """Ejecuta *args* como subproceso hijo; mata y drena en timeout.

    Raises:
        SubprocessTimeoutError: con `.process` (Popen ya matado y reapado).
    """
    proc = subprocess.Popen(
        list(args),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        # Su propia sesión y su propio grupo, para poder matar después **todo** lo que lance.
        start_new_session=True,
    )
    # Los pipes se leen en hilos y se espera **al proceso**, no al fin de los pipes, que es lo
    # que hace `communicate`. Un hijo que el guion deja corriendo hereda el stdout: con
    # `communicate` la ejecución esperaba a ese hijo hasta el timeout y devolvía un 504 en vez
    # del resultado. Ahora, en cuanto el guion acaba, se mata el grupo, los pipes se cierran y
    # los hilos terminan de leer.
    salida: list[str] = []
    errores: list[str] = []
    lectores = [
        threading.Thread(target=_lee, args=(proc.stdout, salida), daemon=True),
        threading.Thread(target=_lee, args=(proc.stderr, errores), daemon=True),
    ]
    for lector in lectores:
        lector.start()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        _matar_el_grupo(proc)
        proc.wait(timeout=2)
        for lector in lectores:
            lector.join(timeout=2)
        raise SubprocessTimeoutError(proc)
    finally:
        _matar_el_grupo(proc)
    for lector in lectores:
        lector.join(timeout=2)
    stdout = "".join(salida)
    stderr = "".join(errores)

    truncated = False
    if stdout is not None and len(stdout) > stdout_cap_bytes:
        stdout = stdout[:stdout_cap_bytes]
        truncated = True

    return SubprocessResult(
        returncode=proc.returncode if proc.returncode is not None else -1,
        stdout=stdout or "",
        stderr=stderr or "",
        stdout_truncated=truncated,
    )
