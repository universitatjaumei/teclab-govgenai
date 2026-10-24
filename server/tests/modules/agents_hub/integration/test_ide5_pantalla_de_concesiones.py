"""IDE.5 — conceder y retirar módulos deja de ser un `INSERT` a mano.

Las concesiones eran filas que solo se ponían conectándose a Postgres. Una plataforma que se
entrega a otra administración no puede pedir eso: quien la administra no tiene por qué tener
acceso a la base de datos, y no debería tenerlo.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import server.app.main  # noqa: F401

from server.app.api.deps import get_current_user
from server.app.core.auth.models import UserInfo
from server.app.api.deps import get_session
from server.app.routers.hub_modulos_router import router


def _principal(role: str = "superadmin") -> UserInfo:
    return UserInfo(user_id="quien-administra", email="root@uji.es", role=role)


def _cliente(session, principal: UserInfo) -> AsyncClient:
    async def _sesion():
        yield session

    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: principal
    app.dependency_overrides[get_session] = _sesion
    app.include_router(router, prefix="/api/v1")
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _catalogo(session, retirado: str | None = None) -> None:
    from server.app.core.auth.modulos import MODULOS_INICIALES
    from server.app.modules.agents_hub.database.config_models import HubPlatformModule

    for codigo, etiqueta in MODULOS_INICIALES:
        session.add(
            HubPlatformModule(code=codigo, label=etiqueta, vigente=codigo != retirado)
        )
    await session.commit()


async def _persona(session, email: str | None = None):
    from server.app.modules.agents_hub.database.config_models import HubUser

    fila = HubUser(
        id=uuid.uuid4(),
        email=email or f"p-{uuid.uuid4().hex[:8]}@uji.es",
        role="user",
        is_active=True,
        origen="manual",
    )
    session.add(fila)
    await session.commit()
    return fila


class TestElCatalogoEsDato:

    @pytest.mark.asyncio
    async def test_should_serve_the_catalogue_from_the_table(self, db_session):
        """La pantalla itera esto; si los códigos estuvieran escritos en el frontend, añadir un
        módulo exigiría tocar el frontend."""
        await _catalogo(db_session)

        async with _cliente(db_session, _principal()) as cliente:
            respuesta = await cliente.get("/api/v1/hub/modulos/catalogo")

        codigos = [m["code"] for m in respuesta.json()]
        # La lista sale de la semilla y el orden es el que el endpoint promete: `ORDER BY code`.
        #
        # Esta comparación se hacía contra el orden de `MODULOS_INICIALES`, y **pasaba por
        # casualidad**: la semilla estaba escrita en orden alfabético. REG.6 metió `registro`
        # entre `personas` y `plataforma` —donde tiene sentido leerlo, junto al módulo del que
        # copia el criterio— y el test se puso rojo sin que nada del endpoint hubiera cambiado.
        # Se compara con `sorted` porque es lo que el endpoint garantiza; el orden en que se
        # escriba la semilla es cosa de quien la lee.
        from server.app.core.auth.modulos import MODULOS_INICIALES

        assert codigos == sorted(codigo for codigo, _etiqueta in MODULOS_INICIALES)

    @pytest.mark.asyncio
    async def test_should_mark_a_retired_module_as_such(self, db_session):
        await _catalogo(db_session, retirado="curacion")

        async with _cliente(db_session, _principal()) as cliente:
            catalogo = (await cliente.get("/api/v1/hub/modulos/catalogo")).json()

        retirado = next(m for m in catalogo if m["code"] == "curacion")
        assert retirado["vigente"] is False


class TestConcederYRetirar:

    @pytest.mark.asyncio
    async def test_should_grant_a_module_to_a_group(self, db_session):
        await _catalogo(db_session)

        async with _cliente(db_session, _principal()) as cliente:
            respuesta = await cliente.post(
                "/api/v1/hub/modulos",
                json={"subject_type": "grupo", "subject_id": "PDI", "module_code": "informes"},
            )

        assert respuesta.status_code == 201, respuesta.text
        assert respuesta.json()["subject_id"] == "PDI"
        assert respuesta.json()["granted_by"] == "quien-administra"

    # Este comprueba que la fila que escribe el endpoint es la que **encuentra** la
    # resolución, así que necesita la función de verdad y no el doble del conftest.
    @pytest.mark.sin_guarda_de_modulos
    @pytest.mark.asyncio
    async def test_should_grant_to_a_person_using_the_derived_key(self, db_session):
        """La concesión se guarda con la clave que consulta la resolución. Sin esta conversión,
        conceder desde la pantalla escribiría una fila que `modulos_del_usuario` no encuentra."""
        from server.app.core.auth.modulos_service import modulos_del_usuario
        from server.app.routers.redaccion._actor import user_to_uuid

        await _catalogo(db_session)
        persona = await _persona(db_session)

        async with _cliente(db_session, _principal()) as cliente:
            await cliente.post(
                "/api/v1/hub/modulos",
                json={
                    "subject_type": "usuario",
                    "subject_id": str(persona.id),
                    "module_code": "informes",
                },
            )

        creado = UserInfo(user_id=str(persona.id), email=persona.email, role="user")
        assert await modulos_del_usuario(db_session, creado) == ["informes"]
        # Y la fila guardada es la clave derivada, no el UUID crudo.
        from sqlalchemy import select

        from server.app.modules.agents_hub.database.config_models import HubModuleGrant

        guardado = (
            await db_session.execute(select(HubModuleGrant.subject_id))
        ).scalar_one()
        assert guardado == str(user_to_uuid(str(persona.id)))

    @pytest.mark.asyncio
    async def test_should_refuse_a_module_outside_the_catalogue(self, db_session):
        await _catalogo(db_session)

        async with _cliente(db_session, _principal()) as cliente:
            respuesta = await cliente.post(
                "/api/v1/hub/modulos",
                json={"subject_type": "grupo", "subject_id": "PDI", "module_code": "expedientes"},
            )

        assert respuesta.status_code == 404

    @pytest.mark.asyncio
    async def test_should_refuse_to_grant_a_retired_module(self, db_session):
        """Concederlo no daría acceso a nada: `modulos_del_usuario` filtra por `vigente`, así
        que la fila sería decorativa y quien la creara creería haber dado un permiso."""
        await _catalogo(db_session, retirado="curacion")

        async with _cliente(db_session, _principal()) as cliente:
            respuesta = await cliente.post(
                "/api/v1/hub/modulos",
                json={"subject_type": "grupo", "subject_id": "PDI", "module_code": "curacion"},
            )

        assert respuesta.status_code == 400

    @pytest.mark.asyncio
    async def test_should_refuse_an_unknown_subject_type(self, db_session):
        await _catalogo(db_session)

        async with _cliente(db_session, _principal()) as cliente:
            respuesta = await cliente.post(
                "/api/v1/hub/modulos",
                json={"subject_type": "departamento", "subject_id": "x", "module_code": "informes"},
            )

        assert respuesta.status_code == 422

    @pytest.mark.asyncio
    async def test_should_refuse_the_same_grant_twice(self, db_session):
        await _catalogo(db_session)
        cuerpo = {"subject_type": "grupo", "subject_id": "PDI", "module_code": "informes"}

        async with _cliente(db_session, _principal()) as cliente:
            primera = await cliente.post("/api/v1/hub/modulos", json=cuerpo)
            segunda = await cliente.post("/api/v1/hub/modulos", json=cuerpo)

        assert primera.status_code == 201
        assert segunda.status_code == 409

    @pytest.mark.asyncio
    async def test_should_revoke_a_grant(self, db_session):
        await _catalogo(db_session)

        async with _cliente(db_session, _principal()) as cliente:
            creada = await cliente.post(
                "/api/v1/hub/modulos",
                json={"subject_type": "grupo", "subject_id": "PDI", "module_code": "informes"},
            )
            borrada = await cliente.delete(f"/api/v1/hub/modulos/{creada.json()['id']}")
            quedan = await cliente.get("/api/v1/hub/modulos")

        assert borrada.status_code == 204
        assert quedan.json() == []

    @pytest.mark.asyncio
    async def test_should_be_reserved_to_a_superadmin(self, db_session):
        await _catalogo(db_session)

        async with _cliente(db_session, _principal(role="admin")) as cliente:
            respuesta = await cliente.post(
                "/api/v1/hub/modulos",
                json={"subject_type": "grupo", "subject_id": "PDI", "module_code": "informes"},
            )

        assert respuesta.status_code == 403


class TestLaFichaDiceDeDondeVieneCadaModulo:

    @pytest.mark.asyncio
    async def test_should_show_the_origin_of_each_module(self, db_session):
        await _catalogo(db_session)
        persona = await _persona(db_session)

        async with _cliente(db_session, _principal()) as cliente:
            await cliente.post(
                "/api/v1/hub/modulos",
                json={
                    "subject_type": "usuario",
                    "subject_id": str(persona.id),
                    "module_code": "informes",
                },
            )
            ficha = await cliente.get(f"/api/v1/hub/modulos/de-persona/{persona.id}")

        assert ficha.status_code == 200
        assert ficha.json()["modulos"]["informes"][0]["tipo"] == "usuario"

    @pytest.mark.asyncio
    async def test_should_return_404_for_someone_who_does_not_exist(self, db_session):
        await _catalogo(db_session)

        async with _cliente(db_session, _principal()) as cliente:
            respuesta = await cliente.get(f"/api/v1/hub/modulos/de-persona/{uuid.uuid4()}")

        assert respuesta.status_code == 404

    @pytest.mark.asyncio
    async def test_should_report_how_many_known_people_a_group_revocation_reaches(
        self, db_session
    ):
        """Un «¿seguro?» a secas no informa cuando lo que se retira alcanza a un colectivo."""
        await _catalogo(db_session)
        await _persona(db_session)
        await _persona(db_session)

        async with _cliente(db_session, _principal()) as cliente:
            respuesta = await cliente.get("/api/v1/hub/modulos/alcance-de-grupo/PDI")

        assert respuesta.status_code == 200
        assert respuesta.json()["personas_conocidas"] == 2
