"""PRO.2.1 — el prompt y el nivel de una actividad se pueden sobreescribir.

Los prompts de las actividades del módulo estaban **escritos en Python**: nadie podía afinar
el texto sin desplegar, ni decidir con qué nivel de modelo corre cada una.

El legacy lo tenía resuelto y el usuario pidió replicarlo: `SystemPrompt`
(`name`/`version`/`content`/`tier`) más un editor con el **tier en un radio de cuatro
opciones** —«por defecto (usa Tier N)», 1, 2, 3— y las variables `{...}` detectadas en vivo.
El defecto por tarea vivía **en código** (`DEFAULT_TIER_MAPPING`) y la base de datos sólo
guardaba el override.

La regla que hace esto revisable, y que estos tests defienden:

- **El código dice qué actividades existen.** Sin fila en base de datos todo funciona igual
  que antes: la fila es una excepción, no un requisito.
- **El texto por defecto no se copia a la base de datos.** Copiarlo congela el prompt: a
  partir de ahí, mejorarlo en el código no llegaría a quien ya lo abrió.
"""
from __future__ import annotations

import pytest
from server.tests.dobles import modelo_de_chat


class _ProveedorSinFilas:
    async def get_activity_prompt(self, activity: str, *, organizacion_id=None):
        return None


class _ProveedorConFila:
    def __init__(self, *, template_text: str | None = None, override_tier: int | None = None):
        from server.app.modules.agents_hub.services.config_provider import (
            ActivityPromptOverride,
        )

        self._override = ActivityPromptOverride(
            template_text=template_text, override_tier=override_tier
        )
        self.pedido: str | None = None

    async def get_activity_prompt(self, activity: str, *, organizacion_id=None):
        self.pedido = activity
        return self._override


# ---------------------------------------------------------------------------
# La resolución
# ---------------------------------------------------------------------------

class TestResolucion:
    @pytest.mark.asyncio
    async def test_should_caer_al_codigo_sin_fila_en_base_de_datos(self) -> None:
        from server.app.modules.redaccion.services.actividades_llm import (
            ActividadLLM,
            PROMPT_POR_ACTIVIDAD,
            resolver_actividad,
        )

        resuelta = await resolver_actividad(
            ActividadLLM.PROPUESTA_DE_SCRIPT, _ProveedorSinFilas()
        )

        assert resuelta.tier == 2
        assert resuelta.template_text == PROMPT_POR_ACTIVIDAD[ActividadLLM.PROPUESTA_DE_SCRIPT]
        assert resuelta.origen_del_tier == "codigo"

    @pytest.mark.asyncio
    async def test_should_usar_el_nivel_del_override(self) -> None:
        from server.app.modules.redaccion.services.actividades_llm import (
            ActividadLLM,
            resolver_actividad,
        )

        resuelta = await resolver_actividad(
            ActividadLLM.PROPUESTA_DE_SCRIPT, _ProveedorConFila(override_tier=3)
        )

        assert resuelta.tier == 3
        assert resuelta.origen_del_tier == "override"

    @pytest.mark.asyncio
    async def test_should_usar_el_texto_del_override(self) -> None:
        from server.app.modules.redaccion.services.actividades_llm import (
            ActividadLLM,
            resolver_actividad,
        )

        resuelta = await resolver_actividad(
            ActividadLLM.PROPUESTA_DE_SCRIPT,
            _ProveedorConFila(template_text="Escribe el script y calla."),
        )

        assert resuelta.template_text == "Escribe el script y calla."
        assert resuelta.origen_del_texto == "override"

    @pytest.mark.asyncio
    async def test_should_caer_al_texto_del_codigo_con_un_override_vacio(self) -> None:
        """Un texto en blanco significa «usa el del código», no «prompt vacío».

        Es la diferencia entre poder volver atrás desde la pantalla y tener que borrar la
        fila por SQL. Y sin esta regla, guardar el formulario sin tocar el texto dejaría al
        modelo sin instrucciones.
        """
        from server.app.modules.redaccion.services.actividades_llm import (
            ActividadLLM,
            PROMPT_POR_ACTIVIDAD,
            resolver_actividad,
        )

        for vacio in ("", "   \n  "):
            resuelta = await resolver_actividad(
                ActividadLLM.AUDITORIA_DE_SCRIPT, _ProveedorConFila(template_text=vacio)
            )
            assert resuelta.template_text == PROMPT_POR_ACTIVIDAD[
                ActividadLLM.AUDITORIA_DE_SCRIPT
            ]
            assert resuelta.origen_del_texto == "codigo"

    @pytest.mark.asyncio
    async def test_should_pedir_la_fila_por_la_clave_estable_de_la_actividad(self) -> None:
        from server.app.modules.redaccion.services.actividades_llm import (
            ActividadLLM,
            resolver_actividad,
        )

        proveedor = _ProveedorConFila(override_tier=1)
        await resolver_actividad(ActividadLLM.AUDITORIA_DE_SCRIPT, proveedor)

        assert proveedor.pedido == "auditoria_de_script"

    @pytest.mark.asyncio
    async def test_should_seguir_funcionando_si_el_proveedor_no_sabe_de_actividades(
        self,
    ) -> None:
        """Un `ConfigProvider` antiguo no puede tumbar la generación de un informe."""
        from server.app.modules.redaccion.services.actividades_llm import (
            ActividadLLM,
            resolver_actividad,
        )

        class _ProveedorViejo:
            pass

        resuelta = await resolver_actividad(
            ActividadLLM.PROPUESTA_DE_SCRIPT, _ProveedorViejo()
        )

        assert resuelta.tier == 2
        assert resuelta.origen_del_tier == "codigo"


# ---------------------------------------------------------------------------
# El catálogo es la lista de lo que existe
# ---------------------------------------------------------------------------

class TestCatalogo:
    def test_should_tener_prompt_toda_actividad(self) -> None:
        from server.app.modules.redaccion.services.actividades_llm import (
            ActividadLLM,
            PROMPT_POR_ACTIVIDAD,
        )

        assert set(PROMPT_POR_ACTIVIDAD) == set(ActividadLLM)
        assert all(texto.strip() for texto in PROMPT_POR_ACTIVIDAD.values())

    def test_should_declarar_las_variables_de_cada_prompt(self) -> None:
        """La pantalla enseña las variables detectadas; si no se declaran, no se validan.

        Un override que se invente `{lista_negra}` no se puede formatear, y el síntoma sería
        un `KeyError` en la petición siguiente en vez de un aviso al guardar.
        """
        from server.app.modules.redaccion.services.actividades_llm import (
            ActividadLLM,
            VARIABLES_POR_ACTIVIDAD,
            variables_de,
        )

        assert set(VARIABLES_POR_ACTIVIDAD) == set(ActividadLLM)
        detectadas = variables_de(ActividadLLM.PROPUESTA_DE_SCRIPT)
        assert "lista_blanca" in detectadas
        assert detectadas == set(VARIABLES_POR_ACTIVIDAD[ActividadLLM.PROPUESTA_DE_SCRIPT])

    def test_should_no_reventar_con_una_variable_que_no_existe(self) -> None:
        """Un override con una variable inventada deja el hueco tal cual y sigue."""
        from server.app.modules.redaccion.services.actividades_llm import rellenar

        texto = rellenar(
            "Usa {lista_blanca} y no {invento}.", {"lista_blanca": "['pandas']"}
        )

        assert "['pandas']" in texto
        assert "{invento}" in texto


# ---------------------------------------------------------------------------
# El servicio consume lo resuelto
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_should_usar_el_servicio_el_prompt_resuelto() -> None:
    """Si un administrador cambia el texto, es el que llega al modelo."""
    from dataclasses import dataclass
    from unittest.mock import AsyncMock

    from server.app.modules.redaccion.services.script_proposal_service import (
        ScriptProposalService,
    )

    @dataclass
    class _Respuesta:
        content: str

    llm = modelo_de_chat()
    llm.ainvoke = AsyncMock(return_value=_Respuesta(content="result = {}"))

    servicio = ScriptProposalService(
        llm=llm,
        system_prompt="INSTRUCCIONES DE UN ADMINISTRADOR CON PRISA",
    )
    await servicio.propose("Extrae algo.")

    mensajes = llm.ainvoke.await_args.args[0]
    assert mensajes[0]["content"].startswith("INSTRUCCIONES DE UN ADMINISTRADOR CON PRISA")


class TestElModuloDeCadaActividad:
    """REV.7 — de qué módulo es cada actividad.

    El catálogo decía qué actividades existen, con qué nivel corren y para qué sirven, pero no
    **de quién son**. Con cuatro da igual; el problema es que la pantalla no puede agrupar ni
    filtrar por algo que no existe, y el catálogo crece cuando se cablea un consumidor —los de
    Curación y Chatbots no están todavía—.
    """

    def test_should_declare_the_module_of_every_activity(self) -> None:
        from server.app.modules.redaccion.services.actividades_llm import (
            ActividadLLM,
            MODULO_POR_ACTIVIDAD,
        )

        assert set(MODULO_POR_ACTIVIDAD) == set(ActividadLLM)
        assert all(modulo.strip() for modulo in MODULO_POR_ACTIVIDAD.values())

    def test_should_use_the_module_codes_the_platform_already_knows(self) -> None:
        """No un vocabulario nuevo: los mismos códigos que concede `HubModuleGrant` y que
        filtran las rutas del panel. Si aquí se inventara «redaccion» y allí fuera «informes»,
        el filtro de la pantalla no cuadraría con el menú."""
        from server.app.core.auth.modulos import MODULOS_INICIALES
        from server.app.modules.redaccion.services.actividades_llm import (
            MODULO_POR_ACTIVIDAD,
        )

        conocidos = {codigo for codigo, _etiqueta in MODULOS_INICIALES}
        assert set(MODULO_POR_ACTIVIDAD.values()) <= conocidos
