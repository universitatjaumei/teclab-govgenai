"""#281 — el doble del modelo de chat y el del almacenamiento llevan la firma de la clase real.

Un `MagicMock()` a pelo acepta cualquier llamada. Así siguió en verde el test de Langfuse
mientras el SDK renombraba `score` a `create_score`, y producción fallaba en cada valoración.
Los dobles con firma están en `tests/dobles.py` (`modelo_de_chat()`, `almacenamiento()`); este
test impide que vuelvan los de antes, que eran el idioma de la suite —quince ficheros con
`llm = MagicMock()` y cinco con el almacenamiento—.

Mira sólo los nombres que en esta suite designan esos dos clientes. No persigue los 900
`MagicMock()` restantes: la mayoría doblan sesiones, filas o funciones nuestras, donde el riesgo
de un SDK que cambia por debajo no existe.
"""
from __future__ import annotations

import re
from pathlib import Path

RAIZ_TESTS = Path(__file__).resolve().parents[1]

_DOBLE_SIN_FIRMA = re.compile(
    r"\b(?:llm|mock_llm|llm_mock|storage|mock_storage)\s*=\s*(?:Magic|Async)?Mock\(\)"
    r"|get_storage_service\]\s*=\s*lambda:\s*(?:.*\bor\s+)?(?:Magic|Async)?Mock\(\)"
)


def _ficheros() -> list[Path]:
    return sorted(p for p in RAIZ_TESTS.rglob("*.py") if "__pycache__" not in p.parts)


def test_should_look_at_the_suite():
    assert len(_ficheros()) > 500, "no se encuentran los tests: el guardarraíl miraría al vacío"


def test_should_double_the_chat_model_and_the_storage_with_their_signature():
    encontrados = [
        f"{p.relative_to(RAIZ_TESTS).as_posix()}:{n}: {linea.strip()}"
        for p in _ficheros()
        if p.name != Path(__file__).name
        for n, linea in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if _DOBLE_SIN_FIRMA.search(linea)
    ]
    assert encontrados == [], (
        "dobles del modelo de chat o del almacenamiento sin la firma de la clase real:\n  "
        + "\n  ".join(encontrados)
        + "\n\nUsa `modelo_de_chat()` o `almacenamiento()` de `tests/dobles.py`: un método que no "
        "existe en el SDK tiene que fallar en el test, no en producción."
    )
