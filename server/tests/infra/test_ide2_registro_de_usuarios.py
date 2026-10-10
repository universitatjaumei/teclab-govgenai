"""IDE.2 — `HubSsoUser` no es de SSO: es la tabla de usuarios.

Tiene correo único, nombre, rol, organización, activo y último acceso. Es una tabla de usuarios
completa; se llamaba así porque su **único escritor** era el ACS de SAML. Mientras el nombre
dijera «SSO», nadie iba a escribir ahí una persona dada de alta a mano, y el siguiente que lo
necesitara habría creado una segunda tabla — que es como se llegó a las cuatro que hubo
(`SuperAdminAccount`, `AdminAccount`, `ClientAccount` —retirada en #249—, y esta).

**Las migraciones antiguas no se renombran.** `w4f5g6h7i8j9` creó `hub_sso_users` y
`q4z5a6b7c8d9` le añadió la organización: una migración describe lo que hizo el día que se
aplicó, y reescribirla convierte el historial del esquema en ficción. El renombrado lo hace una
migración nueva, con `ALTER TABLE ... RENAME` y no crear-y-copiar, para no mover los datos.

**Lo que este prompt NO hace, y está dicho a propósito**: unificar las otras tres tablas de
identidad. `user_to_uuid` está en la propiedad de los workspaces de redacción, en los PAT y en
las concesiones de módulo, y `es_propietario` ya tiene que aceptar **las dos formas** en que
quedó escrita la propiedad (SEC.8.1). Eso es una migración de datos con riesgo real y merece su
propio bloque, con inventario antes de tocar nada.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import psycopg2
import pytest

_SERVER_ROOT = Path(__file__).parent.parent.parent
_RAIZ = _SERVER_ROOT.parent

#: La revisión anterior a IDE.2: la de PLAT.1.
_ANTES_DE_IDE2 = "k1d2e3f4g5h6"


def _alembic(fresh_database: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=_SERVER_ROOT,
        env={**os.environ, "DATABASE_URL_SYNC": fresh_database},
        capture_output=True,
        text=True,
        timeout=240,
    )


def _conexion(fresh_database: str):
    return psycopg2.connect(fresh_database.replace("postgresql+psycopg2", "postgresql"))


def _existe_tabla(fresh_database: str, tabla: str) -> bool:
    conn = _conexion(fresh_database)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "select exists (select 1 from information_schema.tables"
                " where table_schema = 'public' and table_name = %s)",
                (tabla,),
            )
            return cur.fetchone()[0]
    finally:
        conn.close()


def _columnas(fresh_database: str, tabla: str) -> set[str]:
    conn = _conexion(fresh_database)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "select column_name from information_schema.columns where table_name = %s",
                (tabla,),
            )
            return {r[0] for r in cur.fetchall()}
    finally:
        conn.close()


@pytest.fixture
def base_antes_de_ide2(fresh_database: str) -> str:
    """Base migrada hasta PLAT.1, con dos personas dentro de la tabla vieja."""
    resultado = _alembic(fresh_database, "upgrade", _ANTES_DE_IDE2)
    assert resultado.returncode == 0, resultado.stderr

    conn = _conexion(fresh_database)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            for correo, rol in (("una@uji.es", "admin"), ("otra@uji.es", "user")):
                # `created_at` es NOT NULL y sin defecto de servidor en la migración que
                # creó la tabla: el valor lo pone el ORM. Aquí se inserta a pelo.
                cur.execute(
                    "INSERT INTO hub_sso_users"
                    " (id, email, display_name, role, is_active, created_at)"
                    " VALUES (gen_random_uuid(), %s, %s, %s, true, now())",
                    (correo, correo.split("@")[0], rol),
                )
    finally:
        conn.close()
    return fresh_database


class TestElRenombradoConservaLosDatos:

    def test_should_rename_the_table_instead_of_recreating_it(self, base_antes_de_ide2: str):
        assert _existe_tabla(base_antes_de_ide2, "hub_sso_users")

        resultado = _alembic(base_antes_de_ide2, "upgrade", "head")
        assert resultado.returncode == 0, resultado.stderr

        assert _existe_tabla(base_antes_de_ide2, "hub_users")
        assert not _existe_tabla(base_antes_de_ide2, "hub_sso_users")

    def test_should_not_lose_a_single_row(self, base_antes_de_ide2: str):
        """El motivo de renombrar en vez de crear y copiar."""
        _alembic(base_antes_de_ide2, "upgrade", "head")

        conn = _conexion(base_antes_de_ide2)
        try:
            with conn.cursor() as cur:
                cur.execute("select email, role from hub_users order by email")
                filas = cur.fetchall()
        finally:
            conn.close()

        assert filas == [("otra@uji.es", "user"), ("una@uji.es", "admin")]

    def test_should_keep_the_columns_it_had(self, base_antes_de_ide2: str):
        _alembic(base_antes_de_ide2, "upgrade", "head")

        columnas = _columnas(base_antes_de_ide2, "hub_users")

        assert {"id", "email", "display_name", "role", "external_id", "idp_entity_id",
                "organizacion_id", "is_active", "created_at", "last_login_at"} <= columnas

    def test_should_revert_cleanly(self, base_antes_de_ide2: str):
        _alembic(base_antes_de_ide2, "upgrade", "head")

        resultado = _alembic(base_antes_de_ide2, "downgrade", _ANTES_DE_IDE2)
        assert resultado.returncode == 0, resultado.stderr

        assert _existe_tabla(base_antes_de_ide2, "hub_sso_users")
        assert not _existe_tabla(base_antes_de_ide2, "hub_users")
        assert "origen" not in _columnas(base_antes_de_ide2, "hub_sso_users")


class TestElOrigenDeCadaPersona:

    def test_should_mark_the_existing_rows_as_provisioned_by_sso(self, base_antes_de_ide2: str):
        """Las que ya estaban solo pudieron entrar por el ACS: no había otro escritor."""
        _alembic(base_antes_de_ide2, "upgrade", "head")

        conn = _conexion(base_antes_de_ide2)
        try:
            with conn.cursor() as cur:
                cur.execute("select distinct origen from hub_users")
                assert cur.fetchall() == [("sso",)]
        finally:
            conn.close()

    def test_should_refuse_a_value_outside_the_two(self, base_antes_de_ide2: str):
        """Con `CheckConstraint` y no con un `Enum` de Python: son dos valores estables, cada
        uno con consumidor en el código. Mismo criterio que `purpose` en `HubLLMConfig`."""
        _alembic(base_antes_de_ide2, "upgrade", "head")

        conn = _conexion(base_antes_de_ide2)
        conn.autocommit = True
        try:
            with conn.cursor() as cur:
                with pytest.raises(psycopg2.errors.CheckViolation):
                    cur.execute(
                        "INSERT INTO hub_users (id, email, role, is_active, origen, created_at)"
                        " VALUES (gen_random_uuid(), 'x@uji.es', 'user', true, 'ldap', now())"
                    )
        finally:
            conn.close()

    def test_should_default_to_sso_for_a_row_that_does_not_say(self, base_antes_de_ide2: str):
        """El ACS no va a escribir `origen` explícitamente en cada entrada, y una fila sin
        origen no puede quedarse en NULL: `manual` y `sso` se distinguen en la pantalla."""
        _alembic(base_antes_de_ide2, "upgrade", "head")

        conn = _conexion(base_antes_de_ide2)
        conn.autocommit = True
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO hub_users (id, email, role, is_active, created_at)"
                    " VALUES (gen_random_uuid(), 'sin-origen@uji.es', 'user', true, now())"
                )
                cur.execute("select origen from hub_users where email = 'sin-origen@uji.es'")
                assert cur.fetchone()[0] == "sso"
        finally:
            conn.close()


class TestNoQuedaRastroDelNombreViejo:
    """El `grep -r` a cero, pero sin dispararse con su propia explicación.

    Buscar la cadena en el texto del fichero convierte en falso positivo el docstring que
    cuenta **por qué** se renombró: es la trampa que `test_theme_persistence.py` documentó
    —«se comprueba el módulo cargado y no el texto del fichero, porque buscar la cadena
    obligaría a no poder contarla»— y que ya volvió a morder en el frontend con
    `assetsVersionados.test.ts`. Aquí se resuelve con `ast`, que sí distingue un docstring de
    una cadena de verdad como `__tablename__ = "hub_sso_users"`.
    """

    @staticmethod
    def _identificadores_y_cadenas(fuente: str) -> set[str]:
        """Nombres y cadenas del módulo, **sin** docstrings ni comentarios."""
        import ast

        arbol = ast.parse(fuente)
        docstrings: set[int] = set()
        for nodo in ast.walk(arbol):
            cuerpo = getattr(nodo, "body", None)
            if not isinstance(cuerpo, list) or not cuerpo:
                continue
            primero = cuerpo[0]
            if (
                isinstance(primero, ast.Expr)
                and isinstance(primero.value, ast.Constant)
                and isinstance(primero.value.value, str)
            ):
                docstrings.add(id(primero.value))

        piezas: set[str] = set()
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.Name):
                piezas.add(nodo.id)
            elif isinstance(nodo, ast.Attribute):
                piezas.add(nodo.attr)
            elif isinstance(nodo, ast.alias):
                piezas.add(nodo.name)
                if nodo.asname:
                    piezas.add(nodo.asname)
            elif isinstance(nodo, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                piezas.add(nodo.name)
            elif (
                isinstance(nodo, ast.Constant)
                and isinstance(nodo.value, str)
                and id(nodo) not in docstrings
            ):
                piezas.add(nodo.value)
        return piezas

    def test_should_not_keep_the_old_model_name_in_the_application(self):
        """Sin alias ni re-exportaciones: `AGENTS.md` prohíbe los shims de compatibilidad."""
        culpables = []
        for arbol in ("app", "../mcp_server", "../shared"):
            base = (_SERVER_ROOT / arbol).resolve()
            if not base.exists():
                continue
            for ruta in base.rglob("*.py"):
                if "__pycache__" in ruta.parts:
                    continue
                piezas = self._identificadores_y_cadenas(
                    ruta.read_text(encoding="utf-8", errors="ignore")
                )
                for nombre in ("HubSsoUser", "hub_sso_users"):
                    if any(nombre in pieza for pieza in piezas):
                        culpables.append(f"{ruta.relative_to(_RAIZ)} → {nombre}")

        assert culpables == [], (
            "el nombre viejo sigue en el código de aplicación:\n  " + "\n  ".join(culpables)
        )

    def test_should_expose_the_new_model_and_table(self):
        """Sobre el módulo cargado, no sobre su texto: es lo que de verdad usa la aplicación."""
        from server.app.modules.agents_hub.database import config_models

        assert hasattr(config_models, "HubUser")
        assert not hasattr(config_models, "HubSsoUser"), "sin alias de compatibilidad"
        assert config_models.HubUser.__tablename__ == "hub_users"

    def test_should_not_leave_the_old_table_in_the_orm_metadata(self):
        from server.app.modules.agents_hub.database.base import HubConfigBase

        tablas = set(HubConfigBase.metadata.tables)
        assert "hub_users" in tablas
        assert "hub_sso_users" not in tablas

    def test_should_keep_the_old_name_in_the_migrations_that_used_it(self):
        """Y al revés: **las migraciones antiguas no se tocan**. Describen lo que hicieron el
        día que se aplicaron, y reescribirlas convierte el historial del esquema en ficción."""
        versiones = _SERVER_ROOT / "migrations" / "versions"
        creadora = versiones / "w4f5g6h7i8j9_hub_sso_users_auth2.py"

        assert creadora.exists(), "la migración que creó la tabla no puede desaparecer"
        assert "hub_sso_users" in creadora.read_text(encoding="utf-8")
