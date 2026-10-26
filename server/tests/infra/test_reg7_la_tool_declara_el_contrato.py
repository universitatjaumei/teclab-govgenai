"""REG.7 — la tool MCP declara el contrato del evento, y no puede quedarse atrás.

**El defecto que este guardarraíl cierra.** `registrar_actividad` recibía `evento: dict`, así que
el esquema que un cliente MCP obtenía de `tools/list` era esto:

    {"evento": {"type": "object", "additionalProperties": true}}

Un objeto opaco. Quien integra no recibía ningún nombre de campo, ni cuáles son obligatorios, ni
que `ocurrido_en` exige zona horaria — y encima `additionalProperties: true` **contradice al
servidor**, que rechaza los campos no declarados con 422. El esquema decía «vale cualquier cosa» y
el endpoint decía que no, así que un agente lo descubría a base de 422 en bucle.

**Por qué el guardarráil vive aquí y no en `mcp_server/tests/`.** Tipar la firma convierte el
contrato en una segunda declaración, que puede divergir del `ActividadIAEvent` del servidor. Para
comprobarlo hay que tener los dos delante, y `mcp_server/` **no puede importar `server.app`** —es
la regla de MCP.1, con su propio test— ni tiene sus dependencias en el venv. La suite del servidor
sí alcanza los dos: el fichero de la tool es texto que se lee con `ast`.

Lo que se compara son los **nombres y la obligatoriedad**, no los tipos. Los tipos del lado MCP
son los que viajan en JSON (`str` para la marca de tiempo) y el que valida es el servidor: mover
esa validación al cliente sólo cambiaría el sitio donde falla, y el mensaje bueno está donde vive
la regla.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[3]
TOOL = RAIZ / "mcp_server" / "tools" / "actividad.py"


@pytest.fixture(scope="module")
def firma() -> ast.arguments:
    """Los argumentos de la tool `registrar_actividad`, leídos con `ast`."""
    assert TOOL.is_file(), f"Falta {TOOL.relative_to(RAIZ).as_posix()}"
    arbol = ast.parse(TOOL.read_text(encoding="utf-8"))

    funciones = [
        nodo
        for nodo in ast.walk(arbol)
        if isinstance(nodo, (ast.AsyncFunctionDef, ast.FunctionDef))
        and nodo.name == "registrar_actividad"
    ]
    assert funciones, "no se encuentra la tool `registrar_actividad` en el paquete MCP"
    # La que registra la tool es la de dentro de `register_actividad_tools`; si hubiera dos con
    # el mismo nombre, la última definida es la que el decorador registra.
    return funciones[-1].args


def _nombres(args: ast.arguments) -> list[str]:
    return [a.arg for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)]


def _obligatorios(args: ast.arguments) -> set[str]:
    """Los que no tienen valor por defecto: los que el cliente tiene que dar."""
    posicionales = [*args.posonlyargs, *args.args]
    con_defecto = len(args.defaults)
    sin_defecto = posicionales[: len(posicionales) - con_defecto] if con_defecto else posicionales
    solo_clave = [
        a.arg
        for a, d in zip(args.kwonlyargs, args.kw_defaults, strict=True)
        if d is None
    ]
    return {a.arg for a in sin_defecto} | set(solo_clave)


class TestLaToolDeclaraLosCamposDelContrato:

    def test_should_expose_every_field_of_the_event(self, firma: ast.arguments):
        """Un campo del contrato que no esté en la firma es un campo que nadie puede mandar."""
        from server.app.modules.agents_hub.contracts.actividad import ActividadIAEvent

        del_contrato = set(ActividadIAEvent.model_fields)
        de_la_tool = set(_nombres(firma))

        assert del_contrato == de_la_tool, (
            f"la firma de la tool y el contrato no dicen lo mismo. Sólo en el contrato: "
            f"{sorted(del_contrato - de_la_tool)}; sólo en la tool: "
            f"{sorted(de_la_tool - del_contrato)}. Un campo que falta en la firma no se puede "
            "mandar por MCP; uno que sobra provoca un 422 que el cliente no puede prever."
        )

    def test_should_not_take_an_opaque_object(self, firma: ast.arguments):
        """La regresión concreta: volver a `evento: dict` deja el esquema sin contrato."""
        assert "evento" not in _nombres(firma), (
            "`evento: dict` genera `{\"type\": \"object\", \"additionalProperties\": true}`, que "
            "no dice ningún campo y además contradice el `extra=\"forbid\"` del servidor."
        )

    def test_should_require_exactly_what_the_contract_requires(self, firma: ast.arguments):
        """Sin valor por defecto en la firma == obligatorio en el esquema MCP.

        Si la firma pidiera menos, el cliente mandaría una petición incompleta creyendo que vale;
        si pidiera más, no podría omitir un campo que el servidor acepta vacío.
        """
        from server.app.modules.agents_hub.contracts.actividad import ActividadIAEvent

        del_contrato = {
            nombre
            for nombre, campo in ActividadIAEvent.model_fields.items()
            if campo.is_required()
        }

        assert _obligatorios(firma) == del_contrato, (
            f"obligatorios en la tool {sorted(_obligatorios(firma))} frente a "
            f"{sorted(del_contrato)} en el contrato."
        )

    def test_should_describe_each_field_for_whoever_integrates(self, firma: ast.arguments):
        """Cada campo lleva descripción, que es lo que el cliente MCP ve en el esquema.

        Es la mitad del arreglo: los nombres los da la firma, pero «con zona horaria» o «SHA-256
        en minúscula» no se deducen de `str`. Sin esto, el esquema vuelve a obligar a adivinar.
        """
        fuente = TOOL.read_text(encoding="utf-8")
        sin_descripcion = [
            nombre
            for nombre in _nombres(firma)
            if f"{nombre}: Annotated" not in fuente
        ]
        assert sin_descripcion == [], (
            f"estos campos no llevan `Annotated[..., Field(description=...)]`: "
            f"{sin_descripcion}. La descripción viaja en el esquema y es donde caben las reglas "
            "que el tipo no expresa."
        )


# ─────────────────────────── VAS.4: las mismas cuentas para las verificaciones ──


VERIFICACIONES = RAIZ / "mcp_server" / "tools" / "verificaciones.py"


def _args_de(fichero: Path, nombre: str) -> ast.arguments:
    arbol = ast.parse(fichero.read_text(encoding="utf-8"))
    funciones = [
        nodo
        for nodo in ast.walk(arbol)
        if isinstance(nodo, (ast.AsyncFunctionDef, ast.FunctionDef)) and nodo.name == nombre
    ]
    assert funciones, f"no se encuentra la tool `{nombre}`"
    return funciones[-1].args


class TestLasToolsDeVerificacionesDeclaranSusCampos:
    """VAS.4 aplica de entrada la lección de REG.7, y esto lo mantiene.

    El contrato del lado servidor son modelos Pydantic (`PeticionDeCitas`,
    `PeticionDeAuditoria`), así que la comparación es la misma que la del evento: nombres y
    obligatoriedad, no tipos.
    """

    def test_should_match_the_citation_request_contract(self):
        from server.app.routers.verificaciones_router import PeticionDeCitas

        de_la_tool = set(_nombres(_args_de(VERIFICACIONES, "verificar_citas")))
        del_contrato = set(PeticionDeCitas.model_fields)

        # `modo` no se expone en la tool a propósito: hoy el contrato de citas se comporta igual
        # en los tres modos, y un parámetro que no cambia nada sólo invita a rellenarlo mal.
        assert de_la_tool <= del_contrato, (
            f"la tool manda campos que el contrato no declara: {sorted(de_la_tool - del_contrato)}"
        )
        assert {"texto", "fuentes_permitidas"} <= de_la_tool

    def test_should_match_the_audit_request_contract(self):
        from server.app.routers.verificaciones_router import PeticionDeAuditoria

        de_la_tool = set(_nombres(_args_de(VERIFICACIONES, "auditar_codigo")))

        assert de_la_tool == set(PeticionDeAuditoria.model_fields)

    def test_should_not_take_an_opaque_object(self):
        """La regresión de REG.7, vigilada también aquí."""
        for tool in ("verificar_citas", "consultar_vigencia", "auditar_codigo"):
            nombres = _nombres(_args_de(VERIFICACIONES, tool))
            assert "cuerpo" not in nombres, tool
            assert "peticion" not in nombres, tool

    def test_should_describe_each_field(self):
        fuente = VERIFICACIONES.read_text(encoding="utf-8")
        for tool in ("verificar_citas", "consultar_vigencia", "auditar_codigo"):
            for nombre in _nombres(_args_de(VERIFICACIONES, tool)):
                assert f"{nombre}: Annotated" in fuente, f"{tool}.{nombre}"

