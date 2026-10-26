"""Cliente LangFuse para observabilidad del agente.

Si LANGFUSE_SECRET_KEY no está definida, todas las funciones devuelven None
y el agente funciona normalmente sin tracing.
"""

import os
from functools import lru_cache

from langfuse import Langfuse
from langfuse.langchain import CallbackHandler


@lru_cache(maxsize=1)
def get_langfuse_client() -> Langfuse | None:
    if not os.getenv("LANGFUSE_SECRET_KEY"):
        return None
    return Langfuse(
        public_key=os.getenv("LANGFUSE_PUBLIC_KEY", ""),
        secret_key=os.getenv("LANGFUSE_SECRET_KEY", ""),
        host=os.getenv("LANGFUSE_HOST", "http://localhost:3000"),
    )


def create_callback_handler(session_id: str, user_id: str) -> CallbackHandler | None:  # noqa: ARG001 — Langfuse los recibe por `metadata` del grafo
    """Crea un CallbackHandler de LangFuse para inyectar en el grafo LangGraph."""
    if not os.getenv("LANGFUSE_SECRET_KEY"):
        return None
    return CallbackHandler()
