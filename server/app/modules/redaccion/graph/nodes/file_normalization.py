"""FileNormalizationNode — materializa los artefactos de entrada para la extracción (9R.6.1).

Copiaba el `storage_path` tal cual a `artifacts_normalized`, y los pipelines de extracción
hacen `Path(bucket) / key`: abren una **ruta del sistema de archivos**. Con `StorageService`
escribiendo bajo `STORAGE_BUCKET`, el pipeline buscaba `redaccion/<id>/inputs/…` relativo al
directorio de trabajo y no encontraba nada (`Errno 2`), y con el backend en GCS no habría
fichero que abrir en absoluto.

El nodo baja el artefacto por `StorageService` y publica la ruta del fichero temporal. Es la
conversión que su propio docstring anticipaba, y deja la regla de portabilidad en pie: quien
habla con el almacén es el servicio, y los pipelines siguen leyendo un fichero local.

El temporal se borra al terminar la ejecución (`drafting_runner`), que es la unidad de trabajo
dentro de la cual `/tmp` está permitido.
"""
from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path
from typing import Protocol

from server.app.modules.redaccion.contracts.runtime import WorkspaceState

_log = logging.getLogger(__name__)

#: Prefijo del directorio temporal de una ejecución. `drafting_runner` limpia por él.
PREFIJO_TEMPORAL = "govgenai-redaccion-"


class _StorageService(Protocol):
    async def get(self, key: str) -> bytes: ...


class FileNormalizationNode:
    """Baja cada artefacto del almacén a un fichero local y publica su ruta."""

    def __init__(self, storage_service: _StorageService) -> None:
        self._storage = storage_service

    async def __call__(self, state: WorkspaceState) -> dict:
        normalized: dict[str, str] = {}
        if not state.inputs:
            return {"artifacts_normalized": normalized}

        destino = Path(tempfile.mkdtemp(prefix=PREFIJO_TEMPORAL))
        for slot_id, artifact in state.inputs.items():
            try:
                contenido = await self._storage.get(artifact.storage_path)
            except Exception:  # noqa: BLE001
                # Un artefacto que ya no está no puede tumbar el informe entero: el bloque
                # que lo necesitaba avisará por su cuenta al no encontrarlo.
                _log.warning(
                    "No se pudo leer %s del almacén; el bloque que lo use lo advertirá",
                    artifact.storage_path,
                )
                continue

            ruta = destino / f"{slot_id}{Path(artifact.filename).suffix}"
            await asyncio.to_thread(ruta.write_bytes, contenido)
            normalized[slot_id] = str(ruta)

        return {"artifacts_normalized": normalized}
