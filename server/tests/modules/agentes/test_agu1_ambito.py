"""#172 — las tablas de los agentes declaran su ámbito, aunque MT.1 sólo recorra configuración.

Son operacionales por el criterio de FUN —el prompt y la declaración son texto de una persona de
la organización— y por eso el guardarraíl de MT.1, que sólo mira `HubConfigBase`, no las vería.
Éste es el que les faltaría, como `test_fun1_catalogo.py` lo es para las funciones.
"""
from __future__ import annotations


def test_el_agente_es_siempre_de_una_organizacion():
    from server.app.core.ambito import Ambito, ambito_de
    from server.app.modules.agents_hub.database.operational_models import HubAgenteUnidad

    assert ambito_de(HubAgenteUnidad).ambito is Ambito.ORGANIZACION
    assert HubAgenteUnidad.__table__.c.organizacion_id.nullable is False


def test_la_version_llega_a_la_organizacion_por_su_agente():
    from server.app.core.ambito import Ambito, ambito_de
    from server.app.modules.agents_hub.database.operational_models import (
        HubAgenteUnidadVersion,
    )

    derivada = ambito_de(HubAgenteUnidadVersion)
    assert derivada.ambito is Ambito.DERIVADA
    assert derivada.via == "agente_id"


def test_son_operacionales_y_no_configuracion():
    """La configuración se sincroniza cloud→edge, y esto es texto escrito por una persona."""
    from server.app.modules.agents_hub.database.base import HubOperationalBase
    from server.app.modules.agents_hub.database.operational_models import (
        HubAgenteUnidad,
        HubAgenteUnidadVersion,
    )

    assert issubclass(HubAgenteUnidad, HubOperationalBase)
    assert issubclass(HubAgenteUnidadVersion, HubOperationalBase)
