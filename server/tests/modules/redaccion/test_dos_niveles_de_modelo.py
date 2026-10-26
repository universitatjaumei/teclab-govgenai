"""PRO.2 — Tier 2 escribe el script, Tier 3 lo audita.

Escribir código y juzgar si es peligroso son tareas distintas, y el usuario pide modelos
distintos para cada una: **nivel 2 para programar** y **nivel 3, superior, para auditar**.

Dos cosas que este prompt deja atadas y que conviene no perder de vista:

- **El mapa actividad→nivel es un catálogo en código**, no un `2` y un `3` escritos en la raíz
  de composición. Es la forma del legacy (`DEFAULT_TIER_MAPPING` en código, `tier_override` en
  base de datos) y es lo que PRO.2.1 podrá sobreescribir desde la biblioteca de prompts.
- **La auditoría con modelo va encima de la determinista de PRO.1, no en su lugar.** El AST no
  se puede convencer; el modelo explica. Un veredicto del modelo no puede aprobar nada.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from server.app.core.auth.models import UserInfo


# ---------------------------------------------------------------------------
# El catálogo de actividades
# ---------------------------------------------------------------------------

class TestCatalogoDeActividades:
    def test_should_declarar_el_nivel_de_cada_actividad_en_un_solo_sitio(self) -> None:
        from server.app.modules.redaccion.services.actividades_llm import (
            ActividadLLM,
            TIER_POR_ACTIVIDAD,
        )

        assert TIER_POR_ACTIVIDAD[ActividadLLM.PROPUESTA_DE_SCRIPT] == 2
        assert TIER_POR_ACTIVIDAD[ActividadLLM.AUDITORIA_DE_SCRIPT] == 3

    def test_should_tener_nivel_toda_actividad_del_catalogo(self) -> None:
        """Una actividad sin nivel es una actividad que nadie puede resolver."""
        from server.app.modules.redaccion.services.actividades_llm import (
            ActividadLLM,
            TIER_POR_ACTIVIDAD,
        )

        assert set(TIER_POR_ACTIVIDAD) == set(ActividadLLM)
        assert all(1 <= nivel <= 3 for nivel in TIER_POR_ACTIVIDAD.values())


# ---------------------------------------------------------------------------
# La raíz de composición
# ---------------------------------------------------------------------------

@dataclass
class _ModeloFalso:
    model_name: str


#: MT.3 — al llamar la dependencia a mano hay que darle lo que le daría la inyección: sin
#: `current_user`, `organizacion_id` se resolvería sobre el objeto `Depends` y reventaría. Un
#: superadministrador no pertenece a ninguna organización, así que se resuelve el nivel de
#: plataforma, que es lo que estos tests comprueban.
_SIN_ORGANIZACION = UserInfo(
    user_id="1", email="root@uji.es", role="superadmin", organizacion_ids=()
)


class TestRaizDeComposicion:
    """`get_script_proposal_service` era un stub que devolvía 503 siempre."""

    @pytest.fixture
    def niveles_pedidos(self, monkeypatch):
        """Registra con qué nivel se pide cada modelo, sin tocar la base de datos."""
        from server.app.routers.redaccion import scripts_router

        pedidos: list[int] = []

        async def _modelo(tier: int, _proveedor: Any, *, organizacion_id=None):
            pedidos.append(tier)
            return _ModeloFalso(model_name=f"modelo-de-nivel-{tier}")

        monkeypatch.setattr(scripts_router, "get_model_for_tier", _modelo)
        monkeypatch.setattr(
            scripts_router, "LocalConfigProvider", lambda _session: object(), raising=False
        )
        return pedidos

    @pytest.mark.asyncio
    async def test_should_pedir_el_nivel_2_para_escribir_y_el_3_para_auditar(
        self, niveles_pedidos
    ) -> None:
        from server.app.routers.redaccion.scripts_router import get_script_proposal_service

        servicio = await get_script_proposal_service(
            session=MagicMock(), current_user=_SIN_ORGANIZACION
        )

        assert niveles_pedidos == [2, 3], (
            "el que escribe es el de nivel 2 y el que audita el de nivel 3, en ese orden"
        )
        assert servicio is not None

    @pytest.mark.asyncio
    async def test_should_tomar_los_niveles_del_catalogo_y_no_de_literales(
        self, niveles_pedidos, monkeypatch
    ) -> None:
        """Si el catálogo cambia, el cableado cambia con él. Es el requisito de PRO.2.1."""
        from server.app.modules.redaccion.services import actividades_llm
        from server.app.routers.redaccion.scripts_router import get_script_proposal_service

        monkeypatch.setitem(
            actividades_llm.TIER_POR_ACTIVIDAD,
            actividades_llm.ActividadLLM.PROPUESTA_DE_SCRIPT,
            1,
        )

        await get_script_proposal_service(
            session=MagicMock(), current_user=_SIN_ORGANIZACION
        )

        assert niveles_pedidos == [1, 3]

    @pytest.mark.asyncio
    async def test_should_decir_el_503_que_falta_el_nivel_que_escribe(self, monkeypatch) -> None:
        from fastapi import HTTPException

        from server.app.routers.redaccion import scripts_router

        async def _sin_nivel_2(tier: int, _proveedor: Any, *, organizacion_id=None):
            if tier == 2:
                raise ValueError("No hay configuración LLM por defecto para tier 2")
            return _ModeloFalso(model_name="ok")

        monkeypatch.setattr(scripts_router, "get_model_for_tier", _sin_nivel_2)
        monkeypatch.setattr(
            scripts_router, "LocalConfigProvider", lambda _session: object(), raising=False
        )

        with pytest.raises(HTTPException) as fallo:
            await scripts_router.get_script_proposal_service(
            session=MagicMock(), current_user=_SIN_ORGANIZACION
        )

        assert fallo.value.status_code == 503
        detalle = str(fallo.value.detail)
        assert "2" in detalle
        assert "escrib" in detalle.lower(), (
            "el 503 tiene que decir qué nivel falta y para qué servía, no sólo que falla"
        )

    @pytest.mark.asyncio
    async def test_should_decir_el_503_que_falta_el_nivel_que_audita(self, monkeypatch) -> None:
        from fastapi import HTTPException

        from server.app.routers.redaccion import scripts_router

        async def _sin_nivel_3(tier: int, _proveedor: Any, *, organizacion_id=None):
            if tier == 3:
                raise ValueError("No hay configuración LLM por defecto para tier 3")
            return _ModeloFalso(model_name="ok")

        monkeypatch.setattr(scripts_router, "get_model_for_tier", _sin_nivel_3)
        monkeypatch.setattr(
            scripts_router, "LocalConfigProvider", lambda _session: object(), raising=False
        )

        with pytest.raises(HTTPException) as fallo:
            await scripts_router.get_script_proposal_service(
            session=MagicMock(), current_user=_SIN_ORGANIZACION
        )

        assert fallo.value.status_code == 503
        detalle = str(fallo.value.detail)
        assert "3" in detalle
        assert "audit" in detalle.lower()


# ---------------------------------------------------------------------------
# La auditoría con modelo, encima de la determinista
# ---------------------------------------------------------------------------

def _llm_que_responde(texto: str):
    @dataclass
    class _Respuesta:
        content: str

    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=_Respuesta(content=texto))
    return llm


_SCRIPT_LIMPIO = (
    "import pandas as pd\n"
    "df = pd.read_excel(file_path)\n"
    "result = {'tables': [], 'metrics': [], 'free_text': None}\n"
)


class TestAuditoriaConModelo:
    @pytest.mark.asyncio
    async def test_should_anadir_la_revision_del_modelo_al_resultado(self) -> None:
        from server.app.modules.redaccion.services.script_proposal_service import (
            ScriptProposalService,
        )

        servicio = ScriptProposalService(
            llm=_llm_que_responde(_SCRIPT_LIMPIO),
            model_name="escritor",
            auditor_llm=_llm_que_responde(
                '{"veredicto": "acepta", "motivos": ["Lee sólo file_path."]}'
            ),
            auditor_model_name="auditor",
        )

        resultado = await servicio.propose("Extrae las filas del Excel.")

        assert resultado.revision_del_modelo is not None
        assert resultado.revision_del_modelo.veredicto == "acepta"
        assert resultado.revision_del_modelo.model_used == "auditor"
        assert resultado.audit_result.approved is True

    @pytest.mark.asyncio
    async def test_should_no_poder_el_modelo_aprobar_lo_que_la_determinista_no_aprueba(
        self,
    ) -> None:
        """Un `acepta` del modelo sobre un script con hallazgos no mueve nada.

        La determinista es la que no se puede convencer. Si el veredicto del modelo pudiera
        levantar un hallazgo, la auditoría del AST estaría **en manos del modelo**, que es
        justo lo que el orden «primero el AST, después el modelo» evita.
        """
        from server.app.modules.redaccion.services.script_proposal_service import (
            ScriptProposalService,
        )

        servicio = ScriptProposalService(
            llm=_llm_que_responde("import csv\nresult = {'tables': [], 'metrics': []}\n"),
            model_name="escritor",
            auditor_llm=_llm_que_responde(
                '{"veredicto": "acepta", "motivos": ["csv es inofensivo."]}'
            ),
            auditor_model_name="auditor",
        )

        resultado = await servicio.propose("Lee un CSV.")

        assert resultado.audit_result.approved is False
        assert resultado.audit_result.risk_level == "WARNING"
        assert resultado.audit_result.puede_revisarse is True
        assert resultado.revision_del_modelo.veredicto == "acepta"

    @pytest.mark.asyncio
    async def test_should_no_gastar_una_llamada_en_auditar_un_critico(self) -> None:
        """Un script con un crítico no se ejecuta nunca: no hay semántica que juzgar."""
        from server.app.modules.redaccion.services.script_proposal_service import (
            ScriptProposalService,
        )

        auditor = _llm_que_responde('{"veredicto": "rechaza", "motivos": []}')
        servicio = ScriptProposalService(
            llm=_llm_que_responde("import os\nresult = eval('1+1')\n"),
            model_name="escritor",
            auditor_llm=auditor,
            auditor_model_name="auditor",
        )

        resultado = await servicio.propose("Ejecuta lo que quieras.")

        assert resultado.audit_result.risk_level == "CRITICAL"
        auditor.ainvoke.assert_not_awaited()
        assert resultado.revision_del_modelo is None

    @pytest.mark.asyncio
    async def test_should_seguir_funcionando_sin_auditor(self) -> None:
        """Sin modelo auditor el servicio no se rompe: la determinista sigue siendo la puerta."""
        from server.app.modules.redaccion.services.script_proposal_service import (
            ScriptProposalService,
        )

        servicio = ScriptProposalService(llm=_llm_que_responde(_SCRIPT_LIMPIO))

        resultado = await servicio.propose("Extrae las filas.")

        assert resultado.audit_result.approved is True
        assert resultado.revision_del_modelo is None

    @pytest.mark.asyncio
    async def test_should_quedar_en_duda_si_el_auditor_no_devuelve_json(self) -> None:
        """Un auditor que se va por las ramas no puede quedar como un «acepta» silencioso."""
        from server.app.modules.redaccion.services.script_proposal_service import (
            ScriptProposalService,
        )

        servicio = ScriptProposalService(
            llm=_llm_que_responde(_SCRIPT_LIMPIO),
            auditor_llm=_llm_que_responde("Me parece razonable, adelante."),
            auditor_model_name="auditor",
        )

        resultado = await servicio.propose("Extrae las filas.")

        assert resultado.revision_del_modelo.veredicto == "duda"
        assert resultado.revision_del_modelo.motivos


# ---------------------------------------------------------------------------
# El prompt del sistema dice lo que el auditor bloquea
# ---------------------------------------------------------------------------

class TestPromptDelSistema:
    def test_should_nombrar_los_prohibidos_por_su_forma(self) -> None:
        """El auditor marca `getattr` y compañía como CRÍTICO y el prompt no los nombraba.

        Sin decirlo, el modelo los usa con toda naturalidad —`getattr(df, metodo)` es Python
        idiomático— y la propuesta muere en la auditoría sin que nadie sepa por qué.
        """
        from server.app.modules.redaccion.services.script_proposal_service import (
            _build_system_prompt,
        )

        prompt = _build_system_prompt(None)

        for nombre in ("getattr", "globals", "locals", "vars", "setattr", "__class__", "__dict__"):
            assert nombre in prompt, f"el prompt no nombra '{nombre}'"

    def test_should_distinguir_los_modulos_prohibidos_de_los_no_permitidos(self) -> None:
        """PRO.1 separó las dos listas; el prompt tiene que trasladar la diferencia."""
        from server.app.modules.redaccion.services.script_proposal_service import (
            _build_system_prompt,
        )

        prompt = _build_system_prompt(None)

        for modulo in ("os", "subprocess", "socket", "requests", "pickle"):
            assert modulo in prompt

    def test_should_avisar_de_que_las_rutas_absolutas_son_criticas(self) -> None:
        from server.app.modules.redaccion.services.script_proposal_service import (
            _build_system_prompt,
        )

        prompt = _build_system_prompt(None)

        assert "file_path" in prompt
        assert "absolut" in prompt.lower()


# ---------------------------------------------------------------------------
# El endpoint devuelve la revisión del modelo
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_should_serializar_la_revision_del_modelo() -> None:
    from server.app.modules.redaccion.services.script_proposal_service import (
        ScriptProposalService,
    )

    servicio = ScriptProposalService(
        llm=_llm_que_responde(_SCRIPT_LIMPIO),
        auditor_llm=_llm_que_responde(
            '{"veredicto": "duda", "motivos": ["Asume una columna que no consta."]}'
        ),
        auditor_model_name="auditor",
    )

    resultado = await servicio.propose("Extrae las filas.", owner_kind="platform")
    volcado = resultado.model_dump()

    assert volcado["revision_del_modelo"]["veredicto"] == "duda"
    assert volcado["revision_del_modelo"]["motivos"] == [
        "Asume una columna que no consta."
    ]


@pytest.mark.asyncio
async def test_should_persistir_la_revision_del_modelo_con_la_propuesta(monkeypatch) -> None:
    """Lo que el modelo dijo del script tiene que llegar a quien lo revisa.

    Sin persistirla, la opinión del auditor muere en la respuesta HTTP del proponente y el
    administrador que revisa la propuesta días después no la ve: se habría pagado una llamada
    a un modelo superior para nada.
    """
    from server.app.core.auth.models import UserInfo
    from server.app.modules.redaccion.database import repos
    from server.app.routers.redaccion import scripts_router
    from server.app.modules.redaccion.services.script_proposal_service import (
        ScriptProposalService,
    )

    guardadas: list[Any] = []

    async def _save(self, proposal):
        guardadas.append(proposal)

    monkeypatch.setattr(repos.ScriptProposalRepo, "save", _save)

    servicio = ScriptProposalService(
        llm=_llm_que_responde(_SCRIPT_LIMPIO),
        model_name="escritor",
        auditor_llm=_llm_que_responde(
            '{"veredicto": "duda", "motivos": ["Asume la primera hoja."]}'
        ),
        auditor_model_name="auditor",
    )

    sesion = MagicMock()
    sesion.commit = AsyncMock()

    respuesta = await scripts_router.propose_script(
        body=scripts_router.ProposeRequest(prompt_nl="Extrae las filas."),
        user=UserInfo(user_id=str(uuid.uuid4()), email="u@t.com", role="user"),
        service=servicio,
        session=sesion,
    )

    assert respuesta.revision_del_modelo is not None
    assert respuesta.revision_del_modelo.veredicto == "duda"
    assert len(guardadas) == 1
    assert guardadas[0].model_review_json["veredicto"] == "duda"
    assert guardadas[0].model_review_json["motivos"] == ["Asume la primera hoja."]


@pytest.mark.asyncio
async def test_should_guardar_null_cuando_no_hubo_revision(monkeypatch) -> None:
    """Sin revisión no se guarda un diccionario vacío que parezca un veredicto."""
    from server.app.core.auth.models import UserInfo
    from server.app.modules.redaccion.database import repos
    from server.app.routers.redaccion import scripts_router
    from server.app.modules.redaccion.services.script_proposal_service import (
        ScriptProposalService,
    )

    guardadas: list[Any] = []

    async def _save(self, proposal):
        guardadas.append(proposal)

    monkeypatch.setattr(repos.ScriptProposalRepo, "save", _save)

    sesion = MagicMock()
    sesion.commit = AsyncMock()

    await scripts_router.propose_script(
        body=scripts_router.ProposeRequest(prompt_nl="Extrae las filas."),
        user=UserInfo(user_id=str(uuid.uuid4()), email="u@t.com", role="user"),
        service=ScriptProposalService(llm=_llm_que_responde(_SCRIPT_LIMPIO)),
        session=sesion,
    )

    assert guardadas[0].model_review_json is None
