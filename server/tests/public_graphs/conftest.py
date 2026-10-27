"""Orden de importación de torch para los tests de public_graphs.

La sesión sobre la BD desechable (`db_session`) vive en el conftest raíz desde #281; aquí sólo
queda el orden de importación, por la misma razón que en `tests/modules/agents_hub/`.

El import de `langchain_text_splitters` **debe ir primero**: arrastra torch, y en Windows
cargar torch DESPUÉS de abrir una conexión asyncpg aborta el proceso con «Windows fatal
exception: access violation». Diagnosticado en ING.0.5; no reordenar.
"""
from __future__ import annotations

import langchain_text_splitters  # noqa: F401  ← debe ir primero
