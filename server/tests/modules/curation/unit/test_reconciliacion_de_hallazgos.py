"""Un hallazgo que ya no es cierto no puede seguir en la cola (CUR.9).

Del usuario, tras las pruebas manuales: «debería añadirse la pasada de reconciliación al analizar.
No tiene sentido que haya filas que ya no sean ciertas».

Medido antes de arreglarlo: **241 hallazgos `stale` guardados donde el detector de hoy emite 207**.
La diferencia son páginas que ahora se agrupan como serie por curso académico (CUR.7) y por tanto
dejaron de producir aviso — pero su fila vieja seguía ahí acusándolas. Cada mejora del detector
dejaba un sedimento de acusaciones caducadas, y una lista de trabajo con filas falsas se deja de
usar entera.

Tres decisiones que este fichero fija, porque son las que pueden hacer daño:

* **Sólo se retira lo que este pase podía volver a afirmar.** Cada detector declara los tipos que
  emite, y se reconcilian los tipos de los detectores que **han corrido**. Si el semántico no pasó,
  sus tipos no se tocan: reconciliar lo que no se ha vuelto a mirar sería borrar por no haber
  buscado.
* **`duplicate` lo emiten los dos detectores**, así que sólo se reconcilia cuando los dos han
  pasado. Con el semántico apagado, un pase determinista habría resuelto los duplicados semánticos.
* **Lo que una persona descartó no se toca.** `dismissed` es una decisión humana, y `resolved` ya
  está cerrado. Sólo se retiran `new` y `confirmed`.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import pytest

from server.app.modules.curation.reconciliacion import (
    identidad_del_hallazgo,
    reconciliar_hallazgos,
    tipos_a_reconciliar,
)

_AHORA = datetime(2026, 8, 19, tzinfo=timezone.utc)
_SITIO = uuid.uuid4()


class _Fila:
    """Un hallazgo guardado, con lo que la reconciliación mira y escribe."""

    def __init__(
        self,
        finding_type: str,
        status: str = "new",
        page_id: uuid.UUID | None = None,
        related_page_id: uuid.UUID | None = None,
    ) -> None:
        self.id = uuid.uuid4()
        self.site_id = _SITIO
        self.finding_type = finding_type
        self.status = status
        self.page_id = page_id or uuid.uuid4()
        self.related_page_id = related_page_id
        self.reviewed_at: datetime | None = None
        self.reviewed_by: uuid.UUID | None = None
        self.resolution_note: str | None = None


class _Emitido:
    def __init__(self, fila: _Fila) -> None:
        self.finding_type = fila.finding_type
        self.page_id = fila.page_id
        self.related_page_id = fila.related_page_id


class _Sesion:
    def __init__(self, filas: list[_Fila]) -> None:
        self._filas = filas
        self.flushes = 0

    async def execute(self, _stmt: Any) -> Any:
        filas = self._filas

        class _R:
            def scalars(self_inner) -> Any:
                return self_inner

            def all(self_inner) -> list:
                return filas

        return _R()

    async def flush(self) -> None:
        self.flushes += 1


class _Detector:
    def __init__(self, tipos: set[str], corrio: bool = True) -> None:
        self.finding_types = frozenset(tipos)
        self.corrio = corrio


# ───────────────── Qué tipos entran en la reconciliación ─────────────────


def test_solo_los_tipos_de_los_detectores_que_han_corrido():
    determinista = _Detector({"stale", "thin", "duplicate"})
    semantico = _Detector({"duplicate", "contradiction"})

    tipos = tipos_a_reconciliar(ejecutados=[determinista, semantico], omitidos=[])

    assert tipos == {"stale", "thin", "duplicate", "contradiction"}


def test_un_tipo_compartido_no_se_reconcilia_si_falta_uno_de_sus_detectores():
    """Con el semántico apagado, un pase determinista resolvería los duplicados semánticos."""
    determinista = _Detector({"stale", "thin", "duplicate"})
    semantico = _Detector({"duplicate", "contradiction"})

    tipos = tipos_a_reconciliar(ejecutados=[determinista], omitidos=[semantico])

    assert "duplicate" not in tipos
    assert "contradiction" not in tipos
    assert {"stale", "thin"} <= tipos


def test_sin_detectores_ejecutados_no_se_reconcilia_nada():
    """Si la detección falló entera, retirar hallazgos sería borrar por no haber mirado."""
    assert tipos_a_reconciliar(ejecutados=[], omitidos=[_Detector({"stale"})]) == set()


# ───────────────── Qué se retira y qué no ─────────────────


@pytest.mark.asyncio
async def test_un_hallazgo_que_ya_no_se_emite_se_retira():
    viva = _Fila("stale")
    caducada = _Fila("stale")
    sesion = _Sesion([viva, caducada])

    retirados = await reconciliar_hallazgos(
        sesion, _SITIO, tipos={"stale"}, emitidos=[_Emitido(viva)], now=_AHORA
    )

    assert retirados == 1
    assert caducada.status == "resolved"
    assert viva.status == "new"


@pytest.mark.asyncio
async def test_el_retirado_dice_que_lo_retiro_el_sistema_y_cuando():
    """Un `resolved` sin nota se lee como «alguien lo arregló», y aquí nadie lo ha mirado."""
    caducada = _Fila("stale")
    sesion = _Sesion([caducada])

    await reconciliar_hallazgos(sesion, _SITIO, tipos={"stale"}, emitidos=[], now=_AHORA)

    assert caducada.reviewed_at == _AHORA
    assert caducada.reviewed_by is None
    assert "no se detecta" in (caducada.resolution_note or "").lower()


@pytest.mark.asyncio
async def test_lo_que_una_persona_descarto_no_se_toca():
    descartada = _Fila("stale", status="dismissed")
    sesion = _Sesion([descartada])

    await reconciliar_hallazgos(sesion, _SITIO, tipos={"stale"}, emitidos=[], now=_AHORA)

    assert descartada.status == "dismissed"


@pytest.mark.asyncio
async def test_un_hallazgo_confirmado_que_ya_no_se_ve_se_da_por_resuelto():
    """Alguien dijo que era real y ahora no aparece: eso es exactamente «se arregló»."""
    confirmada = _Fila("stale", status="confirmed")
    sesion = _Sesion([confirmada])

    retirados = await reconciliar_hallazgos(sesion, _SITIO, tipos={"stale"}, emitidos=[], now=_AHORA)

    assert retirados == 1
    assert confirmada.status == "resolved"


@pytest.mark.asyncio
async def test_un_tipo_fuera_de_la_reconciliacion_se_queda_como_esta():
    """Los tipos que este pase no cubre no se tocan, ni para bien ni para mal."""
    semantica = _Fila("contradiction")
    sesion = _Sesion([semantica])

    retirados = await reconciliar_hallazgos(sesion, _SITIO, tipos={"stale"}, emitidos=[], now=_AHORA)

    assert retirados == 0
    assert semantica.status == "new"


@pytest.mark.asyncio
async def test_la_identidad_incluye_la_pagina_relacionada():
    """Dos duplicados de la misma página contra páginas distintas son hallazgos distintos."""
    pagina = uuid.uuid4()
    contra_a = _Fila("duplicate", page_id=pagina, related_page_id=uuid.uuid4())
    contra_b = _Fila("duplicate", page_id=pagina, related_page_id=uuid.uuid4())
    sesion = _Sesion([contra_a, contra_b])

    await reconciliar_hallazgos(
        sesion, _SITIO, tipos={"duplicate"}, emitidos=[_Emitido(contra_a)], now=_AHORA
    )

    assert contra_a.status == "new"
    assert contra_b.status == "resolved"


def test_la_identidad_es_la_misma_clave_que_usa_el_upsert():
    """Si divergen, el upsert crearía una fila nueva y la reconciliación retiraría la vieja: el
    hallazgo parpadearía en cada pase."""
    fila = _Fila("duplicate", related_page_id=uuid.uuid4())

    assert identidad_del_hallazgo(fila) == identidad_del_hallazgo(_Emitido(fila))


# ───────────────── El job la ejecuta en cada análisis ─────────────────
#
# Reconciliar a mano no sirve de nada: lo que el usuario pidió es que pase **al analizar**. Y el sitio
# donde tiene que pasar es el job, porque es el único que sabe qué detectores han corrido y tiene la
# unión de lo que han emitido — cada despachador solo ve lo suyo.


class _DetectorQueEmite:
    finding_types = frozenset({"stale", "thin"})

    def __init__(self, hallazgos: list) -> None:
        self._hallazgos = hallazgos

    async def analyze(self, site_id: uuid.UUID) -> list:
        return self._hallazgos


class _DetectorSemanticoFalso:
    _is_semantic = True
    finding_types = frozenset({"duplicate", "contradiction"})

    async def analyze(self, site_id: uuid.UUID) -> list:
        return []


@pytest.mark.asyncio
async def test_el_job_reconcilia_al_terminar_la_deteccion(monkeypatch):
    from server.app.modules.curation import quality_job as modulo

    llamadas: list[dict] = []

    async def _espia(session, site_id, *, tipos, emitidos, now):
        llamadas.append({"site_id": site_id, "tipos": tipos, "emitidos": list(emitidos)})
        return 3

    monkeypatch.setattr(modulo, "reconciliar_hallazgos", _espia)

    hallazgo = _Fila("stale")
    job = _job_con(modulo, detectores=[_DetectorQueEmite([_Emitido(hallazgo)])])

    resumen = await job.run_for_site(_SITIO)

    assert llamadas, "el análisis tiene que reconciliar, no solo añadir"
    assert llamadas[0]["tipos"] == {"stale", "thin"}
    assert resumen.findings_retired == 3


@pytest.mark.asyncio
async def test_con_el_semantico_apagado_sus_tipos_quedan_fuera(monkeypatch):
    from server.app.modules.curation import quality_job as modulo

    recibidos: list[set] = []

    async def _espia(session, site_id, *, tipos, emitidos, now):
        recibidos.append(tipos)
        return 0

    monkeypatch.setattr(modulo, "reconciliar_hallazgos", _espia)

    job = _job_con(
        modulo,
        detectores=[_DetectorQueEmite([]), _DetectorSemanticoFalso()],
        run_semantic=False,
    )
    await job.run_for_site(_SITIO)

    assert "contradiction" not in recibidos[0]


def _job_con(modulo: Any, detectores: list, run_semantic: bool = True) -> Any:
    """Un job con lo mínimo para llegar a la reconciliación."""

    class _ResumenDeRastreo:
        pages_new = pages_changed = pages_gone = pages_error = pages_total = 0
        new_page_ids: list = []
        changed_page_ids: list = []

    class _Rastreador:
        async def crawl_site(
            self, site_id: uuid.UUID, section_id: uuid.UUID | None = None
        ) -> Any:
            return _ResumenDeRastreo()

    class _SesionDeJob(_Sesion):
        def __init__(self) -> None:
            super().__init__([])

        async def get(self, modelo: Any, ident: Any) -> Any:
            return None

        async def commit(self) -> None:
            return None

        async def __aenter__(self) -> "_SesionDeJob":
            return self

        async def __aexit__(self, *_: Any) -> None:
            return None

    class _Selecciones:
        async def list_by_site(self, site_id: uuid.UUID) -> list:
            return []

    sesion = _SesionDeJob()
    return modulo.SiteQualityAnalysisJob(
        session_factory=lambda: sesion,
        site_crawler=_Rastreador(),
        detectors=detectores,
        watcher=None,
        selection_repo=_Selecciones(),
        run_semantic=run_semantic,
    )


# ───────────────── La cola enseña lo abierto (CUR.9) ─────────────────
#
# Retirar no sirve si la fila sigue en la lista con la etiqueta «Resuelto»: el usuario pidió que no
# haya filas que ya no sean ciertas, y una retirada ya no lo es. La cola por defecto es lo **abierto**
# —`new` y `confirmed`—, y lo cerrado se puede ver eligiéndolo.


class TestElFiltroDeAbiertos:

    @pytest.mark.asyncio
    async def test_abierto_es_nuevo_o_confirmado(self):
        from server.app.modules.curation.findings_repo import ESTADOS_ABIERTOS

        assert ESTADOS_ABIERTOS == ("new", "confirmed")

    @pytest.mark.asyncio
    async def test_el_repo_entiende_abierto_como_los_dos_estados(self):
        from server.app.modules.curation.findings_repo import ContentFindingRepo

        capturadas: list = []

        class _SesionQueMira:
            async def execute(self, stmt: Any) -> Any:
                capturadas.append(str(stmt))

                class _R:
                    def scalars(self_inner) -> Any:
                        return self_inner

                    def all(self_inner) -> list:
                        return []

                return _R()

        await ContentFindingRepo(_SesionQueMira()).list_by_site(_SITIO, status="open")

        sql = capturadas[0]
        assert "IN" in sql.upper(), "«abierto» son dos estados, así que la consulta usa IN"
        assert "= :status_1" not in sql, "no puede compararse con el literal «open»"
