"""Las dos tablas de prompts del legacy, fuera del modelo y de la base (LEG.4).

`ExtractionServiceConfig` y `SystemPrompt` vienen del esquema inicial
(`8879cf0a3197_initial_schema`), así que no desaparecen solas: hace falta migración. Dejarlas vacías
sería peor que borrarlas, porque **una tabla que existe invita a que alguien la use**.

De `models.py` se retiran **dos** clases de diecinueve: las otras diecisiete estaban vivas, así que el
fichero se queda. #249 retiró después nueve de esas diecisiete, que resultaron no tener uso
(`test_issue249_tablas_heredadas_de_automatia.py`): quedan ocho.
"""
from __future__ import annotations

import re
from pathlib import Path

SERVER = Path(__file__).resolve().parents[2]
MODELS = SERVER / "app" / "database" / "models.py"


def _fuente_de_models() -> str:
    return MODELS.read_text(encoding="utf-8")


def test_las_dos_clases_ya_no_estan():
    fuente = _fuente_de_models()

    assert "class ExtractionServiceConfig" not in fuente
    assert "class SystemPrompt" not in fuente


def test_las_otras_ocho_siguen():
    """El fichero se queda: retirar clases no es retirar el módulo."""
    clases = re.findall(r"^class (\w+)", _fuente_de_models(), re.MULTILINE)

    assert len(clases) == 8, f"esperaba 8 clases vivas, hay {len(clases)}: {clases}"
    for viva in ("AIConfig", "TokenLog", "ModelPricing", "AutomationLibrary", "AdminAccount"):
        assert viva in clases


def test_las_dos_tablas_no_estan_en_el_metadata():
    """Si siguieran declaradas, `create_all` las recrearía en cada base nueva."""
    from server.app.database import models  # noqa: F401
    from sqlmodel import SQLModel

    # Los nombres son los que SQLModel deriva de la clase, sin guiones bajos.
    tablas = set(SQLModel.metadata.tables)
    assert "extractionserviceconfig" not in tablas
    assert "systemprompt" not in tablas


def test_hay_una_migracion_que_las_borra():
    versiones = SERVER / "migrations" / "versions"
    encontrada = [
        f.name
        for f in versiones.glob("*.py")
        if "DROP TABLE IF EXISTS" in f.read_text(encoding="utf-8", errors="ignore")
        and "extractionserviceconfig" in f.read_text(encoding="utf-8", errors="ignore")
    ]

    assert encontrada, "sin migración, las tablas siguen en la base aunque no estén en el modelo"


def test_nadie_importa_las_dos_clases():
    importadas = re.compile(
        r"^\s*(?:from|import)[^\n]*\b(?:ExtractionServiceConfig|SystemPrompt)\b", re.MULTILINE
    )
    culpables: list[str] = []
    for carpeta in ("app", "tests", "migrations"):
        for fichero in (SERVER / carpeta).rglob("*.py"):
            if "__pycache__" in str(fichero) or fichero.name == Path(__file__).name:
                continue
            if importadas.search(fichero.read_text(encoding="utf-8", errors="ignore")):
                culpables.append(str(fichero.relative_to(SERVER)))

    assert culpables == [], f"quedan imports de las clases retiradas: {culpables}"


def test_el_catalogo_de_actividades_no_apunta_a_lo_que_ya_no_existe():
    """Su comentario decía que la clave de cada actividad «es el `name` de `SystemPrompt` del
    legacy». La convención de nombres se heredó a propósito y eso hay que conservarlo escrito, pero
    sin señalar una clase que ya no está: un comentario que miente cuesta más que uno que falta."""
    fuente = (
        SERVER / "app" / "modules" / "redaccion" / "services" / "actividades_llm.py"
    ).read_text(encoding="utf-8")

    assert "SystemPrompt" not in fuente
    # Lo que sí se conserva: que la clave no se renombra sin migrar los datos.
    assert "no se renombra" in fuente
