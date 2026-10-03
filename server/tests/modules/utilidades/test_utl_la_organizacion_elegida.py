"""Quien no pertenece a una sola organización opera sobre la que ha elegido en el panel.

Lo encontró el usuario en las pruebas manuales (2026-10-03): como superadministrador, con una
organización elegida en el selector, anonimizar un fichero respondía «tu cuenta no pertenece a
una sola». El uso tiene que anotarse en el registro de **alguna** organización, y la regla era
correcta en eso; lo que faltaba es dejar decir cuál.

La convención es la del resto de la plataforma (el catálogo de categorías del registro, por
ejemplo): `organizacion_id` opcional; si no viene, la única del principal; **y siempre
comprobado**, porque si no cualquiera anotaría usos en el registro de otra organización.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

ORG = str(uuid.uuid4())
OTRA = str(uuid.uuid4())
LISTADO = "Nombre completo;DNI\nAna García López;12345678Z\n".encode("utf-8")


def _persona(role="user", orgs=(ORG,)):
    from server.app.core.auth.models import UserInfo

    return UserInfo(
        user_id=str(uuid.uuid4()), email=f"{role}@uji.es", role=role, organizacion_ids=tuple(orgs)
    )


class _Quien:
    def __init__(self) -> None:
        self.actual = _persona()


@pytest.fixture
async def http(db_session):
    from server.app.api.deps import get_current_user, get_session
    from server.app.routers.utilidades_router import router

    quien = _Quien()
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    async def _sesion():
        yield db_session

    app.dependency_overrides[get_current_user] = lambda: quien.actual
    app.dependency_overrides[get_session] = _sesion
    for dependencia in router.dependencies:
        app.dependency_overrides[dependencia.dependency] = lambda: quien.actual

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://prueba") as c:
        yield c, quien


async def _descargar(c, organizacion_id: str | None = None):
    import json

    params = {"organizacion_id": organizacion_id} if organizacion_id else {}
    return await c.post(
        "/api/v1/utilidades/anonimizar/descargar",
        params=params,
        files={"file": ("listado.csv", LISTADO, "text/csv")},
        data={
            "reglas": json.dumps({"Nombre completo": {"tipo": "PERSON_NAME", "modo": "FAKER"}}),
            "semilla": "7",
            "revisado": "true",
        },
    )


async def _registrado_en(db_session) -> list[str]:
    from server.app.modules.agents_hub.database.operational_models import HubActividadIA

    return [str(f.organizacion_id) for f in (await db_session.execute(select(HubActividadIA))).scalars()]


@pytest.mark.asyncio
async def test_el_superadmin_opera_sobre_la_organizacion_elegida_y_se_anota_alli(http, db_session):
    c, quien = http
    quien.actual = _persona("superadmin", orgs=())
    r = await _descargar(c, ORG)
    assert r.status_code == 200, r.text
    assert await _registrado_en(db_session) == [ORG]


@pytest.mark.asyncio
async def test_sin_elegir_ninguna_lo_dice_y_dice_como_arreglarlo(http):
    c, quien = http
    quien.actual = _persona("superadmin", orgs=())
    r = await _descargar(c)
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "ORGANIZACION_INDETERMINADA"
    assert "selector" in r.json()["detail"]["message"]


@pytest.mark.asyncio
async def test_nadie_anota_en_el_registro_de_una_organizacion_que_no_es_suya(http, db_session):
    c, quien = http
    quien.actual = _persona("admin", orgs=(ORG,))
    r = await _descargar(c, OTRA)
    assert r.status_code == 403
    assert await _registrado_en(db_session) == []


@pytest.mark.asyncio
async def test_quien_es_de_una_sola_no_tiene_que_decir_nada(http, db_session):
    c, quien = http
    r = await _descargar(c)
    assert r.status_code == 200, r.text
    assert await _registrado_en(db_session) == [ORG]


@pytest.mark.asyncio
async def test_el_pdf_tambien(http, db_session):
    import pymupdf as fitz

    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "pagina")
    pdf = doc.tobytes()
    doc.close()

    c, quien = http
    quien.actual = _persona("superadmin", orgs=())
    r = await c.post(
        "/api/v1/utilidades/pdf/optimizar",
        params={"organizacion_id": ORG},
        files={"file": ("doc.pdf", pdf, "application/pdf")},
        data={"nivel": "2"},
    )
    assert r.status_code == 200, r.text
    assert await _registrado_en(db_session) == [ORG]
