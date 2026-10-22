"""AdminScriptExtractionPipeline — ejecución de scripts aprobados vía SandboxClient (SBX.3).

El aislamiento subprocess se delega al SandboxClient (HttpSandboxClient en producción,
LocalSandboxClient en tests). La auditoría AST defensiva se mantiene en la API:
defensa en profundidad — aunque el sandbox también audita.

Protocolo del script de usuario:
  - Variables disponibles: file_path (str), raw_text (str), options (dict)
  - El script debe asignar la variable `result` (dict) con las claves:
      tables   : list[dict]  → cada dict: name, headers, rows, source_page
      metrics  : list[dict]  → cada dict: name, value, unit (opcional)
      free_text: str | None
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from server.app.core.sandbox_client import LocalSandboxClient, SandboxClient
from server.app.modules.redaccion.pipelines.contracts import (
    ExtractionInput,
    ExtractionProvenance,
    ExtractionResult,
    ExtractionWarning,
)
from server.app.modules.redaccion.services.script_auditor import ScriptSecurityAuditor

_AUDITOR = ScriptSecurityAuditor()
_DEFAULT_TIMEOUT_SECONDS = 30
#: El techo del sandbox (`TIEMPO_MAXIMO_SEGUNDOS` en su contrato). El tiempo lo pone el contrato
#: de la plantilla, y pedir más daría un 422 del sandbox en vez de una ejecución recortada.
_TIEMPO_MAXIMO_SEGUNDOS = 300


class AdminScriptExtractionPipeline:
    """Ejecuta scripts de extracción aprobados vía SandboxClient."""

    pipeline_id = "admin_script_pipeline_v1"

    def __init__(self, client: SandboxClient | None = None, storage: Any = None) -> None:
        self._client: SandboxClient = client or LocalSandboxClient()
        # PRO.2 — el fichero se lee por `StorageService`, no del disco. Ver `_leer_fichero`.
        self._storage = storage

    def supports(self, source_kind: str) -> bool:
        return source_kind == "admin_script"

    async def extract_async(self, inp: ExtractionInput) -> ExtractionResult:
        code: str = inp.options.get("code", "")
        approved: bool = inp.options.get("approved", False)
        timeout: int = max(
            1,
            min(int(inp.options.get("timeout_seconds", _DEFAULT_TIMEOUT_SECONDS)), _TIEMPO_MAXIMO_SEGUNDOS),
        )

        if not approved:
            return ExtractionResult(
                warnings=[ExtractionWarning(
                    code="SCRIPT_NOT_APPROVED",
                    message="El script no ha sido aprobado mediante revisión HITL.",
                    severity="error",
                )],
                provenance=self._provenance(),
            )

        if not code.strip():
            return ExtractionResult(
                warnings=[ExtractionWarning(
                    code="SCRIPT_EMPTY",
                    message="No se proporcionó código de script.",
                    severity="error",
                )],
                provenance=self._provenance(),
            )

        # Defensa en profundidad: re-auditar antes de enviar al sandbox.
        audit = _AUDITOR.audit(code)
        if not audit.approved:
            summary = "; ".join(f.message for f in audit.findings[:3])
            return ExtractionResult(
                warnings=[ExtractionWarning(
                    code="SCRIPT_SECURITY_VIOLATION",
                    message=f"El script no supera la auditoría de seguridad: {summary}",
                    severity="error",
                )],
                provenance=self._provenance(),
            )

        # PRO.2 — el contenido del fichero, no su ruta.
        #
        # Aquí se construía `Path(file_ref.bucket) / file_ref.key` y se mandaba esa cadena
        # como `file_path`. Es una ruta del host de la API —y con `StorageService` sobre GCS
        # no es ni una ruta—, así que dentro del contenedor del sandbox no existía ningún
        # fichero ahí y `pd.read_excel(file_path)` fallaba **siempre**. Ningún script de
        # extracción había leído nunca su fichero por esta vía.
        file_bytes: bytes | None = None
        file_name = ""
        if inp.file_ref:
            try:
                file_bytes = await self._leer_fichero(inp.file_ref)
            except FileNotFoundError:
                return ExtractionResult(
                    warnings=[ExtractionWarning(
                        code="TEST_DATA_NOT_FOUND",
                        message=(
                            f"El fichero '{inp.file_ref.key}' no está en el almacenamiento: "
                            "vuelve a subirlo."
                        ),
                        severity="error",
                    )],
                    provenance=self._provenance(),
                )
            # El nombre importa porque pandas elige el motor por la extensión, y la clave
            # puede venir con separadores de cualquiera de los dos sistemas.
            file_name = inp.file_ref.key.replace("\\", "/").rsplit("/", 1)[-1]

        return await self._client.execute_extraction_script(
            code=code,
            file_path=None,
            raw_text=inp.raw_text,
            options=inp.options,
            timeout_seconds=timeout,
            file_bytes=file_bytes,
            file_name=file_name,
        )

    async def _leer_fichero(self, file_ref) -> bytes:
        """El contenido del fichero, del disco si ya está bajado y del almacén si no.

        `bucket` vacío con la ruta entera en `key` es la convención que VER.4 dejó para un
        artefacto **ya materializado** por `FileNormalizationNode`: dentro de una generación de
        informe el fichero está en un temporal de la ejecución y volver a pedirlo al almacén
        sería pagarlo dos veces —y en GCS, dos veces de verdad—.

        En el asistente de scripts (`/test`) no hay nada materializado: la referencia es la
        clave del almacén y de ahí se lee.
        """
        from pathlib import Path

        if not file_ref.bucket and Path(file_ref.key).is_file():
            return Path(file_ref.key).read_bytes()

        almacen = self._storage
        if almacen is None:
            from server.app.core.storage import get_storage_service

            almacen = get_storage_service()
        return await almacen.get(file_ref.key)

    def _provenance(self) -> ExtractionProvenance:
        return ExtractionProvenance(
            pipeline_id=self.pipeline_id,
            source_ref="admin_script",
            extracted_at=datetime.now(timezone.utc),
        )
