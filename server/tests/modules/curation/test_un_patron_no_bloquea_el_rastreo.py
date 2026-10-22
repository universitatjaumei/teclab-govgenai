"""Un patrón de URL de un administrador no puede bloquear la API.

`url_regex_filter` y los patrones `regex` de una sección se compilaban con `re` y se aplicaban a
cada URL descubierta **dentro del bucle de eventos**. `re` no tiene límite de tiempo y no suelta
el GIL mientras busca, así que un patrón con retroceso catastrófico —`^(a+)+$`— contra una URL
preparada dejaba la API entera parada: ni en otro hilo se habría salvado.

Ahora se busca con el motor `regex` y un tiempo máximo por búsqueda: lo que no termina a tiempo
no casa.
"""
from __future__ import annotations

import time

from server.app.modules.curation.secciones import casa_patron

PATRON_CATASTROFICO = r"^https://a\.es/(a+)+$"
URL_PREPARADA = "https://a.es/" + "a" * 40 + "!"


def test_should_give_up_on_a_catastrophic_pattern_quickly():
    empezado = time.monotonic()

    casa = casa_patron("regex", PATRON_CATASTROFICO, URL_PREPARADA)

    assert casa is False
    assert time.monotonic() - empezado < 1.0


def test_should_still_match_an_ordinary_pattern():
    assert casa_patron("regex", r"/va/", "https://www.uji.es/va/serveis/") is True
    assert casa_patron("regex", r"/va/", "https://www.uji.es/es/serveis/") is False


def test_the_spider_uses_the_same_bounded_search():
    """El filtro del sitio en el rastreador pasa por la misma búsqueda con tiempo máximo."""
    from server.app.modules.curation import spider

    texto = spider.__loader__.get_source(spider.__name__)

    assert "re.compile(url_regex_filter)" not in texto
