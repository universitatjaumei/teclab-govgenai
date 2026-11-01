"""#350 — el Copilot contesta en la lengua en que se le pregunta.

En producción, «Com exporte l'informe a Word?» recibió respuesta en castellano. La única
instrucción era una línea al final del mensaje de usuario, «Responde en el idioma de la
pregunta», detrás de un bloque largo en castellano; y el prompt de sistema le dictaba la frase de
declinar literal en castellano. El modelo seguía la lengua de lo que más había leído.

No se le dice la lengua desde fuera: se le pide que la tome de la pregunta, y se le dice dónde
está el riesgo —el contexto puede venir en otra—.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage

from server.app.modules.redaccion.services.copilot import CopilotService, IndexedChunk
from server.tests.dobles import modelo_de_chat


class _Buscador:
    async def retrieve(self, question, module=None, top_k=4):
        return [
            IndexedChunk(
                text="Pulsa Exportar a Word.",
                source_path="ayuda/redaccion/es/exportar-el-informe.md",
                module="redaccion",
                chunk_idx=0,
                embedding=[0.0],
            )
        ]


async def _mensajes(pregunta: str, contexto_del_informe: str | None = None) -> list[dict]:
    modelo = modelo_de_chat()
    modelo.ainvoke = AsyncMock(return_value=AIMessage(content="ok"))
    await CopilotService(llm=modelo, retriever=_Buscador()).answer(
        question=pregunta, module="redaccion", contexto_del_informe=contexto_del_informe
    )
    return modelo.ainvoke.await_args.args[0]


@pytest.mark.asyncio
async def test_el_prompt_de_sistema_manda_contestar_en_la_lengua_de_la_pregunta() -> None:
    sistema = (await _mensajes("Com exporte l'informe a Word?"))[0]["content"]

    assert "lengua de la pregunta" in sistema
    assert "valenciano" in sistema, "la lengua que se le escapaba tiene que estar nombrada"
    # Hay que decirle que el contexto puede estar en otra lengua, y que no manda.
    assert "aunque" in sistema
    assert "contexto" in sistema


@pytest.mark.asyncio
async def test_la_frase_de_declinar_no_le_impone_el_castellano() -> None:
    sistema = (await _mensajes("Com exporte l'informe a Word?"))[0]["content"]

    assert '"No tengo esa información en la documentación disponible."' not in sistema


@pytest.mark.asyncio
async def test_lo_ultimo_que_lee_es_la_lengua_de_la_pregunta() -> None:
    usuario = (await _mensajes("Com exporte l'informe a Word?", contexto_del_informe="ESTADO"))[1][
        "content"
    ]

    ultima_linea = usuario.strip().splitlines()[-1]
    assert "lengua de la pregunta" in ultima_linea
    assert "Com exporte l'informe a Word?" in usuario
