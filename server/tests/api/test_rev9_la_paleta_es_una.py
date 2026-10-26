"""REV.9 — la paleta del contrato y la del panel son la misma, y hay quien lo vigila.

El hallazgo que hay detrás no es «falta un color»: es que **había dos fuentes de verdad que no
se hablaban**. `ThemeColors` servía al widget; el panel se dibujaba con las variables Tailwind de
`frontend/src/index.css`, escritas a mano; y el único consumidor de la cascada del servidor era
el logotipo (`useMarca`). O sea que se podía cambiar cualquier color en «Identidad visual» y no
cambiaba nada.

El usuario lo notó por donde se nota —«el color de fondo de la barra lateral no aparece en la
selección de colores»—, y no aparecía porque no existía: la paleta configurable tenía otros
tokens, con otros valores, y su `primary` (`#0066cc`) ni siquiera era el azul de la aplicación
(`#0b5394`).

Este fichero es el guardarraíl de que no vuelvan a separarse. Compara el contrato con
`index.css`, que es el sitio donde vive el valor que de verdad se ve cuando no hay tema.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_RAIZ = Path(__file__).resolve().parents[3]
_INDEX_CSS = _RAIZ / "frontend" / "src" / "index.css"

#: Qué campo del contrato alimenta qué variable de `index.css`. La correspondencia se declara
#: aquí y no se adivina: los nombres coinciden casi siempre, y el «casi» es lo que se escapa.
CORRESPONDENCIA: dict[str, str] = {
    "primary": "--primary",
    "primaryForeground": "--primary-foreground",
    "accent": "--accent",
    "accentForeground": "--accent-foreground",
    "ring": "--ring",
    "sidebar": "--sidebar",
    "sidebarForeground": "--sidebar-foreground",
    "sidebarPrimary": "--sidebar-primary",
    "sidebarAccent": "--sidebar-accent",
    "sidebarAccentForeground": "--sidebar-accent-foreground",
    "sidebarBorder": "--sidebar-border",
}


def _variables_del_tema_claro() -> dict[str, str]:
    """Las variables del bloque `:root` de `index.css`, que es el tema claro.

    Se corta en `.dark` a propósito: el tema oscuro redefine las mismas variables con otros
    valores, y compararlas con el contrato daría un falso rojo.
    """
    texto = _INDEX_CSS.read_text(encoding="utf-8")
    # Se corta en el **selector** `.dark {` al principio de línea, no en la cadena «.dark»: la
    # línea 5 del fichero es `@custom-variant dark (&:is(.dark *));`, así que partir por la
    # cadena se llevaba el bloque `:root` entero y el test no encontraba una sola variable —
    # pasando por «la variable ya no está» cuando estaba.
    claro = re.split(r"^\.dark\s*\{", texto, maxsplit=1, flags=re.MULTILINE)[0]
    return {
        nombre: valor.strip().lower()
        for nombre, valor in re.findall(r"(--[a-z-]+):\s*([^;]+);", claro)
    }


def test_should_have_the_index_css_file_where_this_test_expects_it() -> None:
    """Si el fichero se mueve, este guardarraíl se convertiría en un test que no prueba nada."""
    assert _INDEX_CSS.is_file(), f"no está {_INDEX_CSS}"


@pytest.mark.parametrize(("campo", "variable"), sorted(CORRESPONDENCIA.items()))
def test_should_default_to_the_colour_the_panel_actually_paints(campo: str, variable: str) -> None:
    """**El test del prompt.** El valor por omisión del contrato tiene que ser el que el panel
    pinta hoy sin tema ninguno.

    Si no lo fuera, aplicar la cascada cambiaría la identidad visual sin que nadie lo pidiera —y
    la pantalla estaría enseñando un color que no es el de la aplicación, que es exactamente lo
    que pasaba con `primary`: contrato `#0066cc`, panel `#0b5394`.
    """
    from server.app.routers.hub_themes_router import ThemeColors

    del_contrato = getattr(ThemeColors(), campo).lower()
    del_css = _variables_del_tema_claro().get(variable)

    assert del_css is not None, f"{variable} ya no está en index.css"
    assert del_contrato == del_css, (
        f"«{campo}» vale {del_contrato} en el contrato y {variable} vale {del_css} en "
        "index.css. Son la misma decisión escrita en dos sitios: si se separan, la pantalla "
        "enseña un color y el panel pinta otro."
    )


def test_should_carry_every_panel_token_the_cascade_needs() -> None:
    """Los tokens del panel están en la paleta, no en un grupo aparte.

    La identidad de una institución es una: partirla en «colores del widget» y «colores del
    panel» obligaría a elegir dos veces el mismo azul, y a la tercera dejarían de coincidir.
    """
    from server.app.routers.hub_themes_router import ThemeColors

    declarados = set(ThemeColors().model_dump())
    assert set(CORRESPONDENCIA) <= declarados


def test_should_keep_the_widget_palette_too() -> None:
    """Ampliar no es sustituir: el widget sigue necesitando sus burbujas."""
    from server.app.routers.hub_themes_router import ThemeColors

    declarados = ThemeColors().model_dump()
    for campo in ("botMessage", "botMessageText", "userMessage", "userMessageText"):
        assert campo in declarados
