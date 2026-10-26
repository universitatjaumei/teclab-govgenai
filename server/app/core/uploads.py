"""Validación de ficheros subidos (SEC.6).

Un multipart trae el `content_type` que decida el cliente, así que no vale como
control: hay que mirar la **extensión** y los **magic bytes** del contenido real.
Y el límite de tamaño tiene que cortar *mientras* se lee — comprobarlo después de
`await file.read()` ya implica haberse tragado el fichero entero en memoria, que
es justamente el problema.

La validación es compartida a propósito: el Bloque ING la reutilizará para
`.md`/`.txt` sin duplicar reglas.

Deploy: edge
"""
from __future__ import annotations

import posixpath
import re
import tempfile
import unicodedata
from enum import Enum
from typing import IO, NoReturn

from fastapi import HTTPException, UploadFile, status

from server.app.core.config import get_settings

MAGIC_PDF = b"%PDF-"
MAGIC_PNG = b"\x89PNG\r\n\x1a\n"
MAGIC_JPEG = b"\xff\xd8\xff"

_NOMBRE_POR_DEFECTO = "fichero"
# Todo lo que un sistema de ficheros —o una clave de objeto— puede interpretar como
# separador o como salto de nivel.
_PELIGROSOS = re.compile(r"[\\/\x00-\x1f:*?\"<>|]+")

# Tamaño de lectura y umbral a partir del cual el buffer temporal pasa de RAM a
# disco. Mantiene el consumo acotado sea cual sea el tamaño del fichero.
_CHUNK_BYTES = 64 * 1024
_SPOOL_BYTES = 1024 * 1024


class UploadKind(Enum):
    """Familias admitidas. Cada una fija extensiones y firma esperada."""

    PDF = "pdf"
    TEXT = "text"
    IMAGE = "image"


_REGLAS: dict[UploadKind, dict] = {
    UploadKind.PDF: {
        "extensiones": (".pdf",),
        "magic": (MAGIC_PDF,),
    },
    UploadKind.TEXT: {
        # Los formatos de texto no tienen firma; se validan decodificando.
        "extensiones": (".md", ".markdown", ".txt"),
        "magic": (),
    },
    UploadKind.IMAGE: {
        # Marca institucional (logotipos de plataforma, organización o asistente).
        #
        # **Sin SVG, a propósito.** Un SVG es un documento XML que admite `<script>` y
        # manejadores de eventos: servido desde el origen de la API, subir la marca sería
        # subir código ejecutable a la aplicación. Un logotipo en PNG cubre el caso real.
        #
        # **Sin WebP, y no por gusto**: su firma está partida (`RIFF` en el byte 0 y
        # `WEBP` en el 8), y la comprobación de aquí es un `startswith`. Aceptar `RIFF`
        # a secas dejaría pasar cualquier contenedor RIFF —un AVI, por ejemplo—, así que
        # antes que debilitar la firma se deja el formato fuera.
        "extensiones": (".png", ".jpg", ".jpeg"),
        "magic": (MAGIC_PNG, MAGIC_JPEG),
    },
}

# El tipo que se sirve luego, deducido de la firma real y no del `content_type` del
# multipart, que lo elige quien sube.
TIPO_POR_FIRMA: dict[bytes, str] = {
    MAGIC_PNG: "image/png",
    MAGIC_JPEG: "image/jpeg",
}


def tipo_de_imagen(contenido: bytes) -> str | None:
    """Media type de una imagen ya validada, según su firma."""
    for firma, tipo in TIPO_POR_FIRMA.items():
        if contenido.startswith(firma):
            return tipo
    return None


def default_max_bytes() -> int:
    return get_settings().max_upload_mb * 1024 * 1024


def sanitizar_nombre(filename: str | None) -> str:
    """Nombre de fichero utilizable como **último** segmento de una clave (SEC.8.2).

    El nombre lo elige quien sube, así que interpolarlo en una ruta es dejarle escribir
    donde quiera: con el backend `file` de desarrollo, un `../../../..` sale del bucket.
    Aquí se reduce a un nombre plano —sin separadores, sin niveles, sin caracteres de
    control— conservando lo que un humano reconoce, porque el nombre se le muestra luego
    en la interfaz.

    NO sustituye a `validate_upload`: esto es la ruta, aquello es el contenido.
    """
    bruto = (filename or "").strip()
    # Un %2f no es un separador para el sistema de ficheros, pero sí lo es para quien
    # decodifique la clave más tarde. Se normaliza antes de decidir.
    bruto = bruto.replace("%2f", "/").replace("%2F", "/").replace("%5c", "\\")
    bruto = unicodedata.normalize("NFC", bruto)

    # Quedarse con el último segmento, mirando las dos convenciones: el cliente puede ser
    # Windows y el servidor POSIX, o al revés.
    ultimo = posixpath.basename(bruto.replace("\\", "/"))
    limpio = _PELIGROSOS.sub("", ultimo).strip(" .")

    if not limpio or limpio in (".", ".."):
        return _NOMBRE_POR_DEFECTO
    return limpio[:200]


async def read_within_limit(file: UploadFile, *, max_bytes: int | None = None) -> bytes:
    """Lee el contenido cortando en cuanto supera el límite (SEC.8.2).

    Para las subidas cuyo tipo no está cerrado —los inputs de un workspace admiten hoja
    de cálculo, PDF o CSV según el bloque—, donde `validate_upload` no aplica pero el
    tope de tamaño sí. Devuelve `bytes` porque quien llama ya los persiste enteros.
    """
    limite = max_bytes if max_bytes is not None else default_max_bytes()
    trozos: list[bytes] = []
    escritos = 0

    while True:
        trozo = await file.read(_CHUNK_BYTES)
        if not trozo:
            break
        escritos += len(trozo)
        if escritos > limite:
            # Se corta aquí y no después: leer el fichero entero para luego rechazarlo
            # deja el DoS de memoria intacto.
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"El fichero supera el límite de {limite // (1024 * 1024)} MB.",
            )
        trozos.append(trozo)

    return b"".join(trozos)


def assert_within_document_quota(documentos_actuales: int) -> None:
    """Cuota de documentos por chatbot (SEC.6).

    Recibe el recuento ya calculado en lugar de consultarlo: `core/` es capa
    compartida y no debe importar modelos operacionales de `agents_hub`, que son
    dato del cliente final (frontera edge/cloud).

    `MAX_DOCUMENTS_PER_CHATBOT = 0` significa sin límite.
    """
    limite = get_settings().max_documents_per_chatbot
    if limite and documentos_actuales >= limite:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Este chatbot ha alcanzado el límite de {limite} documentos. "
                "Elimina alguno antes de subir más."
            ),
        )


def _rechazar(detalle: str) -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=detalle
    )


def _validar_extension(filename: str | None, extensiones: tuple[str, ...]) -> None:
    if not filename:
        _rechazar("El fichero debe tener nombre y una extensión admitida.")

    nombre = filename.lower()
    if not any(nombre.endswith(ext) for ext in extensiones):
        _rechazar(
            f"Extensión no admitida. Se aceptan: {', '.join(extensiones)}."
        )


def _validar_contenido(cabecera: bytes, magic: tuple[bytes, ...]) -> None:
    if not cabecera:
        _rechazar("El fichero está vacío.")

    if magic:
        if not any(cabecera.startswith(firma) for firma in magic):
            _rechazar(
                "El contenido del fichero no corresponde a su extensión "
                "(firma de tipo incorrecta)."
            )
        return

    # Sin firma que comprobar (texto). Decodificar no basta: bytes de control
    # como \x00\x01\x02 son UTF-8 perfectamente válido y colarían un binario.
    # El byte NUL es la señal que usa todo el mundo (git incluido) para decidir
    # que un fichero es binario; el texto legítimo no lo contiene.
    if b"\x00" in cabecera:
        _rechazar(
            "El contenido del fichero no es texto válido "
            "(parece binario disfrazado)."
        )

    try:
        cabecera.decode("utf-8")
    except UnicodeDecodeError:
        # El corte de la cabecera puede partir un carácter multibyte; se
        # descarta esa posibilidad antes de rechazar.
        try:
            cabecera[: len(cabecera) - 3].decode("utf-8")
        except UnicodeDecodeError:
            _rechazar(
                "El contenido del fichero no es texto válido "
                "(parece binario disfrazado)."
            )


async def validate_upload(
    file: UploadFile,
    *,
    kind: UploadKind,
    max_bytes: int | None = None,
) -> IO[bytes]:
    """Valida extensión, tipo real y tamaño, y devuelve el contenido validado.

    Devuelve un buffer temporal posicionado al inicio (en RAM hasta 1 MB, en
    disco a partir de ahí), **no** un `bytes`: así el consumo de memoria no
    depende del tamaño de lo que suban.

    Lanza 415 si la extensión o el contenido no cuadran, y 413 si se supera el
    límite — cortando la lectura en ese punto.
    """
    reglas = _REGLAS[kind]
    limite = max_bytes if max_bytes is not None else default_max_bytes()

    _validar_extension(file.filename, reglas["extensiones"])

    buffer = tempfile.SpooledTemporaryFile(max_size=_SPOOL_BYTES)
    escritos = 0
    cabecera = b""

    while True:
        trozo = await file.read(_CHUNK_BYTES)
        if not trozo:
            break

        if not cabecera:
            cabecera = trozo[:_CHUNK_BYTES]

        escritos += len(trozo)
        if escritos > limite:
            # Cortar aquí es el punto del ejercicio: no se sigue leyendo ni se
            # retiene lo ya leído.
            buffer.close()
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=(
                    f"El fichero supera el límite de "
                    f"{limite // (1024 * 1024)} MB."
                ),
            )

        buffer.write(trozo)

    try:
        _validar_contenido(cabecera, reglas["magic"])
    except HTTPException:
        buffer.close()
        raise

    buffer.seek(0)
    return buffer
