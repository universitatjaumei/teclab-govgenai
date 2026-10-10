"""
automatia-shared: Shared DTOs, enums, validators and utilities for AutomatIA.

This package contains pure, stateless code shared between server and client_app.
"""

__version__ = "0.1.0"

from automatia_shared.enums import TaskStatus, ScriptStatus
from automatia_shared.dtos import FlowSpec, TaskSpec
from automatia_shared.crypto_utils import (
    RSASigner,
    rsa_signer,
    SignatureVerificationError,
    InvalidKeyError,
)

__all__ = [
    "TaskStatus",
    "ScriptStatus",
    "FlowSpec",
    "TaskSpec",
    # Crypto utilities
    "RSASigner",
    "rsa_signer",
    "SignatureVerificationError",
    "InvalidKeyError",
]
