"""Al corpus, sólo el contenido: fuera el menú y la plantilla (CUR.3).

El usuario quiere crear un chatbot con el apartado rastreado, y hoy **cada página lleva el menú
completo del portal**: de los ~3.600 caracteres de texto de una página, más de mil son navegación
idéntica en todas. Al corpus entra con el contenido, así que el asistente recupera menús y los cita.

**Lo que la medición del portal real cambió del plan.** El plan decía «quitar `<nav>`, `<header>`,
`<footer>`, `<aside>`». Medido en `/base/doctorands/`: el portal tiene **cero `<nav>`, cero
`<header>`, cero `<aside>`** —su menú son `div` con clases— y **un `<main>`**. Así que la señal útil
aquí es la inversa: **quedarse con `<main>`**. Quita el 39 % en esa página y el 67 % en la de
normativa. Las etiquetas estructurales se siguen descartando porque valen para otros portales, pero
no son lo que salva a este.

**Y la regla de seguridad del plan estaba mal.** Decía «si el recorte se lleva más de la mitad del
texto, conserva el original». Habría revertido la página de normativa, donde llevarse el 67 % es
exactamente lo correcto. Lo que hay que temer no es recortar mucho: es **quedarse sin contenido**.
"""
from __future__ import annotations

import pytest

from server.app.modules.curation.contenido_web import contenido_y_enlaces, texto_visible
from server.app.modules.curation.plantilla_del_sitio import bloques_repetidos, sin_bloques

# La forma real del portal: menú en divs, un `<main>`, y dentro de él la miga de pan, la barra de
# fecha y los iconos de compartir, que también son plantilla.
_PAGINA = """
<html><body>
  <div class="mainMenu"><a href="/x">Valencià</a><a href="/y">Español</a><a href="/z">English</a>
    <span>Menú mòbil</span><span>Perfil</span><span>Futur estudiantat</span></div>
  <main>
    <div class="breadcrumb">UJI Centres i departaments Escola de Doctorat</div>
    <h1>Alumnat de doctorat actual i futur</h1>
    <div class="clockBar"><span>24/09/2025</span> | <span>Escola de Doctorat</span></div>
    <div class="social-links">Compartir Linkedin BlueSky Facebook Mastodon Whatsapp</div>
    <p>El doctorat es regeix per la normativa de la Universitat.</p>
    <p>La matrícula es fa anualment dins el termini establert.</p>
  </main>
  <footer>Universitat Jaume I. Avinguda Vicent Sos Baynat. Castelló</footer>
</body></html>
"""

_SELECTORES_DE_PLANTILLA = [".breadcrumb", ".clockBar", ".social-links"]


# ---------------------------------------------------------------------------
# Estructura
# ---------------------------------------------------------------------------


def test_quedarse_con_el_contenido_deja_fuera_el_menu_y_el_pie():
    texto, _aviso, _enlaces = contenido_y_enlaces(_PAGINA, "main", _SELECTORES_DE_PLANTILLA)

    assert "El doctorat es regeix" in texto
    assert "Menú mòbil" not in texto
    assert "Avinguda Vicent Sos Baynat" not in texto


def test_tambien_se_van_los_bloques_de_plantilla_que_el_sitio_declara():
    """La miga de pan, la barra de fecha y los iconos de compartir están **dentro** de `<main>`."""
    texto, _aviso, _enlaces = contenido_y_enlaces(_PAGINA, "main", _SELECTORES_DE_PLANTILLA)

    assert "Centres i departaments" not in texto
    assert "24/09/2025" not in texto
    assert "BlueSky" not in texto


def test_sin_selector_de_contenido_se_van_las_etiquetas_estructurales():
    """Para un portal que sí use `<nav>` y `<footer>`, que este no usa."""
    html = (
        "<html><body><nav>Inici Serveis Contacte</nav>"
        "<p>Contingut de la pàgina.</p>"
        "<footer>Avís legal</footer></body></html>"
    )

    texto, _aviso, _enlaces = contenido_y_enlaces(html, None, [])

    assert texto == "Contingut de la pàgina."


def test_un_selector_de_contenido_que_no_encuentra_nada_no_deja_la_pagina_vacia():
    """Si el selector está mal, es mejor el texto entero que nada."""
    texto, aviso, _enlaces = contenido_y_enlaces(_PAGINA, "#noExiste", [])

    assert "El doctorat es regeix" in texto
    assert aviso == "content_selector_sin_coincidencia"


def test_el_texto_conserva_los_saltos_de_bloque():
    """Sin ellos el contenido es una sola línea: no se puede trocear bien ni detectar plantilla."""
    texto, _aviso, _enlaces = contenido_y_enlaces(_PAGINA, "main", _SELECTORES_DE_PLANTILLA)

    assert "\n" in texto
    lineas = texto.split("\n")
    assert "Alumnat de doctorat actual i futur" in lineas


def test_el_texto_visible_sigue_sin_dobles_espacios():
    assert "  " not in texto_visible(_PAGINA)


# ---------------------------------------------------------------------------
# Repetición medida: lo que generaliza a portales sin `<main>`
# ---------------------------------------------------------------------------

_MENU = "Inici Serveis Contacte Cercar"
_PIE = "Universitat Jaume I. Avis legal"


def _paginas_con_menu(cuantas: int) -> list[str]:
    return [
        f"{_MENU}\nContingut propi de la pagina {i}.\nAltre paragraf {i}.\n{_PIE}"
        for i in range(cuantas)
    ]


def test_una_linea_que_sale_en_casi_todas_las_paginas_es_plantilla():
    bloques = bloques_repetidos(_paginas_con_menu(10), umbral=0.6)

    assert _MENU in bloques
    assert _PIE in bloques


def test_el_contenido_propio_de_cada_pagina_no_es_plantilla():
    bloques = bloques_repetidos(_paginas_con_menu(10), umbral=0.6)

    assert "Contingut propi de la pagina 3." not in bloques


def test_con_pocas_paginas_no_se_concluye_que_algo_es_plantilla():
    """Dos páginas que comparten una frase no bastan: podría ser contenido que se repite."""
    assert bloques_repetidos(_paginas_con_menu(2), umbral=0.6) == set()


def test_quitar_los_bloques_repetidos_deja_el_contenido():
    paginas = _paginas_con_menu(10)
    bloques = bloques_repetidos(paginas, umbral=0.6)

    limpio, aviso = sin_bloques(paginas[0], bloques)

    assert limpio == "Contingut propi de la pagina 0.\nAltre paragraf 0."
    assert aviso is None


def test_una_linea_muy_corta_no_cuenta_como_plantilla():
    """«Compartir» o «Més» aparecen en todas partes y quitarlas no aporta nada; en cambio, una
    palabra suelta puede ser contenido de una ficha."""
    paginas = ["Mes\nContingut u.", "Mes\nContingut dos.", "Mes\nContingut tres."] * 4

    assert bloques_repetidos(paginas, umbral=0.6) == set()


# ---------------------------------------------------------------------------
# La regla de seguridad, corregida por la medición
# ---------------------------------------------------------------------------


def test_llevarse_dos_tercios_del_texto_es_correcto_y_no_se_revierte():
    """Medido en la página de normativa del portal: 2.120 caracteres de texto, 697 de contenido.
    La regla del plan —«si se lleva más de la mitad, conserva el original»— la habría revertido."""
    pagina = f"{_MENU}\n{_PIE}\n" + "Menu llarg repetit. " * 20 + "\nEl contingut util."
    bloques = {_MENU, _PIE, ("Menu llarg repetit. " * 20).strip()}

    limpio, aviso = sin_bloques(pagina, bloques)

    assert limpio == "El contingut util."
    assert aviso is None


def test_una_pagina_cuyo_contenido_es_una_frase_corta_conserva_esa_frase():
    """El cinturón tenía un mínimo de caracteres y revertía esto: devolver el menú entero a cambio
    de conservar dieciocho caracteres es peor negocio. Que la página tenga poco contenido ya lo dice
    `thin`, que es criterio de cada sitio."""
    pagina = f"{_MENU}\nSí, es obligatori.\n{_PIE}"

    limpio, aviso = sin_bloques(pagina, {_MENU, _PIE})

    assert limpio == "Sí, es obligatori."
    assert aviso is None


def test_si_el_recorte_no_deja_nada_se_conserva_el_original():
    """Lo único inequívoco: nos hemos comido la página entera."""
    pagina = f"{_MENU}\n{_PIE}"

    limpio, aviso = sin_bloques(pagina, {_MENU, _PIE})

    assert limpio == pagina
    assert aviso == "recorte_deja_la_pagina_vacia"


def test_una_pagina_sin_plantitlla_no_se_toca():
    pagina = "Contingut sencer de la pagina, sense menu."

    limpio, aviso = sin_bloques(pagina, set())

    assert limpio == pagina
    assert aviso is None


# ---------------------------------------------------------------------------
# El contrato de configuración
# ---------------------------------------------------------------------------


def test_el_sitio_declara_su_contenido_y_su_plantilla():
    from server.app.modules.curation.selection_contracts import CrawlConfig

    config = CrawlConfig(
        content_selector="main", boilerplate_selectors=[".clockBar", ".social-links"]
    )

    assert config.content_selector == "main"
    assert config.boilerplate_selectors == [".clockBar", ".social-links"]


def test_por_defecto_no_se_recorta_nada_por_selector():
    """El marcado es de cada portal: el defecto no puede ser el de la UJI."""
    from server.app.modules.curation.selection_contracts import CrawlConfig

    config = CrawlConfig()

    assert config.content_selector is None
    assert config.boilerplate_selectors == []


@pytest.mark.parametrize("umbral", [0.0, 1.01, -0.5])
def test_un_umbral_de_repeticion_imposible_se_rechaza(umbral: float):
    from pydantic import ValidationError

    from server.app.modules.curation.selection_contracts import CrawlConfig

    with pytest.raises(ValidationError):
        CrawlConfig(boilerplate_repeat_threshold=umbral)
