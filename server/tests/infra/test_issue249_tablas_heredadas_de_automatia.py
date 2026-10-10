"""#249 — nueve tablas heredadas de AutomatIA, fuera del modelo y de la base.

Las encontró el inventario de retención (#162, 2026-10-08): se creaban en cada base y no las usaba
ningún código, salvo la siembra de desarrollo y un guion de arreglo de esquema de la época de
SQLite. No tiene sentido ponerles plazo de conservación; se retiran. Una de ellas, `clientaccount`,
tenía columnas de correo y NIF.

En producción estaban **vacías** las nueve (contado el 2026-10-09), así que borrarlas no suprime
ningún dato personal.

Es el mismo patrón que LEG.4 (`test_las_dos_tablas_de_prompts_legacy_no_estan.py`): sin
migración siguen en la base aunque no estén en el modelo, y una tabla que existe invita a usarla.
"""
from __future__ import annotations

import re
from pathlib import Path

SERVER = Path(__file__).resolve().parents[2]
RAIZ = SERVER.parent

CLASES = (
    "ClientAccount",
    "License",
    "LicenseActivation",
    "LicenseAuditLog",
    "BillingRecord",
    "TrustedScript",
    "ScriptEscalation",
    "ServerSecurityPolicy",
    "ClientTelemetryLog",
)
TABLAS = (
    "clientaccount",
    "license",
    "licenseactivation",
    "licenseauditlog",
    "billingrecord",
    "trustedscript",
    "scriptescalation",
    "server_security_policy",
    "clienttelemetrylog",
)


def test_las_clases_ya_no_estan_en_models():
    fuente = (SERVER / "app" / "database" / "models.py").read_text(encoding="utf-8")
    quedan = [c for c in CLASES if re.search(rf"^class {c}\b", fuente, re.MULTILINE)]

    assert quedan == []


def test_las_tablas_no_estan_en_el_metadata():
    """Si siguieran declaradas, `create_all` las recrearía en cada base de pruebas."""
    from server.app.database import models  # noqa: F401
    from sqlmodel import SQLModel

    assert set(TABLAS) & set(SQLModel.metadata.tables) == set()


def test_hay_una_migracion_que_las_borra_todas():
    versiones = SERVER / "migrations" / "versions"
    for fichero in versiones.glob("*.py"):
        texto = fichero.read_text(encoding="utf-8", errors="ignore")
        if "#249" in texto and all(f'"{t}"' in texto for t in TABLAS):
            return
    raise AssertionError("sin migración, las tablas siguen en la base aunque no estén en el modelo")


def test_la_siembra_no_crea_cliente_ni_licencia():
    fuente = (SERVER / "app" / "database" / "seeds.py").read_text(encoding="utf-8")

    assert "_seed_dev_client" not in fuente
    assert "_seed_dev_license" not in fuente


def test_los_guiones_de_arreglo_de_esquema_ya_no_estan():
    """Eran de la época de SQLite: añadían columnas que faltaban a estas tablas."""
    assert not (SERVER / "scripts" / "fix_db_schema.py").exists()
    assert not (RAIZ / "scripts" / "fix_db_nif.py").exists()


def test_nadie_nombra_las_clases_en_el_codigo():
    """Ni imports ni usos en `app`, `scripts` ni `mcp_server`; las migraciones antiguas sí."""
    patron = re.compile(r"\b(?:" + "|".join(CLASES) + r")\b")
    culpables: list[str] = []
    for carpeta in (SERVER / "app", SERVER / "scripts", RAIZ / "mcp_server", RAIZ / "shared"):
        for fichero in carpeta.rglob("*.py"):
            if "__pycache__" in fichero.parts or ".venv" in fichero.parts:
                continue
            if patron.search(fichero.read_text(encoding="utf-8", errors="ignore")):
                culpables.append(str(fichero.relative_to(RAIZ)))

    assert culpables == [], f"quedan referencias a las clases retiradas: {culpables}"
