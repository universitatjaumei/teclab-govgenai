"""Abstracción de almacenamiento de objetos basada en fsspec.

El backend se configura por variables de entorno:
  STORAGE_BACKEND  → "file" (local), "s3" (MinIO/AWS), "gcs" (Google Cloud Storage)
  STORAGE_BUCKET   → ruta base (directorio local o nombre de bucket)
  STORAGE_ENDPOINT → URL del endpoint (solo backend "s3" con endpoint personalizado)
  STORAGE_ACCESS_KEY / STORAGE_SECRET_KEY → credenciales S3/MinIO

En producción GCP las credenciales para "gcs" se leen automáticamente vía
Application Default Credentials (ADC) o GOOGLE_APPLICATION_CREDENTIALS.
"""
from __future__ import annotations

import asyncio
import os
import re
from functools import lru_cache
from typing import Protocol, runtime_checkable

import fsspec


@runtime_checkable
class StorageService(Protocol):
    async def put(self, key: str, data: bytes) -> None: ...
    async def get(self, key: str) -> bytes: ...
    async def delete(self, key: str) -> None: ...
    async def delete_prefix(self, prefix: str) -> None: ...
    async def listar(self, prefix: str) -> list[str]: ...
    async def exists(self, key: str) -> bool: ...


class ClaveNoValida(ValueError):
    """La clave se sale del bucket, así que no se resuelve."""


def validar_clave(key: str) -> str:
    """Una clave de almacenamiento no puede salirse del bucket (APER.14).

    `_full_path` concatenaba `bucket/key` sin mirar nada, así que un `../../etc/passwd` resolvía
    fuera del bucket — con el backend `file` de desarrollo, en el sistema de ficheros del
    servidor. Se comprueba **aquí** y no en cada llamante porque el riesgo no es de un módulo:
    es de cualquiera que reciba una clave de fuera, y ya hubo un caso (SEC.8.2, el nombre de
    fichero de una subida).

    `sanitizar_nombre` no sirve para esto: aquella reduce a un nombre plano, y una clave lleva
    barras legítimas (`ingestion/job.pdf`). Lo que aquí se prohíbe es **salirse**: rutas
    absolutas, unidades de Windows y cualquier `..` una vez normalizada.
    """
    bruto = (key or "").strip()
    if not bruto:
        raise ClaveNoValida("la clave está vacía")

    # Las dos convenciones: el llamante puede ser Windows y el servidor POSIX, o al revés.
    normalizada = bruto.replace("\\", "/")
    # Un `%2e%2e` no es un `..` para nosotros, pero sí para quien decodifique la clave luego.
    if "%2e" in normalizada.lower() or "%2f" in normalizada.lower():
        raise ClaveNoValida(f"«{key}» lleva separadores codificados")

    if normalizada.startswith("/") or re.match(r"^[A-Za-z]:", normalizada):
        raise ClaveNoValida(f"«{key}» es una ruta absoluta, no una clave del bucket")

    if any(segmento == ".." for segmento in normalizada.split("/")):
        raise ClaveNoValida(f"«{key}» sube de nivel: una clave no se sale del bucket")

    return key


class FsspecStorageService:

    def __init__(self, backend: str, bucket: str, **kwargs) -> None:
        # Normalizar separadores para compatibilidad Windows/GCS/S3
        self._bucket = bucket.replace("\\", "/").rstrip("/")
        self._fs = fsspec.filesystem(backend, **kwargs)

    def _full_path(self, key: str) -> str:
        # APER.14 — la clave se valida aquí, que es por donde pasan las cuatro operaciones.
        return f"{self._bucket}/{validar_clave(key)}"

    async def put(self, key: str, data: bytes) -> None:
        path = self._full_path(key)
        await asyncio.to_thread(self._sync_put, path, data)

    def _sync_put(self, path: str, data: bytes) -> None:
        parent = path.rsplit("/", 1)[0] if "/" in path else ""
        if parent:
            try:
                self._fs.makedirs(parent, exist_ok=True)
            except (FileExistsError, NotImplementedError):
                pass
        with self._fs.open(path, "wb") as f:
            f.write(data)

    async def get(self, key: str) -> bytes:
        if not await self.exists(key):
            raise FileNotFoundError(f"Key not found in storage: {key}")
        path = self._full_path(key)
        return await asyncio.to_thread(self._sync_get, path)

    def _sync_get(self, path: str) -> bytes:
        with self._fs.open(path, "rb") as f:
            return f.read()

    async def delete(self, key: str) -> None:
        path = self._full_path(key)
        await asyncio.to_thread(self._fs.rm, path)

    async def delete_prefix(self, prefix: str) -> None:
        """Borra todo lo que cuelga de `prefix`, y nada si no hay nada (#251)."""
        path = self._full_path(prefix.rstrip("/"))
        await asyncio.to_thread(self._sync_delete_prefix, path)

    def _sync_delete_prefix(self, path: str) -> None:
        if self._fs.exists(path):
            self._fs.rm(path, recursive=True)

    async def listar(self, prefix: str) -> list[str]:
        """Los nombres de lo que cuelga directamente de `prefix`, o nada si no existe (#258)."""
        path = self._full_path(prefix.rstrip("/"))
        return await asyncio.to_thread(self._sync_listar, path)

    def _sync_listar(self, path: str) -> list[str]:
        if not self._fs.exists(path):
            return []
        return sorted(
            str(hijo).replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
            for hijo in self._fs.ls(path, detail=False)
        )

    async def exists(self, key: str) -> bool:
        path = self._full_path(key)
        return await asyncio.to_thread(self._fs.exists, path)


@lru_cache(maxsize=1)
def _build_storage_service() -> FsspecStorageService:
    backend = os.environ.get("STORAGE_BACKEND", "file")
    bucket = os.environ.get("STORAGE_BUCKET", "/tmp/govgenai")
    kwargs: dict = {}
    if backend == "s3":
        endpoint = os.environ.get("STORAGE_ENDPOINT")
        if endpoint:
            kwargs["endpoint_url"] = endpoint
        kwargs["key"] = os.environ.get("STORAGE_ACCESS_KEY", "")
        kwargs["secret"] = os.environ.get("STORAGE_SECRET_KEY", "")
    return FsspecStorageService(backend=backend, bucket=bucket, **kwargs)


def get_storage_service() -> FsspecStorageService:
    return _build_storage_service()
