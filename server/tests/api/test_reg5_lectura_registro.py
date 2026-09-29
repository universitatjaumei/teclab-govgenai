"""REG.5 — leer y exportar el registro, acotado por organización.

La escritura de REG.2 es para máquinas y autentica un PAT. **La lectura es para personas** —el
panel de administración— y autentica la sesión, con rol admin o superadmin. No es simetría
descuidada: son dos usos distintos con dos poblaciones distintas, y darle a un PAT capacidad de
leer el registro entero sería regalar a cada integración una ventana a la actividad de toda la
organización.

Lo que estos tests fijan, por orden de importancia:

**La acotación por organización.** Un registro de gobernanza que enseñara a un administrador la
actividad de otra organización sería peor que no tener registro: convertiría la herramienta de
cumplimiento en la fuga. Va por `scope_query_to_orgs`, como el resto de los listados, y se
comprueba con dos organizaciones sembradas.

**El orden estable.** `ocurrido_en` viene de fuera y varias herramientas pueden declarar el mismo
instante —un lote que se registra de golpe lo hará—. Ordenar sólo por esa columna deja que el
planificador decida el orden dentro del empate, y entonces paginar puede repetir una fila en la
página 2 y perder otra: el mismo defecto que DET.1 arregló en el retriever, aquí sobre una tabla
que alguien va a auditar. De ahí el desempate por `id`.
"""
from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

import server.app.main  # noqa: F401

from server.app.api.deps import get_current_user
from server.app.core.auth.models import UserInfo

ORG_A = uuid.UUID("735a5f55-7020-4c88-a374-c2b641c5b00b")
ORG_B = uuid.UUID("00000000-0000-0000-0000-000000000010")

BASE = datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc)


@pytest.fixture
async def db_session(db_url):
    engine = create_async_engine(db_url)
    try:
        async with AsyncSession(engine) as session:
            yield session
    finally:
        await engine.dispose()


def _principal(rol: str, *orgs: uuid.UUID) -> UserInfo:
    return UserInfo(
        user_id="persona-1",
        email="admin@uji.es",
        role=rol,
        organizacion_ids=tuple(str(o) for o in orgs),
    )


def _cliente(session, principal: UserInfo) -> AsyncClient:
    """Cliente con sesión JWT: `request.state.pat_scopes` se queda a `None`.

    Es lo contrario del arnés de REG.2, y a propósito: allí se comprobaba que una sesión **no**
    puede escribir; aquí, que sí puede leer.
    """
    from server.app.modules.agents_hub.database.connection import get_async_session
    from server.app.routers.actividad_router import router

    async def _sesion():
        yield session

    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: principal
    app.dependency_overrides[get_async_session] = _sesion
    app.include_router(router, prefix="/api/v1")
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _siembra(session) -> None:
    """Cinco eventos: tres de A y dos de B, dos de ellos en el mismo instante."""
    from server.app.modules.agents_hub.database.operational_models import HubActividadIA

    filas = [
        (ORG_A, BASE, "claude-cowork", "Revisión de un pliego"),
        (ORG_A, BASE, "claude-cowork", "Otro pliego, mismo instante"),
        (ORG_A, BASE + timedelta(days=2), "copilot", "Generación de una consulta"),
        (ORG_B, BASE + timedelta(days=1), "claude-cowork", "Nada que ver con A"),
        (ORG_B, BASE + timedelta(days=3), "gemini-cli", "Tampoco"),
    ]
    for organizacion, cuando, herramienta, finalidad in filas:
        session.add(
            HubActividadIA(
                organizacion_id=organizacion,
                ocurrido_en=cuando,
                actor="u-1",
                herramienta=herramienta,
                finalidad=finalidad,
                categorias_datos=["datos_identificativos"],
            )
        )
    await session.commit()


# ─────────────────────────── La frontera entre organizaciones ──────────────


class TestCadaAdministradorVeLoSuyo:

    async def test_should_show_an_admin_only_their_own_organisation(self, db_session):
        """Un registro de cumplimiento que filtrara entre organizaciones sería la fuga."""
        await _siembra(db_session)

        async with _cliente(db_session, _principal("admin", ORG_A)) as c:
            r = await c.get("/api/v1/actividad")

        assert r.status_code == 200, r.text
        finalidades = {e["finalidad"] for e in r.json()["items"]}
        assert finalidades == {
            "Revisión de un pliego",
            "Otro pliego, mismo instante",
            "Generación de una consulta",
        }

    async def test_should_show_the_other_admin_theirs(self, db_session):
        await _siembra(db_session)

        async with _cliente(db_session, _principal("admin", ORG_B)) as c:
            r = await c.get("/api/v1/actividad")

        assert {e["finalidad"] for e in r.json()["items"]} == {
            "Nada que ver con A",
            "Tampoco",
        }

    async def test_should_show_a_superadmin_everything(self, db_session):
        await _siembra(db_session)

        async with _cliente(db_session, _principal("superadmin")) as c:
            r = await c.get("/api/v1/actividad")

        assert r.json()["total"] == 5

    async def test_should_show_nothing_to_an_admin_without_organisations(self, db_session):
        """Un claim vacío significa «ninguna», no «todas»: es el hallazgo A2 de SEC.2.

        Devolver el listado entero cuando la lista viene vacía es el fallo que `scope_query_to_orgs`
        existe para no repetir.
        """
        await _siembra(db_session)

        async with _cliente(db_session, _principal("admin")) as c:
            r = await c.get("/api/v1/actividad")

        assert r.status_code == 200, r.text
        assert r.json()["items"] == []

    async def test_should_refuse_a_plain_user(self, db_session):
        async with _cliente(db_session, _principal("user", ORG_A)) as c:
            r = await c.get("/api/v1/actividad")

        assert r.status_code == 403, r.text


# ─────────────────────────── Filtros ───────────────────────────────────────


class TestLosFiltros:

    async def test_should_filter_by_tool(self, db_session):
        await _siembra(db_session)

        async with _cliente(db_session, _principal("superadmin")) as c:
            r = await c.get("/api/v1/actividad", params={"herramienta": "copilot"})

        assert [e["herramienta"] for e in r.json()["items"]] == ["copilot"]

    async def test_should_filter_by_date_range_inclusive_on_both_ends(self, db_session):
        """Los dos extremos entran.

        Quien pide «del 1 al 3 de septiembre» cuenta con el 1 y con el 3; un rango abierto por
        arriba deja fuera el último día sin que nada lo diga, y en una auditoría eso es un
        agujero que no se ve.
        """
        await _siembra(db_session)

        async with _cliente(db_session, _principal("superadmin")) as c:
            r = await c.get(
                "/api/v1/actividad",
                params={
                    "desde": BASE.isoformat(),
                    "hasta": (BASE + timedelta(days=3)).isoformat(),
                },
            )

        assert r.json()["total"] == 5

    async def test_should_leave_out_what_falls_before_the_range(self, db_session):
        await _siembra(db_session)

        async with _cliente(db_session, _principal("superadmin")) as c:
            r = await c.get(
                "/api/v1/actividad",
                params={"desde": (BASE + timedelta(days=2)).isoformat()},
            )

        assert r.json()["total"] == 2

    async def test_should_combine_the_filters(self, db_session):
        await _siembra(db_session)

        async with _cliente(db_session, _principal("superadmin")) as c:
            r = await c.get(
                "/api/v1/actividad",
                params={
                    "herramienta": "claude-cowork",
                    "desde": (BASE + timedelta(days=1)).isoformat(),
                },
            )

        assert [e["finalidad"] for e in r.json()["items"]] == ["Nada que ver con A"]


# ─────────────────────────── Orden y paginación ────────────────────────────


class TestElOrdenAguanta:

    async def test_should_order_by_when_it_happened_newest_first(self, db_session):
        await _siembra(db_session)

        async with _cliente(db_session, _principal("superadmin")) as c:
            r = await c.get("/api/v1/actividad")

        ocurridos = [e["ocurrido_en"] for e in r.json()["items"]]
        assert ocurridos == sorted(ocurridos, reverse=True)

    async def test_should_not_repeat_or_lose_a_row_across_pages(self, db_session):
        """El test del desempate, y por qué es éste y no una comprobación del `ORDER BY`.

        Dos eventos comparten `ocurrido_en` a propósito en la siembra: `ocurrido_en` lo declara
        quien registra, y un lote que se manda de golpe trae el mismo instante repetido. Sin
        desempate, el planificador elige el orden dentro del empate y puede elegir uno distinto
        en cada consulta — con lo que una fila sale en las dos páginas y otra en ninguna. Se
        comprueba el síntoma y no la cláusula porque el síntoma es lo que le pasa a quien audita.
        """
        await _siembra(db_session)

        async with _cliente(db_session, _principal("superadmin")) as c:
            paginas = []
            for pagina in (1, 2, 3):
                r = await c.get(
                    "/api/v1/actividad", params={"page": pagina, "size": 2}
                )
                paginas.append([e["id"] for e in r.json()["items"]])

        recogidos = [ident for pagina in paginas for ident in pagina]
        assert len(recogidos) == 5
        assert len(set(recogidos)) == 5, (
            f"Una fila salió dos veces y otra en ninguna: {paginas}"
        )

    async def test_should_report_the_total_before_paging(self, db_session):
        """`total` cuenta lo que hay tras los filtros, no lo que cabe en la página."""
        await _siembra(db_session)

        async with _cliente(db_session, _principal("superadmin")) as c:
            r = await c.get("/api/v1/actividad", params={"page": 1, "size": 2})

        cuerpo = r.json()
        assert cuerpo["total"] == 5
        assert len(cuerpo["items"]) == 2

    async def test_should_reject_a_page_size_over_the_limit(self, db_session):
        """Sin tope, «size=100000» pide la tabla entera por un endpoint paginado."""
        async with _cliente(db_session, _principal("superadmin")) as c:
            r = await c.get("/api/v1/actividad", params={"size": 100_000})

        assert r.status_code == 422


# ─────────────────────────── El CSV ────────────────────────────────────────


class TestLaExportacion:

    async def test_should_open_with_the_contract_field_names(self, db_session):
        """Las cabeceras son los nombres del contrato y no etiquetas traducidas.

        Un CSV que alguien va a cruzar con otra fuente necesita nombres estables; los rótulos
        legibles son cosa del panel, que sí sabe en qué idioma está su lector.
        """
        await _siembra(db_session)

        async with _cliente(db_session, _principal("superadmin")) as c:
            r = await c.get("/api/v1/actividad/export")

        assert r.status_code == 200, r.text
        filas = list(csv.reader(io.StringIO(r.text)))
        assert filas[0] == [
            "ocurrido_en",
            "registrado_en",
            "actor",
            "herramienta",
            "agente",
            "finalidad",
            "modelo_usado",
            "categorias_datos",
            "payload_hash",
            # AUT.5 — con qué función registrada del catálogo se corresponde el uso, si con
            # alguna. Se añade al final: quien cruce el CSV por posición no se rompe.
            "funcion_sha256",
        ]

    async def test_should_carry_the_filtered_events(self, db_session):
        await _siembra(db_session)

        async with _cliente(db_session, _principal("superadmin")) as c:
            r = await c.get(
                "/api/v1/actividad/export", params={"herramienta": "copilot"}
            )

        filas = list(csv.DictReader(io.StringIO(r.text)))
        assert [f["finalidad"] for f in filas] == ["Generación de una consulta"]

    async def test_should_stay_inside_the_organisation(self, db_session):
        """La exportación acota igual que el listado: es la misma consulta."""
        await _siembra(db_session)

        async with _cliente(db_session, _principal("admin", ORG_A)) as c:
            r = await c.get("/api/v1/actividad/export")

        assert "Nada que ver con A" not in r.text
        assert len(list(csv.DictReader(io.StringIO(r.text)))) == 3

    async def test_should_arrive_as_a_file_to_save(self, db_session):
        await _siembra(db_session)

        async with _cliente(db_session, _principal("superadmin")) as c:
            r = await c.get("/api/v1/actividad/export")

        assert r.headers["content-type"].startswith("text/csv")
        assert "attachment" in r.headers.get("content-disposition", ""), (
            "sin esto el navegador lo pinta en una pestaña en vez de guardarlo."
        )

    async def test_should_refuse_a_plain_user(self, db_session):
        async with _cliente(db_session, _principal("user", ORG_A)) as c:
            r = await c.get("/api/v1/actividad/export")

        assert r.status_code == 403

    async def test_should_flatten_the_data_categories_into_one_cell(self, db_session):
        """Son una lista en JSON y una celda en CSV: el formato no admite anidamiento.

        Se separan por `;` y no por `,` porque la coma es el separador de campos del propio
        fichero, y una hoja de cálculo partiría la celda en dos columnas.
        """
        await _siembra(db_session)

        async with _cliente(db_session, _principal("superadmin")) as c:
            r = await c.get("/api/v1/actividad/export")

        filas = list(csv.DictReader(io.StringIO(r.text)))
        assert filas[0]["categorias_datos"] == "datos_identificativos"


class TestElContratoDeLaLectura:

    @pytest.mark.parametrize(
        "ruta", ["/api/v1/actividad", "/api/v1/actividad/export"]
    )
    def test_should_expose_each_endpoint_with_an_explicit_operation_id(self, ruta: str):
        from server.app.main import app
        from server.tests.rutas import operaciones_por_metodo

        # `rutas`, por lo mismo que en `test_reg8`: no llamar a la variable como a nada
        # importado.
        rutas = operaciones_por_metodo(app)
        assert (ruta, "GET") in rutas
        assert rutas[(ruta, "GET")], (
            "REG.6 consume estos endpoints por los hooks que Orval genera del `operation_id`."
        )
