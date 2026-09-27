"""Issue #153 — sustituir un término del vocabulario tiene que reclasificar los documentos.

**Lo que se midió.** `corpus_reclassifier.reclassify_documents` no tiene ningún importador vivo:
sólo lo llaman sus tests. Y al tirar del hilo resultó que **la otra mitad tampoco**:
`vocabulary/load.py:supersede_term` también está sin llamar desde código de producción.

Así que la operación entera —renombrar o fusionar un término— **no existía como operación**.
`docs/CARGA_VOCABULARIO.md` dice al operador «usa `supersede_term`», y no hay manera de usarlo:
el CLI del vocabulario sólo carga CSV, y no hay router. Para renombrar un término había que
abrir un intérprete y llamar a dos funciones en el orden correcto, acordándose de la segunda.

**Y acordarse de la segunda es justo lo que no se puede dejar al operador.** Si sólo corre
`supersede_term`, el término queda marcado como sustituido y los documentos siguen clasificados
con el código viejo: la búsqueda por el nuevo no los encuentra y la del viejo apunta a un término
retirado. El sistema no da ningún error — simplemente deja de recuperar lo que debería.

Esto choca de frente con la regla dura del proyecto sobre vocabulario revisable: *«reclasificar
debe costar un `UPDATE` sobre `hub_documents`»*. El `UPDATE` estaba escrito; lo que faltaba era
que alguien lo ejecutara.

**Lo que se hace.** Una función que hace las dos mitades, `sustituir_termino`, y el CLI que la
expone. No se cablea `reclassify_documents` por su cuenta: separadas vuelven a poder correr a
medias, que es exactamente el defecto.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from server.app.modules.agents_hub.database.operational_models import HubDocument


async def _documento(session, **kwargs):
    defaults = dict(
        chatbot_id=kwargs.pop("chatbot_id", uuid.uuid4()),
        title="Reglament de prova",
        canonical_url=f"https://www.uji.es/{uuid.uuid4().hex[:8]}",
        markdown_content="# Reglament",
        content_hash=uuid.uuid4().hex + uuid.uuid4().hex,
        language="ca",
        source_kind="publicacio",
    )
    defaults.update(kwargs)
    doc = HubDocument(**defaults)
    session.add(doc)
    await session.flush()
    return doc


async def _sembrar_terminos(session, organizacion_id, axis: str, *codis: str) -> None:
    from server.app.modules.agents_hub.database.config_models import HubOrganizacion
    from server.app.modules.agents_hub.services.vocabulary_service import VocabularyTermDTO
    from server.app.modules.agents_hub.vocabulary.load import SqlAlchemyVocabularyStore

    if await session.get(HubOrganizacion, organizacion_id) is None:
        session.add(
            HubOrganizacion(
                id=organizacion_id,
                name=f"Org {uuid.uuid4().hex[:6]}",
                partner_id=f"partner-{uuid.uuid4().hex[:6]}",
            )
        )
        await session.flush()

    store = SqlAlchemyVocabularyStore(session)
    for orden, codi in enumerate(codis):
        await store.create(
            VocabularyTermDTO(axis=axis, codi=codi, nom_primari=codi.title(), ordre=orden),
            organizacion_id,
        )
    await session.flush()


async def _termino(session, organizacion_id, axis: str, codi: str):
    from server.app.modules.agents_hub.database.config_models import HubVocabularyTerm

    fila = (
        await session.execute(
            select(HubVocabularyTerm).where(
                HubVocabularyTerm.organizacion_id == organizacion_id,
                HubVocabularyTerm.axis == axis,
                HubVocabularyTerm.codi == codi,
            )
        )
    ).scalars().first()
    return fila


class TestLasDosMitadesVanJuntas:

    @pytest.mark.asyncio
    async def test_sustituir_marca_el_termino_y_barre_los_documentos(self, db_session):
        from server.app.modules.agents_hub.vocabulary.load import sustituir_termino

        organizacion_id = uuid.uuid4()
        await _sembrar_terminos(db_session, organizacion_id, "submateria", "vella", "nova")
        doc = await _documento(
            db_session, submateries=["vella", "convenis"], submateries_internes=["vella"]
        )
        await db_session.commit()

        tocados = await sustituir_termino(
            db_session,
            axis="submateria",
            codi_antic="vella",
            codi_nou="nova",
            organizacion_id=organizacion_id,
        )
        await db_session.commit()
        await db_session.refresh(doc)

        vieja = await _termino(db_session, organizacion_id, "submateria", "vella")
        assert vieja.vigent is False, "la mitad del vocabulario no corrió"
        assert vieja.substituit_per_codi == "nova"

        assert doc.submateries == ["nova", "convenis"], (
            "el término quedó marcado como sustituido y los documentos siguen con el código "
            "viejo: la búsqueda por el nuevo no los encuentra y nadie ve ningún error"
        )
        assert doc.submateries_internes == ["nova"]
        assert tocados == 1

    @pytest.mark.asyncio
    async def test_un_eje_sin_columnas_se_sustituye_y_no_barre_nada(self, db_session):
        """`rang` y `colectiu` viven en `doc_metadata` y no gobiernan la recuperación.

        Que no haya nada que barrer no puede impedir renombrar el término: si esto levantara,
        media operación quedaría inejecutable para dos de los cuatro ejes.
        """
        from server.app.modules.agents_hub.vocabulary.load import sustituir_termino

        organizacion_id = uuid.uuid4()
        await _sembrar_terminos(db_session, organizacion_id, "rang", "llei", "llei-organica")
        await db_session.commit()

        tocados = await sustituir_termino(
            db_session,
            axis="rang",
            codi_antic="llei",
            codi_nou="llei-organica",
            organizacion_id=organizacion_id,
        )
        await db_session.commit()

        vieja = await _termino(db_session, organizacion_id, "rang", "llei")
        assert vieja.vigent is False
        assert tocados == 0

    @pytest.mark.asyncio
    async def test_si_el_sustituto_no_existe_no_se_toca_ningun_documento(self, db_session):
        """El orden importa: primero se valida el vocabulario, después se barre.

        Al revés, un sustituto mal escrito dejaría los documentos apuntando a un código que no
        existe en ningún eje — y eso no lo detecta nadie hasta que una consulta no devuelve nada.
        """
        from server.app.modules.agents_hub.vocabulary.load import (
            VocabularyCsvError,
            sustituir_termino,
        )

        organizacion_id = uuid.uuid4()
        await _sembrar_terminos(db_session, organizacion_id, "submateria", "vella")
        doc = await _documento(db_session, submateries=["vella"])
        await db_session.commit()

        with pytest.raises(VocabularyCsvError):
            await sustituir_termino(
                db_session,
                axis="submateria",
                codi_antic="vella",
                codi_nou="fantasma",
                organizacion_id=organizacion_id,
            )

        await db_session.rollback()
        await db_session.refresh(doc)
        assert doc.submateries == ["vella"]


class TestElOperadorPuedeEjecutarlo:
    """Una función que nadie puede invocar desde fuera es la misma avería con otra forma."""

    def test_el_cli_acepta_la_sustitucion_sin_pedir_csv(self):
        from server.app.modules.agents_hub.vocabulary.load import _construir_parser

        args = _construir_parser().parse_args(
            [
                "--axis", "submateria",
                "--organizacion-id", str(uuid.uuid4()),
                "--substituir", "vella",
                "--per", "nova",
            ]
        )

        assert args.substituir == "vella"
        assert args.per == "nova"
        assert args.csv is None, "`--csv` seguía siendo obligatorio: sustituir era inalcanzable"

    def test_el_cli_exige_csv_o_sustitucion_pero_no_las_dos(self):
        # La comprobación no la puede hacer argparse —`--substituir` arrastra a `--per`— así
        # que vive en `_validar_modo`, que es lo que `main` llama tras parsear.
        from server.app.modules.agents_hub.vocabulary.load import (
            _construir_parser,
            _validar_modo,
        )

        parser = _construir_parser()
        base = ["--axis", "submateria", "--organizacion-id", str(uuid.uuid4())]

        with pytest.raises(SystemExit):  # ni una cosa ni la otra
            _validar_modo(parser, parser.parse_args(base))

        with pytest.raises(SystemExit):  # falta `--per`
            _validar_modo(parser, parser.parse_args([*base, "--substituir", "vella"]))

        with pytest.raises(SystemExit):  # las dos a la vez
            _validar_modo(
                parser,
                parser.parse_args(
                    [*base, "--csv", "x.csv", "--substituir", "vella", "--per", "nova"]
                ),
            )

    def test_cargar_un_csv_sigue_funcionando_igual(self):
        """Añadir un modo no puede romper el que ya se usa: es el de la guía de carga."""
        from server.app.modules.agents_hub.vocabulary.load import _construir_parser

        args = _construir_parser().parse_args(
            [
                "--axis", "ambit",
                "--csv", "ambits.csv",
                "--organizacion-id", str(uuid.uuid4()),
                "--dry-run",
            ]
        )

        assert args.csv == "ambits.csv"
        assert args.dry_run is True
        assert args.substituir is None
