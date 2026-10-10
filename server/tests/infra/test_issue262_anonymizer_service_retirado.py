"""#262 — `AnonymizerService` no lo usaba nadie, y se retira.

Lo encontró la auditoría independiente de la PR #260 (pandas 3): no se instanciaba en ningún sitio
de `server/app`, y con pandas 3 además fallaba con una fecha vacía (`fillna("").astype(str)` deja
`NaN` y `x.strip()` revienta). La regla es «si no se usa ahora, no existe»: se retira, no se arregla.

Lo único vivo del módulo eran tres funciones para leer y escribir el fichero tabular, y su único
consumidor es el anonimizador de datos de prueba: viven ahora con él.
"""
from __future__ import annotations

from pathlib import Path

SERVER = Path(__file__).resolve().parents[2]
ANONIMIZACION = SERVER / "app" / "modules" / "redaccion" / "services" / "anonymization"


def test_el_modulo_ya_no_esta():
    assert not (ANONIMIZACION / "service.py").exists()


def test_el_paquete_no_lo_exporta():
    from server.app.modules.redaccion.services import anonymization

    assert not hasattr(anonymization, "AnonymizerService")
    assert "AnonymizerService" not in anonymization.__all__


def test_el_anonimizador_de_datos_de_prueba_sigue_leyendo_y_escribiendo():
    import pandas as pd

    from server.app.modules.redaccion.services.test_data_anonymizer import (
        _read_dataframe,
        _write_dataframe,
    )

    df = pd.DataFrame({"a": ["x", "y"], "b": [1, 2]})
    for sufijo in ("csv", "xlsx", "json"):
        assert _read_dataframe(_write_dataframe(df, sufijo), sufijo).shape == (2, 2)
