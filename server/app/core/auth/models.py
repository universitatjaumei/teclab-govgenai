"""Modelos de autenticación y usuario."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class UserRole(str, Enum):
    """Roles de usuario disponibles.

    - SUPERADMIN: gestiona la plataforma global (proveedores LLM, admins, config sistema).
    - ADMIN: crea y configura chatbots/agentes para sus organizaciones.
    - INFORMER: supervisa y valida respuestas de la IA.
    - USER: usuario final del chatbot/agente.
    """

    USER = "user"
    SUPERADMIN = "superadmin"
    ADMIN = "admin"
    INFORMER = "informer"


def _validate_role(role: str) -> str:
    valid_roles = {r.value for r in UserRole}
    if role not in valid_roles:
        raise ValueError(
            f"Invalid role '{role}'. Must be one of: {', '.join(sorted(valid_roles))}"
        )
    return role


@dataclass(frozen=True)
class UserInfo:
    """Información del usuario autenticado, extraída del JWT.

    Inmutable (frozen) para garantizar que no se modifique durante el request.
    """

    user_id: str
    email: str
    role: str = field(default="user")
    # SEC.2 (hallazgo A2): organizaciones a las que este principal tiene acceso.
    #
    # **Vacío significa cosas opuestas según el rol, y es deliberado**: en un superadmin es
    # el comodín «todas»; en cualquier otro es «ninguna». Si «vacío = todas» valiera para
    # todos, un admin al que se le olvidara poblar el claim volvería a verlo todo, que es
    # exactamente el agujero que este claim viene a cerrar. Lo fija un test.
    #
    # **Tupla y no lista**, al contrario de lo que decía el plan: este dataclass es `frozen`
    # justamente para que nadie amplíe los permisos a mitad de una petición, y una lista
    # dejaría esa puerta abierta con `principal.organizacion_ids.append(...)`.
    organizacion_ids: tuple[str, ...] = field(default=())
    # SEC.2.1: grupos que el IdP declara para esta persona. Los consume el modo de acceso
    # `restricted` de `assert_chatbot_access`. Vacío en el login local, que no tiene grupos:
    # ahí la autorización fina se expresa con `allowed_roles`.
    saml_groups: tuple[str, ...] = field(default=())
    #: Si esta sesión arrastra una contraseña que puso otra persona y está pendiente de cambio
    #: (issue #94). Mientras sea cierto, el token **no sirve para nada más que cambiarla**: es lo
    #: que acota a un solo uso el conocimiento de quien la restableció.
    #:
    #: Un token emitido antes de esto no trae el claim y se lee como `False` — quedarse fuera por
    #: no traerlo sería echar de la aplicación a quien no ha hecho nada.
    cambio_pendiente: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "role", _validate_role(self.role))
        object.__setattr__(
            self, "organizacion_ids", tuple(str(o) for o in self.organizacion_ids)
        )
        object.__setattr__(self, "saml_groups", tuple(str(g) for g in self.saml_groups))

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "email": self.email,
            "role": self.role,
            "organizacion_ids": list(self.organizacion_ids),
            "saml_groups": list(self.saml_groups),
            # Issue #94 — para que el panel sepa qué pintar al recargar la página: el token
            # sigue en el navegador y la marca viaja dentro, pero el cliente no lo abre.
            "cambio_pendiente": self.cambio_pendiente,
        }

    @property
    def is_superadmin(self) -> bool:
        return self.role == UserRole.SUPERADMIN.value

    @property
    def is_admin(self) -> bool:
        return self.role == UserRole.ADMIN.value

    @property
    def is_informer(self) -> bool:
        return self.role == UserRole.INFORMER.value
