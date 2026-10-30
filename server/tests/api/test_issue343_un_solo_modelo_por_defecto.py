"""#343 — un solo modelo por defecto por nivel, propósito y organización.

`get_llm_config_for_tier` se queda con la primera fila que devuelve la base, sin `ORDER BY`. Con
una sola fila por defecto da igual; con varias, el modelo que se usa lo decide el plan de la
consulta. En producción, el 30-10, había **tres** modelos de chat por defecto en el nivel 1 de
plataforma —`gemini-2.0-flash`, `llama3.1:8b` y `gemini-2.5-flash`— y salía el 2.0, que Google ya
había retirado: Curación, Informes y el Copilot fallaban a la vez, y los chatbots no, porque llevan
su propio modelo.

El relevo del panel (FIX.1) ya dejaba una sola, pero sólo para lo que pasa por la API: las dos
semillas marcaban la suya sin mirar. Ahora lo garantiza la base, con un índice único parcial, y
eso obliga a dos cosas más que se prueban aquí: que el relevo llegue a la base **antes** que la
promoción —Postgres comprueba el índice fila a fila y el ORM ordena los `UPDATE` por clave—, y que
la semilla no marque la suya si ya hay una.
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from server.app.core.auth.models import UserInfo


async def _proveedor(session) -> None:
    from server.app.modules.agents_hub.database.config_models import HubProvider

    await session.merge(HubProvider(id="google", name="Google", provider_type="google_genai"))
    await session.flush()


def _modelo(*, id=None, nombre="gemini-2.5-flash", tier=1, purpose="chat", por_defecto=True, org=None):
    from server.app.modules.agents_hub.database.config_models import HubLLMConfig

    return HubLLMConfig(
        id=id or uuid.uuid4(), provider="google", model_name=nombre, tier=tier,
        purpose=purpose, is_default=por_defecto, organizacion_id=org,
    )


async def _por_defecto(session, *, tier=1, purpose="chat") -> list[str]:
    from server.app.modules.agents_hub.database.config_models import HubLLMConfig

    session.expire_all()
    filas = (await session.execute(
        select(HubLLMConfig.model_name).where(
            HubLLMConfig.tier == tier, HubLLMConfig.purpose == purpose,
            HubLLMConfig.is_default.is_(True), HubLLMConfig.organizacion_id.is_(None),
        )
    )).scalars().all()
    return sorted(filas)


class TestLaBaseNoAdmiteDos:

    @pytest.mark.asyncio
    async def test_dos_por_defecto_en_el_mismo_nivel_de_plataforma_se_rechazan(self, db_session) -> None:
        """El caso de producción: los dos con `organizacion_id` nulo. Un índice único normal los
        dejaría pasar, porque para Postgres dos nulos son distintos."""
        await _proveedor(db_session)
        db_session.add(_modelo(nombre="gemini-2.0-flash"))
        await db_session.flush()

        db_session.add(_modelo(nombre="gemini-2.5-flash"))
        with pytest.raises(IntegrityError):
            await db_session.flush()

    @pytest.mark.asyncio
    async def test_lo_que_no_comparte_grupo_convive(self, db_session) -> None:
        """Chat y embedding en el nivel 1, otro nivel, otra organización y los no por defecto."""
        from server.app.modules.agents_hub.database.config_models import HubOrganizacion

        await _proveedor(db_session)
        org = HubOrganizacion(name=f"Org {uuid.uuid4().hex[:6]}", partner_id="p")
        db_session.add(org)
        await db_session.flush()

        db_session.add_all([
            _modelo(),
            _modelo(purpose="embedding", nombre="gemini-embedding-001"),
            _modelo(tier=2, nombre="gemini-2.5-pro"),
            _modelo(org=org.id),
            _modelo(por_defecto=False, nombre="otro"),
            _modelo(por_defecto=False, nombre="y otro"),
        ])
        await db_session.flush()


@asynccontextmanager
async def _cliente(session):
    from fastapi import FastAPI

    from server.app.api.deps import get_current_user, get_session, modulos_concedidos
    from server.app.routers.hub_llm_configs_router import router

    async def _sesion():
        yield session

    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: UserInfo(
        user_id="root", email="root@example.org", role="superadmin"
    )
    app.dependency_overrides[get_session] = _sesion
    app.dependency_overrides[modulos_concedidos] = lambda: ["plataforma"]
    app.include_router(router, prefix="/api/v1")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


#: Claves elegidas para que la promovida se ordene **antes** que la que deja de serlo: el ORM
#: emite los `UPDATE` de una tabla por clave primaria, así que sin vaciar el relevo primero la
#: promoción llegaría a la base con la otra todavía marcada.
_PRIMERA = uuid.UUID("00000000-0000-0000-0000-00000000000a")
_SEGUNDA = uuid.UUID("ffffffff-0000-0000-0000-00000000000b")


class TestElPanelReleva:

    @pytest.mark.asyncio
    async def test_promover_releva_aunque_la_promovida_vaya_antes_por_clave(self, db_session) -> None:
        await _proveedor(db_session)
        db_session.add_all([
            _modelo(id=_PRIMERA, nombre="gemini-2.5-flash", por_defecto=False),
            _modelo(id=_SEGUNDA, nombre="gemini-2.0-flash"),
        ])
        await db_session.commit()

        async with _cliente(db_session) as c:
            r = await c.patch(f"/api/v1/hub/llm-configs/{_PRIMERA}", json={"is_default": True})

        assert r.status_code == 200, r.text
        assert await _por_defecto(db_session) == ["gemini-2.5-flash"]

    @pytest.mark.asyncio
    async def test_crear_una_por_defecto_releva_a_la_anterior(self, db_session) -> None:
        await _proveedor(db_session)
        db_session.add(_modelo(nombre="gemini-2.0-flash"))
        await db_session.commit()

        async with _cliente(db_session) as c:
            r = await c.post("/api/v1/hub/llm-configs", json={
                "provider": "google", "model_name": "gemini-2.5-flash", "is_default": True,
            })

        assert r.status_code == 201, r.text
        assert await _por_defecto(db_session) == ["gemini-2.5-flash"]

    @pytest.mark.asyncio
    async def test_mover_una_por_defecto_a_otro_nivel_releva_alli(self, db_session) -> None:
        """La que ya es por defecto cambia de nivel sin tocar la marca: llega por defecto a un
        nivel que ya tenía la suya. Antes del índice quedaban dos; con él sería un 500."""
        await _proveedor(db_session)
        db_session.add_all([
            _modelo(id=_PRIMERA, nombre="gemini-2.5-flash"),
            _modelo(id=_SEGUNDA, nombre="gemini-2.5-pro", tier=2),
        ])
        await db_session.commit()

        async with _cliente(db_session) as c:
            r = await c.patch(f"/api/v1/hub/llm-configs/{_PRIMERA}", json={"tier": 2})

        assert r.status_code == 200, r.text
        assert await _por_defecto(db_session, tier=2) == ["gemini-2.5-flash"]
        assert await _por_defecto(db_session, tier=1) == []


class TestLaSemillaNoSeImpone:

    @pytest.mark.asyncio
    async def test_la_semilla_no_marca_la_suya_si_ya_hay_una(self, db_session) -> None:
        """Así se juntaron tres en producción: cada siembra marcaba la suya sin mirar."""
        from server.app.modules.agents_hub.database.seeds import _seed_llm_config

        await _proveedor(db_session)
        db_session.add(_modelo(nombre="gemini-2.5-flash"))
        await db_session.flush()

        await _seed_llm_config(db_session)
        await db_session.flush()

        assert await _por_defecto(db_session) == ["gemini-2.5-flash"]

    @pytest.mark.asyncio
    async def test_en_una_base_vacia_siembra_un_modelo_que_existe(self, db_session) -> None:
        """`gemini-2.0-flash` está retirado: sembrarlo como defecto deja rota la instalación."""
        from server.app.modules.agents_hub.database.seeds import _seed_llm_config

        await _proveedor(db_session)
        await _seed_llm_config(db_session)
        await db_session.flush()

        assert await _por_defecto(db_session) == ["gemini-2.5-flash"]


class TestDosPromocionesALaVez:

    @pytest.mark.asyncio
    async def test_si_otra_transaccion_gana_es_un_409_y_no_un_500(self, db_session, monkeypatch) -> None:
        """Revisión de la PR #347: el relevo no ve lo que otra transacción aún no ha confirmado.
        Se simula dejando sin relevar, que es lo que esa otra transacción deja a la vista."""
        from server.app.routers import hub_llm_configs_router

        async def _no_ve_nada(*_a, **_k) -> None:
            return None

        await _proveedor(db_session)
        db_session.add_all([
            _modelo(id=_PRIMERA, nombre="gemini-2.5-flash", por_defecto=False),
            _modelo(id=_SEGUNDA, nombre="gemini-2.0-flash"),
        ])
        await db_session.commit()
        monkeypatch.setattr(hub_llm_configs_router, "_relevar_default", _no_ve_nada)

        async with _cliente(db_session) as c:
            r = await c.patch(f"/api/v1/hub/llm-configs/{_PRIMERA}", json={"is_default": True})

        assert r.status_code == 409, r.text
        assert await _por_defecto(db_session) == ["gemini-2.0-flash"]
