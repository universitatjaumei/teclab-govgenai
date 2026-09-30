"""AUT.7 (issue #117) — una función del catálogo puede producir **ficheros**, no sólo cifras.

Hoy la salida de una función es un `ExtractionResult`: tablas, métricas y texto para un bloque de
informe. Las tareas reales de una unidad no acaban así — acaban en **un Excel que alguien manda**,
un Word maquetado o un CSV limpio. Mientras la salida sean sólo cifras, esas tareas se quedan
fuera del catálogo, y quedarse fuera del catálogo significa quedarse sin declaración, sin
auditoría, sin versionado y sin registro.

**Lo que este fichero fija, y es la parte que se puede escribir mal sin que se note:**

1. **Los topes se declaran en el contrato**, no en una constante del servidor. Cuántos ficheros y
   cuántos bytes. Una función que produce un Excel de 200 KB y otra que produce cincuenta PDF no
   pueden compartir un número inventado a medias entre las dos.
2. **Una función que no declara artefactos no puede producirlos.** Es la mitad que se olvida: sin
   esto, el tope declarado es un consejo y cualquier guion escribe lo que quiera en el
   directorio de salida.
3. **Cada artefacto viaja con su hash.** Es lo que permite decir meses después si el fichero que
   alguien tiene es el que salió de aquí. Sin hash, el artefacto es un adjunto sin procedencia.
4. **Y la retención se declara.** Es la decisión que la issue dejaba anotada: la plataforma no
   tiene política de retención en ningún registro (#162), y aquí hace falta una aunque sea
   estrecha. Se declara por contrato y en días; lo que **no** se hace es guardar para siempre
   por omisión, que es como un almacén de ficheros ajenos se crea sin que nadie lo decida.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError


def _contrato(**kw):
    from server.app.modules.redaccion.contracts.funciones import ContratoFuncion

    datos = {
        "slots": [],
        "parametros": [],
        "finalidad": "Sacar el Excel de subvenciones nominativas",
        "categorias_datos": ["sin_datos_personales"],
    }
    datos.update(kw)
    return ContratoFuncion(**datos)


class TestElContratoDeclaraLosArtefactos:

    def test_por_omision_una_funcion_no_produce_ficheros(self):
        """El defecto seguro. Las funciones que ya existen no ganan una capacidad sin pedirla."""
        contrato = _contrato()

        assert contrato.artefactos is None

    def test_se_declaran_con_su_tope_de_numero_y_de_tamano(self):
        from server.app.modules.redaccion.contracts.funciones import ArtefactosDeSalida

        contrato = _contrato(
            artefactos=ArtefactosDeSalida(maximo=2, maximo_bytes=5_000_000, retencion_dias=7)
        )

        assert contrato.artefactos.maximo == 2
        assert contrato.artefactos.maximo_bytes == 5_000_000
        assert contrato.artefactos.retencion_dias == 7

    def test_un_tope_de_cero_ficheros_no_es_una_declaracion(self):
        """Declarar «produzco hasta cero ficheros» es decir dos cosas a la vez.

        Quien no produce ficheros no declara el campo; quien lo declara produce al menos uno. Sin
        esto hay dos formas de escribir lo mismo y el código tiene que tratar las dos.
        """
        from server.app.modules.redaccion.contracts.funciones import ArtefactosDeSalida

        with pytest.raises(ValidationError):
            ArtefactosDeSalida(maximo=0, maximo_bytes=1_000, retencion_dias=7)

    def test_la_retencion_no_puede_ser_indefinida(self):
        """La decisión de AUT.7, y es estrecha a propósito.

        No hay política general de retención en la plataforma (#162). Lo que sí se puede impedir
        aquí es que el silencio signifique «para siempre»: la retención se declara en días, y un
        contrato sin ese campo no valida. El día que haya política general, este campo pasa a
        tener un defecto — y eso **será una migración**, porque hay que rellenar lo guardado.
        """
        from server.app.modules.redaccion.contracts.funciones import ArtefactosDeSalida

        with pytest.raises(ValidationError):
            ArtefactosDeSalida(maximo=1, maximo_bytes=1_000)

    def test_y_tiene_un_techo_que_no_lo_pone_quien_declara(self):
        """Quien escribe el contrato no puede concederse retención perpetua por la vía de 99999.

        El tope lo pone la plataforma. Si no, «se declara» sería «se elige», y la decisión de
        arriba no aguantaría el primer contrato que quiera guardar un año.
        """
        from server.app.modules.redaccion.contracts.funciones import (
            ArtefactosDeSalida,
            RETENCION_MAXIMA_DIAS,
        )

        with pytest.raises(ValidationError):
            ArtefactosDeSalida(
                maximo=1, maximo_bytes=1_000, retencion_dias=RETENCION_MAXIMA_DIAS + 1
            )


class TestElArtefactoLlevaSuProcedencia:

    def test_nombre_tipo_tamano_y_hash(self):
        from server.app.modules.redaccion.pipelines.contracts import Artefacto

        a = Artefacto(
            nombre="subvenciones.xlsx",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            bytes=12_345,
            sha256="a" * 64,
        )

        assert a.nombre == "subvenciones.xlsx"
        assert a.bytes == 12_345
        assert a.sha256 == "a" * 64

    def test_el_hash_tiene_que_parecer_un_sha256(self):
        """Un hash de otra longitud no es un hash: es un campo rellenado para pasar."""
        from server.app.modules.redaccion.pipelines.contracts import Artefacto

        with pytest.raises(ValidationError):
            Artefacto(
                nombre="x.xlsx", media_type="application/octet-stream", bytes=1, sha256="abc"
            )

    def test_el_nombre_no_puede_llevar_ruta(self):
        """`../../etc/passwd` como «nombre» es el defecto clásico de una descarga.

        El nombre lo propone el guion de usuario, así que es entrada no confiable: se comprueba
        aquí, en el contrato, y no sólo en la capa que sirve la descarga — porque esa capa no es
        la única que va a usar este campo.
        """
        from server.app.modules.redaccion.pipelines.contracts import Artefacto

        for malo in ("../fuera.xlsx", "sub/dir.xlsx", "C:\\windows\\x.xlsx", ""):
            with pytest.raises(ValidationError):
                Artefacto(
                    nombre=malo,
                    media_type="application/octet-stream",
                    bytes=1,
                    sha256="a" * 64,
                )


class TestLaSalidaSigueSiendoCompatible:

    def test_un_extraction_result_sin_artefactos_sigue_valiendo(self):
        """Retrocompatible: todo lo que ya devuelve cifras no cambia."""
        from datetime import datetime, timezone

        from server.app.modules.redaccion.pipelines.contracts import (
            ExtractionProvenance,
            ExtractionResult,
        )

        r = ExtractionResult(
            provenance=ExtractionProvenance(
                pipeline_id="csv_table",
                source_ref="entrada.csv",
                extracted_at=datetime.now(timezone.utc),
            )
        )

        assert r.artefactos == []
