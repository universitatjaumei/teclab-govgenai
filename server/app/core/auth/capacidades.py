"""Lo que una sesión puede hacer, calculado aquí para que el panel no lo deduzca del rol (#277).

Cinco pantallas leían el rol del JWT en el cliente y decidían con él: qué niveles de identidad
visual ofrecer, si se puede publicar una plantilla, si se ve la cola de revisión de scripts, si
aparece la integración de asistentes. Es lo que la regla de AGENTS.md prohíbe —el frontend no
calcula permisos— y además se equivocaba de forma silenciosa: la cola de revisión mandaba a
`/hub` a quien no era administrador, una ruta que esa persona podía no tener.

Cada capacidad repite **la misma comprobación que hace su endpoint**, y el endpoint la sigue
haciendo: esto decide qué se enseña, no qué se permite. Van en `/auth/me`, junto a los módulos,
porque es el sitio que ya contesta «qué necesita saber esta sesión».
"""
from __future__ import annotations

from typing import Literal

from server.app.core.auth.models import UserInfo

Capacidad = Literal[
    # `POST /redaccion/llm-drafts/approve` y el constructor de plantillas: admin o superadmin.
    "plantillas.publicar",
    # La cola de propuestas de script (`GET /redaccion/scripts/pending`): admin o superadmin.
    "scripts.revisar",
    # El nivel de plataforma de la identidad visual: sólo superadmin.
    "identidad.plataforma",
    # El adaptador del asistente para la extensión (#215): sólo superadmin.
    "agentes.integrar_asistentes",
]


def capacidades_de(usuario: UserInfo) -> list[Capacidad]:
    capacidades: list[Capacidad] = []
    if usuario.is_superadmin or usuario.is_admin:
        capacidades.append("plantillas.publicar")
        capacidades.append("scripts.revisar")
    if usuario.is_superadmin:
        capacidades.append("identidad.plataforma")
        capacidades.append("agentes.integrar_asistentes")
    return capacidades
