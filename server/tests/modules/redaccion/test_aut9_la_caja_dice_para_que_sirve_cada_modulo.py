"""AUT.9 (issue #119) — la caja de herramientas dice **para qué** sirve cada módulo, no sólo cuál.

**El problema que resuelve.** Desde AUT.4 el guion de extracción se escribe fuera —una persona
con Claude o con Gemini— y luego se importa, se declara o se ejecuta desde la plataforma. Ese
agente pide `reglas_de_auditoria` antes de escribir, y hasta ahora recibía **diecisiete nombres
en una lista plana**. Con eso elige entre `fitz` y `pdfplumber` a cara o cruz.

Y no son alternativas. En la aplicación anterior el módulo de extracción **leía con las dos y
componía las dos lecturas** antes de dárselas al modelo, para que tuviera más de donde agarrarse
al escribir el guion; según cómo esté estructurado el documento interesa una o la otra. Eso es
conocimiento de la casa, y en una lista de nombres no cabe.

**Por qué en el contrato y no en un `.md`.** Es la misma razón por la que las reglas viven en el
código: el agente que escribe fuera lee la API, no el Markdown. Y la herramienta MCP es un
pasamuros —devuelve tal cual lo que responde el endpoint—, así que lo que entra aquí le llega sin
tocar el paquete que ya está repartido.

**La licencia va con cada módulo por un motivo concreto**, y es el que destapó la pregunta:
`fitz` es PyMuPDF, que es **AGPL-3.0** o licencia comercial de Artifex. A la plataforma no le
afecta —ya es AGPL-3.0-or-later—, pero **sí afecta al guion escrito fuera**: si ese código acaba
en un producto que no es AGPL, la pregunta aparece allí. Quien lo escribe tiene que poder saberlo
antes, no después, y si el documento se deja leer con `pdfplumber` la pregunta no se plantea.
"""
from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def caja():
    from server.app.modules.redaccion.services.script_auditor import caja_de_herramientas

    return caja_de_herramientas()


class TestCadaModuloPermitidoSeExplica:

    def test_no_queda_ninguno_sin_ficha(self, caja):
        """Sin esto, el siguiente módulo que se apruebe llega mudo y nadie se entera.

        Es el mismo defecto que AUT.9 acababa de cazar con `fitz`: no que estuviera mal, sino
        que **nada comprobaba** que estuviera.
        """
        explicados = {m.modulo for m in caja.modulos}

        faltan = sorted(set(caja.modulos_permitidos) - explicados)

        assert not faltan, f"módulos permitidos sin ficha en la caja: {faltan}"

    def test_y_no_se_explica_nada_que_no_este_permitido(self, caja):
        """Una ficha sobrante ofrece una librería que el auditor rechazaría."""
        permitidos = set(caja.modulos_permitidos)

        sobrantes = sorted({m.modulo for m in caja.modulos} - permitidos)

        assert not sobrantes, f"fichas de módulos que no están en la lista blanca: {sobrantes}"

    def test_cada_ficha_dice_para_que_sirve(self, caja):
        mudas = sorted(m.modulo for m in caja.modulos if not (m.para or "").strip())

        assert not mudas, f"fichas sin «para qué sirve»: {mudas}"


class TestElNombreConElQueSeInstala:
    """`import fitz` se instala como `pymupdf`, y quien escribe fuera necesita el segundo."""

    def test_fitz_se_instala_como_pymupdf(self, caja):
        ficha = next(m for m in caja.modulos if m.modulo == "fitz")

        assert ficha.instala == "pymupdf"

    def test_docx_se_instala_como_python_docx(self, caja):
        ficha = next(m for m in caja.modulos if m.modulo == "docx")

        assert ficha.instala == "python-docx"

    def test_los_de_la_biblioteca_estandar_no_se_instalan(self, caja):
        """`None` y no una cadena vacía: «no hay nada que instalar» y «no lo sé» no son lo mismo.

        Con `""` quien escriba fuera se quedaría mirando un `pip install ` sin argumento.
        """
        ficha = next(m for m in caja.modulos if m.modulo == "json")

        assert ficha.instala is None


class TestLaLicenciaViajaConElModulo:

    def test_fitz_avisa_de_que_arrastra_copyleft(self, caja):
        ficha = next(m for m in caja.modulos if m.modulo == "fitz")

        assert ficha.copyleft is True
        assert "AGPL" in ficha.licencia

    def test_y_es_el_unico_de_los_de_terceros(self, caja):
        """Si lo fueran todos, el aviso no distinguiría nada y se ignoraría."""
        con_copyleft = sorted(m.modulo for m in caja.modulos if m.copyleft)

        assert con_copyleft == ["fitz"]

    def test_pdfplumber_es_la_salida_sin_copyleft_para_lo_mismo(self, caja):
        """El aviso sólo es accionable si hay alternativa, y para PDF la hay."""
        ficha = next(m for m in caja.modulos if m.modulo == "pdfplumber")

        assert ficha.copyleft is False
        assert ficha.licencia == "MIT"


class TestLasDosLecturasDePdfSiguenLasDos:
    """El día que alguien «simplifique» quitando una, esto se pone rojo y dice por qué."""

    def test_estan_las_dos_y_las_dos_hablan_de_pdf(self, caja):
        pdf = {m.modulo: m.para for m in caja.modulos if m.modulo in ("fitz", "pdfplumber")}

        assert set(pdf) == {"fitz", "pdfplumber"}
        for modulo, para in pdf.items():
            assert "PDF" in para, f"la ficha de {modulo} no dice que sea para PDF: «{para}»"


class TestLaVersionDeLaCajaCubreLasFichas:

    def test_cambiar_una_ficha_cambia_la_version(self, monkeypatch):
        """`version_auditor` sirve para saber si la caja cambió desde la última consulta.

        Si las fichas quedaran fuera del hash, un agente que cachea por esa versión seguiría
        escribiendo con la explicación vieja —y con la licencia vieja— sin enterarse.
        """
        from server.app.modules.redaccion.services import script_auditor

        antes = script_auditor.caja_de_herramientas().version_auditor

        cambiadas = tuple(
            m.model_copy(update={"para": "otra cosa"}) if m.modulo == "fitz" else m
            for m in script_auditor.CATALOGO_DE_MODULOS
        )
        monkeypatch.setattr(script_auditor, "CATALOGO_DE_MODULOS", cambiadas)

        assert script_auditor.caja_de_herramientas().version_auditor != antes
