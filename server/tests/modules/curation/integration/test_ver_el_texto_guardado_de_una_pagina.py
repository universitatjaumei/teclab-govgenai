"""Poder leer el texto guardado de una página rastreada (CUR.4).

El informe acusa y no deja comprobar. No hay **ninguna** pantalla que muestre el texto de una página
rastreada, y es lo que hace falta para dos cosas que el usuario pidió:

* juzgar si un hallazgo es cierto —«¿son ciertos los hallazgos?» era su primera prueba manual—;
* decidir si una página merece entrar en el corpus, que es la función del apartado de curación.

Y desde CUR.3 hay una tercera: comprobar que el recorte de plantilla **no se ha comido contenido**.
Lo que se sirve es el texto **guardado**, no la página original: es lo que iría al asistente, y es
justo lo que no se puede ver abriendo la URL en el navegador.
"""
from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.app.api.deps import get_current_user
from server.app.core.auth.models import UserInfo
from server.app.api.deps import get_session
from server.app.routers.hub_content_quality_router import get_findings_repo
from server.app.routers.hub_content_quality_router import router as calidad_router
from server.app.routers.hub_sites_router import router as sites_router

_ORG = uuid.uuid4()
_TEXTO = (
    "Alumnat de doctorat actual i futur\n"
    "Ets alumnat de doctorat o vols ser-ho?\n"
    "En aquest apartat trobaràs tota la informació que necessites."
)


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


def _sesion_con(pagina: Any, sitio: Any = None) -> Any:
    sitio = sitio or MagicMock(organizacion_id=_ORG)

    async def _get(modelo: Any, ident: Any):
        return pagina if getattr(modelo, "__name__", "") == "HubCrawledPage" else sitio

    sesion = AsyncMock()
    sesion.get = AsyncMock(side_effect=_get)
    return sesion


def _pagina(**campos: Any) -> Any:
    pagina = MagicMock()
    pagina.id = campos.get("id", uuid.uuid4())
    pagina.site_id = campos.get("site_id", uuid.uuid4())
    pagina.url = campos.get("url", "https://www.uji.es/centres/escola-doctorat/base/doctorands/")
    pagina.title = campos.get("title", "Alumnat de doctorat actual i futur")
    pagina.markdown_content = campos.get("markdown_content", _TEXTO)
    pagina.token_count = campos.get("token_count", 24)
    pagina.status = campos.get("status", "active")
    pagina.content_owner = campos.get("content_owner", "Escola de Doctorat")
    pagina.content_published_at = campos.get("content_published_at")
    pagina.render_signals = campos.get("render_signals", [])
    return pagina


def test_se_puede_leer_el_texto_guardado_de_una_pagina():
    pagina = _pagina()
    with TestClient(_app(_sesion_con(pagina))) as client:
        respuesta = client.get(f"/api/v1/hub/pages/{pagina.id}/content")

    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["content"] == _TEXTO
    assert cuerpo["url"].endswith("/doctorands/")
    assert cuerpo["title"] == "Alumnat de doctorat actual i futur"


def test_devuelve_lo_que_hace_falta_para_juzgar_el_hallazgo():
    """Quién mantiene la página y cuántos tokens tiene: el contexto del hallazgo."""
    pagina = _pagina(token_count=24)
    with TestClient(_app(_sesion_con(pagina))) as client:
        cuerpo = client.get(f"/api/v1/hub/pages/{pagina.id}/content").json()

    assert cuerpo["owner"] == "Escola de Doctorat"
    assert cuerpo["token_count"] == 24


def test_una_pagina_que_no_existe_responde_404():
    with TestClient(_app(_sesion_con(None))) as client:
        respuesta = client.get(f"/api/v1/hub/pages/{uuid.uuid4()}/content")

    assert respuesta.status_code == 404


def test_una_pagina_de_otra_organizacion_no_se_sirve():
    """El texto de una página es contenido del cliente: la guarda de organización va aquí también."""
    pagina = _pagina()
    sitio_de_otra_casa = MagicMock(organizacion_id=uuid.uuid4())

    with TestClient(_app(_sesion_con(pagina, sitio_de_otra_casa))) as client:
        respuesta = client.get(f"/api/v1/hub/pages/{pagina.id}/content")

    assert respuesta.status_code in (403, 404)


def test_una_pagina_sin_contenido_lo_dice_en_vez_de_devolver_nulo():
    """Una página en error no tiene texto, y eso hay que poder verlo sin adivinarlo."""
    pagina = _pagina(markdown_content=None, status="error")

    with TestClient(_app(_sesion_con(pagina))) as client:
        cuerpo = client.get(f"/api/v1/hub/pages/{pagina.id}/content").json()

    assert cuerpo["content"] == ""
    assert cuerpo["status"] == "error"


# ─────────────── Lo que la cola de hallazgos tiene que decir de cada fila ───────────────
#
# Verificado en el navegador con los 275 hallazgos reales del apartado: las URLs salían
# clickables, pero **ni un solo** botón de «ver el texto guardado» ni de desplegar la serie.
# La causa no estaba en la pantalla: el contrato de la cola no sirve `page_id` ni la señal, así
# que la pantalla no tiene con qué decidir. El fallo es del contrato, y por eso el test va aquí.


def _hallazgo(**campos: Any) -> Any:
    """Un hallazgo con **sólo** los atributos que el modelo real tiene.

    Aquí no vale un `MagicMock`: inventaría un `.signal` que la fila de la base de datos no
    tiene, y con eso el contrato pasaría el test leyendo un atributo inexistente en producción.
    Es la misma trampa que ya nos costó el `.score()` de Langfuse.
    """

    class _Fila:
        id = uuid.uuid4()
        status = "new"
        confidence = 1.0
        detected_at = "2026-08-19T10:00:00+00:00"
        reviewed_at = None
        site_id = campos.get("site_id", uuid.uuid4())
        finding_type = campos.get("finding_type", "stale")
        severity = campos.get("severity", "info")
        source_url = campos.get("source_url", "https://www.uji.es/x/")
        page_id = campos.get("page_id", uuid.uuid4())
        signal_json = campos.get("signal_json", {"date": "2021-11-18T00:00:00+00:00"})

    return _Fila()


def _app_de_hallazgos(hallazgos: list[Any]) -> FastAPI:
    async def _sesion():
        yield _sesion_con(None, MagicMock(organizacion_id=_ORG))

    async def _usuario():
        return UserInfo(
            user_id=str(uuid.uuid4()), email="admin@example.local", role="admin",
            organizacion_ids=(str(_ORG),),
        )

    repo = MagicMock()
    repo.list_by_site = AsyncMock(return_value=hallazgos)

    app = FastAPI()
    app.include_router(calidad_router, prefix="/api/v1")
    app.dependency_overrides[get_session] = _sesion
    app.dependency_overrides[get_current_user] = _usuario
    app.dependency_overrides[get_findings_repo] = lambda: repo
    return app


def test_cada_hallazgo_dice_de_que_pagina_habla():
    """Sin `page_id` no hay forma de abrir el texto guardado desde la fila del hallazgo."""
    hallazgo = _hallazgo()

    with TestClient(_app_de_hallazgos([hallazgo])) as client:
        cuerpo = client.get(f"/api/v1/hub/sites/{uuid.uuid4()}/findings").json()

    assert cuerpo[0]["page_id"] == str(hallazgo.page_id)


def test_un_hallazgo_de_grupo_trae_sus_versiones_con_sus_fechas():
    """La serie por años es un hallazgo con nueve URLs dentro; la señal es su contenido."""
    versiones = [
        {"url": "https://www.uji.es/x/2025/", "date": "2025-01-01T00:00:00+00:00"},
        {"url": "https://www.uji.es/x/2019/", "date": "2019-01-01T00:00:00+00:00"},
    ]
    hallazgo = _hallazgo(
        finding_type="version_series",
        page_id=None,
        signal_json={"count": 2, "versions": versiones},
    )

    with TestClient(_app_de_hallazgos([hallazgo])) as client:
        cuerpo = client.get(f"/api/v1/hub/sites/{uuid.uuid4()}/findings").json()

    assert cuerpo[0]["page_id"] is None
    assert cuerpo[0]["signal"]["versions"] == versiones


def test_la_senal_de_una_pagina_desactualizada_dice_su_fecha_y_de_donde_sale():
    """Es lo que hace revisable el hallazgo: la fecha y su procedencia, no un «está vieja»."""
    hallazgo = _hallazgo(
        signal_json={"date": "2021-11-18T00:00:00+00:00", "source": "page_date", "age_days": 1735},
    )

    with TestClient(_app_de_hallazgos([hallazgo])) as client:
        senal = client.get(f"/api/v1/hub/sites/{uuid.uuid4()}/findings").json()[0]["signal"]

    assert senal["source"] == "page_date"
    assert senal["age_days"] == 1735
