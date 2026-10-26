"""#273 — la ingesta del Hub es `edge`, y un router `cloud` no toca modelos operacionales.

`hub_ingestion_router` se etiquetaba `Deploy: cloud` y se registraba en `_register_cloud`, pero
todo lo que hace es manejar documentos, trabajos de ingesta y fragmentos, que son
`HubOperationalBase`: datos del cliente. Con `DEPLOY_MODE=edge` no había ingesta, y con `cloud`
el cloud tocaba datos del cliente. `DEPLOY_MODE` funcionaba; lo que estaba mal era la etiqueta.

El guardarraíl lo extiende a todos los routers `cloud`: ninguno importa modelos operacionales,
salvo la excepción que se declara abajo con su motivo.
"""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import FastAPI

from server.app import main
from server.tests.rutas import caminos

ROUTERS = Path(__file__).resolve().parents[4] / "app" / "routers"

#: Los routers `cloud` que aún leen datos operacionales, cada uno con su motivo. Una entrada
#: nueva aquí es una decisión, no un arreglo para poner el test en verde.
EXCEPCIONES = {
    "hub_chatbots_router.py": (
        "mezcla la configuración del chatbot con operaciones sobre su corpus —estadísticas, "
        "regenerar fragmentos, la comprobación de tamaño de MD_LONG_CONTEXT—; partirlo es la "
        "issue #298"
    ),
    "hub_organizaciones_router.py": (
        "borrar una organización purga su corpus, sus agentes, sus sitios y su léxico (#252); en "
        "un despliegue partido esa purga la tiene que hacer el edge — issue #298"
    ),
}


def _registradas(registrar) -> set[str]:
    app = FastAPI()
    registrar(app)
    return set(caminos(app))


def test_la_ingesta_se_registra_en_el_edge_y_no_en_el_cloud() -> None:
    edge, cloud = _registradas(main._register_edge), _registradas(main._register_cloud)
    assert any(p.startswith("/api/v1/hub/ingestion") for p in edge)
    assert not any(p.startswith("/api/v1/hub/ingestion") for p in cloud)


def test_la_etiqueta_dice_lo_mismo_que_el_registro() -> None:
    texto = (ROUTERS / "hub_ingestion_router.py").read_text(encoding="utf-8")
    assert "Deploy: edge" in texto
    assert "Deploy: cloud" not in texto


def _routers_cloud() -> dict[str, str]:
    routers = {}
    for fichero in ROUTERS.rglob("*.py"):
        texto = fichero.read_text(encoding="utf-8")
        if re.search(r"^Deploy:\s*cloud\b", texto, re.MULTILINE):
            routers[fichero.name] = texto
    return routers


def test_hay_routers_cloud_que_mirar() -> None:
    """Sanidad del medidor: si no encontrara ninguno, el test de abajo pasaría sin mirar."""
    assert len(_routers_cloud()) >= 10


def test_ningun_router_cloud_importa_modelos_operacionales() -> None:
    culpables = sorted(
        nombre for nombre, texto in _routers_cloud().items()
        if "operational_models" in texto and nombre not in EXCEPCIONES
    )
    assert not culpables, (
        f"routers cloud que importan modelos operacionales: {culpables}. Los datos del cliente "
        "—documentos, fragmentos, conversaciones— son edge."
    )


def test_cada_excepcion_sigue_haciendo_falta() -> None:
    """Una excepción que ya no hace falta se quita: si no, deja abierta la puerta que nombra."""
    routers = _routers_cloud()
    sobrantes = [n for n in EXCEPCIONES if n not in routers or "operational_models" not in routers[n]]
    assert not sobrantes, sobrantes
