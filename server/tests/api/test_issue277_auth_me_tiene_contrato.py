"""#277 — `/auth/me` tiene modelo de respuesta, y las decisiones por rol las toma el servidor.

`GET /auth/me` declaraba `response_model=dict`, así que Orval generaba `{[key: string]: unknown}`
y el panel casteaba para leer `modulos` o `identity_role_authority`: un agujero en la raíz del
contrato. Y cinco pantallas decidían con el rol leído del JWT en el cliente —qué niveles de
identidad visual se ofrecen, si se puede publicar una plantilla, si se ve la cola de revisión de
scripts, si aparece la pestaña de integración de asistentes—, que es exactamente lo que la regla
de AGENTS.md prohíbe: el frontend no calcula permisos.

Ahora `/auth/me` declara `UsuarioActual` y trae `capacidades`, calculadas con las mismas
comprobaciones que hace cada endpoint.
"""
from __future__ import annotations

import pytest

from server.app.core.auth import UserInfo
from server.app.core.auth.capacidades import capacidades_de


def test_el_contrato_de_auth_me_no_es_un_diccionario_suelto() -> None:
    from server.app.main import app

    esquema = app.openapi()
    respuesta = esquema["paths"]["/api/v1/auth/me"]["get"]["responses"]["200"]
    referencia = respuesta["content"]["application/json"]["schema"]
    assert referencia == {"$ref": "#/components/schemas/UsuarioActual"}
    campos = esquema["components"]["schemas"]["UsuarioActual"]["properties"]
    for campo in ("modulos", "identity_role_authority", "capacidades", "role", "email"):
        assert campo in campos, campo


def test_las_capacidades_son_una_enumeracion_del_contrato() -> None:
    """Para que el panel compare con constantes generadas y no con cadenas escritas a mano."""
    from server.app.main import app

    esquema = app.openapi()
    capacidades = esquema["components"]["schemas"]["UsuarioActual"]["properties"]["capacidades"]
    assert "enum" in capacidades["items"] or "$ref" in capacidades["items"]


@pytest.mark.parametrize(
    ("rol", "esperadas"),
    [
        ("superadmin", {"plantillas.publicar", "scripts.revisar", "identidad.plataforma", "agentes.integrar_asistentes"}),
        ("admin", {"plantillas.publicar", "scripts.revisar"}),
        ("informer", set()),
        ("user", set()),
    ],
)
def test_las_capacidades_salen_del_rol_como_en_cada_endpoint(rol: str, esperadas: set[str]) -> None:
    usuario = UserInfo(user_id="u", email="u@uji.es", role=rol)
    assert set(capacidades_de(usuario)) == esperadas
