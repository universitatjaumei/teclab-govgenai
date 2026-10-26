"""AIS.5 — La anonimización es política de la organización, y el informe sólo puede endurecerla.

**Decisión del usuario (2026-08-24)**: el piloto **no trata datos de ciudadanos**, y la
anonimización **no debe ser obligatoria sino configurable** — depende del contrato con el
proveedor LLM y del tipo de datos. Así que aquí **no se implementa bóveda cifrada**: la
persistencia del mapa sigue siendo F2.A.4, post-piloto.

**Lo que la auditoría dijo mal, y conviene dejar escrito.** Decía que faltaba la anonimización.
No falta: `AnonymizationMode` tiene cuatro valores desde la Fase 13 y es una columna por informe
con `replace` por omisión, o sea que **ya era política**. Y la evidencia del tratamiento tampoco
faltaba: el `RunManifest` ya guarda `anonymization_summary` con el modo y los conteos por tipo,
**sin originales ni sintéticos**.

Lo que sí quedaba son tres cosas, y las tres salen de la frase del usuario:

1. **«Depende del contrato con el proveedor» no es una decisión por informe.** El contrato es de
   la **organización**, y el ajuste vivía sólo en el informe: cada persona elegía el suyo sin
   que nadie pudiera fijar la política de la casa.
2. **El informe podía relajar lo que la organización endureciera.** Un modo por defecto que
   cualquiera puede bajar a `off` no es una política, es una sugerencia.
3. **`REPLACE` prometía más de lo que cumple.** Su docstring dice «revierte el output», y el
   mapa vive en memoria: dentro de una ejecución funciona, entre sesiones no. Re-identificar un
   informe generado ayer es imposible, y eso hay que decirlo donde se lee.

El orden de protección es `off < detect_only < replace < replace_with_disposition_7`, y el
último es el más protector **a propósito**: enmascara DNI, NIE y pasaporte de forma irreversible
(Disposición Adicional 7ª de la LOPDGDD), así que ni siquiera quien generó el informe puede
deshacerlo.
"""
from __future__ import annotations

import pytest


class TestElOrdenDeProteccion:

    def test_should_rank_the_modes_from_least_to_most_protective(self):
        from server.app.modules.redaccion.services.anonymization.run_context import (
            AnonymizationMode,
        )
        from server.app.modules.redaccion.services.anonymization.politica import (
            nivel_de_proteccion,
        )

        orden = [
            AnonymizationMode.OFF,
            AnonymizationMode.DETECT_ONLY,
            AnonymizationMode.REPLACE,
            AnonymizationMode.REPLACE_WITH_DISPOSITION_7,
        ]
        niveles = [nivel_de_proteccion(m) for m in orden]

        assert niveles == sorted(niveles), f"el orden no es monótono: {niveles}"
        assert len(set(niveles)) == len(orden), "dos modos con el mismo nivel no se distinguen"


class TestElInformeEndureceYNoRelaja:

    @pytest.mark.parametrize(
        ("heredado", "pedido", "esperado"),
        [
            # Endurecer siempre vale.
            ("replace", "replace_with_disposition_7", "replace_with_disposition_7"),
            ("detect_only", "replace", "replace"),
            # Relajar no: se queda lo que fijó la organización.
            ("replace", "off", "replace"),
            ("replace", "detect_only", "replace"),
            ("replace_with_disposition_7", "replace", "replace_with_disposition_7"),
            # Lo mismo es lo mismo.
            ("replace", "replace", "replace"),
            # **Sin política de organización manda el informe, incluso hacia abajo.** El valor
            # del código es un valor por omisión, NO un suelo: si lo fuera, nadie podría elegir
            # `off` en una instalación recién montada y la anonimización sería obligatoria con
            # otro nombre — justo lo contrario de la decisión del usuario.
            (None, "off", "off"),
            (None, "detect_only", "detect_only"),
        ],
    )
    def test_should_never_widen_what_the_organisation_set(self, heredado, pedido, esperado):
        from server.app.modules.redaccion.services.anonymization.politica import (
            modo_efectivo,
        )

        assert modo_efectivo(heredado=heredado, pedido=pedido).value == esperado

    def test_should_explain_why_a_request_was_not_applied(self):
        """Quien pide `off` y recibe `replace` tiene que saber **por qué**, o creerá que la
        pantalla no funciona. Es el mismo criterio que el 400 de SEC.9.2."""
        from server.app.modules.redaccion.services.anonymization.politica import (
            motivo_de_no_relajar,
        )

        motivo = motivo_de_no_relajar(heredado="replace", pedido="off")
        assert motivo is not None
        assert "replace" in motivo
        assert motivo_de_no_relajar(heredado="replace", pedido="replace_with_disposition_7") is None
        # Sin política de organización no hay nada que explicar: se aplica lo que se pidió.
        assert motivo_de_no_relajar(heredado=None, pedido="off") is None


class TestLaPoliticaSeHereda:

    def test_should_default_to_the_organisation_policy(self):
        from server.app.modules.redaccion.services.anonymization.politica import (
            modo_heredado,
        )

        assert modo_heredado(de_la_organizacion="detect_only").value == "detect_only"

    def test_should_fall_back_to_the_code_default_without_organisation_policy(self):
        """Nulo significa «la organización no lo ha fijado», y entonces manda el código — la
        misma regla que `core/ambito.py` aplica al resto de la configuración heredable."""
        from server.app.modules.redaccion.services.anonymization.politica import (
            MODO_POR_DEFECTO,
            modo_heredado,
        )

        assert modo_heredado(de_la_organizacion=None) is MODO_POR_DEFECTO
        assert MODO_POR_DEFECTO.value == "replace"

    def test_should_let_the_organisation_declare_its_policy(self):
        """La columna donde vive la decisión de la casa."""
        from server.app.modules.agents_hub.database.config_models import HubOrganizacion

        assert "anonymization_mode" in HubOrganizacion.__table__.columns


class TestLaPromesaDeReplaceEstaAcotada:

    def test_should_not_promise_cross_session_reidentification(self):
        from server.app.modules.redaccion.services.anonymization.run_context import (
            AnonymizationMode,
        )

        doc = AnonymizationMode.__doc__ or ""
        assert "revierte el output" not in doc, (
            "el docstring promete revertir sin decir hasta dónde: el mapa vive en memoria, así "
            "que dentro de la ejecución sí y entre sesiones no. Re-identificar un informe de "
            "ayer es imposible, y quien lo lee tiene que saberlo."
        )
        assert "ejecución" in doc.lower(), "la promesa tiene que decir su alcance"

    def test_should_not_keep_no_op_stubs_that_pretend_a_capability(self):
        """`save_state`/`load_state` eran no-op sin un solo consumidor: capacidad fingida.

        La regla del proyecto es «borra, no comentes», y la persistencia real llegará con
        F2.A.4 (Vault Edge) **cuando haya quien la consuma**. Dejar los stubs invita a
        llamarlos y a creer que el mapa se guardó.
        """
        # Vivían en `anonymization/service.py`, retirado entero en #262 por no usarlo nadie: se
        # mira el paquete, para que no vuelvan por otro fichero.
        from pathlib import Path

        from server.app.modules.redaccion.services import anonymization

        for fuente in Path(anonymization.__file__).parent.glob("*.py"):
            texto = fuente.read_text(encoding="utf-8")
            assert "async def save_state" not in texto, fuente.name
            assert "async def load_state" not in texto, fuente.name
