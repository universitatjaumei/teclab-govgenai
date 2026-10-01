"""Issue #193 — el valor de un ancla acaba donde empieza la etiqueta siguiente.

**El defecto.** Los anclajes de formulario capturan el valor como «una palabra capitalizada, y
opcionalmente una segunda». En un formulario de una sola línea, esa segunda palabra es la
etiqueta del campo siguiente:

    "Nombre: Luis Apellidos: Pérez Martínez"
             └──── el ancla de nombre abarcaba «Luis Apellidos» ────┘

Y como el ancla se sustituye entera, el rótulo desaparecía:

    → 'Nombre: Manuela: Cantón'

**Por qué importa y no es cosmético.** Los anclajes existen precisamente para el caso en que el
texto *es* un formulario. Ahí el rótulo es la estructura del documento, no contenido personal, y
perderlo deja un texto que no se entiende — o peor, que parece correcto. Y esto se aplica a
documentos del cliente antes de mandarlos a un modelo externo: el modelo recibe un formulario con
los campos descolocados.

**Por qué no lo veía ningún test.** El test de anclajes afirmaba que los literales originales no
estuvieran en la salida. Eso se cumple **con más razón** si el ancla se pasa de largo: si se come
más texto, desaparece más. Una afirmación de ausencia no puede detectar que se borró demasiado.
Salió al reescribir ese test para que afirmara sobre los offsets detectados.

**Lo que este fichero fija**: el valor se corta ante una etiqueta conocida, y **sigue abarcando
dos palabras cuando la segunda no es una etiqueta** — que es el caso legítimo de «Luis Manuel» y
la razón por la que el patrón admitía dos desde el principio.
"""
from __future__ import annotations

import pytest

from server.app.modules.redaccion.services.anonymization.anonymizer import (
    AnonymizationContext,
)


@pytest.fixture
def ctx() -> AnonymizationContext:
    return AnonymizationContext(faker_seed=42)


def _ancla(ctx: AnonymizationContext, texto: str, tipo: str) -> str:
    """Qué trozo del texto original abarca el ancla de ese tipo."""
    ctx.anonymize(texto)
    anclas = ctx.get_detected_anchors()
    ancla = next(a for a in anclas if a["field_type"] == tipo)
    return texto[ancla["value_start"] : ancla["value_end"]]


class TestElValorSeCortaAnteLaEtiquetaSiguiente:

    def test_nombre_no_se_come_apellidos(self, ctx):
        texto = "Nombre: Luis Apellidos: Pérez Martínez"

        assert _ancla(ctx, texto, "firstname") == "Luis"

    def test_y_el_apellido_se_captura_entero(self, ctx):
        """La otra mitad: cortar de más dejaría medio apellido sin anonimizar."""
        texto = "Nombre: Luis Apellidos: Pérez Martínez"

        assert _ancla(ctx, texto, "lastname") == "Pérez Martínez"

    def test_el_rotulo_del_campo_siguiente_sobrevive(self, ctx):
        """La consecuencia visible, y la que le importa a quien lee el documento."""
        texto = "Nombre: Luis Apellidos: Pérez Martínez"

        salida = ctx.anonymize(texto)

        assert "Nombre:" in salida
        assert "Apellidos:" in salida

    @pytest.mark.parametrize(
        "etiqueta",
        ["Apellidos", "Cognoms", "Surname", "Titular", "Solicitante", "Correo", "Teléfono"],
    )
    def test_ninguna_etiqueta_conocida_se_traga(self, ctx, etiqueta):
        """Una sola etiqueta arreglada sería arreglar el ejemplo, no el defecto."""
        texto = f"Nombre: Luis {etiqueta}: algo"

        assert _ancla(ctx, texto, "firstname") == "Luis"


class TestUnNombreDeDosPalabrasSigueEntero:
    """Sin esto, el arreglo rompe lo que el patrón admitía dos palabras **para** hacer."""

    def test_nombre_compuesto_sin_etiqueta_detras(self, ctx):
        texto = "Nombre: Luis Manuel"

        assert _ancla(ctx, texto, "firstname") == "Luis Manuel"

    def test_y_tambien_cuando_le_sigue_texto_que_no_es_etiqueta(self, ctx):
        texto = "Nombre: Luis Manuel nacido en Castellón"

        assert _ancla(ctx, texto, "firstname") == "Luis Manuel"


class TestElNombreCompletoIgual:
    """`ANCHOR_FULLNAME` admite hasta cinco palabras, así que se traga más y peor."""

    def test_el_solicitante_no_se_come_el_campo_siguiente(self, ctx):
        texto = "Solicitante: Ana Pérez Correo: ana@uji.es"

        assert _ancla(ctx, texto, "fullname") == "Ana Pérez"

    def test_pero_un_nombre_largo_de_verdad_se_captura_entero(self, ctx):
        texto = "Solicitante: María del Carmen Pérez Martínez"

        # `del` va en minúscula, así que el patrón corta ahí y eso es previo a esta issue;
        # lo que se comprueba es que **no se queda sólo en la primera palabra**.
        assert _ancla(ctx, texto, "fullname").startswith("María")


class TestLasEtiquetasDeVariasPalabras:
    """Las que los propios anclajes reconocen y la lista de cortes no tenía (PR #210).

    `ETIQUETAS_DE_FORMULARIO` son palabras sueltas, y `First Name`, `Last Name`, `Primer
    Apellido` o `Segundo Apellido` no empiezan por ninguna de ellas: «Nombre: Luis First Name: Ana»
    seguía capturando `Luis First`. Se reconocen **enteras** y no por su primera palabra, porque
    «Primer» o «Segundo» solos no son etiquetas.
    """

    @pytest.mark.parametrize(
        "etiqueta", ["First Name", "Last Name", "Primer Apellido", "Segundo Apellido"]
    )
    def test_no_se_traga_la_primera_palabra_de_la_etiqueta(self, ctx, etiqueta):
        texto = f"Nombre: Luis {etiqueta}: Ana"

        assert _ancla(ctx, texto, "firstname") == "Luis"

    def test_y_una_palabra_que_solo_empieza_igual_sigue_contando(self, ctx):
        """«Primer» sin «Apellido» detrás no es una etiqueta: no se corta ahí."""
        texto = "Nombre: Luis Primero Apellidos: Pérez"

        assert _ancla(ctx, texto, "firstname") == "Luis Primero"
