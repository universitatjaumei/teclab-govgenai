"""INF.4 — la IA propone sobre datos que ha visto.

`propose` recibía **solo** `body.prompt_nl`: ninguna muestra de datos. El usuario pidió un
informe sobre un CSV de saldos describiendo las columnas a mano en el prompt, y el modelo tuvo
que adivinar el resto. Adivinó mal: ancló la valoración al bloque `TABLE` en vez de al
`DETERMINISTIC_DATA`, que es justo lo que el validador rechaza.

El legacy no lo hacía así. `client_app/app/modules/factory/etl_factory.py:146-200` preparaba el
contexto del fichero —`columns`, `dtypes`, `row_count`, `df.head(3)`— y **lo anonimizaba antes
de enviarlo** (línea 152). Es el diseño correcto y se perdió en la migración; lo señaló el
usuario, no se deduce del código.
"""
from __future__ import annotations

import pytest


def _csv_de_tesoreria() -> bytes:
    """El caso real del usuario: saldos por cuenta y periodo, importes como texto."""
    return (
        "ccc,denominacion,periodo,banco,_id,saldo\n"
        "0001,Cuenta Nomina,202601,Banco A,1,\"1.234,56\"\n"
        "0002,Cuenta Gastos,202602,Banco B,2,\"7.890,12\"\n"
        "0003,Cuenta Ingresos,202603,Banco C,3,\"3.456,78\"\n"
        "0004,Cuenta Reserva,202604,Banco D,4,\"9.999,99\"\n"
    ).encode("utf-8")


class TestElResumenDeLaMuestra:
    def test_should_report_columns_types_rows_and_a_head_of_three(self):
        from server.app.modules.redaccion.services.muestra_de_datos import resumen_de_la_muestra

        muestra = resumen_de_la_muestra(_csv_de_tesoreria(), "saldos.csv")

        assert muestra.columnas == ["ccc", "denominacion", "periodo", "banco", "_id", "saldo"]
        assert muestra.filas_totales == 4
        # Tres filas, como el legacy: bastantes para ver la forma, pocas para no volcar datos.
        assert len(muestra.primeras_filas) == 3
        assert set(muestra.tipos) == set(muestra.columnas)

    def test_should_keep_the_amount_column_as_text_when_it_is_text(self):
        """«1.234,56» es como lo exportan las aplicaciones de aquí, y el modelo tiene que
        verlo para poner el `to_number` antes de sumar. Si el resumen dijera que es numérico,
        el modelo se saltaría la conversión y el informe daría una cifra mal sin avisar."""
        from server.app.modules.redaccion.services.muestra_de_datos import resumen_de_la_muestra

        muestra = resumen_de_la_muestra(_csv_de_tesoreria(), "saldos.csv")

        assert "object" in muestra.tipos["saldo"] or "str" in muestra.tipos["saldo"]

    def test_should_refuse_a_file_it_cannot_read(self):
        from server.app.modules.redaccion.services.muestra_de_datos import (
            MuestraIlegibleError,
            resumen_de_la_muestra,
        )

        with pytest.raises(MuestraIlegibleError):
            resumen_de_la_muestra(b"\x00\x01\x02 esto no es una tabla", "cosa.bin")

    def test_should_anonymise_the_sample_values(self):
        """Los valores salen anonimizados. Es la mitad del diseño del legacy que importa: la
        muestra viaja a un modelo que puede estar en la nube."""
        from server.app.modules.redaccion.services.muestra_de_datos import resumen_de_la_muestra

        csv = (
            "nombre,dni,correo,importe\n"
            "Modesto Fabra,12345678Z,admin@example.local,100\n"
            "Ana Garcia Lopez,87654321X,ana@uji.es,200\n"
        ).encode("utf-8")

        muestra = resumen_de_la_muestra(csv, "personas.csv")
        plano = str(muestra.primeras_filas)

        assert "12345678Z" not in plano
        assert "admin@example.local" not in plano
        # Las columnas **sí** se conservan: son estructura, no dato personal, y son justo lo
        # que el modelo necesita para no inventarse nombres de campo.
        assert muestra.columnas == ["nombre", "dni", "correo", "importe"]


class TestLoQueLlegaAlModelo:
    async def test_should_put_the_structure_in_the_prompt(self):
        from server.app.modules.redaccion.services.llm_spec_service import LLMSpecService
        from server.app.modules.redaccion.services.muestra_de_datos import resumen_de_la_muestra

        capturado: dict = {}

        class _ModeloFalso:
            async def ainvoke(self, messages, **_kwargs):
                capturado["messages"] = messages
                raise RuntimeError("solo interesa el prompt")

        servicio = LLMSpecService(_ModeloFalso(), "modelo-de-prueba")
        muestra = resumen_de_la_muestra(_csv_de_tesoreria(), "saldos.csv")

        with pytest.raises(RuntimeError, match="solo interesa el prompt"):
            await servicio.propose_template(
                "Informe de tesoreria por ano y mes", "admin", muestra=muestra
            )

        texto = " ".join(str(m.get("content", "")) for m in capturado["messages"])
        for columna in ("ccc", "periodo", "saldo"):
            assert columna in texto, f"el modelo no ve la columna {columna!r}"
        assert "saldos.csv" in texto
        assert "4" in texto  # el numero de filas

    async def test_should_behave_the_same_without_a_sample(self):
        """Sin fichero no cambia nada: no se convierte en obligatorio lo que hoy funciona."""
        from server.app.modules.redaccion.services.llm_spec_service import LLMSpecService

        capturado: dict = {}

        class _ModeloFalso:
            async def ainvoke(self, messages, **_kwargs):
                capturado["messages"] = messages
                raise RuntimeError("solo interesa el prompt")

        servicio = LLMSpecService(_ModeloFalso(), "modelo-de-prueba")

        with pytest.raises(RuntimeError, match="solo interesa el prompt"):
            await servicio.propose_template("Un informe cualquiera", "admin")

        assert len(capturado["messages"]) == 2  # sistema + peticion, nada mas

    async def test_should_tell_the_model_those_are_the_only_columns(self):
        """Sin decirlo, el modelo completa con columnas plausibles que no existen."""
        from server.app.modules.redaccion.services.llm_spec_service import LLMSpecService
        from server.app.modules.redaccion.services.muestra_de_datos import resumen_de_la_muestra

        capturado: dict = {}

        class _ModeloFalso:
            async def ainvoke(self, messages, **_kwargs):
                capturado["messages"] = messages
                raise RuntimeError("solo interesa el prompt")

        servicio = LLMSpecService(_ModeloFalso(), "modelo-de-prueba")
        await_error = pytest.raises(RuntimeError, match="solo interesa el prompt")
        with await_error:
            await servicio.propose_template(
                "Informe", "admin", muestra=resumen_de_la_muestra(_csv_de_tesoreria(), "s.csv")
            )

        texto = " ".join(str(m.get("content", "")) for m in capturado["messages"]).lower()
        assert "only columns" in texto or "no otras" in texto or "do not invent" in texto
