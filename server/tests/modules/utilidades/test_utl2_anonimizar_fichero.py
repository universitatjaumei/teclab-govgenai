"""UTL.2 (issue #191) — anonimizar un fichero tabular y descargarlo, sin que forme parte de nada.

El flujo es el del legacy: subir → analizar y **proponer** un tipo y una regla por columna → que la
persona ajuste → **previsualizar** → descargar. Sólo CSV y Excel (decisión del usuario, 2026-10-01);
un Word o un PDF anonimizado es reescribir el documento manteniendo el formato, y es otra issue.

Lo que este fichero fija:

* **Cada columna tiene su regla, y la regla depende del tipo.** Un DNI admite AEPD; un nombre,
  iniciales. Una regla que no corresponde al tipo se rechaza en vez de aplicarse a medias.
* **El texto libre no se sustituye entero.** Una columna «observaciones» con «Hablar con Ana García»
  se detecta bien como nombres, pero sustituir la celda por un nombre falso borraría el texto. Se
  propone `TEXTO`, que cambia sólo lo que encuentra dentro.
* **La vista previa es la descarga.** Las dos usan la misma semilla y anonimizan el fichero entero,
  así que lo que se ve en la vista previa es exactamente lo que se descarga: un FAKER distinto entre
  una y otra haría que la persona revisara algo que no es lo que va a compartir.
* **Una celda vacía sigue vacía, y lo que no se toca sale igual.**
"""
from __future__ import annotations

import io

import pandas as pd
import pytest

LISTADO = (
    "Nombre completo;DNI;Correo;Teléfono;Observaciones;Importe\n"
    "Ana García López;12345678Z;ana.garcia@example.org;612345678;Hablar con Ana García;12,50\n"
    "Joan Puig Soler;87654321X;joan.puig@example.org;698765432;Sin incidencias;300,00\n"
    "Marta Ferrer Pla;;marta@example.org;655443322;Pendiente;7,25\n"
).encode("utf-8")


def _excel() -> bytes:
    buffer = io.BytesIO()
    pd.DataFrame(
        {"Nombre": ["Ana García", "Joan Puig"], "DNI": ["12345678Z", "87654321X"], "Plazas": [3, 5]}
    ).to_excel(buffer, index=False)
    return buffer.getvalue()


class TestLeer:

    def test_un_csv_con_punto_y_coma(self):
        from server.app.modules.utilidades.anonimizar import leer_tabla

        tabla = leer_tabla(LISTADO, "listado.csv")

        assert tabla.formato == "csv"
        assert tabla.separador == ";"
        assert list(tabla.df.columns)[0] == "Nombre completo"
        assert len(tabla.df) == 3

    def test_un_excel(self):
        from server.app.modules.utilidades.anonimizar import leer_tabla

        tabla = leer_tabla(_excel(), "listado.xlsx")

        assert tabla.formato == "xlsx"
        assert len(tabla.df) == 2

    @pytest.mark.parametrize("nombre", ["informe.docx", "datos.json", "sin_extension"])
    def test_lo_que_no_es_csv_ni_excel_se_rechaza(self, nombre):
        from server.app.modules.utilidades.anonimizar import FicheroNoValido, leer_tabla

        with pytest.raises(FicheroNoValido):
            leer_tabla(b"algo", nombre)


class TestProponer:

    def _propuestas(self):
        from server.app.modules.utilidades.anonimizar import analizar, leer_tabla

        return {p.columna: p for p in analizar(leer_tabla(LISTADO, "listado.csv"))}

    def test_propone_aepd_para_el_dni(self):
        p = self._propuestas()["DNI"]

        assert (p.tipo, p.modo) == ("DNI", "AEPD")
        assert "AEPD" in p.modos_posibles

    def test_el_texto_libre_se_propone_como_texto(self):
        """Sustituir la celda entera por un nombre falso borraría el texto que la rodea."""
        p = self._propuestas()["Observaciones"]

        assert p.tipo == "TEXTO"

    def test_lo_que_no_es_personal_se_deja(self):
        p = self._propuestas()["Importe"]

        assert p.modo == "NINGUNO"


class TestAplicar:

    def _tabla(self):
        from server.app.modules.utilidades.anonimizar import leer_tabla

        return leer_tabla(LISTADO, "listado.csv")

    def test_aepd_deja_solo_las_cifras_centrales(self):
        from server.app.modules.utilidades.anonimizar import Regla, aplicar

        df = aplicar(self._tabla().df, {"DNI": Regla("DNI", "AEPD")}, semilla=1)

        assert df["DNI"].iloc[0] == "***4567**"

    def test_una_celda_vacia_sigue_vacia_y_lo_demas_igual(self):
        from server.app.modules.utilidades.anonimizar import Regla, aplicar

        original = self._tabla().df
        df = aplicar(original, {"DNI": Regla("DNI", "AEPD")}, semilla=1)

        assert df["DNI"].iloc[2] == ""
        assert df["Importe"].tolist() == original["Importe"].tolist()

    def test_el_texto_libre_solo_cambia_el_nombre(self):
        from server.app.modules.utilidades.anonimizar import Regla, aplicar

        df = aplicar(self._tabla().df, {"Observaciones": Regla("TEXTO", "TEXTO")}, semilla=1)

        assert df["Observaciones"].iloc[0].startswith("Hablar con ")
        assert "Ana García" not in df["Observaciones"].iloc[0]
        assert df["Observaciones"].iloc[1] == "Sin incidencias"

    def test_una_regla_que_no_corresponde_al_tipo_se_rechaza(self):
        from server.app.modules.utilidades.anonimizar import Regla, ReglaNoValida, aplicar

        with pytest.raises(ReglaNoValida):
            aplicar(self._tabla().df, {"Correo": Regla("EMAIL", "AEPD")}, semilla=1)

    def test_una_columna_que_no_existe_se_rechaza(self):
        from server.app.modules.utilidades.anonimizar import Regla, ReglaNoValida, aplicar

        with pytest.raises(ReglaNoValida):
            aplicar(self._tabla().df, {"Inventada": Regla("DNI", "AEPD")}, semilla=1)

    def test_la_misma_semilla_da_el_mismo_resultado(self):
        """Es lo que hace que la vista previa sea lo que se descarga."""
        from server.app.modules.utilidades.anonimizar import Regla, aplicar

        reglas = {"Nombre completo": Regla("PERSON_NAME", "FAKER")}
        una = aplicar(self._tabla().df, reglas, semilla=42)
        otra = aplicar(self._tabla().df, reglas, semilla=42)

        assert una["Nombre completo"].tolist() == otra["Nombre completo"].tolist()
        assert "Ana García López" not in una["Nombre completo"].tolist()


class TestEscribir:

    def test_el_csv_sale_con_su_separador(self):
        from server.app.modules.utilidades.anonimizar import Regla, aplicar, escribir, leer_tabla

        tabla = leer_tabla(LISTADO, "listado.csv")
        datos = escribir(aplicar(tabla.df, {"DNI": Regla("DNI", "AEPD")}, semilla=1), tabla)

        primera = datos.decode("utf-8-sig").splitlines()[0]
        assert primera.startswith("Nombre completo;DNI;")

    def test_el_excel_sale_como_excel_y_los_numeros_siguen_siendo_numeros(self):
        from server.app.modules.utilidades.anonimizar import Regla, aplicar, escribir, leer_tabla

        tabla = leer_tabla(_excel(), "listado.xlsx")
        datos = escribir(aplicar(tabla.df, {"DNI": Regla("DNI", "AEPD")}, semilla=1), tabla)

        releido = pd.read_excel(io.BytesIO(datos))
        assert releido["DNI"].iloc[0] == "***4567**"
        assert releido["Plazas"].tolist() == [3, 5]
