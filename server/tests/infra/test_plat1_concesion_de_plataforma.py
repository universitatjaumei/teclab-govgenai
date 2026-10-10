"""PLAT.1 — nadie pierde acceso cuando el módulo `plataforma` empiece a exigirse.

El Bloque PLAT va a declarar `require_module("plataforma")` en los routers de configuración
(PLAT.5). Hoy la única pantalla que lo exige —`hub_llm_configs`— está montada bajo el módulo
`chatbots`, así que quien administra la plataforma llega ahí con la concesión de `chatbots`.
Aplicar la frontera sin repartir antes la concesión deja a esa persona fuera, y el síntoma llega
como un 403 sin explicación.

**La premisa del prompt estaba medida a medias, y se corrige aquí.** El prompt decía que «nadie
tiene `plataforma` salvo los superadmin». Falso para las cuentas que existían al aplicar INF.7:
su migración (`j0c1d2e3f4g5`) siembra **los cuatro módulos** a cada fila de `superadminaccount` y
`adminaccount`. Verificado en la BD de desarrollo: los dos sujetos que hay tienen los cuatro.

Lo que sí queda descubierto, y es el motivo real de esta migración:

- Los sujetos a los que se concedió `chatbots` **después** de INF.7. Ahí no hay semilla que valga.
- Los **usuarios de SSO**: INF.7 solo leyó `superadminaccount` y `adminaccount`, así que ninguna
  identidad aprovisionada por el IdP recibió nada.

De ahí que la migración sea un **relleno idempotente** —«a quien tenga `chatbots` y no
`plataforma`, dale `plataforma`»— y no una siembra: en la mayoría de las instalaciones no hará
nada, y eso es exactamente lo que tiene que pasar.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import psycopg2
import pytest

_SERVER_ROOT = Path(__file__).parent.parent.parent

#: La revisión anterior a PLAT.1: la de INF.7, que creó las dos tablas.
_ANTES_DE_PLAT1 = "j0c1d2e3f4g5"

#: Quién firma las filas que crea esta migración. Es lo que permite que `downgrade` retire
#: exactamente lo suyo y no una concesión que puso una persona.
_FIRMA = "migracion:plat1"


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


def _conceder(fresh_database: str, filas: list[tuple[str, str]], granted_by: str | None = None) -> None:
    conn = _conexion(fresh_database)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            for sujeto, modulo in filas:
                cur.execute(
                    "INSERT INTO hub_module_grants (subject_id, module_code, granted_by)"
                    " VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                    (sujeto, modulo, granted_by),
                )
    finally:
        conn.close()


def _modulos_de(fresh_database: str, sujeto: str) -> list[str]:
    conn = _conexion(fresh_database)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT module_code FROM hub_module_grants WHERE subject_id = %s"
                " ORDER BY module_code",
                (sujeto,),
            )
            return [r[0] for r in cur.fetchall()]
    finally:
        conn.close()


def _cuenta(fresh_database: str, sujeto: str, modulo: str) -> int:
    conn = _conexion(fresh_database)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM hub_module_grants"
                " WHERE subject_id = %s AND module_code = %s",
                (sujeto, modulo),
            )
            return cur.fetchone()[0]
    finally:
        conn.close()


SOLO_CHATBOTS = "11111111-1111-1111-1111-111111111111"
YA_TENIA_PLATAFORMA = "22222222-2222-2222-2222-222222222222"
SOLO_INFORMES = "33333333-3333-3333-3333-333333333333"


@pytest.fixture
def base_en_inf7(fresh_database: str) -> str:
    """Base migrada hasta INF.7, con tres sujetos en los tres estados que importan."""
    resultado = _alembic(fresh_database, "upgrade", _ANTES_DE_PLAT1)
    assert resultado.returncode == 0, resultado.stderr

    _conceder(fresh_database, [(SOLO_CHATBOTS, "chatbots")])
    _conceder(
        fresh_database,
        [(YA_TENIA_PLATAFORMA, "chatbots"), (YA_TENIA_PLATAFORMA, "plataforma")],
        granted_by="una-persona",
    )
    _conceder(fresh_database, [(SOLO_INFORMES, "informes")])
    return fresh_database


class TestLaMigracionRellenaSinPisar:

    def test_should_grant_plataforma_to_whoever_has_chatbots(self, base_en_inf7: str):
        """El test del prompt: quien administra hoy con `chatbots` no se queda fuera."""
        assert _modulos_de(base_en_inf7, SOLO_CHATBOTS) == ["chatbots"]

        resultado = _alembic(base_en_inf7, "upgrade", "head")
        assert resultado.returncode == 0, resultado.stderr

        # `upgrade head` pasa por todas las migraciones posteriores, y USR.9 concede
        # `personas` a quien tenga `plataforma`: la cadena es correcta y la lista crece. Lo que
        # este test fija es que **`plataforma` llega**, no que sea el único añadido.
        assert "plataforma" in _modulos_de(base_en_inf7, SOLO_CHATBOTS)

    def test_should_not_duplicate_an_existing_grant(self, base_en_inf7: str):
        """La restricción única ya lo impediría con un error; aquí se exige que **no falle**."""
        resultado = _alembic(base_en_inf7, "upgrade", "head")
        assert resultado.returncode == 0, resultado.stderr

        assert _cuenta(base_en_inf7, YA_TENIA_PLATAFORMA, "plataforma") == 1

    def test_should_not_touch_someone_without_chatbots(self, base_en_inf7: str):
        """Quien solo hace informes no tiene por qué administrar la plataforma."""
        _alembic(base_en_inf7, "upgrade", "head")

        # Lo que se comprueba es que PLAT.1 no le da `plataforma`, no la lista entera: se migra
        # hasta `head`, y AUT.14 le da `automatizacion` a propósito a quien tenía `informes`.
        # Con la lista exacta, esta prueba se puso roja por una migración posterior correcta.
        modulos = _modulos_de(base_en_inf7, SOLO_INFORMES)
        assert "plataforma" not in modulos
        assert "informes" in modulos

    def test_should_not_steal_the_authorship_of_a_grant_a_person_made(self, base_en_inf7: str):
        """La concesión que puso una persona sigue firmada por ella: `granted_by` es la
        auditoría del permiso, y sobreescribirla la borra."""
        _alembic(base_en_inf7, "upgrade", "head")

        conn = _conexion(base_en_inf7)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT granted_by FROM hub_module_grants"
                    " WHERE subject_id = %s AND module_code = 'plataforma'",
                    (YA_TENIA_PLATAFORMA,),
                )
                assert cur.fetchone()[0] == "una-persona"
        finally:
            conn.close()


class TestElCatalogoTieneElModulo:

    def test_should_seed_plataforma_when_an_old_install_lacks_it(self, base_en_inf7: str):
        """`MODULOS_INICIALES` es semilla, no definición: una instalación puede no tenerlo.

        Y sin la fila del catálogo, `modulos_del_usuario` filtra por `vigente` y la concesión
        no sirve para nada — el relleno habría sido decorativo.
        """
        conn = _conexion(base_en_inf7)
        conn.autocommit = True
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM hub_module_grants WHERE module_code = 'plataforma'")
                cur.execute("DELETE FROM hub_platform_modules WHERE code = 'plataforma'")
        finally:
            conn.close()

        resultado = _alembic(base_en_inf7, "upgrade", "head")
        assert resultado.returncode == 0, resultado.stderr

        conn = _conexion(base_en_inf7)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT vigente FROM hub_platform_modules WHERE code = 'plataforma'"
                )
                fila = cur.fetchone()
        finally:
            conn.close()

        assert fila is not None, "la migración tiene que sembrar el módulo si no está"
        assert fila[0] is True


class TestLaMigracionEsReversibleEIdempotente:

    def test_should_remove_only_the_rows_it_created(self, base_en_inf7: str):
        """`downgrade` retira lo suyo —firmado— y deja lo que puso una persona."""
        _alembic(base_en_inf7, "upgrade", "head")
        assert _cuenta(base_en_inf7, SOLO_CHATBOTS, "plataforma") == 1

        resultado = _alembic(base_en_inf7, "downgrade", _ANTES_DE_PLAT1)
        assert resultado.returncode == 0, resultado.stderr

        assert _cuenta(base_en_inf7, SOLO_CHATBOTS, "plataforma") == 0
        assert _cuenta(base_en_inf7, YA_TENIA_PLATAFORMA, "plataforma") == 1
        assert _modulos_de(base_en_inf7, SOLO_INFORMES) == ["informes"]

    def test_should_be_idempotent_across_a_full_round_trip(self, base_en_inf7: str):
        """Aplicar, revertir y volver a aplicar deja exactamente el mismo estado."""
        _alembic(base_en_inf7, "upgrade", "head")
        primera = _modulos_de(base_en_inf7, SOLO_CHATBOTS)

        _alembic(base_en_inf7, "downgrade", _ANTES_DE_PLAT1)
        resultado = _alembic(base_en_inf7, "upgrade", "head")
        assert resultado.returncode == 0, resultado.stderr

        assert _modulos_de(base_en_inf7, SOLO_CHATBOTS) == primera
        assert _cuenta(base_en_inf7, SOLO_CHATBOTS, "plataforma") == 1

    def test_should_sign_its_own_rows(self, base_en_inf7: str):
        """Sin firma no hay forma de que `downgrade` distinga sus filas de las ajenas."""
        _alembic(base_en_inf7, "upgrade", "head")

        conn = _conexion(base_en_inf7)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT granted_by FROM hub_module_grants"
                    " WHERE subject_id = %s AND module_code = 'plataforma'",
                    (SOLO_CHATBOTS,),
                )
                assert cur.fetchone()[0] == _FIRMA
        finally:
            conn.close()
