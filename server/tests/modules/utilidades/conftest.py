"""Orden de importación de torch para los tests de las utilidades de uso directo (UTL).

Las utilidades anotan su uso en `hub_actividad_ia`, sobre la sesión `db_session` del conftest
raíz (#281); aquí sólo queda el orden de importación.
"""
from __future__ import annotations

# ── Orden de importación obligatorio, no reordenar ─────────────────────────────
# En Windows, cargar torch DESPUÉS de abrir una conexión asyncpg aborta el proceso con
# «access violation»; al revés funciona. Es la regla de APER.16, y la vigila
# `tests/infra/test_aper16_los_conftest_cargan_torch_antes_que_asyncpg.py`, que se puso rojo
# en CI con este fichero. `langchain_text_splitters` arrastra torch.
import langchain_text_splitters  # noqa: F401  ← debe ir primero
