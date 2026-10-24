"""El consumidor de las dos tablas legacy ya no está (LEG.3).

`knowledge_orchestrator_service.py` era el **único** que leía `ExtractionServiceConfig` y
`SystemPrompt`, y **no lo importaba nadie**: cero referencias en `server/`, 0 % de cobertura, 220
líneas sin ejecutar nunca. Es el Caso B de CLAUDE.md —huérfano sin migración activa—, así que se
borra: el historial de git es la fuente de verdad del pasado.

`AutomationLibrary` no se tocó entonces: la importaba este orquestador, pero también
`library_service`, que seguía vivo. **Se retiró después, en #271**, con la biblioteca entera.
"""
from __future__ import annotations

import re
from pathlib import Path

SERVER = Path(__file__).resolve().parents[2]


def test_el_orquestador_huerfano_ya_no_existe():
    assert not (SERVER / "app" / "services" / "knowledge_orchestrator_service.py").exists()


def test_nadie_lo_importa():
    """El `grep -r` a cero que exige CLAUDE.md, escrito como test para que no vuelva.

    Busca **imports**, no menciones: nombrarlo en un comentario o en el docstring de otro test
    —explicando por qué se retiró— no es una referencia viva, y un guardarraíl que da falsos
    positivos se acaba desactivando.
    """
    importado = re.compile(r"^\s*(?:from|import)\s+[\w.]*knowledge_orchestrator", re.MULTILINE)
    culpables: list[str] = []
    for carpeta in ("app", "tests", "migrations"):
        for fichero in (SERVER / carpeta).rglob("*.py"):
            if "__pycache__" in str(fichero) or fichero.name == Path(__file__).name:
                continue
            if importado.search(fichero.read_text(encoding="utf-8", errors="ignore")):
                culpables.append(str(fichero.relative_to(SERVER)))
    assert culpables == [], f"quedan imports del orquestador huérfano: {culpables}"


def test_la_biblioteca_de_automatizaciones_tampoco_esta():
    """#271 — servía al agente de ejecución local, descartado el 2026-09-23, y nadie la llamaba."""
    from server.app.database import models

    assert not hasattr(models, "AutomationLibrary")
    for fichero in ("routers/library_router.py", "services/library_service.py",
                    "services/manifest_signature_service.py"):
        assert not (SERVER / "app" / fichero).exists(), fichero
