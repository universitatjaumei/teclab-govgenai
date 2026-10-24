"""Hasher para detección de cambios en documentos."""

import hashlib


def hash_content(content: str) -> str:
    """Genera hash SHA-256 del contenido.

    Args:
        content: Texto a hashear

    Returns:
        Hash hexadecimal de 64 caracteres
    """
    return hashlib.sha256(content.encode("utf-8")).hexdigest()

