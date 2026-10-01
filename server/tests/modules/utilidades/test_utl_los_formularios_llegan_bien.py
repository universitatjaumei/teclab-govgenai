"""UTL — los endpoints reciben lo que manda un navegador: un formulario multipart, todo texto.

**Por qué existe.** Los demás tests de este directorio llaman a las funciones del router con
valores ya tipados (`nivel=4`, `revisado=True`), y así se saltan el tramo que convierte el
formulario. En ese tramo había un defecto: con `nivel: Literal[1, 2, 3, 4]`, el `"3"` que manda el
navegador **no se convierte** a entero y el servidor respondía 422 — optimizar estaba roto desde la
pantalla y todos los tests en verde. Lo destapó la verificación contra el servidor de verdad.

Aquí cada endpoint recibe lo que de verdad le llega: ficheros y texto.
"""
from __future__ import annotations

import json
import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


def _pdf(paginas: int) -> bytes:
    import pymupdf as fitz

    doc = fitz.open()
    for i in range(paginas):
        doc.new_page().insert_text((72, 72), f"pagina {i + 1}")
    datos = doc.tobytes()
    doc.close()
    return datos


LISTADO = "Nombre completo;DNI\nAna García López;12345678Z\n".encode("utf-8")


@pytest.fixture
async def cliente(db_session):
    from server.app.api.deps import get_current_user, get_session
    from server.app.core.auth.models import UserInfo
    from server.app.routers.utilidades_router import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    usuario = UserInfo(
        user_id=str(uuid.uuid4()), email="persona@uji.es", role="user",
        organizacion_ids=[str(uuid.uuid4())],
    )

    async def _sesion():
        yield db_session

    app.dependency_overrides[get_current_user] = lambda: usuario
    app.dependency_overrides[get_session] = _sesion
    # El módulo lo exige una dependencia del router; aquí se da por concedido.
    for dependencia in router.dependencies:
        app.dependency_overrides[dependencia.dependency] = lambda: usuario

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://prueba") as c:
        yield c


class TestPdf:

    @pytest.mark.asyncio
    @pytest.mark.parametrize("nivel", ["1", "2", "3", "4"])
    async def test_optimizar_con_el_nivel_como_texto(self, cliente, nivel):
        r = await cliente.post(
            "/api/v1/utilidades/pdf/optimizar",
            files={"file": ("doc.pdf", _pdf(2), "application/pdf")},
            data={"nivel": nivel},
        )
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "application/pdf"

    @pytest.mark.asyncio
    async def test_un_nivel_que_no_existe_es_un_422(self, cliente):
        r = await cliente.post(
            "/api/v1/utilidades/pdf/optimizar",
            files={"file": ("doc.pdf", _pdf(1), "application/pdf")},
            data={"nivel": "7"},
        )
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_unir_con_optimizar_como_texto(self, cliente):
        r = await cliente.post(
            "/api/v1/utilidades/pdf/unir",
            files=[
                ("files", ("a.pdf", _pdf(1), "application/pdf")),
                ("files", ("b.pdf", _pdf(2), "application/pdf")),
            ],
            data={"optimizar": "false"},
        )
        assert r.status_code == 200, r.text

    @pytest.mark.asyncio
    async def test_partir_con_modo_y_rangos_como_texto(self, cliente):
        r = await cliente.post(
            "/api/v1/utilidades/pdf/partir",
            files={"file": ("exp.pdf", _pdf(4), "application/pdf")},
            data={"modo": "rangos", "rangos": "1-2, 3-4", "optimizar": "true"},
        )
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "application/zip"


class TestAnonimizar:

    @pytest.mark.asyncio
    async def test_los_tres_pasos_con_semilla_y_revisado_como_texto(self, cliente):
        fichero = {"file": ("listado.csv", LISTADO, "text/csv")}
        analisis = await cliente.post("/api/v1/utilidades/anonimizar/analizar", files=fichero)
        assert analisis.status_code == 200, analisis.text
        semilla = str(analisis.json()["semilla"])
        reglas = json.dumps({"DNI": {"tipo": "DNI", "modo": "AEPD"}})

        vista = await cliente.post(
            "/api/v1/utilidades/anonimizar/vista-previa",
            files=fichero, data={"reglas": reglas, "semilla": semilla},
        )
        assert vista.status_code == 200, vista.text

        descarga = await cliente.post(
            "/api/v1/utilidades/anonimizar/descargar",
            files=fichero, data={"reglas": reglas, "semilla": semilla, "revisado": "true"},
        )
        assert descarga.status_code == 200, descarga.text
        assert "***4567**" in descarga.content.decode("utf-8-sig")
