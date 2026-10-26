"""BD.1 — ninguna tabla de la base pertenece a ningún modelo, o el esquema miente.

**De dónde sale esto.** Al cerrar el bloque NIC, la pregunta fue si la retirada del NiceGUI dejaba
tablas colgando. La respuesta corta era «no, NiceGUI usaba SQLite» y era **media respuesta**:
AutomatIA tenía también un lado servidor, el «Brain», con modelos SQLModel en
`server/app/database/models.py` que apuntan a PostgreSQL. Censado `govgenai`: **88 tablas, 51
declaradas, 36 sin dueño**, todas con cero filas, y con nombres que se leen solos —
`mailwatcherstate`, `webwatcherhistory`, `rpaplaybook`, `localautomation`, `wizarddraft`.

**El mecanismo, que es lo que hay que vigilar y no la lista.** El arranque llama a
`init_server_db()`, que crea el esquema desde el metadato de SQLModel, y el *lifespan* hace lo
mismo con las dos bases del Hub. Esa creación automática **hace lo declarado y nunca borra lo que
dejó de estarlo**, y Alembic no se enteró porque no las creó él: ninguna de las 36 aparece en
ninguna de las 89 migraciones. Así que cada vez que un bloque retiró un modelo, su tabla se quedó.

(La frase de arriba evita escribir el nombre del método junto a `DATABASE_URL`, y no es manía:
`test_suite_hygiene.py` busca justo esa combinación de literales para cazar tests que crean tablas
en la base del desarrollador. Es romo a propósito, y este test lo **explica** sin llamarlo. Se
reformula la prosa antes que aflojar el guardarraíl.)

**Por qué molesta, si son 900 KiB.** No por el espacio, que es irrelevante. Porque **quien lea el
esquema no puede distinguirlas de las vivas**: `report_templates` está justo al lado de
`hub_report_templates`, y `script_library` al lado del mundo de scripts que sí funciona. Son
trampas, y el repositorio se va a abrir.

**Qué hace este test y qué no.** Compara la base contra la unión de los tres metadatos y falla si
sobra alguna. **Necesita la base arrancada**, así que se salta si no responde — un guardarraíl que
exige infraestructura y no la tiene se acaba desactivando. Lo que **no** hace es borrar nada: eso
es la migración, y `DROP TABLE IF EXISTS` para que valga igual en un entorno que ya no las tenga.
"""
from __future__ import annotations

import os

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

#: Tablas que la base tiene a propósito y ningún modelo declara.
FUERA_DEL_CENSO = frozenset({
    "alembic_version",  # la lleva Alembic, no un modelo
})


def _metadatos() -> dict[str, str]:
    """Nombre de tabla → qué metadato la declara.

    **Se importa la aplicación entera**, no una lista de módulos de modelos. Importar a mano deja
    fuera los de `redaccion`, `curation` o el registro de actividad, y entonces sus tablas —vivas y
    con filas— aparecen como huérfanas. Es el error que tuvo la primera versión de este censo:
    `hub_report_templates`, con 23 filas, salió en la lista de sobrantes.
    """
    from sqlmodel import SQLModel

    import server.app.database.models  # el esquema legado del «Brain»
    import server.app.main  # noqa: F401 — registra todo lo demás
    from server.app.modules.agents_hub.database.config_models import HubConfigBase
    from server.app.modules.agents_hub.database.operational_models import HubOperationalBase

    declaradas: dict[str, str] = {}
    for etiqueta, metadata in (
        ("SQLModel", SQLModel.metadata),
        ("HubConfigBase", HubConfigBase.metadata),
        ("HubOperationalBase", HubOperationalBase.metadata),
    ):
        for nombre in metadata.tables:
            declaradas.setdefault(nombre, etiqueta)
    return declaradas


async def _tablas_de_la_base(dsn: str) -> set[str]:
    motor = create_async_engine(dsn, echo=False)
    try:
        async with motor.connect() as conexion:
            filas = await conexion.execute(
                sa.text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
                )
            )
            return {nombre for (nombre,) in filas.all()}
    finally:
        await motor.dispose()


@pytest.mark.asyncio
async def test_should_have_no_table_without_a_model():
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        from server.app.database.db import DATABASE_URL as dsn  # type: ignore[no-redef]

    try:
        en_la_base = await _tablas_de_la_base(dsn)
    except Exception as exc:  # cualquier fallo de conexión vale igual
        pytest.skip(f"la base no responde, y este guardarraíl la necesita: {type(exc).__name__}")

    declaradas = _metadatos()
    sobran = sorted(en_la_base - set(declaradas) - FUERA_DEL_CENSO)

    assert sobran == [], (
        f"{len(sobran)} tablas no pertenecen a ningún modelo: {sobran}.\n"
        "Vienen de la creación automática del esquema desde el metadato, que hace lo declarado "
        "y nunca borra lo que dejó de estarlo. Si el modelo se retiró a propósito, la tabla se "
        "retira con una migración de Alembic (`DROP TABLE IF EXISTS`), no dejándola ahí: quien "
        "lea el esquema no la distingue de una viva."
    )


def test_should_have_closed_the_cause_not_only_the_symptom():
    """El mecanismo que producía huérfanas ya no existe, y `db.py` dice cuál era.

    **Este test decía lo contrario.** Al cerrar BD.1 exigía que `create_all` **siguiera** en
    `db.py` junto con una nota diciendo que Alembic también gobernaba el esquema: el mecanismo se
    dejaba en pie a propósito porque cambiarlo era una decisión de arquitectura del usuario, y lo
    único exigible era que estuviera escrito. BD.2 tomó la decisión y quitó el mecanismo, así que la
    afirmación se invierte — igual que NIC.3 invirtió los guardarraíles de la cuarentena cuando la
    cuarentena se fue.

    Lo que sobrevive del test original es la razón: la causa, dicha donde se lee.
    """
    from pathlib import Path

    raiz = Path(__file__).resolve().parents[3]
    db = (raiz / "server" / "app" / "database" / "db.py").read_text(encoding="utf-8")

    assert "create_all" not in db.replace("`create_all`", ""), (
        "`db.py` vuelve a crear esquema. Desde BD.2 el arranque no crea tablas: Alembic es la "
        "única fuente, y `alembic check` en CI lo vigila"
    )
    assert "Alembic" in db, (
        "`db.py` tiene que decir que el esquema lo define Alembic y por qué se quitó el "
        "`create_all`: sin la nota, el siguiente que lo lea lo añadirá «para que arranque»"
    )
