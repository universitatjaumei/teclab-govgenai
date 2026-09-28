"""AUT.5 (issue #124) — un cuaderno que corre fuera registra su ejecución en tres líneas.

AUT.3 dejó el cuaderno **registrado** en el catálogo: existe, tiene versión, finalidad y quien
responde de él. Lo que faltaba es la otra mitad del circuito: saber **cuándo se ha ejecutado y
por quién**, que es lo que convierte un catálogo en un registro de actividad.

**El enlace entre las dos mitades es el hash del fichero.** El cuaderno sabe calcular el suyo sin
saber nada de la plataforma —ni identificadores, ni versiones—, y ese hash es exactamente lo que
`HubFuncionVersion.code_sha256` guardó al registrarlo. Así el evento se puede cruzar con su
función sin que el cuaderno tenga que consultar nada antes de arrancar.

**Y no se reutiliza `payload_hash`.** Ese campo significa «el SHA-256 del contenido procesado», y
usarlo para el hash del programa convertiría en ambiguo el único campo del registro que existe
para cotejar un tratamiento concreto. Un campo nuevo cuesta una migración; un campo con dos
significados cuesta una auditoría que no se puede leer.

**Si el cuaderno no está registrado, el hash no casa con nada y no pasa nada.** Es información
igualmente: consta que se ejecutó algo que no está en el catálogo, que es justo lo que las normas
de desarrollo ciudadano llaman distribución informal.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

import pytest

CUADERNO = '{"cells": [{"cell_type": "code", "source": ["x = 1"]}]}'


def _evento(**extra):
    from server.app.modules.agents_hub.contracts.actividad import ActividadIAEvent

    datos = {
        "ocurrido_en": datetime(2026, 9, 29, 10, 0, tzinfo=timezone.utc),
        "actor": "u-7f3a1c",
        "herramienta": "jupyter",
        "finalidad": "Extracción anual de subvenciones nominativas",
        "categorias_datos": ["sin_datos_personales"],
    }
    datos.update(extra)
    return ActividadIAEvent(**datos)


class TestElHashDelCuadernoViajaEnElEvento:

    def test_se_acepta_un_sha256_del_fichero(self):
        digest = hashlib.sha256(CUADERNO.encode()).hexdigest()

        assert _evento(funcion_sha256=digest).funcion_sha256 == digest

    def test_sin_el_sigue_valiendo_el_evento_de_siempre(self):
        """Es opcional: la mayoría de las herramientas que registran no son un cuaderno."""
        assert _evento().funcion_sha256 is None

    def test_un_hash_mal_formado_se_rechaza_al_registrar(self):
        """Mismo criterio que `payload_hash`: un hash que no cotejará nada es mejor saberlo
        aquí que en la auditoría, cuando ya no se puede rehacer."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            _evento(funcion_sha256="esto-no-es-un-hash")

    def test_en_minuscula_porque_si_no_no_casa_con_el_catalogo(self):
        """`code_sha256` se guarda en minúscula; dos formas del mismo hash no se cruzan solas."""
        from pydantic import ValidationError

        digest = hashlib.sha256(CUADERNO.encode()).hexdigest().upper()

        with pytest.raises(ValidationError):
            _evento(funcion_sha256=digest)


class TestElCircuitoSeCierra:
    """Lo que importa de verdad: que el evento y la función registrada se puedan cruzar."""

    @pytest.mark.asyncio
    async def test_el_hash_del_evento_es_el_que_guardo_el_catalogo(self, db_session):
        from server.app.modules.redaccion.contracts.funciones import ContratoFuncion
        from server.app.modules.redaccion.funciones_service import registrar_version

        _funcion, version = await registrar_version(
            db_session,
            nombre="Subvenciones nominativas",
            organizacion_id=uuid.uuid4(),
            code=CUADERNO,
            contrato=ContratoFuncion(
                slots=[],
                parametros=[],
                finalidad="Extraer las subvenciones nominativas",
                categorias_datos=["sin_datos_personales"],
            ),
            declarada_por=uuid.uuid4(),
            origen="externa",
            entorno_ejecucion="un cuaderno en el equipo de la persona",
        )

        # Lo que el cuaderno calcula por su cuenta, sin saber nada de la plataforma.
        desde_el_cuaderno = hashlib.sha256(CUADERNO.encode()).hexdigest()

        assert version.code_sha256 == desde_el_cuaderno
        assert _evento(funcion_sha256=desde_el_cuaderno).funcion_sha256 == version.code_sha256

    @pytest.mark.asyncio
    async def test_se_guarda_en_la_fila_del_registro(self, db_session):
        from server.app.modules.agents_hub.database.operational_models import (
            HubActividadIA,
        )

        digest = hashlib.sha256(CUADERNO.encode()).hexdigest()
        fila = HubActividadIA(
            organizacion_id=uuid.uuid4(),
            ocurrido_en=datetime.now(timezone.utc),
            actor="u-7f3a1c",
            herramienta="jupyter",
            finalidad="Extracción anual",
            categorias_datos=["sin_datos_personales"],
            funcion_sha256=digest,
        )
        db_session.add(fila)
        await db_session.flush()

        assert fila.funcion_sha256 == digest


class TestLoQueSigueSinPoderMandarse:

    def test_el_contenido_del_cuaderno_no(self):
        """El campo nuevo no abre la puerta que el bloque REG cerró: metadatos sí, payloads no."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as fallo:
            _evento(payload="las filas del presupuesto")

        assert "payload_hash" in str(fallo.value)
