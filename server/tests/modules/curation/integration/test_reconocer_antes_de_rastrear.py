"""Reconocer un apartado desde la pantalla, antes de darlo de alta (CUR.6).

El endpoint no toca la base: no hay sitio todavía. Eso es el punto — la pregunta «¿cuántas páginas
tiene esto?» se hace **antes** de comprometerse, y hasta ahora la única forma de responderla era
lanzar el rastreo de verdad y esperar.
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.app.api.deps import get_current_user
from server.app.core.auth.models import UserInfo
from server.app.modules.curation.reconocimiento import (
    ApartadoDelSitio,
    InformeDeReconocimiento,
)
from server.app.routers.hub_sites_router import get_servicio_de_reconocimiento
from server.app.routers.hub_sites_router import router as sites_router

_RAIZ = "https://www.uji.es/centres/escola-doctorat/"

_INFORME = InformeDeReconocimiento(
    root_url=_RAIZ,
    urls_encontradas=349,
    paginas_sondeadas=60,
    truncado=True,
    motivo_de_parada="max_pages",
    apartados=[
        ApartadoDelSitio(apartado="base", urls=300, ejemplos=[f"{_RAIZ}base/doctorands/"]),
        ApartadoDelSitio(apartado="info-general", urls=48, ejemplos=[f"{_RAIZ}info-general/"]),
        ApartadoDelSitio(apartado="/", urls=1, ejemplos=[_RAIZ]),
    ],
    segundos_por_pagina=2.4,
    segundos_estimados=837.6,
    urls=[_RAIZ, f"{_RAIZ}base/doctorands/"],
)


class _ServicioFalso:
    def __init__(self, informe: Any = _INFORME) -> None:
        self.llamadas: list[dict] = []
        self._informe = informe

    async def reconocer(self, root_url: str, **opciones: Any) -> Any:
        self.llamadas.append({"root_url": root_url, **opciones})
        if isinstance(self._informe, Exception):
            raise self._informe
        return self._informe


def _app(servicio: Any) -> FastAPI:
    async def _usuario():
        return UserInfo(
            user_id=str(uuid.uuid4()), email="admin@example.local", role="admin",
            organizacion_ids=(str(uuid.uuid4()),),
        )

    app = FastAPI()
    app.include_router(sites_router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = _usuario
    app.dependency_overrides[get_servicio_de_reconocimiento] = lambda: servicio
    return app


def test_el_reconocimiento_devuelve_el_recuento_por_apartado_y_el_total():
    servicio = _ServicioFalso()
    with TestClient(_app(servicio)) as client:
        respuesta = client.post("/api/v1/hub/site-reconnaissance", json={"root_url": _RAIZ})

    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["urls_encontradas"] == 349
    assert cuerpo["apartados"][0] == {
        "apartado": "base",
        "urls": 300,
        "ejemplos": [f"{_RAIZ}base/doctorands/"],
    }


def test_dice_cuanto_tardaria_el_rastreo_completo():
    """Es el dato que responde «de golpe o por subapartados»."""
    with TestClient(_app(_ServicioFalso())) as client:
        cuerpo = client.post("/api/v1/hub/site-reconnaissance", json={"root_url": _RAIZ}).json()

    assert cuerpo["segundos_estimados"] == 837.6
    assert cuerpo["segundos_por_pagina"] == 2.4


def test_dice_que_el_sondeo_se_quedo_corto_en_vez_de_dar_el_tope_por_respuesta():
    with TestClient(_app(_ServicioFalso())) as client:
        cuerpo = client.post("/api/v1/hub/site-reconnaissance", json={"root_url": _RAIZ}).json()

    assert cuerpo["truncado"] is True
    assert cuerpo["motivo_de_parada"] == "max_pages"


def test_el_csv_se_sirve_como_fichero_con_una_fila_por_url():
    """«Lo que se puede compartir con quien decide» tiene que bajar como fichero, no como JSON."""
    with TestClient(_app(_ServicioFalso())) as client:
        respuesta = client.post(
            "/api/v1/hub/site-reconnaissance", json={"root_url": _RAIZ, "formato": "csv"}
        )

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.headers["content-type"].startswith("text/csv")
    assert "attachment" in respuesta.headers.get("content-disposition", "")
    assert respuesta.text.splitlines()[0] == "apartado,url"


def test_la_cortesia_del_rastreo_llega_al_calculo():
    """La pausa que se va a usar de verdad es la que decide si son minutos u horas."""
    servicio = _ServicioFalso()
    with TestClient(_app(servicio)) as client:
        client.post(
            "/api/v1/hub/site-reconnaissance",
            json={"root_url": _RAIZ, "delay_seconds": 2.0, "url_regex_filter": "escola-doctorat"},
        )

    assert servicio.llamadas[0]["pausa_del_rastreo"] == 2.0
    assert servicio.llamadas[0]["url_regex_filter"] == "escola-doctorat"


def test_una_url_que_no_es_una_url_se_rechaza_antes_de_pedir_nada():
    servicio = _ServicioFalso()
    with TestClient(_app(servicio)) as client:
        respuesta = client.post(
            "/api/v1/hub/site-reconnaissance", json={"root_url": "no-soy-una-url"}
        )

    assert respuesta.status_code == 422
    assert servicio.llamadas == []


def test_sin_el_modulo_de_curacion_no_se_hace_rastrear_al_servidor():
    """El reconocimiento hace que el servidor pida páginas: es la misma potestad que crear un sitio.

    Pedía rol de administrador; desde el 2026-10-07 la curación se concede por módulo, así que lo
    que se exige es `curacion`, sea cual sea el rol.
    """
    from server.app.api.deps import modulos_concedidos

    servicio = _ServicioFalso()
    app = _app(servicio)

    async def _sin_curacion():
        return ["informes"]

    app.dependency_overrides[modulos_concedidos] = _sin_curacion

    with TestClient(app) as client:
        respuesta = client.post("/api/v1/hub/site-reconnaissance", json={"root_url": _RAIZ})

    assert respuesta.status_code == 403
    assert servicio.llamadas == []
