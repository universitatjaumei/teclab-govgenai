"""UTL.2 (issue #191) — la superficie HTTP de anonimizar un fichero.

Tres llamadas, porque la persona decide entre medias y el servidor no guarda nada:

1. `analizar` — propone tipo y regla por columna, y da la **semilla** de esta sesión de trabajo.
2. `vista-previa` — aplica las reglas con esa semilla y enseña las primeras filas, antes y después.
3. `descargar` — lo mismo sobre el fichero entero, **sólo si se confirma que se ha revisado**.

El fichero se vuelve a subir en cada llamada en vez de guardarse entre ellas: es lo que hace que
«no se guarda el fichero más allá de la operación» sea literal.

Y sólo `descargar` deja constancia, porque es la única que produce algo que sale de aquí: qué
fichero —por su huella, no por su nombre—, cuántas filas y qué regla a cada tipo de columna.
"""
from __future__ import annotations

import io
import json
import uuid

import pytest
from fastapi import HTTPException, UploadFile

LISTADO = (
    "Nombre completo;DNI;Observaciones\n"
    "Ana García López;12345678Z;Hablar con Ana García\n"
    "Joan Puig Soler;87654321X;Sin incidencias\n"
).encode("utf-8")

NOMBRE_DELATOR = "listado-becas-maria-lopez.csv"


def _subida(datos: bytes = LISTADO, nombre: str = NOMBRE_DELATOR) -> UploadFile:
    return UploadFile(filename=nombre, file=io.BytesIO(datos), headers={"content-type": "text/csv"})


def _usuario(organizacion):
    from server.app.core.auth.models import UserInfo

    return UserInfo(
        user_id=str(uuid.uuid4()),
        email="persona@uji.es",
        role="user",
        organizacion_ids=[str(organizacion)] if organizacion else [],
    )


REGLAS = json.dumps(
    {
        "Nombre completo": {"tipo": "PERSON_NAME", "modo": "INITIALS"},
        "DNI": {"tipo": "DNI", "modo": "AEPD"},
        "Observaciones": {"tipo": "TEXTO", "modo": "TEXTO"},
    }
)


async def _eventos(db_session, organizacion):
    from sqlalchemy import select

    from server.app.modules.agents_hub.database.operational_models import HubActividadIA

    return (
        await db_session.execute(
            select(HubActividadIA).where(HubActividadIA.organizacion_id == organizacion)
        )
    ).scalars().all()


class TestAnalizar:

    @pytest.mark.asyncio
    async def test_propone_por_columna_y_da_una_semilla(self):
        from server.app.routers.utilidades_router import analizar_fichero

        respuesta = await analizar_fichero(file=_subida(), user=_usuario(uuid.uuid4()))

        columnas = {c.columna: c for c in respuesta.columnas}
        assert columnas["DNI"].modo == "AEPD"
        assert respuesta.formato == "csv"
        assert respuesta.filas == 2
        assert isinstance(respuesta.semilla, int)


class TestVistaPrevia:

    @pytest.mark.asyncio
    async def test_ensena_antes_y_despues(self):
        from server.app.routers.utilidades_router import vista_previa_anonimizacion

        vista = await vista_previa_anonimizacion(
            file=_subida(), reglas=REGLAS, semilla=5, user=_usuario(uuid.uuid4())
        )

        assert vista.columnas == ["Nombre completo", "DNI", "Observaciones"]
        assert vista.antes[0][1] == "12345678Z"
        assert vista.despues[0][1] == "***4567**"
        assert vista.despues[0][0] == "A. G. L."

    @pytest.mark.asyncio
    async def test_una_regla_mal_escrita_es_un_422(self):
        from server.app.routers.utilidades_router import vista_previa_anonimizacion

        with pytest.raises(HTTPException) as fallo:
            await vista_previa_anonimizacion(
                file=_subida(), reglas="{no es json", semilla=5, user=_usuario(uuid.uuid4())
            )

        assert fallo.value.status_code == 422


class TestDescargar:

    @pytest.mark.asyncio
    async def test_sin_confirmar_la_revision_no_se_descarga(self, db_session):
        """Un falso negativo aquí es un dato personal publicado: la revisión no es opcional."""
        from server.app.routers.utilidades_router import descargar_anonimizado

        organizacion = uuid.uuid4()
        with pytest.raises(HTTPException) as fallo:
            await descargar_anonimizado(
                file=_subida(), reglas=REGLAS, semilla=5, revisado=False,
                user=_usuario(organizacion), session=db_session,
            )

        assert fallo.value.status_code == 422
        assert await _eventos(db_session, organizacion) == []

    @pytest.mark.asyncio
    async def test_descarga_lo_mismo_que_enseno_la_vista_previa(self, db_session):
        from server.app.routers.utilidades_router import (
            descargar_anonimizado,
            vista_previa_anonimizacion,
        )

        usuario = _usuario(uuid.uuid4())
        reglas = json.dumps({"Nombre completo": {"tipo": "PERSON_NAME", "modo": "FAKER"}})
        vista = await vista_previa_anonimizacion(
            file=_subida(), reglas=reglas, semilla=9, user=usuario
        )
        respuesta = await descargar_anonimizado(
            file=_subida(), reglas=reglas, semilla=9, revisado=True,
            user=usuario, session=db_session,
        )

        lineas = respuesta.body.decode("utf-8-sig").splitlines()
        assert lineas[1].split(";")[0] == vista.despues[0][0]
        assert "Ana García López" not in respuesta.body.decode("utf-8-sig")

    @pytest.mark.asyncio
    async def test_deja_constancia_de_las_reglas_y_no_del_contenido(self, db_session):
        from server.app.routers.utilidades_router import descargar_anonimizado

        organizacion = uuid.uuid4()
        await descargar_anonimizado(
            file=_subida(), reglas=REGLAS, semilla=5, revisado=True,
            user=_usuario(organizacion), session=db_session,
        )

        eventos = await _eventos(db_session, organizacion)
        assert len(eventos) == 1
        evento = eventos[0]
        assert evento.herramienta == "utilidades/anonimizar:csv"
        assert "DNI→AEPD" in evento.finalidad
        assert "datos_identificativos" in evento.categorias_datos
        campos = " ".join(str(v) for v in vars(evento).values()).lower()
        for prohibido in ("maria", "ana garcía", "12345678z"):
            assert prohibido not in campos

    @pytest.mark.asyncio
    async def test_sin_una_organizacion_no_se_descarga(self, db_session):
        from server.app.routers.utilidades_router import descargar_anonimizado

        with pytest.raises(HTTPException) as fallo:
            await descargar_anonimizado(
                file=_subida(), reglas=REGLAS, semilla=5, revisado=True,
                user=_usuario(None), session=db_session,
            )

        assert fallo.value.status_code == 403
