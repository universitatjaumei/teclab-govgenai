"""#270 — las dos herramientas que suben un fichero del equipo miran qué suben antes de leerlo.

En el servidor stdio, `registrar_cuaderno` y `cargar_indice_de_agente` aceptaban cualquier ruta y
la subían entera al catálogo de la organización: una errata en la ruta —`~/.ssh/id_rsa` en vez
del cuaderno— y el fichero acababa en el servidor. Ahora sólo pasan las extensiones que el
servidor sabe interpretar y hasta el tamaño que admite, y se comprueba **antes de leer**.
"""
from __future__ import annotations

import pytest
from api_client import ApiClient
from tools.agentes import MAXIMO_BYTES_DE_LA_HOJA, run_cargar_indice_core
from tools.funciones import MAXIMO_BYTES_DEL_CUADERNO, run_registrar_cuaderno_core

from tests.test_actividad_tools import API, PAT_UNO

DECLARACION = {"nombre": "n", "finalidad": "f", "categorias_datos": [], "entorno_ejecucion": "e"}


@pytest.mark.parametrize("nombre", ["id_rsa", "notas.txt", ".env", "datos.pdf"])
async def test_un_cuaderno_con_otra_extension_no_se_sube(tmp_path, nombre):
    fichero = tmp_path / nombre
    fichero.write_text("secreto", encoding="utf-8")
    async with ApiClient(API, PAT_UNO) as cliente:
        with pytest.raises(ValueError, match="ipynb"):
            await run_registrar_cuaderno_core(cliente, DECLARACION, ruta=str(fichero))


async def test_un_cuaderno_demasiado_grande_no_se_sube(tmp_path):
    fichero = tmp_path / "enorme.ipynb"
    fichero.write_bytes(b" " * (MAXIMO_BYTES_DEL_CUADERNO + 1))
    async with ApiClient(API, PAT_UNO) as cliente:
        with pytest.raises(ValueError, match="MB"):
            await run_registrar_cuaderno_core(cliente, DECLARACION, ruta=str(fichero))


@pytest.mark.parametrize("nombre", ["id_rsa", "indice.txt", "indice.json", "indice.ods"])
async def test_una_hoja_con_otra_extension_no_se_sube(tmp_path, nombre):
    hoja = tmp_path / nombre
    hoja.write_text("secreto", encoding="utf-8")
    async with ApiClient(API, PAT_UNO) as cliente:
        with pytest.raises(ValueError, match="csv"):
            await run_cargar_indice_core(cliente, "a1", ruta_hoja=str(hoja))


async def test_una_hoja_demasiado_grande_no_se_sube(tmp_path):
    hoja = tmp_path / "indice.csv"
    hoja.write_bytes(b"x" * (MAXIMO_BYTES_DE_LA_HOJA + 1))
    async with ApiClient(API, PAT_UNO) as cliente:
        with pytest.raises(ValueError, match="MB"):
            await run_cargar_indice_core(cliente, "a1", ruta_hoja=str(hoja))


def test_el_tope_de_la_hoja_es_el_del_servidor():
    """El servidor rechaza a partir de 10 MB; aquí no se puede importar `server/app`."""
    assert MAXIMO_BYTES_DE_LA_HOJA == 10 * 1024 * 1024
