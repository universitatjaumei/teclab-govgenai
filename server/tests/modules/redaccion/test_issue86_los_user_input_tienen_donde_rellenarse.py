"""Issue #86 — los bloques `USER_INPUT` no tenían dónde rellenarse, y su valor no salía.

La plantilla del doctorado declara cuatro bloques `USER_INPUT` y su `ui_contract` declara
`manual_fields: []`: la sección «Datos aportados por la coordinación» salía vacía y nadie podía
hacer nada al respecto. Se decidió el 2026-09-21 documentarlo en vez de arreglarlo, **porque
sembrar sólo los `manual_fields` habría sido peor**: un formulario que se rellena y cuya
respuesta no sale en el informe parece que funcionó.

Así que el arreglo son **tres** piezas, y las tres tienen test aquí:

1. **Los campos se derivan al servir**, no se confían al valor guardado. Es el mismo argumento
   que INF.1 usó para `required` de las zonas de arrastre: las versiones de plantilla son
   inmutables y la del doctorado ya está sembrada, así que un arreglo que dependa de volver a
   sembrar no arregla la plantilla que tiene el problema. `spec_builder` deriva `manual_fields`
   de los **slots de entrada** y aquí lo que hay que rellenar son **bloques**: son dos cosas, y
   confundirlas es lo que dejó el contrato permitiendo describir un informe que no se puede
   completar.

2. **El valor se guarda**, y en su propia columna. En `inputs_json` no, porque esa columna es de
   ficheros: `uploaded_slots` lista sus claves como ficheros subidos y el runner valida cada
   entrada como `InputArtifact`. Un texto ahí saldría en la pantalla como un fichero subido y en
   el registro como una entrada corrupta.

3. **El valor sale en el informe.** Un nodo del grafo lleva lo que se escribió al `content` del
   bloque, que es lo que el ensamblador lee. Sin esto las otras dos piezas son el formulario
   engañoso que la decisión del 21-09 quería evitar.
"""

from __future__ import annotations

import uuid

import pytest

from server.app.modules.redaccion.contracts.blocks import (
    AIAssistedTextBlock,
    UserInputBlock,
)
from server.app.modules.redaccion.contracts.inputs import InputContract, InputSlot
from server.app.modules.redaccion.contracts.template import (
    AIBlockPolicy,
    ExportPolicy,
    ReportTemplateSpec,
    ReviewPolicy,
    SectionContract,
)
from server.app.modules.redaccion.contracts.ui import (
    ReportUIContract,
    UIFieldDescriptor,
)


def _spec(*, manual_fields=None, bloques=None) -> ReportTemplateSpec:
    return ReportTemplateSpec(
        sections=[SectionContract(id="s1", title="Única", order=1, block_ids=[])],
        blocks=bloques
        if bloques is not None
        else [
            UserInputBlock(
                id="campo_movilidad",
                title="Porcentaje de estudiantado con movilidad",
                field_type="number",
                order=1,
                required=True,
            ),
            UserInputBlock(id="campo_quejas", title="Quejas y sugerencias", order=2),
        ],
        input_contract=InputContract(
            required_slots=[],
            optional_slots=[
                InputSlot(slot_id="datos", kind="markdown", label={"es": "Datos"})
            ],
        ),
        ui_contract=ReportUIContract(
            wizard_steps=[],
            dropzones=[],
            manual_fields=manual_fields if manual_fields is not None else [],
            block_editor_enabled=True,
            ai_review_panel_enabled=True,
            preview_layout="markdown",
        ),
        ai_block_policy=AIBlockPolicy.ALLOWED,
        review_policy=ReviewPolicy.NONE,
        export_policy=ExportPolicy.DOCX,
    )


class TestLosCamposSeDerivanDeLosBloques:
    """Pieza 1 — al servir, no al guardar: la plantilla con el problema ya está sembrada."""

    def test_un_bloque_user_input_produce_su_campo(self):
        from server.app.modules.redaccion.services.campos_manuales import (
            con_los_campos_de_los_bloques,
        )

        contrato = con_los_campos_de_los_bloques(_spec())

        assert [c.slot_id for c in contrato.manual_fields] == [
            "campo_movilidad",
            "campo_quejas",
        ], "los cuatro USER_INPUT del doctorado siguen sin tener dónde rellenarse"

    def test_el_campo_conserva_tipo_y_obligatoriedad_del_bloque(self):
        """El servidor manda: la pantalla no deduce ni el tipo ni si es obligatorio."""
        from server.app.modules.redaccion.services.campos_manuales import (
            con_los_campos_de_los_bloques,
        )

        campos = {c.slot_id: c for c in con_los_campos_de_los_bloques(_spec()).manual_fields}

        assert campos["campo_movilidad"].field_type == "number"
        assert campos["campo_movilidad"].required is True
        assert campos["campo_quejas"].required is False

    def test_la_etiqueta_es_el_titulo_del_bloque_en_una_sola_lengua(self):
        """El bloque trae **una** cadena; inventar tres sería fingir que está traducida.

        Con una sola clave, `getLocalizedLabel` cae a ella para cualquier idioma, que es lo
        que hace hoy con las etiquetas que sólo traen castellano.
        """
        from server.app.modules.redaccion.services.campos_manuales import (
            con_los_campos_de_los_bloques,
        )

        campos = {c.slot_id: c for c in con_los_campos_de_los_bloques(_spec()).manual_fields}

        assert campos["campo_quejas"].label == {"es": "Quejas y sugerencias"}

    def test_no_duplica_un_campo_que_la_plantilla_ya_declaraba(self):
        """Una plantilla nueva puede declararlo; derivar no puede pisarlo ni repetirlo."""
        from server.app.modules.redaccion.services.campos_manuales import (
            con_los_campos_de_los_bloques,
        )

        declarado = UIFieldDescriptor(
            slot_id="campo_quejas",
            label={"ca": "Queixes"},
            field_type="text",
            required=True,
        )
        contrato = con_los_campos_de_los_bloques(_spec(manual_fields=[declarado]))

        cuantos = [c.slot_id for c in contrato.manual_fields].count("campo_quejas")
        assert cuantos == 1
        assert contrato.manual_fields[0].label == {"ca": "Queixes"}

    def test_una_plantilla_sin_user_input_no_cambia(self):
        """Sin esto, lo de arriba se cumpliría inventando campos en todas las plantillas."""
        from server.app.modules.redaccion.services.campos_manuales import (
            con_los_campos_de_los_bloques,
        )

        spec = _spec(
            bloques=[
                AIAssistedTextBlock(
                    id="b1",
                    title="Valoración",
                    ai_prompt_template_id="p1",
                    review_policy_id="r1",
                )
            ]
        )

        assert con_los_campos_de_los_bloques(spec).manual_fields == []


class TestElValorLlegaAlInforme:
    """Pieza 3 — sin esto, las otras dos son el formulario engañoso que se quiso evitar."""

    def _estado(self, *, valores):
        from server.app.modules.redaccion.contracts.runtime import (
            BlockState,
            WorkspaceState,
        )

        spec = _spec()
        ahora = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        return WorkspaceState(
            workspace_id=uuid.uuid4(),
            template_version_id=uuid.uuid4(),
            report_profile="GENERIC_REPORT",
            inputs={},
            blocks={
                b.id: BlockState(
                    block_id=b.id,
                    kind=b.kind,
                    status="draft",
                    last_updated_by="system",
                    updated_at=ahora,
                )
                for b in spec.blocks
            },
            status="drafting",
            warnings=[],
            spec=spec,
            manual_inputs=valores,
        )

    @pytest.mark.asyncio
    async def test_lo_escrito_acaba_en_el_contenido_del_bloque(self):
        from server.app.modules.redaccion.graph.nodes.user_input_fill import (
            UserInputFillNode,
        )

        estado = self._estado(valores={"campo_quejas": "Ninguna en el curso"})
        cambios = await UserInputFillNode()(estado)

        bloque = cambios["blocks"]["campo_quejas"]
        assert bloque.content == {"text": "Ninguna en el curso"}
        assert bloque.status == "extracted"
        assert bloque.last_updated_by == "user"

    @pytest.mark.asyncio
    async def test_el_ensamblador_lo_imprime(self):
        """Medir el efecto, no la forma: lo que importa es que salga en el documento."""
        from server.app.modules.redaccion.graph.nodes.final_assembler import (
            contenido_a_markdown,
        )
        from server.app.modules.redaccion.graph.nodes.user_input_fill import (
            UserInputFillNode,
        )

        estado = self._estado(valores={"campo_quejas": "Ninguna en el curso"})
        cambios = await UserInputFillNode()(estado)

        assert (
            contenido_a_markdown(cambios["blocks"]["campo_quejas"].content)
            == "Ninguna en el curso"
        )

    @pytest.mark.asyncio
    async def test_un_obligatorio_sin_rellenar_se_dice(self):
        """Callarlo dejaría la misma sección vacía de antes, ahora sin explicación."""
        from server.app.modules.redaccion.graph.nodes.user_input_fill import (
            UserInputFillNode,
        )

        cambios = await UserInputFillNode()(self._estado(valores={}))

        assert cambios["blocks"]["campo_movilidad"].status == "missing_input"
        assert any(
            w.block_id == "campo_movilidad" and w.kind == "missing_data"
            for w in cambios["warnings"]
        )

    @pytest.mark.asyncio
    async def test_no_toca_los_bloques_que_no_son_suyos(self):
        """Sin esto, lo de arriba se cumpliría pisando el informe entero."""
        from server.app.modules.redaccion.graph.nodes.user_input_fill import (
            UserInputFillNode,
        )

        estado = self._estado(valores={"campo_quejas": "algo"})
        cambios = await UserInputFillNode()(estado)

        assert cambios["blocks"]["campo_movilidad"].content is None

    @pytest.mark.asyncio
    async def test_un_valor_que_no_corresponde_a_ningun_bloque_se_ignora(self):
        """Lo que manda es la plantilla, no lo que llegue en el diccionario."""
        from server.app.modules.redaccion.graph.nodes.user_input_fill import (
            UserInputFillNode,
        )

        cambios = await UserInputFillNode()(self._estado(valores={"inventado": "x"}))

        assert "inventado" not in cambios["blocks"]


class TestElValorSeGuardaYSobrevive:
    """Pieza 2 — y en su propia columna, no entre los ficheros."""

    async def _workspace(self, session) -> uuid.UUID:
        from server.app.modules.redaccion.database.models import (
            HubReportTemplate,
            HubReportTemplateVersion,
            HubWorkspace,
        )
        from server.app.routers.redaccion._actor import user_to_uuid

        plantilla = HubReportTemplate(
            name=f"Plantilla {uuid.uuid4()}",
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

        workspace = HubWorkspace(
            template_version_id=version.id,
            owner_id=user_to_uuid("1"),
            status="draft",
        )
        session.add(workspace)
        await session.flush()
        identificador = workspace.id
        await session.commit()
        return identificador

    @pytest.mark.asyncio
    async def test_lo_escrito_se_guarda_y_no_ensucia_los_ficheros(self, db_url):
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlmodel.ext.asyncio.session import AsyncSession

        from server.app.core.auth.models import UserInfo
        from server.app.modules.redaccion.database.models import HubWorkspace
        from server.app.routers.redaccion.workspaces_router import (
            ManualInputsIn,
            set_workspace_fields,
        )

        motor = create_async_engine(db_url)
        try:
            async with AsyncSession(motor) as sesion:
                identificador = await self._workspace(sesion)

                await set_workspace_fields(
                    identificador,
                    ManualInputsIn(fields={"campo_quejas": "Ninguna"}),
                    user=UserInfo(user_id="1", email="a@uji.es", role="superadmin"),
                    session=sesion,
                )

            async with AsyncSession(motor) as sesion:
                fila = await sesion.get(HubWorkspace, identificador)
                assert fila.manual_inputs_json == {"campo_quejas": "Ninguna"}
                assert fila.inputs_json == {}, (
                    "el texto se ha colado entre los ficheros: saldría en la pantalla como un "
                    "fichero subido y en el registro como una entrada corrupta"
                )
        finally:
            await motor.dispose()

    @pytest.mark.asyncio
    async def test_vaciar_un_campo_lo_deja_vacio(self, db_url):
        """Es un `PUT`: fusionar dejaría vivo el valor anterior sin que nadie lo viera."""
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlmodel.ext.asyncio.session import AsyncSession

        from server.app.core.auth.models import UserInfo
        from server.app.modules.redaccion.database.models import HubWorkspace
        from server.app.routers.redaccion.workspaces_router import (
            ManualInputsIn,
            set_workspace_fields,
        )

        quien = UserInfo(user_id="1", email="a@uji.es", role="superadmin")
        motor = create_async_engine(db_url)
        try:
            async with AsyncSession(motor) as sesion:
                identificador = await self._workspace(sesion)
                await set_workspace_fields(
                    identificador, ManualInputsIn(fields={"campo_quejas": "Ninguna"}), quien, sesion
                )

            async with AsyncSession(motor) as sesion:
                await set_workspace_fields(
                    identificador, ManualInputsIn(fields={"campo_quejas": ""}), quien, sesion
                )

            async with AsyncSession(motor) as sesion:
                assert (await sesion.get(HubWorkspace, identificador)).manual_inputs_json == {}
        finally:
            await motor.dispose()


class TestLaPlantillaDelDoctoradoConcreta:
    """El efecto sobre la plantilla que abrió la issue, leída del fichero que se siembra."""

    def _spec_del_doctorado(self, version: int) -> ReportTemplateSpec:
        import json
        import pathlib

        fichero = (
            pathlib.Path(__file__).resolve().parents[3]
            / "app/data/plantillas_demo/informe_seguimiento_doctorado.json"
        )
        datos = json.loads(fichero.read_text(encoding="utf-8"))
        cruda = next(v for v in datos["versiones"] if v["version"] == version)
        return ReportTemplateSpec.model_validate(cruda["spec_json"])

    @pytest.mark.parametrize("version", [1, 2])
    def test_los_cuatro_campos_aparecen_en_las_dos_versiones(self, version):
        from server.app.modules.redaccion.services.campos_manuales import (
            con_los_campos_de_los_bloques,
        )

        spec = self._spec_del_doctorado(version)
        contrato = con_los_campos_de_los_bloques(spec)

        assert sorted(c.slot_id for c in contrato.manual_fields) == [
            "campo_destinos",
            "campo_movilidad",
            "campo_quejas",
            "campo_reacreditacion",
        ], "la sección «Datos aportados por la coordinación» sigue sin tener dónde rellenarse"
