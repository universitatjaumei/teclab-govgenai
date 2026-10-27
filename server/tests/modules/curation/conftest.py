"""Orden de importación de torch para los tests de curation.

La sesión sobre la BD desechable (`db_session`) vive en el conftest raíz desde #281; aquí sólo
queda el orden de importación que exige Windows.
"""
from __future__ import annotations

# ── Orden de importación obligatorio, no reordenar ─────────────────────────────
# Ver tests/modules/agents_hub/conftest.py: cargar torch después de abrir una conexión
# asyncpg aborta el proceso en Windows con «access violation».
import langchain_text_splitters  # noqa: F401  ← debe ir primero
