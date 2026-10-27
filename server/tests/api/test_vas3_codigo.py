"""VAS.3 — la auditoría estática como servicio, con evento de registro y la caja publicada.

Es **la revisión posterior del nivel 2 de la Instrucció 02/2026 para código que no corre en la
plataforma**: la misma vara que el catálogo de funciones aplica a los scripts de dentro, prestada
a quien desarrolla fuera.

Lo que este fichero defiende:

**El veredicto es el del auditor, sin añadir ni quitar.** El test de paridad compara el
`AuditResult` de la API con el del auditor invocado directamente. Si la API «suavizara» un
CRITICAL o añadiera un hallazgo propio, la revisión de dentro y la de fuera dejarían de ser la
misma revisión, y entonces pasar por aquí no probaría nada.

**El código no se guarda: sólo su SHA-256.** Aquí llega, por definición, código que alguien está
a punto de ejecutar en otro sitio; guardarlo convertiría este servicio en un repositorio de
código ajeno que nadie ha decidido tener.

**La auditoría sí deja evento, a diferencia de los otros dos servicios.** Auditar es un acto de
gobernanza y tiene que constar: quién auditó qué hash, con qué nivel de riesgo y cuándo. Es la
asimetría deliberada del bloque, y está en un test para que nadie la «arregle» en ninguno de los
dos sentidos.

**La caja de herramientas se publica desde el código.** El endpoint de reglas lee los `frozenset`
del auditor; el test lo comprueba cambiándolos con un monkeypatch. Es lo que permite pedirle a la
UADTI que las contraste con las Guías Operativas Técnicas sin que el documento y el sistema puedan
divergir.
"""
from __future__ import annotations

import hashlib
import logging
import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import server.app.main  # noqa: F401

from server.app.api.deps import get_current_user
from server.app.core.auth.models import UserInfo

ORG = uuid.UUID("735a5f55-7020-4c88-a374-c2b641c5b00b")

LIMPIO = "import json\n\ndatos = json.loads('{}')\n"
CON_MODULO_FUERA = "import csv\n\nlector = csv.reader([])\n"
CON_EVAL = "resultado = eval('2 + 2')\n"

CENTINELA = "CENTINELA_DEL_CODIGO_AUDITADO"


def _principal(org: uuid.UUID | None = ORG) -> UserInfo:
    return UserInfo(
        user_id="agente-externo",
        email="integracion@uji.es",
        role="admin",
        organizacion_ids=(str(org),) if org else (),
    )


def _cliente(session, scopes=("verificaciones:use",), org=ORG) -> AsyncClient:
    from server.app.api.deps import get_session
    from server.app.routers.verificaciones_router import router

    async def _sesion():
        yield session

    app = FastAPI()

    @app.middleware("http")
    async def _marca_el_pat(request, call_next):
        request.state.pat_scopes = list(scopes) if scopes is not None else None
        return await call_next(request)

    app.dependency_overrides[get_current_user] = lambda: _principal(org)
    app.dependency_overrides[get_session] = _sesion
    app.include_router(router, prefix="/api/v1")
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ─────────────────────────── El veredicto ──────────────────────────────────


class TestElVeredicto:

    async def test_should_pass_a_clean_script(self, db_session):
        async with _cliente(db_session) as c:
            r = await c.post(
                "/api/v1/verificaciones/codigo", json={"codigo": LIMPIO}
            )

        assert r.status_code == 200, r.text
        cuerpo = r.json()
        assert cuerpo["risk_level"] == "SAFE"
        assert cuerpo["approved"] is True
        assert cuerpo["puede_revisarse"] is True
        assert cuerpo["findings"] == []

    async def test_should_warn_about_a_module_outside_the_whitelist(self, db_session):
        """Un hueco en una lista, no una capacidad: lo puede aceptar una persona mirándolo."""
        async with _cliente(db_session) as c:
            r = await c.post(
                "/api/v1/verificaciones/codigo", json={"codigo": CON_MODULO_FUERA}
            )

        cuerpo = r.json()
        assert cuerpo["risk_level"] == "WARNING"
        assert cuerpo["puede_revisarse"] is True
        assert cuerpo["findings"][0]["line"] == 1, "el hallazgo dice en qué línea está"
        assert cuerpo["findings"][0]["detail"] == "csv"

    async def test_should_reject_eval_as_critical(self, db_session):
        """Nadie acepta un `eval()` mirándolo, así que `puede_revisarse` es False."""
        async with _cliente(db_session) as c:
            r = await c.post(
                "/api/v1/verificaciones/codigo", json={"codigo": CON_EVAL}
            )

        cuerpo = r.json()
        assert cuerpo["risk_level"] == "CRITICAL"
        assert cuerpo["approved"] is False
        assert cuerpo["puede_revisarse"] is False

    async def test_should_return_the_hash_of_what_it_audited(self, db_session):
        async with _cliente(db_session) as c:
            r = await c.post(
                "/api/v1/verificaciones/codigo", json={"codigo": LIMPIO}
            )

        assert r.json()["code_sha256"] == hashlib.sha256(
            LIMPIO.encode("utf-8")
        ).hexdigest()


class TestParidadConElAuditor:
    """La regla dura: la revisión de fuera es **la misma** que la de dentro."""

    @pytest.mark.parametrize(
        "codigo",
        [LIMPIO, CON_MODULO_FUERA, CON_EVAL, "import os\n", "x = (\n", "abrir = open('a')\n"],
    )
    async def test_should_return_what_the_auditor_returns(self, db_session, codigo: str):
        from server.app.modules.redaccion.services.script_auditor import (
            ScriptSecurityAuditor,
        )

        del_auditor = ScriptSecurityAuditor().audit(codigo)

        async with _cliente(db_session) as c:
            r = await c.post("/api/v1/verificaciones/codigo", json={"codigo": codigo})

        cuerpo = r.json()
        assert cuerpo["risk_level"] == del_auditor.risk_level.value
        assert cuerpo["approved"] == del_auditor.approved
        assert cuerpo["puede_revisarse"] == del_auditor.puede_revisarse
        assert cuerpo["findings"] == [
            f.model_dump(mode="json") for f in del_auditor.findings
        ]


# ─────────────────────────── El código no se guarda ────────────────────────


class TestElCodigoNoSeGuarda:

    async def test_should_keep_the_code_out_of_every_log_record(self, db_session, caplog):
        with caplog.at_level(logging.DEBUG):
            async with _cliente(db_session) as c:
                r = await c.post(
                    "/api/v1/verificaciones/codigo",
                    json={"codigo": f"# {CENTINELA}\n{LIMPIO}"},
                )

        assert r.status_code == 200, r.text
        registrado = "\n".join(
            [reg.getMessage() for reg in caplog.records]
            + [str(reg.args) for reg in caplog.records]
        )
        assert CENTINELA not in registrado

    async def test_should_keep_the_code_out_of_the_activity_event(self, db_session):
        """El evento lleva el hash, y el hash es lo que permite cotejar sin guardar.

        El contrato de REG.1 ya rechaza cualquier campo de contenido, así que esto no puede
        pasar ni por descuido — pero se comprueba, porque la afirmación «no guardamos el código»
        es la que sostiene el servicio.
        """
        from sqlalchemy import select

        from server.app.modules.agents_hub.database.operational_models import (
            HubActividadIA,
        )

        async with _cliente(db_session) as c:
            await c.post(
                "/api/v1/verificaciones/codigo",
                json={"codigo": f"# {CENTINELA}\n{LIMPIO}"},
            )

        filas = (await db_session.execute(select(HubActividadIA))).scalars().all()
        assert filas, "la auditoría sí registra evento"
        entero = " ".join(str(f.__dict__) for f in filas)
        assert CENTINELA not in entero


# ─────────────────────────── El evento de registro ─────────────────────────


class TestElEventoDeRegistro:
    """La asimetría del bloque: **esto sí registra**, y citas y vigencia no."""

    async def test_should_record_an_activity_event(self, db_session):
        from sqlalchemy import select

        from server.app.modules.agents_hub.database.operational_models import (
            HubActividadIA,
        )

        async with _cliente(db_session) as c:
            await c.post(
                "/api/v1/verificaciones/codigo",
                json={"codigo": CON_EVAL, "finalidad": "Revisar un script de la UADTI"},
            )

        fila = (await db_session.execute(select(HubActividadIA))).scalars().one()
        assert fila.organizacion_id == ORG
        # La finalidad declarada se conserva, con el nivel de riesgo delante: el contrato de
        # REG.1 no tiene campo de nivel y no se le añade uno que sólo esta operación rellenaría
        # (ver `_registra_la_auditoria`), así que el nivel va aquí y esto no es igualdad.
        assert "Revisar un script de la UADTI" in fila.finalidad
        assert fila.payload_hash == hashlib.sha256(CON_EVAL.encode("utf-8")).hexdigest()

    async def test_should_record_the_risk_level(self, db_session):
        """Sin el nivel, el registro dice que alguien auditó y no si aquello era peligroso.

        Y eso es justo lo que una revisión posterior tiene que poder contar.
        """
        from sqlalchemy import select

        from server.app.modules.agents_hub.database.operational_models import (
            HubActividadIA,
        )

        async with _cliente(db_session) as c:
            await c.post("/api/v1/verificaciones/codigo", json={"codigo": CON_EVAL})

        fila = (await db_session.execute(select(HubActividadIA))).scalars().one()
        entero = f"{fila.finalidad} {fila.categorias_datos} {fila.agente}"
        assert "CRITICAL" in entero, (
            f"el nivel de riesgo no consta en el evento: {fila.__dict__}"
        )

    async def test_should_default_the_purpose_when_none_is_given(self, db_session):
        from sqlalchemy import select

        from server.app.modules.agents_hub.database.operational_models import (
            HubActividadIA,
        )

        async with _cliente(db_session) as c:
            await c.post("/api/v1/verificaciones/codigo", json={"codigo": LIMPIO})

        fila = (await db_session.execute(select(HubActividadIA))).scalars().one()
        assert fila.finalidad

    async def test_should_refuse_when_the_organisation_cannot_be_determined(
        self, db_session
    ):
        """Sin organización no hay dónde registrar, y auditar sin registrar no es esta operación.

        Es la misma decisión que `POST /actividad`: no se elige una organización por el
        llamante. Aquí importa más, porque el registro **es** parte del servicio.
        """
        async with _cliente(db_session, org=None) as c:
            r = await c.post("/api/v1/verificaciones/codigo", json={"codigo": LIMPIO})

        assert r.status_code == 403, r.text


# ─────────────────────────── La caja de herramientas ───────────────────────


class TestLaCajaDeHerramientas:

    async def test_should_publish_the_allowed_modules(self, db_session):
        from server.app.modules.redaccion.services.script_auditor import (
            WHITELIST_MODULES,
        )

        async with _cliente(db_session) as c:
            r = await c.get("/api/v1/verificaciones/codigo/reglas")

        assert r.status_code == 200, r.text
        assert set(r.json()["modulos_permitidos"]) == set(WHITELIST_MODULES)

    async def test_should_publish_the_denied_capabilities(self, db_session):
        from server.app.modules.redaccion.services.script_auditor import (
            MODULOS_PROHIBIDOS,
        )

        async with _cliente(db_session) as c:
            r = await c.get("/api/v1/verificaciones/codigo/reglas")

        assert set(MODULOS_PROHIBIDOS) <= set(r.json()["capacidades_denegadas"])

    async def test_should_publish_every_rule_the_auditor_can_emit(self, db_session):
        async with _cliente(db_session) as c:
            r = await c.get("/api/v1/verificaciones/codigo/reglas")

        publicadas = {regla["id"] for regla in r.json()["reglas"]}
        assert publicadas == {
            "syntax-error",
            "forbidden-call",
            "interpreter-access",
            "absolute-path",
            "forbidden-module",
            "module-not-whitelisted",
        }
        for regla in r.json()["reglas"]:
            assert regla["nivel"] in {"WARNING", "CRITICAL"}
            assert regla["descripcion"]

    async def test_should_derive_the_answer_from_the_auditor(self, db_session, monkeypatch):
        """El test que impide la lista paralela.

        Si la respuesta se construyera de una copia —en un `.md`, en un JSON o en el router—,
        cambiar el `frozenset` del auditor no cambiaría nada aquí. Y entonces las Guías
        Operativas Técnicas se contrastarían contra un documento y no contra el sistema.
        """
        from server.app.modules.redaccion.services import script_auditor

        monkeypatch.setattr(
            script_auditor, "WHITELIST_MODULES", frozenset({"solo_este"})
        )

        async with _cliente(db_session) as c:
            r = await c.get("/api/v1/verificaciones/codigo/reglas")

        assert r.json()["modulos_permitidos"] == ["solo_este"]

    async def test_should_change_the_version_when_the_toolbox_changes(
        self, db_session, monkeypatch
    ):
        """`version_auditor` existe para que un cliente sepa si la caja cambió."""
        from server.app.modules.redaccion.services import script_auditor

        async with _cliente(db_session) as c:
            antes = (await c.get("/api/v1/verificaciones/codigo/reglas")).json()

        monkeypatch.setattr(
            script_auditor,
            "WHITELIST_MODULES",
            frozenset(script_auditor.WHITELIST_MODULES | {"un_modulo_nuevo"}),
        )

        async with _cliente(db_session) as c:
            despues = (await c.get("/api/v1/verificaciones/codigo/reglas")).json()

        assert antes["version_auditor"] != despues["version_auditor"]

    async def test_should_keep_the_version_stable_across_calls(self, db_session):
        """Estable entre procesos, así que no puede salir de `hash()`, que va con sal.

        Un cliente que guarde la versión para saber si la caja cambió recibiría un cambio
        falso en cada reinicio del servidor.
        """
        async with _cliente(db_session) as c:
            una = (await c.get("/api/v1/verificaciones/codigo/reglas")).json()
            otra = (await c.get("/api/v1/verificaciones/codigo/reglas")).json()

        assert una["version_auditor"] == otra["version_auditor"]

    def test_should_not_have_a_parallel_list_of_rules(self):
        """El catálogo vive junto a los `frozenset`, en el auditor. No en el router.

        Un test de presencia y no de flujo: si el router escribiera las reglas, tendría los
        identificadores dentro.
        """
        from pathlib import Path

        fuente = (
            Path(__file__).resolve().parents[2]
            / "app"
            / "routers"
            / "verificaciones_router.py"
        ).read_text(encoding="utf-8")

        assert "module-not-whitelisted" not in fuente
        assert "interpreter-access" not in fuente


class TestElCatalogoDeReglasNoSeQuedaAtras:

    def test_should_catalogue_every_rule_id_the_auditor_emits(self):
        """El guardarraíl que el prompt no pedía y que hace falta.

        `audit()` escribe los identificadores de regla como literales en cada hallazgo. Si
        alguien añade una regla y no la cataloga, `/reglas` publicaría una caja de herramientas
        incompleta **sin que nada fallara** — y quien la consultara creería tener la lista
        entera. Se extraen del fuente y se comparan con el catálogo.
        """
        import re
        from pathlib import Path

        from server.app.modules.redaccion.services.script_auditor import REGLAS

        fuente = (
            Path(__file__).resolve().parents[2]
            / "app"
            / "modules"
            / "redaccion"
            / "services"
            / "script_auditor.py"
        ).read_text(encoding="utf-8")

        emitidas = set(re.findall(r'rule="([a-z-]+)"', fuente))
        catalogadas = {regla.id for regla in REGLAS}

        assert emitidas == catalogadas, (
            f"reglas que el auditor emite y no cataloga: {sorted(emitidas - catalogadas)}; "
            f"catalogadas que ya no emite: {sorted(catalogadas - emitidas)}"
        )


# ─────────────────────────── Límites y scope ───────────────────────────────


class TestLosLimites:

    async def test_should_reject_code_over_the_limit(self, db_session):
        from server.app.routers.verificaciones_router import MAXIMO_BYTES

        async with _cliente(db_session) as c:
            r = await c.post(
                "/api/v1/verificaciones/codigo",
                json={"codigo": "#" * (MAXIMO_BYTES + 1)},
            )

        assert r.status_code == 413, r.status_code

    @pytest.mark.parametrize("ruta", ["/codigo", "/codigo/reglas"])
    async def test_should_refuse_a_pat_without_the_scope(self, db_session, ruta: str):
        async with _cliente(db_session, scopes=["chatbots:read"]) as c:
            r = (
                await c.post(f"/api/v1/verificaciones{ruta}", json={"codigo": LIMPIO})
                if ruta == "/codigo"
                else await c.get(f"/api/v1/verificaciones{ruta}")
            )

        assert r.status_code == 403, r.text
        assert "verificaciones:use" in r.text

    @pytest.mark.parametrize(
        "ruta", ["/api/v1/verificaciones/codigo", "/api/v1/verificaciones/codigo/reglas"]
    )
    def test_should_expose_each_endpoint_with_an_explicit_operation_id(self, ruta: str):
        from server.app.main import app
        from server.tests.rutas import operaciones

        rutas = operaciones(app)
        assert ruta in rutas
        assert rutas[ruta]
