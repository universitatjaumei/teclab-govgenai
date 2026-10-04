"""Emisión, validación y revocación de Personal Access Tokens (AUTH.3)."""

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select

from server.app.core.auth.models import UserInfo
from server.app.core.auth.pat.scopes import (
    allowed_scopes_for,
    validate_scopes,
)
from server.app.modules.agents_hub.database.config_models import (
    HubPersonalAccessToken,
)

_TOKEN_NS = "pat"
_PREFIX_BYTES = 4  # → 8 hex chars
_SECRET_BYTES = 32


class PatForbiddenError(Exception):
    """El rol no puede emitir el PAT o los scopes exceden su techo."""


class PatInvalidError(Exception):
    """El token es inválido, está revocado o ha expirado."""


@dataclass(frozen=True)
class PatPrincipal:
    """Resultado de validar un PAT: identidad + scopes del token."""

    user_info: UserInfo
    scopes: list[str]


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _parse_prefix(token: str) -> str | None:
    parts = token.split("_", 2)
    if len(parts) != 3 or parts[0] != _TOKEN_NS or not parts[1]:
        return None
    return parts[1]


class PatService:
    """Gestiona el ciclo de vida de los PAT."""

    def __init__(self, session) -> None:
        self.session = session

    async def create(
        self,
        owner: UserInfo,
        name: str,
        scopes: list[str],
        expires_at: datetime | None = None,
        modulos: list[str] | tuple[str, ...] = (),
    ) -> tuple[HubPersonalAccessToken, str]:
        """Crea un PAT y devuelve (fila, token_plano). El plano se ve UNA vez.

        `modulos` son los concedidos al dueño: un módulo puede abrir algún alcance que su rol no
        tiene (#174, `agentes` → `agentes:indice`).
        """
        validate_scopes(scopes)

        allowed = allowed_scopes_for(owner.role, modulos)
        if not allowed:
            raise PatForbiddenError(
                f"Role '{owner.role}' is not allowed to issue access tokens"
            )
        if not set(scopes).issubset(allowed):
            raise PatForbiddenError(
                f"Role '{owner.role}' cannot grant scopes outside its ceiling: "
                f"{', '.join(sorted(set(scopes) - allowed))}"
            )

        prefix = secrets.token_hex(_PREFIX_BYTES)
        secret = secrets.token_urlsafe(_SECRET_BYTES)
        token = f"{_TOKEN_NS}_{prefix}_{secret}"

        pat = HubPersonalAccessToken(
            owner_id=owner.user_id,
            owner_email=owner.email,
            owner_role=owner.role,
            name=name,
            token_prefix=prefix,
            token_hash=_hash_token(token),
            scopes=list(scopes),
            created_at=datetime.now(timezone.utc),
            expires_at=expires_at,
        )
        self.session.add(pat)
        await self.session.commit()
        await self.session.refresh(pat)
        return pat, token

    async def verify(self, token: str) -> PatPrincipal:
        """Valida un token y devuelve el principal; actualiza last_used_at."""
        prefix = _parse_prefix(token)
        if prefix is None:
            raise PatInvalidError("Malformed access token")

        rows = (
            await self.session.execute(
                select(HubPersonalAccessToken).where(
                    HubPersonalAccessToken.token_prefix == prefix
                )
            )
        ).scalars().all()

        token_hash = _hash_token(token)
        pat = next(
            (r for r in rows if hmac.compare_digest(r.token_hash, token_hash)),
            None,
        )
        if pat is None:
            raise PatInvalidError("Unknown access token")
        if pat.revoked_at is not None:
            raise PatInvalidError("Access token has been revoked")
        if pat.expires_at is not None and pat.expires_at <= datetime.now(timezone.utc):
            raise PatInvalidError("Access token has expired")

        # Capturar los valores ANTES del commit: expire_on_commit los invalidaría y un
        # acceso posterior dispararía un lazy-load síncrono (MissingGreenlet).
        # SEC.2: el PAT **hereda** las organizaciones de su dueño y no las lleva guardadas.
        # Guardarlas en la fila las congelaría: a un admin al que se le retira una
        # organización le seguiría valiendo un token emitido antes, que es una revocación
        # que no revoca. Resolverlas aquí cuesta una consulta por validación y siempre dice
        # la verdad de hoy.
        # MT.5 — y si el token declara una organización, **acota** ese alcance. Nunca amplía:
        # la intersección la hace `acota_a_la_organizacion`, así que un token cuya organización
        # ya no gestiona su dueño se queda sin ninguna, que es lo que tiene que pasar.
        from server.app.core.auth.pat.principal import acota_a_la_organizacion

        dueno = UserInfo(
            user_id=pat.owner_id,
            email=pat.owner_email,
            role=pat.owner_role,
            organizacion_ids=await self._orgs_del_dueno(pat.owner_role, pat.owner_id),
        )
        principal = PatPrincipal(
            user_info=acota_a_la_organizacion(dueno, pat),
            scopes=list(pat.scopes),
        )
        pat.last_used_at = datetime.now(timezone.utc)
        await self.session.commit()
        return principal

    async def _orgs_del_dueno(self, owner_role: str, owner_id: str) -> tuple[str, ...]:
        """Organizaciones del dueño del PAT. Vacío en superadmin: ahí es el comodín.

        **Dos formas de dueño, y sólo se miraba una** (defecto encontrado en VAS.2 con un `curl`
        real). Esto resolvía únicamente por `HubOrganizacion.partner_id == owner_id`, que es el
        modelo de *partner*: una cuenta de partner **posee** organizaciones y `partner_id` es su
        código. Pero desde ROL/IDE la identidad de administración es un **`HubUser` con
        `role='admin'`**, y un `HubUser` no posee organizaciones: **pertenece** a una, por su
        columna `organizacion_id`. Así que la consulta comparaba un uuid de usuario con un código
        de partner —`60082aa4-…` contra `uji`— y no encajaba nunca.

        Y para un rol que no es superadmin, la tupla vacía significa «ninguna organización» (I5),
        con lo que el PAT no veía nada de la suya y `organizacion_unica_de` daba `None`: **`POST
        /api/v1/actividad` respondía 403 a todo integrador real** desde REG.2. Ninguno de sus
        tests lo veía porque todos sobreescriben `get_current_user` con un principal ya poblado.

        Se prueba primero la identidad de usuario, que es la de hoy, y se cae al partner, que
        sigue siendo un dueño legítimo. Un `HubUser` sin organización cae también al partner y
        acaba devolviendo la tupla vacía, que en un rol no privilegiado es «ninguna» — la
        respuesta correcta para un usuario que no pertenece a ninguna.
        """
        from sqlalchemy import select as sa_select

        from server.app.modules.agents_hub.database.config_models import (
            HubOrganizacion,
            HubUser,
        )

        if owner_role == "superadmin":
            return ()

        # `owner_id` puede no ser un uuid —un partner lo tiene como código—, así que la consulta
        # por usuario se intenta sólo cuando la forma encaja: pasarle `'uji'` a una columna UUID
        # revienta la sentencia en vez de no encontrar nada.
        try:
            como_uuid = uuid.UUID(str(owner_id))
        except (ValueError, AttributeError, TypeError):
            como_uuid = None

        if como_uuid is not None:
            del_usuario = await self.session.execute(
                sa_select(HubUser.organizacion_id).where(HubUser.id == como_uuid)
            )
            propia = del_usuario.scalars().first()
            if propia:
                return (str(propia),)

        filas = await self.session.execute(
            sa_select(HubOrganizacion.id).where(HubOrganizacion.partner_id == owner_id)
        )
        return tuple(str(fila) for fila in filas.scalars().all())

    async def list_for(self, owner: UserInfo) -> list[HubPersonalAccessToken]:
        """Lista los PAT del owner (metadatos; nunca el plano ni el hash)."""
        return list(
            (
                await self.session.execute(
                    select(HubPersonalAccessToken)
                    .where(HubPersonalAccessToken.owner_id == owner.user_id)
                    .order_by(HubPersonalAccessToken.created_at.desc())
                )
            ).scalars().all()
        )

    async def revoke(self, owner: UserInfo, pat_id) -> None:
        """Revoca un PAT del owner. Lanza ``PatInvalidError`` si no es suyo."""
        pat = (
            await self.session.execute(
                select(HubPersonalAccessToken).where(
                    HubPersonalAccessToken.id == pat_id,
                    HubPersonalAccessToken.owner_id == owner.user_id,
                )
            )
        ).scalars().first()
        if pat is None:
            raise PatInvalidError("Access token not found")
        if pat.revoked_at is None:
            pat.revoked_at = datetime.now(timezone.utc)
            await self.session.commit()
