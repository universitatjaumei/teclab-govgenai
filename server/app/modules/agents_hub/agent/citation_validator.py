"""Validacion post-generacion: garantiza que la respuesta cite cuando debe."""

import re
import unicodedata

from server.app.core.llm_text import texto_de
from server.app.modules.agents_hub.services.retrieval.citations import ANCLAS_CITABLES

# Issue #148 — los dos límites no son estética: quitan un coste **cuadrático**.
#
# Sin ellos, el motor arranca en cada `[` del texto y, si no encuentra cierre, escanea hasta el
# final: con *m* corchetes sobre *n* caracteres, O(n·m). Medido sobre un texto de sólo corchetes,
# antes y después de acotar:
#
#     n=16.000    1.358 ms → 133 ms          n=64.000   32.671 ms → 515 ms
#
# Es decir, **32 segundos** en el peor caso de 64.000 caracteres, que es una respuesta larga del
# modelo. Doblar la entrada multiplicaba el tiempo por cuatro.
#
# **500 para el título** porque ninguno real se acerca —el más largo del corpus, con fecha y
# órgano, no llega a 200— y **2.048 para la URL** porque es lo que cabe en `source_url`, que es
# `String(2048)`: una más larga no está en la base y no puede ser una cita recuperada.
#
# El intercambio está escrito y probado en `test_issue148_…`: un enlace que pase del límite deja
# de contar como cita. No existe en ninguna respuesta real, y el precio de no acotarlo es que el
# proceso se quede segundos leyendo corchetes.
_MD_LINK = re.compile(r"\[([^\]]{1,500})\]\(([^)]{1,2048})\)")
# Un corchete que NO va seguido de parentesis: la forma en la que el modelo cita cuando se
# deja la URL. Se excluye el salto de linea para no tragarse dos citas de parrafos distintos.
# El mismo límite y por la misma razón (#148). Ésta era la peor de las dos: 68 segundos sobre
# 64.000 caracteres, frente a 898 ms acotada.
_CORCHETE_SIN_ENLACE = re.compile(r"\[([^\]\n]{1,500})\](?!\()")

NO_CITATION_FALLBACK = (
    "No tengo informacion suficiente en los documentos disponibles para responder a "
    "esta pregunta con citas verificables. Podrias reformular o proporcionar mas contexto?"
)


# #336 — una dirección escrita en el texto de la evidencia. Se corta en lo que no puede ir en
# una URL sin escapar, y se le quita la puntuación que la cierra en la frase.
_URL_EN_EL_TEXTO = re.compile(r"https?://[^\s<>\"'()\[\]]{1,2040}")


def _anclas_leidas(sources: list) -> set[str]:
    """`página#ancla` por cada ancla que la estrategia declara citable en esa evidencia.

    Es lo que el modelo tuvo delante: en contexto largo, el documento entero con sus
    encabezados. Un ancla que no está aquí sigue bajando al documento (HIB.D).
    """
    return {
        f"{_sin_fragmento(url)}#{ancla}"
        for s in sources
        if (url := _url_de(s))
        for ancla in ((getattr(s, "metadata", None) or {}).get(ANCLAS_CITABLES) or ())
    }


def _urls_escritas(sources: list) -> set[str]:
    """Las direcciones que aparecen tal cual en el texto entregado (#336).

    Enlazarlas no es inventar: el modelo las copió de la evidencia. Pero no cuentan como cita
    del fundamento —una aplicación no es una norma—, así que no bastan para cumplir.
    """
    return {
        u.rstrip(".,;:")
        for s in sources
        for u in _URL_EN_EL_TEXTO.findall(str(getattr(s, "content", "") or ""))
    }


def has_valid_citations(response_text: str, allowed_urls: set[str]) -> bool:
    """True si la respuesta contiene al menos una cita cuyo URL este en allowed_urls."""
    for _title, url in _MD_LINK.findall(response_text):
        if url.strip() in allowed_urls:
            return True
    return False


def _url_de(evidencia) -> str | None:
    """URL de un EvidenceItem (`source_url`).

    RAG.2 unificó el contrato de evidencia en EvidenceItem; se acepta también `url`
    porque los tools de lectura y las estrategias de `services/retrieval/` siguen
    hablando ese dialecto por debajo de los pipelines.
    """
    return getattr(evidencia, "source_url", None) or getattr(evidencia, "url", None)


def _sin_fragmento(url: str) -> str:
    return url.split("#", 1)[0]


def degradar_anclas(response_text: str, allowed: set[str]) -> str:
    """Reescribe al documento las citas cuyo ancla no es la admitida.

    Medido el 2026-08-24: dos de cada ocho descartes citaban el documento correcto con otra
    ancla —`#art-1.7.a` cuando el fragmento venia anclado en `#art-1`, y `#Primer` cuando el
    fragmento no traia ancla—. Tirar la respuesta entera por eso no protege de nada: el
    documento SI se recupero y SI se leyo.

    Degradar al documento pierde precision y no veracidad: el lector aterriza en la portada
    de la norma en vez de en el articulo. Componer un ancla que nadie leyo, en cambio, seria
    fabricar un puntero, y eso es justo lo que este modulo existe para impedir.
    """
    documentos = {_sin_fragmento(u) for u in allowed}

    def _reemplazo(coincidencia: re.Match) -> str:
        titulo, url = coincidencia.group(1), coincidencia.group(2).strip()
        if url in allowed:
            return coincidencia.group(0)
        documento = _sin_fragmento(url)
        if documento in documentos:
            return f"[{titulo}]({documento})"
        return coincidencia.group(0)

    return _MD_LINK.sub(_reemplazo, response_text)


def _normalizar(texto: str) -> str:
    """Minusculas, sin tildes y con los espacios colapsados, para comparar titulos.

    El corpus escribe «creditos» sin tilde y «máster» con ella en el mismo titulo, asi que
    comparar en crudo fallaria por como se transcribio el original, que no es lo que se
    quiere medir.
    """
    sin_tildes = (
        unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    )
    return re.sub(r"\s+", " ", sin_tildes).strip().lower()


def enlazar_citas_en_prosa(response_text: str, sources: list) -> str:
    """Pone la URL a las citas que nombran bien una norma recuperada pero no la enlazan.

    HIB.0. Medido con la sonda el 2026-08-26 sobre SGE-01: el modelo respondio correcto y con
    detalle y cito asi —«[Reglamento sobre reconocimiento y transferencia de creditos...,
    ANEXO II, apartado 3]»—, corchetes sin URL. No es un enlace markdown, el contrato no
    encontraba ninguna cita valida y **tiraba la respuesta entera**. RES.5 previo esta forma y
    aplazo el enlazado determinista porque midio cero casos en 85 respuestas; ese cero caduco.

    **Esto no amplia lo citable, que es la garantia del contrato.** El titulo se busca
    unicamente entre los documentos RECUPERADOS: una norma que el texto menciona pero que no
    se entrego al modelo no se enlaza aqui ni en ningun sitio. Y el enlace lo escribe el
    codigo desde `source_url`, no el modelo: no hay puntero que se pueda inventar.

    El detalle que va detras del titulo —«ANEXO II, apartado 3»— se conserva dentro del texto
    del enlace: es informacion que el lector necesita y que el ancla del documento no da.
    """
    candidatos = [
        (_normalizar(titulo), url)
        for titulo, url in (
            (getattr(s, "title", None), _url_de(s)) for s in sources
        )
        if titulo and url
    ]
    if not candidatos:
        return response_text
    # El mas especifico primero: dos normas cuyo titulo empieza igual —«Reglament de
    # permanencia» y «Reglament de permanencia per als estudis de grau i master»— se
    # resolverian a la corta si se mirara en el orden de llegada.
    candidatos.sort(key=lambda c: len(c[0]), reverse=True)

    def _reemplazo(coincidencia: re.Match) -> str:
        dentro = coincidencia.group(1)
        normalizado = _normalizar(dentro)
        for titulo, url in candidatos:
            if normalizado.startswith(titulo):
                return f"[{dentro}]({url})"
        return coincidencia.group(0)

    return _CORCHETE_SIN_ENLACE.sub(_reemplazo, response_text)


def despojar_remisiones(response_text: str, allowed: set[str]) -> str:
    """Deja en texto plano las referencias que apuntan fuera del conjunto recuperado.

    HIB.0. La regla, tal como la fijó el usuario el 2026-08-26: la respuesta cita la norma
    principal y, en su caso, las otras normas recuperadas y utilizadas para redactarla, pero
    **no las normas citadas por esas normas**.

    Con `parent_child` el fragmento inyectado es el artículo entero, que trae dentro sus
    remisiones —«conforme al artículo 118 de la Ley 9/2017»—. El modelo las enlaza, y ese
    enlace apunta a un texto que **no se le ha entregado**: lo que dijera sobre él saldría de
    su memoria, no del fundamento. La mención se conserva porque es información legítima y
    útil; lo que se va es el puntero, que es lo que no podemos respaldar.
    """

    def _reemplazo(coincidencia: re.Match) -> str:
        titulo, url = coincidencia.group(1), coincidencia.group(2).strip()
        return coincidencia.group(0) if url in allowed else titulo

    return _MD_LINK.sub(_reemplazo, response_text)


def citas_de(texto: str) -> list[tuple[str, str]]:
    """Los `(titulo, url)` de los enlaces markdown del texto.

    Existe para que nadie tenga que volver a escribir la expresión regular de una cita. VAS.1
    necesita contar y clasificar lo que el contrato hizo, y un `re.compile` en el router sería
    una segunda implementación de qué cuenta como cita entrando por la puerta de atrás.
    """
    return [(titulo, url.strip()) for titulo, url in _MD_LINK.findall(texto)]


def evidencias_citadas(texto: str, evidencias: list) -> list:
    """Las evidencias que el texto cita, en el orden en que llegaron (#335).

    Cuenta el documento, no el ancla: una cita a `página#art-3` es de la evidencia `página`. Es
    para el modo de contexto largo, donde todo el corpus es citable y devolverlo entero como
    fuentes no informa de nada.
    """
    citadas = {_sin_fragmento(url) for _titulo, url in citas_de(texto)}
    return [e for e in evidencias if (u := _url_de(e)) and _sin_fragmento(u) in citadas]


class ResultadoDelContrato:
    """El texto que el contrato deja, y el desglose de lo que hizo para dejarlo.

    Existe porque VAS.1 expone el contrato como servicio y quien lo llama necesita saber **qué
    pasó**, no sólo el veredicto: qué citas valieron, cuáles apuntaban fuera, cuántas anclas
    bajaron al documento y cuántas remisiones perdieron el enlace.

    El desglose sale de la **misma pasada** que produce el texto. Calcularlo aparte sería
    describir un texto distinto del que se devuelve: los pasos no son idempotentes entre sí, y
    el orden de degradar y despojar *es* el contrato.
    """

    __slots__ = (
        "texto",
        "cumple",
        "citas_validas",
        "citas_invalidas",
        "anclas_degradadas",
        "remisiones_despojadas",
    )

    def __init__(
        self,
        *,
        texto: str,
        cumple: bool,
        citas_validas: list[str],
        citas_invalidas: list[str],
        anclas_degradadas: int,
        remisiones_despojadas: int,
    ) -> None:
        self.texto = texto
        self.cumple = cumple
        self.citas_validas = citas_validas
        self.citas_invalidas = citas_invalidas
        self.anclas_degradadas = anclas_degradadas
        self.remisiones_despojadas = remisiones_despojadas


def aplicar_contrato(
    response_text: str,
    sources: list,
    mode: str,  # noqa: ARG001 — el agéntico se distingue por `sources` vacío; `mode` sigue en la firma pública de VAS.1
    no_answer_message: str | None = None,
) -> ResultadoDelContrato:
    """El contrato de citas, con el desglose de lo que hizo. **La única implementación.**

    `enforce_citation_contract` delega aquí y devuelve sólo el texto, que es lo que el grafo
    necesita. Así el servicio de VAS.1 y el motor no pueden divergir: no hay dos caminos, hay
    uno con dos vistas.
    """
    response_text = texto_de(response_text)
    if not sources:
        # Sin fuentes no hay contrato que aplicar: es el modo agéntico, donde el agente puede
        # decidir no leer nada. Se declara conforme porque no hay nada que fundamentar.
        return ResultadoDelContrato(
            texto=response_text,
            cumple=True,
            citas_validas=[],
            citas_invalidas=[],
            anclas_degradadas=0,
            remisiones_despojadas=0,
        )

    anclas = {u for u in (_url_de(s) for s in sources) if u} | _anclas_leidas(sources)
    # La URL de la norma es citable por derecho propio: es el «o la norma» del criterio
    # «el articulo si se puede, la norma si no». Sin esto, degradar produciria una URL que
    # el propio contrato rechazaria.
    citables = anclas | {_sin_fragmento(u) for u in anclas}
    # #336 — lo que se puede enlazar es algo más que lo que se puede citar: una dirección que
    # viene escrita en la evidencia conserva su enlace, pero no fundamenta la respuesta.
    allowed = citables | _urls_escritas(sources)

    # HIB.0: el orden de estos dos pasos es el contrato.
    #
    # 1. DEGRADAR primero: una cita al documento correcto con un ancla que no es la
    #    recuperada baja al documento y **sobrevive**. Si se despojara antes, esa cita —que
    #    es fundamento legitimo— se convertiria en texto plano y la respuesta se quedaria
    #    sin apoyo por un ancla mal compuesta.
    # 2. DESPOJAR despues: lo que sigue apuntando fuera del conjunto recuperado pierde el
    #    enlace, no la mencion.
    #
    # Y la comprobacion va LA ULTIMA, sobre el texto ya despojado: al reves, una remision
    # enlazada contaria como cita valida y el contrato dejaria de proteger justo de lo que
    # existe para proteger.
    degradado = degradar_anclas(response_text, anclas)
    enlazado = enlazar_citas_en_prosa(degradado, sources)
    texto = despojar_remisiones(enlazado, allowed)

    # El desglose, leyendo las citas en los puntos donde el contrato las cambia. Se cuentan
    # posiciones y no URL únicas: dos citas a la misma ancla equivocada son dos degradaciones,
    # y quien integra quiere saber cuántas veces pasó.
    antes = citas_de(response_text)
    tras_degradar = citas_de(degradado)
    finales = citas_de(texto)

    anclas_degradadas = sum(
        1
        for (_t1, u1), (_t2, u2) in zip(antes, tras_degradar, strict=False)
        if u1 != u2
    )
    urls_finales = {u for _t, u in finales}
    remisiones_despojadas = sum(
        1 for _t, u in tras_degradar if u not in allowed and u not in urls_finales
    )

    validas = list(dict.fromkeys(u for _t, u in finales if u in citables))
    invalidas = list(
        dict.fromkeys(u for _t, u in tras_degradar if u not in allowed)
    )

    if has_valid_citations(texto, citables):
        return ResultadoDelContrato(
            texto=texto,
            cumple=True,
            citas_validas=validas,
            citas_invalidas=invalidas,
            anclas_degradadas=anclas_degradadas,
            remisiones_despojadas=remisiones_despojadas,
        )

    # UX.4: el mensaje es del chatbot. Esta rama lo ignoraba y devolvia el texto fijo, en
    # castellano, a preguntas hechas en valenciano.
    return ResultadoDelContrato(
        texto=no_answer_message or NO_CITATION_FALLBACK,
        cumple=False,
        citas_validas=[],
        citas_invalidas=invalidas,
        anclas_degradadas=anclas_degradadas,
        remisiones_despojadas=remisiones_despojadas,
    )


def enforce_citation_contract(
    response_text: str,
    sources: list,
    mode: str,
    no_answer_message: str | None = None,
) -> str:
    """Si hubo sources y la respuesta no cita ninguno valido, devuelve el fallback.

    Antes de darla por invalida se intenta **degradar**: una cita al documento correcto con
    un ancla equivocada se reescribe al documento. Sin ese paso el contrato dejaba de
    proteger y empezaba a destruir — nueve de veinticinco respuestas descartadas, ocho de
    ellas con la mejor recuperacion de la tanda.

    Lo que sigue atrapando, que es para lo que existe: citar un documento que nunca se
    recupero, y no citar nada.

    En modo agentic, se relaja: el agente puede decidir no leer ningun documento
    (saludo, charla); validamos solo si sources no esta vacio.

    **USR.11 — la respuesta se normaliza al entrar.** Gemini devuelve el `content` como lista de
    bloques en cuanto tiene mas de una parte, y con una lista esta funcion se portaba de dos
    maneras distintas, que es lo peor de los dos mundos: con `sources` reales moria en la primera
    expresion regular (`TypeError: expected string or bytes-like object`), y con `sources` vacias
    salia por la linea de abajo **devolviendo la lista**, incumpliendo su propia firma y dejandola
    viajar aguas abajo con etiqueta de texto. Esa segunda mitad es la que no avisa, y es
    precisamente la forma del modo agentic cuando el modelo contesta sin leer nada.

    Se normaliza, **no se envuelve en un `except`**: un `except` cambiaria un fallo por silencio,
    que es lo que se acaba de arreglar en dos sitios. `texto_de` es donde vive el saber de como se
    lee un `content`, y esto es un llamador mas.

    **VAS.1 — el cuerpo se fue a `aplicar_contrato`**, que devuelve lo mismo mas el desglose de
    lo que hizo. Esta funcion se queda porque es la firma que el grafo usa y porque el desglose
    no le sirve de nada; lo que no puede haber es dos implementaciones del contrato, y ahora no
    las hay.
    """
    return aplicar_contrato(response_text, sources, mode, no_answer_message).texto
