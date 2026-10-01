"""Unir, dividir y optimizar PDF sin que el documento salga (UTL.1, issue #190).

Deploy: edge.

Portado de `client_app/app/modules/utilities/pdf_tools.py` de AutomatIA (en el historial de git y
en `Documents/AutomatIA`). Las operaciones son las mismas; cambian tres cosas de fondo:

* **Bytes, no rutas.** Entra un PDF y sale un PDF, en memoria. El contenedor es efímero y la regla
  de portabilidad prohíbe escribir documentos de negocio en disco, y aquí además es el argumento
  entero: una utilidad que existe para que el documento no salga no puede dejar copias.
* **Lo que no existe se dice.** El legacy saltaba en silencio un rango o una página fuera del
  documento, y quien pedía las páginas 3-9 de uno de cinco recibía menos de lo pedido sin aviso.
* **El nivel 4 ya no linealiza.** MuPDF retiró la linealización y pedirla rompe el guardado
  (`Linearisation is no longer supported`). El nivel queda como el más agresivo de los que hay.

**Funciones síncronas a propósito.** MuPDF es CPU y no tiene API asíncrona; quien las llama desde
un endpoint las manda a un hilo con `asyncio.to_thread`, que es lo que mantiene libre el bucle.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import fitz

#: Lo que se puede guardar en cada nivel de optimización. Sin `linear`: ver el docstring.
_NIVELES: dict[int, dict] = {
    1: {"garbage": 1},
    2: {"garbage": 2, "deflate": True},
    3: {"garbage": 3, "deflate": True, "clean": True},
    4: {"garbage": 4, "deflate": True, "clean": True, "deflate_images": True, "deflate_fonts": True},
}

#: El guardado con optimización que usan unir y partir: el nivel 3, el recomendado.
_OPTIMIZADO = _NIVELES[3]


class PdfNoValido(ValueError):
    """El fichero no es un PDF con el que se pueda operar. El mensaje dice por qué."""


class OperacionNoValida(ValueError):
    """Lo que se pide no se puede hacer con este documento. El mensaje dice por qué."""


@dataclass(frozen=True)
class InfoPdf:
    paginas: int
    bytes: int


@dataclass(frozen=True)
class Optimizado:
    datos: bytes
    bytes_original: int
    bytes_final: int


def _abrir(datos: bytes) -> fitz.Document:
    try:
        doc = fitz.open(stream=datos, filetype="pdf")
    except Exception as fallo:  # noqa: BLE001 — MuPDF lanza tipos propios; el motivo va en el mensaje
        raise PdfNoValido(f"no es un PDF que se pueda leer: {fallo}") from fallo
    if doc.needs_pass:
        doc.close()
        raise PdfNoValido(
            "el PDF está protegido con contraseña: quítasela antes, porque sin ella no se pueden "
            "leer sus páginas"
        )
    if doc.page_count == 0:
        doc.close()
        raise PdfNoValido("el PDF no tiene páginas")
    return doc


def _guardar(doc: fitz.Document, optimizar: bool) -> bytes:
    return doc.tobytes(**_OPTIMIZADO) if optimizar else doc.tobytes()


def info(datos: bytes) -> InfoPdf:
    with _abrir(datos) as doc:
        return InfoPdf(paginas=doc.page_count, bytes=len(datos))


def unir(documentos: list[bytes], *, optimizar: bool = True) -> bytes:
    """Une los PDF en el orden dado."""
    if len(documentos) < 2:
        raise OperacionNoValida("para unir hacen falta al menos dos PDF")
    salida = fitz.open()
    try:
        for i, datos in enumerate(documentos, 1):
            try:
                doc = _abrir(datos)
            except PdfNoValido as fallo:
                raise PdfNoValido(f"el fichero {i}: {fallo}") from fallo
            with doc:
                salida.insert_pdf(doc)
        return _guardar(salida, optimizar)
    finally:
        salida.close()


def leer_rangos(texto: str) -> list[tuple[int, int]]:
    """`1-3, 5, 8-10` → `[(1, 3), (5, 5), (8, 10)]`. Páginas empezando en 1, como se ven.

    Es como lo escribe una persona en un campo de texto. Lo que no se entiende se dice, en vez de
    interpretarlo de una forma que quien lo escribió no esperaba.
    """
    rangos: list[tuple[int, int]] = []
    for trozo in (texto or "").split(","):
        trozo = trozo.strip()
        if not trozo:
            continue
        casado = re.fullmatch(r"(\d+)\s*(?:-\s*(\d+))?", trozo)
        if not casado:
            raise OperacionNoValida(f"«{trozo}» no es una página ni un rango (por ejemplo, 3 o 1-4)")
        inicio = int(casado.group(1))
        fin = int(casado.group(2)) if casado.group(2) else inicio
        if inicio < 1 or fin < inicio:
            raise OperacionNoValida(f"«{trozo}» no es un rango válido: empieza en 1 y va hacia delante")
        rangos.append((inicio, fin))
    if not rangos:
        raise OperacionNoValida("no se ha indicado ninguna página ni rango")
    return rangos


def _comprobar_rango(inicio: int, fin: int, total: int) -> None:
    if inicio < 1 or fin > total or inicio > fin:
        raise OperacionNoValida(
            f"el rango {inicio}-{fin} no cabe: el documento tiene {total} páginas"
        )


def partir_por_rangos(
    datos: bytes, rangos: list[tuple[int, int]], *, nombre_base: str, optimizar: bool = True
) -> list[tuple[str, bytes]]:
    """Un fichero por rango, con el rango en el nombre."""
    with _abrir(datos) as doc:
        for inicio, fin in rangos:
            _comprobar_rango(inicio, fin, doc.page_count)
        partes = []
        for inicio, fin in rangos:
            salida = fitz.open()
            try:
                salida.insert_pdf(doc, from_page=inicio - 1, to_page=fin - 1)
                partes.append((f"{nombre_base}_p{inicio}-{fin}.pdf", _guardar(salida, optimizar)))
            finally:
                salida.close()
        return partes


def extraer_paginas(
    datos: bytes, paginas: list[int], *, nombre_base: str, optimizar: bool = True
) -> tuple[str, bytes]:
    """Las páginas pedidas, en orden y sin repetir, en un solo fichero."""
    with _abrir(datos) as doc:
        for p in paginas:
            _comprobar_rango(p, p, doc.page_count)
        ordenadas = sorted(set(paginas))
        salida = fitz.open()
        try:
            for p in ordenadas:
                salida.insert_pdf(doc, from_page=p - 1, to_page=p - 1)
            if len(ordenadas) <= 5:
                etiqueta = "-".join(map(str, ordenadas))
            else:
                etiqueta = f"{ordenadas[0]}-etc-{ordenadas[-1]}"
            return f"{nombre_base}_paginas_{etiqueta}.pdf", _guardar(salida, optimizar)
        finally:
            salida.close()


def una_por_pagina(
    datos: bytes, *, nombre_base: str, optimizar: bool = True
) -> list[tuple[str, bytes]]:
    """Un fichero por página, con ceros delante para que ordenen bien."""
    with _abrir(datos) as doc:
        cifras = len(str(doc.page_count))
        partes = []
        for i in range(doc.page_count):
            salida = fitz.open()
            try:
                salida.insert_pdf(doc, from_page=i, to_page=i)
                partes.append(
                    (f"{nombre_base}_pagina_{str(i + 1).zfill(cifras)}.pdf", _guardar(salida, optimizar))
                )
            finally:
                salida.close()
        return partes


def optimizar(datos: bytes, *, nivel: int = 3) -> Optimizado:
    """Reescribe el PDF con el nivel pedido: 1 limpieza básica … 4 el más agresivo."""
    if nivel not in _NIVELES:
        raise OperacionNoValida(f"el nivel {nivel} no existe: van del 1 al {max(_NIVELES)}")
    with _abrir(datos) as doc:
        resultado = doc.tobytes(**_NIVELES[nivel])
    return Optimizado(datos=resultado, bytes_original=len(datos), bytes_final=len(resultado))
