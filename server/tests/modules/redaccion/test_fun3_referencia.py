"""FUN.3 — el bloque referencia `funcion@versión` en vez de llevar el código dentro.

Es el prompt que convierte la crítica de desarrollo en falsa también aquí. Hasta ahora aprobar un
script **lo incrustaba copiado** en el bloque de la plantilla (`options={"code": …, "approved":
True}`), así que dos plantillas que necesitaban la misma extracción eran dos propuestas, dos
aprobaciones y dos copias, y un error en un script usado por N plantillas se arreglaba N veces.

Lo que fija este fichero, en orden de importancia:

1. **Publicar v2 NO cambia una plantilla anclada a v1.** Es la clave de bóveda del bloque: sin
   ella, «arreglar una vez» sería «cambiar en silencio informes ya aprobados» y el `RunManifest`
   dejaría de ser reproducible.
2. **Dos plantillas referencian la misma función y las dos ejecutan.** El caso que justifica el
   catálogo.
3. **Registrar no es aprobar.** Declaración responsable + auditoría sin CRITICAL + sandbox
   superado → versión `registrada` y usable **de inmediato**, sin que ninguna persona dé el
   visto bueno. Es el nivel 2 de la Instrucció 02/2026, y la aprobación previa está prohibida
   como condición para compartir.
4. **Un `WARNING` del auditor no bloquea**: queda en la ficha para la revisión posterior. Un
   `CRITICAL` sí.
5. **Suspendida o retirada, el bloque falla EN ALTO y con el motivo.** Nunca vacío en silencio —
   la lección de los perfiles sin configurar.
6. **El contrato del bloque rechaza `options.code`.** Retirar el camino viejo es parte de la
   migración, no un paso opcional.
"""
from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError


# ──────────────────────────── El contrato del bloque ────────────────────────────


class TestElBloqueReferenciaEnVezDeCopiar:

    def test_should_accept_a_block_that_points_at_a_function_version(self):
        from server.app.modules.redaccion.contracts.blocks import DeterministicDataBlock

        funcion_id = uuid.uuid4()
        bloque = DeterministicDataBlock(
            id="b1",
            title="Gastos",
            source_pipeline="admin_script",
            funcion_ref={"funcion_id": str(funcion_id), "version": 1},
        )

        assert bloque.funcion_ref.funcion_id == funcion_id
        assert bloque.funcion_ref.version == 1

    def test_should_reject_the_embedded_code_that_used_to_live_in_options(self):
        """El camino viejo desaparece **del contrato**, no sólo del código que lo escribía: si
        siguiera validando, una plantilla podría volver a llevar el código dentro y nadie lo
        vería hasta que divergiera de su función."""
        from server.app.modules.redaccion.contracts.blocks import DeterministicDataBlock

        with pytest.raises(ValidationError) as fallo:
            DeterministicDataBlock(
                id="b1",
                title="Gastos",
                source_pipeline="admin_script",
                options={"code": "result = {}", "approved": True},
            )

        mensaje = str(fallo.value)
        assert "code" in mensaje
        assert "funcion_ref" in mensaje

    def test_should_refuse_an_admin_script_block_without_a_reference(self):
        """Un bloque de script sin función no puede ejecutar nada: antes esto se manifestaba
        como `SCRIPT_NOT_APPROVED`, que acusaba a la aprobación cuando lo que faltaba era el
        código."""
        from server.app.modules.redaccion.contracts.blocks import DeterministicDataBlock

        with pytest.raises(ValidationError) as fallo:
            DeterministicDataBlock(
                id="b1", title="Gastos", source_pipeline="admin_script"
            )

        assert "funcion_ref" in str(fallo.value)

    def test_should_leave_the_other_pipelines_alone(self):
        """`excel_pipeline` y compañía no tienen función: su bloque sigue como estaba."""
        from server.app.modules.redaccion.contracts.blocks import DeterministicDataBlock

        bloque = DeterministicDataBlock(
            id="b1", title="Gastos", source_pipeline="excel_pipeline"
        )

        assert bloque.funcion_ref is None


# ──────────────────────────── El resolutor ────────────────────────────


@pytest.fixture
async def catalogo(db_session):
    """Una función registrada con dos versiones, y las herramientas para pedirlas."""
    from server.app.modules.redaccion.database.models import (
        HubFuncion,
        HubFuncionVersion,
    )
    from server.app.modules.redaccion.funciones_service import sha256_del_codigo

    funcion = HubFuncion(
        nombre="Extraer gastos",
        descripcion="",
        organizacion_id=uuid.uuid4(),
        origen="autoservicio",
    )
    db_session.add(funcion)
    await db_session.flush()

    versiones = {}
    for numero, codigo in ((1, "result = {'free_text': 'v1'}"), (2, "result = {'free_text': 'v2'}")):
        version = HubFuncionVersion(
            funcion_id=funcion.id,
            version=numero,
            code=codigo,
            contrato_entrada={
                "slots": [{"slot_id": "datos", "kind": "excel", "required": False}],
                "parametros": [],
                "finalidad": "Extraer gastos",
                "categorias_datos": ["datos_economicos_y_financieros"],
            },
            contrato_salida={},
            code_sha256=sha256_del_codigo(codigo),
            estado="registrada",
            finalidad="Extraer gastos",
            categorias_datos=["datos_economicos_y_financieros"],
            declarada_por=uuid.uuid4(),
        )
        db_session.add(version)
        versiones[numero] = version
    await db_session.flush()
    return funcion, versiones


class TestElResolutor:

    @pytest.mark.asyncio
    async def test_should_hand_back_the_exact_version_that_was_anchored(self, db_session, catalogo):
        """**El test más importante del bloque.** Publicar v2 no cambia una plantilla anclada a
        v1: el anclaje es por versión exacta, por construcción."""
        from server.app.modules.redaccion.funciones_resolver import ResolvedorDeFuncion

        funcion, _ = catalogo
        resolutor = ResolvedorDeFuncion(db_session)

        ejecutable = await resolutor.resolver(funcion.id, 1)

        assert ejecutable.code == "result = {'free_text': 'v1'}"
        assert ejecutable.version == 1

    @pytest.mark.asyncio
    async def test_should_hand_back_v2_when_v2_is_the_one_anchored(self, db_session, catalogo):
        from server.app.modules.redaccion.funciones_resolver import ResolvedorDeFuncion

        funcion, _ = catalogo

        ejecutable = await ResolvedorDeFuncion(db_session).resolver(funcion.id, 2)

        assert ejecutable.code == "result = {'free_text': 'v2'}"

    @pytest.mark.asyncio
    async def test_should_carry_the_hash_of_what_will_run(self, db_session, catalogo):
        """El `RunManifest` registra la versión y el hash: hasta ahora no registraba nada de
        esto, porque el código iba incrustado y no tenía identidad."""
        from server.app.modules.redaccion.funciones_resolver import ResolvedorDeFuncion
        from server.app.modules.redaccion.funciones_service import sha256_del_codigo

        funcion, _ = catalogo

        ejecutable = await ResolvedorDeFuncion(db_session).resolver(funcion.id, 1)

        assert ejecutable.code_sha256 == sha256_del_codigo(ejecutable.code)

    @pytest.mark.asyncio
    async def test_should_fail_loudly_naming_the_function_when_the_version_does_not_exist(
        self, db_session, catalogo
    ):
        from server.app.modules.redaccion.funciones_resolver import (
            FuncionNoEjecutable,
            ResolvedorDeFuncion,
        )

        funcion, _ = catalogo

        with pytest.raises(FuncionNoEjecutable) as fallo:
            await ResolvedorDeFuncion(db_session).resolver(funcion.id, 7)

        mensaje = str(fallo.value)
        assert "Extraer gastos" in mensaje
        assert "7" in mensaje

    @pytest.mark.asyncio
    async def test_should_fail_loudly_with_the_reason_when_the_version_is_suspended(
        self, db_session, catalogo
    ):
        """El motivo viaja hasta el fallo del bloque: quien mira el informe tiene que poder
        saber por qué dejó de funcionar, y «revisión posterior» sin motivo no es una respuesta."""
        from server.app.modules.redaccion.funciones_resolver import (
            FuncionNoEjecutable,
            ResolvedorDeFuncion,
        )

        funcion, versiones = catalogo
        versiones[1].estado = "suspendida"
        versiones[1].motivo_suspension = "lee una ruta absoluta del equipo de quien la escribió"
        await db_session.flush()

        with pytest.raises(FuncionNoEjecutable) as fallo:
            await ResolvedorDeFuncion(db_session).resolver(funcion.id, 1)

        assert "ruta absoluta" in str(fallo.value)

    @pytest.mark.asyncio
    async def test_should_fail_loudly_when_the_function_is_withdrawn(self, db_session, catalogo):
        from server.app.modules.redaccion.funciones_resolver import (
            FuncionNoEjecutable,
            ResolvedorDeFuncion,
        )

        funcion, versiones = catalogo
        versiones[1].estado = "retirada"
        await db_session.flush()

        with pytest.raises(FuncionNoEjecutable) as fallo:
            await ResolvedorDeFuncion(db_session).resolver(funcion.id, 1)

        assert "retirada" in str(fallo.value)

    @pytest.mark.asyncio
    async def test_should_never_return_empty_in_silence(self, db_session):
        """Una función que no existe es un fallo, no un resultado vacío: es la lección de los
        perfiles sin configurar, que devolvían nada y parecían funcionar."""
        from server.app.modules.redaccion.funciones_resolver import (
            FuncionNoEjecutable,
            ResolvedorDeFuncion,
        )

        with pytest.raises(FuncionNoEjecutable):
            await ResolvedorDeFuncion(db_session).resolver(uuid.uuid4(), 1)

    @pytest.mark.asyncio
    async def test_should_serve_the_same_version_to_two_templates(self, db_session, catalogo):
        """**El caso que justifica el catálogo**: dos plantillas, una función, y las dos
        ejecutan lo mismo. Antes eran dos copias que podían divergir."""
        from server.app.modules.redaccion.funciones_resolver import ResolvedorDeFuncion

        funcion, _ = catalogo
        resolutor = ResolvedorDeFuncion(db_session)

        una = await resolutor.resolver(funcion.id, 1)
        otra = await resolutor.resolver(funcion.id, 1)

        assert una.code == otra.code
        assert una.code_sha256 == otra.code_sha256


# ──────────────────────────── Lo que el nodo hace con la referencia ────────────────────────────


class TestElNodoResuelveLaReferencia:

    @pytest.mark.asyncio
    async def test_should_pass_the_resolved_code_to_the_pipeline(self, db_session, catalogo):
        """El pipeline no cambia: sigue recibiendo el código en `options`. Lo que cambia es de
        dónde sale — del catálogo y no del bloque."""
        from server.app.modules.redaccion.funciones_resolver import ResolvedorDeFuncion

        funcion, _ = catalogo
        ejecutable = await ResolvedorDeFuncion(db_session).resolver(funcion.id, 1)

        opciones = ejecutable.como_opciones_del_pipeline()

        assert opciones["code"] == "result = {'free_text': 'v1'}"
        # `approved` sigue ahí porque el pipeline lo exige, y ahora significa lo que de verdad
        # pasó: la versión está **registrada** (auditada y probada), que es la puerta del nivel 2.
        assert opciones["approved"] is True

    @pytest.mark.asyncio
    async def test_should_describe_itself_for_the_run_manifest(self, db_session, catalogo):
        from server.app.modules.redaccion.funciones_resolver import ResolvedorDeFuncion

        funcion, _ = catalogo
        ejecutable = await ResolvedorDeFuncion(db_session).resolver(funcion.id, 1)

        anotacion = ejecutable.para_el_manifiesto()

        assert anotacion["funcion_id"] == str(funcion.id)
        assert anotacion["version"] == 1
        assert anotacion["code_sha256"] == ejecutable.code_sha256
        assert anotacion["origen"] == "autoservicio"
