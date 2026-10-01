"""UTL.1 (issue #190) — la superficie HTTP de las utilidades de PDF.

Lo que este fichero fija, además de que las operaciones respondan:

* **Nada se guarda.** El PDF entra en la petición y sale en la respuesta; no hay `StorageService`
  ni disco de por medio, así que no hay nada que borrar después.
* **Queda constancia, y sólo de metadatos** (decisión del usuario, 2026-10-01): quién, cuándo, qué
  operación y cuántos ficheros y páginas. **Nunca el nombre del fichero ni su contenido**, que es el
  criterio del bloque REG. El nombre de un expediente ya dice de quién es.
* **Quien no tiene una organización no opera.** El registro va por organización y su columna no
  admite nulo; operar sin anotar sería un uso sin rastro, que es lo contrario de lo que se decidió.
"""
from __future__ import annotations

import io
import uuid
import zipfile

import pytest
from fastapi import HTTPException, UploadFile

#: Un nombre de fichero que dice de quién es. No puede aparecer en el registro.
NOMBRE_DELATOR = "expediente-maria-lopez-garcia.pdf"


def _pdf(paginas: int) -> bytes:
    import fitz

    doc = fitz.open()
    for i in range(paginas):
        doc.new_page().insert_text((72, 72), f"pagina {i + 1}")
    datos = doc.tobytes()
    doc.close()
    return datos


def _subida(datos: bytes, nombre: str = NOMBRE_DELATOR) -> UploadFile:
    return UploadFile(
        filename=nombre, file=io.BytesIO(datos), headers={"content-type": "application/pdf"}
    )


def _usuario(organizacion):
    from server.app.core.auth.models import UserInfo

    return UserInfo(
        user_id=str(uuid.uuid4()),
        email="persona@uji.es",
        role="user",
        organizacion_ids=[str(organizacion)] if organizacion else [],
    )


def _paginas(datos: bytes) -> int:
    import fitz

    with fitz.open(stream=datos, filetype="pdf") as doc:
        return doc.page_count


async def _eventos(db_session, organizacion):
    from sqlalchemy import select

    from server.app.modules.agents_hub.database.operational_models import HubActividadIA

    return (
        await db_session.execute(
            select(HubActividadIA).where(HubActividadIA.organizacion_id == organizacion)
        )
    ).scalars().all()


class TestUnir:

    @pytest.mark.asyncio
    async def test_devuelve_el_pdf_unido(self, db_session):
        from server.app.routers.utilidades_router import unir_pdf

        organizacion = uuid.uuid4()
        respuesta = await unir_pdf(
            files=[_subida(_pdf(2)), _subida(_pdf(3))],
            optimizar=True,
            user=_usuario(organizacion),
            session=db_session,
        )

        assert respuesta.media_type == "application/pdf"
        assert _paginas(respuesta.body) == 5
        assert "attachment" in respuesta.headers["content-disposition"]

    @pytest.mark.asyncio
    async def test_deja_constancia_sin_el_nombre_ni_el_contenido(self, db_session):
        from server.app.routers.utilidades_router import unir_pdf

        organizacion = uuid.uuid4()
        usuario = _usuario(organizacion)
        await unir_pdf(
            files=[_subida(_pdf(2)), _subida(_pdf(1))],
            optimizar=True,
            user=usuario,
            session=db_session,
        )

        eventos = await _eventos(db_session, organizacion)
        assert len(eventos) == 1
        evento = eventos[0]
        assert evento.actor == usuario.user_id
        assert evento.herramienta == "utilidades/pdf/unir"
        assert "2 PDF" in evento.finalidad and "3 páginas" in evento.finalidad
        # El nombre del expediente dice de quién es: no puede estar en ningún campo.
        campos = " ".join(str(v) for v in vars(evento).values())
        assert "maria" not in campos.lower()
        assert len(evento.payload_hash or "") == 64


class TestPartir:

    @pytest.mark.asyncio
    async def test_por_rangos_devuelve_un_zip_con_un_fichero_por_rango(self, db_session):
        from server.app.routers.utilidades_router import partir_pdf

        respuesta = await partir_pdf(
            file=_subida(_pdf(6), "expediente.pdf"),
            modo="rangos",
            rangos="1-2, 4-6",
            optimizar=True,
            user=_usuario(uuid.uuid4()),
            session=db_session,
        )

        assert respuesta.media_type == "application/zip"
        with zipfile.ZipFile(io.BytesIO(respuesta.body)) as z:
            assert sorted(z.namelist()) == ["expediente_p1-2.pdf", "expediente_p4-6.pdf"]

    @pytest.mark.asyncio
    async def test_extraer_paginas_devuelve_un_solo_pdf(self, db_session):
        from server.app.routers.utilidades_router import partir_pdf

        respuesta = await partir_pdf(
            file=_subida(_pdf(6), "expediente.pdf"),
            modo="paginas",
            rangos="1, 3, 5",
            optimizar=True,
            user=_usuario(uuid.uuid4()),
            session=db_session,
        )

        assert respuesta.media_type == "application/pdf"
        assert _paginas(respuesta.body) == 3

    @pytest.mark.asyncio
    async def test_un_rango_que_no_cabe_es_un_422_con_su_motivo(self, db_session):
        from server.app.routers.utilidades_router import partir_pdf

        organizacion = uuid.uuid4()
        with pytest.raises(HTTPException) as fallo:
            await partir_pdf(
                file=_subida(_pdf(3)),
                modo="rangos",
                rangos="2-9",
                optimizar=True,
                user=_usuario(organizacion),
                session=db_session,
            )

        assert fallo.value.status_code == 422
        assert "3 páginas" in str(fallo.value.detail)
        # Lo que no se hizo no se anota.
        assert await _eventos(db_session, organizacion) == []


class TestOptimizar:

    @pytest.mark.asyncio
    async def test_devuelve_el_pdf_reescrito(self, db_session):
        from server.app.routers.utilidades_router import optimizar_pdf

        respuesta = await optimizar_pdf(
            file=_subida(_pdf(2)), nivel=4, user=_usuario(uuid.uuid4()), session=db_session
        )

        assert _paginas(respuesta.body) == 2


class TestLoQueNoSeAcepta:

    @pytest.mark.asyncio
    async def test_lo_que_no_es_un_pdf_no_entra(self, db_session):
        from server.app.routers.utilidades_router import optimizar_pdf

        with pytest.raises(HTTPException) as fallo:
            await optimizar_pdf(
                file=_subida(b"MZ\x90\x00no soy un pdf", "trampa.pdf"),
                nivel=3,
                user=_usuario(uuid.uuid4()),
                session=db_session,
            )

        assert fallo.value.status_code == 415

    @pytest.mark.asyncio
    async def test_hay_un_tope_de_ficheros(self, db_session):
        from server.app.routers.utilidades_router import MAXIMO_FICHEROS, unir_pdf

        with pytest.raises(HTTPException) as fallo:
            await unir_pdf(
                files=[_subida(_pdf(1)) for _ in range(MAXIMO_FICHEROS + 1)],
                optimizar=False,
                user=_usuario(uuid.uuid4()),
                session=db_session,
            )

        assert fallo.value.status_code == 413

    @pytest.mark.asyncio
    async def test_sin_una_organizacion_no_se_opera(self, db_session):
        """El registro va por organización; operar sin anotar sería un uso sin rastro."""
        from server.app.routers.utilidades_router import optimizar_pdf

        with pytest.raises(HTTPException) as fallo:
            await optimizar_pdf(
                file=_subida(_pdf(1)), nivel=3, user=_usuario(None), session=db_session
            )

        assert fallo.value.status_code == 403
        assert fallo.value.detail["code"] == "ORGANIZACION_INDETERMINADA"


def test_el_router_exige_el_modulo_utilidades():
    """La dependencia de verdad, no sólo el docstring."""
    from server.app.routers.utilidades_router import router

    codigos = [
        getattr(d.dependency, "__qualname__", "") for d in router.dependencies
    ]
    assert codigos, "el router no declara dependencias"
    from server.app.routers import utilidades_router

    assert 'require_module("utilidades")' in open(
        utilidades_router.__file__, encoding="utf-8"
    ).read()
