"""Chunker para documentos Markdown (ING.0.4).

Consume el formato de `docs/CONTRATO_MD_CORPUS.md`:

    #      documento (uno por fichero)
    ##     preámbulo | título | grupo de disposiciones | anexo
    ###    capítulo
    ####   sección
    #####  UNIDAD CITABLE: artículo | disposición concreta   → ancla obligatoria

**El nivel lo determina el TIPO de elemento, no su anidamiento**, así que el chunker puede
fiarse de él. De ahí que haya saltos de nivel legítimos —`#####` justo bajo `##` en las
disposiciones— que no son errores y que el splitter trata bien: registra los encabezados
que ve y descarta los niveles intermedios que quedaron atrás.

Dos cosas que este módulo garantiza y de las que depende el resto:

- **La taxonomía nunca entra en el texto** (CLAUDE.md §5). Solo contexto estructural.
- **Las tablas no se parten dejando fragmentos sin cabecera.** Medido sobre el corpus
  convertido: 30 de los 54 bloques `TABLA-TEXT` superan `chunk_size`, y sin tratamiento
  especial todo fragmento menos el primero queda con importes sin nombre de columna. Eso
  es peor que no tener el dato, porque se recupera igual y sostiene una respuesta segura
  y falsa sobre una cuantía.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

# D.4.0: `langchain_text_splitters` se importa DENTRO del constructor, no aquí.
#
# Su `__init__.py` importa `langchain_text_splitters.sentence_transformers` de forma ansiosa,
# y ese módulo arrastra `sentence_transformers` → `transformers` → `torch`: unos 600 MB y casi
# todo el tiempo de arranque, por un splitter que este proyecto no usa. Como no hay forma de
# importar un submódulo sin ejecutar el `__init__` del paquete, la única salida es no
# importarlo al cargar el módulo.
#
# El coste se paga al construir un `MarkdownChunker`, o sea al ingerir. El proceso que solo
# atiende chat nunca lo paga.

# Ancla de atributos Pandoc/kramdown al final del encabezado: '{#art-14}'.
# Bloque de atributos Pandoc/kramdown al final del encabezado. Admite clases junto al
# ancla —`{#art-14 .modificat}`— porque el estado de consolidación del elemento viaja ahí:
# es el mismo token que el ancla, así que sobrevive al troceado y queda pegado al artículo.
# Sin este soporte, un `{#art-14 .modificat}` perdía el ancla EN SILENCIO.
_ANCORA = re.compile(
    r"\s*\{#(?P<ancora>[A-Za-z0-9][A-Za-z0-9._-]*)(?P<atributos>[^}]*)\}\s*$"
)
_CLASE = re.compile(r"\.([A-Za-z][A-Za-z0-9_-]*)")
# Estados de consolidación conocidos. Se nombran para que un filtro pueda usarlos; el
# resto de clases se conserva en `classes` sin interpretarlas.
# `derogat` entra en ACT.4: un articulo derogado dentro de una norma vigente es el
# mismo caso que uno suprimido, y el corpus lo marca asi en las derogaciones
# parciales, que ya no son un estado de norma sino marcas de articulo.
ESTADOS_CONSOLIDACION = ("suprimit", "derogat", "modificat", "afegit")
# Ancla vacía o mal formada: se limpia del texto pero no produce ancla.
_ANCORA_ROTA = re.compile(r"\s*\{#[^}]*\}")

_BLOQUE_TABLA = re.compile(
    r"<!--\s*TABLA-TEXT:(?P<cabecera>[^>]*?)-->\s*\n"
    r"(?P<cuerpo>.*?)"
    r"\n?\s*<!--\s*/TABLA-TEXT\s*-->",
    re.DOTALL,
)
_MARCADOR_IMAGEN = re.compile(r"^\s*<!--\s*TABLE-IMG:.*?-->\s*$", re.MULTILINE)
_FORMATOS_TABLA = ("markdown", "html")

_NIVELES = 5


@dataclass
class Chunk:
    """Representa un chunk de documento.

    `embedding_text` (RAG.7) es lo que se embebe; `content` es lo que se almacena y se
    muestra como evidencia. **Son distintos a propósito**: un fragmento que dice «L'import
    es de 53,34 euros» no dice de qué importe habla ni de qué norma sale, y embebido asi
    compite contra cualquier otro importe del corpus. Con su jerarquia delante queda anclado
    a su contexto sin cambiar ni una letra de lo que lee el usuario.

    No se persiste: se calcula al trocear y se consume en la ingesta.
    """

    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    embedding_text: str = ""
    # RAG.8: seccion estructural completa a la que pertenece el fragmento, con la estrategia
    # 'parent_child'. Vacio con 'structural'.
    parent_content: str = ""

    def __post_init__(self) -> None:
        if not self.embedding_text:
            self.embedding_text = self.content


@runtime_checkable
class ContextEnricher(Protocol):
    """Nivel 2 de contextual retrieval: una frase de contexto generada en la ingesta.

    Se define el protocolo y se deja `NoopEnricher` por defecto. La implementacion con LLM
    —que redacta «este fragmento trata de X» leyendo el documento entero— queda como
    candidata para cuando el corpus definitivo este cargado: cuesta una llamada por chunk en
    la ingesta y no tiene sentido pagarla contra un corpus que aun va a cambiar.
    """

    def enrich(self, document: str, chunk: str) -> str: ...


class NoopEnricher:
    """No enriquece. El default, y el unico que existe hoy."""

    def enrich(self, document: str, chunk: str) -> str:  # noqa: ARG002 — el enriquecedor nulo cumple el protocolo y no enriquece
        return ""


# Todos los separadores de la categoría Unicode `Zs` menos el espacio ASCII. Es un conjunto
# cerrado: Unicode no añade caracteres a esta categoría.
_SEPARADORES_RAROS = str.maketrans(
    {
        c: " "
        for c in "\xa0           "
        "   　"
    }
)


def normalizar_separadores(texto: str) -> str:
    """Todo separador Unicode pasa a ser un espacio normal (issue #164).

    **Hay que hacerlo antes de partir por encabezados, no después.**
    `MarkdownHeaderTextSplitter` limpia la línea del encabezado con
    `"".join(filter(str.isprintable, linea))`, y `str.isprintable` da por no imprimible cualquier
    separador de la categoría `Zs` que no sea el espacio ASCII. O sea que no lo sustituye: **lo
    borra**, y el hueco ya no se puede recuperar sin inventárselo.

    Pasó, y en producción: el BOE titula la Ley 39/2015 y la Ley 40/2015 con `Artículo\xa01.`, y
    la base guardaba `Artículo1. Objeto de la Ley` en **343 encabezados de 7 normas**. El
    encabezado no es decoración —es el contexto estructural que viaja al modelo en
    `embedding_text` y lo que se enseña junto a la cita—, y `articulo1` tampoco es el mismo token
    que `artículo 1` para la búsqueda de texto completo.

    Se aplica al documento entero y no sólo a sus encabezados: el espacio duro abunda también en
    el cuerpo del BOE («artículo\xa020 de la Ley»), y normalizar sólo el rótulo dejaría el mismo
    artículo escrito de dos maneras dentro del mismo fragmento.
    """
    return texto.translate(_SEPARADORES_RAROS)


def strip_anchor_tokens(texto: str) -> str:
    """Quita los tokens `{#...}` del texto visible.

    Se usa también al inyectar documentos completos (long context): el token es ruido
    tanto para el modelo como para quien lee la respuesta.
    """
    return _ANCORA_ROTA.sub("", texto)


def _extraer_ancora(encabezado: str) -> tuple[str, str | None, list[str]]:
    """Devuelve (encabezado_limpio, ancora, clases)."""
    match = _ANCORA.search(encabezado)
    if match:
        clases = _CLASE.findall(match.group("atributos") or "")
        return encabezado[: match.start()].rstrip(), match.group("ancora"), clases
    return _ANCORA_ROTA.sub("", encabezado).rstrip(), None, []


class MarkdownChunker:
    """Divide documentos Markdown en chunks semánticos.

    `table_chunk_size` es el presupuesto de atomicidad de una tabla: un bloque que quepa
    en él NO se parte, aunque supere `chunk_size`. El default de 4.000 caracteres deja
    enteros 51 de los 54 bloques del corpus medido.
    """

    def __init__(
        self,
        chunk_size: int = 1000,
        chunk_overlap: int = 100,
        table_chunk_size: int = 4000,
        enricher: ContextEnricher | None = None,
        strategy: str = "structural",
        chunk_size_child: int = 400,
        parent_max_tokens: int = 8000,
    ):
        from langchain_text_splitters import (
            MarkdownHeaderTextSplitter,
            RecursiveCharacterTextSplitter,
        )

        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.table_chunk_size = table_chunk_size
        self.enricher = enricher or NoopEnricher()
        # RAG.8. 'parent_child' trocea mas fino DENTRO de cada seccion y guarda la seccion
        # entera como padre: se busca con el hijo, que es mas especifico y se encuentra
        # mejor, y se responde con el padre, que trae el contexto que al hijo le falta.
        self.strategy = strategy
        self.chunk_size_child = chunk_size_child
        # HIB.L — techo del padre, medido y no supuesto. Sobre los 10.614 padres del corpus de
        # Normativa la mediana son **205 tokens** y el p90 **710**; sólo 24 pasan de 8.000.
        #
        # Pero contar padres engaña: lo que cuesta son los **fragmentos**, porque cada hijo
        # arrastra su padre y uno gigante va pegado a todos los hijos de su sección. Medido:
        # **5.172 de 60.859 fragmentos (8,5 %)** arrastraban un padre de más de 8.000 tokens,
        # en 11 documentos; el coste medio del padre por fragmento era de **2.955 tokens** y
        # el peor caso con `top_k = 3` sumaba **177.516 — el 139 % del presupuesto**, así que
        # el packer descartaba evidencia en silencio. Con el techo: 895 de media y 19 % en el
        # peor caso.
        #
        # La cola es de dos clases, y ninguna tiene unidad estructural más fina a la que bajar.
        #
        # **8 preámbulos**, incluido uno de 59.172 tokens: no tienen encabezados internos —los
        # números romanos son texto— y además no son normativos. Y **16 artículos o anexos**
        # reales, casi todos de leyes de acompañamiento cuyos artículos modifican otras leyes
        # enteras (`art-119` de la Ley 6/2024 son 21.484 tokens): un artículo ya ES la unidad
        # mínima.
        #
        # Qué se hace con lo que no cabe: **el hijo se queda sin padre** y responde con su
        # propio texto, como en `structural`. No se subdivide ni se trunca, así que ningún
        # artículo acaba partido en dos padres —dos hijos del mismo artículo recibirían
        # contextos distintos e incompatibles— y se renuncia al contexto ampliado justo donde
        # no era ni asequible ni útil.
        self.parent_max_tokens = parent_max_tokens
        self.child_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size_child,
            chunk_overlap=min(chunk_overlap, chunk_size_child // 4),
        )

        self.headers_to_split = [("#" * n, f"header_{n}") for n in range(1, _NIVELES + 1)]

        self.md_splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=self.headers_to_split,
            strip_headers=False,
        )

        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

    # ───────────────────────── Encabezados ─────────────────────────

    def _limpiar_encabezados(
        self, doc_metadata: dict
    ) -> tuple[dict, list[str], str | None, list[str]]:
        """Separa los encabezados en ruta de ancestros + ancla y clases de la unidad."""
        limpios: dict[str, str] = {}
        ancora: str | None = None
        clases: list[str] = []
        presentes: list[str] = []

        for nivel in range(1, _NIVELES + 1):
            clave = f"header_{nivel}"
            if clave not in doc_metadata:
                continue
            texto, ancora_nivel, clases_nivel = _extraer_ancora(str(doc_metadata[clave]))
            limpios[clave] = texto
            presentes.append(clave)
            if ancora_nivel:
                # El ancla del nivel más profundo es la que cita el fragmento, y sus
                # clases son el estado de consolidación de ese elemento.
                ancora = ancora_nivel
                clases = clases_nivel

        # La ruta son los ancestros: todo menos el encabezado más profundo.
        ruta = [limpios[c] for c in presentes[:-1]] if len(presentes) > 1 else []
        return limpios, ruta, ancora, clases

    # ───────────────────────── Tablas ─────────────────────────

    @staticmethod
    def _metadatos_tabla(cabecera: str) -> dict[str, Any]:
        """Lee la procedencia del marcador: origen, página, dimensiones y formato."""
        campos = [c.strip() for c in cabecera.split("|")]
        datos: dict[str, Any] = {
            "es_taula": True,
            "taula_origen": campos[0] if campos else None,
            "pagina": None,
            "dimensions": None,
            # Sin formato declarado se asume markdown, que es el del contrato.
            "taula_format": "markdown",
        }
        for campo in campos[1:]:
            bajo = campo.lower()
            if bajo in _FORMATOS_TABLA:
                datos["taula_format"] = bajo
            elif re.fullmatch(r"\d+x\d+", bajo):
                datos["dimensions"] = campo
            elif datos["pagina"] is None and re.search(r"\d", campo):
                datos["pagina"] = campo
        return datos

    @staticmethod
    def _es_separador(linea: str) -> bool:
        limpia = linea.replace("|", "").replace(" ", "")
        return bool(limpia) and set(limpia) <= {"-", ":"}

    def _partir_tabla_pipe(self, cuerpo: str) -> list[str]:
        """Parte por filas repitiendo el prefijo (leyenda + cabecera) en cada fragmento.

        La fila de cabecera es la que **precede al separador** `| --- |`, no la primera
        línea del bloque: el corpus curado mete la leyenda de la tabla dentro del bloque
        («**Retribucions del professorat…**»), y tomarla por cabecera dejaría la cabecera
        real convertida en una fila de datos.
        """
        lineas = [ln for ln in cuerpo.splitlines() if ln.strip()]
        if not lineas:
            return []

        separador = next(
            (i for i, ln in enumerate(lineas) if self._es_separador(ln)), None
        )
        if separador is not None:
            # Todo hasta el separador (leyenda + cabecera) se repite en cada fragmento.
            cabecera = lineas[: separador + 1]
            resto = lineas[separador + 1 :]
        else:
            cabecera = lineas[:1]
            resto = lineas[1:]

        prefijo = "\n".join(cabecera)
        fragmentos: list[str] = []
        actual: list[str] = []
        for fila in resto:
            candidato = "\n".join([prefijo, *actual, fila])
            if actual and len(candidato) > self.table_chunk_size:
                fragmentos.append("\n".join([prefijo, *actual]))
                actual = [fila]
            else:
                actual.append(fila)
        if actual:
            fragmentos.append("\n".join([prefijo, *actual]))
        return fragmentos or [prefijo]

    def _partir_tabla_html(self, cuerpo: str) -> list[str]:
        """Parte por `<tr>` del cuerpo, repitiendo apertura y `<thead>`."""
        apertura = re.search(r"<table[^>]*>", cuerpo)
        thead = re.search(r"<thead>.*?</thead>", cuerpo, re.DOTALL)
        filas = re.findall(r"<tr>(?!.*?</thead>).*?</tr>", cuerpo, re.DOTALL)
        if thead:
            filas = [f for f in filas if f not in thead.group(0)]
        if not filas:
            return [cuerpo]

        prefijo = (apertura.group(0) if apertura else "<table>") + (
            "\n" + thead.group(0) if thead else ""
        )
        fragmentos: list[str] = []
        actual: list[str] = []
        for fila in filas:
            candidato = f"{prefijo}\n<tbody>\n" + "\n".join([*actual, fila]) + "\n</tbody>\n</table>"
            if actual and len(candidato) > self.table_chunk_size:
                fragmentos.append(
                    f"{prefijo}\n<tbody>\n" + "\n".join(actual) + "\n</tbody>\n</table>"
                )
                actual = [fila]
            else:
                actual.append(fila)
        if actual:
            fragmentos.append(
                f"{prefijo}\n<tbody>\n" + "\n".join(actual) + "\n</tbody>\n</table>"
            )
        return fragmentos

    def _trocear_tabla(self, cabecera: str, cuerpo: str) -> list[tuple[str, dict]]:
        metadatos = self._metadatos_tabla(cabecera)
        cuerpo = cuerpo.strip()

        if len(cuerpo) <= self.table_chunk_size:
            return [(cuerpo, metadatos)]

        partes = (
            self._partir_tabla_html(cuerpo)
            if metadatos["taula_format"] == "html"
            else self._partir_tabla_pipe(cuerpo)
        )
        total = len(partes)
        return [
            (parte, {**metadatos, "taula_part": i + 1, "taula_parts": total})
            for i, parte in enumerate(partes)
        ]

    # ───────────────────────── Troceado de una sección ─────────────────────────

    def _trocear_seccion(self, contenido: str) -> list[tuple[str, dict]]:
        """Devuelve [(texto, metadatos_extra)] separando prosa y bloques de tabla."""
        piezas: list[tuple[str, dict]] = []
        posicion = 0

        for match in _BLOQUE_TABLA.finditer(contenido):
            prosa = contenido[posicion : match.start()]
            piezas.extend((t, {}) for t in self._trocear_prosa(prosa))
            piezas.extend(self._trocear_tabla(match.group("cabecera"), match.group("cuerpo")))
            posicion = match.end()

        piezas.extend((t, {}) for t in self._trocear_prosa(contenido[posicion:]))
        return piezas

    def _trocear_prosa(self, texto: str) -> list[str]:
        # El marcador de imagen no aporta nada al índice y ensucia el fragmento.
        limpio = _MARCADOR_IMAGEN.sub("", texto).strip()
        if not limpio:
            return []
        if len(limpio) <= self.chunk_size:
            return [limpio]
        return self.text_splitter.split_text(limpio)

    # ───────────────────────── API ─────────────────────────

    @staticmethod
    def _texto_embebible(
        titulo: str | None, encabezados: dict[str, str], contenido: str, prefacio: str
    ) -> str:
        """Jerarquía estructural + contenido (RAG.7).

        Solo entra el título del documento y sus encabezados. **Nunca taxonomía ni ancla**:
        la taxonomía porque el vocabulario está pendiente de validar y debe seguir siendo
        revisable —embebida, cada revisión costaría re-embeber el corpus (CLAUDE.md §5)—; el
        ancla porque es ruido para el vector y su sitio es la URL de la cita.

        El encabezado más profundo no se repite si el contenido ya empieza por él: duplicar
        la misma frase sesga el vector hacia ella.
        """
        # El contenido conserva sus encabezados (`strip_headers=False` desde ING.0.4), así
        # que el PRIMER fragmento de una sección ya los lleva dentro y prefijarlos otra vez
        # solo sesgaría el vector hacia ellos. Los que ganan contexto son los fragmentos
        # SIGUIENTES de una sección larga, que se quedaron sin encabezado al trocear.
        ya_presentes = set()
        for linea in contenido.lstrip().splitlines():
            if not linea.lstrip().startswith("#"):
                break
            ya_presentes.add(linea.lstrip("#").strip())

        niveles: list[str] = []
        for nivel in ([titulo] if titulo else []) + [
            encabezados[c] for c in sorted(encabezados) if encabezados[c]
        ]:
            if nivel and nivel not in ya_presentes and nivel not in niveles:
                niveles.append(nivel)

        partes = [p for p in (prefacio.strip(), " > ".join(niveles)) if p]
        return f"{chr(10).join(partes)}\n\n{contenido}" if partes else contenido

    def split(
        self,
        content: str,
        metadata: dict[str, Any] | None = None,
        document_title: str | None = None,
    ) -> list[Chunk]:
        """Divide el contenido en chunks.

        Args:
            content: Contenido Markdown
            metadata: Metadatos adicionales (document_id, source_url…). **No se copia
                al texto**: si trajera taxonomía, entraría en el embedding.
            document_title: título del documento, que encabeza el `embedding_text`. Va como
                parámetro y no dentro de `metadata` justamente para que quede claro que no
                es un metadato del chunk: es contexto de embedding y no se persiste.

        Returns:
            Lista de chunks
        """
        base_metadata = metadata or {}

        chunks: list[Chunk] = []
        # Issue #164: antes de partir, porque el splitter **borra** los separadores raros del
        # encabezado en vez de sustituirlos, y después ya no hay hueco que recuperar.
        for doc in self.md_splitter.split_text(normalizar_separadores(content)):
            encabezados, ruta, ancora, clases = self._limpiar_encabezados(doc.metadata)
            estado = next((c for c in clases if c in ESTADOS_CONSOLIDACION), None)
            comun = {
                **base_metadata,
                **encabezados,
                "ruta": ruta,
                "ancora": ancora,
                # Estado de consolidación del elemento, del bloque de atributos del
                # encabezado. Pegado al artículo y sobreviviendo al troceado, es lo que
                # evita citar un artículo suprimido como si estuviera en vigor.
                "estat": estado,
                "classes": clases,
            }

            seccion = strip_anchor_tokens(doc.page_content)
            # HIB.L — el techo se comprueba por SECCIÓN y no por documento: el artículo de al
            # lado no paga el preámbulo gigante de su misma ley.
            cabe_como_padre = len(seccion) // 4 <= self.parent_max_tokens
            piezas = self._trocear_seccion(seccion)
            if self.strategy == "parent_child":
                # El padre es la SECCION estructural entera, no la pieza: la unidad que da
                # contexto es el articulo completo, no el trozo del que salio el hijo.
                piezas = [
                    (hijo, extra)
                    for texto, extra in piezas
                    for hijo in self.child_splitter.split_text(texto)
                ]

            for indice, (texto, extra) in enumerate(piezas):
                chunks.append(
                    Chunk(
                        content=texto,
                        metadata={**comun, **extra, "chunk_index": indice},
                        embedding_text=self._texto_embebible(
                            document_title,
                            encabezados,
                            texto,
                            self.enricher.enrich(content, texto),
                        ),
                        parent_content=(
                            seccion
                            if self.strategy == "parent_child" and cabe_como_padre
                            else ""
                        ),
                    )
                )

        return chunks
