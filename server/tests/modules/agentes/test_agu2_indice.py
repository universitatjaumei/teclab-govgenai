"""#173 — el índice como corpus ligero: una ficha por documento, sin troceado.

Un agente de unidad no promete citar el artículo exacto; promete «esto es lo que dicen los
documentos aplicables». Así que no se paga la maquinaria del corpus normativo: **una ficha por
documento**, un vector por ficha, y reconstruirlo entero cuesta minutos.

Lo que fija este fichero:

* **La carga es el estado completo, no un delta.** Lo que no viene se retira: un delta por fecha
  no sabe expresar una baja, y quien consume no la distinguiría de «no ha cambiado».
* **Incremental por huella.** Lo que no cambió no se vuelve a embeber; lo que cambió sólo en su
  vigencia o sus metadatos, tampoco: el vector es del título y el resumen.
* **En el texto embebido sólo va el título y el resumen** (regla 5 de AGENTS.md): los metadatos
  cambian, y cambiarlos no puede obligar a re-embeber.
* **La vigencia va en el `WHERE`**, no después del top-k: una ficha descartada en memoria ya ha
  consumido una plaza del presupuesto.
* **El presupuesto es el del agente**: nunca más documentos que los que declaró.
* **La plataforma no guarda ni un documento**: guarda la ficha y la URL.
"""
from __future__ import annotations

import math
import uuid
from datetime import date, timedelta

import pytest

from server.app.core.auth.models import UserInfo

ORG = uuid.uuid4()
AUTORA = str(uuid.uuid4())

#: Las palabras que distinguen los documentos de prueba. El vector falso tiene un eje por palabra.
_EJES = ("contrato", "subvencion", "viaje", "matricula")
DIMENSION = 1024


class EmbebedorFalso:
    """Un vector por palabras clave: lo bastante para ordenar sin red y sin modelos."""

    model_name = "falso-1"
    dimensions = DIMENSION
    embedding_task_type = None

    def __init__(self) -> None:
        self.textos: list[str] = []

    def _vector(self, texto: str) -> list[float]:
        bajo = texto.lower()
        v = [float(bajo.count(p)) for p in _EJES] + [0.01] + [0.0] * (DIMENSION - len(_EJES) - 1)
        norma = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norma for x in v]

    async def embed(self, texto: str, purpose: str | None = None) -> list[float]:
        return self._vector(texto)

    async def embed_batch(self, textos: list[str], purpose: str | None = None) -> list[list[float]]:
        self.textos.extend(textos)
        return [self._vector(t) for t in textos]


def _ficha(n: int, tema: str, **cambios):
    from server.app.modules.agentes.indice import FichaEntrada

    base = dict(
        url=f"https://drive.google.com/file/d/doc{n}",
        titulo=f"Documento {n} sobre {tema}",
        resumen=f"Resumen del documento {n}: trata de {tema} y de {tema} otra vez.",
    )
    base.update(cambios)
    return FichaEntrada(**base)


async def _agente(db_session, *, estado="registrada", presupuesto=5, colectivo="organizacion", grupos=None):
    from datetime import datetime, timezone

    from server.app.core.identidad import user_to_uuid
    from server.app.modules.agents_hub.database.operational_models import (
        HubAgenteUnidad,
        HubAgenteUnidadVersion,
    )

    agente = HubAgenteUnidad(
        id=uuid.uuid4(), organizacion_id=ORG, nombre="Contratación", unidad="Servicio",
        creado_por=user_to_uuid(AUTORA),
    )
    db_session.add(agente)
    await db_session.flush()
    version = HubAgenteUnidadVersion(
        agente_id=agente.id, version=1, estado=estado, prompt="p",
        carpeta_url="https://drive.google.com/drive/folders/x", finalidad="f", responsable="r",
        colectivo=colectivo, grupos=grupos or [], revision_prevista_en=date.today() + timedelta(days=90),
        presupuesto_documentos=presupuesto,
        declarada_por=user_to_uuid(AUTORA), declarada_en=datetime.now(timezone.utc),
    )
    db_session.add(version)
    await db_session.commit()
    return agente, version


def _persona(orgs=(ORG,), grupos=()) -> UserInfo:
    return UserInfo(
        user_id=str(uuid.uuid4()), email="p@uji.es", role="user",
        organizacion_ids=tuple(str(o) for o in orgs), saml_groups=tuple(grupos),
    )


class TestCarga:

    @pytest.mark.asyncio
    async def test_una_carga_nueva_crea_una_ficha_por_documento(self, db_session):
        from server.app.modules.agentes.indice import cargar

        agente, _ = await _agente(db_session)
        emb = EmbebedorFalso()
        informe = await cargar(db_session, agente.id, [_ficha(1, "contrato"), _ficha(2, "viaje")], emb)

        assert (informe.nuevas, informe.actualizadas, informe.sin_cambios, informe.retiradas) == (2, 0, 0, 0)
        assert len(emb.textos) == 2

    @pytest.mark.asyncio
    async def test_en_el_texto_embebido_solo_van_el_titulo_y_el_resumen(self, db_session):
        """Regla 5: cambiar una etiqueta no puede obligar a re-embeber."""
        from server.app.modules.agentes.indice import cargar

        agente, _ = await _agente(db_session)
        emb = EmbebedorFalso()
        ficha = _ficha(1, "contrato", metadatos={"materia": "CONTRATACION_MENOR"})
        await cargar(db_session, agente.id, [ficha], emb)

        assert emb.textos == [f"{ficha.titulo}\n\n{ficha.resumen}"]
        assert "CONTRATACION_MENOR" not in emb.textos[0]

    @pytest.mark.asyncio
    async def test_volver_a_cargar_lo_mismo_no_embebe_nada(self, db_session):
        from server.app.modules.agentes.indice import cargar

        agente, _ = await _agente(db_session)
        fichas = [_ficha(1, "contrato"), _ficha(2, "viaje")]
        await cargar(db_session, agente.id, fichas, EmbebedorFalso())

        emb = EmbebedorFalso()
        informe = await cargar(db_session, agente.id, fichas, emb)
        assert (informe.nuevas, informe.actualizadas, informe.sin_cambios) == (0, 0, 2)
        assert emb.textos == []

    @pytest.mark.asyncio
    async def test_cambiar_el_resumen_reembebe_solo_esa(self, db_session):
        from server.app.modules.agentes.indice import cargar

        agente, _ = await _agente(db_session)
        await cargar(db_session, agente.id, [_ficha(1, "contrato"), _ficha(2, "viaje")], EmbebedorFalso())

        emb = EmbebedorFalso()
        informe = await cargar(
            db_session, agente.id,
            [_ficha(1, "contrato", resumen="Otro resumen del contrato."), _ficha(2, "viaje")], emb,
        )
        assert (informe.actualizadas, informe.sin_cambios) == (1, 1)
        assert emb.textos == ["Documento 1 sobre contrato\n\nOtro resumen del contrato."]

    @pytest.mark.asyncio
    async def test_cambiar_solo_la_vigencia_o_los_metadatos_no_reembebe(self, db_session):
        from server.app.modules.agentes.indice import cargar

        agente, _ = await _agente(db_session)
        await cargar(db_session, agente.id, [_ficha(1, "contrato")], EmbebedorFalso())

        emb = EmbebedorFalso()
        informe = await cargar(
            db_session, agente.id, [_ficha(1, "contrato", vigente=False, metadatos={"a": "b"})], emb
        )
        assert informe.actualizadas == 1
        assert emb.textos == []

    @pytest.mark.asyncio
    async def test_lo_que_no_viene_se_retira(self, db_session):
        """Estado completo, no delta: una baja es una ficha que deja de venir."""
        from sqlalchemy import func, select

        from server.app.modules.agentes.indice import cargar
        from server.app.modules.agents_hub.database.operational_models import HubAgenteFicha

        agente, _ = await _agente(db_session)
        await cargar(db_session, agente.id, [_ficha(1, "contrato"), _ficha(2, "viaje")], EmbebedorFalso())
        informe = await cargar(db_session, agente.id, [_ficha(1, "contrato")], EmbebedorFalso())

        assert informe.retiradas == 1
        quedan = (await db_session.execute(
            select(func.count()).select_from(HubAgenteFicha).where(HubAgenteFicha.agente_id == agente.id)
        )).scalar_one()
        assert quedan == 1

    @pytest.mark.asyncio
    async def test_el_indice_de_un_agente_no_toca_el_de_otro(self, db_session):
        from server.app.modules.agentes.indice import cargar

        uno, _ = await _agente(db_session)
        otro, _ = await _agente(db_session)
        await cargar(db_session, uno.id, [_ficha(1, "contrato")], EmbebedorFalso())
        informe = await cargar(db_session, otro.id, [_ficha(2, "viaje")], EmbebedorFalso())
        assert informe.retiradas == 0

    @pytest.mark.asyncio
    async def test_dos_cargas_a_la_vez_del_mismo_agente_no_chocan(self, db_session, db_url):
        """Lo destapó la verificación en navegador: dos cargas simultáneas leían el índice vacío,
        las dos insertaban, y una moría en la restricción única con un 500. Es lo que pasaría si
        el guion de curación y una persona cargan a la vez. Se serializan por agente."""
        import asyncio

        from sqlalchemy import func, select

        from server.app.modules.agentes.indice import cargar
        from server.app.modules.agents_hub.database.connection import (
            create_async_engine,
            create_session_factory,
        )
        from server.app.modules.agents_hub.database.operational_models import HubAgenteFicha

        class Lento(EmbebedorFalso):
            async def embed_batch(self, textos, purpose=None):
                # Lo bastante para que la otra carga lea el índice antes de que ésta escriba.
                await asyncio.sleep(0.3)
                return await super().embed_batch(textos, purpose)

        agente, _ = await _agente(db_session)
        fichas = [_ficha(1, "contrato"), _ficha(2, "viaje")]
        engine = create_async_engine(db_url)
        fabrica = create_session_factory(engine)
        try:
            async with fabrica() as uno, fabrica() as otro:
                informes = await asyncio.gather(
                    cargar(uno, agente.id, fichas, Lento()),
                    cargar(otro, agente.id, fichas, Lento()),
                )
        finally:
            await engine.dispose()

        assert sorted(i.nuevas for i in informes) == [0, 2]
        assert sorted(i.sin_cambios for i in informes) == [0, 2]
        quedan = (await db_session.execute(
            select(func.count()).select_from(HubAgenteFicha).where(HubAgenteFicha.agente_id == agente.id)
        )).scalar_one()
        assert quedan == 2

    @pytest.mark.parametrize(
        "fichas, motivo",
        [
            (lambda: [_ficha(1, "contrato"), _ficha(1, "viaje")], "repetida"),
            (lambda: [_ficha(1, "contrato", url="http://intranet/doc")], "https"),
            (lambda: [_ficha(1, "contrato", resumen="  ")], "resumen"),
            (lambda: [_ficha(1, "contrato", titulo="")], "título"),
        ],
    )
    @pytest.mark.asyncio
    async def test_una_hoja_incoherente_no_se_carga_a_medias(self, db_session, fichas, motivo):
        from server.app.modules.agentes.indice import IndiceNoValido, cargar

        agente, _ = await _agente(db_session)
        with pytest.raises(IndiceNoValido, match=motivo):
            await cargar(db_session, agente.id, fichas(), EmbebedorFalso())


class TestSeleccion:

    async def _con_indice(self, db_session, **agente):
        from server.app.modules.agentes.indice import cargar

        a, v = await _agente(db_session, **agente)
        await cargar(
            db_session, a.id,
            [_ficha(1, "contrato"), _ficha(2, "subvencion"), _ficha(3, "viaje"), _ficha(4, "matricula")],
            EmbebedorFalso(),
        )
        return a, v

    @pytest.mark.asyncio
    async def test_devuelve_lo_pertinente_primero(self, db_session):
        from server.app.modules.agentes.indice import seleccionar

        a, v = await self._con_indice(db_session)
        elegidas = await seleccionar(db_session, a, v, "requisitos de un contrato menor", EmbebedorFalso(), principal=_persona())
        assert elegidas[0].url.endswith("doc1")

    @pytest.mark.asyncio
    async def test_nunca_mas_que_el_presupuesto_del_agente(self, db_session):
        from server.app.modules.agentes.indice import seleccionar

        a, v = await self._con_indice(db_session, presupuesto=2)
        elegidas = await seleccionar(db_session, a, v, "contrato", EmbebedorFalso(), principal=_persona())
        assert len(elegidas) == 2

    @pytest.mark.asyncio
    async def test_lo_no_vigente_no_ocupa_plaza(self, db_session):
        """En el WHERE: si se filtrara después del top-k, la plaza ya estaría gastada."""
        from server.app.modules.agentes.indice import cargar, seleccionar

        a, v = await _agente(db_session, presupuesto=1)
        await cargar(
            db_session, a.id,
            [_ficha(1, "contrato", vigente=False), _ficha(2, "contrato viaje")],
            EmbebedorFalso(),
        )
        elegidas = await seleccionar(db_session, a, v, "contrato", EmbebedorFalso(), principal=_persona())
        assert [e.url for e in elegidas] == ["https://drive.google.com/file/d/doc2"]

    @pytest.mark.asyncio
    async def test_una_ficha_con_la_revision_vencida_se_devuelve_marcada(self, db_session):
        from server.app.modules.agentes.indice import cargar, seleccionar

        a, v = await _agente(db_session)
        ayer = date.today() - timedelta(days=1)
        await cargar(db_session, a.id, [_ficha(1, "contrato", revision_prevista_en=ayer)], EmbebedorFalso())
        elegidas = await seleccionar(db_session, a, v, "contrato", EmbebedorFalso(), principal=_persona())
        assert elegidas[0].revision_vencida is True

    @pytest.mark.asyncio
    async def test_quien_no_es_del_colectivo_no_obtiene_nada(self, db_session):
        from server.app.modules.agentes.indice import AgenteNoDisponible, seleccionar

        a, v = await self._con_indice(db_session, colectivo="grupos", grupos=["PDI"])
        with pytest.raises(AgenteNoDisponible):
            await seleccionar(db_session, a, v, "contrato", EmbebedorFalso(), principal=_persona(grupos=("PTGAS",)))

    @pytest.mark.asyncio
    async def test_un_agente_suspendido_no_selecciona(self, db_session):
        from server.app.modules.agentes.indice import AgenteNoDisponible, seleccionar

        a, v = await self._con_indice(db_session, estado="suspendida")
        with pytest.raises(AgenteNoDisponible):
            await seleccionar(db_session, a, v, "contrato", EmbebedorFalso(), principal=_persona())

    @pytest.mark.asyncio
    async def test_un_indice_de_otro_modelo_de_embeddings_lo_dice(self, db_session):
        """Comparar vectores de dos modelos da un orden sin sentido y no da error. Se para."""
        from server.app.modules.agentes.indice import IndiceDeOtroModelo, seleccionar

        a, v = await self._con_indice(db_session)
        otro = EmbebedorFalso()
        otro.model_name = "otro-modelo"
        with pytest.raises(IndiceDeOtroModelo):
            await seleccionar(db_session, a, v, "contrato", otro, principal=_persona())

    @pytest.mark.asyncio
    async def test_sin_indice_devuelve_nada_sin_error(self, db_session):
        from server.app.modules.agentes.indice import seleccionar

        a, v = await _agente(db_session)
        assert await seleccionar(db_session, a, v, "contrato", EmbebedorFalso(), principal=_persona()) == []


class TestHoja:

    def _tabla(self, filas: list[dict]):
        import pandas as pd

        return pd.DataFrame(filas)

    def test_lee_las_columnas_con_o_sin_acentos_y_el_resto_va_a_metadatos(self):
        from server.app.modules.agentes.indice import desde_tabla

        fichas = desde_tabla(self._tabla([{
            "URL": "https://drive.google.com/file/d/a", "Título": "Instrucción", "Resumen": "Trata de contratos.",
            "Vigente": "sí", "Revisión prevista": "2027-01-31", "Materia": "Contratación",
        }]))
        f = fichas[0]
        assert (f.url, f.titulo, f.vigente, f.revision_prevista_en) == (
            "https://drive.google.com/file/d/a", "Instrucción", True, date(2027, 1, 31)
        )
        assert f.metadatos == {"Materia": "Contratación"}

    @pytest.mark.parametrize("valor, esperado", [("no", False), ("No vigente", False), ("", True), ("1", True), ("x", True)])
    def test_la_vigencia_se_entiende_como_la_escribe_una_persona(self, valor, esperado):
        from server.app.modules.agentes.indice import desde_tabla

        fichas = desde_tabla(self._tabla([{"url": "https://a", "titulo": "t", "resumen": "r", "vigente": valor}]))
        assert fichas[0].vigente is esperado

    def test_una_vigencia_que_no_se_entiende_dice_la_fila(self):
        from server.app.modules.agentes.indice import IndiceNoValido, desde_tabla

        with pytest.raises(IndiceNoValido, match="fila 2"):
            desde_tabla(self._tabla([{"url": "https://a", "titulo": "t", "resumen": "r", "vigente": "quizá"}]))

    def test_sin_columna_de_url_no_se_lee(self):
        from server.app.modules.agentes.indice import IndiceNoValido, desde_tabla

        with pytest.raises(IndiceNoValido, match="url"):
            desde_tabla(self._tabla([{"titulo": "t", "resumen": "r"}]))

    def test_la_fecha_en_formato_espanol_tambien_vale(self):
        from server.app.modules.agentes.indice import desde_tabla

        fichas = desde_tabla(self._tabla([{"url": "https://a", "titulo": "t", "resumen": "r", "revision_prevista_en": "31/01/2027"}]))
        assert fichas[0].revision_prevista_en == date(2027, 1, 31)
