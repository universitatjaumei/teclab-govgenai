"""Tests RAG.14 — huecos de corpus detectados desde señales de fallo.

La señal ya existe y no cuesta nada recogerla: RAG.2 persiste `fallback_reason` cada vez que
el chatbot no encuentra con qué responder, y el feedback bajo lleva ahí desde 9Q. Lo que
faltaba es leerlas juntas. Una pregunta sin respuesta es ruido; **veinte preguntas parecidas
sin respuesta son un documento que falta en el corpus**, y eso sí es accionable.

Dos decisiones que estos tests fijan:

- **Un hallazgo de hueco es del CHATBOT, no de un sitio web.** El resto de hallazgos de 9Q
  nacieron de auditar páginas; este nace de conversaciones. Forzarlo a colgar de un sitio
  sería inventarle un sitio a una pregunta.
- **La deduplicación es por centroide, no por texto.** «quant cobro de dieta» y «import de
  la dieta per dia» son el mismo hueco; comparar cadenas los contaría como dos y la cola de
  revisión se llenaría del mismo problema escrito de veinte maneras.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone

import pytest


def _casilla_de(palabra: str) -> int:
    """La dimensión que representa un tema. **Estable entre procesos, y ésa es la gracia.**

    Antes esto era `hash(palabra) % 1024`, y `hash()` de una cadena está aleatorizado por
    proceso (PYTHONHASHSEED). O sea que en aproximadamente **1 de cada 1024 ejecuciones** dos
    temas distintos caían en la misma casilla, quedaban a coseno 1 y el detector los agrupaba en
    uno: `test_should_separate_unrelated_topics` esperaba dos huecos y veía uno. Un fallo cada
    mil ejecuciones, en otro sitio cada vez, sin forma de reproducirlo — que es la peor forma de
    rojo que puede tener una suite, porque enseña a relanzar CI en vez de a mirar.

    `blake2b` no depende de la semilla del proceso: la misma palabra da la misma casilla hoy, en
    CI y dentro de un año. Y si dos palabras llegaran a compartirla, `embed` lo dice en voz alta
    en vez de devolver un resultado que parece bueno (ver abajo).
    """
    digest = hashlib.blake2b(palabra.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") % _DIMENSIONES


_DIMENSIONES = 1024


class _EmbeddingPorTema:
    """Embedding determinista: la primera palabra decide la dirección del vector.

    Las consultas que empiezan por el mismo término quedan a coseno 1; las que no, a 0. Es
    grosero a propósito — lo que se prueba es el mecanismo de agrupación, no la calidad de
    un modelo, misma postura que RAG.1 con el dorado.

    **Una colisión no se tolera en silencio.** Con 1024 casillas y un digest fijo, dos palabras
    podrían compartir casilla; si pasa, este doble haría indistinguibles dos temas que el caso
    declara distintos y el test mediría otra cosa mientras aparenta medir lo suyo. Al ser el
    digest fijo, además, ocurriría **siempre** y no una vez de cada mil: se ve la primera vez y
    se arregla cambiando una palabra del caso.
    """

    model_name = "test/por-tema"
    dimensions = _DIMENSIONES

    def __init__(self) -> None:
        #: casilla -> palabra que la ocupó, sólo para detectar colisiones.
        self._ocupadas: dict[int, str] = {}

    async def embed(self, text: str) -> list[float]:
        primera = (text.strip().split() or ["_"])[0].lower()
        casilla = _casilla_de(primera)

        anterior = self._ocupadas.setdefault(casilla, primera)
        if anterior != primera:
            raise AssertionError(
                f"«{primera}» y «{anterior}» caen en la misma casilla ({casilla}), así que este "
                "doble las haría indistinguibles y el caso mediría otra cosa. Cambia una de las "
                "dos palabras del escenario."
            )

        vector = [0.0] * _DIMENSIONES
        vector[casilla] = 1.0
        return vector


async def _chatbot(session):
    from server.tests.modules.agents_hub.integration.test_embedding_resolution import (
        _organizacion_y_chatbot,
    )

    _, chatbot = await _organizacion_y_chatbot(session)
    chatbot.name = f"Bot {uuid.uuid4().hex[:8]}"
    await session.flush()
    return chatbot


async def _interaccion(
    session,
    chatbot_id: uuid.UUID,
    mensaje: str,
    *,
    feedback: int | None = None,
    fallback: str | None = None,
    hace_dias: int = 1,
):
    from server.app.modules.agents_hub.database.operational_models import HubInteraction

    interaccion = HubInteraction(
        chatbot_id=chatbot_id,
        user_id="u1",
        user_message=mensaje,
        assistant_message="...",
        feedback_score=feedback,
        fallback_reason=fallback,
        created_at=datetime.now(timezone.utc) - timedelta(days=hace_dias),
    )
    session.add(interaccion)
    await session.flush()
    return interaccion


class TestRecogidaDeSenales:

    @pytest.mark.asyncio
    async def test_should_collect_low_feedback_interactions_as_signals(self, db_session):
        from server.app.modules.agents_hub.ingestion.gap_detector import (
            recoger_senales,
        )

        chatbot = await _chatbot(db_session)
        await _interaccion(db_session, chatbot.id, "dieta estranger", feedback=1)
        await _interaccion(db_session, chatbot.id, "dieta nacional", feedback=2)
        await _interaccion(db_session, chatbot.id, "contenta", feedback=5)
        await _interaccion(db_session, chatbot.id, "sin opinar")
        await db_session.commit()

        senales = await recoger_senales(db_session, chatbot.id)

        assert sorted(s.query for s in senales) == ["dieta estranger", "dieta nacional"]

    @pytest.mark.asyncio
    async def test_should_collect_citation_and_gate_fallbacks_as_signals(self, db_session):
        """La señal gratuita: el chatbot ya dijo «no encontré nada» y quedó registrado."""
        from server.app.modules.agents_hub.ingestion.gap_detector import (
            recoger_senales,
        )

        chatbot = await _chatbot(db_session)
        await _interaccion(db_session, chatbot.id, "teletreball dies", fallback="quality_gate")
        await _interaccion(db_session, chatbot.id, "teletreball ampliar", fallback="citation")
        await _interaccion(db_session, chatbot.id, "todo bien", fallback=None)
        await db_session.commit()

        senales = await recoger_senales(db_session, chatbot.id)

        assert len(senales) == 2
        assert {s.motivo for s in senales} == {"quality_gate", "citation"}

    @pytest.mark.asyncio
    async def test_should_scope_analysis_by_chatbot_and_time_window(self, db_session):
        from server.app.modules.agents_hub.ingestion.gap_detector import (
            recoger_senales,
        )

        chatbot = await _chatbot(db_session)
        otro = await _chatbot(db_session)
        await _interaccion(db_session, chatbot.id, "dentro", fallback="citation", hace_dias=5)
        await _interaccion(db_session, chatbot.id, "fuera", fallback="citation", hace_dias=90)
        await _interaccion(db_session, otro.id, "ajeno", fallback="citation", hace_dias=1)
        await db_session.commit()

        senales = await recoger_senales(db_session, chatbot.id, dias=30)

        assert [s.query for s in senales] == ["dentro"]


class TestElDobleNoDependeDelAzar:
    """El doble de embeddings no puede cambiar de una ejecución a otra.

    **Esto arregla un rojo real.** La suite completa con `-n0` —la configuración de CI— falló el
    2026-09-18 en `test_should_separate_unrelated_topics`, pasaba al ejecutarla sola, pasaba con
    su fichero entero, y las cinco ejecuciones anteriores de CI estaban verdes. Parecía estado
    filtrado entre tests; no lo era. El doble hacía `hash(palabra) % 1024`, y `hash()` de una
    cadena está **aleatorizado por proceso**: una vez de cada mil y pico, «dieta» y «teletreball»
    caían en la misma casilla, el detector las agrupaba en un solo hueco y el caso —que espera
    dos— se ponía rojo.

    Un rojo que aparece una vez de cada mil y en otro sitio cada vez no se investiga: se
    relanza. Por eso lo que se fija aquí no es el caso, es **la propiedad del doble**.
    """

    def test_la_casilla_de_un_tema_no_cambia_entre_procesos(self) -> None:
        """Con `hash()` este test fallaba casi siempre: el valor cambiaba en cada ejecución."""
        guion = (
            "import hashlib;"
            "print(int.from_bytes("
            "hashlib.blake2b('dieta'.encode('utf-8'), digest_size=8).digest(), 'big') % 1024)"
        )
        salidas = set()
        for semilla in ("0", "1", "12345"):
            entorno = {**os.environ, "PYTHONHASHSEED": semilla}
            salida = subprocess.run(
                [sys.executable, "-c", guion],
                capture_output=True, text=True, check=True, env=entorno,
            )
            salidas.add(salida.stdout.strip())

        assert salidas == {str(_casilla_de("dieta"))}, (
            "La casilla de un tema cambia según la semilla del proceso. Ése era exactamente el "
            f"defecto: {salidas}. Un doble que depende del azar del intérprete produce un rojo "
            "cada mil ejecuciones y en otro sitio cada vez."
        )

    def test_los_dos_temas_del_caso_no_comparten_casilla(self) -> None:
        """Lo que el caso de abajo da por hecho, comprobado en vez de supuesto."""
        assert _casilla_de("dieta") != _casilla_de("teletreball")

    async def test_una_colision_se_dice_en_voz_alta(self) -> None:
        """Si algún día dos palabras coincidieran, el doble tiene que romper, no mentir.

        Se fuerza la colisión buscando por fuerza bruta una palabra que comparta casilla con
        «dieta». Con 1024 casillas existe seguro, y al ser el digest fijo la búsqueda es
        reproducible: este test no puede volverse intermitente.
        """
        objetivo = _casilla_de("dieta")
        gemela = next(
            p for p in (f"x{n}" for n in range(200_000)) if _casilla_de(p) == objetivo
        )

        doble = _EmbeddingPorTema()
        await doble.embed("dieta a")
        with pytest.raises(AssertionError, match="misma casilla"):
            await doble.embed(f"{gemela} a")


class TestAgrupacion:

    @pytest.mark.asyncio
    async def test_should_cluster_similar_queries_into_one_gap(self, db_session):
        from server.app.modules.agents_hub.ingestion.gap_detector import (
            detectar_huecos,
        )

        chatbot = await _chatbot(db_session)
        for pregunta in ("dieta estranger", "dieta nacional", "dieta justificar"):
            await _interaccion(db_session, chatbot.id, pregunta, fallback="citation")
        await db_session.commit()

        huecos = await detectar_huecos(db_session, chatbot.id, _EmbeddingPorTema())

        assert len(huecos) == 1
        assert huecos[0].signal["count"] == 3
        assert len(huecos[0].signal["queries"]) == 3

    @pytest.mark.asyncio
    async def test_should_ignore_clusters_below_min_size(self, db_session):
        """Dos preguntas parecidas son casualidad; el umbral es lo que separa una señal de
        un hueco. Sin él, la cola de revisión se llena de ruido y deja de mirarse."""
        from server.app.modules.agents_hub.ingestion.gap_detector import (
            detectar_huecos,
        )

        chatbot = await _chatbot(db_session)
        for pregunta in ("dieta estranger", "dieta nacional"):
            await _interaccion(db_session, chatbot.id, pregunta, fallback="citation")
        await db_session.commit()

        assert await detectar_huecos(db_session, chatbot.id, _EmbeddingPorTema()) == []

    @pytest.mark.asyncio
    async def test_should_create_content_gap_finding_with_representative_queries(
        self, db_session
    ):
        from server.app.modules.agents_hub.ingestion.gap_detector import (
            MAX_QUERIES_REPRESENTATIVAS,
            detectar_huecos,
        )

        chatbot = await _chatbot(db_session)
        for i in range(9):
            await _interaccion(
                db_session, chatbot.id, f"dieta pregunta {i}", fallback="citation"
            )
        await db_session.commit()

        huecos = await detectar_huecos(db_session, chatbot.id, _EmbeddingPorTema())

        hueco = huecos[0]
        assert hueco.finding_type == "content_gap"
        assert hueco.chatbot_id == chatbot.id
        assert hueco.site_id is None, "un hueco no cuelga de ningún sitio web"
        assert hueco.page_id is None
        assert hueco.signal["count"] == 9
        # Se guardan unas cuantas para que se entienda el hueco, no las nueve: el payload
        # es para leerlo, no un volcado.
        assert len(hueco.signal["queries"]) == MAX_QUERIES_REPRESENTATIVAS
        assert hueco.signal["first_seen"] and hueco.signal["last_seen"]
        assert hueco.signal["top_terms"]

    @pytest.mark.asyncio
    async def test_should_separate_unrelated_topics(self, db_session):
        from server.app.modules.agents_hub.ingestion.gap_detector import (
            detectar_huecos,
        )

        chatbot = await _chatbot(db_session)
        for pregunta in ("dieta a", "dieta b", "dieta c"):
            await _interaccion(db_session, chatbot.id, pregunta, fallback="citation")
        for pregunta in ("teletreball a", "teletreball b", "teletreball c"):
            await _interaccion(db_session, chatbot.id, pregunta, fallback="citation")
        await db_session.commit()

        huecos = await detectar_huecos(db_session, chatbot.id, _EmbeddingPorTema())

        assert len(huecos) == 2


class TestPersistenciaYDeduplicacion:

    @pytest.mark.asyncio
    async def test_should_not_duplicate_open_finding_for_same_cluster(self, db_session):
        """Analizar dos veces no crea dos hallazgos: actualiza el recuento del que hay.

        Sin esto, cada ejecución del detector añadiría una fila del mismo problema y la cola
        de revisión sería inservible en una semana.
        """
        from sqlalchemy import func, select

        from server.app.modules.agents_hub.database.operational_models import (
            HubContentFinding,
        )
        from server.app.modules.agents_hub.ingestion.gap_detector import (
            analizar_huecos,
        )

        chatbot = await _chatbot(db_session)
        for pregunta in ("dieta a", "dieta b", "dieta c"):
            await _interaccion(db_session, chatbot.id, pregunta, fallback="citation")
        await db_session.commit()

        primera = await analizar_huecos(db_session, chatbot.id, _EmbeddingPorTema())
        await db_session.commit()

        await _interaccion(db_session, chatbot.id, "dieta d", fallback="citation")
        await db_session.commit()
        segunda = await analizar_huecos(db_session, chatbot.id, _EmbeddingPorTema())
        await db_session.commit()

        assert primera == 1
        total = await db_session.scalar(
            select(func.count()).select_from(HubContentFinding)
            .where(HubContentFinding.finding_type == "content_gap")
        )
        assert total == 1, "el segundo análisis duplicó el hallazgo"
        assert segunda == 1

        fila = await db_session.execute(
            select(HubContentFinding).where(HubContentFinding.finding_type == "content_gap")
        )
        assert fila.scalar_one().signal_json["count"] == 4

    @pytest.mark.asyncio
    async def test_should_persist_a_gap_finding_without_a_site(self, db_session):
        """`site_id` pasa a nullable, y esa es la extensión del contrato 9Q que este
        prompt necesita: hasta ahora todo hallazgo colgaba de un sitio auditado."""
        from sqlalchemy import select

        from server.app.modules.agents_hub.database.operational_models import (
            HubContentFinding,
        )
        from server.app.modules.agents_hub.ingestion.gap_detector import (
            analizar_huecos,
        )

        chatbot = await _chatbot(db_session)
        for pregunta in ("dieta a", "dieta b", "dieta c"):
            await _interaccion(db_session, chatbot.id, pregunta, fallback="citation")
        await db_session.commit()

        await analizar_huecos(db_session, chatbot.id, _EmbeddingPorTema())
        await db_session.commit()

        fila = await db_session.execute(
            select(HubContentFinding).where(HubContentFinding.chatbot_id == chatbot.id)
        )
        hallazgo = fila.scalar_one()
        assert hallazgo.site_id is None
        assert hallazgo.status == "new"
        assert hallazgo.severity in ("info", "warning", "critical")

    @pytest.mark.asyncio
    async def test_should_reject_a_finding_with_neither_site_nor_chatbot(self, db_session):
        """Nullable no significa opcional: un hallazgo sin sujeto no se puede revisar."""
        from sqlalchemy.exc import IntegrityError

        from server.app.modules.agents_hub.database.operational_models import (
            HubContentFinding,
        )

        db_session.add(
            HubContentFinding(
                site_id=None,
                chatbot_id=None,
                finding_type="content_gap",
                severity="warning",
                confidence=0.5,
                detected_at=datetime.now(timezone.utc),
            )
        )
        with pytest.raises(IntegrityError):
            await db_session.commit()


class TestEndpointYComando:

    @pytest.mark.asyncio
    async def test_should_expose_an_admin_endpoint_to_analyze(self, db_session):
        from unittest.mock import AsyncMock, patch

        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        from server.app.api.deps import get_current_user
        from server.app.core.auth.models import UserInfo
        from server.app.api.deps import get_session
        from server.app.routers.hub_content_quality_router import router

        chatbot = await _chatbot(db_session)
        for pregunta in ("dieta a", "dieta b", "dieta c"):
            await _interaccion(db_session, chatbot.id, pregunta, fallback="citation")
        await db_session.commit()

        async def _sesion():
            yield db_session

        app = FastAPI()
        app.dependency_overrides[get_session] = _sesion
        app.dependency_overrides[get_current_user] = lambda: UserInfo(
            user_id="a1",
            email="admin@uji.es",
            role="admin",
            # SEC.8.1: leer los huecos de un chatbot exige pertenecer a su organización.
            organizacion_ids=(str(chatbot.organizacion_id),),
        )
        app.include_router(router, prefix="/api/v1")

        cliente = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        with patch(
            "server.app.routers.hub_content_quality_router.resolve_embedding_service",
            new=AsyncMock(return_value=_EmbeddingPorTema()),
        ):
            resp = await cliente.post(
                f"/api/v1/hub/quality/gaps/analyze?chatbot_id={chatbot.id}"
            )

        assert resp.status_code == 200, resp.text
        assert resp.json()["gaps_found"] == 1

    @pytest.mark.asyncio
    async def test_should_list_gaps_for_the_review_queue(self, db_session):
        """Un hallazgo que nadie puede ver es codigo muerto: el endpoint de 9Q filtra por
        SITIO y un hueco no tiene sitio, asi que sin este listado se escribirian hallazgos
        que no aparecen en ninguna cola."""

        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        from server.app.api.deps import get_current_user
        from server.app.core.auth.models import UserInfo
        from server.app.api.deps import get_session
        from server.app.modules.agents_hub.ingestion.gap_detector import (
            analizar_huecos,
        )
        from server.app.routers.hub_content_quality_router import router

        chatbot = await _chatbot(db_session)
        for pregunta in ("dieta a", "dieta b", "dieta c"):
            await _interaccion(db_session, chatbot.id, pregunta, fallback="citation")
        await db_session.commit()
        await analizar_huecos(db_session, chatbot.id, _EmbeddingPorTema())
        await db_session.commit()

        async def _sesion():
            yield db_session

        app = FastAPI()
        app.dependency_overrides[get_session] = _sesion
        app.dependency_overrides[get_current_user] = lambda: UserInfo(
            user_id="a1",
            email="admin@uji.es",
            role="admin",
            # SEC.8.1: leer los huecos de un chatbot exige pertenecer a su organización.
            organizacion_ids=(str(chatbot.organizacion_id),),
        )
        app.include_router(router, prefix="/api/v1")

        cliente = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        resp = await cliente.get(f"/api/v1/hub/quality/gaps?chatbot_id={chatbot.id}")

        assert resp.status_code == 200, resp.text
        huecos = resp.json()
        assert len(huecos) == 1
        assert huecos[0]["count"] == 3
        assert huecos[0]["status"] == "new"
        assert huecos[0]["top_terms"]

    def test_the_cli_exists_and_declares_its_scope(self):
        from server.app.modules.agents_hub.ingestion import detect_gaps

        assert "Deploy: edge" in (detect_gaps.__doc__ or "")
        assert hasattr(detect_gaps, "main")
