"""DIN.4 — retirar del corpus lo que desapareció del portal, acotado y con salvaguarda.

Hasta aquí `mark_gone` marcaba la página y ahí moría: `retire_page` sólo lo llamaba el endpoint
manual, así que **un evento borrado del portal seguía en el corpus respondiendo como si
existiera**. Para un apartado de eventos ése es el fallo dominante, y es justo lo que la sección
en modo automático viene a resolver.

Tres reglas, y las tres son sobre no pasarse:

1. **Sólo en modo automático.** Una sección `manual` —o una pasada del sitio entero, que es lo que
   hace hoy quien cura a mano— deja un hallazgo `page_gone` y no toca el corpus. «Curación una
   vez, automatización después» significa que la automatización mantiene **dentro del ámbito que
   alguien aprobó**, no en todo el portal.
2. **Salvaguarda de proporción.** Si las bajas superan el 30 % del ámbito rastreado no se retira
   nada: es la clase de rastreo malo que `truncated` **no** capta —el portal que responde 200 con
   una plantilla vacía, la redirección masiva— y sin esto vacía corpus con el rastreo en verde.
   Misma idea que el reconciliador del corpus normativo.
3. **La proporción es del ámbito, no del sitio.** Con dos secciones sembradas, medir sobre el
   sitio da otra cifra: en un apartado de 10 páginas, 4 bajas son el 40 % del apartado y el 4 %
   de un portal de 100. La salvaguarda tiene que disparar en el primer caso.

Y el camino de vuelta: si la página reaparece, su aviso `page_gone` se retira solo. No puede
hacerlo `tipos_a_reconciliar` de CUR.9 —este hallazgo no lo emite ningún detector, así que su
tipo nunca entra en la lista de lo reconciliable—, y reconciliarlo por sitio desde una pasada de
sección retiraría los avisos de las otras secciones: es la misma trampa del censo de DIN.2. Se
resuelve mirando la página, que es lo único que dice la verdad: **volvió a estar activa**.
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pytest

AHORA = datetime(2026, 9, 17, 12, 0, 0, tzinfo=timezone.utc)


# ──────────────────────────── Dobles ────────────────────────────


@dataclass
class _Pagina:
    url: str
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    status: str = "active"
    markdown_content: str | None = "Contenido."
    title: str | None = "Título"
    superseded: bool = False
    quality_score: float | None = None


@dataclass
class _Seccion:
    site_id: uuid.UUID
    name: str = "Jornadas"
    pattern: str = "/jornadas"
    pattern_kind: str = "path_prefix"
    mode: str = "automatic"
    crawl_interval_hours: int | None = None
    criteria_json: dict | None = None
    is_active: bool = True
    id: uuid.UUID = field(default_factory=uuid.uuid4)


@dataclass
class _Sitio:
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    config_json: dict = field(default_factory=dict)
    crawl_interval_hours: int = 24
    root_url: str = "https://www.uji.es"


@dataclass
class _Seleccion:
    chatbot_id: uuid.UUID
    site_id: uuid.UUID
    rule_type: str = "path_prefix"
    rule_value: str | None = "/"
    section_id: uuid.UUID | None = None
    auto_ingest_new: bool = True
    id: uuid.UUID = field(default_factory=uuid.uuid4)


@dataclass
class _ResumenDeRastreo:
    pages_new: int = 0
    pages_changed: int = 0
    pages_gone: int = 0
    pages_error: int = 0
    pages_total: int = 0
    errors: list = field(default_factory=list)
    new_page_ids: list = field(default_factory=list)
    changed_page_ids: list = field(default_factory=list)
    gone_page_ids: list = field(default_factory=list)
    section_id: uuid.UUID | None = None


class _Rastreador:
    def __init__(self, resumen: _ResumenDeRastreo) -> None:
        self._resumen = resumen

    async def crawl_site(
        self, site_id: uuid.UUID, section_id: uuid.UUID | None = None
    ) -> Any:
        return self._resumen


class _RepoDeSelecciones:
    def __init__(self, selecciones: list[_Seleccion], secciones: dict | None = None) -> None:
        self._selecciones = selecciones
        self._secciones = secciones or {}

    async def list_by_site(self, site_id: uuid.UUID) -> list:
        return [s for s in self._selecciones if s.site_id == site_id]

    async def secciones_de(self, selections: list) -> dict:
        return dict(self._secciones)

    def matches(self, selection: Any, page_url: str, *, secciones: dict | None = None) -> bool:
        from urllib.parse import urlparse

        if selection.section_id is not None:
            seccion = (secciones or {}).get(selection.section_id)
            if seccion is None:
                raise AssertionError("la sección tenía que venir cargada")
            return urlparse(page_url).path.startswith(seccion.pattern)
        if selection.rule_type == "path_prefix" and selection.rule_value:
            return urlparse(page_url).path.startswith(selection.rule_value)
        return False


class _Retirador:
    """Doble de `CorpusSelectionService`: sólo se le pide `retire_page`."""

    def __init__(self, falla_en: set[uuid.UUID] | None = None) -> None:
        self.retiradas: list[tuple[uuid.UUID, uuid.UUID]] = []
        self._falla_en = falla_en or set()

    async def retire_page(self, chatbot_id: uuid.UUID, page_id: uuid.UUID) -> int:
        if page_id in self._falla_en:
            raise RuntimeError("no se pudo retirar")
        self.retiradas.append((chatbot_id, page_id))
        return 1


class _RepoDeHallazgos:
    def __init__(self) -> None:
        self.hallazgos: list = []

    async def upsert(self, hallazgo: Any) -> Any:
        self.hallazgos.append(hallazgo)
        return hallazgo

    def tipos(self) -> list[str]:
        return [h.finding_type for h in self.hallazgos]

    def de_tipo(self, tipo: str) -> list:
        return [h for h in self.hallazgos if h.finding_type == tipo]


class _Sesion:
    """Devuelve sitio, sección y páginas; y responde la consulta de páginas del sitio."""

    def __init__(
        self,
        sitio: _Sitio,
        paginas: list[_Pagina],
        secciones: list[_Seccion] | None = None,
    ) -> None:
        self._sitio = sitio
        self._paginas = {p.id: p for p in paginas}
        self._secciones = {s.id: s for s in (secciones or [])}
        self.resueltos: list = []
        self.confirmada = False

    async def get(self, modelo: Any, ident: Any) -> Any:
        nombre = getattr(modelo, "__name__", "")
        if nombre == "HubWebSection":
            return self._secciones.get(ident)
        if nombre == "HubWebSite":
            return self._sitio if ident == self._sitio.id else None
        return self._paginas.get(ident)

    async def execute(self, stmt: Any) -> Any:
        entidad = _entidad_de(stmt)
        if entidad == "HubCrawledPage":
            filas: list = list(self._paginas.values())
        elif entidad == "HubContentFinding":
            filas = list(self.resueltos)
        else:
            filas = []

        # **Pedir una columna no es pedir el objeto**, y este doble no lo distinguía: devolvía
        # las páginas enteras para cualquier `select` sobre `HubCrawledPage`. Cuando la issue
        # #159 cambió el contador de ámbito a `select(HubCrawledPage.url)` —para no traer
        # objetos sólo para contarlos—, el código recibió páginas donde esperaba cadenas.
        #
        # El doble mentía en la misma dirección que el defecto que se arreglaba: daba por bueno
        # traerlo todo. Ahora hace lo que hace SQLAlchemy.
        columnas = _columnas_de(stmt)
        if columnas:
            filas = [
                getattr(f, columnas[0])
                if len(columnas) == 1
                else tuple(getattr(f, c) for c in columnas)
                for f in filas
            ]

        class _R:
            def scalars(self_inner) -> Any:  # noqa: N805
                return self_inner

            def all(self_inner) -> list:  # noqa: N805
                return filas

        return _R()

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.confirmada = True


def _da_el_watcher(watcher: Any) -> Any:
    """La fábrica de watchers es **asíncrona**, como la del arranque: el job la espera."""

    async def _fabrica(_session: Any, _chatbot_id: Any) -> Any:
        return watcher

    return _fabrica


def _entidad_de(stmt: Any) -> str:
    try:
        return stmt.column_descriptions[0]["entity"].__name__
    except Exception:  # noqa: BLE001 — un doble de sentencia sin descripción
        return ""


def _columnas_de(stmt: Any) -> list[str]:
    """Los nombres de las columnas si el `select` pide **columnas** y no la entidad.

    SQLAlchemy lo distingue en `column_descriptions`: al pedir la entidad, `expr` es la clase;
    al pedir una columna, es el atributo. Sin esto, el doble devuelve objetos donde el código
    espera valores — y eso fue lo que pasó al acotar el contador de ámbito en la issue #159.
    """
    try:
        columnas = []
        for descripcion in stmt.column_descriptions:
            expresion = descripcion.get("expr")
            if expresion is descripcion.get("entity"):
                return []
            clave = getattr(expresion, "key", None)
            if clave is None:
                return []
            columnas.append(clave)
        return columnas
    except Exception:  # noqa: BLE001
        return []


def _job(
    *,
    sesion: _Sesion,
    resumen: _ResumenDeRastreo,
    selecciones: list[_Seleccion] | None = None,
    secciones_de_selecciones: dict | None = None,
    retirador: _Retirador | None = None,
    hallazgos: _RepoDeHallazgos | None = None,
):
    from server.app.modules.curation.quality_job import SiteQualityAnalysisJob

    @asynccontextmanager
    async def _factoria():
        yield sesion

    return SiteQualityAnalysisJob(
        session_factory=_factoria,
        site_crawler=_Rastreador(resumen),
        detectors=[],
        watcher=None,
        selection_repo=_RepoDeSelecciones(
            selecciones or [], secciones_de_selecciones
        ),
        finding_repo=hallazgos or _RepoDeHallazgos(),
        retirer_factory=(lambda _s: retirador) if retirador is not None else None,
    )


# ──────────────────────────── Modo automático ────────────────────────────


class TestSeccionAutomatica:

    @pytest.mark.asyncio
    async def test_should_retire_a_gone_page_of_an_automatic_section(self):
        sitio = _Sitio()
        seccion = _Seccion(site_id=sitio.id, mode="automatic")
        ida = _Pagina(url="https://www.uji.es/jornadas/vieja", status="gone")
        vivas = [_Pagina(url=f"https://www.uji.es/jornadas/{i}") for i in range(9)]
        sesion = _Sesion(sitio, [ida, *vivas], [seccion])
        chatbot = uuid.uuid4()
        seleccion = _Seleccion(
            chatbot_id=chatbot, site_id=sitio.id, section_id=seccion.id
        )
        retirador = _Retirador()
        hallazgos = _RepoDeHallazgos()

        resumen = await _job(
            sesion=sesion,
            resumen=_ResumenDeRastreo(
                gone_page_ids=[ida.id], pages_gone=1, section_id=seccion.id
            ),
            selecciones=[seleccion],
            secciones_de_selecciones={seccion.id: seccion},
            retirador=retirador,
            hallazgos=hallazgos,
        ).run_for_site(sitio.id, section_id=seccion.id)

        assert retirador.retiradas == [(chatbot, ida.id)]
        assert resumen.documents_auto_retired == 1
        assert "page_gone" not in hallazgos.tipos()

    @pytest.mark.asyncio
    async def test_should_commit_what_it_retired(self):
        """**Lo destapó el ciclo real de DIN.7.** El job abría su sesión con
        `async with self._session_factory() as session:` y **no la confirmaba nunca**: sólo
        `flush`. Al cerrarse, la sesión deshace lo pendiente — así que la retirada contaba 1, el
        resumen decía «retirada 1», el diario lo escribía (tiene transacción propia) y **el
        documento seguía en el corpus**. Peor que no retirar: retirar mintiendo.

        Y no es sólo la retirada: por el mismo camino se perdían el `quality_score` y las
        supersesiones que 9Q.5 escribe en esta misma sesión.
        """
        sitio = _Sitio()
        seccion = _Seccion(site_id=sitio.id, mode="automatic")
        ida = _Pagina(url="https://www.uji.es/jornadas/vieja", status="gone")
        vivas = [_Pagina(url=f"https://www.uji.es/jornadas/{i}") for i in range(9)]
        sesion = _Sesion(sitio, [ida, *vivas], [seccion])
        seleccion = _Seleccion(
            chatbot_id=uuid.uuid4(), site_id=sitio.id, section_id=seccion.id
        )

        await _job(
            sesion=sesion,
            resumen=_ResumenDeRastreo(
                gone_page_ids=[ida.id], pages_gone=1, section_id=seccion.id
            ),
            selecciones=[seleccion],
            secciones_de_selecciones={seccion.id: seccion},
            retirador=_Retirador(),
        ).run_for_site(sitio.id, section_id=seccion.id)

        assert sesion.confirmada is True

    @pytest.mark.asyncio
    async def test_should_not_retire_a_page_no_selection_points_to(self):
        """«Y hay selección al chatbot». Una página del ámbito que ningún asistente publicó no
        tiene nada que retirar, y llamar a `retire_page` por ella sería ruido."""
        sitio = _Sitio()
        seccion = _Seccion(site_id=sitio.id, mode="automatic")
        ida = _Pagina(url="https://www.uji.es/jornadas/vieja", status="gone")
        vivas = [_Pagina(url=f"https://www.uji.es/jornadas/{i}") for i in range(9)]
        sesion = _Sesion(sitio, [ida, *vivas], [seccion])
        # La selección apunta a OTRA sección, así que su patrón no casa esta página.
        otra = _Seccion(site_id=sitio.id, name="Eventos", pattern="/eventos")
        seleccion = _Seleccion(
            chatbot_id=uuid.uuid4(), site_id=sitio.id, section_id=otra.id
        )
        retirador = _Retirador()

        resumen = await _job(
            sesion=sesion,
            resumen=_ResumenDeRastreo(
                gone_page_ids=[ida.id], pages_gone=1, section_id=seccion.id
            ),
            selecciones=[seleccion],
            secciones_de_selecciones={otra.id: otra},
            retirador=retirador,
        ).run_for_site(sitio.id, section_id=seccion.id)

        assert retirador.retiradas == []
        assert resumen.documents_auto_retired == 0

    @pytest.mark.asyncio
    async def test_should_keep_going_when_one_retirement_fails(self):
        """Un fallo en una página no aborta el resto, y queda en `summary.errors`: media
        retirada silenciosa dejaría el corpus en un estado que nadie sabría reconstruir."""
        sitio = _Sitio()
        seccion = _Seccion(site_id=sitio.id, mode="automatic")
        mala = _Pagina(url="https://www.uji.es/jornadas/mala", status="gone")
        buena = _Pagina(url="https://www.uji.es/jornadas/buena", status="gone")
        vivas = [_Pagina(url=f"https://www.uji.es/jornadas/v{i}") for i in range(20)]
        sesion = _Sesion(sitio, [mala, buena, *vivas], [seccion])
        seleccion = _Seleccion(
            chatbot_id=uuid.uuid4(), site_id=sitio.id, section_id=seccion.id
        )
        retirador = _Retirador(falla_en={mala.id})

        resumen = await _job(
            sesion=sesion,
            resumen=_ResumenDeRastreo(
                gone_page_ids=[mala.id, buena.id], pages_gone=2, section_id=seccion.id
            ),
            selecciones=[seleccion],
            secciones_de_selecciones={seccion.id: seccion},
            retirador=retirador,
        ).run_for_site(sitio.id, section_id=seccion.id)

        assert [p for _c, p in retirador.retiradas] == [buena.id]
        assert resumen.documents_auto_retired == 1
        assert any("retirada" in e for e in resumen.errors)


# ──────────────────────────── Modo manual ────────────────────────────


class TestSeccionManual:

    @pytest.mark.asyncio
    async def test_should_leave_a_finding_and_touch_nothing_in_manual_mode(self):
        sitio = _Sitio()
        seccion = _Seccion(site_id=sitio.id, mode="manual")
        ida = _Pagina(url="https://www.uji.es/jornadas/vieja", status="gone")
        vivas = [_Pagina(url=f"https://www.uji.es/jornadas/{i}") for i in range(9)]
        sesion = _Sesion(sitio, [ida, *vivas], [seccion])
        seleccion = _Seleccion(
            chatbot_id=uuid.uuid4(), site_id=sitio.id, section_id=seccion.id
        )
        retirador = _Retirador()
        hallazgos = _RepoDeHallazgos()

        resumen = await _job(
            sesion=sesion,
            resumen=_ResumenDeRastreo(
                gone_page_ids=[ida.id], pages_gone=1, section_id=seccion.id
            ),
            selecciones=[seleccion],
            secciones_de_selecciones={seccion.id: seccion},
            retirador=retirador,
            hallazgos=hallazgos,
        ).run_for_site(sitio.id, section_id=seccion.id)

        assert retirador.retiradas == []
        assert resumen.documents_auto_retired == 0
        avisos = hallazgos.de_tipo("page_gone")
        assert [a.page_id for a in avisos] == [ida.id]
        assert avisos[0].source_url == ida.url

    @pytest.mark.asyncio
    async def test_should_warn_and_not_claim_the_safeguard_stopped_anything(self):
        """**El orden de las dos comprobaciones.** Con muchas bajas en un ámbito `manual`,
        mirar primero la proporción emitiría «la salvaguarda paró una retirada» cuando no había
        ninguna retirada que parar. La salvaguarda guarda lo que de verdad retira; en manual, lo
        que hay son avisos."""
        sitio = _Sitio()
        seccion = _Seccion(site_id=sitio.id, mode="manual")
        idas = [
            _Pagina(url=f"https://www.uji.es/jornadas/ida{i}", status="gone")
            for i in range(4)
        ]
        vivas = [_Pagina(url=f"https://www.uji.es/jornadas/viva{i}") for i in range(6)]
        sesion = _Sesion(sitio, [*idas, *vivas], [seccion])
        hallazgos = _RepoDeHallazgos()

        await _job(
            sesion=sesion,
            resumen=_ResumenDeRastreo(
                gone_page_ids=[p.id for p in idas],
                pages_gone=len(idas),
                section_id=seccion.id,
            ),
            selecciones=[],
            hallazgos=hallazgos,
        ).run_for_site(sitio.id, section_id=seccion.id)

        assert len(hallazgos.de_tipo("page_gone")) == 4
        assert hallazgos.de_tipo("retirada_masiva_detenida") == []

    @pytest.mark.asyncio
    async def test_should_not_retire_on_a_whole_site_pass(self):
        """Una pasada del sitio entero es lo que hace hoy quien cura a mano: no automatiza nada,
        avisa. Sin esto, pulsar «Rastrear ahora» podría vaciar corpus."""
        sitio = _Sitio()
        ida = _Pagina(url="https://www.uji.es/jornadas/vieja", status="gone")
        vivas = [_Pagina(url=f"https://www.uji.es/x/{i}") for i in range(9)]
        sesion = _Sesion(sitio, [ida, *vivas])
        seleccion = _Seleccion(chatbot_id=uuid.uuid4(), site_id=sitio.id)
        retirador = _Retirador()
        hallazgos = _RepoDeHallazgos()

        resumen = await _job(
            sesion=sesion,
            resumen=_ResumenDeRastreo(gone_page_ids=[ida.id], pages_gone=1),
            selecciones=[seleccion],
            retirador=retirador,
            hallazgos=hallazgos,
        ).run_for_site(sitio.id)

        assert retirador.retiradas == []
        assert resumen.documents_auto_retired == 0
        assert hallazgos.de_tipo("page_gone")


# ──────────────────────────── Salvaguarda de proporción ────────────────────────────


class TestSalvaguardaDeProporcion:

    @staticmethod
    def _con_bajas(cuantas_bajas: int, cuantas_vivas: int, **criterios: Any):
        sitio = _Sitio(config_json=dict(criterios))
        seccion = _Seccion(site_id=sitio.id, mode="automatic")
        idas = [
            _Pagina(url=f"https://www.uji.es/jornadas/ida{i}", status="gone")
            for i in range(cuantas_bajas)
        ]
        vivas = [
            _Pagina(url=f"https://www.uji.es/jornadas/viva{i}")
            for i in range(cuantas_vivas)
        ]
        sesion = _Sesion(sitio, [*idas, *vivas], [seccion])
        seleccion = _Seleccion(
            chatbot_id=uuid.uuid4(), site_id=sitio.id, section_id=seccion.id
        )
        return sitio, seccion, idas, sesion, seleccion

    @pytest.mark.asyncio
    async def test_should_stop_everything_above_the_threshold(self):
        """30 % del ámbito o más: cero retiradas y un hallazgo con las cifras. Un rastreo malo no
        puede vaciar un corpus, y `truncated` no capta esta clase de fallo."""
        sitio, seccion, idas, sesion, seleccion = self._con_bajas(4, 6)
        retirador = _Retirador()
        hallazgos = _RepoDeHallazgos()

        resumen = await _job(
            sesion=sesion,
            resumen=_ResumenDeRastreo(
                gone_page_ids=[p.id for p in idas],
                pages_gone=len(idas),
                section_id=seccion.id,
            ),
            selecciones=[seleccion],
            secciones_de_selecciones={seccion.id: seccion},
            retirador=retirador,
            hallazgos=hallazgos,
        ).run_for_site(sitio.id, section_id=seccion.id)

        assert retirador.retiradas == []
        assert resumen.documents_auto_retired == 0
        detenida = hallazgos.de_tipo("retirada_masiva_detenida")
        assert len(detenida) == 1
        assert detenida[0].signal["bajas"] == 4
        assert detenida[0].signal["ambito"] == 10
        assert detenida[0].severity == "critical"

    @pytest.mark.asyncio
    async def test_should_retire_just_below_the_threshold(self):
        """**El camino bueno de la salvaguarda**, no sólo el disparo: un 29 % sí retira. Sin este
        test, una salvaguarda que lo detuviera todo pasaría por correcta."""
        sitio, seccion, idas, sesion, seleccion = self._con_bajas(29, 71)
        retirador = _Retirador()
        hallazgos = _RepoDeHallazgos()

        resumen = await _job(
            sesion=sesion,
            resumen=_ResumenDeRastreo(
                gone_page_ids=[p.id for p in idas],
                pages_gone=len(idas),
                section_id=seccion.id,
            ),
            selecciones=[seleccion],
            secciones_de_selecciones={seccion.id: seccion},
            retirador=retirador,
            hallazgos=hallazgos,
        ).run_for_site(sitio.id, section_id=seccion.id)

        assert resumen.documents_auto_retired == 29
        assert hallazgos.de_tipo("retirada_masiva_detenida") == []

    @pytest.mark.asyncio
    async def test_should_honour_the_threshold_inherited_from_the_site(self):
        """El umbral es un criterio de juicio más, y por tanto heredable sitio→sección (DIN.1)."""
        sitio, seccion, idas, sesion, seleccion = self._con_bajas(
            2, 98, retirada_masiva_umbral=0.01
        )
        retirador = _Retirador()
        hallazgos = _RepoDeHallazgos()

        await _job(
            sesion=sesion,
            resumen=_ResumenDeRastreo(
                gone_page_ids=[p.id for p in idas],
                pages_gone=len(idas),
                section_id=seccion.id,
            ),
            selecciones=[seleccion],
            secciones_de_selecciones={seccion.id: seccion},
            retirador=retirador,
            hallazgos=hallazgos,
        ).run_for_site(sitio.id, section_id=seccion.id)

        assert retirador.retiradas == []
        assert hallazgos.de_tipo("retirada_masiva_detenida")

    @pytest.mark.asyncio
    async def test_should_honour_the_threshold_overridden_in_the_section(self):
        sitio, seccion, idas, sesion, seleccion = self._con_bajas(
            4, 6, retirada_masiva_umbral=0.9
        )
        seccion.criteria_json = {"retirada_masiva_umbral": 0.1}
        retirador = _Retirador()
        hallazgos = _RepoDeHallazgos()

        await _job(
            sesion=sesion,
            resumen=_ResumenDeRastreo(
                gone_page_ids=[p.id for p in idas],
                pages_gone=len(idas),
                section_id=seccion.id,
            ),
            selecciones=[seleccion],
            secciones_de_selecciones={seccion.id: seccion},
            retirador=retirador,
            hallazgos=hallazgos,
        ).run_for_site(sitio.id, section_id=seccion.id)

        assert retirador.retiradas == []
        assert hallazgos.de_tipo("retirada_masiva_detenida")

    @pytest.mark.asyncio
    async def test_should_measure_the_proportion_over_the_scope_and_not_the_site(self):
        """**El test que separa el ámbito del sitio.** Cuatro bajas en un apartado de diez son el
        40 % del apartado y el 4 % de un portal de cien: medido sobre el sitio, la salvaguarda no
        dispararía nunca en un apartado pequeño de un portal grande."""
        sitio = _Sitio()
        jornadas = _Seccion(site_id=sitio.id, name="Jornadas", pattern="/jornadas")
        idas = [
            _Pagina(url=f"https://www.uji.es/jornadas/ida{i}", status="gone")
            for i in range(4)
        ]
        vivas_del_ambito = [
            _Pagina(url=f"https://www.uji.es/jornadas/viva{i}") for i in range(6)
        ]
        # El resto del portal, que no es del ámbito y por tanto no entra en la cuenta.
        resto = [_Pagina(url=f"https://www.uji.es/otros/{i}") for i in range(90)]
        sesion = _Sesion(sitio, [*idas, *vivas_del_ambito, *resto], [jornadas])
        seleccion = _Seleccion(
            chatbot_id=uuid.uuid4(), site_id=sitio.id, section_id=jornadas.id
        )
        retirador = _Retirador()
        hallazgos = _RepoDeHallazgos()

        await _job(
            sesion=sesion,
            resumen=_ResumenDeRastreo(
                gone_page_ids=[p.id for p in idas],
                pages_gone=len(idas),
                section_id=jornadas.id,
            ),
            selecciones=[seleccion],
            secciones_de_selecciones={jornadas.id: jornadas},
            retirador=retirador,
            hallazgos=hallazgos,
        ).run_for_site(sitio.id, section_id=jornadas.id)

        assert retirador.retiradas == []
        detenida = hallazgos.de_tipo("retirada_masiva_detenida")
        assert detenida and detenida[0].signal["ambito"] == 10


# ──────────────────── La puerta que nadie había abierto ────────────────────


class TestElJobDeProduccionSiHaceEstoDeVerdad:
    """**Lo destapó cablear DIN.4 en el arranque**, y no es un detalle de cableado.

    El job de producción se construye con `watcher=None` y `selection_repo=_NullSelectionRepo()`
    —que devuelve lista vacía siempre—, y el paso de auto-ingesta de 9Q.7 exigía `self._watcher
    is not None` y preguntaba las selecciones a ese repositorio nulo. O sea: **dos puertas
    cerradas a la vez**, y la auto-ingesta de páginas nuevas no ha corrido nunca en producción.
    Es la cuarta vez que aparece este patrón en el proyecto —el watcher de RAS.5, el bloque
    `TABLE` de SEG.5, el detector semántico de CUR.7— y siempre igual: la capacidad construida
    detrás de una puerta que nadie abrió.

    Sin esto, DIN.4 y DIN.5 se habrían construido encima del mismo hueco.
    """

    @pytest.mark.asyncio
    async def test_should_auto_ingest_with_only_a_watcher_factory(self):
        """La forma con la que el arranque lo construye: sin watcher fijo y con fábrica."""
        sitio = _Sitio()
        nueva = _Pagina(url="https://www.uji.es/jornadas/nueva")
        sesion = _Sesion(sitio, [nueva])
        chatbot = uuid.uuid4()
        seleccion = _Seleccion(chatbot_id=chatbot, site_id=sitio.id, auto_ingest_new=True)
        ingeridas: list = []

        class _Watcher:
            async def process_source(self, source_url: str, chatbot_id: uuid.UUID, **kw: Any):
                ingeridas.append((source_url, chatbot_id))
                return (object(), 1)

        from server.app.modules.curation.quality_job import SiteQualityAnalysisJob

        @asynccontextmanager
        async def _factoria():
            yield sesion

        job = SiteQualityAnalysisJob(
            session_factory=_factoria,
            site_crawler=_Rastreador(
                _ResumenDeRastreo(new_page_ids=[nueva.id], pages_new=1)
            ),
            detectors=[],
            watcher=None,
            selection_repo=_RepoDeSelecciones([seleccion]),
            watcher_factory=_da_el_watcher(_Watcher()),
        )

        resumen = await job.run_for_site(sitio.id)

        assert ingeridas == [(nueva.url, chatbot)]
        assert resumen.documents_auto_ingested == 1

    @pytest.mark.asyncio
    async def test_should_use_the_watcher_of_each_chatbot(self):
        """La lección de RAS.5: el watcher lleva el servicio de embeddings **del chatbot**, así
        que una instancia única no puede servir a varios — ingerir con otro modelo del que usa su
        corpus deja vectores que no se pueden comparar con los que ya hay."""
        sitio = _Sitio()
        nueva = _Pagina(url="https://www.uji.es/jornadas/nueva")
        sesion = _Sesion(sitio, [nueva])
        uno, otro = uuid.uuid4(), uuid.uuid4()
        pedidos: list = []

        class _Watcher:
            async def process_source(self, source_url: str, chatbot_id: uuid.UUID, **kw: Any):
                return (object(), 1)

        async def _fabrica(_session: Any, chatbot_id: uuid.UUID) -> Any:
            pedidos.append(chatbot_id)
            return _Watcher()

        from server.app.modules.curation.quality_job import SiteQualityAnalysisJob

        @asynccontextmanager
        async def _factoria():
            yield sesion

        job = SiteQualityAnalysisJob(
            session_factory=_factoria,
            site_crawler=_Rastreador(
                _ResumenDeRastreo(new_page_ids=[nueva.id], pages_new=1)
            ),
            detectors=[],
            watcher=None,
            selection_repo=_RepoDeSelecciones([
                _Seleccion(chatbot_id=uno, site_id=sitio.id),
                _Seleccion(chatbot_id=otro, site_id=sitio.id),
            ]),
            watcher_factory=_fabrica,
        )

        await job.run_for_site(sitio.id)

        assert set(pedidos) == {uno, otro}

    @pytest.mark.asyncio
    async def test_should_ask_the_selections_to_the_repo_of_this_session(self):
        """El repositorio de selecciones se resuelve **con la sesión de la pasada**. Construido
        al arrancar tendría la sesión de entonces, y por eso el arranque pasaba uno nulo: la
        fábrica es lo que permite que sea el de verdad."""
        sitio = _Sitio()
        nueva = _Pagina(url="https://www.uji.es/jornadas/nueva")
        sesion = _Sesion(sitio, [nueva])
        chatbot = uuid.uuid4()
        sesiones_vistas: list = []

        def _fabrica_de_repo(session: Any) -> Any:
            sesiones_vistas.append(session)
            return _RepoDeSelecciones(
                [_Seleccion(chatbot_id=chatbot, site_id=sitio.id)]
            )

        class _Watcher:
            async def process_source(self, source_url: str, chatbot_id: uuid.UUID, **kw: Any):
                return (object(), 1)

        from server.app.modules.curation.quality_job import SiteQualityAnalysisJob

        @asynccontextmanager
        async def _factoria():
            yield sesion

        job = SiteQualityAnalysisJob(
            session_factory=_factoria,
            site_crawler=_Rastreador(
                _ResumenDeRastreo(new_page_ids=[nueva.id], pages_new=1)
            ),
            detectors=[],
            watcher=None,
            selection_repo=_RepoDeSelecciones([]),
            watcher_factory=_da_el_watcher(_Watcher()),
            selection_repo_factory=_fabrica_de_repo,
        )

        resumen = await job.run_for_site(sitio.id)

        assert sesiones_vistas == [sesion]
        assert resumen.documents_auto_ingested == 1


# ──────────────────────────── El camino de vuelta ────────────────────────────


class TestSiLaPaginaVuelve:

    @pytest.mark.asyncio
    async def test_should_retire_the_warning_when_the_page_is_active_again(self):
        """Un aviso que ya no es cierto se deja de usar, y con él la lista entera (la lección de
        CUR.9). Aquí no lo puede hacer `tipos_a_reconciliar` —`page_gone` no lo emite ningún
        detector—, así que se mira la página: si volvió a estar activa, el aviso se retira."""
        from server.app.modules.curation.quality_job import (
            NOTA_DE_PAGINA_QUE_VOLVIO,
        )

        sitio = _Sitio()
        seccion = _Seccion(site_id=sitio.id, mode="manual")
        volvio = _Pagina(url="https://www.uji.es/jornadas/volvio", status="active")
        sesion = _Sesion(sitio, [volvio], [seccion])

        @dataclass
        class _Aviso:
            page_id: uuid.UUID
            finding_type: str = "page_gone"
            status: str = "new"
            reviewed_at: Any = None
            resolution_note: str | None = None

        aviso = _Aviso(page_id=volvio.id)
        sesion.resueltos = [aviso]

        await _job(
            sesion=sesion,
            resumen=_ResumenDeRastreo(section_id=seccion.id),
            selecciones=[],
        ).run_for_site(sitio.id, section_id=seccion.id)

        assert aviso.status == "resolved"
        assert aviso.resolution_note == NOTA_DE_PAGINA_QUE_VOLVIO

    @pytest.mark.asyncio
    async def test_should_not_touch_a_warning_of_a_page_still_gone(self):
        sitio = _Sitio()
        seccion = _Seccion(site_id=sitio.id, mode="manual")
        sigue_ida = _Pagina(url="https://www.uji.es/jornadas/ida", status="gone")
        sesion = _Sesion(sitio, [sigue_ida], [seccion])

        @dataclass
        class _Aviso:
            page_id: uuid.UUID
            finding_type: str = "page_gone"
            status: str = "new"
            reviewed_at: Any = None
            resolution_note: str | None = None

        aviso = _Aviso(page_id=sigue_ida.id)
        sesion.resueltos = [aviso]

        await _job(
            sesion=sesion,
            resumen=_ResumenDeRastreo(section_id=seccion.id),
            selecciones=[],
        ).run_for_site(sitio.id, section_id=seccion.id)

        assert aviso.status == "new"
