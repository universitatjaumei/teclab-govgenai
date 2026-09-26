"""Issue #159, parte 2 de 3 — ningún recorrido de una tabla que crece va sin acotar.

**El defecto, y por qué el techo de memoria no lo cierra.** El 2026-09-24 una consulta sin acotar
—la unión completa de documentos y fragmentos— dejó la VM 50 minutos sin responder. La #149 puso
techos, que convierten esa caída en un reinicio del contenedor; pero **nada impide escribir la
consulta**, y el reinicio sigue siendo una caída para quien esté preguntando.

**La trampa que hay que no perder, porque parecía el arreglo y no lo era.** `stream()` **no
basta** cuando lo que se recorre son objetos ORM: las filas llegan de una en una pero la sesión
las retiene todas en su mapa de identidad, y la memoria crece igual. Fue el segundo fallo del
detector de enlaces, el mismo día. Lo que funciona es **no pedir objetos**: columnas planas,
`func.count` en SQL, o un `LIMIT` con paginación.

**Qué comprueba esto y qué no.** Comprueba lo que está escrito, no lo que se ejecuta, así que no
sustituye a medir: es una red para que la forma peligrosa no vuelva a entrar sin que nadie lo
note. La salida es **declarar la razón**, no apagar el guardarraíl, porque hay recorridos
completos legítimos —un reembebido recorre el corpus entero a propósito— y lo que importa es que
estén dichos.
"""

from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2] / "app"

#: Las tablas que crecen sin techo. `hub_document_chunks` son 163.950 filas con un corpus de 334
#: documentos, y cada objeto ORM arrastra su vector de 3.072 dimensiones.
TABLAS_QUE_CRECEN = ("HubDocumentChunk", "HubInteraction", "HubCrawledPage")

#: Lo que hace segura una consulta sobre ellas.
SEÑALES_DE_ACOTADO = (".limit(", "func.count(", ".distinct(", "exists(")

#: El escape, que es una declaración y no un interruptor: quien recorre una tabla grande entera
#: escribe por qué a la vista de quien lea el código después.
MARCA = "recorrido-acotado:"

_SELECT_DE_OBJETO = re.compile(
    r"select\(\s*(" + "|".join(TABLAS_QUE_CRECEN) + r")\s*[,)]"
)


def _consultas_sin_acotar() -> list[str]:
    """`fichero:línea` de cada `select(<tabla grande>)` que no se ve acotado ni declarado."""
    hallazgos: list[str] = []
    for fichero in sorted(RAIZ.rglob("*.py")):
        lineas = fichero.read_text(encoding="utf-8").splitlines()
        for i, linea in enumerate(lineas):
            if not _SELECT_DE_OBJETO.search(linea):
                continue
            # La consulta se construye en varias líneas y el límite se añade a menudo bastante
            # después: en el recuperador va catorce líneas más abajo, tras los filtros
            # opcionales. Una ventana corta lo daba por no acotado, y un falso positivo es lo que
            # enseña a ignorar un guardarraíl.
            ventana = "\n".join(lineas[max(0, i - 6) : i + 25])
            if MARCA in ventana:
                continue
            if any(s in ventana for s in SEÑALES_DE_ACOTADO):
                continue
            hallazgos.append(f"{fichero.relative_to(RAIZ).as_posix()}:{i + 1}")
    return hallazgos


def test_ninguna_consulta_recorre_una_tabla_grande_sin_acotar() -> None:
    sin_acotar = _consultas_sin_acotar()

    assert not sin_acotar, (
        "Estas consultas piden objetos ORM de una tabla que crece, sin límite, sin contar en SQL "
        "y sin declarar por qué:\n  - " + "\n  - ".join(sin_acotar) + "\n\n"
        "Una de esa forma dejó la VM 50 minutos sin responder el 2026-09-24. El techo de memoria "
        "convierte esa caída en un reinicio, pero el reinicio sigue siendo una caída para quien "
        "esté preguntando.\n\n"
        "Y ojo con el arreglo que parece bueno y no lo es: `stream()` NO basta sobre objetos ORM, "
        "porque la sesión los retiene en su mapa de identidad y la memoria crece igual. Lo que "
        "funciona es no pedir objetos —columnas planas, `func.count`— o paginar con `limit`.\n\n"
        f"Si el recorrido completo es deliberado, escríbelo: un comentario con «{MARCA} <razón>» "
        "cerca de la consulta. La salida es declararlo, no quitar la comprobación."
    )


def test_el_guardarrail_sabe_encontrar_la_forma_que_busca(tmp_path: Path) -> None:
    """Un guardarraíl que recorre algo y no encuentra nada pasa en verde sin haber mirado.

    Ya pasó en este repositorio: un test que recorría un directorio inexistente llevaba días
    verde sin comprobar nada. Aquí se demuestra que el patrón casa con la forma peligrosa y **no**
    casa con la acotada ni con la declarada.
    """
    assert _SELECT_DE_OBJETO.search("select(HubDocumentChunk).where(x)")
    assert _SELECT_DE_OBJETO.search("select(HubDocumentChunk, similarity.label('s'))")
    # Pedir una columna no es pedir el objeto: eso es justamente el arreglo.
    assert not _SELECT_DE_OBJETO.search("select(HubDocumentChunk.document_id, ancora)")


def test_el_guardarrail_mira_donde_hay_codigo() -> None:
    """Y que la raíz exista, que es la otra forma silenciosa de no comprobar nada."""
    assert RAIZ.is_dir(), f"{RAIZ} no existe: este test no está mirando ningún código"
    assert len(list(RAIZ.rglob("*.py"))) > 100
