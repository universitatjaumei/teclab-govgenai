"""AUT.10 (issue #120) — las dos funciones del presupuesto propio, en el sandbox de verdad.

Gemela de `server/tests/modules/redaccion/test_aut10_el_presupuesto_propio.py`. Aquélla corre por
el modo local de la plataforma, con **pandas 2**; ésta, por `/execute-extraction`, con **pandas 3**,
el auditor de la última barrera y el envoltorio real. Un guion que funcionara con una versión y no
con la otra pasaría en una y fallaría en la otra, y la que importa al desplegar es ésta.
"""
from __future__ import annotations

import base64
import importlib.util
import io
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
EJEMPLO = RAIZ / "docs" / "ejemplos" / "funciones" / "presupuesto"


def _datos():
    spec = importlib.util.spec_from_file_location(
        "_aut10_datos_sandbox", EJEMPLO / "datos_sinteticos.py"
    )
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modulo
    spec.loader.exec_module(modulo)
    return modulo


DATOS = _datos()
CONTRATOS = json.loads((EJEMPLO / "contratos.json").read_text(encoding="utf-8"))


def _guion(clave: str) -> str:
    return (EJEMPLO / CONTRATOS[clave]["guion"]).read_text(encoding="utf-8")


def _fichero(nombre: str, contenido: bytes) -> dict:
    return {"nombre": nombre, "contenido_b64": base64.b64encode(contenido).decode("ascii")}


def _ejecutar(client, clave: str, ficheros: dict, options: dict | None = None) -> dict:
    artefactos = CONTRATOS[clave]["contrato"]["artefactos"]
    resp = client.post(
        "/execute-extraction",
        json={
            "code": _guion(clave),
            "options": options or {},
            "timeout_seconds": 120,
            "ficheros_b64": ficheros,
            "artefactos_maximo": artefactos["maximo"],
            "artefactos_maximo_bytes": artefactos["maximo_bytes"],
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _artefacto(cuerpo: dict, nombre: str) -> bytes:
    a = next(a for a in cuerpo["artefactos"] if a["nombre"] == nombre)
    return base64.b64decode(a["contenido_b64"])


def test_anonimizar_no_deja_ninguna_persona(client) -> None:
    cuerpo = _ejecutar(
        client,
        "anonimizar_presupuesto",
        {
            "presupuesto": _fichero("presupuesto.csv", DATOS.presupuesto()),
            "pdi": _fichero("pdi.txt", DATOS.pdi()),
        },
    )

    salida = _artefacto(cuerpo, "presupuesto_anonimizado.csv").decode("utf-8-sig")
    for persona in DATOS.PERSONAS:
        assert persona not in salida, f"«{persona}» sigue en el CSV anonimizado"
    for intacto in DATOS.NO_PERSONAS:
        assert intacto in salida, f"«{intacto}» no es una persona y ha desaparecido"


def test_el_documento_sale_sobre_lo_anonimizado(client) -> None:
    from docx import Document

    primera = _ejecutar(
        client,
        "anonimizar_presupuesto",
        {
            "presupuesto": _fichero("presupuesto.csv", DATOS.presupuesto()),
            "pdi": _fichero("pdi.txt", DATOS.pdi()),
        },
    )
    anonimizado = _artefacto(primera, "presupuesto_anonimizado.csv")

    segunda = _ejecutar(
        client,
        "documento_presupuesto",
        {
            "presupuesto": _fichero("presupuesto_anonimizado.csv", anonimizado),
            "clasificacion": _fichero("clasificacion.csv", DATOS.clasificacion()),
            "prosa": _fichero("prosa.md", DATOS.prosa()),
        },
        options={"titulo": "Pressupost sintètic 2026"},
    )

    assert {a["nombre"] for a in segunda["artefactos"]} == {
        "pressupost_net.csv",
        "pressupost_uji.docx",
    }
    metricas = {m["name"]: m["value"] for m in segunda["result"]["metrics"]}
    assert abs(metricas["total_gastos"] - DATOS.total_gastos_del_ultimo_ejercicio()) < 0.01

    word = Document(io.BytesIO(_artefacto(segunda, "pressupost_uji.docx")))
    texto = "\n".join(p.text for p in word.paragraphs)
    assert "Pressupost sintètic 2026" in texto
    assert "{{VAL:" not in texto
    assert "‹?" not in texto
