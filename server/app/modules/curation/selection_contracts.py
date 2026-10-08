"""Contratos Pydantic para la gestión de sitios y selecciones (9Q.7).

Deploy: edge.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from server.app.core.red_publica import DestinoNoPublico, assert_forma_publica


def _url_que_el_servidor_va_a_pedir(valor: str | None) -> str | None:
    """APER.1 — la forma de una URL que el rastreador acabará pidiendo.

    Se comprueba **aquí** y no sólo al descargar para que quien se equivoca al dar de alta un
    sitio reciba un 422 con el motivo, en vez de un rastreo que devuelve cero páginas sin decir
    por qué. La comprobación del destino resuelto va en cada petición —incluida cada
    redirección—, porque la redirección la decide el servidor remoto y un contrato no la ve.

    No resuelve el DNS a propósito: dar de alta un sitio no puede depender de que su servidor
    esté respondiendo en ese instante, y un nombre que resuelve a una dirección privada lo para
    el guardia de la descarga.
    """
    if valor is None:
        return None
    try:
        assert_forma_publica(valor)
    except DestinoNoPublico as exc:
        raise ValueError(str(exc)) from exc
    return valor


class CrawlConfig(BaseModel):
    """Cómo se rastrea un apartado (RAS.5).

    El spider ya leía todo esto de `config_json`, pero **no había forma de fijarlo**: ni al crear
    ni al modificar un sitio. Sin `url_regex_filter` la decisión operativa del bloque —un sitio por
    apartado, porque cada apartado tiene un responsable distinto— era inalcanzable desde la
    interfaz, y el rastreo salía con los valores por defecto contra todo el dominio.

    Los defectos son los conservadores de RAS.1: la cortesía no se pide, se hereda.
    """

    crawl_depth: int = Field(default=1, ge=0, le=10)
    #: Expresión regular que acota el apartado. Se valida al guardar: una que no compila rompería
    #: todos los rastreos del sitio, y el fallo saldría lejos del formulario donde se escribió.
    url_regex_filter: str | None = None
    max_pages: int = Field(default=50, ge=1, le=100_000)
    #: Presupuesto de tiempo por ejecución, en segundos. Con pausa de cortesía, el coste real de un
    #: rastreo es el tiempo: mil páginas a un segundo son veinte minutos.
    max_seconds: int = Field(default=1800, ge=10, le=86_400)
    delay_seconds: float = Field(default=1.0, ge=0.0, le=60.0)
    respect_robots: bool = True
    max_concurrency: int = Field(default=1, ge=1, le=8)
    max_retries: int = Field(default=3, ge=1, le=10)

    # CUR.1 — de dónde sacar la fecha que **publica** la página y la unidad que la mantiene. El
    # marcado es de cada portal (`www.uji.es` las sirve juntas en `.clockBarDate`), así que va en la
    # configuración del sitio: hardcodearlo acoplaría el módulo a un cliente. Vacío = como antes.
    content_date_selector: str | None = None
    content_date_format: str = "%d/%m/%Y"

    # CUR.2.1 — los **criterios de juicio**, por sitio y por tanto por organización. Estaban en el
    # código: `stale_days` y el umbral de contenido pobre los ponía el constructor del detector y
    # nadie los pasaba, y la semántica de una serie por años se fijó global a partir de cómo publica
    # un portal concreto. Un portal de normativa y uno de noticias no envejecen igual, y donde la
    # UJI publica series vigentes otro versiona convocatorias. Es la misma regla que el proyecto ya
    # aplica al vocabulario del corpus: **el criterio es dato, no código**.
    #
    # Los defectos son los de hoy, para no cambiarle el criterio a nadie al desplegar esto.
    # CUR.3 — qué parte de la página es contenido y qué es plantilla. Al corpus tiene que ir sólo
    # lo primero: medido en el portal, cada página lleva el menú completo, y el asistente lo cita.
    # `content_selector` es la señal más fuerte cuando el portal la ofrece (`main` aquí);
    # `boilerplate_selectors` quita lo que está dentro del contenido y sigue siendo plantilla
    # —miga de pan, barra de fecha, iconos de compartir—.
    content_selector: str | None = None
    boilerplate_selectors: list[str] = Field(default_factory=list)
    #: Proporción de páginas en las que una línea tiene que aparecer para tenerse por plantilla.
    boilerplate_repeat_threshold: float = Field(default=0.6, gt=0.0, le=1.0)

    stale_days: int = Field(default=365, ge=1, le=36_500)
    thin_min_tokens: int = Field(default=120, ge=0, le=100_000)
    #: `series` — varias versiones por año y **todas vigentes** (la UJI: acuerdos y actas).
    #: `superseded` — la nueva deroga a la vieja (un portal que versiona convocatorias).
    #: `off` — el año de la URL no significa nada aquí; agrupar sólo daría ruido.
    version_series_policy: Literal["series", "superseded", "off"] = "series"

    @field_validator("content_date_format")
    @classmethod
    def _debe_ser_un_formato_de_fecha(cls, valor: str) -> str:
        """Un formato inválido fallaría en **cada página** del rastreo, lejos del formulario."""
        from datetime import datetime

        try:
            datetime.strptime(datetime(2026, 1, 2).strftime(valor), valor)
        except (ValueError, TypeError) as fallo:
            raise ValueError(
                f"«{valor}» no es un formato de fecha de `strftime` válido: {fallo}"
            ) from fallo
        if valor.strip() == datetime(2026, 1, 2).strftime(valor).strip():
            # Una cadena sin directivas (`no es un formato`) «formatea» a sí misma: no es un
            # formato, es texto.
            raise ValueError(f"«{valor}» no lleva ninguna directiva de fecha (%d, %m, %Y…)")
        return valor

    @field_validator("url_regex_filter")
    @classmethod
    def _debe_compilar(cls, valor: str | None) -> str | None:
        if valor is None or not valor.strip():
            return None
        try:
            re.compile(valor)
        except re.error as fallo:
            raise ValueError(
                f"«{valor}» no es una expresión regular válida: {fallo}"
            ) from fallo
        return valor


class SiteView(BaseModel):
    id: uuid.UUID
    organizacion_id: uuid.UUID | None
    name: str
    root_url: str
    sitemap_url: str | None
    spider_type: str
    crawl_interval_hours: int
    audit_semantic_scope: str
    last_crawled_at: datetime | None
    status: str
    created_at: datetime
    #: RAS.5 — quien mira la lista tiene que poder ver con qué cortesía y con qué filtro se está
    #: rastreando cada apartado. Antes no salía, así que no había forma de revisarlo.
    crawl_config: CrawlConfig | None = None

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def _desde_config_json(cls, datos: Any) -> Any:
        """La configuración vive en `config_json` en la base; aquí se sirve tipada."""
        if isinstance(datos, dict) or not hasattr(datos, "config_json"):
            return datos
        crudo = getattr(datos, "config_json", None) or {}
        campos = {k: v for k, v in crudo.items() if k in CrawlConfig.model_fields}
        return {
            **{
                nombre: getattr(datos, nombre, None)
                for nombre in cls.model_fields
                if nombre != "crawl_config"
            },
            "crawl_config": CrawlConfig(**campos) if campos else None,
        }


class SiteCreate(BaseModel):
    name: str
    root_url: str
    sitemap_url: str | None = None
    audit_semantic_scope: str = "ingested"
    crawl_interval_hours: int = 24
    crawl_config: CrawlConfig | None = None

    #: El sitemap se pide igual que la raíz, así que se valida igual: era la puerta de al lado.
    _valida_destinos = field_validator("root_url", "sitemap_url")(
        classmethod(lambda cls, v: _url_que_el_servidor_va_a_pedir(v))
    )


class SitePatch(BaseModel):
    name: str | None = None
    root_url: str | None = None
    sitemap_url: str | None = None
    audit_semantic_scope: str | None = None
    crawl_interval_hours: int | None = None
    crawl_config: CrawlConfig | None = None

    #: Sin esto el `PATCH` sería el rodeo obvio para meter lo que el `POST` rechaza.
    _valida_destinos = field_validator("root_url", "sitemap_url")(
        classmethod(lambda cls, v: _url_que_el_servidor_va_a_pedir(v))
    )


class PageView(BaseModel):
    id: uuid.UUID
    site_id: uuid.UUID
    url: str
    title: str | None
    status: str
    token_count: int | None
    superseded: bool
    quality_score: float | None
    last_crawled_at: datetime | None
    #: 2026-10-08 — propuesta para un asistente: cuándo y quién. Nula = no propuesta.
    propuesta_at: datetime | None = None
    propuesta_por: str | None = None

    model_config = {"from_attributes": True}


class PageContentView(BaseModel):
    """El texto **guardado** de una página, que es el que iría al corpus (CUR.4).

    El informe acusaba y no dejaba comprobar: no había ninguna pantalla que mostrara el texto de una
    página rastreada. Hace falta para juzgar un hallazgo, para decidir si la página merece entrar en
    el corpus y —desde CUR.3— para comprobar que el recorte de plantilla no se ha comido contenido.

    Se sirve lo guardado, no la página original: eso último ya se puede ver abriendo la URL.
    """

    id: uuid.UUID
    url: str
    title: str | None
    status: str
    content: str
    token_count: int | None
    owner: str | None
    published_at: datetime | None
    #: Por qué no se pudo leer sin renderizar, si es el caso (RAS.2).
    render_signals: list[dict[str, Any]] = Field(default_factory=list)


class SelectionView(BaseModel):
    id: uuid.UUID
    chatbot_id: uuid.UUID
    site_id: uuid.UUID
    rule_type: str
    rule_value: str | None
    auto_ingest_new: bool
    created_at: datetime
    #: DIN.3 — cuando apunta a una sección, el patrón efectivo es el de la sección y
    #: `rule_value` se ignora: dos sitios de verdad de la misma regla divergirían.
    section_id: uuid.UUID | None = None

    model_config = {"from_attributes": True}


# ──────────────────────── Secciones de un sitio (DIN.1–DIN.3) ────────────────────────


class SectionCreate(BaseModel):
    """Lo que hace falta para dar de alta un apartado: un nombre y lo que lo delimita.

    El patrón se valida aquí además de en el repositorio, y las dos validaciones llaman a la
    misma función: `secciones.validar_patron`. Un regex que no compila rompería todos los
    rastreos de la sección y el fallo saldría lejos del formulario donde se escribió, que es la
    lección de `CrawlConfig` en RAS.5.
    """

    name: str = Field(min_length=1, max_length=255)
    pattern: str = Field(min_length=1, max_length=2048)
    pattern_kind: Literal["path_prefix", "regex"] = "path_prefix"
    #: Nulo = hereda la cadencia del sitio (DIN.1).
    crawl_interval_hours: int | None = Field(default=None, ge=1, le=8_760)
    #: `manual` a propósito: una sección nueva no automatiza hasta que alguien lo dice.
    mode: Literal["manual", "automatic"] = "manual"
    criteria_json: dict[str, Any] | None = None
    owner: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def _el_patron_tiene_que_servir(self) -> "SectionCreate":
        from server.app.modules.curation.secciones import PatronInvalido, validar_patron

        try:
            validar_patron(self.pattern_kind, self.pattern)
        except PatronInvalido as fallo:
            raise ValueError(str(fallo)) from fallo
        return self


class SectionPatch(BaseModel):
    """Los campos editables de una sección. Ausente = no se toca; nulo en la cadencia = hereda.

    `crawl_interval_hours` no puede distinguir «no lo toques» de «vuelve a heredarlo» con un solo
    nulo, así que se usa `heredar_cadencia` para lo segundo: colapsarlos dejaría imposible vaciar
    un valor puesto, que es el mismo problema que `core/ambito.py` resuelve con la distinción
    entre `None` y `0`.
    """

    name: str | None = Field(default=None, min_length=1, max_length=255)
    pattern: str | None = Field(default=None, min_length=1, max_length=2048)
    pattern_kind: Literal["path_prefix", "regex"] | None = None
    crawl_interval_hours: int | None = Field(default=None, ge=1, le=8_760)
    heredar_cadencia: bool = False
    mode: Literal["manual", "automatic"] | None = None
    criteria_json: dict[str, Any] | None = None
    owner: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None

    @model_validator(mode="after")
    def _el_patron_tiene_que_servir(self) -> "SectionPatch":
        from server.app.modules.curation.secciones import PatronInvalido, validar_patron

        if self.pattern is None and self.pattern_kind is None:
            return self
        if self.pattern is None:
            # Cambiar sólo la clase de patrón dejaría el patrón viejo interpretado de otra forma
            # sin que nadie lo hubiera revisado: se piden los dos juntos.
            raise ValueError(
                "para cambiar la clase de patrón hay que enviar también el patrón"
            )
        try:
            validar_patron(self.pattern_kind or "path_prefix", self.pattern)
        except PatronInvalido as fallo:
            raise ValueError(str(fallo)) from fallo
        return self


class SectionView(BaseModel):
    """Una sección tal y como la ve quien cura.

    **La cadencia se sirve dos veces a propósito**: la propia (nula si hereda) y la efectiva, con
    una bandera que dice cuál es cuál. Sin la bandera, cambiar la cadencia del sitio parecería no
    hacer nada en las secciones que la heredan — y quien cura no tendría forma de saber cuál de
    las dos está mirando.
    """

    id: uuid.UUID
    site_id: uuid.UUID
    name: str
    pattern: str
    pattern_kind: str
    crawl_interval_hours: int | None
    crawl_interval_hours_effective: int
    crawl_interval_inherited: bool
    mode: str
    criteria_json: dict[str, Any] | None
    owner: str | None
    last_crawled_at: datetime | None
    is_active: bool
    created_at: datetime


class PatternTestRequest(BaseModel):
    """Probar el patrón **antes** de guardar la sección (DIN.3)."""

    pattern: str = Field(min_length=1, max_length=2048)
    pattern_kind: Literal["path_prefix", "regex"] = "path_prefix"

    @model_validator(mode="after")
    def _el_patron_tiene_que_servir(self) -> "PatternTestRequest":
        from server.app.modules.curation.secciones import PatronInvalido, validar_patron

        try:
            validar_patron(self.pattern_kind, self.pattern)
        except PatronInvalido as fallo:
            raise ValueError(str(fallo)) from fallo
        return self


class CrawlRunView(BaseModel):
    """Una pasada, tal y como la lee quien cura (DIN.6).

    `scope_label` va al lado de `section_id` porque el diario es **historia**: si alguien borra
    la sección, la fila tiene que seguir diciendo qué cubrió.
    """

    id: uuid.UUID
    site_id: uuid.UUID
    section_id: uuid.UUID | None
    scope_label: str
    started_at: datetime
    finished_at: datetime
    pages_total: int
    pages_new: int
    pages_changed: int
    pages_gone: int
    pages_error: int
    documents_auto_ingested: int
    documents_reingested: int
    documents_auto_retired: int
    pages_blocked_by_findings: int
    findings_retired: int
    truncated: bool
    stop_reason: str | None
    errors: list[str] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class PaginaDePasadas(BaseModel):
    """Una página del diario. El total va aparte porque la tabla lo necesita para paginar."""

    total: int
    items: list[CrawlRunView]


class PatternTestView(BaseModel):
    """Cuántas páginas **ya rastreadas** casarían, y una muestra.

    Es lo que evita el regex que compila y no casa nada, que hoy sólo se descubre cuando la
    pasada siguiente no ingiere nada — y como la ingesta automática es silenciosa, se descubre
    tarde.
    """

    matched: int
    total: int
    #: Una muestra y no el volcado: la pantalla tiene que caber.
    sample: list[str] = Field(default_factory=list)


#: Los tipos de regla que `SelectionRepo.matches` sabe evaluar. Cualquier otro se guardaba
#: con un 201 y no casaba nunca: en la pantalla, una selección activa y ninguna página
#: seleccionada, sin nada que explicara por qué (VER.8). Mismo criterio que el spider
#: desconocido del dispatcher: fallar donde se ve, no caer a algo que parece funcionar.
TiposDeRegla = Literal["path_prefix", "sitemap_section", "manual"]


class SelectionCreate(BaseModel):
    site_id: uuid.UUID
    rule_type: TiposDeRegla
    rule_value: str | None = None
    auto_ingest_new: bool = True
    #: DIN.3 — apuntar a una sección en vez de repetir su patrón. Con esto puesto, el patrón
    #: efectivo es el de la sección y `rule_value` se ignora.
    section_id: uuid.UUID | None = None


class ReconnaissanceRequest(BaseModel):
    """Lo que se pide para reconocer un apartado antes de darlo de alta (CUR.6).

    `delay_seconds` no es la pausa del sondeo —el sondeo va con prisa porque responde dentro de una
    petición— sino **la del rastreo que se lanzaría**: es la que decide si el apartado son minutos u
    horas, y por tanto la que hace útil la estimación.
    """

    root_url: str
    crawl_depth: int = Field(default=3, ge=0, le=10)
    max_pages: int = Field(default=60, ge=1, le=2_000)
    delay_seconds: float = Field(default=1.0, ge=0, le=60)
    respect_robots: bool = True
    url_regex_filter: str | None = None
    formato: Literal["json", "csv"] = "json"

    @field_validator("root_url")
    @classmethod
    def _debe_ser_una_url(cls, valor: str) -> str:
        # APER.1 — antes esto comprobaba sólo esquema y `netloc`, así que
        # `http://169.254.169.254/…` pasaba: el reconocimiento es el que **devuelve el texto
        # leído**, o sea el más rentable de los dos endpoints para quien busca la red interna.
        _url_que_el_servidor_va_a_pedir(valor)
        return valor

    @field_validator("url_regex_filter")
    @classmethod
    def _debe_compilar(cls, valor: str | None) -> str | None:
        if valor:
            try:
                re.compile(valor)
            except re.error as fallo:
                raise ValueError(f"url_regex_filter no es una expresión regular válida: {fallo}")
        return valor


class SiteSectionView(BaseModel):
    apartado: str
    urls: int
    ejemplos: list[str]


class ReconnaissanceView(BaseModel):
    root_url: str
    urls_encontradas: int
    paginas_sondeadas: int
    truncado: bool
    motivo_de_parada: str | None
    apartados: list[SiteSectionView]
    segundos_por_pagina: float
    segundos_estimados: float
    urls_prohibidas: int = 0
    no_legibles: int = 0
    fallos: int = 0


class CandidatePageView(BaseModel):
    """Una página activa del sitio, con su estado frente al corpus del asistente.

    `is_ingested` existe porque «que se vea lo que ya está ingerido» (CUR.5) no se puede resolver
    ocultando la fila: la ausencia no distingue «ya está en el corpus» de «nunca fue candidata», y
    tras ingerir una página desaparecía sin decir si había funcionado.
    """

    page_id: uuid.UUID
    url: str
    title: str | None
    matched_rule: str | None
    is_new: bool
    is_ingested: bool = False
    #: 2026-10-08 — si quien curó la propuso para un asistente, y quién: Publicación filtra por ello.
    propuesta_at: datetime | None = None
    propuesta_por: str | None = None
