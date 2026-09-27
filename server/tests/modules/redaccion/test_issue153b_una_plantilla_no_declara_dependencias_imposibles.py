"""Issue #153, coletilla — una plantilla no puede declarar dependencias que nadie podrá cumplir.

**De dónde sale.** Al retirar `block_topology` se defendió que el orden de ejecución es el de la
plantilla, y es verdad: está decidido en SEG.1 —«quien redacta la plantilla sabe si la tabla de
matrícula va antes que la de tasas»—. La revisión de la PR #178 señaló lo que faltaba para que esa
defensa se sostenga: **si el orden lo fija quien escribe la plantilla, alguien tiene que comprobar
que ese orden es posible.** Antes lo habría cazado `BlockTopology.detect_cycles`, que tampoco
llamaba nadie.

Dos plantillas imposibles, y ninguna daba error:

- **Una dependencia hacia adelante**: `b_analisi` declara depender de `b_dades`, que está
  declarado después. Cuando el nodo de IA llega a `b_analisi`, `b_dades` todavía no ha producido
  nada, así que la propagación de fallos no ve nada que propagar y el apartado se redacta igual.
- **Un ciclo**: `A` depende de `B` y `B` de `A`. No rompe nada —la propagación termina— y
  simplemente ninguna de las dos puertas de revisión se abre nunca.

**Se comprueba al publicar la plantilla, no al ejecutarla**, y es el mismo criterio que ya está
escrito tres líneas más arriba en el router para los bloques sin sección: *«se rechaza aquí porque
es el único momento en que avisar sirve de algo»*. Validar al ejecutar llegaría tarde —el informe
ya está a medias— y validar al leer rompería las plantillas que ya están guardadas.
"""

from __future__ import annotations

import pytest

from server.app.modules.redaccion.contracts.block_io import BlockReference
from server.app.modules.redaccion.contracts.blocks import (
    AIAssistedTextBlock,
    DeterministicDataBlock,
)


def _datos(block_id: str, **kwargs):
    return DeterministicDataBlock(
        id=block_id, title=block_id, source_pipeline="EXCEL", **kwargs
    )


def _ia(block_id: str, depende_de: list[str]):
    return AIAssistedTextBlock(
        id=block_id,
        title=block_id,
        depends_on=[BlockReference(block_id=b) for b in depende_de],
        ai_prompt_template_id="p",
        review_policy_id="required",
    )


class TestDependenciasQueNoSePuedenCumplir:

    def test_una_dependencia_declarada_despues_se_senala(self):
        from server.app.modules.redaccion.services.estructura_del_informe import (
            dependencias_imposibles,
        )

        bloques = [_ia("b_analisi", ["b_dades"]), _datos("b_dades")]

        problemas = dependencias_imposibles(bloques)

        assert problemas, (
            "`b_analisi` depende de un bloque declarado después: cuando le toque, su dependencia "
            "no habrá producido nada y se redactará igual"
        )
        assert "b_analisi" in problemas[0] and "b_dades" in problemas[0]

    def test_un_ciclo_se_senala(self):
        from server.app.modules.redaccion.services.estructura_del_informe import (
            dependencias_imposibles,
        )

        bloques = [_ia("a", ["b"]), _ia("b", ["a"])]

        assert dependencias_imposibles(bloques), "un ciclo deja las dos puertas cerradas siempre"

    def test_una_dependencia_a_un_bloque_inexistente_se_senala(self):
        from server.app.modules.redaccion.services.estructura_del_informe import (
            dependencias_imposibles,
        )

        problemas = dependencias_imposibles([_ia("b_analisi", ["b_que_no_existe"])])

        assert problemas
        assert "b_que_no_existe" in problemas[0]


class TestLoQueSiEsValidoSigueSiendoValido:
    """Sin esto, la comprobación se cumpliría rechazándolo todo."""

    def test_el_orden_correcto_no_se_senala(self):
        from server.app.modules.redaccion.services.estructura_del_informe import (
            dependencias_imposibles,
        )

        bloques = [_datos("b_dades"), _ia("b_analisi", ["b_dades"]), _ia("b_conclusions", ["b_analisi"])]

        assert dependencias_imposibles(bloques) == []

    def test_una_plantilla_sin_dependencias_no_se_senala(self):
        from server.app.modules.redaccion.services.estructura_del_informe import (
            dependencias_imposibles,
        )

        assert dependencias_imposibles([_datos("a"), _datos("b")]) == []

    def test_el_perfil_generico_que_esta_en_produccion_es_valido(self):
        """El que de verdad importa: si esta comprobación rechazara el perfil vivo, sobra."""
        from server.app.modules.redaccion.profiles.generic_report import (
            GenericReportProfile,
        )
        from server.app.modules.redaccion.services.estructura_del_informe import (
            dependencias_imposibles,
        )

        assert dependencias_imposibles(GenericReportProfile().default_spec().blocks) == []
