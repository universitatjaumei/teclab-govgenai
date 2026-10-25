"""Tests SEC.8.2 — subidas que no pasaban por la validación de SEC.6.

SEC.6 endureció las subidas de corpus, pero dos caminos posteriores se quedaron fuera:

- El **input de un workspace de redacción** interpolaba el `filename` del cliente en la
  clave de almacenamiento (`redaccion/{ws}/inputs/{slot}/{filename}`) y leía el fichero
  entero con `file.read()` sin tope. Con el backend `file` —el de desarrollo, que escribe
  en disco— un nombre con `../` sale del bucket.
- Los **datos de prueba de un script** se leían igual, sin límite de tamaño.

Los dos son de usuario autenticado, así que el vector no es anónimo; lo que estaba abierto
era escribir fuera del bucket y agotar la memoria del proceso con una subida grande.
"""
from __future__ import annotations

import io

import pytest
from fastapi import HTTPException, UploadFile


def _upload(nombre: str, contenido: bytes = b"x") -> UploadFile:
    return UploadFile(filename=nombre, file=io.BytesIO(contenido))


# ───────────────────── Nombre de fichero ─────────────────────


class TestNombreSeguro:
    """El nombre lo elige quien sube, así que no puede llegar a una ruta tal cual."""

    def test_should_strip_parent_directory_traversal(self):
        from server.app.core.uploads import sanitizar_nombre

        assert ".." not in sanitizar_nombre("../../../../etc/cron.d/evil")

    def test_should_keep_only_the_basename(self):
        from server.app.core.uploads import sanitizar_nombre

        assert sanitizar_nombre("carpeta/otra/informe.xlsx") == "informe.xlsx"
        assert sanitizar_nombre(r"C:\Windows\System32\algo.pdf") == "algo.pdf"

    def test_should_never_return_an_absolute_or_empty_name(self):
        from server.app.core.uploads import sanitizar_nombre

        for entrada in ("/", "..", "", "   ", "/////"):
            resultado = sanitizar_nombre(entrada)
            assert resultado, f"{entrada!r} produjo un nombre vacío"
            assert not resultado.startswith(("/", "\\"))
            assert resultado != ".."

    def test_should_preserve_a_reasonable_name_untouched(self):
        """Endurecer no puede significar destrozar los nombres legítimos: el nombre
        se le enseña al usuario en la interfaz."""
        from server.app.core.uploads import sanitizar_nombre

        assert sanitizar_nombre("Informe anual 2026.xlsx") == "Informe anual 2026.xlsx"

    def test_should_neutralize_separators_hidden_in_the_name(self):
        from server.app.core.uploads import sanitizar_nombre

        resultado = sanitizar_nombre("..%2f..%2fetc%2fpasswd")
        assert "/" not in resultado
        assert "\\" not in resultado


# ───────────────────── Lectura con tope ─────────────────────


class TestLecturaConTope:

    async def test_should_reject_content_over_the_limit(self):
        from server.app.core.uploads import read_within_limit

        with pytest.raises(HTTPException) as exc:
            await read_within_limit(_upload("grande.bin", b"a" * 5_000), max_bytes=1_000)
        assert exc.value.status_code == 413

    async def test_should_return_the_content_when_it_fits(self):
        from server.app.core.uploads import read_within_limit

        datos = await read_within_limit(_upload("ok.bin", b"hola"), max_bytes=1_000)
        assert datos == b"hola"

    async def test_should_stop_reading_once_the_limit_is_exceeded(self):
        """Igual que en SEC.6: cortar después de habérselo tragado no arregla el DoS."""
        from server.app.core.uploads import read_within_limit

        class _Contadora(io.BytesIO):
            def __init__(self, datos: bytes) -> None:
                super().__init__(datos)
                self.leidos = 0

            def read(self, size: int = -1) -> bytes:  # type: ignore[override]
                trozo = super().read(size)
                self.leidos += len(trozo)
                return trozo

        fuente = _Contadora(b"a" * 10_000_000)
        with pytest.raises(HTTPException):
            await read_within_limit(
                UploadFile(filename="bomba.bin", file=fuente), max_bytes=1_000
            )

        assert fuente.leidos < 10_000_000, (
            "se leyó el fichero entero pese a superar el límite en el primer trozo"
        )


# ───────────────────── El endpoint ─────────────────────


class TestSubidaDeInputDeWorkspace:

    def test_should_not_write_outside_the_bucket_with_a_traversal_filename(self):
        """La comprobación es sobre la CLAVE que se manda a StorageService: es lo que
        decide dónde acaba el byte, y es lo que el `filename` del cliente controlaba."""
        import uuid
        from datetime import datetime, timezone
        from unittest.mock import AsyncMock, MagicMock

        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from server.app.api.deps import get_current_user, get_session
        from server.app.core.auth.models import UserInfo
        from server.app.routers.redaccion.workspaces_router import (
            get_storage_service,
            router,
        )

        workspace_id = uuid.uuid4()
        user_id = uuid.uuid4()

        workspace = MagicMock()
        workspace.id = workspace_id
        workspace.owner_id = user_id
        workspace.inputs_json = {}
        workspace.updated_at = datetime.now(timezone.utc)

        session = AsyncMock()
        session.get = AsyncMock(return_value=workspace)
        session.commit = AsyncMock()

        storage = MagicMock()
        storage.put = AsyncMock()

        app = FastAPI()

        async def _sesion():
            yield session

        app.dependency_overrides[get_session] = _sesion
        app.dependency_overrides[get_current_user] = lambda: UserInfo(
            user_id=str(user_id), email="u@uji.es", role="user"
        )
        app.dependency_overrides[get_storage_service] = lambda: storage
        app.include_router(router, prefix="/api/v1")

        with TestClient(app) as cliente:
            cliente.post(
                f"/api/v1/redaccion/workspaces/{workspace_id}/inputs/slot_1",
                files={"file": ("../../../../etc/cron.d/evil", b"contenido", "text/plain")},
            )

        if storage.put.await_args is not None:
            clave = storage.put.await_args.args[0]
            assert ".." not in clave, f"la clave sale del bucket: {clave}"
            assert clave.startswith(f"redaccion/{workspace_id}/inputs/slot_1/")
