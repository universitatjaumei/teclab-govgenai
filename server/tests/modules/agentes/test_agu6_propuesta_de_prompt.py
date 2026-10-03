"""#213 — un asistente propone el prompt de un agente a partir de su finalidad.

Lo pidió el usuario tras las pruebas manuales (2026-10-03): escribir un buen prompt es lo que más
cuesta a quien publica. La unidad describe en lenguaje natural para qué quiere el agente y un
modelo le propone un prompt.

Lo que fija este fichero:

* **Propone, no publica**: no se guarda nada; la propuesta va al formulario para editarla.
* **No duplica lo que la plataforma añade siempre** al entregar el prompt —la pregunta, los
  enlaces y la instrucción de abstención—, y lo sabe porque se lo dice el meta-prompt.
* **Usa la declaración del agente**: finalidad, unidad, colectivo y si espera un adjunto.
* **Queda constancia**: el uso va al registro de actividad, sin el texto, y la versión que se
  publica con ayuda de IA lo dice (`autoria_prompt`).
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from server.tests.modules.agentes._comun import declaracion, publicar

DESCRIPCION = "Quiero que oriente al PDI sobre cómo tramitar un contrato menor de servicios."


class ModeloFalso:
    """Un modelo que contesta lo que le digan y apunta lo que recibió."""

    model_name = "modelo-falso-1"

    def __init__(self, respuesta: str = "Eres el asistente de contratación de la universidad.") -> None:
        self.respuesta = respuesta
        self.mensajes: list = []

    async def ainvoke(self, mensajes):
        self.mensajes.append(mensajes)

        class _R:
            content = self.respuesta

        return _R()


@pytest.fixture
def modelo(http):
    from server.app.routers.agentes_router import obtener_modelo_de_redaccion

    c, _ = http
    falso = ModeloFalso()
    c._transport.app.dependency_overrides[obtener_modelo_de_redaccion] = lambda: falso
    return falso


def _cuerpo(**extra) -> dict:
    return {
        "descripcion": DESCRIPCION,
        "nombre": "Contratación menor",
        "unidad": "Servicio de Contratación",
        "finalidad": "Orientar sobre el contrato menor",
        "colectivo": "organizacion",
        "grupos": [],
        "espera_adjunto": False,
        "lengua": "es",
        **extra,
    }


class TestLaPropuesta:

    @pytest.mark.asyncio
    async def test_devuelve_el_prompt_propuesto_y_el_modelo(self, http, modelo):
        c, _ = http
        r = await c.post("/api/v1/agentes/proponer-prompt", json=_cuerpo())
        assert r.status_code == 200, r.text
        assert r.json() == {
            "prompt": "Eres el asistente de contratación de la universidad.",
            "modelo_usado": "modelo-falso-1",
            "version": "propuesta-prompt-v1",
        }

    @pytest.mark.asyncio
    async def test_no_guarda_nada(self, http, modelo):
        c, _ = http
        await c.post("/api/v1/agentes/proponer-prompt", json=_cuerpo())
        assert (await c.get("/api/v1/agentes")).json()["agentes"] == []

    @pytest.mark.asyncio
    async def test_el_modelo_recibe_la_descripcion_y_la_declaracion(self, http, modelo):
        c, _ = http
        await c.post("/api/v1/agentes/proponer-prompt", json=_cuerpo())
        texto = "\n".join(m["content"] for m in modelo.mensajes[0])
        for dato in (DESCRIPCION, "Servicio de Contratación", "Orientar sobre el contrato menor"):
            assert dato in texto

    @pytest.mark.asyncio
    async def test_el_meta_prompt_dice_lo_que_la_plataforma_ya_anade(self, http, modelo):
        """Si no lo supiera, la propuesta repetiría la abstención o pediría una lista de enlaces."""
        c, _ = http
        await c.post("/api/v1/agentes/proponer-prompt", json=_cuerpo())
        sistema = modelo.mensajes[0][0]["content"].lower()
        assert modelo.mensajes[0][0]["role"] == "system"
        for ya_lo_pone_la_plataforma in ("pregunta", "enlaces", "abstención"):
            assert ya_lo_pone_la_plataforma in sistema

    @pytest.mark.asyncio
    async def test_con_adjunto_se_lo_dice_al_modelo(self, http, modelo):
        c, _ = http
        await c.post("/api/v1/agentes/proponer-prompt", json=_cuerpo(espera_adjunto=True))
        texto = "\n".join(m["content"] for m in modelo.mensajes[0]).lower()
        assert "adjunt" in texto

    @pytest.mark.asyncio
    async def test_en_la_lengua_que_se_pide(self, http, modelo):
        c, _ = http
        await c.post("/api/v1/agentes/proponer-prompt", json=_cuerpo(lengua="ca"))
        sistema = modelo.mensajes[0][0]["content"]
        assert "valenciano" in sistema.lower() or "valencià" in sistema.lower()

    @pytest.mark.asyncio
    async def test_limpia_lo_que_el_modelo_pone_alrededor(self, http):
        from server.app.routers.agentes_router import obtener_modelo_de_redaccion

        c, _ = http
        c._transport.app.dependency_overrides[obtener_modelo_de_redaccion] = lambda: ModeloFalso(
            "```\nEres el asistente de contratación.\n```"
        )
        r = await c.post("/api/v1/agentes/proponer-prompt", json=_cuerpo())
        assert r.json()["prompt"] == "Eres el asistente de contratación."

    @pytest.mark.asyncio
    @pytest.mark.parametrize("descripcion", ["", "corto", "x" * 4001])
    async def test_una_descripcion_vacia_o_desmedida_es_un_422(self, http, modelo, descripcion):
        c, _ = http
        r = await c.post("/api/v1/agentes/proponer-prompt", json=_cuerpo(descripcion=descripcion))
        assert r.status_code == 422


class TestLoQueFalla:

    @pytest.mark.asyncio
    async def test_sin_modelo_configurado_es_un_503_que_dice_que_hacer(self, http):
        from fastapi import HTTPException

        from server.app.routers.agentes_router import obtener_modelo_de_redaccion

        c, _ = http

        def _sin_modelo():
            raise HTTPException(status_code=503, detail="No hay modelo de redacción configurado.")

        c._transport.app.dependency_overrides[obtener_modelo_de_redaccion] = _sin_modelo
        r = await c.post("/api/v1/agentes/proponer-prompt", json=_cuerpo())
        assert r.status_code == 503

    @pytest.mark.asyncio
    async def test_si_el_proveedor_falla_es_un_502_y_no_un_500(self, http):
        from server.app.routers.agentes_router import obtener_modelo_de_redaccion

        class Roto(ModeloFalso):
            async def ainvoke(self, mensajes):
                raise RuntimeError("cuota agotada")

        c, _ = http
        c._transport.app.dependency_overrides[obtener_modelo_de_redaccion] = lambda: Roto()
        r = await c.post("/api/v1/agentes/proponer-prompt", json=_cuerpo())
        assert r.status_code == 502

    @pytest.mark.asyncio
    async def test_una_respuesta_vacia_no_se_da_por_buena(self, http):
        from server.app.routers.agentes_router import obtener_modelo_de_redaccion

        c, _ = http
        c._transport.app.dependency_overrides[obtener_modelo_de_redaccion] = lambda: ModeloFalso("  ")
        r = await c.post("/api/v1/agentes/proponer-prompt", json=_cuerpo())
        assert r.status_code == 502

    @pytest.mark.asyncio
    async def test_un_token_no_pide_propuestas(self, http, modelo):
        c, _ = http
        r = await c.post(
            "/api/v1/agentes/proponer-prompt",
            json=_cuerpo(),
            headers={"X-Prueba-Scopes": "agentes:indice"},
        )
        assert r.status_code == 403


class TestLaConstancia:

    @pytest.mark.asyncio
    async def test_el_uso_va_al_registro_sin_el_texto(self, http, modelo, db_session):
        from server.app.modules.agents_hub.database.operational_models import HubActividadIA

        c, _ = http
        await c.post("/api/v1/agentes/proponer-prompt", json=_cuerpo())
        filas = (await db_session.execute(select(HubActividadIA))).scalars().all()
        assert len(filas) == 1
        uso = filas[0]
        assert uso.herramienta == "agentes/proponer-prompt"
        assert uso.modelo_usado == "modelo-falso-1"
        for columna in HubActividadIA.__table__.columns:
            assert "contrato menor de servicios" not in str(getattr(uso, columna.key, ""))

    @pytest.mark.asyncio
    async def test_la_version_publicada_con_ayuda_de_ia_lo_dice(self, http):
        c, _ = http
        agente = await publicar(c, autoria_prompt="ia")
        assert agente["version"]["autoria_prompt"] == "ia"

    @pytest.mark.asyncio
    async def test_por_defecto_la_escribe_una_persona(self, http):
        c, _ = http
        agente = await publicar(c)
        assert agente["version"]["autoria_prompt"] == "persona"

    @pytest.mark.asyncio
    async def test_una_autoria_que_no_existe_se_rechaza(self, http):
        c, _ = http
        r = await c.post("/api/v1/agentes", json=declaracion(autoria_prompt="otra"))
        assert r.status_code == 422

