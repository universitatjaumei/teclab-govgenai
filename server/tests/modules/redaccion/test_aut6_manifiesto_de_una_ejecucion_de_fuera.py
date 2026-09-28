"""AUT.6 (issue #116) — depositar el manifiesto de una ejecución hecha fuera.

Es el candidato §4.2 de `docs/GOVERNANCA_PER_API.md`, y el paso que va del **evento** a la
**evidencia**:

- El evento de actividad (REG.2, AUT.5) dice «quién, qué, cuándo, con qué finalidad».
- El manifiesto dice **qué pasó dentro de esa ejecución**: modelo, versión de prompt, fuentes
  citadas, aprobaciones humanas, hash de la salida.

Una aplicación construida fuera que genere informes con IA deposita el manifiesto de cada
generación, y el panel los lee junto a los de la plataforma, distinguiendo el origen.

**Y sin contenido, que es la regla que gobierna todo este bloque.** El manifiesto propio de la
plataforma guarda citas con `excerpt` —un trozo del documento—, y eso aquí **no puede entrar**:
un depósito abierto por API que admitiera extractos sería un segundo sitio donde viven los datos
personales de la organización, creado por la herramienta que existe para llevar la cuenta de los
riesgos. Es la misma regla del evento de actividad, y se hace cumplir igual: `extra="forbid"` más
un mensaje que explica **por qué** en vez de «Extra inputs are not permitted».

**Tabla propia y no `hub_run_manifests`.** Aquélla exige `workspace_id` y `template_version_id`
con clave ajena, y una ejecución de fuera no tiene ni workspace ni plantilla de la plataforma.
Hacer esas columnas nulas para que quepan las dos cosas dejaría una tabla en la que la mitad de
las filas incumplen lo que la otra mitad garantiza.

**Un cuaderno determinista no necesita manifiesto**: le basta el evento. El manifiesto añade
evidencia cuando hubo un modelo de por medio.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

import pytest

_AHORA = datetime(2026, 9, 29, 11, 0, tzinfo=timezone.utc)


def _manifiesto(**extra):
    from server.app.modules.redaccion.contracts.manifiesto_externo import (
        ManifiestoExterno,
    )

    datos = {
        "ocurrido_en": _AHORA,
        "aplicacion": "informes-uadti",
        "finalidad": "Redacción del informe de seguimiento del programa de doctorado",
        "modelo_usado": "claude-opus-5",
    }
    datos.update(extra)
    return ManifiestoExterno(**datos)


class TestLoQueElManifiestoRecoge:

    def test_el_modelo_la_version_de_prompt_y_el_hash_de_la_salida(self):
        digest = hashlib.sha256(b"el informe").hexdigest()

        manifiesto = _manifiesto(
            versiones_de_prompt=["informe_seguimiento_v3"],
            hash_de_la_salida=digest,
        )

        assert manifiesto.modelo_usado == "claude-opus-5"
        assert manifiesto.versiones_de_prompt == ["informe_seguimiento_v3"]
        assert manifiesto.hash_de_la_salida == digest

    def test_las_aprobaciones_humanas(self):
        """Es lo que distingue supervisión instrumentada de supervisión declarada."""
        manifiesto = _manifiesto(
            aprobaciones=[
                {
                    "actor": "u-7f3a1c",
                    "aprobado_en": _AHORA,
                    "que_aprobo": "bloque de valoración",
                }
            ]
        )

        assert manifiesto.aprobaciones[0].actor == "u-7f3a1c"

    def test_las_fuentes_citadas_por_referencia(self):
        manifiesto = _manifiesto(
            citas=[{"fuente": "https://www.boe.es/buscar/act.php?id=BOE-A-2017-12902"}]
        )

        assert manifiesto.citas[0].fuente.startswith("https://")

    def test_enlaza_con_la_funcion_del_catalogo_si_la_hay(self):
        """El mismo hash que AUT.5: el catálogo dice qué existe y esto qué hizo al correr."""
        digest = hashlib.sha256(b"el cuaderno").hexdigest()

        assert _manifiesto(funcion_sha256=digest).funcion_sha256 == digest


class TestSinContenido:
    """La regla del bloque, aquí también y con el mismo mensaje que la explica."""

    def test_una_cita_no_puede_traer_su_extracto(self):
        """El manifiesto propio lo guarda; éste no. Un depósito abierto por API que admitiera
        extractos sería un segundo sitio donde viven los datos personales."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as fallo:
            _manifiesto(
                citas=[{"fuente": "https://x.es/a", "excerpt": "El artículo 18 dice…"}]
            )

        assert "hash_de_la_salida" in str(fallo.value)

    def test_el_documento_generado_tampoco(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as fallo:
            _manifiesto(documento="El informe entero, en Markdown")

        assert "hash_de_la_salida" in str(fallo.value)

    def test_la_organizacion_no_viaja_en_el_cuerpo(self):
        """Se deriva del token. Si se pudiera elegir, una organización escribiría en otra."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as fallo:
            _manifiesto(organizacion_id=str(uuid.uuid4()))

        assert "token" in str(fallo.value)

    def test_un_hash_mal_formado_se_rechaza(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            _manifiesto(hash_de_la_salida="no-es-un-hash")


class TestElDeposito:

    @pytest.mark.asyncio
    async def test_queda_guardado_con_su_organizacion_y_su_marca(self, db_session):
        from server.app.modules.redaccion.database.models import HubManifiestoExterno

        organizacion = uuid.uuid4()
        fila = HubManifiestoExterno(
            organizacion_id=organizacion,
            ocurrido_en=_AHORA,
            aplicacion="informes-uadti",
            finalidad="Redacción del informe",
            modelo_usado="claude-opus-5",
            payload_json=_manifiesto().model_dump(mode="json"),
        )
        db_session.add(fila)
        await db_session.flush()

        assert fila.organizacion_id == organizacion
        assert fila.depositado_en is not None

    @pytest.mark.asyncio
    async def test_se_lee_acotado_a_la_organizacion(self, db_session):
        """La frontera de siempre: una organización no ve los manifiestos de otra."""
        from server.app.core.auth.models import UserInfo
        from server.app.modules.redaccion.database.models import HubManifiestoExterno
        from server.app.routers.governanca_router import (
            listar_manifiestos_externos,
        )

        mia, ajena = uuid.uuid4(), uuid.uuid4()
        for organizacion, aplicacion in ((mia, "la-mia"), (ajena, "la-de-otros")):
            db_session.add(
                HubManifiestoExterno(
                    organizacion_id=organizacion,
                    ocurrido_en=_AHORA,
                    aplicacion=aplicacion,
                    finalidad="Redacción",
                    payload_json={},
                )
            )
        await db_session.commit()

        pagina = await listar_manifiestos_externos(
            limite=50,
            principal=UserInfo(
                user_id=str(uuid.uuid4()),
                email="admin@uji.es",
                role="admin",
                organizacion_ids=[str(mia)],
            ),
            session=db_session,
        )

        assert [m.aplicacion for m in pagina] == ["la-mia"]

    @pytest.mark.asyncio
    async def test_dice_que_viene_de_fuera(self, db_session):
        """«Junto a los de la plataforma, distinguiendo el origen»: si no se distingue, un
        manifiesto declarado por un tercero se lee con la misma autoridad que uno que la
        plataforma produjo ella misma, y no son lo mismo."""
        from server.app.core.auth.models import UserInfo
        from server.app.modules.redaccion.database.models import HubManifiestoExterno
        from server.app.routers.governanca_router import (
            listar_manifiestos_externos,
        )

        organizacion = uuid.uuid4()
        db_session.add(
            HubManifiestoExterno(
                organizacion_id=organizacion,
                ocurrido_en=_AHORA,
                aplicacion="informes-uadti",
                finalidad="Redacción",
                payload_json={},
            )
        )
        await db_session.commit()

        pagina = await listar_manifiestos_externos(
            limite=50,
            principal=UserInfo(
                user_id=str(uuid.uuid4()),
                email="admin@uji.es",
                role="admin",
                organizacion_ids=[str(organizacion)],
            ),
            session=db_session,
        )

        assert pagina[0].origen == "externo"


class TestElScopePropio:

    def test_depositar_tiene_su_propio_permiso(self):
        """No se reutiliza `actividad:write`: registrar un uso y depositar la evidencia de una
        ejecución son dos capacidades, y una aplicación puede querer la primera sin la segunda."""
        from server.app.core.auth.pat.scopes import ALL_SCOPES, MANIFIESTOS_WRITE

        assert MANIFIESTOS_WRITE in ALL_SCOPES
        assert MANIFIESTOS_WRITE != "actividad:write"

    def test_lo_puede_emitir_tambien_un_admin_de_organizacion(self):
        """Depositar es añadir evidencia de lo propio: no muta nada de la plataforma."""
        from server.app.core.auth.pat.scopes import (
            MANIFIESTOS_WRITE,
            allowed_scopes_for_role,
        )

        assert MANIFIESTOS_WRITE in allowed_scopes_for_role("admin")
