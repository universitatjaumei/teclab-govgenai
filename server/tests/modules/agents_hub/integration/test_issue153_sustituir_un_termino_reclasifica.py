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
from sqlmodel.ext.asyncio.session import AsyncSession

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


async def _chatbot(session, organizacion_id) -> uuid.UUID:
    """Un chatbot de esa organización, que es el camino por el que un documento llega a ella.

    `hub_documents` no lleva `organizacion_id`: se llega por `chatbot_id`, y así está escrito en
    `docs/MULTITENENCIA.md`. Sembrarlo es lo que permite comprobar la frontera de verdad.
    """
    from server.app.modules.agents_hub.database.config_models import (
        HubChatbot,
        HubLLMConfig,
        HubProvider,
    )

    await session.merge(HubProvider(id="google", name="Google", provider_type="google_genai"))
    await session.flush()

    llm = HubLLMConfig(
        id=uuid.uuid4(),
        provider="google",
        model_name="gemini-2.5-flash",
        label=f"llm-{uuid.uuid4().hex[:6]}",
    )
    session.add(llm)
    await session.flush()

    chatbot = HubChatbot(
        organizacion_id=organizacion_id,
        llm_config_id=llm.id,
        name=f"Chatbot {uuid.uuid4().hex[:6]}",
        system_prompt="x",
        sources=[],
    )
    session.add(chatbot)
    await session.flush()
    return chatbot.id


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
        chatbot_id = await _chatbot(db_session, organizacion_id)
        doc = await _documento(
            db_session,
            chatbot_id=chatbot_id,
            submateries=["vella", "convenis"],
            submateries_internes=["vella"],
        )
        await db_session.commit()

        tocados = await sustituir_termino(
            db_session,
            axis="submateria",
            codi_antic="vella",
            codi_nou="nova",
            organizacion_id=organizacion_id,
            chatbot_ids=[chatbot_id],
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
            chatbot_ids=[],
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
        chatbot_id = await _chatbot(db_session, organizacion_id)
        doc = await _documento(db_session, chatbot_id=chatbot_id, submateries=["vella"])
        await db_session.commit()

        with pytest.raises(VocabularyCsvError):
            await sustituir_termino(
                db_session,
                axis="submateria",
                codi_antic="vella",
                codi_nou="fantasma",
                organizacion_id=organizacion_id,
                chatbot_ids=[chatbot_id],
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


class TestNoCruzaLaFronteraEntreOrganizaciones:
    """Lo encontró la revisión automática de la PR, y es la regla más dura del proyecto.

    El vocabulario es **por organización** —`hub_vocabulary_terms` lleva `organizacion_id`— pero
    el barrido de documentos no lo era: `reclassify_documents` sólo acotaba por un `chatbot_id`
    opcional, y quien lo llamaba le pasaba `None`. Así que sustituir un término de la organización
    A reescribía los documentos de la B que usaran el mismo código.

    Dos organizaciones pueden usar perfectamente el mismo código: `personal`, `beques`,
    `contractacio` no son de nadie. El camino a la organización de un documento es
    `chatbot_id`, y está escrito en `docs/MULTITENENCIA.md`.
    """

    @pytest.mark.asyncio
    async def test_sustituir_en_una_organizacion_no_toca_los_documentos_de_la_otra(
        self, db_session
    ):
        from server.app.modules.agents_hub.vocabulary.load import sustituir_termino

        propia, ajena = uuid.uuid4(), uuid.uuid4()
        await _sembrar_terminos(db_session, propia, "submateria", "vella", "nova")
        await _sembrar_terminos(db_session, ajena, "submateria", "vella", "nova")

        chatbot_propio = await _chatbot(db_session, propia)
        chatbot_ajeno = await _chatbot(db_session, ajena)
        meu = await _documento(db_session, chatbot_id=chatbot_propio, submateries=["vella"])
        seu = await _documento(db_session, chatbot_id=chatbot_ajeno, submateries=["vella"])
        await db_session.commit()

        tocados = await sustituir_termino(
            db_session,
            axis="submateria",
            codi_antic="vella",
            codi_nou="nova",
            organizacion_id=propia,
            chatbot_ids=[chatbot_propio],
        )
        await db_session.commit()
        await db_session.refresh(meu)
        await db_session.refresh(seu)

        assert meu.submateries == ["nova"], "no se reclasificó el documento propio"
        assert seu.submateries == ["vella"], (
            "se reescribió el documento de otra organización. El vocabulario es por "
            "organización y el barrido no lo era."
        )
        assert tocados == 1, f"contó {tocados} documentos: está barriendo fuera de su ámbito"

    @pytest.mark.asyncio
    async def test_el_ambito_es_una_entrada_de_la_operacion_y_no_se_descubre(self, db_session):
        """Segunda revisión (PR #179): resolver el ámbito dentro obligaba a mirar dos bases.

        `HubChatbot` es configuración y `HubDocument` es operacional; en un despliegue partido no
        comparten base, así que la consulta dentro de la función ataba la operación al modo
        `all`. Ahora entra por parámetro, y quien compone —el CLI— es quien lo resuelve.
        """
        import inspect

        from server.app.modules.agents_hub.vocabulary import load

        firma = inspect.signature(load.sustituir_termino)

        assert "chatbot_ids" in firma.parameters, (
            "el ámbito tiene que ser una entrada de la operación, no algo que averigua"
        )
        # Sin el docstring: ahí `HubChatbot` se nombra para explicar por qué **ya no** se
        # consulta, y contar esa mención sería medir la prosa en vez del código.
        fuente = inspect.getsource(load.sustituir_termino)
        cuerpo = fuente.split('"""')[-1]

        assert "HubChatbot" not in cuerpo, (
            "la función vuelve a consultar un modelo de configuración: eso la ata a un "
            "despliegue donde las dos bases son la misma"
        )

    @pytest.mark.asyncio
    async def test_una_organizacion_sin_chatbots_no_barre_nada_y_no_falla(self, db_session):
        """El caso de borde que un ámbito obligatorio podría convertir en excepción."""
        from server.app.modules.agents_hub.vocabulary.load import sustituir_termino

        organizacion_id = uuid.uuid4()
        await _sembrar_terminos(db_session, organizacion_id, "submateria", "vella", "nova")
        await db_session.commit()

        tocados = await sustituir_termino(
            db_session,
            axis="submateria",
            codi_antic="vella",
            codi_nou="nova",
            organizacion_id=organizacion_id,
            chatbot_ids=[],
        )
        await db_session.commit()

        vieja = await _termino(db_session, organizacion_id, "submateria", "vella")
        assert vieja.vigent is False, "el término tiene que quedar sustituido igualmente"
        assert tocados == 0


class TestElCodigoQueEsPrefijoDeOtroNoCorrompe:
    """El segundo hallazgo de la revisión: el campo escalar se actualizaba con `replace()`.

    La fila entra en el `UPDATE` si **cualquiera** de sus columnas trae el código viejo, y el
    `replace()` se aplicaba después sobre `ambit_principal` fuera cual fuera su valor. Un
    documento con el código viejo en el array y un ámbito principal que **empieza igual** salía
    con el ámbito principal roto — y no da ningún error.
    """

    @pytest.mark.asyncio
    async def test_un_ambito_principal_que_empieza_igual_se_queda_como_estaba(self, db_session):
        from server.app.modules.agents_hub.vocabulary.load import sustituir_termino

        organizacion_id = uuid.uuid4()
        await _sembrar_terminos(
            db_session, organizacion_id, "ambit", "administracio", "gerencia"
        )
        chatbot_id = await _chatbot(db_session, organizacion_id)
        doc = await _documento(
            db_session,
            chatbot_id=chatbot_id,
            ambit_principal="administracio-general",
            ambits_secundaris=["administracio"],
        )
        await db_session.commit()

        await sustituir_termino(
            db_session,
            axis="ambit",
            codi_antic="administracio",
            codi_nou="gerencia",
            organizacion_id=organizacion_id,
            chatbot_ids=[chatbot_id],
        )
        await db_session.commit()
        await db_session.refresh(doc)

        assert doc.ambits_secundaris == ["gerencia"], "el array sí tenía que cambiar"
        assert doc.ambit_principal == "administracio-general", (
            "el ámbito principal se corrompió: `replace()` sustituye subcadenas, y "
            "`administracio` es prefijo de `administracio-general`. Tiene que ser igualdad."
        )

    @pytest.mark.asyncio
    async def test_el_ambito_principal_exacto_si_cambia(self, db_session):
        """El camino bueno, sin el cual el test de arriba se cumpliría no haciendo nada."""
        from server.app.modules.agents_hub.vocabulary.load import sustituir_termino

        organizacion_id = uuid.uuid4()
        await _sembrar_terminos(
            db_session, organizacion_id, "ambit", "administracio", "gerencia"
        )
        chatbot_id = await _chatbot(db_session, organizacion_id)
        doc = await _documento(
            db_session, chatbot_id=chatbot_id, ambit_principal="administracio"
        )
        await db_session.commit()

        await sustituir_termino(
            db_session,
            axis="ambit",
            codi_antic="administracio",
            codi_nou="gerencia",
            organizacion_id=organizacion_id,
            chatbot_ids=[chatbot_id],
        )
        await db_session.commit()
        await db_session.refresh(doc)

        assert doc.ambit_principal == "gerencia"


class TestElAmbitoNoSePuedeFalsear:
    """Tercera revisión (PR #181), y el agujero lo abrí yo arreglando el anterior.

    Para que la operación pudiera correr en un despliegue partido añadí `--chatbot-id`, que
    saltaba la resolución desde la organización. Pero `reclassify_documents` filtra **sólo** por
    los UUID que recibe y `hub_documents` no lleva `organizacion_id`, así que
    `--organizacion-id A --chatbot-id B` marcaba el término de A y reescribía los documentos de
    B: la misma fuga entre organizaciones que la ronda anterior había cerrado, reabierta por la
    puerta de atrás.

    **Y no se puede validar donde hace falta.** Comprobar que esos chatbots son de esa
    organización exige leer configuración, que es justo lo que ese despliegue partido no tiene a
    mano. O sea que la bandera no podía ser a la vez «ejecutable sin configuración» y
    «comprobada contra la configuración».

    Así que se retira. El ámbito se resuelve siempre desde la organización, y el día que exista
    un despliegue partido de verdad esta operación necesita un diseño en la frontera de
    sincronización — no una bandera. La regla del proyecto es no anticipar infraestructura antes
    de que el problema aparezca, y ese despliegue hoy no existe.
    """

    def test_el_cli_no_acepta_un_ambito_escrito_a_mano(self):
        from server.app.modules.agents_hub.vocabulary.load import _construir_parser

        base = [
            "--axis", "submateria",
            "--organizacion-id", str(uuid.uuid4()),
            "--substituir", "vella",
            "--per", "nova",
        ]

        with pytest.raises(SystemExit):
            _construir_parser().parse_args([*base, "--chatbot-id", str(uuid.uuid4())])

    @pytest.mark.asyncio
    async def test_el_cli_solo_toca_los_documentos_de_su_organizacion(self, db_url, monkeypatch):
        """El camino del CLI ejecutado de verdad, con dos organizaciones.

        **Aquí había un test que leía el código fuente** —comprobaba que `_run_sustitucion`
        nombra a `_chatbots_de` y no a la bandera— y la revisión de la PR #182 lo tumbó con
        razón: eso fija la **forma**, no el efecto. Una regresión que llamara al auxiliar y luego
        mandara otro ámbito seguiría pasando en verde.

        Es, otra vez, el error que esta misma tanda de commits estaba arreglando, cometido en el
        test que lo arreglaba. Así que este ejecuta el camino entero y mira **qué documentos
        cambian**.
        """
        from sqlalchemy.ext.asyncio import create_async_engine as _crear_motor

        from server.app.modules.agents_hub.database import connection
        from server.app.modules.agents_hub.vocabulary import load

        motor = _crear_motor(db_url)
        try:
            async with AsyncSession(motor) as siembra:
                propia, ajena = uuid.uuid4(), uuid.uuid4()
                await _sembrar_terminos(siembra, propia, "submateria", "vella", "nova")
                await _sembrar_terminos(siembra, ajena, "submateria", "vella", "nova")
                chatbot_propio = await _chatbot(siembra, propia)
                chatbot_ajeno = await _chatbot(siembra, ajena)
                meu = await _documento(siembra, chatbot_id=chatbot_propio, submateries=["vella"])
                seu = await _documento(siembra, chatbot_id=chatbot_ajeno, submateries=["vella"])
                # Los identificadores **antes** del commit: después, `expire_on_commit` deja el
                # atributo expirado y leerlo dispara IO donde no toca.
                id_meu, id_seu = meu.id, seu.id
                await siembra.commit()

            # El CLI abre su propio motor: se le da el de la base desechable, no el del entorno.
            monkeypatch.setattr(connection, "create_async_engine", lambda: _crear_motor(db_url))
            monkeypatch.setattr(
                connection,
                "create_session_factory",
                lambda m: (lambda: AsyncSession(m)),
            )

            args = load._construir_parser().parse_args(
                [
                    "--axis", "submateria",
                    "--organizacion-id", str(propia),
                    "--substituir", "vella",
                    "--per", "nova",
                ]
            )
            assert await load._run_sustitucion(args) == 0

            async with AsyncSession(motor) as comprobacion:
                from server.app.modules.agents_hub.database.operational_models import HubDocument

                despues_meu = await comprobacion.get(HubDocument, id_meu)
                despues_seu = await comprobacion.get(HubDocument, id_seu)

                assert despues_meu.submateries == ["nova"], (
                    "el CLI resolvió el ámbito pero no reclasificó lo suyo"
                )
                assert despues_seu.submateries == ["vella"], (
                    "el CLI tocó los documentos de otra organización: el ámbito que resuelve no "
                    "es el que acaba usando"
                )
        finally:
            await motor.dispose()
