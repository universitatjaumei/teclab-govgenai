"""Pliegos de la Plataforma de Contratación del Sector Público, para la carpeta de un agente.

Ejemplo de la plataforma: llena la carpeta de Drive que el guion del índice (#174) resume y manda
como índice de un **agente de pliegos**. Lee los datos abiertos de PLACSP —ficheros ZIP con feeds
Atom en formato CODICE—, se queda con los expedientes que pide la selección y descarga sus pliegos.

Lo propio de cada organización es la **selección**: qué órganos, qué CPV, qué procedimientos. La
de la Universitat Jaume I está al final, en `SELECCION_UJI`, y es sólo un ejemplo.

Tres decisiones, y por qué:

* **Una carpeta plana y sólo PDF.** El guion lee el primer nivel de la carpeta y resume PDF de
  hasta 15 MB; lo demás lo contaría como documento sin ficha. Lo que no se guarda se anota.
* **La tabla de expedientes va fuera de la carpeta.** Por la misma razón: dentro sería un
  documento más. Sirve para revisar la selección y para rellenar a mano columnas del índice.
* **El nombre del fichero es el título de la ficha**, y lleva delante la **capa** del corpus entre
  corchetes —`[Universidad]`, `[CSIC]`—: así el prompt del agente puede decir cuánto pesa cada
  documento, y el título dice de dónde viene sin abrirlo.

Sólo usa la biblioteca estándar: corre igual en Colab que en local.
"""
from __future__ import annotations

import csv
import io
import json
import re
import shutil
import time
import unicodedata
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Iterator
from xml.etree import ElementTree as ET

#: Los dos feeds. Los periodos son `AAAA` (año cerrado) o `AAAAMM` (mes del año en curso).
FUENTES = {
    # Lo que se publica en la propia PLACSP.
    "perfiles": "https://contrataciondelsectorpublico.gob.es/sindicacion/sindicacion_643/"
    "licitacionesPerfilesContratanteCompleto3_{periodo}.zip",
    # Lo que publican las plataformas autonómicas y PLACSP agrega (sin contratos menores).
    "agregadas": "https://contrataciondelsectorpublico.gob.es/sindicacion/sindicacion_1044/"
    "PlataformasAgregadasSinMenores_{periodo}.zip",
}

_NS = {
    "a": "http://www.w3.org/2005/Atom",
    "cac": "urn:dgpe:names:draft:codice:schema:xsd:CommonAggregateComponents-2",
    "cbc": "urn:dgpe:names:draft:codice:schema:xsd:CommonBasicComponents-2",
    "cacx": "urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonAggregateComponents-2",
    "cbcx": "urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonBasicComponents-2",
}
_ENTRADA = "{%s}entry" % _NS["a"]
#: Un expediente retirado del feed llega como lápida: `<at:deleted-entry ref="…">`.
_LAPIDA = "{http://purl.org/atompub/tombstones/1.0}deleted-entry"

#: ContractCode de CODICE. Las etiquetas son las opciones del dato «Tipo de contrato» del agente.
TIPOS = {"1": "Suministros", "2": "Servicios", "3": "Obras"}

#: SyndicationTenderingProcessCode de CODICE.
PROCEDIMIENTOS = {
    "1": "Abierto",
    "2": "Restringido",
    "3": "Negociado sin publicidad",
    "4": "Negociado con publicidad",
    "5": "Diálogo competitivo",
    "6": "Contrato menor",
    "7": "Derivado de acuerdo marco",
    "8": "Concurso de proyectos",
    "9": "Abierto simplificado",
    "10": "Asociación para la innovación",
    "11": "Derivado de asociación para la innovación",
    "100": "Normas internas",
    "999": "Otros",
}

#: Las clases de documento que se saben descargar. La memoria es el código 9 de los
#: documentos generales (GeneralContractDocuments).
CLASES = ("PCAP", "PPT", "Memoria")
_MEMORIA = "9"


def normalizar(texto: str) -> str:
    """Sin acentos, sin mayúsculas y con los espacios colapsados: para comparar nombres."""
    sin = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", sin).strip().lower()


# =============================================================================
#  La selección
# =============================================================================


@dataclass(frozen=True)
class Capa:
    """Qué órganos pertenecen a una capa del corpus.

    Tres maneras de casar, sobre el órgano y cada uno de sus ancestros; basta con una:

    * `ancestros`: el nombre exacto de un nodo de la jerarquía —«UNIVERSIDADES» recoge todas las
      públicas de PLACSP sin escribir su nombre—;
    * `empieza`: el nombre empieza por esto, **como palabra entera** —«Universidad» casa con
      «Universidad de Burgos» y no con «Universidades»—;
    * `contiene`: el nombre contiene esto, en cualquier sitio.

    **Las capas se prueban en orden**: la propia va antes que la general que también la contiene.

    `maximo_por_entidad`: cuántos expedientes de cada entidad, los más recientes. Sin él, todos.
    Es lo que da variedad sin que una entidad que licita mucho llene la carpeta. `alias`: el
    nombre corto de la entidad en el título del fichero.
    """

    nombre: str
    ancestros: frozenset[str] = frozenset()
    empieza: tuple[str, ...] = ()
    contiene: tuple[str, ...] = ()
    maximo_por_entidad: int | None = None
    alias: str | None = None

    def _por_nombre(self, nombre: str) -> bool:
        n = normalizar(nombre)
        return any(re.match(re.escape(normalizar(e)) + r"\b", n) for e in self.empieza) or any(
            normalizar(c) in n for c in self.contiene
        )

    def casa(self, jerarquia: list[str]) -> bool:
        if {normalizar(a) for a in self.ancestros} & {normalizar(n) for n in jerarquia}:
            return True
        return any(self._por_nombre(n) for n in jerarquia)

    def entidad(self, jerarquia: list[str]) -> str:
        """La entidad, no el órgano: el nombre **más general** que casa por nombre —«Universidad de
        Burgos» y no «Rectorado de la …»—; si sólo casa por un nodo, el propio órgano."""
        if self.alias:
            return self.alias
        return next((n for n in reversed(jerarquia) if self._por_nombre(n)), jerarquia[0] if jerarquia else "")


@dataclass(frozen=True)
class Seleccion:
    capas: tuple[Capa, ...]
    periodos: tuple[str, ...]
    fuentes: tuple[str, ...] = ("perfiles", "agregadas")
    #: Prefijos de CPV; basta con que case uno del expediente o de cualquiera de sus lotes.
    cpv: tuple[str, ...] = ()
    #: Códigos de tipo de contrato (`TIPOS`). Hace falta junto al CPV: un CPV de un lote mete una
    #: obra entre los suministros.
    tipos: frozenset[str] = frozenset()
    #: Por defecto, los procedimientos con pliegos que enseñan a redactar: fuera los negociados
    #: sin publicidad (a menudo por exclusividad, con pliegos escuetos), los menores y los
    #: derivados de un acuerdo marco, cuyos pliegos son los del acuerdo.
    procedimientos: frozenset[str] = frozenset({"1", "2", "4", "5", "9", "10"})
    #: Fuera lo anulado y los anuncios previos, que aún no tienen pliegos.
    estados_excluidos: frozenset[str] = frozenset({"ANUL", "PRE"})
    #: Si no está vacío, sólo estos estados. Adjudicado (ADJ) y resuelto (RES) son pliegos que
    #: llegaron al final.
    estados: frozenset[str] = frozenset()
    clases: tuple[str, ...] = ("PPT", "PCAP", "Memoria")


# =============================================================================
#  Leer el feed
# =============================================================================


@dataclass
class Documento:
    clase: str
    nombre: str
    url: str


@dataclass
class Expediente:
    id: str
    actualizado: str
    ficha: str
    expediente: str
    estado: str
    organo: str
    jerarquia: list[str]
    objeto: str
    tipo: str
    cpv: list[str]
    procedimiento: str
    importe: str
    recursos: str
    adjudicatarios: list[str]
    documentos: list[Documento] = field(default_factory=list)
    #: FundingProgramCode: `NO-EU` o el programa europeo. Un contrato de proyecto suele llevarlo.
    fondos: str = ""
    #: Los pone la selección: dependen de la capa en que cae el expediente.
    capa: str = ""
    entidad: str = ""


def _texto(el: ET.Element | None, ruta: str) -> str:
    if el is None:
        return ""
    hallado = el.find(ruta, _NS)
    return (hallado.text or "").strip() if hallado is not None else ""


def _documentos(estado: ET.Element) -> list[Documento]:
    docs: list[Documento] = []
    for etiqueta, clase in (("cac:LegalDocumentReference", "PCAP"), ("cac:TechnicalDocumentReference", "PPT")):
        for ref in estado.findall(etiqueta, _NS):
            url = _texto(ref, "cac:Attachment/cac:ExternalReference/cbc:URI")
            if url:
                docs.append(Documento(clase, _texto(ref, "cbc:ID"), url))
    for ref in estado.findall("cacx:GeneralDocument/cacx:GeneralDocumentDocumentReference", _NS):
        if _texto(ref, "cbc:DocumentTypeCode") == _MEMORIA:
            url = _texto(ref, "cac:Attachment/cac:ExternalReference/cbc:URI")
            if url:
                nombre = _texto(ref, "cac:Attachment/cac:ExternalReference/cbc:FileName")
                docs.append(Documento("Memoria", nombre, url))
    return docs


def _jerarquia(estado: ET.Element) -> list[str]:
    """El órgano y sus ancestros, del más concreto al más general."""
    parte = estado.find("cacx:LocatedContractingParty", _NS)
    if parte is None:
        return []
    nombres = [_texto(parte, "cac:Party/cac:PartyName/cbc:Name")]
    padre = parte.find("cacx:ParentLocatedParty", _NS)
    while padre is not None:
        nombres.append(_texto(padre, "cac:PartyName/cbc:Name"))
        padre = padre.find("cacx:ParentLocatedParty", _NS)
    return [n for n in nombres if n]


def leer_entrada(entrada: ET.Element) -> Expediente | None:
    estado = entrada.find("cacx:ContractFolderStatus", _NS)
    if estado is None:
        return None
    proyecto = estado.find("cac:ProcurementProject", _NS)
    cpv = [c.text.strip() for c in estado.iter("{%s}ItemClassificationCode" % _NS["cbc"]) if c.text]
    enlace = entrada.find("a:link", _NS)
    jerarquia = _jerarquia(estado)
    return Expediente(
        id=_texto(entrada, "a:id"),
        actualizado=_texto(entrada, "a:updated"),
        ficha=enlace.get("href", "") if enlace is not None else "",
        expediente=_texto(estado, "cbc:ContractFolderID"),
        estado=_texto(estado, "cbcx:ContractFolderStatusCode"),
        organo=jerarquia[0] if jerarquia else "",
        jerarquia=jerarquia,
        objeto=_texto(proyecto, "cbc:Name") or _texto(entrada, "a:title"),
        tipo=_texto(proyecto, "cbc:TypeCode"),
        cpv=list(dict.fromkeys(cpv)),
        procedimiento=_texto(estado, "cac:TenderingProcess/cbc:ProcedureCode"),
        importe=_texto(proyecto, "cac:BudgetAmount/cbc:TaxExclusiveAmount"),
        recursos=_texto(estado, "cac:TenderingTerms/cbc:ReceivedAppealQuantity"),
        adjudicatarios=list(
            dict.fromkeys(
                n.text.strip()
                for n in estado.findall("cac:TenderResult/cac:WinningParty/cac:PartyName/cbc:Name", _NS)
                if n.text
            )
        ),
        documentos=_documentos(estado),
        fondos=_texto(estado, "cac:TenderingTerms/cbc:FundingProgramCode"),
    )


def entradas(feed: io.BufferedIOBase | Path | str) -> Iterator[ET.Element]:
    """Las entradas y las lápidas de un feed Atom, de una en una y sin cargarlo entero."""
    for _, el in ET.iterparse(feed, events=("end",)):
        if el.tag in (_ENTRADA, _LAPIDA):
            yield el
            el.clear()


def capa_de(expediente: Expediente, seleccion: Seleccion) -> Capa | None:
    """La capa del expediente si la selección lo quiere; `None` si no."""
    capa = next((c for c in seleccion.capas if c.casa(expediente.jerarquia)), None)
    if capa is None:
        return None
    if seleccion.tipos and expediente.tipo not in seleccion.tipos:
        return None
    if seleccion.estados and expediente.estado not in seleccion.estados:
        return None
    if seleccion.cpv and not any(c.startswith(p) for c in expediente.cpv for p in seleccion.cpv):
        return None
    if expediente.procedimiento not in seleccion.procedimientos:
        return None
    if expediente.estado in seleccion.estados_excluidos:
        return None
    if not any(d.clase in seleccion.clases for d in expediente.documentos):
        return None
    return capa


def extraer(feeds: Iterable[io.BufferedIOBase | Path | str], capas: Iterable[Capa]) -> list[Expediente]:
    """Todos los expedientes de los órganos de las capas, **uno por expediente y en su último
    estado**, con cualquier CPV, tipo o procedimiento: es la pasada pesada, y se hace una vez.

    Un expediente aparece en el feed cada vez que cambia —se publica, se adjudica, se formaliza—,
    así que el mismo identificador viene varias veces, y gana la entrada más reciente. Una lápida
    posterior lo retira.
    """
    capas = tuple(capas)
    ultimos: dict[str, Expediente] = {}
    retirados: dict[str, str] = {}
    for feed in feeds:
        for entrada in entradas(feed):
            if entrada.tag == _LAPIDA:
                ref, cuando = entrada.get("ref", ""), entrada.get("when", "")
                retirados[ref] = max(retirados.get(ref, ""), cuando)
                continue
            # El órgano no cambia entre versiones de un expediente: filtrar por él antes de leer
            # la entrada entera ahorra casi todo el trabajo.
            estado = entrada.find("cacx:ContractFolderStatus", _NS)
            if estado is None or not any(c.casa(_jerarquia(estado)) for c in capas):
                continue
            exp = leer_entrada(entrada)
            if exp is None:
                continue
            previo = ultimos.get(exp.id)
            if previo is None or exp.actualizado > previo.actualizado:
                ultimos[exp.id] = exp
    for ref, cuando in retirados.items():
        if ref in ultimos and cuando >= ultimos[ref].actualizado:
            del ultimos[ref]
    return list(ultimos.values())


def ultimo_estado(*listas: Iterable[Expediente]) -> list[Expediente]:
    """Junta las extracciones de varios periodos: un expediente de 2024 adjudicado en 2025 viene en
    los dos, y gana el estado más reciente."""
    ultimos: dict[str, Expediente] = {}
    for lista in listas:
        for exp in lista:
            previo = ultimos.get(exp.id)
            if previo is None or exp.actualizado > previo.actualizado:
                ultimos[exp.id] = exp
    return list(ultimos.values())


def elegir(expedientes: Iterable[Expediente], seleccion: Seleccion) -> list[Expediente]:
    """Lo que pide la selección, con el tope por entidad de cada capa. Es barato: se pueden probar
    otras familias de CPV sobre la misma extracción sin volver a leer los feeds."""
    por_entidad: dict[tuple[str, str], list[Expediente]] = {}
    topes: dict[str, int | None] = {}
    for exp in expedientes:
        capa = capa_de(exp, seleccion)
        if capa is not None:
            exp.capa, exp.entidad = capa.nombre, capa.entidad(exp.jerarquia)
            topes[capa.nombre] = capa.maximo_por_entidad
            por_entidad.setdefault((capa.nombre, exp.entidad), []).append(exp)
    elegidos = []
    for (capa, _), lista in por_entidad.items():
        lista.sort(key=lambda e: e.actualizado, reverse=True)
        elegidos.extend(lista[: topes[capa]] if topes[capa] is not None else lista)
    return sorted(elegidos, key=lambda e: (e.capa, e.entidad, e.expediente))


def seleccionar(feeds: Iterable[io.BufferedIOBase | Path | str], seleccion: Seleccion) -> list[Expediente]:
    return elegir(extraer(feeds, seleccion.capas), seleccion)


_CAMPOS_EXTRACCION = [
    "id", "actualizado", "ficha", "expediente", "estado", "organo", "jerarquia", "objeto", "tipo",
    "cpv", "procedimiento", "importe", "recursos", "adjudicatarios", "fondos", "documentos",
]
_LISTAS = ("jerarquia", "cpv", "adjudicatarios")


def guardar_extraccion(expedientes: Iterable[Expediente], ruta: Path) -> None:
    """La extracción de un periodo: unos megas frente a los gigas del feed. Las listas van en JSON."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=_CAMPOS_EXTRACCION)
        w.writeheader()
        for e in expedientes:
            fila = {c: getattr(e, c) for c in _CAMPOS_EXTRACCION}
            for c in _LISTAS:
                fila[c] = json.dumps(fila[c], ensure_ascii=False)
            fila["documentos"] = json.dumps([vars(d) for d in e.documentos], ensure_ascii=False)
            w.writerow(fila)


def leer_extraccion(ruta: Path) -> list[Expediente]:
    with ruta.open(encoding="utf-8", newline="") as fh:
        filas = list(csv.DictReader(fh))
    for f in filas:
        for c in _LISTAS:
            f[c] = json.loads(f[c])
        f["documentos"] = [Documento(**d) for d in json.loads(f["documentos"])]
    return [Expediente(**f) for f in filas]


def feeds_de_zip(ruta: Path) -> Iterator[io.BufferedIOBase]:
    with zipfile.ZipFile(ruta) as z:
        for nombre in sorted(z.namelist()):
            if nombre.endswith(".atom"):
                with z.open(nombre) as fh:
                    yield fh


# =============================================================================
#  Descargar
# =============================================================================

#: El guion del índice no resume lo que pase de aquí.
MAXIMO_BYTES = 15 * 1024 * 1024
_PROHIBIDOS = re.compile(r'[\\/:*?"<>|\r\n\t]+')


def nombre_de_fichero(exp: Expediente, clase: str, largo: int = 150) -> str:
    """`[Universidad] Universidad de Burgos – UBU-2025-0024 – Suministro de … – PPT.pdf`."""
    objeto = _PROHIBIDOS.sub(" ", exp.objeto).strip()
    cabeza = _PROHIBIDOS.sub(" ", f"[{exp.capa}] {exp.entidad} – {exp.expediente.replace('/', '-')} – ")
    cola = f" – {clase}.pdf"
    sitio = max(20, largo - len(cabeza) - len(cola))
    if len(objeto) > sitio:
        objeto = objeto[: sitio - 1].rstrip() + "…"
    return re.sub(r"\s+", " ", cabeza + objeto + cola).strip()


def _http(url: str) -> bytes:
    peticion = urllib.request.Request(url, headers={"User-Agent": "govgenai-pliegos/1 (ejemplo)"})
    with urllib.request.urlopen(peticion, timeout=120) as r:
        return r.read()


@dataclass
class Resultado:
    expediente: Expediente
    clase: str
    fichero: str
    estado: str  # guardado | ya_estaba | no_es_pdf | demasiado_grande | error: …


def descargar(
    expedientes: Iterable[Expediente],
    carpeta: Path,
    clases: Iterable[str],
    *,
    obtener: Callable[[str], bytes] = _http,
    pausa: float = 0.5,
) -> list[Resultado]:
    """Guarda en `carpeta` los documentos de cada expediente. **Lo que ya está no se vuelve a pedir**,
    así que se puede relanzar tras un corte. Un expediente con dos PPT —lotes— guarda los dos."""
    carpeta.mkdir(parents=True, exist_ok=True)
    clases = tuple(clases)
    resultados: list[Resultado] = []
    for exp in expedientes:
        vistos: dict[str, int] = {}
        for doc in exp.documentos:
            if doc.clase not in clases:
                continue
            vistos[doc.clase] = vistos.get(doc.clase, 0) + 1
            clase = doc.clase if vistos[doc.clase] == 1 else f"{doc.clase} {vistos[doc.clase]}"
            nombre = nombre_de_fichero(exp, clase)
            destino = carpeta / nombre
            if destino.exists():
                resultados.append(Resultado(exp, clase, nombre, "ya_estaba"))
                continue
            try:
                contenido = obtener(doc.url)
            except Exception as e:  # noqa: BLE001 — un documento caído no para la descarga
                resultados.append(Resultado(exp, clase, nombre, f"error: {e}"))
                continue
            if not contenido.startswith(b"%PDF"):
                estado = "no_es_pdf"
            elif len(contenido) > MAXIMO_BYTES:
                estado = "demasiado_grande"
            else:
                destino.write_bytes(contenido)
                estado = "guardado"
            resultados.append(Resultado(exp, clase, nombre, estado))
            if pausa:
                time.sleep(pausa)
    return resultados


# =============================================================================
#  La tabla de expedientes
# =============================================================================

COLUMNAS = [
    "capa",
    "entidad",
    "organo",
    "expediente",
    "objeto",
    "tipo_de_contrato",
    "cpv",
    "procedimiento",
    "importe_sin_iva",
    "estado",
    "recursos",
    "adjudicatarios",
    "ficha_placsp",
    "url_pcap",
    "url_ppt",
    "url_memoria",
]


def escribir_tabla(expedientes: Iterable[Expediente], ruta: Path) -> None:
    """Una fila por expediente. **Va fuera de la carpeta del agente**: dentro sería un documento más."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNAS)
        w.writeheader()
        for e in expedientes:
            primera = {c: next((d.url for d in e.documentos if d.clase == c), "") for c in CLASES}
            w.writerow(
                {
                    "capa": e.capa,
                    "entidad": e.entidad,
                    "organo": e.organo,
                    "expediente": e.expediente,
                    "objeto": e.objeto,
                    "tipo_de_contrato": TIPOS.get(e.tipo, "Otros"),
                    "cpv": " ".join(e.cpv),
                    "procedimiento": PROCEDIMIENTOS.get(e.procedimiento, e.procedimiento),
                    "importe_sin_iva": e.importe,
                    "estado": e.estado,
                    "recursos": e.recursos,
                    "adjudicatarios": "; ".join(e.adjudicatarios),
                    "ficha_placsp": e.ficha,
                    "url_pcap": primera["PCAP"],
                    "url_ppt": primera["PPT"],
                    "url_memoria": primera["Memoria"],
                }
            )


# =============================================================================
#  Todo junto
# =============================================================================


def bajar_zip(fuente: str, periodo: str, cache: Path) -> Path:
    """El ZIP de un periodo, **a disco y no a memoria**: un año pesa casi dos gigas."""
    cache.mkdir(parents=True, exist_ok=True)
    ruta = cache / f"{fuente}_{periodo}.zip"
    if not ruta.exists():
        parcial = ruta.with_suffix(".parcial")
        peticion = urllib.request.Request(
            FUENTES[fuente].format(periodo=periodo), headers={"User-Agent": "govgenai-pliegos/1 (ejemplo)"}
        )
        with urllib.request.urlopen(peticion, timeout=600) as r, parcial.open("wb") as fh:
            shutil.copyfileobj(r, fh, 1024 * 1024)
        parcial.rename(ruta)
    return ruta


def extraccion(fuente: str, periodo: str, capas: Iterable[Capa], cache: Path, *, conservar_zip: bool = False) -> list[Expediente]:
    """La extracción de un periodo, **hecha una sola vez**: si ya está en `cache`, se lee.

    Lo que se queda es la extracción, unos megas; el ZIP se borra al terminar salvo que se pida
    conservarlo. Para extraer con otras capas, se borra la extracción y se vuelve a lanzar.
    """
    ruta = cache / f"extraccion_{fuente}_{periodo}.csv"
    if ruta.exists():
        return leer_extraccion(ruta)
    zip_ = bajar_zip(fuente, periodo, cache)
    expedientes = extraer(feeds_de_zip(zip_), capas)
    guardar_extraccion(expedientes, ruta)
    if not conservar_zip:
        zip_.unlink()
    return expedientes


def ejecutar(seleccion: Seleccion, carpeta: Path, tabla: Path, cache: Path) -> list[Resultado]:
    extracciones = []
    for fuente in seleccion.fuentes:
        for periodo in seleccion.periodos:
            extracciones.append(extraccion(fuente, periodo, seleccion.capas, cache))
            print(f"extraído {fuente} {periodo}: {len(extracciones[-1])} expedientes")
    expedientes = elegir(ultimo_estado(*extracciones), seleccion)
    escribir_tabla(expedientes, tabla)
    resultados = descargar(expedientes, carpeta, seleccion.clases)
    print(f"{len(expedientes)} expedientes; documentos:")
    for estado in sorted({r.estado.split(":")[0] for r in resultados}):
        print(f"  {estado}: {sum(r.estado.split(':')[0] == estado for r in resultados)}")
    return resultados


# =============================================================================
#  La selección de la UJI, como ejemplo
# =============================================================================

#: Piloto de equipamiento científico: suministros con CPV 38 (equipos de laboratorio, ópticos y
#: de precisión), adjudicados o resueltos, desde 2022 —años cerrados como `AAAA`, el año en curso
#: por meses—. Tres capas, en este orden:
#:
#: * **UJI**, todo: es el estilo de la casa. Va primero porque también es una universidad.
#: * **Universidad**, las públicas por el nodo de la jerarquía, **dos por universidad**: variedad
#:   sin que las que más licitan llenen la carpeta.
#: * **CSIC**, que compra el mismo equipamiento, **los diez más recientes**.
#:
#: PPT y memoria justificativa, no el PCAP: el de cada universidad varía poco entre expedientes, y
#: el modelo de PCAP entra aparte, como ficha prioritaria (#223).
SELECCION_UJI = Seleccion(
    capas=(
        Capa("UJI", contiene=("Universidad Jaume I", "Universitat Jaume I")),
        # En PLACSP cuelgan del nodo «UNIVERSIDADES»; en las plataformas agregadas, las catalanas
        # de «Universitats» y otras de ninguno, así que también por el nombre, en las cuatro lenguas.
        Capa(
            "Universidad",
            ancestros=frozenset({"UNIVERSIDADES", "Universitats"}),
            empieza=("Universidad", "Universitat", "Universidade", "Unibertsitatea", "UPV/EHU"),
            maximo_por_entidad=2,
        ),
        Capa("CSIC", contiene=("Consejo Superior de Investigaciones Científicas",), maximo_por_entidad=10, alias="CSIC"),
    ),
    periodos=("2022", "2023", "2024", "2025") + tuple(f"2026{m:02d}" for m in range(1, 10)),
    cpv=("38",),
    tipos=frozenset({"1"}),
    estados=frozenset({"ADJ", "RES"}),
    clases=("PPT", "Memoria"),
)


# =============================================================================
#  Desde la línea de órdenes
# =============================================================================


def main(argv: list[str] | None = None) -> None:
    import argparse

    p = argparse.ArgumentParser(description="Pliegos de PLACSP para la carpeta de un agente de pliegos.")
    p.add_argument("--carpeta", type=Path, required=True, help="la carpeta del agente (la que lee el guion)")
    p.add_argument("--tabla", type=Path, required=True, help="el CSV de expedientes, FUERA de la carpeta")
    p.add_argument("--cache", type=Path, default=Path("placsp_zips"), help="dónde se guardan los ZIP")
    p.add_argument("--periodos", nargs="*", help="AAAA o AAAAMM; por defecto, los de la selección")
    a = p.parse_args(argv)
    seleccion = SELECCION_UJI
    if a.periodos:
        from dataclasses import replace

        seleccion = replace(seleccion, periodos=tuple(a.periodos))
    if a.carpeta.resolve() in a.tabla.resolve().parents:
        p.error("la tabla no puede ir dentro de la carpeta: el guion la contaría como un documento")
    ejecutar(seleccion, a.carpeta, a.tabla, a.cache)


if __name__ == "__main__":
    main()
