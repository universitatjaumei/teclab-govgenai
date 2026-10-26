"""Advertencia de vigencia no validada (VIS.3). Deploy: edge.

El riesgo nº1 del corpus, medido en `INFORME_MATERIES_I_METADADES_AGENTS.md`: **312 de 314
fichas declaran «vigent?»**. Citar una de ellas sin decirlo es afirmar como vigente algo que
nadie ha comprobado.

Por qué el aviso no vive en el system prompt: una instruccion al modelo se cumple casi
siempre, y «casi siempre» no es una garantia cuando lo que esta en juego es si una norma
rige. El flag lo pone la capa de recuperacion —que es la que ve el dato— y el texto lo
anade el CoreGraph despues de generar la respuesta.

Un documento necesita aviso si NO ha pasado revision humana de vigencia
(`vigencia_validada_el IS NULL`). El catalogo real trae valores como 'vigent?', que es
precisamente el caso que hay que advertir, y entra por aqui: sin fecha de validacion, se avisa.

ACT.4 quito la segunda rama —«o si su estado no es exactamente vigent»—. Tenia sentido mientras
`no_vigent` y `derogat` llegaban al modelo; ya no llegan, porque `metadata_filter` los excluye.
Lo que queda es la unica pregunta que el aviso responde de verdad: ¿ha confirmado una persona
que esto rige? Hoy son 63 fichas de 290 las que no.
"""
from __future__ import annotations

from typing import Any

ESTAT_VIGENT = "vigent"
#: ACT.4 — estados de NORMA que afirman que ya no rige. Es una lista de exclusion y no una de
#: admision, y la diferencia importa: un documento SIN `estat_vigencia` no es una norma que se
#: haya dejado de aplicar, es un documento que no tiene ese ciclo de vida —una pagina rastreada,
#: un PDF que alguien sube para preguntarle cosas—. Exigir `= 'vigent'` los borraba a todos del
#: indice, y con ellos el corpus entero de cualquier chatbot que no se alimente del corpus
#: curado. Lo destapo la suite: 52 tests en rojo.
#:
#: `vigent?` y `parcialment_derogat` se quedan DENTRO, con el aviso de vigencia no validada: el
#: primero es la duda del catalogo original y el segundo dice que una parte SI rige.
ESTATS_QUE_NO_RIGEN = ("no_vigent", "futur", "derogat")
#: Estados de ARTICULO que no rigen dentro de una norma vigente. No son estados de
#: norma: `derogat` dejo de serlo cuando la derogacion paso a ser una CAUSA y la derogacion
#: parcial paso a ser `vigent` con articulos marcados.
ESTATS_DE_ARTICULO_QUE_NO_RIGEN = ("suprimit", "derogat")

AVISO_VIGENCIA_NO_VALIDADA = (
    "Aviso: la vigencia de la normativa citada no esta validada, asi que puede haber sido "
    "modificada o derogada. Confirmalo en la fuente oficial antes de actuar."
)

CLAVE_METADATO = "vigencia_no_validada"


def vigencia_no_validada(
    estat_vigencia: str | None,  # noqa: ARG001 — ACT.4 retiró la rama del estado; la firma la comparten los llamantes
    vigencia_validada_el: Any | None,
) -> bool:
    """True si el documento no puede presentarse como vigente sin advertirlo.

    ACT.4 — **la rama del estado desaparece.** Antes tambien avisaba cuando el estado no era
    exactamente `vigent`, y eso tenia sentido mientras `no_vigent` y `derogat` llegaban al
    modelo. Ya no llegan: `metadata_filter` solo recupera `vigent`. Lo que queda es la unica
    pregunta que el aviso responde de verdad — **¿ha confirmado una persona que esto rige?**—,
    y hoy son 63 fichas de 290 las que no.

    El catalogo original trae `vigent?`, que entra por aqui: sin fecha de validacion, se
    advierte, que es exactamente lo que ese interrogante significa.
    """
    return vigencia_validada_el is None


def marca_de_vigencia(documento: Any) -> dict[str, bool]:
    """Metadato listo para incrustar en un `Source` o un `EvidenceItem`."""
    return {
        CLAVE_METADATO: vigencia_no_validada(
            getattr(documento, "estat_vigencia", None),
            getattr(documento, "vigencia_validada_el", None),
        )
    }


CLASE_DESPLACAT = "desplacat"


def _entrada_de_desplazamiento(documento: Any, ancora: str | None) -> dict | None:
    """La entrada de `desplacat_per` que corresponde a esta ancla, si la hay."""
    if documento is None or not ancora:
        return None
    metadatos = getattr(documento, "doc_metadata", None) or {}
    for entrada in metadatos.get("desplacat_per") or ():
        if isinstance(entrada, dict) and entrada.get("ancora") == ancora:
            return entrada
    return None


def aviso_de_desplazamiento(entrada: dict) -> str:
    """Redacta el aviso a partir de lo que declara el corpus. No añade juicio propio."""
    quien = entrada.get("desplacat_per") or {}
    partes = [
        "AVISO DE VIGENCIA: el texto de este articulo sigue aprobado y sin modificar, pero "
        "su contenido esta DESPLAZADO por una norma posterior, asi que no se aplica tal "
        "como se lee."
    ]
    apartado = entrada.get("apartat_afectat")
    if apartado:
        partes.append(f"Apartado afectado: {apartado}.")

    norma = quien.get("norma") or quien.get("id_norma")
    if norma:
        referencia = f"Lo desplaza: {norma}"
        if quien.get("ancora"):
            referencia += f" ({quien['ancora']}"
            if quien.get("apartat"):
                referencia += f", apartado {quien['apartat']}"
            referencia += ")"
        if quien.get("data"):
            referencia += f", de {quien['data']}"
        partes.append(referencia + ".")

    if entrada.get("motiu"):
        partes.append(f"Motivo: {entrada['motiu']}")
    return " ".join(partes)


CLAVE_TRANSITORIA = "vigencia_transitoria"


def aviso_de_vigencia_transitoria(bloque: dict) -> str:
    """El aviso de una norma SUSTITUIDA que sigue rigiendo para un colectivo.

    El caso lo trajo `PRG-003`: el Programa de suport al PDI de 2024 lo sustituye sin clausula
    derogatoria, pero su disposicion transitoria primera mantiene la reduccion por sexenios del
    de 2021 hasta el curso 2026/2027 para quien tuviera un unico sexenni viu. **Las dos rigen**,
    asi que las dos son `vigent` y las dos se recuperan; lo que hace falta es que quien lea el
    articulo sepa a QUIEN y HASTA CUANDO se le aplica.

    Se redacta desde lo que declara el corpus y no se anade juicio propio, igual que el aviso de
    desplazamiento.
    """
    quien = bloque.get("per") or {}
    partes = ["AVISO DE VIGENCIA: esta norma ha sido SUSTITUIDA, pero este apartado sigue "
              "aplicandose transitoriamente."]
    norma = quien.get("norma") or quien.get("id_norma")
    if norma:
        referencia = f"La sustituye: {norma}"
        if quien.get("id_norma") and quien.get("norma"):
            referencia += f" ({quien['id_norma']})"
        if quien.get("ancora"):
            referencia += f", {quien['ancora']}"
        if quien.get("data"):
            referencia += f", de {quien['data']}"
        partes.append(referencia + ".")
    if bloque.get("abast"):
        partes.append(f"Solo se aplica a: {bloque['abast']}.")
    if bloque.get("fins"):
        partes.append(f"Hasta el {bloque['fins']}.")
    if bloque.get("regim"):
        partes.append(f"Regimen que se mantiene: {bloque['regim']}.")
    return " ".join(partes)


def _transitoria_aplicable(documento: Any, ancora: str | None) -> dict | None:
    """El bloque de vigencia transitoria que le toca a esta ancla, si le toca.

    **`ancores_vigents` es opcional, y eso es una decision.** Si la norma tiene anclas, se dice
    que apartados continuan y el aviso solo acompana a esos. Si no las tiene —es el caso de
    `PRG-003`, cuyas secciones no van numeradas— la declaracion vale a nivel de DOCUMENTO: el
    aviso acompana a todos sus fragmentos y se cita el documento entero, que es la regla general
    del corpus. Menos preciso, pero cierto.
    """
    if documento is None:
        return None
    bloque = (getattr(documento, "doc_metadata", None) or {}).get(CLAVE_TRANSITORIA)
    if not isinstance(bloque, dict):
        return None
    ancores = bloque.get("ancores_vigents")
    if ancores and ancora not in ancores:
        return None
    return bloque


def hidratar_avisos_de_vigencia(
    texto: str, documento: Any, metadatos_del_fragmento: dict | None
) -> str:
    """Antepone al fragmento los avisos de vigencia que le correspondan.

    Dos, y se acumulan: el de DESPLAZAMIENTO (el contenido del articulo no se aplica porque una
    norma superior lo desplaza) y el de VIGENCIA TRANSITORIA (la norma esta sustituida pero este
    apartado sigue rigiendo para alguien). Son cosas distintas y un articulo puede llevar las
    dos.
    """
    texto = hidratar_desplazamiento(texto, documento, metadatos_del_fragmento)
    metadatos = metadatos_del_fragmento or {}
    bloque = _transitoria_aplicable(documento, metadatos.get("ancora"))
    if bloque is None:
        return texto
    return f"{aviso_de_vigencia_transitoria(bloque)}\n\n{texto}"


def hidratar_desplazamiento(
    texto: str, documento: Any, metadatos_del_fragmento: dict | None
) -> str:
    """Antepone el aviso de desplazamiento al texto del fragmento, si le corresponde.

    **Por qué aquí y no en el troceado** (las tres alternativas se evaluaron):

    - La nota `::: nota-vigencia` del corpus cae en UNO de los trozos del artículo. Hidratar
      al montar la evidencia no depende de dónde cayó; las demás soluciones sí.
    - La nota vive en un solo sitio. Reescribirla no obliga a reindexar 290 fragmentos.
    - Propagarla al trocear metería 400-700 caracteres en cada trozo, **y esos caracteres
      entrarían al embedding**: cambiaría el vector de todo artículo desplazado.
    - `parent_child` sólo ayudaría si la respuesta se hace con el padre, y cambiaría el
      troceado de todo el corpus para resolver el caso de 45 documentos.

    Lo que NO resuelve nada, y por eso no se hizo: añadir `desplacat` a
    `ESTADOS_CONSOLIDACION`. Saber el estado no es mostrar el aviso, y hoy nadie consume
    `estat`.
    """
    metadatos = metadatos_del_fragmento or {}
    if CLASE_DESPLACAT not in (metadatos.get("classes") or ()):
        return texto
    entrada = _entrada_de_desplazamiento(documento, metadatos.get("ancora"))
    if entrada is None:
        return texto
    return f"{aviso_de_desplazamiento(entrada)}\n\n{texto}"


def aviso_para(items: list[Any]) -> str | None:
    """Bloque de aviso para la respuesta, o None si no hay nada que advertir.

    Nombra los documentos afectados: un aviso genérico no dice de qué norma se duda, y el
    usuario necesita saber cuál de las citas tiene que confirmar.
    """
    afectados = [
        (getattr(i, "title", None) or getattr(i, "source_id", "?"))
        for i in items
        if (getattr(i, "metadata", None) or {}).get(CLAVE_METADATO)
    ]
    if not afectados:
        return None
    unicos = list(dict.fromkeys(afectados))
    return f"---\n{AVISO_VIGENCIA_NO_VALIDADA}\nDocumentos afectados: {', '.join(unicos)}."
