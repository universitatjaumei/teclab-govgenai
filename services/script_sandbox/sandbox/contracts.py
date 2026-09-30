"""Modelos Pydantic del contrato HTTP del sandbox."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class FicheroDeEntrada(BaseModel):
    """Un fichero de entrada con su nombre (issue #194).

    El nombre importa: pandas elige el motor por la extensión, así que perderla convierte un
    `.xlsx` en un CSV ilegible.
    """

    nombre: str = ""
    contenido_b64: str = ""


class ExecuteExtractionRequest(BaseModel):
    code: str
    file_path: str = ""
    raw_text: str = ""
    options: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int = 30
    # PRO.2 — el contenido del fichero, no su ruta.
    #
    # `file_path` era una ruta del host de la API, y dentro de este contenedor no existe
    # ningún fichero ahí: `pd.read_excel(file_path)` fallaba siempre. `/execute-chart` y
    # `/execute-etl` ya recibían el contenido (`data_csv`) y lo escribían en su temporal;
    # la extracción hace lo mismo. El nombre viaja porque pandas elige el motor por la
    # extensión.
    file_bytes_b64: str = ""
    file_name: str = ""
    # Issue #194 — de qué slot es el fichero de `file_bytes_b64`. Con él, su ruta aparece
    # también en `options["ficheros"]`, y el contenido no tiene que viajar ni escribirse dos
    # veces: el temporal es un `tmpfs` de 128 MB que comparte con los artefactos.
    file_slot: str = ""
    # Issue #194 — **los demás ficheros**, por slot.
    #
    # Hasta aquí el protocolo materializaba uno solo: el resto viajaba en `options["ficheros"]`
    # como referencias de almacenamiento, que dentro de este contenedor no son rutas de nada. O
    # sea que declarar tres slots era declarar uno y medio.
    #
    # Cada uno se materializa en el temporal de la ejecución y el guion recibe su **ruta real**
    # en `options["ficheros"]`, que es donde ya la buscaba.
    ficheros_b64: dict[str, FicheroDeEntrada] = Field(default_factory=dict)
    # AUT.7 — cuántos ficheros puede producir el guion y cuánto pueden pesar en total.
    #
    # **Los manda el caller porque los declara el contrato de la función**; el sandbox no inventa
    # un número. Cero —el defecto— significa que esta función no declaró artefactos, y entonces
    # lo que el guion escriba se descarta: la capacidad no se concede por omisión.
    artefactos_maximo: int = Field(default=0, ge=0, le=100)
    artefactos_maximo_bytes: int = Field(default=0, ge=0, le=100_000_000)


class ArtefactoProducido(BaseModel):
    """Un fichero que el guion dejó en `output_dir`.

    Viaja en base64 por el mismo camino por el que entra un fichero (`file_bytes_b64`): el
    sandbox es otro servicio y su temporal no existe para la API.
    """

    nombre: str
    media_type: str
    bytes: int
    sha256: str
    contenido_b64: str


class ExtractionPayload(BaseModel):
    tables: list[dict[str, Any]] = Field(default_factory=list)
    metrics: list[dict[str, Any]] = Field(default_factory=list)
    free_text: str | None = None


class ExecuteExtractionResponse(BaseModel):
    result: ExtractionPayload
    stdout_truncated: bool = False
    artefactos: list[ArtefactoProducido] = Field(default_factory=list)
    #: Cuántos ficheros escribió el guion sin que nadie los espere. **Se cuenta y se dice**:
    #: descartarlos en silencio deja a quien escribió el guion creyendo que su Excel se entrega.
    artefactos_descartados: int = 0


class ExecuteChartRequest(BaseModel):
    code: str
    data_csv: str
    output_format: Literal["png", "svg"] = "png"
    timeout_seconds: int = 30


class ExecuteEtlRequest(BaseModel):
    code: str
    data_csv: str
    timeout_seconds: int = 30
