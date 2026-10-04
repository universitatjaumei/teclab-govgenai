"""Lo que encontró la revisión de la PR #221 (Copilot y CodeQL) en los agentes de unidad.

Cada test fija un defecto que existía:

* un superadministrador sin organización propia publicaba en la elegida y **no se le reconocía
  como autor**, así que se le ofrecía revisar y suspender su propio agente;
* versionar con **otra carpeta** dejaba servir el índice de la anterior hasta que el guion corriera;
* en incidencias, cambiar un informe a 👍 **dejaba guardadas** la pregunta y la respuesta;
* copiar sin poder leer la respuesta dejaba la consulta **pendiente para siempre** en validación;
* la conexión de la extensión redirigía a un destino que venía en la dirección: ahora la página
  redirige al que **devuelve el servidor**, que es el que validó.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from server.tests.modules.agentes._comun import FICHAS, persona, publicar
from server.tests.modules.agentes.test_agu1_acciones import _acciones, _agente, _persona, _version

CONSULTA = {"X-Prueba-Scopes": "agentes:consulta"}


class TestElAutorSinOrganizacion:

    def test_un_superadministrador_no_revisa_ni_suspende_lo_que_publico(self):
        superadmin = _persona(role="superadmin", orgs=())
        agente = _agente(creado_por=superadmin.user_id)
        permitidas = _acciones(_version(), superadmin, agente)
        assert "revisar" not in permitidas
        assert "suspender" not in permitidas
        assert "versionar" in permitidas

    def test_el_de_otro_si(self):
        assert "revisar" in _acciones(_version(), _persona(role="superadmin", orgs=()))


def _de_version(**cambios) -> dict:
    """Una versión se declara sin nombre ni unidad: son del agente."""
    from server.tests.modules.agentes._comun import declaracion

    cuerpo = declaracion(**cambios)
    cuerpo.pop("nombre")
    cuerpo.pop("unidad")
    return cuerpo


class TestOtraCarpeta:

    @pytest.mark.asyncio
    async def test_versionar_con_otra_carpeta_vacia_el_indice_de_la_anterior(self, http):
        c, _ = http
        agente = await publicar(c)
        await c.put(f"/api/v1/agentes/{agente['id']}/indice", json={"fichas": FICHAS})
        r = await c.post(
            f"/api/v1/agentes/{agente['id']}/versiones",
            json=_de_version(carpeta_url="https://drive.google.com/drive/folders/otra"),
        )
        assert r.status_code == 201, r.text
        assert r.json()["indice"]["fichas"] == 0
        assert r.json()["indice"]["actualizado_en"] is None
        assert (await c.get(f"/api/v1/agentes/{agente['id']}/indice")).json() == []

    @pytest.mark.asyncio
    async def test_con_la_misma_carpeta_se_conserva(self, http):
        c, _ = http
        agente = await publicar(c)
        await c.put(f"/api/v1/agentes/{agente['id']}/indice", json={"fichas": FICHAS})
        r = await c.post(f"/api/v1/agentes/{agente['id']}/versiones", json=_de_version(finalidad="Otra finalidad"))
        assert r.json()["indice"]["fichas"] == len(FICHAS)


class TestLasConversaciones:

    async def _consulta(self, c, quien, *, incidencias=False):
        agente = await publicar(c)
        await c.put(f"/api/v1/agentes/{agente['id']}/indice", json={"fichas": FICHAS})
        if incidencias:
            await c.post(f"/api/v1/agentes/{agente['id']}/registro", json={"modo": "incidencias"})
        quien.actual = persona()
        cuerpo = (await c.post(f"/api/v1/agentes/{agente['id']}/consulta", json={"consulta": "¿Importe?"}, headers=CONSULTA)).json()
        return cuerpo["consulta_id"]

    async def _fila(self, db_session, consulta_id):
        from server.app.modules.agents_hub.database.operational_models import HubAgenteConsulta

        db_session.expire_all()
        return (await db_session.execute(select(HubAgenteConsulta).where(HubAgenteConsulta.id == consulta_id))).scalar_one()

    @pytest.mark.asyncio
    async def test_en_incidencias_pasar_un_informe_a_bueno_borra_lo_que_guardo(self, http, db_session):
        c, quien = http
        consulta = await self._consulta(c, quien, incidencias=True)
        url = f"/api/v1/agentes/consultas/{consulta}/valoracion"
        await c.post(url, json={"puntuacion": -1, "motivo": "inventa", "pregunta": "¿Importe?", "respuesta": "Mal"}, headers=CONSULTA)
        await c.post(url, json={"puntuacion": 1}, headers=CONSULTA)
        fila = await self._fila(db_session, consulta)
        assert (fila.puntuacion, fila.pregunta, fila.respuesta, fila.motivo) == (1, None, None, None)

    @pytest.mark.asyncio
    async def test_copiar_para_pegar_a_mano_se_dice_y_no_queda_pendiente(self, http, db_session):
        c, quien = http
        consulta = await self._consulta(c, quien)
        r = await c.post(f"/api/v1/agentes/consultas/{consulta}/respuesta", json={"no_capturada": "copiado"}, headers=CONSULTA)
        assert r.status_code == 204, r.text
        assert (await self._fila(db_session, consulta)).respuesta_no_capturada == "copiado"


class TestLaConexionDeLaExtension:

    @pytest.mark.asyncio
    async def test_devuelve_el_destino_que_valido(self, http, monkeypatch):
        destino = "https://pgcofokabefjfmadgmeiddhfkbkebnhk.chromiumapp.org/"
        monkeypatch.setenv("AGENTES_EXTENSION_IDS", "pgcofokabefjfmadgmeiddhfkbkebnhk")
        c, _ = http
        r = await c.post("/api/v1/agentes/extension/conectar", json={"destino": destino})
        assert r.status_code == 201, r.text
        assert r.json()["destino"] == destino
