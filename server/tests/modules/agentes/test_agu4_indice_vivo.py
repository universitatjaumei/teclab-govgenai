"""#174 — el índice se mantiene solo: frescura, integridad y el prompt de resumen.

Decisión del usuario (2026-10-03): el índice es **dinámico**. Lo mantiene un guion de Apps Script
que corre a diario en el Drive de la unidad; subir la hoja a mano queda como vía secundaria.

Lo que fija este fichero:

* **Se sabe cuándo se actualizó por última vez**, también cuando no cambió nada: un guion que corre
  y no encuentra cambios está vivo, y uno que no corre está muerto aunque el índice parezca bien.
* **Un índice parado avisa, no oculta**: el agente se sigue ofreciendo, marcado. Mismo criterio
  que la revisión vencida.
* **La carpeta se cuenta contra el índice.** Un documento que no llega a la ficha no existe para el
  agente y nadie recibe un error; contar es lo que convierte ese fallo silencioso en uno visible.
* **El prompt de resumen lo sirve la plataforma, versionado**, y cada ficha anota con qué versión
  se resumió: si cambia, la plataforma dice cuántas fichas han quedado desfasadas. Regenerar es
  decisión de la unidad, no automático.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from server.tests.modules.agentes._comun import FICHAS, persona, publicar


async def _cargar(c, agente_id, fichas=FICHAS, **extra):
    r = await c.put(f"/api/v1/agentes/{agente_id}/indice", json={"fichas": fichas, **extra})
    assert r.status_code == 200, r.text
    return r.json()


async def _agente(c, agente_id) -> dict:
    agentes = (await c.get("/api/v1/agentes")).json()["agentes"]
    return next(a for a in agentes if a["id"] == agente_id)


class TestFrescura:

    @pytest.mark.asyncio
    async def test_sin_cargar_nunca_no_hay_fecha_ni_aviso(self, http):
        c, _ = http
        agente = await publicar(c)
        assert agente["indice"]["actualizado_en"] is None
        assert agente["indice"]["sin_actualizar"] is False

    @pytest.mark.asyncio
    async def test_por_api_queda_la_fecha_y_que_lo_mantiene_el_guion(self, http):
        c, _ = http
        agente = await publicar(c)
        await _cargar(c, agente["id"])
        indice = (await _agente(c, agente["id"]))["indice"]
        assert indice["actualizado_en"] is not None
        assert indice["origen"] == "guion"

    @pytest.mark.asyncio
    async def test_subiendo_la_hoja_el_origen_es_la_hoja(self, http):
        c, _ = http
        agente = await publicar(c)
        hoja = "url;titulo;resumen\nhttps://drive.google.com/file/d/1;T;Resumen.\n".encode("utf-8")
        r = await c.post(
            f"/api/v1/agentes/{agente['id']}/indice/hoja",
            files={"file": ("indice.csv", hoja, "text/csv")},
        )
        assert r.status_code == 200, r.text
        assert (await _agente(c, agente["id"]))["indice"]["origen"] == "hoja"

    @pytest.mark.asyncio
    async def test_una_carga_sin_cambios_tambien_refresca_la_fecha(self, http, db_session):
        """El guion que corre y no encuentra nada nuevo está vivo."""
        from sqlalchemy import update

        from server.app.modules.agents_hub.database.operational_models import HubAgenteUnidad

        c, _ = http
        agente = await publicar(c)
        await _cargar(c, agente["id"])
        hace_una_semana = datetime.now(timezone.utc) - timedelta(days=7)
        await db_session.execute(update(HubAgenteUnidad).values(indice_actualizado_en=hace_una_semana))
        await db_session.commit()

        informe = await _cargar(c, agente["id"])
        assert informe["sin_cambios"] == 2
        indice = (await _agente(c, agente["id"]))["indice"]
        assert datetime.fromisoformat(indice["actualizado_en"]) > hace_una_semana + timedelta(days=6)
        assert indice["sin_actualizar"] is False

    @pytest.mark.asyncio
    async def test_un_guion_parado_avisa_en_la_gestion_y_en_el_catalogo(self, http, db_session):
        from sqlalchemy import update

        from server.app.modules.agents_hub.database.operational_models import HubAgenteUnidad

        c, quien = http
        agente = await publicar(c)
        await _cargar(c, agente["id"])
        await db_session.execute(
            update(HubAgenteUnidad).values(
                indice_actualizado_en=datetime.now(timezone.utc) - timedelta(days=4)
            )
        )
        await db_session.commit()

        assert (await _agente(c, agente["id"]))["indice"]["sin_actualizar"] is True
        quien.actual = persona()
        catalogo = (await c.get("/api/v1/agentes/catalogo")).json()
        # Avisa, no oculta: se sigue ofreciendo.
        assert [a["id"] for a in catalogo] == [agente["id"]]
        assert catalogo[0]["indice_sin_actualizar"] is True

    @pytest.mark.asyncio
    async def test_una_hoja_subida_a_mano_no_caduca(self, http, db_session):
        """Quien la sube a mano no ha prometido actualizarla a diario: no hay guion que se pare."""
        from sqlalchemy import update

        from server.app.modules.agents_hub.database.operational_models import HubAgenteUnidad

        c, _ = http
        agente = await publicar(c)
        hoja = "url;titulo;resumen\nhttps://drive.google.com/file/d/1;T;Resumen.\n".encode("utf-8")
        await c.post(
            f"/api/v1/agentes/{agente['id']}/indice/hoja",
            files={"file": ("indice.csv", hoja, "text/csv")},
        )
        await db_session.execute(
            update(HubAgenteUnidad).values(
                indice_actualizado_en=datetime.now(timezone.utc) - timedelta(days=30)
            )
        )
        await db_session.commit()
        assert (await _agente(c, agente["id"]))["indice"]["sin_actualizar"] is False


class TestCarpetaContraIndice:

    @pytest.mark.asyncio
    async def test_el_guion_dice_cuantos_documentos_hay_y_se_ve_cuantos_faltan(self, http):
        c, _ = http
        agente = await publicar(c)
        await _cargar(c, agente["id"], documentos_en_carpeta=5)
        indice = (await _agente(c, agente["id"]))["indice"]
        assert indice["documentos_en_carpeta"] == 5
        assert indice["fichas"] == 2
        assert indice["faltan"] == 3

    @pytest.mark.asyncio
    async def test_sin_el_recuento_no_se_inventa_una_diferencia(self, http):
        c, _ = http
        agente = await publicar(c)
        await _cargar(c, agente["id"])
        indice = (await _agente(c, agente["id"]))["indice"]
        assert indice["documentos_en_carpeta"] is None
        assert indice["faltan"] is None

    @pytest.mark.asyncio
    async def test_un_recuento_negativo_se_rechaza(self, http):
        c, _ = http
        agente = await publicar(c)
        r = await c.put(
            f"/api/v1/agentes/{agente['id']}/indice",
            json={"fichas": FICHAS, "documentos_en_carpeta": -1},
        )
        assert r.status_code == 422


class TestElPromptDeResumen:

    @pytest.mark.asyncio
    async def test_la_plataforma_lo_sirve_con_su_version(self, http):
        c, _ = http
        r = await c.get("/api/v1/agentes/prompt-de-resumen")
        assert r.status_code == 200, r.text
        cuerpo = r.json()
        assert cuerpo["version"]
        assert len(cuerpo["texto"]) > 100

    @pytest.mark.asyncio
    async def test_el_prompt_no_pide_etiquetas_del_vocabulario(self, http):
        """El resumen es lo que se embebe: si pidiera la materia, la taxonomía entraría en el vector."""
        c, _ = http
        texto = (await c.get("/api/v1/agentes/prompt-de-resumen")).json()["texto"].lower()
        for prohibida in ("ámbito", "submateria", "etiqueta"):
            assert prohibida not in texto

    @pytest.mark.asyncio
    async def test_un_token_sin_agentes_indice_no_lo_lee(self, http):
        c, _ = http
        r = await c.get(
            "/api/v1/agentes/prompt-de-resumen", headers={"X-Prueba-Scopes": "agentes:consulta"}
        )
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_se_cuentan_las_fichas_resumidas_con_otra_version(self, http):
        c, _ = http
        version = (await c.get("/api/v1/agentes/prompt-de-resumen")).json()["version"]
        agente = await publicar(c)
        fichas = [
            {**FICHAS[0], "version_prompt_resumen": version, "modelo_resumen": "gemini"},
            {**FICHAS[1], "version_prompt_resumen": "resumen-v0", "modelo_resumen": "gemini"},
            {
                "url": "https://drive.google.com/file/d/3",
                "titulo": "Escrita a mano",
                "resumen": "Sin versión: la escribió una persona.",
            },
        ]
        await _cargar(c, agente["id"], fichas=fichas)
        indice = (await _agente(c, agente["id"]))["indice"]
        # La escrita a mano no está desfasada: no la hizo ningún prompt.
        assert indice["desfasadas"] == 1
