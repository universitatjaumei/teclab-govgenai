"""Revisión de la PR #311: la caché del modelo de spaCy, con hilos.

#274 llevó la anonimización a `asyncio.to_thread`. Antes, la llamada bloqueante en el bucle
serializaba la primera carga; con hilos, dos peticiones en frío veían la caché vacía a la vez y
cargaban dos copias del modelo —cientos de MB cada una— en una VM con la memoria sobreasignada.
"""

from __future__ import annotations

import threading
import time

from server.app.modules.redaccion.services.anonymization import anonymizer


def test_dos_hilos_en_frio_cargan_el_modelo_una_sola_vez(monkeypatch) -> None:
    cargas: list[str] = []

    def _carga_lenta(model: str) -> object:
        cargas.append(model)
        time.sleep(0.05)
        return object()

    monkeypatch.setattr(anonymizer, "_NLP_CACHE", {})
    monkeypatch.setattr(anonymizer, "_try_load_spacy_model", _carga_lenta)

    resultados: list[object] = []
    hilos = [
        threading.Thread(target=lambda: resultados.append(anonymizer._get_nlp("es_core_news_md")))
        for _ in range(4)
    ]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join()

    assert cargas == ["es_core_news_md"]
    assert len({id(r) for r in resultados}) == 1
