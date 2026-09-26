"""Issue #109 — dar de alta a una persona con sus módulos es **un** acto, o no es ninguno.

Tres cosas que quedaron pendientes del arreglo de #100 y que la revisión de la PR #105 señaló con
razón. Van juntas porque tocan el mismo trozo de `create_user`, y este fichero es la tercera: **el
test de integración que faltaba**, el que habría cazado las otras dos.

**1. El alta y sus concesiones no eran atómicas.** La fila se confirmaba con su propio `commit` y
las concesiones después, con otro. Si el segundo fallaba quedaba **una persona creada sin los
módulos que se pidieron**, y la promesa de «se concede en el mismo acto» dejaba de cumplirse justo
cuando importa. Estaba mitigado —los códigos se validan antes de crear a nadie— pero no cerrado:
un error de base de datos en el segundo `commit` seguía dejando el estado a medias. Y ese estado
es exactamente el que la issue #100 vino a hacer visible: una persona sin acceso a nada.

**2. El aviso «Sin acceso» ignoraba las concesiones de grupo.** Se calculaba sólo con las
directas, así que el día que SAML se encienda empezaría a mentir sin que nadie toque nada — y un
aviso que miente se aprende a ignorar, que es justo lo que el aviso venía a evitar.

De las dos salidas que la issue planteaba se toma la honesta: **estrechar lo que el campo
afirma**. Resolver el acceso efectivo exige saber los grupos de cada persona, y eso viene en la
aserción del IdP, no en `hub_users`; prometerlo con los datos de aquí sería inventarlo.

**Lo que este fichero comprueba es el camino completo por HTTP y contra la base**, no los
ayudantes. Lo que había eran tests de `_a_lectura`, de `_concesiones_por_sujeto` y del contrato de
entrada: ninguno hacía `POST /hub/users` con módulos, que es donde las tres cosas se juntan. Y la
atomicidad no se puede probar con un doble de sesión, porque lo que se comprueba es justamente
que la base no se quede a medias.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from server.app.core.auth.models import UserInfo, UserRole
from server.app.core.identidad import user_to_uuid
from server.app.modules.agents_hub.database.config_models import (
    HubModuleGrant,
    HubPlatformModule,
    HubUser,
)

_SUPERADMIN = UserInfo(
    user_id="00000000-0000-0000-0000-0000000000f1",
    email="plataforma@uji.es",
    role=UserRole.SUPERADMIN.value,
)


@pytest.fixture
async def sesion(db_url: str):
    from server.app.modules.agents_hub.database.connection import (
        create_async_engine,
        create_session_factory,
    )

    motor = create_async_engine(db_url)
    fabrica = create_session_factory(motor)
    async with fabrica() as s:
        yield s
    await motor.dispose()


@pytest.fixture
async def modulo_vigente(sesion):
    """Un módulo del catálogo, porque `create_user` valida los códigos contra él."""
    codigo = f"modulo-{uuid.uuid4().hex[:8]}"
    sesion.add(HubPlatformModule(code=codigo, label="De prueba", vigente=True))
    await sesion.commit()
    return codigo


def _cliente(sesion):
    """Un cliente **asíncrono**, en el mismo bucle de eventos que la sesión.

    Con `TestClient` —que es síncrono y monta su propio bucle— la conexión de asyncpg acaba
    usándose desde dos bucles a la vez y asyncpg lo corta con «another operation is in progress».
    No es un detalle del arnés: la sesión de la prueba y la que usa el endpoint tienen que ser la
    misma para poder mirar qué quedó escrito después de un fallo.
    """
    import httpx
    from fastapi import FastAPI

    from server.app.api.deps import get_current_user
    from server.app.modules.agents_hub.database.connection import get_async_session
    from server.app.routers.hub_users_router import router

    async def _sesion_override():
        yield sesion

    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: _SUPERADMIN
    app.dependency_overrides[get_async_session] = _sesion_override
    app.include_router(router, prefix="/api/v1")
    # `raise_app_exceptions=False` para poder mirar la base después de un fallo del servidor:
    # con el valor por defecto la excepción sube y el test no llega a comprobar lo único que
    # importa, que es qué quedó escrito.
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    )


async def _concesiones_de(sesion, user_id) -> list[str]:
    sujeto = str(user_to_uuid(str(user_id)))
    filas = (
        await sesion.execute(
            select(HubModuleGrant.module_code).where(HubModuleGrant.subject_id == sujeto)
        )
    ).scalars().all()
    return sorted(filas)


class TestElAltaConModulos:

    async def test_las_concesiones_se_guardan_y_la_respuesta_las_refleja(
        self, sesion, modulo_vigente
    ) -> None:
        async with _cliente(sesion) as cliente:
            respuesta = await cliente.post(
            "/api/v1/hub/users",
            json={
                "email": f"{uuid.uuid4().hex[:8]}@uji.es",
                "display_name": "Alguien",
                "role": "user",
                "modulos": [modulo_vigente],
            },
        )

        assert respuesta.status_code == 201, respuesta.text
        cuerpo = respuesta.json()
        assert cuerpo["modulos_concedidos"] == [modulo_vigente]
        assert await _concesiones_de(sesion, cuerpo["id"]) == [modulo_vigente]

    async def test_un_codigo_retirado_no_deja_persona_a_medias(self, sesion) -> None:
        """Lo que ya estaba mitigado, fijado: validar antes de crear a nadie."""
        correo = f"{uuid.uuid4().hex[:8]}@uji.es"
        async with _cliente(sesion) as cliente:
            respuesta = await cliente.post(
            "/api/v1/hub/users",
            json={
                "email": correo,
                "display_name": "Alguien",
                "role": "user",
                "modulos": ["no-existe-este-modulo"],
            },
        )

        assert respuesta.status_code == 400
        sin_crear = (
            await sesion.execute(select(HubUser).where(HubUser.email == correo))
        ).scalars().first()
        assert sin_crear is None, "se ha creado la persona pese a rechazar sus módulos"


class TestLaAtomicidad:
    """Si las concesiones no se pueden escribir, **la persona tampoco se crea**.

    Es lo que quedaba abierto: la fila se confirmaba por su cuenta y las concesiones después. Un
    error en el segundo `commit` dejaba a alguien dado de alta sin los módulos que se pidieron —y
    sin que nadie lo supiera, porque la respuesta ya se había ido—.
    """

    async def test_si_falla_la_concesion_no_queda_la_persona(
        self, sesion, modulo_vigente, monkeypatch
    ) -> None:
        from server.app.routers import hub_users_router

        def _revienta(*_args, **_kwargs):
            raise RuntimeError("la base dice que no")

        # Falla al preparar las concesiones, que es el segundo paso del alta.
        monkeypatch.setattr(hub_users_router, "_preparar_concesiones", _revienta)

        correo = f"{uuid.uuid4().hex[:8]}@uji.es"
        async with _cliente(sesion) as cliente:
            respuesta = await cliente.post(
            "/api/v1/hub/users",
            json={
                "email": correo,
                "display_name": "Alguien",
                "role": "user",
                "modulos": [modulo_vigente],
            },
        )

        assert respuesta.status_code == 500, (
            f"se esperaba que el alta fallara, y devolvió {respuesta.status_code}"
        )
        await sesion.rollback()
        a_medias = (
            await sesion.execute(select(HubUser).where(HubUser.email == correo))
        ).scalars().first()
        assert a_medias is None, (
            "la persona quedó creada sin sus módulos: el alta y sus concesiones no son un solo "
            "acto, y eso deja exactamente el estado que la issue #100 vino a hacer visible."
        )


class TestElAvisoNoPuedeAfirmarLoQueNoSabe:
    """«Sin acceso» se calculaba con las concesiones **directas** y no con las de grupo.

    Resolver el acceso efectivo exige los grupos de cada persona, que vienen en la aserción del
    IdP y no están en `hub_users`. Con SAML apagado hoy nadie tiene concesiones de grupo, así que
    el aviso no miente **todavía**: empezaría a hacerlo el día que se encienda, sin que nadie
    toque nada. Por eso lo que se estrecha es lo que el campo afirma.
    """

    def test_el_campo_dice_que_habla_de_concesiones_directas(self) -> None:
        from server.app.routers.hub_users_router import UsuarioRead

        campos = UsuarioRead.model_fields
        assert "sin_concesion_directa" in campos, (
            "el campo sigue llamándose como si supiera el acceso efectivo. Con los datos de "
            "`hub_users` sólo se pueden ver las concesiones directas; afirmar más es inventarlo."
        )
