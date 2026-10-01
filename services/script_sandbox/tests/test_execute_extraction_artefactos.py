"""AUT.7 (issue #117) — el guion escribe ficheros y el sandbox los devuelve.

**Dónde escribe.** El wrapper le da una variable `output_dir`, dentro del temporal de la
ejecución, que se borra al terminar. No hay otra: el auditor deniega `open`, así que un guion no
escribe a mano — escribe a través de una librería (`df.to_excel(...)`, `doc.save(...)`), que es
justo la forma en que se sabe qué produjo.

**Y los topes los manda el caller**, porque los declara el contrato de la función. El sandbox no
inventa un número: si no le dicen que se esperan artefactos, no devuelve ninguno.

**Pasarse del tope falla en alto y no recorta.** Devolver tres de los cinco ficheros que el guion
escribió sería entregar un resultado parcial con aspecto de completo, y quien lo recibe no tiene
forma de notarlo. El error dice los dos números.
"""
from __future__ import annotations

import base64
import hashlib


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


#: Escribe un CSV con pandas, que es como un guion real produce un fichero: por librería, no con
#: `open`, que el auditor deniega.
_ESCRIBE_UN_CSV = (
    "import pandas\n"
    "df = pandas.DataFrame({'a': [1, 2]})\n"
    "df.to_csv(output_dir + '/salida.csv', index=False)\n"
    "result = {'metrics': [{'name': 'filas', 'value': 2}]}\n"
)


class TestElGuionPuedeEscribir:

    def test_devuelve_el_fichero_con_su_nombre_y_su_hash(self, client) -> None:
        resp = client.post(
            "/execute-extraction",
            json=_payload(_ESCRIBE_UN_CSV, artefactos_maximo=2, artefactos_maximo_bytes=100_000),
        )

        assert resp.status_code == 200, resp.text
        artefactos = resp.json()["artefactos"]
        assert len(artefactos) == 1
        assert artefactos[0]["nombre"] == "salida.csv"
        contenido = base64.b64decode(artefactos[0]["contenido_b64"])
        assert artefactos[0]["sha256"] == hashlib.sha256(contenido).hexdigest()
        assert artefactos[0]["bytes"] == len(contenido)
        assert b"a\n1\n2" in contenido.replace(b"\r\n", b"\n")

    def test_y_las_cifras_siguen_llegando(self, client) -> None:
        """Producir un fichero no sustituye a la salida de siempre, la acompaña."""
        resp = client.post(
            "/execute-extraction",
            json=_payload(_ESCRIBE_UN_CSV, artefactos_maximo=2, artefactos_maximo_bytes=100_000),
        )

        assert resp.json()["result"]["metrics"] == [{"name": "filas", "value": 2}]


class TestSinDeclararNoHayArtefactos:
    """Una función que no declara artefactos no los produce, aunque el guion escriba."""

    def test_no_se_devuelve_nada_si_el_caller_no_los_espera(self, client) -> None:
        resp = client.post("/execute-extraction", json=_payload(_ESCRIBE_UN_CSV))

        assert resp.status_code == 200, resp.text
        assert resp.json()["artefactos"] == []

    def test_pero_se_avisa_de_que_se_han_descartado(self, client) -> None:
        """**Descartar en silencio es lo que no se puede hacer.**

        El guion escribió algo y nadie lo va a recibir. Si eso no se dice, quien lo escribió cree
        que su Excel se está entregando y no aparece por ninguna parte; con el aviso sabe que le
        falta declararlos en el contrato.
        """
        resp = client.post("/execute-extraction", json=_payload(_ESCRIBE_UN_CSV))

        assert resp.json()["artefactos_descartados"] == 1


class TestLosTopesFallanEnAlto:

    def test_mas_ficheros_de_los_declarados(self, client) -> None:
        code = (
            "import pandas\n"
            "df = pandas.DataFrame({'a': [1]})\n"
            "for i in range(3):\n"
            "    df.to_csv(output_dir + '/f%d.csv' % i, index=False)\n"
            "result = {}\n"
        )

        resp = client.post(
            "/execute-extraction",
            json=_payload(code, artefactos_maximo=2, artefactos_maximo_bytes=100_000),
        )

        assert resp.status_code == 422
        cuerpo = resp.json()
        assert cuerpo["code"] == "ARTEFACTOS_DE_MAS"
        # Los dos números, porque «te has pasado» sin decir de cuánto no es accionable.
        assert cuerpo["producidos"] == 3
        assert cuerpo["maximo"] == 2

    def test_mas_bytes_de_los_declarados(self, client) -> None:
        code = (
            "import pandas\n"
            "df = pandas.DataFrame({'a': list(range(5000))})\n"
            "df.to_csv(output_dir + '/grande.csv', index=False)\n"
            "result = {}\n"
        )

        resp = client.post(
            "/execute-extraction",
            json=_payload(code, artefactos_maximo=1, artefactos_maximo_bytes=100),
        )

        assert resp.status_code == 422
        cuerpo = resp.json()
        assert cuerpo["code"] == "ARTEFACTOS_DEMASIADO_GRANDES"
        assert cuerpo["maximo_bytes"] == 100
        assert cuerpo["bytes"] > 100

    def test_un_subdirectorio_tambien_falla_en_alto(self, tmp_path) -> None:
        """Sólo son artefactos los ficheros que quedan **directamente** en `output_dir`.

        Recogerlos recursivamente obligaría a que el nombre llevara ruta, y el nombre lo propone
        el guion: es entrada no confiable y no puede ser una ruta. Así que un subdirectorio se
        dice, no se ignora — ignorarlo dejaría el fichero escrito y sin entregar.

        **Y va por la función y no por el endpoint a propósito.** Intenté escribirlo con un guion
        real y no se puede: crear un directorio necesita `pathlib` o `os`, y ninguno de los dos
        está en la lista blanca —`os` está denegado explícitamente—, así que el auditor lo para
        antes de llegar aquí. O sea que hoy **este camino no es alcanzable desde un guion**.

        La comprobación se queda porque la lista blanca es **el ecosistema autorizado y lo fija
        la institución** (AUT.9): el día que alguien apruebe `pathlib` para otra cosa, este caso
        pasa a ser alcanzable sin que nadie se acuerde de esta función. Lo que no se queda es la
        pretensión de que el test pase por donde no pasa.
        """
        from sandbox.contracts import ExecuteExtractionRequest
        from sandbox.main import _recoger_artefactos

        (tmp_path / "dentro").mkdir()
        (tmp_path / "dentro" / "x.csv").write_text("a\n1\n", encoding="utf-8")

        _artefactos, _descartados, err = _recoger_artefactos(
            tmp_path,
            ExecuteExtractionRequest(
                code="result = {}", artefactos_maximo=3, artefactos_maximo_bytes=100_000
            ),
        )

        assert err is not None
        assert err.status_code == 422
        assert b"ARTEFACTOS_EN_SUBDIRECTORIO" in err.body


class TestElDirectorioNoSobreviveALaEjecucion:

    def test_dos_ejecuciones_no_se_ven_los_ficheros(self, client) -> None:
        """Si el temporal persistiera, la segunda ejecución entregaría el fichero de la primera.

        Es el defecto que convierte un directorio de trabajo en una fuga entre organizaciones.
        """
        primera = client.post(
            "/execute-extraction",
            json=_payload(_ESCRIBE_UN_CSV, artefactos_maximo=5, artefactos_maximo_bytes=100_000),
        )
        assert primera.status_code == 200

        code_que_no_escribe = "result = {'metrics': []}\n"
        segunda = client.post(
            "/execute-extraction",
            json=_payload(
                code_que_no_escribe, artefactos_maximo=5, artefactos_maximo_bytes=100_000
            ),
        )

        assert segunda.status_code == 200
        assert segunda.json()["artefactos"] == []
