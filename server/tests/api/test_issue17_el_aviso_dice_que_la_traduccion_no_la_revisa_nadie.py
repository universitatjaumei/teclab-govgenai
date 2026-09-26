"""Issue #17 — el aviso tiene que decir que **la traducción** no la ha revisado nadie.

**La premisa de la issue estaba desactualizada, y lo que falta no es lo que decía.** La issue
pedía que el aviso permanente de contenido generado por IA mencionara la lengua. Ya la menciona:
las seis cadenas de `chat.json` dicen «no han pasado revisión lingüística: contrasta siempre con
la norma citada». Eso cubre el caso general.

**Lo que no cubre es el caso concreto, y es el que preocupa.** Al corpus **sólo entran
originales**: no se sube ni una traducción. Cuando quien pregunta escribe en una lengua y la
norma que responde su pregunta sólo existe en la otra, lo que lee **no es la norma**: es una
traducción que ha hecho el modelo en ese momento, que nadie ha revisado y que no está publicada
en ningún sitio. Decir «puede contener errores» no es decir eso.

**El aviso condicional ya existe y es el sitio correcto.** `_build_translation_warning` se emite
exactamente cuando la lengua de la fuente difiere de la de la pregunta (VIS.5), que es la
condición que define el caso. Lo que le faltaba era la mitad importante: decía **dónde lleva el
enlace** y no **qué es lo que se está leyendo**.

Que sea condicional y no permanente es deliberado: un aviso que sale siempre se aprende a
ignorar, y afirmar en las 511 normas que sólo existen en valencià que su traducción no está
revisada sería además falso —no hay traducción ninguna cuando se pregunta en valencià—.
"""
from __future__ import annotations

import pytest

from server.app.api.v1.hub_chat import _build_translation_warning

#: Las tres lenguas en las que el aviso se escribe, con la marca de que dice lo que tiene que
#: decir. No se comprueba la frase literal: eso sería fijar la redacción en un test y obligar a
#: tocarlo cada vez que el servicio de lenguas pula una coma.
_LO_QUE_TIENE_QUE_DECIR: dict[str, tuple[str, str]] = {
    # lengua de la pregunta: (que la respuesta se generó sola, que nadie revisó la traducción)
    "val": ("automatitzada", "traducció"),
    "es": ("automatizada", "traducción"),
    "en": ("automatically", "translation"),
}


class TestElAvisoDiceQueLaTraduccionNoEstaRevisada:

    @pytest.mark.parametrize("pregunta", sorted(_LO_QUE_TIENE_QUE_DECIR))
    def test_lo_dice_en_las_tres_lenguas(self, pregunta: str) -> None:
        aviso = _build_translation_warning(
            lengua_de_la_fuente="fr", lengua_de_la_pregunta=pregunta
        )

        assert aviso is not None
        automatica, traduccion = _LO_QUE_TIENE_QUE_DECIR[pregunta]
        assert automatica in aviso.lower(), (
            f"el aviso en «{pregunta}» no dice que la respuesta se haya generado de forma "
            f"automatizada: {aviso!r}"
        )
        assert traduccion in aviso.lower(), (
            f"el aviso en «{pregunta}» no dice que lo que se lee es una traducción sin revisar. "
            f"Al corpus sólo entran originales, así que esa traducción la acaba de hacer el "
            f"modelo y no está publicada en ningún sitio: {aviso!r}"
        )

    def test_sigue_diciendo_en_que_lengua_esta_la_norma(self) -> None:
        """VIS.5 no se pierde por el camino: nombrar la lengua de la fuente es lo que permite
        entender por qué el enlace lleva a un documento que no se puede leer igual."""
        aviso = _build_translation_warning(lengua_de_la_fuente="val", lengua_de_la_pregunta="es")

        assert aviso is not None
        assert "valenci" in aviso.lower()

    def test_sigue_sin_salir_cuando_no_hay_traduccion(self) -> None:
        """La condición no cambia: si la norma está en la lengua de la pregunta no hay ninguna
        traducción de la que avisar, y afirmar lo contrario sería falso."""
        assert (
            _build_translation_warning(lengua_de_la_fuente="val", lengua_de_la_pregunta="val")
            is None
        )
