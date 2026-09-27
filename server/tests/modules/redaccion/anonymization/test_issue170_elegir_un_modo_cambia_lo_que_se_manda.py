"""Issue #170 — elegir un modo de anonimización tiene que cambiar lo que ve el modelo.

**El defecto.** `drafting_runner.construir_grafo` no inyectaba `pii_detector` ni
`faker_generator`, y `_build_init_anonymization_node` devuelve un **no-op declarado** cuando
faltan: `anonymization_context` se quedaba en `None`, y con `None` los hooks `apply_pre_llm` y
`apply_post_llm` devuelven el texto tal cual. Así que una organización podía fijar `replace`
—creyendo cumplir su contrato con el proveedor del LLM— y obtener exactamente lo mismo que con
`off`. **Sin error y sin aviso.**

Medido antes de arreglarlo: **0 de 36** manifiestos de la base de desarrollo llevaban spans.

**Lo que NO es el defecto.** Que la anonimización sea *opt-in* es el diseño, no un fallo: el
modo «depende del contrato con el proveedor LLM y del tipo de datos», y eso lo valora el
administrador de la organización. Lo que no puede ser es que **«apagada por decisión» y
«apagada porque nadie conectó el motor» se vean igual desde fuera**.

**El segundo agujero, que sólo se ve al ejecutar.** `modo_efectivo` se aplicaba únicamente en el
`PATCH` de la pantalla, así que el suelo de la organización se congelaba en el instante en que
alguien tocó el ajuste. Una organización que endurece su política **hoy** no endurecía los
informes creados **ayer**: seguirían ejecutándose con el modo guardado entonces. Una política que
sólo rige para quien pase después por una pantalla concreta no es un suelo.

Estos tests ejecutan el grafo de verdad contra una base desechable, con el modelo simulado, y
miran **el texto que recibe el modelo**. Es la única comprobación que no se puede satisfacer
declarando una intención.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession
from unittest.mock import AsyncMock, MagicMock

from server.app.modules.redaccion.contracts.blocks import AIAssistedTextBlock, UserInputBlock
from server.app.modules.redaccion.contracts.inputs import InputContract
from server.app.modules.redaccion.contracts.template import (
    AIBlockPolicy,
    ExportPolicy,
    ReportTemplateSpec,
    ReviewPolicy,
)
from server.app.modules.redaccion.contracts.ui import ReportUIContract
from server.app.modules.redaccion.database.models import (
    HubReportTemplate,
    HubReportTemplateVersion,
    HubRunManifest,
    HubWorkspace,
    HubWorkspaceBlock,
)

# PII realista y comprobable, con las **tres vías** representadas:
#
# - el DNI y el correo los coge la regex, que es determinista y no necesita modelo;
# - el nombre, dentro de la prosa, lo coge el NER — y es lo que sólo funciona si el modelo de
#   spaCy está instalado.
#
# El nombre se afirma **sin `skipif`** a propósito. El modelo es dependencia por defecto desde la
# #170, así que si falta, esto tiene que ponerse rojo: un test que se salta a sí mismo cuando no
# encuentra el modelo es exactamente la avería que la issue corrige —la capacidad deja de estar y
# nadie se entera—.
DNI = "45678912K"
CORREO = "aitana.beltran@example.org"
NOMBRE = "Aitana Beltran Roig"
TEXTO_CON_PII = (
    "Solicitante: Aitana Beltran Roig, con DNI 45678912K y correo "
    "aitana.beltran@example.org, presenta la documentacion requerida."
)


def _spec() -> ReportTemplateSpec:
    """Un bloque de datos con el texto, y uno de IA que lo usa como contexto."""
    return ReportTemplateSpec(
        sections=[],
        blocks=[
            # El texto con datos personales entra por un bloque de la plantilla: el estado
            # arranca de `spec.blocks`, así que una fila de `hub_workspace_blocks` que la
            # plantilla no declara no llega al grafo — y el contexto saldría vacío.
            UserInputBlock(id="b_datos", title="Datos del solicitante"),
            AIAssistedTextBlock(
                id="b_valoracion",
                title="Valoracion",
                ai_prompt_template_id="valoracion_v1",
                review_policy_id="required",
            )
        ],
        input_contract=InputContract(),
        ui_contract=ReportUIContract(
            wizard_steps=[],
            dropzones=[],
            manual_fields=[],
            block_editor_enabled=False,
            ai_review_panel_enabled=True,
            preview_layout="markdown",
        ),
        ai_block_policy=AIBlockPolicy.ALLOWED,
        review_policy=ReviewPolicy.REQUIRED,
        export_policy=ExportPolicy.DOCX,
    )


def _llm_que_repite_su_contexto() -> MagicMock:
    """Devuelve el contexto recibido, para poder mirar **las dos direcciones** del hook.

    Un modelo que devuelve una constante sólo deja comprobar el `pre`; repitiendo el contexto se
    comprueba además que el `post` deshace la sustitución en lo que lee la persona.
    """
    servicio = MagicMock()
    servicio.model_name = "modelo-de-prueba"

    async def _generar(prompt: str, context: str) -> str:  # noqa: ARG001
        return f"Valoracion basada en: {context}"

    servicio.generate = AsyncMock(side_effect=_generar)
    return servicio


def _contextos_vistos(llm: MagicMock) -> str:
    """Todo lo que se le mandó al modelo, concatenado."""
    return "\n".join(str(llamada.kwargs.get("context", "")) for llamada in llm.generate.await_args_list)


async def _sembrar(
    session,
    *,
    modo_del_informe: str = "replace",
    modo_de_la_organizacion: str | None = None,
) -> uuid.UUID:
    """Workspace con un bloque ya extraído que contiene datos personales."""
    plantilla = HubReportTemplate(
        name=f"Plantilla {uuid.uuid4().hex[:6]}",
        report_profile="GENERIC_REPORT",
        owner_kind="platform",
    )
    session.add(plantilla)
    await session.flush()

    version = HubReportTemplateVersion(
        template_id=plantilla.id,
        version=1,
        spec_json=_spec().model_dump(mode="json"),
        created_by=uuid.uuid4(),
    )
    session.add(version)
    await session.flush()
    plantilla.current_version_id = version.id

    organizacion_id = None
    if modo_de_la_organizacion is not None:
        from server.app.modules.agents_hub.database.config_models import HubOrganizacion

        organizacion_id = uuid.uuid4()
        session.add(
            HubOrganizacion(
                id=organizacion_id,
                name=f"Org {uuid.uuid4().hex[:6]}",
                partner_id=f"partner-{uuid.uuid4().hex[:6]}",
                anonymization_mode=modo_de_la_organizacion,
            )
        )
        await session.flush()

    workspace = HubWorkspace(
        template_version_id=version.id,
        owner_id=uuid.uuid4(),
        status="drafting",
        anonymization_mode=modo_del_informe,
        organizacion_id=organizacion_id,
    )
    session.add(workspace)
    await session.flush()

    # El texto con PII llega como un bloque ya extraído: es lo que `AIAssistDraftNode` mete en el
    # contexto del prompt, y por tanto lo que saldría hacia el proveedor del modelo.
    session.add(
        HubWorkspaceBlock(
            workspace_id=workspace.id,
            block_id="b_datos",
            kind="USER_INPUT",
            # `extracted` y no `ready`: `_build_context` sólo mete en el prompt los bloques
            # validados, y son exactamente `extracted` y `approved`.
            status="extracted",
            content_json={"free_text": TEXTO_CON_PII},
        )
    )
    await session.flush()
    return workspace.id


class TestElegirUnModoCambiaLoQueVeElModelo:
    """El criterio de cierre de la issue, comprobado sobre el texto que sale hacia el modelo."""

    @pytest.mark.asyncio
    async def test_en_replace_el_modelo_no_ve_el_dni_ni_el_correo(self, db_url):
        from server.app.modules.redaccion.services.drafting_runner import ejecutar_borrador

        engine = create_async_engine(db_url)
        try:
            async with AsyncSession(engine) as session:
                workspace_id = await _sembrar(session, modo_del_informe="replace")
                await session.commit()

                llm = _llm_que_repite_su_contexto()
                await ejecutar_borrador(workspace_id, session, llm_service=llm)

                enviado = _contextos_vistos(llm)
                assert enviado, "el modelo no llegó a recibir nada: el test no está mirando nada"
                assert DNI not in enviado, (
                    "el DNI real llegó al modelo con el modo `replace` puesto. Es el defecto de "
                    "la #170: sin detector inyectado el nodo de anonimización es un no-op y "
                    "`replace` no se distingue de `off`."
                )
                assert CORREO not in enviado, "el correo real llegó al modelo con `replace`"
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_en_replace_el_modelo_tampoco_ve_el_nombre(self, db_url):
        """La red de seguridad: un nombre en mitad de la prosa no lo anuncia ninguna cabecera.

        Es la única de las tres vías que depende del modelo de spaCy. Medido sobre 20 nombres de
        morfología valenciana: `es_core_news_md` recupera el 90 % y `es_core_news_sm` el 65 %.
        """
        from server.app.modules.redaccion.services.drafting_runner import ejecutar_borrador

        engine = create_async_engine(db_url)
        try:
            async with AsyncSession(engine) as session:
                workspace_id = await _sembrar(session, modo_del_informe="replace")
                await session.commit()

                llm = _llm_que_repite_su_contexto()
                await ejecutar_borrador(workspace_id, session, llm_service=llm)

                assert NOMBRE not in _contextos_vistos(llm), (
                    "el nombre completo llegó al modelo. O el modelo de spaCy no está instalado "
                    "—es dependencia por defecto desde la #170— o el NER dejó de aplicarse."
                )
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_en_off_el_texto_va_tal_cual(self, db_url):
        """La otra mitad: si `off` y `replace` dieran lo mismo, el test de arriba no probaría nada."""
        from server.app.modules.redaccion.services.drafting_runner import ejecutar_borrador

        engine = create_async_engine(db_url)
        try:
            async with AsyncSession(engine) as session:
                workspace_id = await _sembrar(session, modo_del_informe="off")
                await session.commit()

                llm = _llm_que_repite_su_contexto()
                await ejecutar_borrador(workspace_id, session, llm_service=llm)

                enviado = _contextos_vistos(llm)
                assert DNI in enviado, (
                    "con `off` el texto tiene que ir tal cual: es una decisión de la "
                    "organización, no un fallo. Si aquí tampoco aparece, lo que falla es el "
                    "sembrado y el test de `replace` estaría pasando por vacío."
                )
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_el_informe_final_recupera_los_originales(self, db_url):
        """`replace` es reversible **dentro de la ejecución**: quien lee el informe ve el dato real."""
        from server.app.modules.redaccion.services.drafting_runner import ejecutar_borrador

        engine = create_async_engine(db_url)
        try:
            async with AsyncSession(engine) as session:
                workspace_id = await _sembrar(session, modo_del_informe="replace")
                await session.commit()

                await ejecutar_borrador(
                    workspace_id, session, llm_service=_llm_que_repite_su_contexto()
                )

                filas = (
                    await session.execute(
                        select(HubWorkspaceBlock).where(
                            HubWorkspaceBlock.workspace_id == workspace_id,
                            HubWorkspaceBlock.block_id == "b_valoracion",
                        )
                    )
                ).scalars().all()

                generado = str(filas[0].content_json)
                assert DNI in generado, (
                    "el post-hook no deshizo la sustitución: el informe que lee la persona se "
                    "quedó con el dato sintético, que es un informe equivocado"
                )
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_el_manifiesto_registra_cuantos_datos_se_trataron(self, db_url):
        """Sin spans en el manifiesto no hay evidencia del tratamiento, que es lo que se audita."""
        from server.app.modules.redaccion.services.drafting_runner import ejecutar_borrador

        engine = create_async_engine(db_url)
        try:
            async with AsyncSession(engine) as session:
                workspace_id = await _sembrar(session, modo_del_informe="replace")
                await session.commit()

                await ejecutar_borrador(
                    workspace_id, session, llm_service=_llm_que_repite_su_contexto()
                )

                manifiesto = (
                    await session.execute(
                        select(HubRunManifest).where(
                            HubRunManifest.workspace_id == workspace_id
                        )
                    )
                ).scalars().first()

                # El manifiesto guarda su contrato entero en `payload_json`; no hay columna.
                resumen = (manifiesto.payload_json or {}).get("anonymization_summary")
                assert resumen, "el manifiesto no lleva resumen de anonimización"
                assert resumen.get("total_spans", 0) > 0, (
                    f"el resumen dice que no se detectó nada: {resumen}"
                )
        finally:
            await engine.dispose()


class TestElSueloDeLaOrganizacionRigeAlEjecutar:
    """`modo_efectivo` sólo se aplicaba al guardar desde la pantalla, y eso congela la política."""

    @pytest.mark.asyncio
    async def test_un_informe_guardado_en_off_se_ejecuta_con_el_suelo_de_su_organizacion(
        self, db_url
    ):
        from server.app.modules.redaccion.services.drafting_runner import ejecutar_borrador

        engine = create_async_engine(db_url)
        try:
            async with AsyncSession(engine) as session:
                # El informe quedó en `off` —por ejemplo, antes de que la organización fijara
                # nada— y la organización endurece después.
                workspace_id = await _sembrar(
                    session, modo_del_informe="off", modo_de_la_organizacion="replace"
                )
                await session.commit()

                llm = _llm_que_repite_su_contexto()
                await ejecutar_borrador(workspace_id, session, llm_service=llm)

                enviado = _contextos_vistos(llm)
                assert DNI not in enviado, (
                    "la organización exige `replace` y el informe se ejecutó con el `off` que "
                    "tenía guardado. El suelo se resolvía sólo en el PATCH de la pantalla, así "
                    "que regía para quien volviera a tocarlo y para nadie más."
                )
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_sin_politica_de_organizacion_manda_el_informe(self, db_url):
        """Endurecer al ejecutar no puede convertirse en un suelo implícito del código."""
        from server.app.modules.redaccion.services.drafting_runner import ejecutar_borrador

        engine = create_async_engine(db_url)
        try:
            async with AsyncSession(engine) as session:
                workspace_id = await _sembrar(
                    session, modo_del_informe="off", modo_de_la_organizacion=None
                )
                await session.commit()

                llm = _llm_que_repite_su_contexto()
                await ejecutar_borrador(workspace_id, session, llm_service=llm)

                assert DNI in _contextos_vistos(llm), (
                    "sin política de organización manda el informe, incluso hacia abajo: "
                    "`MODO_POR_DEFECTO` es un valor por omisión, no un mínimo"
                )
        finally:
            await engine.dispose()


class TestElMotorEstaEnchufadoYNoSoloDeclarado:
    """Que el grafo se construya con el detector es lo que distingue esto de una intención."""

    def test_construir_grafo_inyecta_detector_y_generador(self, monkeypatch):
        from server.app.modules.redaccion.graph import core_graph
        from server.app.modules.redaccion.services import drafting_runner

        recogido: dict = {}

        def _capturar(**kwargs):
            recogido.update(kwargs)
            return object()

        monkeypatch.setattr(core_graph, "build_core_graph", _capturar)
        drafting_runner.construir_grafo(MagicMock(), llm_service=MagicMock())

        assert recogido, "no se llegó a construir el grafo: el test no está mirando nada"
        assert recogido.get("pii_detector") is not None, (
            "el grafo se construye sin detector, así que el nodo de anonimización es el no-op"
        )
        assert recogido.get("faker_generator") is not None, (
            "el grafo se construye sin generador de sintéticos"
        )
        assert hasattr(recogido["pii_detector"], "detect_spans")
        assert hasattr(recogido["faker_generator"], "generate")


class TestSeSabeSiLaRedDeSeguridadEstuvoPuesta:
    """La otra mitad del criterio de cierre de la #170.

    Sin modelo de spaCy la anonimización **no se cae**: sigue cogiendo DNI, correos, IBAN y las
    cabeceras de formulario. Lo que deja de coger son los nombres dentro de la prosa. Y el
    resumen quedaría igual de saludable —con sus spans y sus conteos— mientras los nombres pasan.

    Es el mismo patrón que la issue arregla, un nivel más abajo: una capacidad que falta y no se
    distingue de una capacidad que no encontró nada. Así que la ejecución **registra si el NER
    estuvo disponible**, y eso viaja al manifiesto, que es la evidencia que se audita.
    """

    @pytest.mark.asyncio
    async def test_el_manifiesto_dice_si_el_ner_estuvo_disponible(self, db_url):
        from server.app.modules.redaccion.services.drafting_runner import ejecutar_borrador

        engine = create_async_engine(db_url)
        try:
            async with AsyncSession(engine) as session:
                workspace_id = await _sembrar(session, modo_del_informe="replace")
                await session.commit()

                await ejecutar_borrador(
                    workspace_id, session, llm_service=_llm_que_repite_su_contexto()
                )

                manifiesto = (
                    await session.execute(
                        select(HubRunManifest).where(
                            HubRunManifest.workspace_id == workspace_id
                        )
                    )
                ).scalars().first()
                resumen = (manifiesto.payload_json or {}).get("anonymization_summary") or {}

                assert "ner_disponible" in resumen, (
                    "el resumen no dice si el NER estuvo puesto, así que una ejecución sin "
                    "modelo es indistinguible de una con modelo que no encontró nombres"
                )
                assert resumen["ner_disponible"] is True, (
                    "el modelo es dependencia por defecto desde la #170: si aquí sale `False`, "
                    "esta instalación está anonimizando sólo con patrones"
                )
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_en_off_no_se_carga_el_modelo_para_responder_esa_pregunta(self, db_url):
        """`off` no puede pagar los ~305 MB del modelo para informar de algo que no usó.

        Con la anonimización apagada no se escanea nada, así que la pregunta «¿había NER?» no
        tiene respuesta: `None`, que es un dato distinto de `False`.
        """
        from server.app.modules.redaccion.services.drafting_runner import ejecutar_borrador

        engine = create_async_engine(db_url)
        try:
            async with AsyncSession(engine) as session:
                workspace_id = await _sembrar(session, modo_del_informe="off")
                await session.commit()

                await ejecutar_borrador(
                    workspace_id, session, llm_service=_llm_que_repite_su_contexto()
                )

                manifiesto = (
                    await session.execute(
                        select(HubRunManifest).where(
                            HubRunManifest.workspace_id == workspace_id
                        )
                    )
                ).scalars().first()
                resumen = (manifiesto.payload_json or {}).get("anonymization_summary") or {}

                assert resumen.get("ner_disponible") is None, (
                    "con `off` no se escanea nada: decir `True` o `False` sería afirmar algo "
                    "que no se comprobó"
                )
        finally:
            await engine.dispose()

    def test_el_resumen_lo_toma_del_contexto_y_no_lo_inventa(self):
        """Un valor por omisión `True` mentiría justo en la instalación que hay que detectar."""
        from server.app.modules.redaccion.services.anonymization.run_context import (
            AnonymizationMode,
            AnonymizationSummary,
            RunAnonymizationContext,
        )

        degradado = RunAnonymizationContext(
            workspace_id=uuid.uuid4(),
            mode=AnonymizationMode.REPLACE,
            ner_disponible=False,
        )

        assert AnonymizationSummary.from_context(degradado).ner_disponible is False


class TestElContextoExisteAntesDeQueNadieLlameAlModelo:
    """El nodo declaraba en su docstring que va «antes de cualquier nodo que toque LLM». No iba.

    El orden real era `deterministic_extraction → data_transformation → chart_render →
    table_render → data_quality_check → init_anonymization → ai_assist_draft`, y **dos de los
    nodos que llaman al modelo quedaban por delante**: la transformación de datos, que le manda
    la instrucción en lenguaje natural para que genere las operaciones, y el de gráficos, que le
    manda la suya para generar el código. Los dos llaman a `apply_pre_llm` —están preparados—
    con un contexto que en ese punto **todavía es `None`**, así que el hook devolvía el texto tal
    cual y nadie se enteraba.

    Se arregla moviendo el nodo detrás de la extracción, que es de donde sale el texto que
    escanea. Lo que detecta ahí sigue valiendo para los nodos posteriores: el mapa sustituye
    cadenas, no posiciones, así que un dato que venía del documento se sustituye igual cuando
    reaparece en una tabla transformada.
    """

    def _grafo(self):
        from server.app.modules.redaccion.graph.core_graph import build_core_graph

        return build_core_graph(MagicMock(), MagicMock(), MagicMock(), MagicMock()).get_graph()

    #: Los nodos que llaman al modelo. Escrito a mano y protegido por el test de abajo: si
    #: aparece un nodo nuevo, hay que decidir si entra aquí.
    NODOS_QUE_LLAMAN_AL_MODELO = frozenset(
        {"data_transformation", "chart_render", "ai_assist_draft"}
    )

    def test_ninguno_llama_al_modelo_antes_de_que_exista_el_contexto(self):
        grafo = self._grafo()

        salientes: dict[str, set[str]] = {}
        for arista in grafo.edges:
            salientes.setdefault(arista.source, set()).add(arista.target)

        # Todo lo alcanzable sin pasar por el nodo de anonimización.
        alcanzables: set[str] = set()
        pendientes = ["__start__"]
        while pendientes:
            actual = pendientes.pop()
            for siguiente in salientes.get(actual, ()):  # noqa: B007
                if siguiente in alcanzables or siguiente == "init_anonymization":
                    continue
                alcanzables.add(siguiente)
                pendientes.append(siguiente)

        prematuros = self.NODOS_QUE_LLAMAN_AL_MODELO & alcanzables
        assert not prematuros, (
            f"{sorted(prematuros)} pueden llamar al modelo sin haber pasado por "
            "`init_anonymization`, así que su `anonymization_context` es `None` y el hook "
            "`apply_pre_llm` les devuelve el texto sin tocar"
        )

    def test_el_conjunto_de_nodos_es_el_que_este_test_conoce(self):
        """Un nodo nuevo que llame al modelo tiene que pasar por la lista de arriba."""
        grafo = self._grafo()
        nodos = {n for n in grafo.nodes if not n.startswith("__")}

        esperados = {
            "load_template", "validate_inputs", "file_normalization",
            "deterministic_extraction", "data_transformation", "chart_render",
            "table_render", "data_quality_check", "missing_data_question",
            "init_anonymization", "ai_assist_draft", "citation_traceability",
            "review_gate", "apply_user_edits", "final_assembler", "audit_log",
        }
        assert nodos == esperados, (
            "el grafo cambió de nodos: revisa si alguno de los nuevos llama al modelo y, si lo "
            "hace, añádelo a NODOS_QUE_LLAMAN_AL_MODELO"
        )
