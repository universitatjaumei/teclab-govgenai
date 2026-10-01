"""Issue #194 — varios ficheros de entrada, cada uno con su ruta real.

Hasta aquí el protocolo materializaba **uno**: los demás slots viajaban en
`options["ficheros"]` como referencias de almacenamiento, que dentro de este contenedor no son
rutas de nada. O sea que declarar tres slots era declarar uno y medio, y el guion se enteraba con
un error de pandas.
"""
from __future__ import annotations

import base64


def _payload(code: str, **overrides) -> dict:
    base = {
        "code": code,
        "file_path": "",
        "raw_text": "",
        "options": {},
        "timeout_seconds": 30,
    }
    base.update(overrides)
    return base


def _fichero(nombre: str, contenido: bytes) -> dict:
    return {"nombre": nombre, "contenido_b64": base64.b64encode(contenido).decode("ascii")}


#: Lee los dos ficheros por la ruta que el sandbox le pone en `options["ficheros"]`.
_LEE_LOS_DOS = (
    "import pandas\n"
    "rutas = options['ficheros']\n"
    "a = pandas.read_csv(rutas['presupuesto'])\n"
    "b = pandas.read_csv(rutas['clasificacion'])\n"
    "result = {'metrics': ["
    "  {'name': 'filas_a', 'value': len(a)},"
    "  {'name': 'filas_b', 'value': len(b)}]}\n"
)


def test_el_guion_lee_los_dos_ficheros_por_su_ruta(client) -> None:
    resp = client.post(
        "/execute-extraction",
        json=_payload(
            _LEE_LOS_DOS,
            ficheros_b64={
                "presupuesto": _fichero("p.csv", b"a\n1\n2\n3\n"),
                "clasificacion": _fichero("c.csv", b"b\n9\n"),
            },
        ),
    )

    assert resp.status_code == 200, resp.text
    metricas = {m["name"]: m["value"] for m in resp.json()["result"]["metrics"]}
    assert metricas == {"filas_a": 3, "filas_b": 1}


def test_dos_slots_con_el_mismo_nombre_de_fichero_no_se_pisan(client) -> None:
    """Cada slot va a su carpeta. Sin eso, uno sobreescribe al otro y nada avisa."""
    resp = client.post(
        "/execute-extraction",
        json=_payload(
            _LEE_LOS_DOS,
            ficheros_b64={
                "presupuesto": _fichero("datos.csv", b"a\n1\n2\n"),
                "clasificacion": _fichero("datos.csv", b"b\n7\n8\n9\n"),
            },
        ),
    )

    assert resp.status_code == 200, resp.text
    metricas = {m["name"]: m["value"] for m in resp.json()["result"]["metrics"]}
    assert metricas == {"filas_a": 2, "filas_b": 3}


def test_el_principal_tambien_esta_en_options_por_su_slot(client) -> None:
    """El principal llega una sola vez, como `file_bytes`, y `file_slot` dice de qué slot es.

    El guion puede leerlo por `file_path`, como siempre, o por `options["ficheros"]`, como los
    demás: las dos rutas son el mismo fichero, escrito una vez.
    """
    resp = client.post(
        "/execute-extraction",
        json=_payload(
            _LEE_LOS_DOS + "assert rutas['presupuesto'] == file_path\n",
            file_bytes_b64=base64.b64encode(b"a\n1\n2\n3\n").decode("ascii"),
            file_name="p.csv",
            file_slot="presupuesto",
            ficheros_b64={"clasificacion": _fichero("c.csv", b"b\n9\n")},
        ),
    )

    assert resp.status_code == 200, resp.text
    metricas = {m["name"]: m["value"] for m in resp.json()["result"]["metrics"]}
    assert metricas == {"filas_a": 3, "filas_b": 1}


class TestUnNombreNoSaleDeSuCarpeta:
    """El nombre del fichero llega en la petición, así que el sandbox no se fía de él.

    `Path(nombre).name` quita los directorios —`../../etc/x` se queda en `x`— **pero no todo**:
    `Path("..").name` es `".."`, y `carpeta / ".."` es la carpeta de arriba. Hoy fallaría al
    escribir sobre un directorio, sin salir del temporal; eso es suerte, no diseño. Lo señaló
    CodeQL en la PR #210.
    """

    def test_dos_puntos_como_nombre_se_rechaza(self, client) -> None:
        resp = client.post(
            "/execute-extraction",
            json=_payload(
                "result = {}",
                ficheros_b64={"presupuesto": _fichero("..", b"x")},
            ),
        )

        assert resp.status_code == 422, resp.text
        assert resp.json() == {"code": "FILE_NAME_INVALID", "slot": "presupuesto"}

    def test_y_tambien_en_el_fichero_principal(self, client) -> None:
        resp = client.post(
            "/execute-extraction",
            json=_payload(
                "result = {}",
                file_bytes_b64=base64.b64encode(b"x").decode("ascii"),
                file_name="..",
            ),
        )

        assert resp.status_code == 422, resp.text
        assert resp.json()["code"] == "FILE_NAME_INVALID"

    def test_un_nombre_con_directorios_se_queda_en_su_carpeta(self, client) -> None:
        """Sin esto, lo de arriba se cumpliría rechazando cualquier nombre con una barra."""
        resp = client.post(
            "/execute-extraction",
            json=_payload(
                # Sin `os`: el auditor no lo permite dentro del guion.
                "partes = options['ficheros']['presupuesto'].replace(chr(92), '/').split('/')\n"
                "result = {'metrics': [{'name': 'nombre', 'value': partes[-1]},"
                " {'name': 'carpeta', 'value': partes[-2]}]}\n",
                ficheros_b64={"presupuesto": _fichero("../../etc/p.csv", b"a\n1\n")},
            ),
        )

        assert resp.status_code == 200, resp.text
        metricas = {m["name"]: m["value"] for m in resp.json()["result"]["metrics"]}
        assert metricas["nombre"] == "p.csv"
        # La carpeta lleva el slot delante, para que se lea, y una huella detrás, para que dos
        # slots que se limpian igual no la compartan.
        assert metricas["carpeta"].startswith("presupuesto-")


def test_dos_slots_que_se_limpian_igual_no_comparten_carpeta(client) -> None:
    """Quitar caracteres no es inyectivo: `a/b` y `ab` daban la misma carpeta (PR #210).

    Con ficheros del mismo nombre, el segundo pisaba al primero y **los dos slots apuntaban al
    mismo contenido**, sin que nada lo dijera.
    """
    codigo = (
        "import pandas\n"
        "rutas = options['ficheros']\n"
        "a = pandas.read_csv(rutas['a/b'])\n"
        "b = pandas.read_csv(rutas['ab'])\n"
        "result = {'metrics': ["
        "  {'name': 'filas_a', 'value': len(a)},"
        "  {'name': 'filas_b', 'value': len(b)}]}\n"
    )
    resp = client.post(
        "/execute-extraction",
        json=_payload(
            codigo,
            ficheros_b64={
                "a/b": _fichero("datos.csv", b"x\n1\n2\n"),
                "ab": _fichero("datos.csv", b"x\n1\n2\n3\n4\n"),
            },
        ),
    )

    assert resp.status_code == 200, resp.text
    metricas = {m["name"]: m["value"] for m in resp.json()["result"]["metrics"]}
    assert metricas == {"filas_a": 2, "filas_b": 4}


def test_un_contenido_que_no_es_base64_se_dice_con_el_slot(client) -> None:
    """Y con el slot dentro: «FILE_NOT_BASE64» a secas no dice cuál de los tres."""
    resp = client.post(
        "/execute-extraction",
        json=_payload(
            "result = {}",
            ficheros_b64={"presupuesto": {"nombre": "p.csv", "contenido_b64": "no-es-base64!!"}},
        ),
    )

    assert resp.status_code == 422
    cuerpo = resp.json()
    assert cuerpo["code"] == "FILE_NOT_BASE64"
    assert cuerpo["slot"] == "presupuesto"
