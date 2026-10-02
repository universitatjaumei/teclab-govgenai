"""UTL.1 (issue #190) — unir, dividir y optimizar PDF dentro de casa.

**Por qué existe.** Hoy se hace con aplicaciones online que no aseguran el RGPD: alguien que tiene
que partir un expediente o juntar cinco anexos busca «unir PDF» y sube el documento a un servicio
del que no sabe dónde procesa ni cuánto conserva. La operación es trivial y no necesita salir de
la máquina; lo que faltaba es que existiera aquí.

Portado de `client_app/app/modules/utilities/pdf_tools.py` de AutomatIA, con tres cambios de
fondo:

* **Trabaja sobre bytes y no sobre rutas.** El contenedor es efímero y la regla de portabilidad
  prohíbe escribir documentos de negocio en disco: entra un PDF, sale un PDF, y no queda nada.
* **Un rango o una página que no existen se dicen.** El legacy los saltaba en silencio, y quien
  pedía las páginas 3-9 de un documento de cinco recibía un fichero con menos de lo pedido y
  ninguna explicación.
* **El nivel «agresivo» ya no linealiza.** MuPDF retiró la linealización
  (`Linearisation is no longer supported`), y pedirla rompe el guardado.
"""
from __future__ import annotations

import pytest


def _pdf(paginas: int, texto: str = "pagina") -> bytes:
    import pymupdf as fitz

    doc = fitz.open()
    for i in range(paginas):
        pagina = doc.new_page()
        pagina.insert_text((72, 72), f"{texto} {i + 1}")
    datos = doc.tobytes()
    doc.close()
    return datos


def _paginas(datos: bytes) -> int:
    import pymupdf as fitz

    with fitz.open(stream=datos, filetype="pdf") as doc:
        return doc.page_count


def _texto(datos: bytes) -> list[str]:
    import pymupdf as fitz

    with fitz.open(stream=datos, filetype="pdf") as doc:
        return [p.get_text().strip() for p in doc]


class TestValidar:

    def test_un_pdf_dice_cuantas_paginas_tiene(self):
        from server.app.modules.utilidades.pdf import info

        assert info(_pdf(3)).paginas == 3

    def test_lo_que_no_es_un_pdf_se_rechaza_con_su_motivo(self):
        from server.app.modules.utilidades.pdf import PdfNoValido, info

        with pytest.raises(PdfNoValido):
            info(b"esto no es un pdf")

    def test_un_pdf_con_contrasena_se_dice(self):
        """No se puede operar sobre él, y el error tiene que decir por qué."""
        import pymupdf as fitz

        from server.app.modules.utilidades.pdf import PdfNoValido, info

        doc = fitz.open()
        doc.new_page()
        protegido = doc.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="x", owner_pw="y")

        with pytest.raises(PdfNoValido, match="contraseña"):
            info(protegido)


class TestUnir:

    def test_une_en_el_orden_dado(self):
        from server.app.modules.utilidades.pdf import unir

        resultado = unir([_pdf(2, "a"), _pdf(1, "b")])

        assert _texto(resultado) == ["a 1", "a 2", "b 1"]

    def test_hacen_falta_al_menos_dos(self):
        from server.app.modules.utilidades.pdf import OperacionNoValida, unir

        with pytest.raises(OperacionNoValida):
            unir([_pdf(1)])


class TestPartir:

    def test_por_rangos_cada_rango_es_un_fichero(self):
        from server.app.modules.utilidades.pdf import partir_por_rangos

        partes = partir_por_rangos(_pdf(5), [(1, 2), (4, 5)], nombre_base="exp")

        assert [n for n, _ in partes] == ["exp_p1-2.pdf", "exp_p4-5.pdf"]
        assert [_paginas(d) for _, d in partes] == [2, 2]

    def test_un_rango_fuera_del_documento_se_dice_y_no_se_salta(self):
        """El legacy lo saltaba en silencio: se pedía 3-9 de cinco y llegaba menos sin aviso."""
        from server.app.modules.utilidades.pdf import OperacionNoValida, partir_por_rangos

        with pytest.raises(OperacionNoValida, match="5 páginas"):
            partir_por_rangos(_pdf(5), [(3, 9)], nombre_base="exp")

    def test_extraer_paginas_sueltas_en_el_orden_pedido(self):
        from server.app.modules.utilidades.pdf import extraer_paginas

        nombre, datos = extraer_paginas(_pdf(6, "p"), [5, 1, 3], nombre_base="exp")

        assert _texto(datos) == ["p 1", "p 3", "p 5"]
        assert nombre == "exp_paginas_1-3-5.pdf"

    def test_una_por_pagina_con_ceros_para_que_ordenen(self):
        from server.app.modules.utilidades.pdf import una_por_pagina

        partes = una_por_pagina(_pdf(12), nombre_base="exp")

        assert partes[0][0] == "exp_pagina_01.pdf"
        assert partes[-1][0] == "exp_pagina_12.pdf"
        assert all(_paginas(d) == 1 for _, d in partes)


class TestLosRangosQueEscribeLaPersona:
    """`1-3, 5, 8-10` es como lo escribe alguien en un campo de texto."""

    def test_se_leen_rangos_y_paginas_sueltas(self):
        from server.app.modules.utilidades.pdf import leer_rangos

        assert leer_rangos("1-3, 5, 8-10") == [(1, 3), (5, 5), (8, 10)]

    @pytest.mark.parametrize("malo", ["", "3-1", "a-b", "0-2", "1-"])
    def test_lo_que_no_se_entiende_se_dice(self, malo):
        from server.app.modules.utilidades.pdf import OperacionNoValida, leer_rangos

        with pytest.raises(OperacionNoValida):
            leer_rangos(malo)


class TestOptimizar:

    @pytest.mark.parametrize("nivel", [1, 2, 3, 4])
    def test_los_cuatro_niveles_producen_un_pdf_valido(self, nivel):
        """El 4 incluido: linealizar ya no se puede, y pedirlo rompía el guardado."""
        from server.app.modules.utilidades.pdf import optimizar

        resultado = optimizar(_pdf(3), nivel=nivel)

        assert _paginas(resultado.datos) == 3
        assert resultado.bytes_original > 0 and resultado.bytes_final > 0

    def test_un_nivel_que_no_existe_se_dice(self):
        from server.app.modules.utilidades.pdf import OperacionNoValida, optimizar

        with pytest.raises(OperacionNoValida):
            optimizar(_pdf(1), nivel=7)
