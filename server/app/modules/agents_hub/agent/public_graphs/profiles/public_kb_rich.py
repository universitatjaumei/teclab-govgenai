"""Perfil PUBLIC_KB_RICH — chatbot público genérico con KB enriquecida.

Compatible con los tres modos de retrieval (RAG, MD_LONG_CONTEXT, MD_AGENT_SELECTOR).
Sin lógica de dominio; apto para grupos, oferta académica, FAQs municipales, etc.

Deploy: edge
"""
from __future__ import annotations

from server.app.modules.agents_hub.services.language_detector import (
    detect_language as _detect_language,
)
from server.app.modules.agents_hub.agent.public_graphs.strategies.protocols import (
    PipelineRetrievalStrategy,
    PreferLanguagePolicy,
    RetrievalOutput,
)
from server.app.modules.agents_hub.agent.public_graphs.strategies.retrieval_contract import (
    EvidenceItem,
)
from server.app.modules.agents_hub.services.retrieval.citations import ANCLAS_CITABLES
from server.app.modules.agents_hub.services.retrieval.vigencia import (
    CLAVE_METADATO as CLAVE_VIGENCIA,
)


class SingleSourceRetrievalStrategy(PipelineRetrievalStrategy):
    """Retrieval desde una única fuente, seleccionada por cfg.retrieval_mode.

    Hereda PipelineRetrievalStrategy sin modificaciones; el nombre explicita
    que este perfil usa siempre una sola fuente por consulta.
    """


class PassthroughMergeStrategy:
    """Fusiona los buckets aplanando todos sus items en una lista única."""

    def merge(self, output: RetrievalOutput) -> list[EvidenceItem]:
        items: list[EvidenceItem] = []
        for bucket in output.buckets:
            items.extend(bucket.items)
        return items


CITATION_RULES = """\
REGLAS DE CITA (obligatorias):
1. Cada afirmacion factual basada en los documentos debe ir seguida de una cita en formato
   markdown `[titulo del documento](url)`. La cita va al final de la frase citada.
2. Si una afirmacion combina varios documentos, cita todos: `[doc1](url1) [doc2](url2)`.
3. Si la pregunta no puede responderse con la informacion disponible, dilo explicitamente:
   "No tengo informacion suficiente en los documentos disponibles para responder a esta
   pregunta con citas verificables." NO inventes informacion ni cites documentos no
   recuperados.
4. NUNCA inventes URLs ni titulos. Usa SOLO los proporcionados en el contexto.
5. COPIA la URL EXACTAMENTE como aparece en la linea `URL:` del documento, sin anadir ni
   quitar un solo caracter. En particular, NO le anadas un ancla (`#...`) que no venga ya
   en esa linea: si el fragmento que has leido pertenece a un apartado mas concreto, dilo
   en el TEXTO del enlace, no en la direccion.
6. Nombra en el texto el articulo, apartado o seccion del que sale cada afirmacion, para
   que quien lee pueda localizarla dentro de la norma:
   `[Directrius academiques, art. 1.7.a](url)`. Si el documento no se divide en articulos,
   nombra el apartado tal y como aparezca."""

# #336 — un documento entregado entero trae sus anclas en los encabezados, y su URL es la del
# documento. La regla 5 general prohíbe añadir ancla porque, con fragmentos, el ancla buena ya
# viene en la URL; con el documento entero no viene, y prohibirla impedía citar el artículo.
#
# Revisión de la PR #338: sólo para los documentos que la estrategia marca con anclas citables
# —los que se citan en nuestro sitio—. Decidirlo por el modo invitaba a poner anclas a un PDF o
# a una página del BOE, que no las sirven o usan otras, y sin `show_citation_corrections` el
# usuario las veía tal cual.
MARCA_DE_ANCLAS = "CITA POR APARTADO: si"
_REGLA_5 = CITATION_RULES[CITATION_RULES.index("5. COPIA") : CITATION_RULES.index("6. Nombra")]
_REGLA_5_DOCUMENTO_ENTERO = f"""\
5. COPIA la URL EXACTAMENTE como aparece en la linea `URL:` del documento. Si el documento
   lleva la linea `{MARCA_DE_ANCLAS}`, para citar un apartado concreto anade a esa URL el ancla
   que el documento declara en su encabezado entre llaves: si el encabezado dice `{{#art-3}}`,
   cita `URL#art-3`. Usa SOLO anclas que aparezcan asi en ese documento. En los documentos sin
   esa linea, NO anadas ningun ancla: cita la URL tal cual.
"""


def _anclas_de(item: EvidenceItem) -> list:
    return (item.metadata or {}).get(ANCLAS_CITABLES) or []


def reglas_de_cita(items: list[EvidenceItem]) -> str:
    """Las reglas de cita: la 5 cambia si algún documento se puede citar por apartado (#336)."""
    if any(_anclas_de(i) for i in items):
        return CITATION_RULES.replace(_REGLA_5, _REGLA_5_DOCUMENTO_ENTERO)
    return CITATION_RULES


RANK_AND_VALIDITY_RULES = """\
REGLAS DE RANGO Y VIGENCIA (obligatorias):
1. Ante dos normas que regulan lo mismo, manda la de rango superior: ley > decreto >
   reglamento > acuerdo > instruccion. Dilo cuando resuelvas una contradiccion asi.
2. No presentes como vigente lo que el documento no declara vigente. Si la vigencia del
   documento citado no esta validada, advierte de ello en la respuesta.
3. No cites una norma derogada como si estuviera en vigor, ni siquiera si la recuperas."""

_INSTRUCCION_TOOLS = (
    "Usa la tool `list_documents(submateries=[...])` con 1-3 submaterias del indice de "
    "materias para ver las fichas de las normas de esos temas, y "
    "`read_document(document_id=...)` para cargar el texto completo de cada documento que "
    "necesites antes de responder. "
    "Si ninguna submateria encaja, llama a `list_documents` sin submaterias. "
    # La ficha del indice trae el tamano en tokens, asi que el modelo puede decidir antes
    # de pedir la lectura. Sin esta instruccion pedia igualmente la ley entera y recibia
    # solo el principio, que es peor que buscar dentro.
    "Cuando la ficha diga que un documento es muy largo —las normas externas como la Ley "
    "de Contratos lo son— no lo leas entero: usa `search_knowledge(query=...)` para traer "
    "los fragmentos que responden a la pregunta, con las palabras de la norma."
)


class GenericAnswerTemplateStrategy:
    """Plantilla genérica y **única fuente del system prompt** (RAG.2).

    Absorbe `agent/prompts.py` (`build_system_prompt`, `format_sources_block`,
    `CITATION_RULES`), que se retiró con el grafo antiguo. Tener dos sitios donde se
    componía el system prompt era la razón por la que las reglas de cita y el bloque de
    fuentes podían divergir entre el grafo viejo y el CoreGraph.

    `base_system_prompt` es el del `HubChatbot`, que llega por la cascada del
    ConfigResolver.
    """

    def __init__(
        self,
        base_system_prompt: str | None = None,
        retrieval_mode: str = "RAG",
        router_index: str | None = None,
    ) -> None:
        self._base = (base_system_prompt or "").strip()
        self._retrieval_mode = retrieval_mode
        self._router_index = (router_index or "").strip()

    def _bloque_de_fuentes(self, items: list[EvidenceItem]) -> str:
        lineas: list[str] = []
        for item in items:
            lineas.append(f"## {item.title or item.source_id}")
            if item.source_url:
                # La URL va SOLA en su linea y sin marcado alrededor. Estuvo en cursiva
                # (`_URL: ..._`) y el guion bajo de cierre, pegado al final de la direccion,
                # se colaba en la cita que escribia el modelo: `...#art-1_`. La comparacion
                # exacta fallaba y se descartaba la respuesta ENTERA.
                #
                # Medido el 2026-08-24 sobre el lote ujirag: seis de cada ocho descartes por
                # citas eran esto y nada mas. Y de forma intermitente, porque depende de si
                # el modelo arrastra el caracter en esa generacion — que es el peor modo de
                # fallo posible, el que no se reproduce cuando alguien va a mirarlo.
                lineas.append(f"URL: {item.source_url}")
                if _anclas_de(item):
                    lineas.append(MARCA_DE_ANCLAS)
            # VIS.3: marcado por documento, no aviso general. El modelo necesita saber de
            # CUAL de las normas se duda para poder redactarlo con naturalidad; el aviso
            # que garantiza que se diga lo pone el CoreGraph sobre la respuesta.
            if (item.metadata or {}).get(CLAVE_VIGENCIA):
                lineas.append("_[VIGENCIA NO VALIDADA: dilo si citas este documento]_")
            lineas.append("")
            lineas.append(item.content)
            lineas.append("")
        return "\n".join(lineas)

    def build_prompt_context(
        self,
        items: list[EvidenceItem],
        language: str | None,
        query: str,
    ) -> str:
        partes: list[str] = []
        if self._base:
            partes.extend([self._base, ""])
        if language:
            partes.extend([f"Responde en {language}.", ""])
        partes.append(reglas_de_cita(items).strip())

        if self._retrieval_mode == "MD_AGENT_SELECTOR":
            # Nivel 0 (VIS.2): el router necesita saber qué TEMAS existen, no qué normas.
            # El catálogo de fichas son ~72k tokens y no cabe aquí; el índice de las 58
            # submaterias son ~2,3k y sí. Va acompañado de las reglas con las que el modelo
            # tiene que leer lo que después seleccione.
            partes.extend(["", RANK_AND_VALIDITY_RULES.strip()])
            if self._router_index:
                partes.extend(["", "INDICE DE MATERIAS:", "", self._router_index])
            partes.extend(["", _INSTRUCCION_TOOLS])
        elif items:
            partes.extend(["", "DOCUMENTOS DISPONIBLES:", "", self._bloque_de_fuentes(items)])
        else:
            partes.extend(["", "No hay evidencias disponibles para responder esta consulta."])

        return "\n".join(partes).strip()


class DefaultLanguagePolicy(PreferLanguagePolicy):
    """Política de idioma por defecto para PUBLIC_KB_RICH: prefer con langdetect."""

    def detect(self, query: str) -> str | None:
        return _detect_language(query)
