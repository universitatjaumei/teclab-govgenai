"""USR.5 — el correo de un administrador es único, y por qué importa.

`AdminAccount.email` **no tenía restricción de unicidad** mientras dos sitios lo consultan
esperando una sola fila:

* `login_admin` (`auth_router.py`), con `.first()`.
* el ACS de SAML (`identity_service.py`), al reencontrar a quien entra por el IdP.

Con dos filas del mismo correo, cuál de las dos gana depende del orden que devuelva Postgres, que
no está definido sin `ORDER BY`. El síntoma sería **un 401 intermitente**: la misma contraseña
entra unas veces y otras no, según qué fila conteste. Imposible de diagnosticar desde fuera, y el
mismo patrón que `SuperAdminAccount` ya descarta —ahí el correo **sí** es único—.

**Ahora es el momento barato.** Medido el 2026-09-03: `adminaccount` tiene **1 fila** en
desarrollo y **0 en producción**, así que el índice entra sin migración de datos. Mañana, con
cuentas creadas, haría falta decidir qué hacer con los duplicados antes de poder crearlo.

Vive en este directorio porque aquí está la fixture `db_session`; el sujeto es
`server.app.database.models`, no `agents_hub`.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError

CORREO = "duplicado@uji.es"


@pytest.fixture(autouse=True)
async def _tablas_de_cuenta(db_session):
    from sqlmodel import SQLModel

    import server.app.database.models  # noqa: F401

    conexion = await db_session.connection()
    await conexion.run_sync(SQLModel.metadata.create_all)
    await db_session.commit()


def _admin(correo: str):
    from server.app.database.models import AdminAccount

    return AdminAccount(
        partner_id=f"p-{uuid.uuid4().hex[:10]}",
        name="Administración de prueba",
        email=correo,
    )


class TestElCorreoEsUnico:

    async def test_should_refuse_two_admins_with_the_same_email(self, db_session):
        """El índice único, visto desde donde se nota: la base lo rechaza."""
        db_session.add(_admin(CORREO))
        await db_session.flush()

        db_session.add(_admin(CORREO))
        with pytest.raises(IntegrityError):
            await db_session.flush()

    async def test_should_still_allow_two_admins_with_different_emails(self, db_session):
        """La restricción es sobre el correo, no sobre la tabla."""
        db_session.add(_admin("uno@uji.es"))
        db_session.add(_admin("otro@uji.es"))
        await db_session.flush()  # no levanta

    async def test_should_declare_it_in_the_model_and_not_only_in_the_database(self):
        """Si sólo estuviera en la migración, una instalación nueva desde el modelo no lo tendría.

        La comprobación es sobre la columna del ORM: es lo que copia
        `SQLModel.metadata.create_all`, que es como nacen las tablas en los tests y en cualquier
        arranque que no pase por Alembic.
        """
        from server.app.database.models import AdminAccount

        columna = AdminAccount.__table__.c.email
        assert columna.unique, "`AdminAccount.email` no está declarada única en el modelo"


class TestLasOtrasTablasDeIdentidad:
    """Lo que el prompt mandaba comprobar, y no suponer."""

    def test_should_confirm_the_superadmin_email_was_already_unique(self):
        from server.app.database.models import SuperAdminAccount

        assert SuperAdminAccount.__table__.c.email.unique

    def test_should_confirm_the_person_email_was_already_unique(self):
        from server.app.modules.agents_hub.database.config_models import HubUser

        assert HubUser.__table__.c.email.unique
