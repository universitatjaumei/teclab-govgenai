"""BD.2 — el esquema lo define Alembic, la aplicación no crea tablas, y CI lo demuestra.

**De dónde sale.** BD.1 censó 36 tablas sin dueño en `govgenai`, y la causa no era una lista sino un
mecanismo: el arranque creaba el esquema desde los metadatos (`init_server_db()` y
`_init_hub_db()`) además de lo que Alembic hace en el despliegue. Esa creación hace lo declarado y
**nunca borra lo que dejó de estarlo**, así que cada modelo retirado dejaba su tabla.

**Lo que se midió antes de decidir.** Aplicada la cadena de Alembic a una base vacía, produce
**exactamente las 51 tablas declaradas**: la creación del arranque no aportaba ninguna. Quitarla no
cuesta cobertura. Y `alembic check` —que compara modelos con base— **fallaba ya** con tres
columnas `nullable=True` en la migración y `NOT NULL` en el modelo: deriva de columna, invisible
para el censo de tablas de BD.1, y presente en producción también.

**Los cuatro tests, y qué vigila cada uno.**

1. La aplicación no crea esquema: ni `create_all` en `db.py`, ni una función de arranque que lo
   haga. Es lo que cierra la fuente de las huérfanas.
2. CI tiene un paso `alembic check` **después** de `alembic upgrade head`. Es la mitad que
   importa: un modelo cambiado sin su migración se pone rojo en el mismo push.
3. Sobre una base desechable con la cadena aplicada, `alembic check` sale limpio. Es lo mismo que
   hará CI, ejecutado aquí para no descubrirlo en el push. Necesita Postgres; se salta si no hay.
4. Las tres columnas que divergían son `NOT NULL` en la base migrada: la verdad era el modelo, y
   la migración de BD.2 lo hace cumplir.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest

RAIZ = Path(__file__).resolve().parents[3]
SERVER = RAIZ / "server"

#: Las tres columnas que la migración de BD.2 endurece. Cada una con la migración que la creó mal.
COLUMNAS_ENDURECIDAS = (
    ("hub_content_findings", "created_at"),  # u2d3e4f5g6h7 (9Q.1)
    ("hub_provider_credentials", "created_at"),  # q7j8k9l0m1n2 (MT.2)
    ("hub_provider_credentials", "updated_at"),  # q7j8k9l0m1n2 (MT.2)
)


class TestLaAplicacionNoCreaEsquema:

    def test_should_have_no_create_all_in_the_app_tree(self):
        """`create_all` en `server/app/` era la fuente de las 36 huérfanas de BD.1.

        Los tests conservan el suyo: crean bases desechables y las tiran. Lo que no puede existir
        es una **aplicación** que cree tablas al arrancar, porque entonces hay dos fuentes del
        esquema y la que no borra gana.
        """
        # `\.create_all\b`: el ACCESO al atributo —con el punto delante—, no la palabra. La
        # docstring de `db.py` explica por qué se quitó y lo nombra entre acentos graves; un
        # guardarraíl que prohíba nombrar lo que prohíbe impide escribir la razón. (Y este
        # comentario evita escribir el nombre completo del atributo junto a `DATABASE_URL`:
        # `test_suite_hygiene.py` busca esa pareja de literales para cazar tests que crean
        # tablas en la base del desarrollador. Es romo a propósito.)
        patron = re.compile(r"\.create_all\b")
        culpables = []
        for fichero in (SERVER / "app").rglob("*.py"):
            texto = fichero.read_text(encoding="utf-8", errors="replace")
            for numero, linea in enumerate(texto.splitlines(), start=1):
                if patron.search(linea) and not linea.lstrip().startswith("#"):
                    culpables.append(f"{fichero.relative_to(RAIZ)}:{numero}: {linea.strip()}")
        assert culpables == [], (
            "la aplicación vuelve a crear esquema por su cuenta. Alembic es la única fuente: "
            "una tabla nueva va con su migración, no con `create_all`:\n  " + "\n  ".join(culpables)
        )

    def test_should_not_import_a_schema_creator_in_main(self):
        """Ni `init_server_db` ni `_init_hub_db` en el arranque. Borradas, no comentadas."""
        main = (SERVER / "app" / "main.py").read_text(encoding="utf-8")
        for nombre in ("init_server_db", "_init_hub_db"):
            assert nombre not in main, (
                f"`{nombre}` sigue en `main.py`. El esquema lo aplica `alembic upgrade head` "
                "antes de arrancar; la aplicación no lo crea"
            )

    def test_should_say_in_db_py_that_alembic_is_the_only_source(self):
        """La causa, dicha donde se lee: `db.py` es el fichero que abre el motor."""
        db = (SERVER / "app" / "database" / "db.py").read_text(encoding="utf-8")
        assert "Alembic" in db or "alembic" in db, (
            "`db.py` tiene que decir que el esquema lo define Alembic y que la aplicación no crea "
            "tablas. Sin la nota, el siguiente que lo lea añadirá un `create_all` «para que "
            "arranque» y volverán las huérfanas"
        )


class TestCiDemuestraQueModelosYMigracionesCoinciden:

    def test_should_run_alembic_check_after_upgrade_in_ci(self):
        """`alembic check` en CI, y después de `alembic upgrade head`, porque compara con la base.

        Sin el `upgrade` antes, comprobaría contra una base vacía y propondría crear todo: rojo
        siempre, y un guardarraíl que siempre está rojo se desactiva.
        """
        ci = (RAIZ / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        # Se buscan las ÓRDENES (`uv run alembic …` al principio de línea), no la mención: el
        # comentario que explica el paso nombra `alembic check` antes de la orden de `upgrade`, y
        # un `find` sobre el texto entero daba el orden al revés.
        upgrade = re.search(r"^\s*uv run alembic upgrade head\s*$", ci, re.MULTILINE)
        check = re.search(r"^\s*uv run alembic check\s*$", ci, re.MULTILINE)
        assert upgrade, "CI no aplica las migraciones a la base del servicio"
        assert check, "CI no ejecuta `alembic check`"
        assert upgrade.start() < check.start(), (
            "`alembic check` tiene que ir DESPUÉS de `alembic upgrade head`"
        )


def _dsn_sync() -> str:
    dsn = os.environ.get("DATABASE_URL_SYNC")
    if dsn:
        return dsn
    from server.app.database.db import DATABASE_URL

    return DATABASE_URL.replace("postgresql+asyncpg", "postgresql+psycopg2")


class _BaseDesechableMigrada:
    """Una base con nombre único y la cadena de Alembic aplicada. Se borra al salir.

    Es el patrón de `test_bootstrap_seed.py`: `DATABASE_URL` sólo se usa como conexión de
    administración para crear y borrar `bd2_check_<hex>`; a la base del desarrollador no se le
    toca ni una fila.
    """

    def __enter__(self):
        import psycopg2

        sync = _dsn_sync()
        plain = sync.replace("postgresql+psycopg2", "postgresql")
        partes = urlsplit(plain)
        try:
            self.admin = psycopg2.connect(urlunsplit(partes._replace(path="/postgres")))
        except Exception as exc:
            pytest.skip(f"Postgres no disponible: {type(exc).__name__}")
        self.admin.autocommit = True
        self.nombre = f"bd2_check_{uuid.uuid4().hex[:12]}"
        with self.admin.cursor() as cur:
            cur.execute(f'CREATE DATABASE "{self.nombre}"')
        self.sync = urlunsplit(urlsplit(sync)._replace(path=f"/{self.nombre}"))
        self.plain = self.sync.replace("postgresql+psycopg2", "postgresql")
        c = psycopg2.connect(self.plain)
        c.autocommit = True
        with c.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        c.close()
        subida = self._alembic("upgrade", "head")
        assert subida.returncode == 0, f"la cadena no sube en una base vacía:\n{subida.stderr[-2000:]}"
        return self

    def _alembic(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=SERVER,
            env={**os.environ, "DATABASE_URL_SYNC": self.sync},
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )

    def __exit__(self, *_exc):
        with self.admin.cursor() as cur:
            cur.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (self.nombre,),
            )
            cur.execute(f'DROP DATABASE IF EXISTS "{self.nombre}"')
        self.admin.close()


class TestLaCadenaYLosModelosCoinciden:

    def test_should_pass_alembic_check_on_a_freshly_migrated_database(self):
        """Lo que CI hará, hecho aquí. Si falla, hay un modelo sin migración o al revés."""
        with _BaseDesechableMigrada() as base:
            resultado = base._alembic("check")
        salida = (resultado.stdout + resultado.stderr)
        assert resultado.returncode == 0, (
            "`alembic check` ve diferencias entre los modelos y la base que producen las "
            "migraciones. Cada línea de abajo es o un modelo sin migración o una migración que "
            "dijo otra cosa que el modelo:\n" + salida[-3000:]
        )

    def test_should_have_the_three_drifted_columns_not_null(self):
        """La verdad era el modelo: `default` en Python, cero nulos en 292 filas en dos entornos."""
        import psycopg2

        with _BaseDesechableMigrada() as base:
            with psycopg2.connect(base.plain) as c, c.cursor() as cur:
                todavia_nulas = []
                for tabla, columna in COLUMNAS_ENDURECIDAS:
                    cur.execute(
                        "SELECT is_nullable FROM information_schema.columns "
                        "WHERE table_name = %s AND column_name = %s",
                        (tabla, columna),
                    )
                    (nulable,) = cur.fetchone()
                    if nulable == "YES":
                        todavia_nulas.append(f"{tabla}.{columna}")
        assert todavia_nulas == [], (
            f"siguen admitiendo NULL en la base migrada: {todavia_nulas}. El modelo las declara "
            "`Mapped[datetime]` —NOT NULL— y la migración que las creó dijo `nullable=True`; "
            "REG.1 y USR.1 lo anotaron y lo aplazaron. BD.2 es quien lo cierra"
        )


class TestLaFronteraEdgeCloudEstaEnLaBase:
    """Ninguna tabla operacional tiene FK hacia una tabla de configuración.

    **Lo que `alembic check` no puede ver.** Compara los modelos con la base: si alguien añadiera
    la FK cruzada al modelo Y a una migración, saldría limpio. La frontera edge/cloud de
    `AGENTS.md` —`HubOperationalBase` vive sólo en el edge, `HubConfigBase` se sincroniza desde el
    cloud— es una regla sobre el **esquema resultante**, y hay que mirarla en la base.

    **Y no era teórico.** La primera migración del Hub creó `chatbot_id → hub_chatbots` con
    `ON DELETE CASCADE` en tres tablas operacionales, los modelos dejaron de declararla con el
    split, y la cadena la conservó: en producción, borrar un chatbot destruía sus interacciones
    en silencio, contra la decisión escrita en `corpus_purge.py` de no reescribir la historia de lo
    que el asistente contestó. `8f5a3c2d1e07` las retiró; esto impide que vuelvan.
    """

    def test_should_have_no_fk_from_operational_to_config_tables(self):
        import psycopg2

        from server.app.modules.agents_hub.database.base import HubConfigBase, HubOperationalBase
        import server.app.modules.agents_hub.database.config_models
        import server.app.modules.agents_hub.database.operational_models  # noqa: F401

        operacionales = set(HubOperationalBase.metadata.tables)
        de_configuracion = set(HubConfigBase.metadata.tables)

        with _BaseDesechableMigrada() as base:
            with psycopg2.connect(base.plain) as c, c.cursor() as cur:
                cur.execute(
                    """
                    SELECT tc.table_name, ccu.table_name, tc.constraint_name
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.constraint_column_usage ccu
                      ON tc.constraint_name = ccu.constraint_name
                     AND tc.table_schema = ccu.table_schema
                    WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = 'public'
                    """
                )
                cruzadas = sorted(
                    f"{hija}.{nombre} → {madre}"
                    for hija, madre, nombre in cur.fetchall()
                    if hija in operacionales and madre in de_configuracion
                )

        assert cruzadas == [], (
            "FK desde una tabla operacional (edge) hacia una de configuración (cloud): "
            f"{cruzadas}. En el edge la tabla destino puede no estar en la misma base, y el "
            "CASCADE borra en producción lo que el código decidió conservar. Se navega por "
            "`chatbot_id` con consulta explícita, no con FK"
        )


def test_should_not_shadow_the_reason_with_a_regex_false_positive():
    """El primer test busca la cadena `create_all`; este fichero la nombra en su docstring.

    `rglob` sólo recorre `server/app/`, así que este fichero no se ve a sí mismo — pero conviene
    decirlo, porque es la clase de guardarraíl que se rompe al primero que lo «mejora» ampliando
    el árbol a `server/`.
    """
    assert re.search(r"rglob\(\"\*\.py\"\)", Path(__file__).read_text(encoding="utf-8"))
