"""Dar de alta un apartado, con su filtro y su cortesía (RAS.5).

El spider lee de `config_json` la profundidad, el filtro de URL, el tope de páginas, el presupuesto
de tiempo y la cortesía. **Nada de eso se podía fijar al crear ni al modificar un sitio**: ni
`SiteCreate` ni `SitePatch` tenían el campo, así que un sitio dado de alta desde la interfaz
rastreaba con los valores por defecto y **sin filtro de URL**.

Eso no es un detalle de configuración: la decisión operativa del bloque es **un sitio por apartado**
—cada apartado tiene un responsable distinto en la casa y un informe del portal completo no lo lee
nadie—, y esa decisión se expresa exactamente con `url_regex_filter`. Sin el campo, la forma de
usarlo que tiene sentido era inalcanzable.

El filtro se valida al guardar: una expresión regular que no compila rompería **todos** los rastreos
del sitio, y el fallo saldría lejos del formulario donde se escribió.
"""
from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.app.api.deps import get_current_user
from server.app.core.auth.models import UserInfo
from server.app.api.deps import get_session
from server.app.routers.hub_sites_router import router as sites_router

_ORG = uuid.uuid4()
_APARTADO = {
    "crawl_depth": 3,
    "url_regex_filter": r"/centres/escola-doctorat/",
    "max_pages": 500,
    "max_seconds": 1800,
    "delay_seconds": 2.0,
    "respect_robots": True,
    "max_concurrency": 1,
    "max_retries": 3,
}


class _SesionQueGuarda:
    """Recoge lo que se le añade, que es lo que este test tiene que mirar."""

    def __init__(self) -> None:
        self.anadidos: list[Any] = []
        self.commits = 0

    def add(self, obj: Any) -> None:
        # Lo que pondría la base al insertar: sin esto la respuesta no valida y el test hablaría
        # de `created_at` en vez de la configuración del rastreo, que es lo que mira.
        from datetime import datetime, timezone

        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        if getattr(obj, "created_at", None) is None:
            obj.created_at = datetime.now(timezone.utc)
        if getattr(obj, "spider_type", None) is None:
            obj.spider_type = "generic"
        if getattr(obj, "status", None) is None:
            obj.status = "active"
        self.anadidos.append(obj)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, obj: Any) -> None:
        return None

    async def get(self, modelo: Any, ident: Any) -> Any:
        return self.anadidos[-1] if self.anadidos else None

    async def execute(self, stmt: Any) -> Any:
        resultado = MagicMock()
        resultado.scalars.return_value.all.return_value = self.anadidos
        resultado.scalar_one_or_none.return_value = (
            self.anadidos[-1] if self.anadidos else None
        )
        return resultado


def _app(sesion: Any) -> FastAPI:
    async def _sesion():
        yield sesion

    async def _usuario():
        return UserInfo(
            user_id=str(uuid.uuid4()), email="admin@example.local", role="admin",
            organizacion_ids=(str(_ORG),),
        )

    app = FastAPI()
    app.include_router(sites_router, prefix="/api/v1")
    app.dependency_overrides[get_session] = _sesion
    app.dependency_overrides[get_current_user] = _usuario
    return app


def test_el_alta_acepta_la_configuracion_del_rastreo():
    sesion = _SesionQueGuarda()
    with TestClient(_app(sesion)) as client:
        respuesta = client.post(
            "/api/v1/hub/sites",
            params={"organizacion_id": str(_ORG)},
            json={
                "name": "Escola de Doctorat",
                "root_url": "https://www.uji.es/centres/escola-doctorat/",
                "crawl_config": _APARTADO,
            },
        )

    assert respuesta.status_code == 201, respuesta.text
    guardado = sesion.anadidos[-1]
    assert guardado.config_json["url_regex_filter"] == r"/centres/escola-doctorat/"
    assert guardado.config_json["delay_seconds"] == 2.0
    assert guardado.config_json["crawl_depth"] == 3


def test_el_alta_sin_configuracion_deja_la_cortesia_por_defecto():
    """Un sitio creado sin decir nada tiene que rastrear despacio, no a toda velocidad."""
    sesion = _SesionQueGuarda()
    with TestClient(_app(sesion)) as client:
        respuesta = client.post(
            "/api/v1/hub/sites",
            params={"organizacion_id": str(_ORG)},
            json={"name": "Sitio", "root_url": "https://www.uji.es/algo/"},
        )

    assert respuesta.status_code == 201, respuesta.text
    guardado = sesion.anadidos[-1]
    assert guardado.config_json.get("delay_seconds", 1.0) >= 1.0
    assert guardado.config_json.get("respect_robots", True) is True


def test_un_filtro_que_no_compila_se_rechaza_al_guardarlo():
    """Si no, rompe todos los rastreos del sitio y el fallo sale lejos del formulario."""
    sesion = _SesionQueGuarda()
    with TestClient(_app(sesion)) as client:
        respuesta = client.post(
            "/api/v1/hub/sites",
            params={"organizacion_id": str(_ORG)},
            json={
                "name": "Mal filtro",
                "root_url": "https://www.uji.es/x/",
                "crawl_config": {"url_regex_filter": "/centres/[escola"},
            },
        )

    assert respuesta.status_code == 422, respuesta.text
    assert "regular" in respuesta.text.lower() or "regex" in respuesta.text.lower()


def test_una_pausa_negativa_se_rechaza():
    sesion = _SesionQueGuarda()
    with TestClient(_app(sesion)) as client:
        respuesta = client.post(
            "/api/v1/hub/sites",
            params={"organizacion_id": str(_ORG)},
            json={
                "name": "Pausa imposible",
                "root_url": "https://www.uji.es/x/",
                "crawl_config": {"delay_seconds": -1},
            },
        )

    assert respuesta.status_code == 422, respuesta.text


def test_el_sitio_devuelve_su_configuracion_para_poder_revisarla():
    """Quien mira la lista tiene que poder ver con qué cortesía se está rastreando."""
    sesion = _SesionQueGuarda()
    with TestClient(_app(sesion)) as client:
        creado = client.post(
            "/api/v1/hub/sites",
            params={"organizacion_id": str(_ORG)},
            json={
                "name": "Escola de Doctorat",
                "root_url": "https://www.uji.es/centres/escola-doctorat/",
                "crawl_config": _APARTADO,
            },
        ).json()

    assert creado["crawl_config"]["url_regex_filter"] == r"/centres/escola-doctorat/"


@pytest.mark.parametrize("campo,valor", [
    ("crawl_depth", 3),
    ("max_pages", 500),
    ("delay_seconds", 5.0),
])
def test_la_configuracion_se_puede_cambiar_despues(campo: str, valor: Any):
    sesion = _SesionQueGuarda()
    app = _app(sesion)
    with TestClient(app) as client:
        client.post(
            "/api/v1/hub/sites",
            params={"organizacion_id": str(_ORG)},
            json={"name": "S", "root_url": "https://www.uji.es/x/",
                  "crawl_config": _APARTADO},
        )
        sitio = sesion.anadidos[-1]
        sitio.organizacion_id = _ORG
        respuesta = client.patch(
            f"/api/v1/hub/sites/{sitio.id}",
            json={"crawl_config": {**_APARTADO, campo: valor}},
        )

    assert respuesta.status_code == 200, respuesta.text
    assert sesion.anadidos[-1].config_json[campo] == valor
