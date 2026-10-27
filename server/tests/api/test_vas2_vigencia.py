"""VAS.2 — el estado de vigencia de un documento, y el aviso que la plataforma pondría.

Una aplicación externa que cite normativa del mismo corpus no debería afirmar como vigente lo que
el asistente advertiría. Este endpoint le da el estado y **el aviso literal**, no un booleano que
cada cliente redacte a su manera.

Lo que este fichero defiende:

**El aviso es byte a byte el del motor.** Sale de `marca_de_vigencia` y `aviso_para`, las mismas
funciones que el grafo usa para hidratar la respuesta. Si el texto del aviso cambiara aquí y no
allí, dos superficies de la misma institución dirían cosas distintas sobre la misma norma — y la
que se equivoca es siempre la que nadie mira.

**Preguntar por lo que no se puede recuperar da 404, no «no validado».** Si respondiera «existe
pero no lo he validado», el propio título de la respuesta confirmaría que el documento existe, y
eso es una fuga de la frontera entre organizaciones disfrazada de cortesía. Lo mismo con lo que el
filtro cerrado excluye: superseded, no público, `us_assistents='no'`.

**La URL se normaliza con la misma función que el emparejador de citas.** El portal real sirve la
misma sección con y sin barra final y por http y https —lo documentó el bloque de curación—, así
que comparar la cadena tal cual produce 404 en documentos que existen.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import server.app.main  # noqa: F401

from server.app.api.deps import get_current_user
from server.app.core.auth.models import UserInfo

NORMA = "https://normativa.uji.es/html/reglament-permanencia.html"


def _principal(*orgs: uuid.UUID) -> UserInfo:
    return UserInfo(
        user_id="agente-externo",
        email="integracion@uji.es",
        role="admin",
        organizacion_ids=tuple(str(o) for o in orgs),
    )


def _cliente(session, principal: UserInfo, scopes=("verificaciones:use",)) -> AsyncClient:
    from server.app.api.deps import get_session
    from server.app.routers.verificaciones_router import router

    async def _sesion():
        yield session

    app = FastAPI()

    @app.middleware("http")
    async def _marca_el_pat(request, call_next):
        request.state.pat_scopes = list(scopes) if scopes is not None else None
        return await call_next(request)

    app.dependency_overrides[get_current_user] = lambda: principal
    app.dependency_overrides[get_session] = _sesion
    app.include_router(router, prefix="/api/v1")
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _organizacion(session) -> uuid.UUID:
    from server.app.modules.agents_hub.database.config_models import HubOrganizacion

    org = HubOrganizacion(
        id=uuid.uuid4(), name=f"Org {uuid.uuid4().hex[:6]}", partner_id="partner-de-prueba"
    )
    session.add(org)
    await session.flush()
    return org.id


async def _chatbot(session, organizacion_id: uuid.UUID) -> uuid.UUID:
    from server.app.modules.agents_hub.database.config_models import (
        HubChatbot,
        HubLLMConfig,
        HubProvider,
    )

    # `hub_llm_configs.provider` tiene FK a `hub_providers`, que la plantilla del test no
    # siembra: se merge por si otro helper de la misma sesion ya lo puso.
    await session.merge(
        HubProvider(id="google", name="Google", provider_type="google_genai")
    )
    await session.flush()

    llm = HubLLMConfig(
        id=uuid.uuid4(),
        provider="google",
        model_name="gemini-2.5-flash",
        label=f"llm-{uuid.uuid4().hex[:6]}",
    )
    session.add(llm)
    await session.flush()

    cb = HubChatbot(
        organizacion_id=organizacion_id,
        llm_config_id=llm.id,
        name=f"Chatbot {uuid.uuid4().hex[:6]}",
        system_prompt="x",
        sources=[],
    )
    session.add(cb)
    await session.flush()
    return cb.id


async def _documento(session, chatbot_id: uuid.UUID, **kwargs):
    from server.app.modules.agents_hub.database.operational_models import HubDocument

    defaults = dict(
        chatbot_id=chatbot_id,
        title="Reglamento de permanencia",
        canonical_url=NORMA,
        markdown_content="# Reglamento",
        content_hash=uuid.uuid4().hex + uuid.uuid4().hex,
        language="val",
        source_kind="publicacio",
        estat_vigencia="vigent",
        nivell_acces="public",
        us_assistents="si",
    )
    defaults.update(kwargs)
    doc = HubDocument(**defaults)
    session.add(doc)
    # `flush` y no `commit`: el endpoint recibe **esta misma sesion** por el override, asi que ve
    # la fila dentro de la transaccion. Con `commit` los objetos quedan expirados y el primer
    # `doc.id` de despues intenta refrescarlos fuera del contexto async — `MissingGreenlet`, que
    # se lee como un fallo del endpoint y es del arnes.
    await session.flush()
    return doc


# ─────────────────────────── El estado y el aviso ──────────────────────────


class TestElEstadoDeVigencia:

    async def test_should_report_a_validated_document_without_a_warning(self, db_session):
        org = await _organizacion(db_session)
        cb = await _chatbot(db_session, org)
        doc = await _documento(
            db_session,
            cb,
            vigencia_validada_el=datetime(2026, 8, 1, tzinfo=timezone.utc),
            vigencia_validada_per="Secretaria General",
        )

        async with _cliente(db_session, _principal(org)) as c:
            r = await c.get(
                "/api/v1/verificaciones/vigencia", params={"document_id": str(doc.id)}
            )

        assert r.status_code == 200, r.text
        cuerpo = r.json()
        assert cuerpo["vigencia_validada"] is True
        assert cuerpo["necesita_aviso"] is False
        assert cuerpo["aviso"] is None
        assert cuerpo["vigencia_validada_por"] == "Secretaria General"

    async def test_should_warn_about_a_document_nobody_validated(self, db_session):
        """`vigent?` es la duda del catálogo original: se advierte, no se oculta."""
        org = await _organizacion(db_session)
        cb = await _chatbot(db_session, org)
        doc = await _documento(db_session, cb, estat_vigencia="vigent?")

        async with _cliente(db_session, _principal(org)) as c:
            r = await c.get(
                "/api/v1/verificaciones/vigencia", params={"document_id": str(doc.id)}
            )

        cuerpo = r.json()
        assert cuerpo["vigencia_validada"] is False
        assert cuerpo["necesita_aviso"] is True
        assert cuerpo["aviso"]

    async def test_should_give_the_very_same_warning_the_engine_would(self, db_session):
        """Byte a byte, y por eso se compara con `aviso_para` y no con una cadena escrita aquí.

        Dos superficies de la misma institución que redacten distinto el mismo aviso acaban
        contradiciéndose, y la que se equivoca es la que nadie mira.
        """
        from server.app.modules.agents_hub.services.retrieval.vigencia import (
            aviso_para,
            marca_de_vigencia,
        )

        org = await _organizacion(db_session)
        cb = await _chatbot(db_session, org)
        doc = await _documento(db_session, cb, estat_vigencia="vigent?")

        class _Item:
            title = "Reglamento de permanencia"
            metadata = marca_de_vigencia(doc)

        del_motor = aviso_para([_Item()])

        async with _cliente(db_session, _principal(org)) as c:
            r = await c.get(
                "/api/v1/verificaciones/vigencia", params={"document_id": str(doc.id)}
            )

        assert r.json()["aviso"] == del_motor


# ─────────────────────────── Lo que no se puede recuperar ──────────────────


class TestLoQueNoSePuedeRecuperar:

    async def test_should_answer_404_for_another_organisations_document(self, db_session):
        """404 y no 403: el 403 confirmaría que existe."""
        propia = await _organizacion(db_session)
        ajena = await _organizacion(db_session)
        cb_ajeno = await _chatbot(db_session, ajena)
        doc = await _documento(db_session, cb_ajeno)

        async with _cliente(db_session, _principal(propia)) as c:
            r = await c.get(
                "/api/v1/verificaciones/vigencia", params={"document_id": str(doc.id)}
            )

        assert r.status_code == 404, r.text
        assert doc.title not in r.text, "ni el título: eso ya diría que existe."

    async def test_should_answer_404_for_a_document_the_closed_filter_excludes(
        self, db_session
    ):
        """`us_assistents='no'` dice «no para asistentes», y esto es un asistente externo."""
        org = await _organizacion(db_session)
        cb = await _chatbot(db_session, org)
        doc = await _documento(db_session, cb, us_assistents="no")

        async with _cliente(db_session, _principal(org)) as c:
            r = await c.get(
                "/api/v1/verificaciones/vigencia", params={"document_id": str(doc.id)}
            )

        assert r.status_code == 404, r.text

    async def test_should_answer_404_for_a_document_that_no_longer_rules(self, db_session):
        """`no_vigent` no entra en la búsqueda, así que tampoco se verifica por aquí.

        Es coherente con ACT.4: la norma derogada se lee por id con `read_document`, que es una
        consulta legítima y distinta de «¿puedo citar esto como vigente?».
        """
        org = await _organizacion(db_session)
        cb = await _chatbot(db_session, org)
        doc = await _documento(db_session, cb, estat_vigencia="no_vigent")

        async with _cliente(db_session, _principal(org)) as c:
            r = await c.get(
                "/api/v1/verificaciones/vigencia", params={"document_id": str(doc.id)}
            )

        assert r.status_code == 404, r.text

    async def test_should_answer_404_for_an_unknown_id(self, db_session):
        org = await _organizacion(db_session)

        async with _cliente(db_session, _principal(org)) as c:
            r = await c.get(
                "/api/v1/verificaciones/vigencia",
                params={"document_id": str(uuid.uuid4())},
            )

        assert r.status_code == 404


# ─────────────────────────── La URL ────────────────────────────────────────


class TestLaUrlSeNormaliza:

    @pytest.mark.parametrize(
        "variante",
        [
            NORMA,
            f"{NORMA}/",
            NORMA.replace("https://", "http://"),
            f"{NORMA}#art-4",
            NORMA.upper().replace("HTTPS", "https"),
        ],
    )
    async def test_should_resolve_the_same_document(self, db_session, variante: str):
        """La barra final, el esquema y el ancla no cambian de qué norma hablamos."""
        org = await _organizacion(db_session)
        cb = await _chatbot(db_session, org)
        doc = await _documento(db_session, cb)

        async with _cliente(db_session, _principal(org)) as c:
            r = await c.get("/api/v1/verificaciones/vigencia", params={"url": variante})

        assert r.status_code == 200, f"{variante}: {r.text}"
        assert r.json()["document_id"] == str(doc.id)

    def test_should_reuse_the_normaliser_of_the_citation_matcher(self):
        """La misma función, no una copia: dos normalizadores divergen en el primer caso raro.

        Vivía privada en `evaluation/escenario_metricas.py`; VAS.2 la sube a `core/urls.py` y
        aquel módulo la importa de ahí. Es lo que manda la regla del bloque: si el servicio
        necesita algo que la función no da —aquí, ser pública—, se cambia la función.
        """
        from server.app.core.urls import normalizar_url
        from server.app.modules.agents_hub.evaluation import escenario_metricas

        assert escenario_metricas._normaliza_url is normalizar_url


class TestLosDosParametros:

    async def test_should_refuse_both_at_once(self, db_session):
        org = await _organizacion(db_session)

        async with _cliente(db_session, _principal(org)) as c:
            r = await c.get(
                "/api/v1/verificaciones/vigencia",
                params={"document_id": str(uuid.uuid4()), "url": NORMA},
            )

        assert r.status_code == 422, r.text

    async def test_should_refuse_neither(self, db_session):
        org = await _organizacion(db_session)

        async with _cliente(db_session, _principal(org)) as c:
            r = await c.get("/api/v1/verificaciones/vigencia")

        assert r.status_code == 422, r.text


# ─────────────────────────── La pareja bilingüe ────────────────────────────


class TestLaVersionEnLaOtraLengua:

    async def test_should_point_at_the_sibling_declared_in_either_direction(
        self, db_session
    ):
        """El corpus declara `versio_idiomatica_de` en un solo lado, y ese lado es arbitrario.

        Resolverlo en un sentido dejaría la mitad de las parejas sin hermana según quién
        ingiriera primero, que no es una afirmación sobre nada.
        """
        org = await _organizacion(db_session)
        cb = await _chatbot(db_session, org)
        valenciana = await _documento(db_session, cb, language="val")
        castellana = await _documento(
            db_session,
            cb,
            language="es",
            canonical_url=f"{NORMA}?lang=es",
            versio_idiomatica_de=valenciana.id,
        )

        async with _cliente(db_session, _principal(org)) as c:
            desde_la_valenciana = await c.get(
                "/api/v1/verificaciones/vigencia",
                params={"document_id": str(valenciana.id)},
            )
            desde_la_castellana = await c.get(
                "/api/v1/verificaciones/vigencia",
                params={"document_id": str(castellana.id)},
            )

        assert desde_la_valenciana.json()["version_pareja"]["document_id"] == str(
            castellana.id
        )
        assert desde_la_castellana.json()["version_pareja"]["document_id"] == str(
            valenciana.id
        )

    async def test_should_say_none_when_there_is_no_sibling(self, db_session):
        org = await _organizacion(db_session)
        cb = await _chatbot(db_session, org)
        doc = await _documento(db_session, cb)

        async with _cliente(db_session, _principal(org)) as c:
            r = await c.get(
                "/api/v1/verificaciones/vigencia", params={"document_id": str(doc.id)}
            )

        assert r.json()["version_pareja"] is None


# ─────────────────────────── Sin evento, y con scope ───────────────────────


class TestSinEventoDeRegistro:

    async def test_should_not_record_an_activity_event(self, db_session):
        """La regla del bloque, escrita en un test para que nadie la «arregle».

        Consultar vigencia es una comprobación sin estado. La aplicación externa registra **su**
        actividad por REG.2; un evento por cada comprobación duplicaría el registro sin decir
        nada nuevo, y encima haría que auditar el registro fuera leer ruido.
        """
        from sqlalchemy import func, select

        from server.app.modules.agents_hub.database.operational_models import (
            HubActividadIA,
        )

        org = await _organizacion(db_session)
        cb = await _chatbot(db_session, org)
        doc = await _documento(db_session, cb)

        antes = (
            await db_session.execute(select(func.count()).select_from(HubActividadIA))
        ).scalar_one()

        async with _cliente(db_session, _principal(org)) as c:
            await c.get(
                "/api/v1/verificaciones/vigencia", params={"document_id": str(doc.id)}
            )

        despues = (
            await db_session.execute(select(func.count()).select_from(HubActividadIA))
        ).scalar_one()
        assert despues == antes


class TestElScope:

    async def test_should_refuse_a_pat_without_the_scope(self, db_session):
        org = await _organizacion(db_session)

        async with _cliente(db_session, _principal(org), scopes=["chatbots:read"]) as c:
            r = await c.get(
                "/api/v1/verificaciones/vigencia",
                params={"document_id": str(uuid.uuid4())},
            )

        assert r.status_code == 403, r.text
        assert "verificaciones:use" in r.text

    def test_should_expose_the_endpoint_with_an_explicit_operation_id(self):
        from server.app.main import app
        from server.tests.rutas import operaciones

        rutas = operaciones(app)
        assert "/api/v1/verificaciones/vigencia" in rutas
        assert rutas["/api/v1/verificaciones/vigencia"]
