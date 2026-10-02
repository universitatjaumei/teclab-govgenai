"""UTL.2 (issue #191) — lo que el motor de anonimización por columnas tenía que arreglar antes.

El motor (`AnonymizationContext.analyze_fields` y `anonymize_dataframe`) ya estaba portado del
legacy, con los modos MASK, AEPD, FAKER e INITIALS. La #191 decía que el modo AEPD «no existe en la
plataforma»; existe, lo que no había era por dónde usarlo con un fichero. Pero al leerlo para
usarlo así salieron tres cosas que con un fichero de verdad importan:

1. **`analyze_fields` colapsaba los tipos.** Teléfono, IBAN, tarjeta y DNI salían todos como `"ID"`,
   y con el modo AEPD una columna de teléfonos se enmascararía como si fuera un DNI. Se añade el
   tipo preciso como campo **nuevo** (`pii_type`) y `type` se deja como estaba, porque lo consumen
   el servicio de anonimización de informes y `PiiDetector.scan_dataframe`.
2. **Las celdas vacías se convertían en `"nan"`** (`astype(str)`) y salían enmascaradas como `***`:
   el fichero resultante tenía contenido donde el original no tenía nada.
3. **Nadie validaba la letra del DNI/NIE.** La #191 lo atribuía al legacy y no lo tenía. Se escribe:
   sirve para dar confianza a una columna, **no para excluir valores** — aquí un falso negativo es
   un dato personal publicado.
"""
from __future__ import annotations

import pandas as pd
import pytest


def _ctx():
    from server.app.modules.redaccion.services.anonymization.anonymizer import (
        AnonymizationContext,
    )

    return AnonymizationContext(faker_seed=7)


class TestElTipoPreciso:

    def test_una_columna_de_telefonos_no_se_queda_en_id(self):
        df = pd.DataFrame({"contacto": ["612345678", "698765432", "655443322"]})

        analisis = {a["field"]: a for a in _ctx().analyze_fields(df)}

        assert analisis["contacto"]["pii_type"] == "PHONE"

    def test_y_la_de_dni_es_dni(self):
        df = pd.DataFrame({"documento": ["12345678Z", "87654321X", "11111111H"]})

        analisis = {a["field"]: a for a in _ctx().analyze_fields(df)}

        assert analisis["documento"]["pii_type"] == "DNI"

    def test_el_tipo_reducido_sigue_como_estaba(self):
        """Lo consumen el servicio de informes y `scan_dataframe`: cambiarlo los rompería."""
        df = pd.DataFrame({"contacto": ["612345678", "698765432"]})

        analisis = {a["field"]: a for a in _ctx().analyze_fields(df)}

        assert analisis["contacto"]["type"] == "ID"

    def test_una_columna_sin_nada_personal_es_none(self):
        df = pd.DataFrame({"importe": ["12,50", "300,00", "7,25"]})

        analisis = {a["field"]: a for a in _ctx().analyze_fields(df)}

        assert analisis["importe"]["pii_type"] == "NONE"


class TestLasCeldasVacias:

    @pytest.mark.parametrize("vacio", [None, float("nan"), ""])
    def test_una_celda_vacia_sigue_vacia(self, vacio):
        df = pd.DataFrame({"dni": ["12345678Z", vacio, "87654321X"]})

        resultado = _ctx().anonymize_dataframe(df, {"dni": {"type": "DNI", "mode": "AEPD"}})

        assert resultado["dni"].iloc[0] != "12345678Z"
        valor = resultado["dni"].iloc[1]
        assert valor is None or valor == "" or (isinstance(valor, float) and pd.isna(valor)), valor

    def test_y_en_los_nombres_tambien(self):
        df = pd.DataFrame({"nombre": ["Ana García", None]})

        resultado = _ctx().anonymize_dataframe(
            df, {"nombre": {"type": "PERSON_NAME", "mode": "FAKER"}}
        )

        assert pd.isna(resultado["nombre"].iloc[1])


class TestUnNombreFalsoTieneLaFormaDelVerdadero:
    """Lo destapó la verificación en el navegador: «Nombre completo» salía como una sola palabra.

    El generador miraba sólo la cabecera, y «Nombre completo» contiene «nom», así que inventaba un
    nombre de pila suelto para «Ana García López». Seguía anonimizado, pero no era verosímil y la
    columna perdía su forma: quien recibe el fichero ya no ve nombres y apellidos.
    """

    @pytest.mark.parametrize(
        "columna, original",
        [("Nombre completo", "Ana García López"), ("Persona", "Joan Puig"), ("Apellidos", "García López")],
    )
    def test_tantas_palabras_como_el_original(self, columna, original):
        df = pd.DataFrame({columna: [original]})

        resultado = _ctx().anonymize_dataframe(
            df, {columna: {"type": "PERSON_NAME", "mode": "FAKER"}}
        )

        falso = resultado[columna].iloc[0]
        assert falso != original
        assert len(falso.split()) == len(original.split()), falso

    def test_un_nombre_de_pila_sigue_siendo_uno(self):
        df = pd.DataFrame({"Nombre": ["Ana"]})

        resultado = _ctx().anonymize_dataframe(df, {"Nombre": {"type": "PERSON_NAME", "mode": "FAKER"}})

        assert len(resultado["Nombre"].iloc[0].split()) == 1


class TestLaLetraDelDni:

    @pytest.mark.parametrize("valor", ["12345678Z", "00000000T", "X1234567L", "Y0000000Z"])
    def test_una_letra_buena(self, valor):
        from server.app.modules.redaccion.services.anonymization.anonymizer import (
            letra_de_documento_valida,
        )

        assert letra_de_documento_valida(valor)

    @pytest.mark.parametrize("valor", ["12345678A", "X1234567A", "1234567", "hola"])
    def test_una_letra_mala_o_algo_que_no_es_un_documento(self, valor):
        from server.app.modules.redaccion.services.anonymization.anonymizer import (
            letra_de_documento_valida,
        )

        assert not letra_de_documento_valida(valor)
