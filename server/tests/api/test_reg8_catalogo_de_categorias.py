"""REG.8 — el catálogo de categorías de datos, y por qué se anuncia sin imponerse.

`categorias_datos` nació como vocabulario abierto: `list[str]` sin validar. Eso resuelve un
problema y crea otro. El que resuelve: quien registra sabe qué datos trató, y una lista cerrada en
nuestro código haría que un caso legítimo se registrara mal o no se registrara. El que crea: si
cada herramienta inventa sus códigos —`datos_identificativos`, `identificativos`, `PII`—, el
registro **deja de poder agregarse**, que es exactamente para lo que existe en una auditoría del
AI Act. Y ningún canal automático lo arregla: ni el esquema MCP ni OpenAPI pueden transmitir un
vocabulario que no existe.

De ahí este catálogo, con dos decisiones que los tests fijan:

**Se anuncia, no se impone.** `GET /api/v1/actividad/categorias` da los códigos para que las
herramientas converjan, y el `POST` **sigue aceptando cualquiera**. Rechazar un código que no está
en el catálogo convertiría «esta categoría todavía no está dada de alta» en «este uso de IA no
queda registrado», y perder el registro es peor que tenerlo con una etiqueta imperfecta. Lo que sí
se hace es dejar los códigos sin catalogar **a la vista** en el panel, que es como el catálogo se
cura en vez de podrirse.

**Vive en `hub_vocabulary_terms` con un eje nuevo**, no en una tabla propia. Es el mecanismo que
el proyecto ya sanciona para esto —el vocabulario es dato y los ejes son estructura—, y trae
gratis lo que un catálogo de protección de datos va a necesitar: `vigent` para retirar una
categoría sin borrar el histórico, `substituit_per_codi` para renombrar dejando la traza, y el par
`nom_primari`/`nom_secundari` para las dos lenguas.
"""
from __future__ import annotations

import uuid

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import server.app.main  # noqa: F401

from server.app.api.deps import get_current_user
from server.app.core.auth.models import UserInfo

ORG_A = uuid.UUID("735a5f55-7020-4c88-a374-c2b641c5b00b")
ORG_B = uuid.UUID("00000000-0000-0000-0000-000000000010")

EJE = "categoria_dades"


def _principal(rol: str = "admin", *orgs: uuid.UUID) -> UserInfo:
    """Un principal del rol dado.

    Sin organizaciones explícitas, un superadministrador se queda con la **lista vacía**, que es
    lo que en `UserInfo` significa «todas»; cualquier otro rol cae en `ORG_A` para no repetirla
    en cada test. Antes esta función daba `ORG_A` también al superadministrador, y entonces el
    caso que comprueba `test_should_ask_a_superadmin_which_organisation` no se daba nunca: el
    test pasaba con la implementación equivocada.
    """
    if not orgs and rol != "superadmin":
        orgs = (ORG_A,)
    return UserInfo(
        user_id="persona-1",
        email="admin@uji.es",
        role=rol,
        organizacion_ids=tuple(str(o) for o in orgs),
    )


def _cliente(session, principal: UserInfo) -> AsyncClient:
    from server.app.api.deps import get_session
    from server.app.routers.actividad_router import router

    async def _sesion():
        yield session

    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: principal
    app.dependency_overrides[get_session] = _sesion
    app.include_router(router, prefix="/api/v1")
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _organizacion(session, org_id: uuid.UUID, nombre: str) -> None:
    from server.app.modules.agents_hub.database.config_models import HubOrganizacion

    session.add(HubOrganizacion(id=org_id, name=nombre, partner_id="partner-de-prueba"))
    await session.commit()


async def _termino(
    session,
    org_id: uuid.UUID,
    codi: str,
    nom: str,
    *,
    vigent: bool = True,
    substituit_per_codi: str | None = None,
    ordre: int = 0,
) -> None:
    from server.app.modules.agents_hub.database.config_models import HubVocabularyTerm

    session.add(
        HubVocabularyTerm(
            organizacion_id=org_id,
            axis=EJE,
            codi=codi,
            nom_primari=nom,
            ordre=ordre,
            vigent=vigent,
            substituit_per_codi=substituit_per_codi,
        )
    )
    await session.commit()


# ─────────────────────────── El eje es estructura ──────────────────────────


class TestElEjeNuevo:

    def test_should_add_the_axis_to_the_vocabulary_axes(self):
        """Los ejes van en `StrEnum` porque añadir uno exige código que lo consuma.

        Los términos, en cambio, son dato: por eso no hay ningún `Enum` con los códigos.
        """
        from server.app.modules.agents_hub.services.vocabulary_service import (
            VocabularyAxis,
        )

        assert VocabularyAxis.CATEGORIA_DADES == EJE

    def test_should_not_declare_the_codes_in_code(self):
        """La regla de CLAUDE.md §5: el vocabulario es dato, no código (I4).

        Un `Enum` o un `CheckConstraint` con las categorías convertiría «dar de alta una
        categoría» en «desplegar», y entonces nadie la daría de alta.
        """
        from pathlib import Path

        raiz = Path(__file__).resolve().parents[2] / "app"
        fuente = (raiz / "routers" / "actividad_router.py").read_text(encoding="utf-8")

        assert "datos_identificativos" not in fuente, (
            "los códigos vienen de la tabla; escritos aquí, el catálogo dejaría de ser dato."
        )


# ─────────────────────────── Servirlo ──────────────────────────────────────


class TestServirElCatalogo:

    async def test_should_serve_the_organisations_own_terms(self, db_session):
        await _organizacion(db_session, ORG_A, "UJI")
        await _termino(db_session, ORG_A, "datos_identificativos", "Datos identificativos")
        await _termino(db_session, ORG_A, "datos_de_salud", "Datos de salud", ordre=1)

        async with _cliente(db_session, _principal()) as c:
            r = await c.get("/api/v1/actividad/categorias")

        assert r.status_code == 200, r.text
        assert [t["codigo"] for t in r.json()] == [
            "datos_identificativos",
            "datos_de_salud",
        ]

    async def test_should_carry_the_label_so_the_panel_need_not_invent_it(self, db_session):
        await _organizacion(db_session, ORG_A, "UJI")
        await _termino(db_session, ORG_A, "datos_de_salud", "Datos de salud")

        async with _cliente(db_session, _principal()) as c:
            r = await c.get("/api/v1/actividad/categorias")

        (termino,) = r.json()
        assert termino["nombre"] == "Datos de salud"

    async def test_should_not_show_another_organisations_catalogue(self, db_session):
        """Cada administración clasifica a su manera; el catálogo es suyo."""
        await _organizacion(db_session, ORG_A, "UJI")
        await _organizacion(db_session, ORG_B, "Demo")
        await _termino(db_session, ORG_A, "solo_de_a", "Sólo de A")
        await _termino(db_session, ORG_B, "solo_de_b", "Sólo de B")

        async with _cliente(db_session, _principal("admin", ORG_A)) as c:
            r = await c.get("/api/v1/actividad/categorias")

        assert [t["codigo"] for t in r.json()] == ["solo_de_a"]

    async def test_should_leave_out_a_retired_category(self, db_session):
        """Retirada, no borrada: los eventos que la usaron siguen diciendo la verdad.

        Es lo que compra reutilizar `hub_vocabulary_terms`: una tabla propia habría tenido que
        reinventar esto, y lo probable es que hubiera empezado borrando filas.
        """
        await _organizacion(db_session, ORG_A, "UJI")
        await _termino(db_session, ORG_A, "vigente", "Vigente")
        await _termino(
            db_session,
            ORG_A,
            "retirada",
            "Retirada",
            vigent=False,
            substituit_per_codi="vigente",
        )

        async with _cliente(db_session, _principal()) as c:
            r = await c.get("/api/v1/actividad/categorias")

        assert [t["codigo"] for t in r.json()] == ["vigente"]

    async def test_should_say_where_a_renamed_category_went(self, db_session):
        """Con `?incluir_retiradas=true`, para quien tenga que reetiquetar lo ya registrado."""
        await _organizacion(db_session, ORG_A, "UJI")
        await _termino(db_session, ORG_A, "nueva", "Nueva")
        await _termino(
            db_session, ORG_A, "vieja", "Vieja", vigent=False, substituit_per_codi="nueva"
        )

        async with _cliente(db_session, _principal()) as c:
            r = await c.get(
                "/api/v1/actividad/categorias", params={"incluir_retiradas": True}
            )

        vieja = next(t for t in r.json() if t["codigo"] == "vieja")
        assert vieja["vigente"] is False
        assert vieja["sustituida_por"] == "nueva"

    async def test_should_answer_an_empty_catalogue_without_failing(self, db_session):
        """Una organización recién creada no tiene catálogo, y eso no es un error."""
        await _organizacion(db_session, ORG_A, "UJI")

        async with _cliente(db_session, _principal()) as c:
            r = await c.get("/api/v1/actividad/categorias")

        assert r.status_code == 200
        assert r.json() == []


# ─────────────────────────── Quién lo lee ──────────────────────────────────


class TestQuienPuedeLeerlo:

    async def test_should_let_a_machine_client_read_it(self, db_session):
        """Es el consumidor principal: sin el catálogo, la herramienta inventa códigos.

        No se exige rol ni módulo, a diferencia de la lectura del registro: saber cómo se llaman
        las categorías de tu propia organización no es privilegiado, y exigir el módulo
        `registro` dejaría fuera al token de máquina que sólo tiene `actividad:write`.
        """
        await _organizacion(db_session, ORG_A, "UJI")
        await _termino(db_session, ORG_A, "datos_identificativos", "Identificativos")

        async with _cliente(db_session, _principal("user", ORG_A)) as c:
            r = await c.get("/api/v1/actividad/categorias")

        assert r.status_code == 200, r.text
        assert len(r.json()) == 1

    async def test_should_refuse_without_any_credential(self, db_session):
        from server.app.api.deps import get_session
        from server.app.routers.actividad_router import router

        async def _sesion():
            yield db_session

        app = FastAPI()
        app.dependency_overrides[get_session] = _sesion
        app.include_router(router, prefix="/api/v1")

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            r = await c.get("/api/v1/actividad/categorias")

        assert r.status_code == 401

    async def test_should_ask_a_superadmin_which_organisation(self, db_session):
        """En un superadministrador la lista vacía significa «todas», así que no hay «la suya».

        Elegir una por él sería enseñarle un catálogo que no ha pedido y hacerle creer que es el
        único.
        """
        await _organizacion(db_session, ORG_A, "UJI")

        async with _cliente(db_session, _principal("superadmin")) as c:
            sin_decir = await c.get("/api/v1/actividad/categorias")
            diciendo = await c.get(
                "/api/v1/actividad/categorias", params={"organizacion_id": str(ORG_A)}
            )

        assert sin_decir.status_code == 400, sin_decir.text
        assert diciendo.status_code == 200, diciendo.text

    async def test_should_refuse_a_foreign_organisation(self, db_session):
        await _organizacion(db_session, ORG_A, "UJI")
        await _organizacion(db_session, ORG_B, "Demo")

        async with _cliente(db_session, _principal("admin", ORG_A)) as c:
            r = await c.get(
                "/api/v1/actividad/categorias", params={"organizacion_id": str(ORG_B)}
            )

        assert r.status_code == 403, r.text


# ─────────────────────────── Se anuncia, no se impone ──────────────────────


class TestElCatalogoNoRechazaNada:

    async def test_should_still_accept_a_category_outside_the_catalogue(self, db_session):
        """La decisión del prompt, y la que más importa.

        Rechazar un código no catalogado convertiría «esta categoría no está dada de alta» en
        «este uso de IA no queda registrado». Perder el registro es peor que tenerlo con una
        etiqueta imperfecta, y el código raro es justamente la señal de que al catálogo le falta
        una entrada.
        """
        from server.app.modules.agents_hub.contracts.actividad import ActividadIAEvent

        evento = ActividadIAEvent(
            ocurrido_en="2026-09-03T10:30:00+00:00",
            actor="u-1",
            herramienta="una-herramienta-nueva",
            finalidad="Algo que nadie previó",
            categorias_datos=["una_categoria_que_no_esta_en_el_catalogo"],
        )

        assert evento.categorias_datos == ["una_categoria_que_no_esta_en_el_catalogo"]

    def test_should_expose_the_endpoint_with_an_explicit_operation_id(self):
        from server.app.main import app
        from server.tests.rutas import operaciones

        # `rutas` y no `operaciones`: la variable local no se llama igual que la función que la
        # produce. Tal y como estaba **funcionaba** —el import dentro de la función liga el
        # nombre local antes de que la asignación lo lea, comprobado con una reproducción
        # mínima— pero queda a un refactor de romperse: si alguien sube ese import al nivel del
        # módulo, la misma línea lanza `UnboundLocalError` y el test deja de poder ejecutarse.
        # Lo señaló la revisión de la PR #76, con el diagnóstico equivocado y el arreglo bueno.
        rutas = operaciones(app)
        assert "/api/v1/actividad/categorias" in rutas
        assert rutas["/api/v1/actividad/categorias"]


class TestElRegistroSeSiembraConUnPuntoDePartida:

    def test_should_seed_a_starting_catalogue(self):
        """Un catálogo vacío no lo rellena nadie, y el primer integrador inventa códigos.

        Se siembra un punto de partida convencional —las categorías con las que se escribe un
        registro de actividades de tratamiento— y se dice en la documentación que **está
        pendiente de validar** por quien lleva ese registro. Es la misma postura que el
        vocabulario del corpus con Secretaría General, y por eso vive en la misma tabla.
        """
        from server.app.core.actividad_categorias import CATEGORIAS_INICIALES

        codigos = {codigo for codigo, _nombre in CATEGORIAS_INICIALES}

        assert "datos_identificativos" in codigos
        assert "datos_de_contacto" in codigos
        assert "sin_datos_personales" in codigos, (
            "hace falta poder decir «aquí no hubo datos personales»: sin ese código, una lista "
            "vacía es ambigua entre «ninguno» y «no lo declaré»."
        )

    def test_should_keep_the_migration_and_the_seed_saying_the_same_today(self):
        """La migración lleva su propia copia de la lista, y eso es deliberado.

        Una migración es un hecho histórico: tiene que seguir haciendo lo mismo dentro de un año,
        aunque la semilla del código cambie. Un `import` la ataría al presente y una instalación
        nueva se sembraría distinta que las viejas.

        Lo que no puede pasar es que **hoy** difieran, porque entonces una instalación recién
        migrada arrancaría con un catálogo que no es el que el código dice que hay. Esto lo caza.
        """
        import ast
        from pathlib import Path

        from server.app.core.actividad_categorias import CATEGORIAS_INICIALES

        ruta = next(
            (Path(__file__).resolve().parents[2] / "migrations" / "versions").glob(
                "*reg_8_catalogo*"
            )
        )
        arbol = ast.parse(ruta.read_text(encoding="utf-8"))
        asignada = next(
            nodo.value
            for nodo in ast.walk(arbol)
            if isinstance(nodo, ast.AnnAssign)
            and getattr(nodo.target, "id", None) == "_CATEGORIAS"
        )

        assert ast.literal_eval(asignada) == list(CATEGORIAS_INICIALES) or ast.literal_eval(
            asignada
        ) == CATEGORIAS_INICIALES, (
            "la lista de la migración y la del código han divergido: una instalación recién "
            "migrada tendría un catálogo distinto del que el código dice que hay."
        )
