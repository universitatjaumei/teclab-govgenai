"""Contrato del escenario de evaluación enriquecido (HIB.G). Deploy: edge.

**Por qué existe.** Hasta HIB.G los dos lotes de evaluación no se podían medir sin una persona
delante: el de Normativa lleva la fuente esperada **en prosa** (`expectation_note`, que
`HubTestScenario` documenta a propósito como no comprobable automáticamente) y el de Gerencia son
siete consultas con nada más que nombre y texto. Consecuencia práctica: cada ablación —reranker
sí o no, padre sí o no, umbral tal o cual— exigía volver a pedir juicio humano sobre las mismas
preguntas, y por eso las ablaciones no se hacían.

Con la fuente esperada **estructurada** —documento y ancla— tres cosas pasan a calcularse solas:
si el documento que el informador esperaba entró en lo recuperado, si el ancla de la cita apunta
al artículo correcto, y si un negativo se rechazó como debía. Eso es lo que hace las ablaciones
asequibles, y es además lo que convierte el lote en juicios de relevancia, que es la forma que
tiene que tener un banco de recuperación publicable.

**`expectation_note` no se sustituye, se acompaña.** Sigue siendo la nota que lee quien juzga, y
su valor —el veredicto del informador con el motivo del fallo— es irreemplazable. Lo estructurado
se añade al lado.

**La procedencia viaja con cada escenario, y no es burocracia.** Una pregunta escrita mirando el
artículo comparte su vocabulario con la norma e infla la recuperación léxica: es la diferencia
entre un lote de preguntas reales y uno generado. Y una fuente esperada anotada por quien afinó
el sistema no es evidencia independiente. Sin la columna de procedencia, esas dos cosas se
confunden con las demás en cuanto alguien saca una media.
"""
from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, model_validator

from server.app.core.lengua_del_corpus import codi_del_corpus


class Kind(StrEnum):
    """Qué tipo de recuperación exige la pregunta.

    `StrEnum` y no tabla: son pocos, estables, y cada valor tiene consumidor en el análisis
    (añadir uno exige de todos modos código que lo agrupe). El vocabulario de ámbitos y
    submaterias del corpus es lo contrario y por eso vive en tabla — ver CLAUDE.md §5.
    """

    ARTICULO_UNICO = "articulo_unico"
    VARIOS_ARTICULOS = "varios_articulos"
    TABLA_O_DATO = "tabla_o_dato"
    SEGUIMIENTO = "seguimiento"
    NEGATIVO = "negativo"


class RefusalReason(StrEnum):
    """Por qué una pregunta no debe contestarse."""

    FUERA_DE_ALCANCE = "fuera_de_alcance"
    PREMISA_FALSA = "premisa_falsa"
    """La pregunta da por hecho algo que no es cierto **y la correccion no se puede
    fundamentar en el corpus** — casi siempre porque hay que probar una inexistencia («que
    examen propio de acceso hace la UJI», y no hace ninguno).

    Cuando el hecho que refuta la premisa SI esta en el corpus, el escenario **no es esto**:
    es contestable con `debe_refutar=True` y la fuente que lo refuta. Medido el 2026-08-27,
    confundir las dos cosas costo dos falsos fallos: a «puedo partir una factura de 60.000 en
    cuatro de 15.000» el asistente contesto «no, el art. 99.2 lo prohibe expresamente», que es
    la respuesta ideal, y la metrica lo conto como no haberse rendido."""
    VIGENCIA_NO_VALIDADA = "vigencia_no_validada"
    DATO_NO_NORMATIVO = "dato_no_normativo"


class Provenance(StrEnum):
    """De dónde salió la pregunta y quién anotó lo que se espera de ella."""

    REAL = "real"
    """Pregunta que hizo una persona de verdad, y veredicto de informador."""

    INFORMADOR = "informador"
    """La escribió un informador para el lote; sigue siendo juicio profesional."""

    EQUIPO_PROVISIONAL = "equipo_provisional"
    """La anotó quien desarrolla. **No es evidencia independiente**: sirve para afinar y
    ninguna cifra que dependa de ella se publica sin que un informador la confirme."""

    SINTETICO = "sintetico"
    """Escrita a propósito para cubrir un caso —casi siempre un negativo— que los usuarios
    no producen en cantidad suficiente."""


class ExpectedSource(BaseModel):
    """Un documento del corpus, y el artículo dentro de él.

    `canonical_url` o `document_id`, al menos uno: el identificador es estable dentro de esta
    base pero no viaja entre entornos, y la URL canónica sí. El ancla es del **artículo**, que
    es la unidad que un jurista cita y la que PUB.3 abre.
    """

    document_id: str | None = None
    canonical_url: str | None = None
    anchor: str | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _identifica_el_documento(self) -> ExpectedSource:
        if not self.document_id and not self.canonical_url:
            raise ValueError(
                "una fuente esperada necesita `document_id` o `canonical_url`"
            )
        # HIB.H — el título de la norma escrito a mano no es un identificador. Casa con nada,
        # así que la fuente esperada nunca aparecería «en lo recuperado» y el fallo se leería
        # como un fallo de recuperación: se pierde la métrica sin dar ningún error. En la UI
        # esto se elige del corpus; aquí se rechaza la forma.
        if self.canonical_url and not self.canonical_url.startswith(
            ("http://", "https://")
        ):
            raise ValueError(
                "`canonical_url` tiene que ser una URL; el documento se elige del corpus, "
                "no se escribe a mano"
            )
        return self


class ExpectedSources(BaseModel):
    """Los dos conjuntos, y son distintos a propósito.

    `required`: sin ellos la respuesta es incorrecta, por completa que parezca.
    `acceptable`: pueden salir sin penalizar —una norma de rango superior que el artículo
    invoca, una versión idiomática— pero su ausencia no es un fallo.

    Sin esa distinción sólo hay dos opciones malas: exigir un conjunto exacto (y contar como
    error toda cita legítima de más) o no exigir nada.
    """

    required: list[ExpectedSource] = Field(default_factory=list)
    acceptable: list[ExpectedSource] = Field(default_factory=list)


class Escenario(BaseModel):
    """Un escenario del lote de evaluación."""

    name: str
    prompt: str
    history: list[str] | None = None
    expectation_note: str | None = None
    meta: dict | None = None

    expected_sources: ExpectedSources | None = None
    answerable: bool = True
    refusal_reason: RefusalReason | None = None
    kind: Kind
    language: str
    domain: str | None = None
    provenance: Provenance
    reference_answer: str | None = None

    debe_refutar: bool = False
    """La respuesta correcta **niega la premisa de la pregunta** citando lo que la refuta.

    Es contestable —no se rinde— pero contestar «si» seria el fallo grave. Sin este campo el
    caso solo se podia expresar como negativo, y entonces la unica respuesta correcta posible
    contaba como error."""

    @model_validator(mode="after")
    def _coherencia(self) -> Escenario:
        if self.debe_refutar and not self.answerable:
            raise ValueError(
                "`debe_refutar` es para escenarios CONTESTABLES: refutar es contestar. Si la "
                "correccion no se puede fundamentar, el escenario es un negativo con "
                "`refusal_reason=premisa_falsa`"
            )
        # ACT.2: el codigo del valenciano en este sistema es `val`, el del corpus. Se sigue
        # aceptando `ca` —los lotes de `_local/golden/` estan escritos asi y son el instrumento
        # de medida, no se invalidan por un cambio de vocabulario— pero se normaliza, para que
        # el recuento por lengua del informe no parta en dos la misma lengua.
        object.__setattr__(self, "language", codi_del_corpus(self.language))
        if self.language not in ("val", "es"):
            raise ValueError("`language` tiene que ser 'val' o 'es'")

        if self.answerable:
            # Sin fuente esperada no hay precisión de cita: sólo opinión. Es la razón de ser
            # de este contrato, así que se exige aquí y no en una comprobación aparte que
            # alguien pueda saltarse.
            if not self.expected_sources or not self.expected_sources.required:
                raise ValueError(
                    f"{self.name}: un escenario contestable necesita al menos una fuente "
                    "esperada en `required`"
                )
            if self.refusal_reason is not None:
                raise ValueError(
                    f"{self.name}: `refusal_reason` sólo tiene sentido si `answerable` es falso"
                )
        else:
            if self.refusal_reason is None:
                raise ValueError(
                    f"{self.name}: un escenario no contestable necesita `refusal_reason`; sin "
                    "él no se puede distinguir un silencio correcto de una avería"
                )
            if self.expected_sources and self.expected_sources.required:
                raise ValueError(
                    f"{self.name}: un escenario no contestable no puede exigir fuentes"
                )

        if self.kind is Kind.SEGUIMIENTO and not self.history:
            raise ValueError(
                f"{self.name}: un escenario de seguimiento necesita `history`"
            )
        return self


class Lote(BaseModel):
    """El lote entero, con lo que hay que saber antes de leer cualquier cifra suya."""

    name: str
    description: str | None = None
    # La taxonomía de modos de fallo del lote de 25 (curso_caducado, ambito_equivocado...).
    # Se conserva tal cual: es la mejor parte de aquel lote y no se reescribe.
    failure_modes: dict | None = None
    verdict_legend: dict | None = None
    source_document: str | None = None
    corpus_reference: str | None = None
    # HIB.G — el lote AFINA la configuración; el piloto INFORMA. Si se elige `top_k` y umbral
    # sobre estas consultas y después se reporta la calidad sobre las mismas, es conjunto de
    # entrenamiento y la cifra no vale. Queda escrito aquí para que viaje con los datos.
    uso: str = "afinado"
    scenarios: list[Escenario]

    def composicion(self) -> dict:
        """Reparto por cada eje que condiciona lo que el lote puede medir."""
        def _cuenta(clave):
            salida: dict = {}
            for e in self.scenarios:
                v = clave(e)
                salida[str(v)] = salida.get(str(v), 0) + 1
            return dict(sorted(salida.items()))

        return {
            "total": len(self.scenarios),
            "kind": _cuenta(lambda e: e.kind),
            "language": _cuenta(lambda e: e.language),
            "domain": _cuenta(lambda e: e.domain),
            "provenance": _cuenta(lambda e: e.provenance),
            "answerable": _cuenta(lambda e: e.answerable),
            "con_fuente_requerida": sum(
                1
                for e in self.scenarios
                if e.expected_sources and e.expected_sources.required
            ),
            "con_ancla": sum(
                1
                for e in self.scenarios
                if e.expected_sources
                and any(f.anchor for f in e.expected_sources.required)
            ),
        }
