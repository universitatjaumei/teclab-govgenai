"""FUN.2 — el contrato de entrada y salida de una función, declarado y validado.

Hoy el contrato de un script es **implícito**: «tienes `file_path`, `raw_text` y `options`, asigna
`result`». Eso funciona mientras quien escribe el script y quien le pasa los datos son la misma
persona el mismo día. En cuanto una función se comparte entre dos plantillas, dos organizaciones y
una API, el contrato implícito se convierte en el sitio por donde se rompe todo: un ERP cambia una
columna y el informe falla con un `KeyError` de pandas dentro del sandbox.

Lo que fija este prompt:

* **El contrato es dato declarado de la versión**, no una convención. Slots de fichero y
  parámetros tipados a la entrada; `ExtractionResult` —el que ya existe— a la salida. No se
  inventa un segundo esquema de salida: el que hay es el que consumen los nodos, y dos esquemas
  divergen.
* **Los parámetros reutilizan la forma de `UIFieldDescriptor`**, así que el SDUI pinta el
  formulario desde el contrato, gratis y sin un campo *hardcoded* en React (regla maestra 1).
* **Un solo objeto y un solo validador para los dos orígenes.** Lo que declara una función
  empaquetada en su descriptor (FUN.5) es este mismo `ContratoFuncion`. Ninguna rama «si es
  paquete»: dos esquemas de contrato divergen, y uno solo es lo que hace que el formulario, la API
  y el expediente traten igual a las dos.
* **La declaración responsable forma parte del contrato**, porque es lo que la Instrucció exige
  registrar antes de compartir y lo que la revisión posterior lee — también en una función
  corporativa.
* **La entrada se valida ANTES de llegar al sandbox**, y el error es tipado: «falta el slot
  datos», no un *traceback*.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError


# ──────────────────────────── El contrato se declara ────────────────────────────


def _contrato_minimo(**kw):
    from server.app.modules.redaccion.contracts.funciones import ContratoFuncion

    datos = {
        "slots": [{"slot_id": "datos", "kind": "excel", "required": True}],
        "parametros": [],
        "finalidad": "Extraer la tabla de gastos del ERP",
        "categorias_datos": ["datos_economicos_y_financieros"],
    }
    datos.update(kw)
    return ContratoFuncion(**datos)


class TestElContratoSeDeclara:

    def test_should_accept_a_contract_with_slots_and_typed_parameters(self):
        contrato = _contrato_minimo(
            parametros=[
                {
                    "slot_id": "umbral",
                    "label": {"es": "Umbral", "ca": "Llindar", "en": "Threshold"},
                    "field_type": "number",
                    "required": True,
                }
            ]
        )

        assert contrato.slots[0].slot_id == "datos"
        assert contrato.parametros[0].field_type == "number"

    def test_should_default_the_output_to_the_schema_that_already_exists(self):
        """No se inventa un segundo esquema de salida: `ExtractionResult` es el que consumen los
        nodos, y dos esquemas divergen."""
        assert _contrato_minimo().salida == "ExtractionResult"

    def test_should_refuse_a_slot_of_an_unknown_kind(self):
        with pytest.raises(ValidationError) as fallo:
            _contrato_minimo(slots=[{"slot_id": "datos", "kind": "parquet"}])

        assert "parquet" in str(fallo.value)

    def test_should_refuse_a_parameter_of_an_unknown_type(self):
        with pytest.raises(ValidationError):
            _contrato_minimo(
                parametros=[
                    {"slot_id": "umbral", "label": {"es": "Umbral"}, "field_type": "matriz"}
                ]
            )

    def test_should_refuse_two_slots_with_the_same_identifier(self):
        """Dos slots homónimos hacen ambigua la entrada: el segundo pisaría al primero y el
        formulario pintaría dos campos que escriben en el mismo sitio."""
        with pytest.raises(ValidationError) as fallo:
            _contrato_minimo(
                slots=[
                    {"slot_id": "datos", "kind": "excel"},
                    {"slot_id": "datos", "kind": "pdf"},
                ]
            )

        assert "datos" in str(fallo.value)

    def test_should_refuse_a_parameter_that_collides_with_a_slot(self):
        """El mismo espacio de nombres: la entrada es un solo diccionario."""
        with pytest.raises(ValidationError):
            _contrato_minimo(
                parametros=[{"slot_id": "datos", "label": {"es": "Datos"}}]
            )


class TestLaDeclaracionFormaParteDelContrato:
    """§8.2 de la Instrucció: finalidad y categorías de datos, antes de compartir. También en una
    función corporativa — el descriptor de un paquete declara lo mismo (FUN.5)."""

    def test_should_refuse_a_contract_without_a_purpose(self):
        with pytest.raises(ValidationError) as fallo:
            _contrato_minimo(finalidad="")

        assert "finalidad" in str(fallo.value).lower()

    def test_should_refuse_a_contract_with_no_data_categories(self):
        """Una lista vacía es ambigua entre «no hubo datos personales» y «no lo declaré», y en una
        auditoría son dos cosas muy distintas. El vocabulario de REG tiene un código para lo
        primero (`sin_datos_personales`), así que callar no vale."""
        with pytest.raises(ValidationError) as fallo:
            _contrato_minimo(categorias_datos=[])

        assert "categor" in str(fallo.value).lower()

    def test_should_share_the_vocabulary_with_the_activity_register(self):
        """Un solo vocabulario de categorías en la plataforma: si el catálogo y el registro de
        actividad usaran dos, los dos registros no se podrían cruzar en una auditoría."""
        from server.app.core.actividad_categorias import CATEGORIAS_INICIALES
        from server.app.modules.redaccion.contracts.funciones import (
            CATEGORIAS_CONOCIDAS,
        )

        assert CATEGORIAS_CONOCIDAS == tuple(c for c, _ in CATEGORIAS_INICIALES)

    def test_should_accept_a_category_outside_the_seed(self):
        """El vocabulario es **abierto** (I4): rechazar un código no catalogado convertiría «esta
        categoría todavía no está dada de alta» en «esta función no se puede declarar»."""
        contrato = _contrato_minimo(categorias_datos=["expedientes_de_contratacion"])

        assert contrato.categorias_datos == ["expedientes_de_contratacion"]


# ──────────────────────────── El formulario sale del contrato ────────────────────────────


class TestElFormularioSaleDelContrato:

    def test_should_derive_the_sdui_descriptors_from_the_declared_contract(self):
        """Regla maestra 1: el frontend no conoce los campos a priori; los pinta iterando lo que
        el servidor declara. Este test comprueba que salen del contrato y no de literales."""
        from server.app.modules.redaccion.contracts.funciones import (
            descriptores_de_formulario,
        )

        contrato = _contrato_minimo(
            slots=[
                {"slot_id": "datos", "kind": "excel", "required": True},
                {"slot_id": "anexo", "kind": "pdf", "required": False},
            ],
            parametros=[
                {
                    "slot_id": "umbral",
                    "label": {"es": "Umbral"},
                    "field_type": "number",
                    "required": True,
                }
            ],
        )

        formulario = descriptores_de_formulario(contrato)

        assert [d.slot_id for d in formulario.dropzones] == ["datos", "anexo"]
        assert [d.required for d in formulario.dropzones] == [True, False]
        # Lo que el navegador acepta sale del `kind`, no de una lista escrita en React.
        assert ".xlsx" in formulario.dropzones[0].accept
        assert [c.slot_id for c in formulario.campos] == ["umbral"]
        assert formulario.campos[0].field_type == "number"

    def test_should_be_the_descriptors_the_report_ui_already_uses(self):
        """Los mismos tipos que `ReportUIContract`: si fueran otros, la pantalla de informes y la
        de funciones pintarían formularios distintos para lo mismo."""
        from server.app.modules.redaccion.contracts.funciones import (
            descriptores_de_formulario,
        )
        from server.app.modules.redaccion.contracts.ui import (
            UIDropzoneDescriptor,
            UIFieldDescriptor,
        )

        formulario = descriptores_de_formulario(
            _contrato_minimo(parametros=[{"slot_id": "umbral", "label": {"es": "U"}}])
        )

        assert isinstance(formulario.dropzones[0], UIDropzoneDescriptor)
        assert isinstance(formulario.campos[0], UIFieldDescriptor)


# ──────────────────────────── La entrada se valida antes ────────────────────────────


class TestLaEntradaSeValidaAntesDelSandbox:

    @staticmethod
    def _contrato():
        return _contrato_minimo(
            slots=[
                {"slot_id": "datos", "kind": "excel", "required": True},
                {"slot_id": "anexo", "kind": "pdf", "required": False},
            ],
            parametros=[
                {"slot_id": "umbral", "label": {"es": "Umbral"}, "field_type": "number"}
            ],
        )

    def test_should_accept_an_entry_that_meets_the_contract(self):
        from server.app.modules.redaccion.contracts.funciones import validar_entrada

        entrada = validar_entrada(
            self._contrato(),
            ficheros={"datos": "/tmp/gastos.xlsx"},
            parametros={"umbral": 12.5},
        )

        assert entrada.ficheros["datos"].endswith(".xlsx")
        assert entrada.parametros["umbral"] == 12.5

    def test_should_say_which_slot_is_missing(self):
        """El fallo de un ERP que cambia de formato tiene que ser «la entrada no cumple el
        contrato», no un *traceback* de pandas."""
        from server.app.modules.redaccion.contracts.funciones import (
            EntradaNoCumpleElContrato,
            validar_entrada,
        )

        with pytest.raises(EntradaNoCumpleElContrato) as fallo:
            validar_entrada(self._contrato(), ficheros={}, parametros={"umbral": 1})

        assert "datos" in str(fallo.value)

    def test_should_not_require_an_optional_slot(self):
        from server.app.modules.redaccion.contracts.funciones import validar_entrada

        validar_entrada(
            self._contrato(), ficheros={"datos": "/tmp/g.xlsx"}, parametros={"umbral": 1}
        )

    def test_should_say_which_parameter_is_not_of_its_type(self):
        from server.app.modules.redaccion.contracts.funciones import (
            EntradaNoCumpleElContrato,
            validar_entrada,
        )

        with pytest.raises(EntradaNoCumpleElContrato) as fallo:
            validar_entrada(
                self._contrato(),
                ficheros={"datos": "/tmp/g.xlsx"},
                parametros={"umbral": "doce y medio"},
            )

        mensaje = str(fallo.value)
        assert "umbral" in mensaje and "num" in mensaje.lower()

    def test_should_refuse_a_file_in_a_slot_that_the_contract_does_not_declare(self):
        """Un slot de más es tan sospechoso como uno de menos: o alguien cambió el contrato sin
        avisar, o está mandando datos a una función que no los pidió."""
        from server.app.modules.redaccion.contracts.funciones import (
            EntradaNoCumpleElContrato,
            validar_entrada,
        )

        with pytest.raises(EntradaNoCumpleElContrato) as fallo:
            validar_entrada(
                self._contrato(),
                ficheros={"datos": "/tmp/g.xlsx", "sobrante": "/tmp/x.pdf"},
                parametros={},
            )

        assert "sobrante" in str(fallo.value)

    @pytest.mark.asyncio
    async def test_should_not_touch_the_sandbox_when_the_entry_is_invalid(self):
        """**El test que justifica el prompt**: el espía sobre el cliente del sandbox no recibe
        ninguna llamada. Validar después sería pagar un subproceso para obtener un error peor."""
        from server.app.modules.redaccion.contracts.funciones import (
            EntradaNoCumpleElContrato,
        )
        from server.app.modules.redaccion.funciones_service import ejecutar_funcion

        class _EspiaDeSandbox:
            def __init__(self) -> None:
                self.llamadas = 0

            async def execute_extraction_script(self, **kw):  # pragma: no cover
                self.llamadas += 1
                raise AssertionError("no se puede llegar al sandbox con la entrada inválida")

        espia = _EspiaDeSandbox()

        with pytest.raises(EntradaNoCumpleElContrato):
            await ejecutar_funcion(
                contrato=self._contrato(),
                code="result = {}",
                ficheros={},
                parametros={},
                sandbox=espia,
            )

        assert espia.llamadas == 0

    @pytest.mark.asyncio
    async def test_should_reach_the_sandbox_with_todays_protocol_when_the_entry_is_valid(self):
        """El protocolo del script no cambia: `file_path`, `raw_text` y `options`. Cambiar eso
        obligaría a reescribir los scripts que ya funcionan, que es justo lo que empuja al
        *Shadow IT*.

        Lo que sí cambió (issue #194) es el tramo **hasta** el sandbox: le llega el contenido
        (`file_bytes`, con el nombre y su extensión) y no la referencia de almacenamiento, que
        en otro contenedor no es una ruta de nada. El sandbox lo materializa y el guion sigue
        recibiendo su `file_path` de siempre."""
        from server.app.modules.redaccion.funciones_service import ejecutar_funcion

        recibido: dict = {}

        class _Almacen:
            async def get(self, key):
                assert key == "org/1/gastos.xlsx"
                return b"contenido del excel"

        class _Sandbox:
            async def execute_extraction_script(
                self, *, code, file_path=None, raw_text=None, options=None, **kw
            ):
                recibido.update(
                    code=code, file_path=file_path, raw_text=raw_text, options=options, **kw
                )
                from server.app.modules.redaccion.pipelines.contracts import (
                    ExtractionProvenance,
                    ExtractionResult,
                )

                from datetime import datetime, timezone

                return ExtractionResult(
                    free_text="ok",
                    provenance=ExtractionProvenance(
                        pipeline_id="prueba",
                        source_ref="datos",
                        extracted_at=datetime.now(timezone.utc),
                    ),
                )

        await ejecutar_funcion(
            contrato=self._contrato(),
            code="result = {}",
            ficheros={"datos": "org/1/gastos.xlsx"},
            parametros={"umbral": 3},
            sandbox=_Sandbox(),
            almacen=_Almacen(),
        )

        assert recibido["file_path"] is None
        assert recibido["file_bytes"] == b"contenido del excel"
        assert recibido["file_name"] == "gastos.xlsx"
        assert recibido["options"]["umbral"] == 3


class TestLaSalidaSeValida:

    @pytest.mark.asyncio
    async def test_should_report_an_output_that_is_not_an_extraction_result_as_a_warning(self):
        """Un aviso de error, no una excepción opaca: quien mira el informe tiene que ver que la
        función devolvió algo que no encaja, y con qué."""
        from server.app.modules.redaccion.funciones_service import ejecutar_funcion

        class _SandboxQueDevuelveBasura:
            """Un cliente que devuelve algo que no es `ExtractionResult`. Con el sandbox real no
            pasa —lo construye él—, pero en FUN.5 el `run` de un paquete de un tercero devuelve
            lo que haya escrito ese tercero, y la costura tiene que aguantarlo."""

            async def execute_extraction_script(self, **kw):
                return {"tablas": "esto no es el contrato"}

        resultado = await ejecutar_funcion(
            contrato=_contrato_minimo(),
            code="result = {}",
            ficheros={"datos": "/tmp/g.xlsx"},
            parametros={},
            sandbox=_SandboxQueDevuelveBasura(),
        )

        assert resultado.warnings
        assert resultado.warnings[0].severity == "error"
        assert "contrato" in resultado.warnings[0].message.lower()


class TestUnSoloValidadorParaLosDosOrigenes:

    def test_should_validate_a_packaged_descriptor_with_the_same_object(self):
        """Lo que declara un paquete (FUN.5) es este mismo `ContratoFuncion`. El test de FUN.5 que
        registra un contrato incoherente reutiliza este validador sin tocarlo."""
        from server.app.modules.redaccion.contracts.funciones import (
            ContratoFuncion,
            contrato_coherente,
        )

        contrato = ContratoFuncion.model_validate(
            {
                "slots": [{"slot_id": "datos", "kind": "excel", "required": True}],
                "parametros": [],
                "finalidad": "Explotar el ERP común de las cuatro organizaciones",
                "categorias_datos": ["datos_economicos_y_financieros"],
            }
        )

        contrato_coherente(contrato)  # no levanta

    def test_should_refuse_an_incoherent_contract_saying_why(self):
        from server.app.modules.redaccion.contracts.funciones import (
            ContratoIncoherente,
            contrato_coherente,
        )

        with pytest.raises(ContratoIncoherente) as fallo:
            contrato_coherente(
                _contrato_minimo(slots=[]), exige_entrada=True
            )

        assert "slot" in str(fallo.value).lower()
