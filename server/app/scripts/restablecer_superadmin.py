"""Restablecer la contraseña de un superadministrador que ya existe. Deploy: n/a.

**Es el último recurso de una cuenta, no un mecanismo de recuperación para usuarios.** Si el
superadministrador pierde su contraseña no hay camino de vuelta por producto: `bootstrap` **no**
rehashea —a propósito, para que reejecutar `setup.sh` no revierta un cambio posterior—,
`PATCH /admins/{id}/password` es sólo superadmin y por tanto no puede ayudarle a él mismo, y la
plataforma **no puede enviar correo**, así que no hay autoservicio posible. Antes de esto la única
salida era escribir un hash de bcrypt a mano en la base de producción (issue #96).

Y no lo arregla el login con Google: el login local del superadministrador se conserva **como
reserva**, justo para poder entrar cuando Google o su configuración fallen. Es esa reserva la que
no tenía recuperación.

**Por qué es un guion y no un endpoint.** Su autorización no es un rol: es **tener acceso a la
máquina** —SSH por IAP, `sudo`, `docker`—. Añadir un rol no añadiría seguridad, porque quien puede
ejecutar `docker exec` en esa máquina ya puede escribir en la base. Conviene dejarlo escrito
porque es la primera pregunta que hace quien lo lee.

**Tres reglas que lo separan de `bootstrap`:**

1. **Se niega a crear.** Si el correo no existe, error. `bootstrap` hace lo contrario y de ahí
   salía un agujero real: una errata creaba un segundo superadministrador en silencio.
2. **La contraseña entra por entrada estándar, nunca por `argv`**: un `--password` queda en el
   historial del *shell* y se ve en `ps` mientras corre.
3. **No se imprime**, ni ella ni su hash.

Uso, dentro del contenedor de la máquina:

    python -m server.app.scripts.restablecer_superadmin --email persona@organizacion

Pide la contraseña dos veces —se teclea a ciegas— y no la muestra.
"""

from __future__ import annotations

from sqlmodel import col

import argparse
import asyncio
import getpass
import sys
from datetime import datetime, timezone

from sqlalchemy import select

from server.app.core.security import hash_password
from server.app.database.models import SuperAdminAccount
from server.app.modules.agents_hub.database.connection import (
    create_async_engine,
    create_session_factory,
)

#: El mínimo del contrato de contraseña (`SetPasswordRequest`). No es una regla nueva: es la
#: misma, comprobada aquí para no dejar la cuenta con algo que el login rechazaría.
LONGITUD_MINIMA = 12


class ErrorDeRestablecimiento(RuntimeError):
    """No se puede restablecer. El motivo va en el mensaje, para quien ejecuta."""


def _pedir_contrasena() -> str:
    """Dos veces, y sin eco cuando hay terminal.

    Sin terminal —una tubería, un test— se leen dos líneas de la entrada estándar. Se pide dos
    veces porque se teclea a ciegas: una errata dejaría la cuenta con una contraseña que nadie
    conoce, que es peor que el problema que se venía a resolver.
    """
    if sys.stdin.isatty():
        primera = getpass.getpass("Contraseña nueva: ")
        segunda = getpass.getpass("Repítela: ")
    else:
        primera = sys.stdin.readline().rstrip("\n")
        segunda = sys.stdin.readline().rstrip("\n")

    if not primera:
        raise ErrorDeRestablecimiento("no se ha introducido ninguna contraseña")
    if primera != segunda:
        raise ErrorDeRestablecimiento("las dos contraseñas no coinciden; no se ha cambiado nada")
    if len(primera) < LONGITUD_MINIMA:
        raise ErrorDeRestablecimiento(
            f"la contraseña tiene que tener al menos {LONGITUD_MINIMA} caracteres; "
            "no se ha cambiado nada"
        )
    return primera


async def _restablecer(email: str, contrasena: str, url: str | None) -> str:
    """Fija la contraseña de un superadministrador **existente**. Devuelve su nombre."""
    engine = create_async_engine(url)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            cuenta = (
                await session.execute(
                    select(SuperAdminAccount).where(col(SuperAdminAccount.email) == email)
                )
            ).scalar_one_or_none()

            # **Se niega a crear**, y es la diferencia con `bootstrap`. Un correo que no existe
            # es casi siempre una errata, y crear una cuenta a partir de una errata es el
            # agujero que este guion no puede tener.
            if cuenta is None:
                raise ErrorDeRestablecimiento(
                    f"no hay ningún superadministrador con el correo «{email}». Este guion "
                    "restablece, no crea: comprueba el correo."
                )

            cuenta.hashed_password = hash_password(contrasena)
            await session.commit()
            return cuenta.name
    finally:
        await engine.dispose()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m server.app.scripts.restablecer_superadmin",
        description=(
            "Restablece la contraseña de un superadministrador que YA EXISTE. La contraseña se "
            "pide por entrada estándar: no hay ninguna opción para pasarla como argumento, "
            "porque quedaría en el historial del shell y sería visible en `ps`."
        ),
    )
    parser.add_argument(
        "--email",
        required=True,
        help="Correo del superadministrador. Si no existe, el guion falla y no crea nada.",
    )
    parser.add_argument(
        "--database-url", default=None, help="Por defecto, DATABASE_URL del entorno."
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        contrasena = _pedir_contrasena()
        nombre = asyncio.run(_restablecer(args.email, contrasena, args.database_url))
    except ErrorDeRestablecimiento as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    # La traza. Un uso de emergencia que no deja rastro es indistinguible de un acceso no
    # autorizado que sí supo hacerlo, así que se dice quién, cuándo y por qué vía — en el
    # registro de la aplicación, que es lo que producción recoge.
    #
    # **Nunca la contraseña ni su hash**: el guion los tiene en memoria y no los enseña.
    cuando = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(
        f"Restablecida la contraseña de «{args.email}» ({nombre}) el {cuando} "
        f"mediante el guion de emergencia, ejecutado con acceso a la máquina."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
