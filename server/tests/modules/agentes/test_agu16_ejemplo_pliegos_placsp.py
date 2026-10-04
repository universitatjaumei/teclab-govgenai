"""El ejemplo que llena la carpeta de un agente de pliegos con los datos abiertos de PLACSP.

Vive en `docs/ejemplos/agentes/pliegos/`: es de la UJI en su selección y de cualquiera en lo
demás. Estas pruebas usan un feed **sintético** con la forma del real (CODICE, Atom con lápidas) y
nunca salen a la red: la descarga recibe la función que trae los bytes.

Lo que fijan es lo que hace que la carpeta sirva al guion del índice (#174): un expediente en su
último estado, sólo PDF y de hasta 15 MB, un nombre que dice la capa y de dónde viene, y relanzar
sin volver a pedir lo que ya está.
"""
from __future__ import annotations

import csv
import importlib.util
import io
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[4]
RUTA = RAIZ / "docs" / "ejemplos" / "agentes" / "pliegos" / "descarga_placsp.py"


def _modulo():
    spec = importlib.util.spec_from_file_location("descarga_placsp", RUTA)
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["descarga_placsp"] = modulo
    spec.loader.exec_module(modulo)
    return modulo


d = _modulo()

_CABECERA = (
    '<feed xmlns="http://www.w3.org/2005/Atom" '
    'xmlns:cbc-place-ext="urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonBasicComponents-2" '
    'xmlns:cbc="urn:dgpe:names:draft:codice:schema:xsd:CommonBasicComponents-2" '
    'xmlns:cac="urn:dgpe:names:draft:codice:schema:xsd:CommonAggregateComponents-2" '
    'xmlns:cac-place-ext="urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonAggregateComponents-2" '
    'xmlns:at="http://purl.org/atompub/tombstones/1.0">'
)


def _entrada(
    n: int,
    *,
    organo: str = "Rectorado de la Universidad de Burgos",
    ancestros: tuple[str, ...] = ("Universidad de Burgos", "Castilla y León", "UNIVERSIDADES"),
    actualizado: str = "2025-09-30T08:00:00+02:00",
    estado: str = "ADJ",
    tipo: str = "1",
    cpv: str = "38432000",
    cpv_lote: str | None = None,
    procedimiento: str = "1",
    ppt: int = 1,
    memoria: bool = True,
    objeto: str = "Suministro de un espectrómetro",
) -> str:
    padres = ""
    for nombre in reversed(ancestros):
        padres = (
            f"<cac-place-ext:ParentLocatedParty><cac:PartyName><cbc:Name>{nombre}</cbc:Name></cac:PartyName>"
            f"{padres}</cac-place-ext:ParentLocatedParty>"
        )
    lote = (
        f"<cac:ProcurementProjectLot><cac:ProcurementProject><cac:RequiredCommodityClassification>"
        f"<cbc:ItemClassificationCode>{cpv_lote}</cbc:ItemClassificationCode>"
        f"</cac:RequiredCommodityClassification></cac:ProcurementProject></cac:ProcurementProjectLot>"
        if cpv_lote
        else ""
    )
    ppts = "".join(
        f"<cac:TechnicalDocumentReference><cbc:ID>ppt{i}.pdf</cbc:ID><cac:Attachment><cac:ExternalReference>"
        f"<cbc:URI>https://placsp/doc?ppt={n}-{i}</cbc:URI></cac:ExternalReference></cac:Attachment>"
        f"</cac:TechnicalDocumentReference>"
        for i in range(1, ppt + 1)
    )
    generales = (
        "<cac-place-ext:GeneralDocument><cac-place-ext:GeneralDocumentDocumentReference>"
        "<cbc:DocumentTypeCode>11</cbc:DocumentTypeCode><cac:Attachment><cac:ExternalReference>"
        f"<cbc:URI>https://placsp/doc?aprobacion={n}</cbc:URI></cac:ExternalReference></cac:Attachment>"
        "</cac-place-ext:GeneralDocumentDocumentReference></cac-place-ext:GeneralDocument>"
    )
    if memoria:
        generales += (
            "<cac-place-ext:GeneralDocument><cac-place-ext:GeneralDocumentDocumentReference>"
            "<cbc:DocumentTypeCode>9</cbc:DocumentTypeCode><cac:Attachment><cac:ExternalReference>"
            f"<cbc:URI>https://placsp/doc?memoria={n}</cbc:URI><cbc:FileName>Memoria justificativa</cbc:FileName>"
            "</cac:ExternalReference></cac:Attachment>"
            "</cac-place-ext:GeneralDocumentDocumentReference></cac-place-ext:GeneralDocument>"
        )
    return f"""
<entry>
  <id>https://placsp/licitacion/{n}</id>
  <link href="https://placsp/ficha/{n}"/>
  <title>{objeto}</title>
  <updated>{actualizado}</updated>
  <cac-place-ext:ContractFolderStatus>
    <cbc:ContractFolderID>EXP/2025/{n}</cbc:ContractFolderID>
    <cbc-place-ext:ContractFolderStatusCode>{estado}</cbc-place-ext:ContractFolderStatusCode>
    <cac-place-ext:LocatedContractingParty>
      <cac:Party><cac:PartyName><cbc:Name>{organo}</cbc:Name></cac:PartyName></cac:Party>
      {padres}
    </cac-place-ext:LocatedContractingParty>
    <cac:ProcurementProject>
      <cbc:Name>{objeto}</cbc:Name>
      <cbc:TypeCode>{tipo}</cbc:TypeCode>
      <cac:BudgetAmount><cbc:TaxExclusiveAmount currencyID="EUR">90000</cbc:TaxExclusiveAmount></cac:BudgetAmount>
      <cac:RequiredCommodityClassification><cbc:ItemClassificationCode>{cpv}</cbc:ItemClassificationCode></cac:RequiredCommodityClassification>
    </cac:ProcurementProject>
    {lote}
    <cac:TenderingTerms><cbc:ReceivedAppealQuantity>0</cbc:ReceivedAppealQuantity></cac:TenderingTerms>
    <cac:TenderingProcess><cbc:ProcedureCode>{procedimiento}</cbc:ProcedureCode></cac:TenderingProcess>
    <cac:LegalDocumentReference><cbc:ID>pcap.pdf</cbc:ID><cac:Attachment><cac:ExternalReference>
      <cbc:URI>https://placsp/doc?pcap={n}</cbc:URI></cac:ExternalReference></cac:Attachment></cac:LegalDocumentReference>
    {ppts}
    <cac:TenderResult><cac:WinningParty><cac:PartyName><cbc:Name>Óptica S.L.</cbc:Name></cac:PartyName></cac:WinningParty></cac:TenderResult>
    {generales}
  </cac-place-ext:ContractFolderStatus>
</entry>"""


def _feed(*cuerpo: str) -> io.BytesIO:
    return io.BytesIO((_CABECERA + "".join(cuerpo) + "</feed>").encode("utf-8"))


SEL = d.Seleccion(
    capas=(
        d.Capa("UJI", contiene=("Universitat Jaume I",)),
        d.Capa(
            "Universidad",
            ancestros=frozenset({"UNIVERSIDADES", "Universitats"}),
            empieza=("Universidad", "Universitat", "UPV/EHU"),
        ),
        d.Capa("CSIC", contiene=("Consejo Superior de Investigaciones Científicas",), alias="CSIC"),
    ),
    periodos=("2025",),
    cpv=("38",),
    tipos=frozenset({"1"}),
    estados=frozenset({"ADJ", "RES"}),
    clases=("PPT", "Memoria"),
)


def _ids(expedientes) -> list[str]:
    return [e.expediente.rsplit("/", 1)[-1] for e in expedientes]


class TestLaSeleccion:

    def test_las_universidades_por_el_nodo_de_la_jerarquia(self):
        otra = _entrada(2, organo="Alcaldía", ancestros=("Ayuntamiento de Burgos", "ENTIDADES LOCALES"))
        [exp] = d.seleccionar([_feed(_entrada(1), otra)], SEL)
        assert (exp.capa, exp.entidad) == ("Universidad", "Universidad de Burgos")

    @pytest.mark.parametrize(
        "organo,ancestros,entidad",
        [
            # Plataforma catalana agregada: cuelga de «Universitats», sin nodo «UNIVERSIDADES».
            ("Universitat de Barcelona", ("Universitats",), "Universitat de Barcelona"),
            # Sin nodo: casa por el nombre, y la entidad es el nombre más general que casa.
            (
                "UPV/EHU - Universidad del País Vasco-La Gerente",
                ("UPV/EHU - Universidad del País Vasco", "Campus de Bizkaia"),
                "UPV/EHU - Universidad del País Vasco",
            ),
            # Una fundación bajo el nodo: casa por el nodo, y la entidad es ella misma.
            ("Fundació Josep Finestres", ("Universitats",), "Fundació Josep Finestres"),
        ],
    )
    def test_las_plataformas_agregadas(self, organo, ancestros, entidad):
        [exp] = d.seleccionar([_feed(_entrada(1, organo=organo, ancestros=ancestros))], SEL)
        assert (exp.capa, exp.entidad) == ("Universidad", entidad)

    @pytest.mark.parametrize(
        "organo",
        [
            "Consejería de Educación, Ciencia y Universidades",  # «Universidad» no es «Universidades»
            "Delegación Territorial de Universidad, Investigación e Innovación",  # no empieza por ello
        ],
    )
    def test_el_nombre_casa_por_el_principio_y_como_palabra(self, organo):
        assert d.seleccionar([_feed(_entrada(1, organo=organo, ancestros=("Junta de Andalucía",)))], SEL) == []

    def test_las_capas_se_prueban_en_orden(self):
        """La UJI también es una universidad: va a su capa porque se prueba antes."""
        uji = _entrada(1, organo="Rectorado de la Universitat Jaume I", ancestros=("Universitat Jaume I", "UNIVERSIDADES"))
        [exp] = d.seleccionar([_feed(uji)], SEL)
        assert exp.capa == "UJI"

    def test_el_alias_acorta_la_entidad(self):
        csic = _entrada(1, organo="Presidencia", ancestros=("Agencia Estatal Consejo Superior de Investigaciones Científicas",))
        [exp] = d.seleccionar([_feed(csic)], SEL)
        assert exp.entidad == "CSIC"

    def test_el_cpv_casa_por_prefijo_tambien_en_un_lote(self):
        feed = _feed(_entrada(1, cpv="30200000", cpv_lote="38540000"), _entrada(2, cpv="30200000"))
        assert _ids(d.seleccionar([feed], SEL)) == ["1"]

    @pytest.mark.parametrize(
        "cambio",
        [
            {"tipo": "3"},  # una obra con un lote de CPV 38
            {"procedimiento": "3"},  # negociado sin publicidad
            {"procedimiento": "7"},  # derivado de acuerdo marco
            {"estado": "EV"},  # sin adjudicar
            {"ppt": 0, "memoria": False},  # sin documentos que se quieran
        ],
    )
    def test_lo_que_no_se_quiere(self, cambio):
        assert d.seleccionar([_feed(_entrada(1, **cambio))], SEL) == []

    def test_gana_el_ultimo_estado_de_cada_expediente(self):
        """El mismo expediente viene en cada cambio, y en cualquier orden entre ficheros."""
        nuevo = _entrada(1, actualizado="2025-10-01T00:00:00+02:00", estado="RES")
        viejo = _entrada(1, actualizado="2025-06-01T00:00:00+02:00", estado="ADJ")
        [exp] = d.seleccionar([_feed(nuevo), _feed(viejo)], SEL)
        assert exp.estado == "RES"

    def test_el_ultimo_estado_decide_aunque_saque_el_expediente(self):
        anulado = _entrada(1, actualizado="2025-10-01T00:00:00+02:00", estado="ANUL")
        assert d.seleccionar([_feed(_entrada(1), anulado)], SEL) == []

    def test_una_lapida_retira_el_expediente(self):
        lapida = '<at:deleted-entry ref="https://placsp/licitacion/1" when="2025-10-02T00:00:00+02:00"/>'
        assert d.seleccionar([_feed(_entrada(1), lapida)], SEL) == []

    def test_el_tope_por_entidad_se_queda_con_los_mas_recientes(self):
        import dataclasses

        sel = dataclasses.replace(SEL, capas=(d.Capa("Universidad", empieza=("Universidad",), maximo_por_entidad=2),))
        feed = _feed(
            *(_entrada(n, actualizado=f"2025-0{n}-01T00:00:00+02:00") for n in range(1, 5)),
            _entrada(9, ancestros=("Universidad de León", "UNIVERSIDADES")),
        )
        assert sorted(_ids(d.seleccionar([feed], sel))) == ["3", "4", "9"]

    def test_la_memoria_es_el_documento_general_de_codigo_9(self):
        [exp] = d.seleccionar([_feed(_entrada(1))], SEL)
        assert [(x.clase, x.url) for x in exp.documentos] == [
            ("PCAP", "https://placsp/doc?pcap=1"),
            ("PPT", "https://placsp/doc?ppt=1-1"),
            ("Memoria", "https://placsp/doc?memoria=1"),
        ]


def _pdf(tamano: int = 100) -> bytes:
    return b"%PDF-1.7" + b"0" * tamano


class TestLaDescarga:

    def _exp(self, **cambio):
        [exp] = d.seleccionar([_feed(_entrada(1, **cambio))], SEL)
        return exp

    def test_el_nombre_dice_la_capa_y_de_donde_viene(self):
        nombre = d.nombre_de_fichero(self._exp(), "PPT")
        assert nombre == "[Universidad] Universidad de Burgos – EXP-2025-1 – Suministro de un espectrómetro – PPT.pdf"

    def test_un_objeto_largo_se_corta_y_no_lleva_barras(self):
        nombre = d.nombre_de_fichero(self._exp(objeto="Suministro / instalación: " + "equipo " * 60), "Memoria")
        assert len(nombre) <= 150
        assert nombre.endswith("… – Memoria.pdf")
        assert "/" not in nombre and ":" not in nombre

    def test_guarda_los_pdf_y_anota_lo_demas(self, tmp_path):
        respuestas = {
            "https://placsp/doc?ppt=1-1": _pdf(),
            "https://placsp/doc?ppt=1-2": b"PK\x03\x04 un zip",
            "https://placsp/doc?memoria=1": _pdf(d.MAXIMO_BYTES),
        }
        resultados = d.descargar([self._exp(ppt=2)], tmp_path, ("PPT", "Memoria"), obtener=respuestas.__getitem__, pausa=0)
        assert [(r.clase, r.estado) for r in resultados] == [
            ("PPT", "guardado"),
            ("PPT 2", "no_es_pdf"),
            ("Memoria", "demasiado_grande"),
        ]
        assert [p.name for p in tmp_path.iterdir()] == [resultados[0].fichero]

    def test_un_documento_caido_no_para_la_descarga(self, tmp_path):
        def obtener(url: str) -> bytes:
            if "ppt" in url:
                raise OSError("503")
            return _pdf()

        resultados = d.descargar([self._exp()], tmp_path, ("PPT", "Memoria"), obtener=obtener, pausa=0)
        assert [r.estado for r in resultados] == ["error: 503", "guardado"]

    def test_relanzar_no_vuelve_a_pedir_lo_que_ya_esta(self, tmp_path):
        pedidas: list[str] = []

        def obtener(url: str) -> bytes:
            pedidas.append(url)
            return _pdf()

        d.descargar([self._exp()], tmp_path, ("PPT",), obtener=obtener, pausa=0)
        segunda = d.descargar([self._exp()], tmp_path, ("PPT",), obtener=obtener, pausa=0)
        assert len(pedidas) == 1
        assert [r.estado for r in segunda] == ["ya_estaba"]


def test_la_tabla_usa_las_opciones_del_agente(tmp_path):
    """El tipo de contrato sale con la etiqueta de las opciones del dato «Tipo de contrato»."""
    ruta = tmp_path / "fuera" / "expedientes.csv"
    d.escribir_tabla(d.seleccionar([_feed(_entrada(1))], SEL), ruta)
    with ruta.open(encoding="utf-8-sig") as fh:
        [fila] = list(csv.DictReader(fh))
    assert fila["tipo_de_contrato"] == "Suministros"
    assert fila["procedimiento"] == "Abierto"
    assert fila["url_memoria"] == "https://placsp/doc?memoria=1"
    assert fila["adjudicatarios"] == "Óptica S.L."


class TestLaExtraccion:
    """La pasada pesada se hace una vez por periodo; elegir familias sobre ella es barato."""

    def test_extraer_guarda_cualquier_cpv_y_tipo(self):
        obra = _entrada(2, tipo="3", cpv="45000000", procedimiento="3", estado="EV")
        assert sorted(_ids(d.extraer([_feed(_entrada(1), obra)], SEL.capas))) == ["1", "2"]

    def test_se_guarda_y_se_lee_igual(self, tmp_path):
        ruta = tmp_path / "extraccion.csv"
        extraidos = d.extraer([_feed(_entrada(1, ppt=2), _entrada(2, memoria=False))], SEL.capas)
        d.guardar_extraccion(extraidos, ruta)
        assert d.leer_extraccion(ruta) == extraidos

    def test_elegir_sobre_la_extraccion_es_seleccionar(self, tmp_path):
        cuerpo = [_entrada(1), _entrada(2, cpv="30200000"), _entrada(3, estado="EV")]
        ruta = tmp_path / "extraccion.csv"
        d.guardar_extraccion(d.extraer([_feed(*cuerpo)], SEL.capas), ruta)
        assert _ids(d.elegir(d.leer_extraccion(ruta), SEL)) == _ids(d.seleccionar([_feed(*cuerpo)], SEL)) == ["1"]

    def test_entre_periodos_gana_el_estado_mas_reciente(self):
        en_2024 = d.extraer([_feed(_entrada(1, estado="EV", actualizado="2024-12-01T00:00:00+01:00"))], SEL.capas)
        en_2025 = d.extraer([_feed(_entrada(1, estado="RES", actualizado="2025-02-01T00:00:00+01:00"))], SEL.capas)
        [exp] = d.ultimo_estado(en_2025, en_2024)
        assert exp.estado == "RES"
