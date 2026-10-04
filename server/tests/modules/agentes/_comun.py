"""Lo que comparten las pruebas HTTP de los agentes: las personas, la autora y cómo se publica.

La fixture `http` vive en el `conftest.py` del directorio y usa esto; los ficheros de prueba lo
importan para publicar y para cambiar de persona entre llamadas.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta

from server.app.core.auth.models import UserInfo

ORG = str(uuid.uuid4())


def persona(role: str = "user", orgs: tuple[str, ...] = (ORG,), grupos: tuple[str, ...] = ()) -> UserInfo:
    return UserInfo(
        user_id=str(uuid.uuid4()),
        email=f"{role}@uji.es",
        role=role,
        organizacion_ids=tuple(orgs),
        saml_groups=tuple(grupos),
    )


#: Quien publica en las pruebas, salvo que se cambie.
AUTORA = persona()


class Quien:
    """Quién hace la petición. Se cambia entre llamadas, como cambiaría la sesión."""

    def __init__(self) -> None:
        self.actual = AUTORA


def declaracion(**cambios) -> dict:
    cuerpo = {
        "nombre": "Contratación menor",
        "unidad": "Servicio de Contratación",
        "prompt": "Eres el asistente de contratación.",
        "carpeta_url": "https://drive.google.com/drive/folders/abc",
        "finalidad": "Orientar",
        "responsable": "Jefatura",
        "colectivo": "organizacion",
        "grupos": [],
        "revision_prevista_en": (date.today() + timedelta(days=180)).isoformat(),
    }
    cuerpo.update(cambios)
    return cuerpo


async def publicar(c, **cambios) -> dict:
    r = await c.post("/api/v1/agentes", json=declaracion(**cambios))
    assert r.status_code == 201, r.text
    return r.json()


FICHAS = [
    {"url": "https://drive.google.com/file/d/1", "titulo": "Instrucción de contrato menor", "resumen": "Trata del contrato menor."},
    {"url": "https://drive.google.com/file/d/2", "titulo": "Guía de viajes", "resumen": "Trata de viajes.", "vigente": False},
]
