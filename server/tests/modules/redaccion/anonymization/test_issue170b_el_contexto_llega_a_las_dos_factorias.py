"""Issue #170, segunda mitad — el contexto tiene que **llegar**, no sólo existir.

**Lo que se hizo mal, y lo encontró la revisión automática de la PR.** Al cablear la
anonimización se movió `init_anonymization` delante de los nodos que llaman al modelo, y se
escribió un guardarraíl que recorre el grafo comprobando que ninguno de ellos es alcanzable sin
pasar por él. El guardarraíl pasa, es cierto lo que dice, **y no mide lo que importa**:
comprueba que el contexto *existe* cuando esos nodos corren, no que lo *usen*.

Y no lo usaban. `DataTransformationNode` construye `ETLService` y llama a `run(...)`, que no tenía
parámetro para el contexto, así que `ETLFactory.generate_operations_from_nl` lo recibía siempre en
`None` y su `apply_pre_llm` devolvía el texto sin tocar. `ChartHandler.execute` recibe el estado
entero y tampoco se lo pasaba a `ChartFactory`.

O sea: las dos factorías tienen los *hooks* puestos desde la fase 13, el orden del grafo ya es
correcto, y el prompt salía igualmente con los datos personales dentro.

**Es la misma forma de fallo que la issue arregla, cometida al arreglarla**, y por eso estos tests
no miran el grafo ni los argumentos: miran **los mensajes que recibe el modelo**. Un test que
comprueba que se pasa un parámetro se puede satisfacer pasando `None`.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from server.app.modules.redaccion.contracts.block_io import BlockReference
from server.app.modules.redaccion.contracts.blocks import (
    ChartBlock,
    ChartBlockConfig,
    DataTransformBlock,
    DataTransformBlockConfig,
)
from server.app.modules.redaccion.contracts.inputs import InputContract
from server.app.modules.redaccion.contracts.runtime import BlockState, WorkspaceState
from server.app.modules.redaccion.contracts.template import (
    AIBlockPolicy,
    ExportPolicy,
    ReportTemplateSpec,
    ReviewPolicy,
)
from server.app.modules.redaccion.contracts.ui import ReportUIContract
from server.app.modules.redaccion.services.anonymization.run_context import (
    AnonymizationMode,
    PiiSpan,
    RunAnonymizationContext,
)

AHORA = datetime(2026, 9, 27, tzinfo=timezone.utc)

#: El dato real y su sustituto. La instrucción en lenguaje natural la escribe una persona, así
#: que es un sitio donde el PII entra a mano: «agrupa las dietas de …».
ORIGINAL = "Aitana Beltran Roig"
SINTETICO = "Marta Lopez Diaz"


def _contexto() -> RunAnonymizationContext:
    return RunAnonymizationContext(
        workspace_id=uuid.uuid4(),
        mode=AnonymizationMode.REPLACE,
        spans=[PiiSpan(type="PERSON_NAME", original=ORIGINAL, synthetic=SINTETICO)],
        forward_map={ORIGINAL: SINTETICO},
        reverse_map={SINTETICO: ORIGINAL},
    )


def _llm_que_registra() -> MagicMock:
    """Un modelo que apunta todo lo que le mandan y devuelve un plan válido."""
    servicio = MagicMock()
    servicio.model_name = "modelo-de-prueba"
    respuesta = MagicMock()
    respuesta.content = '{"mode": "operations", "operations": []}'
    servicio.ainvoke = AsyncMock(return_value=respuesta)
    return servicio


def _lo_que_vio(llm: MagicMock) -> str:
    """Todo el texto que ha pasado por el modelo, sea cual sea la forma del mensaje."""
    trozos: list[str] = []
    for llamada in llm.ainvoke.await_args_list:
        trozos.append(str(llamada.args))
        trozos.append(str(llamada.kwargs))
    return "\n".join(trozos)


def _bloque(block_id: str, kind: str, status: str, content: Any = None) -> BlockState:
    return BlockState(
        block_id=block_id,
        kind=kind,
        status=status,
        content=content,
        last_updated_by="system",
        updated_at=AHORA,
    )


def _estado(bloques: list, blocks: dict) -> WorkspaceState:
    spec = ReportTemplateSpec(
        sections=[],
        blocks=bloques,
        input_contract=InputContract(),
        ui_contract=ReportUIContract(
            wizard_steps=[], dropzones=[], manual_fields=[],
            block_editor_enabled=False, ai_review_panel_enabled=True,
            preview_layout="markdown",
        ),
        ai_block_policy=AIBlockPolicy.ALLOWED,
        review_policy=ReviewPolicy.REQUIRED,
        export_policy=ExportPolicy.DOCX,
    )
    return WorkspaceState(
        workspace_id=uuid.uuid4(),
        template_version_id=uuid.uuid4(),
        report_profile="GENERIC_REPORT",
        inputs={},
        blocks=blocks,
        status="drafting",
        warnings=[],
        spec=spec,
        anonymization_context=_contexto(),
    )


class TestLaTransformacionDeDatos:
    """`DATA_TRANSFORM` en modo IA manda al modelo la instrucción que escribió una persona."""

    @pytest.mark.asyncio
    async def test_el_modelo_no_ve_el_nombre_real_en_la_instruccion(self):
        from server.app.modules.redaccion.graph.nodes.data_transformation import (
            DataTransformationNode,
        )

        contrato = DataTransformBlock(
            id="b_transform",
            title="Transformacio",
            config=DataTransformBlockConfig(
                mode="ai",
                source_block_ref=BlockReference(block_id="b_datos"),
                nl_instruction=f"Agrupa per mes les dietes de {ORIGINAL} i suma l'import",
            ),
        )
        datos = _bloque(
            "b_datos",
            "DETERMINISTIC_DATA",
            "extracted",
            {"rows": [{"mes": "gener", "import": 100}]},
        )
        estado = _estado(
            [contrato],
            {"b_datos": datos, "b_transform": _bloque("b_transform", "DATA_TRANSFORM", "draft")},
        )

        llm = _llm_que_registra()
        await DataTransformationNode(llm_service=llm, model_name="modelo-de-prueba")(estado)

        visto = _lo_que_vio(llm)
        assert visto, "el modelo no llegó a recibir nada: el test no está mirando nada"
        assert ORIGINAL not in visto, (
            "el nombre real llegó al modelo en la instrucción de transformación. El hook "
            "`apply_pre_llm` está puesto en `ETLFactory` desde la fase 13, pero nadie le pasaba "
            "el contexto: `ETLService.run` no tenía por dónde recibirlo."
        )
        assert SINTETICO in visto, "no se sustituyó: el hook no llegó a operar"


class TestElNodoDeGraficos:
    """`CHART` en modo IA manda al modelo la descripción del gráfico que escribió una persona."""

    @pytest.mark.asyncio
    async def test_el_modelo_no_ve_el_nombre_real_en_la_descripcion(self):
        from server.app.modules.redaccion.blocks.handlers import ChartHandler

        contrato = ChartBlock(
            id="b_chart",
            title="Grafic",
            data_block_ref="b_datos",
            config=ChartBlockConfig(
                mode="ai",
                nl_prompt=f"Barres amb l'evolucio de les dietes de {ORIGINAL}",
            ),
        )
        datos = _bloque(
            "b_datos",
            "DETERMINISTIC_DATA",
            "extracted",
            {"rows": [{"mes": "gener", "import": 100}]},
        )
        estado = _estado(
            [contrato],
            {"b_datos": datos, "b_chart": _bloque("b_chart", "CHART", "draft")},
        )

        llm = _llm_que_registra()
        manejador = ChartHandler(llm=llm, model_name="modelo-de-prueba")
        try:
            await manejador.execute(contrato, estado)
        except Exception:
            # Lo que se mide es el prompt, no que el gráfico llegue a dibujarse: sin sandbox
            # el dibujo falla después, y ese fallo no dice nada sobre lo que vio el modelo.
            pass

        visto = _lo_que_vio(llm)
        assert visto, "el modelo no llegó a recibir nada: el test no está mirando nada"
        assert ORIGINAL not in visto, (
            "el nombre real llegó al modelo en la descripción del gráfico. `ChartHandler` recibe "
            "el estado entero —contexto incluido— y no se lo pasaba a `ChartFactory`."
        )
        assert SINTETICO in visto, "no se sustituyó: el hook no llegó a operar"


class TestElGuardarrailNuevoMideElTextoYNoElGrafo:
    """La lección que deja esto escrita, para que el próximo no repita la medición floja."""

    def test_un_contexto_vacio_no_sustituye_nada(self):
        """Comprueba el instrumento: si el contexto no llegara, el texto saldría igual.

        Sin esto, los dos tests de arriba podrían estar pasando porque el nombre nunca estuvo
        en el prompt, en vez de porque se sustituyó.
        """
        from server.app.modules.redaccion.services.anonymization.hooks import apply_pre_llm

        texto = f"Dietes de {ORIGINAL}"

        assert apply_pre_llm(texto, None) == texto
        assert ORIGINAL not in apply_pre_llm(texto, _contexto())


class TestNoSePagaElModeloSiNoHayNadaQueEscanear:
    """Tercer hallazgo de la revisión, y es coherencia con lo que el cambio prometió.

    `spacy_available` **fuerza la carga** del modelo, ~305 MB medidos. Se preguntaba antes de
    mirar si había texto, así que una ejecución en `replace` sin nada extraído pagaba el modelo
    entero para informar de una capa que no llegó a usar. La carga perezosa que este cambio
    introdujo quedaba anulada justo en el caso en que más se nota.

    Y hay una segunda cosa, de honradez del dato: si no se escaneó nada, la respuesta correcta a
    «¿estuvo el NER?» es **`None`**, no `False`. `False` diría que se comprobó y no estaba.
    """

    @pytest.mark.asyncio
    async def test_sin_texto_no_se_toca_el_detector_y_no_se_afirma_nada(self):
        from server.app.modules.redaccion.graph.nodes.init_anonymization import (
            InitAnonymizationNode,
        )

        class _DetectorQueSeQueja:
            """Si alguien le pregunta por spaCy, revienta: así el test lo nota."""

            @property
            def spacy_available(self) -> bool:  # pragma: no cover - debe no llamarse
                raise AssertionError(
                    "se preguntó por el modelo sin haber texto que escanear: eso lo carga"
                )

            def detect_spans(self, texto: str) -> list:
                return []

        estado = WorkspaceState(
            workspace_id=uuid.uuid4(),
            template_version_id=uuid.uuid4(),
            report_profile="GENERIC_REPORT",
            inputs={},
            blocks={},
            status="drafting",
            warnings=[],
            anonymization_mode="replace",
        )

        salida = await InitAnonymizationNode(_DetectorQueSeQueja(), MagicMock())(estado)

        assert salida["anonymization_context"].ner_disponible is None, (
            "sin texto no se escaneó nada, así que no se puede afirmar si el NER estaba"
        )

    @pytest.mark.asyncio
    async def test_con_texto_si_se_pregunta(self):
        """El camino bueno, sin el cual el de arriba se cumpliría no preguntando nunca."""
        from server.app.modules.redaccion.graph.nodes.init_anonymization import (
            InitAnonymizationNode,
        )

        detector = MagicMock()
        detector.spacy_available = True
        detector.detect_spans = MagicMock(return_value=[])

        estado = WorkspaceState(
            workspace_id=uuid.uuid4(),
            template_version_id=uuid.uuid4(),
            report_profile="GENERIC_REPORT",
            inputs={},
            blocks={
                "b": BlockState(
                    block_id="b", kind="USER_INPUT", status="extracted",
                    content={"free_text": "Hi ha text ací"},
                    last_updated_by="system", updated_at=AHORA,
                )
            },
            status="drafting",
            warnings=[],
            anonymization_mode="replace",
        )

        salida = await InitAnonymizationNode(detector, MagicMock())(estado)

        assert salida["anonymization_context"].ner_disponible is True


class TestElEscaneoMiraTambienLasInstrucciones:
    """Segunda revisión (PR #179), y es el hueco que mis propios tests no veían.

    Los de arriba **inyectan el span a mano**, así que comprueban que el contexto viaja pero no
    que llegue a existir. Y no llegaba: `_gather_text` recoge `artifacts_normalized` y el
    contenido de los bloques, y la instrucción en lenguaje natural de un `DATA_TRANSFORM` o un
    `CHART` **no está en ninguno de los dos** — vive en `spec.blocks[*].config`.

    O sea que un nombre que aparezca sólo ahí no genera ningún span, el mapa sale vacío, y el
    `apply_pre_llm` que acabo de cablear no tiene nada que sustituir. El cableado era correcto y
    el escaneo llegaba corto: dos mitades, y sólo arreglé una.

    Un test que construye el contexto a mano no puede encontrar esto. Éste deja que lo construya
    el nodo, con el detector de verdad.
    """

    def _estado_con_instruccion(self, texto: str) -> WorkspaceState:
        contrato = DataTransformBlock(
            id="b_transform",
            title="Transformacio",
            config=DataTransformBlockConfig(
                mode="ai",
                source_block_ref=BlockReference(block_id="b_datos"),
                nl_instruction=texto,
            ),
        )
        spec = ReportTemplateSpec(
            sections=[],
            blocks=[contrato],
            input_contract=InputContract(),
            ui_contract=ReportUIContract(
                wizard_steps=[], dropzones=[], manual_fields=[],
                block_editor_enabled=False, ai_review_panel_enabled=True,
                preview_layout="markdown",
            ),
            ai_block_policy=AIBlockPolicy.ALLOWED,
            review_policy=ReviewPolicy.REQUIRED,
            export_policy=ExportPolicy.DOCX,
        )
        return WorkspaceState(
            workspace_id=uuid.uuid4(),
            template_version_id=uuid.uuid4(),
            report_profile="GENERIC_REPORT",
            inputs={},
            blocks={"b_transform": _bloque("b_transform", "DATA_TRANSFORM", "draft")},
            status="drafting",
            warnings=[],
            spec=spec,
            anonymization_mode="replace",
        )

    @pytest.mark.asyncio
    async def test_un_dni_que_solo_esta_en_la_instruccion_se_detecta(self):
        """El DNI porque lo coge la regex: así el test no depende del modelo de spaCy."""
        from server.app.modules.redaccion.graph.nodes.init_anonymization import (
            InitAnonymizationNode,
        )
        from server.app.modules.redaccion.services.anonymization.faker_generator import (
            FakerGenerator,
        )
        from server.app.modules.redaccion.services.anonymization.pii_detector import PiiDetector

        estado = self._estado_con_instruccion(
            "Agrupa les dietes de la persona amb DNI 45678912K per mes"
        )

        salida = await InitAnonymizationNode(PiiDetector(), FakerGenerator())(estado)
        contexto = salida["anonymization_context"]

        assert "45678912K" in contexto.forward_map, (
            "el DNI está sólo en la instrucción del bloque y no se escaneó, así que el mapa sale "
            "vacío y el hook no tiene nada que sustituir: el prompt sale con el dato dentro"
        )

    @pytest.mark.asyncio
    async def test_de_punta_a_punta_sin_inyectar_nada_a_mano(self):
        """Lo que de verdad importa: escanear y sustituir, con el nodo construyendo su contexto."""
        from server.app.modules.redaccion.graph.nodes.data_transformation import (
            DataTransformationNode,
        )
        from server.app.modules.redaccion.graph.nodes.init_anonymization import (
            InitAnonymizationNode,
        )
        from server.app.modules.redaccion.services.anonymization.faker_generator import (
            FakerGenerator,
        )
        from server.app.modules.redaccion.services.anonymization.pii_detector import PiiDetector

        estado = self._estado_con_instruccion(
            "Agrupa les dietes de la persona amb DNI 45678912K per mes"
        )
        estado.blocks["b_datos"] = _bloque(
            "b_datos", "DETERMINISTIC_DATA", "extracted", {"rows": [{"mes": "gener"}]}
        )

        salida = await InitAnonymizationNode(PiiDetector(), FakerGenerator())(estado)
        estado.anonymization_context = salida["anonymization_context"]

        llm = _llm_que_registra()
        await DataTransformationNode(llm_service=llm, model_name="modelo-de-prueba")(estado)

        visto = _lo_que_vio(llm)
        assert visto, "el modelo no recibió nada: el test no está mirando nada"
        assert "45678912K" not in visto, (
            "el DNI llegó al modelo. El cableado del contexto estaba bien y el escaneo llegaba "
            "corto: son dos mitades y hay que comprobar las dos juntas."
        )
