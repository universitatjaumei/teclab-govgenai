"""El nombre de una columna derivada, con reglas (LEG.1).

Del legacy de AutomatIA se retiran ocho prompts, y **uno aporta algo que el vivo no decía**:
`sys_semantic_naming` daba reglas para nombrar el resultado de un paso —`snake_case`, español, tres
o cuatro palabras, sin sufijos como `_var`, y que el nombre refleje **qué datos** lleva y no qué
operación los produjo—.

El prompt del ETL hace que el modelo **cree columnas nuevas** con `compute_column` y renombre con
`rename`, y no decía nada sobre cómo llamarlas. El resultado va a una tabla de un informe
institucional, así que el nombre se lee: `pct_ejecucion` o `Unnamed: 3_calc` no cuestan lo mismo.

Comparativa completa en `docs/COMPARATIVA_PROMPTS_LEGACY.md`.
"""
from __future__ import annotations

import pytest

from server.app.modules.redaccion.services.actividades_llm import (
    PROMPT_POR_ACTIVIDAD,
    ActividadLLM,
)


@pytest.fixture
def prompt_del_etl() -> str:
    return PROMPT_POR_ACTIVIDAD[ActividadLLM.TRANSFORMACION_ETL].lower()


def test_el_prompt_del_etl_dice_como_nombrar_una_columna_nueva(prompt_del_etl: str):
    assert "snake_case" in prompt_del_etl


def test_pide_nombres_cortos(prompt_del_etl: str):
    assert "palabras" in prompt_del_etl


def test_pide_que_el_nombre_diga_el_dato_y_no_la_operacion(prompt_del_etl: str):
    """`lista_facturas`, no `resultado_extraccion`: el nombre acaba en la tabla de un informe."""
    assert "dato" in prompt_del_etl


def test_los_demas_prompts_no_se_contaminan():
    """La nomenclatura es del ETL: el que escribe scripts no crea columnas de tabla."""
    propuesta = PROMPT_POR_ACTIVIDAD[ActividadLLM.PROPUESTA_DE_SCRIPT].lower()
    assert "snake_case" not in propuesta
