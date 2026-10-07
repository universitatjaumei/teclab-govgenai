"""Los módulos de una persona que ya existe se editan de una vez, desde Personas (2026-10-07).

**Lo que pasó.** Quien entra con su cuenta institucional queda dada de alta sola, así que lo normal
no es «crear a alguien con sus módulos» sino **darle módulos a alguien que ya está**. Eso sólo se
podía hacer en Plataforma → Módulos, con un desplegable de **un** módulo por concesión: para
darle Informes y Curación a una persona había que repetir el formulario. Y la ficha donde se ve
qué le falta, Personas, no dejaba tocarlo.

**Decisión del usuario: editarlo en Personas, marcando varios.** El servidor recibe **la lista
entera** y reconcilia en una transacción: concede lo que falta y retira lo que se ha desmarcado.
Mandar la lista, y no altas y bajas sueltas, es lo que hace que guardar sea un solo acto: o queda
como se pidió, o no cambia nada.

Dos reglas que no se ven en la pantalla:

- **Sólo se reconcilia lo que se puede conceder**: módulos vigentes y no de oficio. Una concesión a
  un módulo retirado no se ofrece en la pantalla, así que no se puede desmarcar, y borrarla por no
  venir en la lista sería retirar algo que nadie ha pedido retirar.
- **Lo que no cambia, no se toca**: una concesión que sigue marcada conserva su fila, y con ella
  cuándo y quién la concedió.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

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


async def _modulo(sesion, *, vigente: bool = True, de_oficio: bool = False) -> str:
    codigo = f"modulo-{uuid.uuid4().hex[:8]}"
    sesion.add(HubPlatformModule(code=codigo, label=codigo, vigente=vigente, de_oficio=de_oficio))
    await sesion.commit()
    return codigo


async def _persona(sesion, *, role: str = "user") -> uuid.UUID:
    ident = uuid.uuid4()
    sesion.add(
        HubUser(
            id=ident,
            email=f"p-{ident.hex[:8]}@uji.es",
            role=role,
            is_active=True,
            origen="sso",
            created_at=datetime.now(timezone.utc),
        )
    )
    await sesion.commit()
    return ident


async def _conceder(sesion, persona: uuid.UUID, codigo: str) -> int:
    fila = HubModuleGrant(
        subject_type="usuario",
        subject_id=str(user_to_uuid(str(persona))),
        module_code=codigo,
        granted_by="antes",
        granted_at=datetime.now(timezone.utc),
    )
    sesion.add(fila)
    await sesion.commit()
    return fila.id


async def _concesiones(sesion, persona: uuid.UUID) -> dict[str, int]:
    sesion.expire_all()
    filas = (
        await sesion.execute(
            select(HubModuleGrant.module_code, HubModuleGrant.id).where(
                HubModuleGrant.subject_id == str(user_to_uuid(str(persona)))
            )
        )
    ).all()
    return {codigo: ident for codigo, ident in filas}


def _cliente(sesion, principal: UserInfo = _SUPERADMIN):
    import httpx
    from fastapi import FastAPI

    from server.app.api.deps import get_current_user
    from server.app.modules.agents_hub.database.connection import get_async_session
    from server.app.routers.hub_users_router import router

    async def _sesion_override():
        yield sesion

    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: principal
    app.dependency_overrides[get_async_session] = _sesion_override
    app.include_router(router, prefix="/api/v1")
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    )


async def _poner(sesion, persona, modulos, principal: UserInfo = _SUPERADMIN):
    async with _cliente(sesion, principal) as c:
        return await c.put(f"/api/v1/hub/users/{persona}/modulos", json={"modulos": modulos})


class TestSeEditanDeUnaVez:

    @pytest.mark.asyncio
    async def test_concede_varios_de_una_vez(self, sesion):
        a, b = await _modulo(sesion), await _modulo(sesion)
        persona = await _persona(sesion)

        r = await _poner(sesion, persona, [a, b])

        assert r.status_code == 200, r.text
        assert r.json()["modulos_concedidos"] == sorted([a, b])
        assert set(await _concesiones(sesion, persona)) == {a, b}

    @pytest.mark.asyncio
    async def test_retira_lo_desmarcado_y_conserva_lo_que_sigue(self, sesion):
        a, b, c = await _modulo(sesion), await _modulo(sesion), await _modulo(sesion)
        persona = await _persona(sesion)
        fila_de_a = await _conceder(sesion, persona, a)
        await _conceder(sesion, persona, c)

        r = await _poner(sesion, persona, [a, b])

        assert r.status_code == 200, r.text
        despues = await _concesiones(sesion, persona)
        assert set(despues) == {a, b}
        assert despues[a] == fila_de_a, "lo que sigue marcado conserva su fila: cuándo y quién"

    @pytest.mark.asyncio
    async def test_no_toca_lo_que_la_pantalla_no_ofrece(self, sesion):
        """Una concesión a un módulo retirado no se puede desmarcar: no se borra por no venir."""
        retirado = await _modulo(sesion, vigente=False)
        persona = await _persona(sesion)
        await _conceder(sesion, persona, retirado)

        r = await _poner(sesion, persona, [])

        assert r.status_code == 200, r.text
        assert set(await _concesiones(sesion, persona)) == {retirado}


class TestLoQueSeRechaza:

    @pytest.mark.asyncio
    @pytest.mark.parametrize("como", ["desconocido", "retirado", "de_oficio"])
    async def test_un_codigo_que_no_se_puede_conceder_no_cambia_nada(self, sesion, como):
        bueno = await _modulo(sesion)
        malo = {
            "desconocido": "no-existe",
            "retirado": await _modulo(sesion, vigente=False),
            "de_oficio": await _modulo(sesion, de_oficio=True),
        }[como]
        persona = await _persona(sesion)

        r = await _poner(sesion, persona, [bueno, malo])

        assert r.status_code == 400, r.text
        assert malo in r.json()["detail"]
        assert await _concesiones(sesion, persona) == {}

    @pytest.mark.asyncio
    async def test_solo_lo_hace_un_superadmin(self, sesion):
        persona = await _persona(sesion)
        admin = UserInfo(user_id="adm", email="adm@uji.es", role="admin")
        r = await _poner(sesion, persona, [], principal=admin)
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_una_persona_que_no_existe_es_404(self, sesion):
        r = await _poner(sesion, uuid.uuid4(), [])
        assert r.status_code == 404


class TestLaPantallaLoSabePorElServidor:
    """Regla maestra: el botón se pinta iterando lo que dice el servidor, no con un `rol ===`."""

    def _lectura(self, *, rol_fila: str, quien: UserInfo):
        from server.app.routers.hub_users_router import _a_lectura

        fila = HubUser(
            id=uuid.uuid4(), email="x@uji.es", role=rol_fila, is_active=True, origen="sso",
            created_at=datetime.now(timezone.utc),
        )
        return _a_lectura(fila, quien=quien, modulos=[])

    def test_un_superadmin_puede_editar_los_de_una_persona(self):
        assert self._lectura(rol_fila="user", quien=_SUPERADMIN).puede_editar_modulos is True

    def test_no_los_de_otro_superadmin_que_entra_por_su_rol(self):
        assert self._lectura(rol_fila="superadmin", quien=_SUPERADMIN).puede_editar_modulos is False

    def test_un_admin_no_puede(self):
        admin = UserInfo(user_id="adm", email="adm@uji.es", role="admin")
        assert self._lectura(rol_fila="user", quien=admin).puede_editar_modulos is False
