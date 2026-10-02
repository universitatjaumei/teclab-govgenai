"""#172 — la superficie HTTP del catálogo de agentes de unidad.

Criterio de cierre de la issue: una unidad publica un agente desde el panel, **declarando
finalidad, responsable, colectivo y fecha de revisión**; aparece en el catálogo **sólo para su
colectivo**; y quien revisa puede suspenderlo.

Se prueba por HTTP y no llamando a las funciones del router: así es como llega de verdad.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from server.app.core.auth.models import UserInfo

ORG = str(uuid.uuid4())
OTRA = str(uuid.uuid4())


def _persona(role="user", orgs=(ORG,), grupos=(), user_id=None) -> UserInfo:
    return UserInfo(
        user_id=user_id or str(uuid.uuid4()),
        email=f"{role}@uji.es",
        role=role,
        organizacion_ids=tuple(orgs),
        saml_groups=tuple(grupos),
    )


AUTORA = _persona()
ADMIN = _persona("admin")


class _Quien:
    """Quién hace la petición. Se cambia entre llamadas, como cambiaría la sesión."""

    def __init__(self) -> None:
        self.actual = AUTORA


@pytest.fixture
async def http(db_session):
    from server.app.api.deps import get_current_user, get_session
    from server.app.modules.agents_hub.database.connection import get_async_session
    from server.app.routers.agentes_router import router, router_catalogo

    quien = _Quien()
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.include_router(router_catalogo, prefix="/api/v1")

    async def _sesion():
        yield db_session

    app.dependency_overrides[get_current_user] = lambda: quien.actual
    app.dependency_overrides[get_session] = _sesion
    app.dependency_overrides[get_async_session] = _sesion
    # El módulo lo exige una dependencia del router; aquí se da por concedido.
    for dependencia in router.dependencies:
        app.dependency_overrides[dependencia.dependency] = lambda: quien.actual

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://prueba") as c:
        yield c, quien


def _declaracion(**cambios) -> dict:
    cuerpo = {
        "nombre": "Asistente de contratación menor",
        "unidad": "Servicio de Contratación",
        "prompt": "Eres el asistente de contratación de la UJI. Responde con los documentos.",
        "carpeta_url": "https://drive.google.com/drive/folders/abc123",
        "finalidad": "Orientar sobre el procedimiento de contrato menor",
        "responsable": "Jefatura del Servicio de Contratación",
        "colectivo": "organizacion",
        "grupos": [],
        "revision_prevista_en": (date.today() + timedelta(days=180)).isoformat(),
    }
    cuerpo.update(cambios)
    return cuerpo


async def _publicar(c, **cambios) -> dict:
    r = await c.post("/api/v1/agentes", json=_declaracion(**cambios))
    assert r.status_code == 201, r.text
    return r.json()


class TestPublicar:

    @pytest.mark.asyncio
    async def test_registrar_es_publicar(self, http):
        c, _ = http
        agente = await _publicar(c)

        assert agente["version"]["estado"] == "registrada"
        assert agente["version"]["version"] == 1
        assert agente["unidad"] == "Servicio de Contratación"
        assert agente["version"]["acciones_permitidas"] == ["versionar", "cargar_indice", "retirar"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "falta", ["finalidad", "responsable", "colectivo", "revision_prevista_en", "prompt"]
    )
    async def test_la_declaracion_es_obligatoria(self, http, falta):
        c, _ = http
        cuerpo = _declaracion()
        del cuerpo[falta]
        r = await c.post("/api/v1/agentes", json=cuerpo)
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_por_grupos_sin_grupos_se_rechaza(self, http):
        c, _ = http
        r = await c.post("/api/v1/agentes", json=_declaracion(colectivo="grupos", grupos=[]))
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_un_colectivo_que_no_existe_se_rechaza(self, http):
        c, _ = http
        r = await c.post("/api/v1/agentes", json=_declaracion(colectivo="estudiantes"))
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_la_carpeta_es_una_url_https(self, http):
        c, _ = http
        r = await c.post("/api/v1/agentes", json=_declaracion(carpeta_url="file:///C:/carpeta"))
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_una_fecha_de_revision_ya_pasada_se_rechaza(self, http):
        """Declararla vencida el mismo día de publicar no es declarar una revisión."""
        c, _ = http
        ayer = (date.today() - timedelta(days=1)).isoformat()
        r = await c.post("/api/v1/agentes", json=_declaracion(revision_prevista_en=ayer))
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_sin_una_organizacion_no_se_publica(self, http):
        c, quien = http
        quien.actual = _persona(orgs=(ORG, OTRA))
        r = await c.post("/api/v1/agentes", json=_declaracion())
        assert r.status_code == 403


class TestVersionar:

    @pytest.mark.asyncio
    async def test_una_version_nueva_es_la_que_se_ofrece(self, http):
        c, _ = http
        agente = await _publicar(c)
        r = await c.post(
            f"/api/v1/agentes/{agente['id']}/versiones",
            json={k: v for k, v in _declaracion(prompt="Versión 2 del prompt").items()
                  if k not in ("nombre", "unidad")},
        )
        assert r.status_code == 201, r.text
        assert r.json()["version"]["version"] == 2
        assert r.json()["version"]["prompt"] == "Versión 2 del prompt"

    @pytest.mark.asyncio
    async def test_quien_no_es_la_autora_ni_admin_no_versiona(self, http):
        c, quien = http
        agente = await _publicar(c)
        quien.actual = _persona()
        r = await c.post(
            f"/api/v1/agentes/{agente['id']}/versiones",
            json={k: v for k, v in _declaracion().items() if k not in ("nombre", "unidad")},
        )
        assert r.status_code == 403


class TestCatalogo:

    @pytest.mark.asyncio
    async def test_toda_la_organizacion_lo_ve(self, http):
        c, quien = http
        agente = await _publicar(c)

        quien.actual = _persona()
        r = await c.get("/api/v1/agentes/catalogo")
        assert r.status_code == 200
        assert [a["id"] for a in r.json()] == [agente["id"]]

    @pytest.mark.asyncio
    async def test_otra_organizacion_no_lo_ve(self, http):
        c, quien = http
        await _publicar(c)

        quien.actual = _persona(orgs=(OTRA,))
        r = await c.get("/api/v1/agentes/catalogo")
        assert r.json() == []

    @pytest.mark.asyncio
    async def test_por_grupos_solo_lo_ve_su_grupo(self, http):
        c, quien = http
        agente = await _publicar(c, colectivo="grupos", grupos=["PDI"])

        quien.actual = _persona(grupos=("pdi",))
        assert [a["id"] for a in (await c.get("/api/v1/agentes/catalogo")).json()] == [agente["id"]]

        quien.actual = _persona(grupos=("PTGAS",))
        assert (await c.get("/api/v1/agentes/catalogo")).json() == []

    @pytest.mark.asyncio
    async def test_el_catalogo_no_lleva_el_prompt(self, http):
        """El prompt vigente lo entrega la consulta (#175), que es lo que se registra."""
        c, quien = http
        await _publicar(c)
        quien.actual = _persona()
        item = (await c.get("/api/v1/agentes/catalogo")).json()[0]
        assert "prompt" not in item
        assert item["finalidad"] and item["responsable"] and item["unidad"]

    @pytest.mark.asyncio
    async def test_con_la_revision_vencida_se_sigue_ofreciendo_y_lo_dice(self, http, db_session):
        from sqlalchemy import update

        from server.app.modules.agents_hub.database.operational_models import (
            HubAgenteUnidadVersion,
        )

        c, quien = http
        await _publicar(c)
        await db_session.execute(
            update(HubAgenteUnidadVersion).values(
                revision_prevista_en=date.today() - timedelta(days=10)
            )
        )
        await db_session.commit()

        quien.actual = _persona()
        item = (await c.get("/api/v1/agentes/catalogo")).json()[0]
        assert item["revision_vencida"] is True


class TestRevisarYSuspender:

    @pytest.mark.asyncio
    async def test_quien_revisa_lo_suspende_y_deja_de_ofrecerse(self, http):
        c, quien = http
        agente = await _publicar(c)

        quien.actual = ADMIN
        r = await c.post(
            f"/api/v1/agentes/{agente['id']}/suspender", json={"motivo": "cita un criterio de 2019"}
        )
        assert r.status_code == 200, r.text
        assert r.json()["version"]["estado"] == "suspendida"
        assert r.json()["version"]["acciones_permitidas"] == ["versionar", "cargar_indice", "reactivar", "retirar"]

        quien.actual = _persona()
        assert (await c.get("/api/v1/agentes/catalogo")).json() == []

    @pytest.mark.asyncio
    async def test_la_autora_no_puede_suspenderlo(self, http):
        c, _ = http
        agente = await _publicar(c)
        r = await c.post(f"/api/v1/agentes/{agente['id']}/suspender", json={"motivo": "x"})
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_suspender_sin_motivo_es_un_422(self, http):
        c, quien = http
        agente = await _publicar(c)
        quien.actual = ADMIN
        r = await c.post(f"/api/v1/agentes/{agente['id']}/suspender", json={"motivo": " "})
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_revisar_lo_sella_y_sigue_en_uso(self, http):
        c, quien = http
        agente = await _publicar(c)
        quien.actual = ADMIN
        r = await c.post(
            f"/api/v1/agentes/{agente['id']}/revisar",
            json={"resultado": "conforme", "nota": "documentos vigentes"},
        )
        assert r.status_code == 200, r.text
        version = r.json()["version"]
        assert version["estado"] == "registrada"
        assert version["revision_resultado"] == "conforme"
        assert version["revisada_en"]

    @pytest.mark.asyncio
    async def test_reactivar_lo_vuelve_a_ofrecer(self, http):
        c, quien = http
        agente = await _publicar(c)
        quien.actual = ADMIN
        await c.post(f"/api/v1/agentes/{agente['id']}/suspender", json={"motivo": "revisar anexos"})
        r = await c.post(f"/api/v1/agentes/{agente['id']}/reactivar")
        assert r.status_code == 200
        quien.actual = _persona()
        assert len((await c.get("/api/v1/agentes/catalogo")).json()) == 1


class TestRetirar:

    @pytest.mark.asyncio
    async def test_la_autora_lo_retira_y_ya_no_admite_nada(self, http):
        c, quien = http
        agente = await _publicar(c)
        r = await c.post(f"/api/v1/agentes/{agente['id']}/retirar")
        assert r.status_code == 200
        assert r.json()["version"]["estado"] == "retirada"
        assert r.json()["version"]["acciones_permitidas"] == []

        quien.actual = _persona()
        assert (await c.get("/api/v1/agentes/catalogo")).json() == []


class TestGestion:

    @pytest.mark.asyncio
    async def test_lista_los_de_su_organizacion_con_sus_acciones(self, http):
        c, quien = http
        agente = await _publicar(c)

        quien.actual = ADMIN
        r = await c.get("/api/v1/agentes")
        assert r.status_code == 200
        cuerpo = r.json()
        assert [a["id"] for a in cuerpo["agentes"]] == [agente["id"]]
        assert "suspender" in cuerpo["agentes"][0]["version"]["acciones_permitidas"]

    @pytest.mark.asyncio
    async def test_dice_si_llegan_grupos_del_idp(self, http):
        """Con el login de Google no llegan: la pantalla tiene que poder decirlo."""
        c, _ = http
        r = await c.get("/api/v1/agentes")
        assert r.json()["grupos_del_idp"] is False

    @pytest.mark.asyncio
    async def test_de_otra_organizacion_es_un_404(self, http):
        c, quien = http
        agente = await _publicar(c)
        quien.actual = _persona("admin", orgs=(OTRA,))
        assert (await c.get("/api/v1/agentes")).json()["agentes"] == []
        r = await c.post(f"/api/v1/agentes/{agente['id']}/suspender", json={"motivo": "x"})
        assert r.status_code == 404
