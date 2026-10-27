"""Fixtures de agents_hub: el orden de importación de torch que exige Windows.

`db_url` y `db_session` (la BD desechable por test y su sesión) viven en el conftest raíz
`tests/conftest.py` para que todos los directorios puedan usarlas; la sesión, desde #281.
"""
from __future__ import annotations

# ── Orden de importación obligatorio, no reordenar ─────────────────────────────
# `langchain_text_splitters` arrastra `sentence_transformers` → torch. En Windows,
# cargar torch DESPUÉS de haber abierto una conexión asyncpg aborta el proceso con
# «Windows fatal exception: access violation»; al revés funciona. Diagnosticado el
# 2026-07-29 reduciéndolo a dos líneas:
#
#     asyncpg connect  →  import langchain_text_splitters   ⇒ access violation
#     import langchain_text_splitters  →  asyncpg connect    ⇒ OK
#
# Es la causa del crash que arrastraba `test_full_pipeline.py` y que bloqueaba
# cualquier test de integración que tocara el chunker. Importarlo aquí, al cargar el
# conftest, garantiza que torch entra antes que cualquier motor de BD.
import langchain_text_splitters  # noqa: F401  ← debe ir primero



