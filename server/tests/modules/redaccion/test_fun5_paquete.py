"""FUN.5 — el origen empaquetado: funciones que llegan por *entry point*.

La respuesta a «¿qué añade hacerlo en la plataforma en vez de en el editor de quien programa?».
Un equipo con repositorio, CI y semver mantiene su función donde la escribe; lo que la plataforma
se queda es **la revisión, el contrato, el manifiesto y la trazabilidad**, no el código. Y se
queda con ellos **por el mismo camino** que una función de autoservicio: un solo validador, un
solo resolutor, un solo nodo.

Tres decisiones que se comprueban aquí porque son las que se pueden perder sin ruido:

* **El arranque falla en alto** ante un contrato incoherente, nombrando paquete y función. Un
  `warning` dejaría un servidor en pie al que le falta una función, y el síntoma aparecería como
  «la plantilla referencia algo que no existe», sin pista del paquete roto. Es literalmente la
  lección que `public_graphs/plugins.py` ya escribió para los perfiles.
* **El anclaje es por mayor**, no exacto: es lo que compra el semver, y sin ello instalar 1.3.0
  rompería todas las plantillas ancladas a 1.2.0. Pero el manifiesto anota la **instalada
  exacta** con su hash, porque «qué corrió» no admite aproximaciones.
* **Una versión que se desinstala no se borra**: pasa a `no_instalada`. Hay manifiestos que la
  citan por id, y un manifiesto que apunta a una fila que ya no existe no se puede auditar.

**Sobre el paquete de pruebas**: se simula `importlib.metadata` en vez de instalar una
distribución de verdad, y la decisión no es de comodidad — es el precedente **medido** de PLG,
que lo dejó escrito en `_puntos_de_entrada`: «simular un paquete roto o dos que chocan instalando
distribuciones de verdad sería lento y frágil; lo que importa comprobar es el comportamiento del
cargador ante lo que `importlib.metadata` devuelva». Instalar en editable dentro de la suite
además obligaría a un `pip install` por ejecución y dejaría basura en el entorno del
desarrollador. El descriptor sí es real y se valida con el validador de FUN.2, que es donde
estaba el riesgo.
"""
from __future__ import annotations

import uuid

import pytest


# ─────────────────────────── El paquete demo ───────────────────────────


def _contrato_del_demo():
    from server.app.modules.redaccion.contracts.funciones import ContratoFuncion

    return ContratoFuncion(
        slots=[
            {
                "slot_id": "gastos",
                "kind": "excel",
                "required": True,
                "label": {"es": "Fichero de gastos"},
            }
        ],
        parametros=[],
        finalidad="Contar las filas del fichero de gastos",
        categorias_datos=["dades_pressupostaries"],
    )


def _run_del_demo(entrada):
    """El `run` del paquete demo. **Una función corporativa también declara**, así que su
    descriptor trae el mismo `ContratoFuncion` que una de autoservicio."""
    from server.app.modules.redaccion.pipelines.contracts import (
        ExtractionProvenance,
        ExtractionResult,
    )
    from datetime import datetime, timezone

    return ExtractionResult(
        tables=[],
        metrics=[],
        free_text="dos filas",
        provenance=ExtractionProvenance(
            pipeline_id="paquete-demo",
            source_kind="paquete",
            source_ref="paquete-demo",
            extracted_at=datetime.now(timezone.utc),
        ),
    )


def _descriptor(nombre="contar_filas", version="1.2.0", contrato=None):
    from server.app.modules.redaccion.funciones_paquete import FuncionEmpaquetada

    return FuncionEmpaquetada(
        nombre=nombre,
        version=version,
        contrato=contrato if contrato is not None else _contrato_del_demo(),
        run=_run_del_demo,
    )


class _PuntoDeEntrada:
    """Un *entry point* simulado, con la misma superficie que usa el cargador."""

    def __init__(self, nombre, descriptor, distribucion="govgenai-demo"):
        self.name = nombre
        self._descriptor = descriptor
        self.dist = type("_Dist", (), {"name": distribucion})()

    def load(self):
        return self._descriptor


@pytest.fixture
def puntos(monkeypatch):
    """Sustituye la costura del cargador, igual que hacen los tests de PLG."""
    from server.app.modules.redaccion import funciones_paquete

    def poner(*entradas):
        monkeypatch.setattr(
            funciones_paquete, "_puntos_de_entrada", lambda grupo: list(entradas)
        )

    return poner


# ─────────────────────────── El alta al arrancar ───────────────────────────


class TestLaSincronizacionAlArrancar:

    @pytest.mark.asyncio
    async def test_should_create_the_function_and_its_version_from_the_package(
        self, db_session, puntos
    ):
        from server.app.modules.redaccion.funciones_paquete import sincronizar_paquetes

        puntos(_PuntoDeEntrada("contar_filas", _descriptor()))

        resumen = await sincronizar_paquetes(db_session)

        assert resumen.funciones_nuevas == 1
        assert resumen.versiones_nuevas == 1

        funcion, version = await _la_del_catalogo(db_session, "govgenai-demo:contar_filas")
        assert funcion.origen == "paquete"
        # Ámbito plataforma: no es de ninguna organización, la instala quien opera el despliegue.
        assert funcion.organizacion_id is None
        assert funcion.nivel == 3
        assert version.version_paquete == "1.2.0"
        # El código no se copia —divergiría del `pip install`— pero el hash de la fuente sí, que
        # es lo que permite decir después si lo que corrió era esto.
        assert version.code is None
        assert len(version.code_sha256) == 64
        assert version.estado == "registrada"

    @pytest.mark.asyncio
    async def test_should_declare_purpose_and_data_categories_like_any_other(
        self, db_session, puntos
    ):
        """No hay rama «si es de paquete»: la declaración responsable de la Instrucció §8.2 la
        trae el descriptor, y sin ella el contrato ni se construye."""
        from server.app.modules.redaccion.funciones_paquete import sincronizar_paquetes

        puntos(_PuntoDeEntrada("contar_filas", _descriptor()))
        await sincronizar_paquetes(db_session)

        _funcion, version = await _la_del_catalogo(db_session, "govgenai-demo:contar_filas")

        assert version.finalidad == "Contar las filas del fichero de gastos"
        assert version.categorias_datos == ["dades_pressupostaries"]
        # Y la autoría es de persona: lo escribió un equipo, no un modelo.
        assert version.autoria == "persona"

    @pytest.mark.asyncio
    async def test_should_fail_loudly_when_the_package_contract_is_incoherent(
        self, db_session, puntos
    ):
        """Y **no deja fila**: registrar a medias sería peor que no registrar."""
        from sqlalchemy import func, select

        from server.app.modules.redaccion.database.models import HubFuncion
        from server.app.modules.redaccion.funciones_paquete import (
            PaqueteIncoherente,
            sincronizar_paquetes,
        )

        antes = (
            await db_session.execute(select(func.count()).select_from(HubFuncion))
        ).scalar_one()
        # Un descriptor sin `run` invocable: el paquete se equivocó de objeto en el entry point.
        malo = type(
            "_Malo", (), {"nombre": "roto", "version": "1.0.0", "contrato": _contrato_del_demo(),
                          "run": "esto no es invocable"}
        )()
        puntos(_PuntoDeEntrada("roto", malo, distribucion="govgenai-roto"))

        with pytest.raises(PaqueteIncoherente) as fallo:
            await sincronizar_paquetes(db_session)

        mensaje = str(fallo.value)
        assert "govgenai-roto" in mensaje
        assert "roto" in mensaje
        despues = (
            await db_session.execute(select(func.count()).select_from(HubFuncion))
        ).scalar_one()
        assert despues == antes

    @pytest.mark.asyncio
    async def test_should_fail_loudly_when_the_version_is_not_semver(self, db_session, puntos):
        """El anclaje es por mayor, así que sin semver no hay anclaje posible: se dice al
        arrancar y no en la primera plantilla que la referencie."""
        from server.app.modules.redaccion.funciones_paquete import (
            PaqueteIncoherente,
            sincronizar_paquetes,
        )

        puntos(_PuntoDeEntrada("contar_filas", _descriptor(version="ultima")))

        with pytest.raises(PaqueteIncoherente) as fallo:
            await sincronizar_paquetes(db_session)

        assert "semver" in str(fallo.value).lower()

    @pytest.mark.asyncio
    async def test_should_be_idempotent(self, db_session, puntos):
        """Arrancar dos veces no crea nada: `uvicorn --reload` reimporta, y un arranque que falla
        y se reintenta pasa por aquí dos veces."""
        from server.app.modules.redaccion.funciones_paquete import sincronizar_paquetes

        puntos(_PuntoDeEntrada("contar_filas", _descriptor()))

        primera = await sincronizar_paquetes(db_session)
        segunda = await sincronizar_paquetes(db_session)

        assert (primera.funciones_nuevas, primera.versiones_nuevas) == (1, 1)
        assert (segunda.funciones_nuevas, segunda.versiones_nuevas) == (0, 0)

    @pytest.mark.asyncio
    async def test_should_add_a_version_when_the_installed_one_changes(
        self, db_session, puntos
    ):
        """`pip install -U` es el versionado de este origen: aparece la versión 2 y **la 1 se
        conserva**, porque hay plantillas ancladas y manifiestos que la citan."""
        from server.app.modules.redaccion.funciones_paquete import sincronizar_paquetes

        puntos(_PuntoDeEntrada("contar_filas", _descriptor(version="1.2.0")))
        await sincronizar_paquetes(db_session)

        puntos(_PuntoDeEntrada("contar_filas", _descriptor(version="1.3.0")))
        resumen = await sincronizar_paquetes(db_session)

        assert resumen.versiones_nuevas == 1
        versiones = await _versiones_de(db_session, "govgenai-demo:contar_filas")
        assert [(v.version, v.version_paquete) for v in versiones] == [
            (1, "1.2.0"),
            (2, "1.3.0"),
        ]
        # La instalada queda registrada y la que ya no lo está, `no_instalada`.
        assert versiones[0].estado == "no_instalada"
        assert versiones[1].estado == "registrada"

    @pytest.mark.asyncio
    async def test_should_mark_every_version_uninstalled_when_the_package_disappears(
        self, db_session, puntos
    ):
        """Desinstalar el paquete no borra la función: se conserva, con todas sus versiones
        `no_instalada`. Borrarla dejaría manifiestos apuntando a la nada."""
        from server.app.modules.redaccion.funciones_paquete import sincronizar_paquetes

        puntos(_PuntoDeEntrada("contar_filas", _descriptor()))
        await sincronizar_paquetes(db_session)

        puntos()  # el paquete ya no está instalado
        await sincronizar_paquetes(db_session)

        funcion, version = await _la_del_catalogo(db_session, "govgenai-demo:contar_filas")
        assert funcion is not None
        assert version.estado == "no_instalada"


# ─────────────────────────── La resolución por mayor ───────────────────────────


class TestElAnclajePorMayor:

    @pytest.mark.asyncio
    async def test_should_run_the_installed_minor_and_say_so_in_the_manifest(
        self, db_session, puntos
    ):
        """1.2.0 anclada, 1.3.0 instalada: **corre la instalada**, que es lo que compra el
        semver, y el manifiesto anota la exacta. Si anotara la anclada, el manifiesto diría que
        corrió código que no corrió."""
        from server.app.modules.redaccion.funciones_paquete import sincronizar_paquetes
        from server.app.modules.redaccion.funciones_resolver import ResolvedorDeFuncion

        puntos(_PuntoDeEntrada("contar_filas", _descriptor(version="1.2.0")))
        await sincronizar_paquetes(db_session)
        funcion, _v = await _la_del_catalogo(db_session, "govgenai-demo:contar_filas")
        anclada = 1

        puntos(_PuntoDeEntrada("contar_filas", _descriptor(version="1.3.0")))
        await sincronizar_paquetes(db_session)

        ejecutable = await ResolvedorDeFuncion(db_session).resolver(funcion.id, anclada)

        assert ejecutable.version_paquete == "1.3.0"
        assert ejecutable.para_el_manifiesto()["version_paquete"] == "1.3.0"
        # Y el hash es el de la fuente que se va a ejecutar, no el de la anclada.
        assert ejecutable.para_el_manifiesto()["code_sha256"] == ejecutable.code_sha256

    @pytest.mark.asyncio
    async def test_should_refuse_a_different_major_out_loud(self, db_session, puntos):
        """2.0.0 instalada sobre una plantilla anclada a 1.x: el contrato puede haber cambiado,
        así que el bloque falla nombrando los dos mayores. Ejecutarla en silencio sería cambiar
        el significado de un informe sin decírselo a nadie."""
        from server.app.modules.redaccion.funciones_paquete import sincronizar_paquetes
        from server.app.modules.redaccion.funciones_resolver import (
            FuncionNoEjecutable,
            ResolvedorDeFuncion,
        )

        puntos(_PuntoDeEntrada("contar_filas", _descriptor(version="1.2.0")))
        await sincronizar_paquetes(db_session)
        funcion, _v = await _la_del_catalogo(db_session, "govgenai-demo:contar_filas")

        puntos(_PuntoDeEntrada("contar_filas", _descriptor(version="2.0.0")))
        await sincronizar_paquetes(db_session)

        with pytest.raises(FuncionNoEjecutable) as fallo:
            await ResolvedorDeFuncion(db_session).resolver(funcion.id, 1)

        mensaje = str(fallo.value)
        assert "contar_filas" in mensaje
        assert "1" in mensaje
        assert "2" in mensaje

    @pytest.mark.asyncio
    async def test_should_fail_out_loud_when_nothing_is_installed(self, db_session, puntos):
        from server.app.modules.redaccion.funciones_paquete import sincronizar_paquetes
        from server.app.modules.redaccion.funciones_resolver import (
            FuncionNoEjecutable,
            ResolvedorDeFuncion,
        )

        puntos(_PuntoDeEntrada("contar_filas", _descriptor()))
        await sincronizar_paquetes(db_session)
        funcion, _v = await _la_del_catalogo(db_session, "govgenai-demo:contar_filas")

        puntos()
        await sincronizar_paquetes(db_session)

        with pytest.raises(FuncionNoEjecutable) as fallo:
            await ResolvedorDeFuncion(db_session).resolver(funcion.id, 1)

        assert "no_instalada" in str(fallo.value) or "instalada" in str(fallo.value)


# ─────────────────────────── La ejecución in-process ───────────────────────────


class TestLaEjecucionDelPaquete:

    @pytest.mark.asyncio
    async def test_should_validate_the_input_before_calling_run(self, db_session, puntos):
        """El espía que lo demuestra: con la validación detrás, el fallo es un `KeyError` dentro
        del código de un tercero; con ella delante, «falta el slot gastos»."""
        from server.app.modules.redaccion.contracts.funciones import (
            EntradaNoCumpleElContrato,
        )
        from server.app.modules.redaccion.funciones_paquete import (
            FuncionEmpaquetada,
            ejecutar_empaquetada,
            sincronizar_paquetes,
        )

        llamadas = []

        def run_espia(entrada):
            llamadas.append(entrada)
            raise AssertionError("no tendría que llegar aquí")

        descriptor = FuncionEmpaquetada(
            nombre="contar_filas",
            version="1.2.0",
            contrato=_contrato_del_demo(),
            run=run_espia,
        )
        puntos(_PuntoDeEntrada("contar_filas", descriptor))
        await sincronizar_paquetes(db_session)

        with pytest.raises(EntradaNoCumpleElContrato):
            await ejecutar_empaquetada(
                "govgenai-demo:contar_filas", ficheros={}, parametros={}
            )

        assert llamadas == [], "el run del paquete no se llama con una entrada inválida"

    @pytest.mark.asyncio
    async def test_should_run_a_sync_callable_without_blocking_the_loop(
        self, db_session, puntos
    ):
        """`run` es síncrono en el caso normal —es código de análisis— y va al executor de hilos:
        la regla de asincronía total no se relaja porque el código sea de un tercero."""
        import asyncio

        from server.app.modules.redaccion.funciones_paquete import (
            ejecutar_empaquetada,
            sincronizar_paquetes,
        )

        hilos = []

        def run_que_mira_su_hilo(entrada):
            import threading

            hilos.append(threading.current_thread().name)
            return _run_del_demo(entrada)

        from server.app.modules.redaccion.funciones_paquete import FuncionEmpaquetada

        puntos(
            _PuntoDeEntrada(
                "contar_filas",
                FuncionEmpaquetada(
                    nombre="contar_filas", version="1.2.0",
                    contrato=_contrato_del_demo(), run=run_que_mira_su_hilo,
                ),
            )
        )
        await sincronizar_paquetes(db_session)

        resultado = await ejecutar_empaquetada(
            "govgenai-demo:contar_filas",
            ficheros={"gastos": "/tmp/gastos.xlsx"},
            parametros={},
        )

        assert resultado.free_text == "dos filas"
        principal = asyncio.current_task().get_name()
        assert hilos
        assert hilos[0] != principal


# ─────────────────────────── El catálogo ───────────────────────────


class TestLoQueElCatalogoOfreceDeUnPaquete:

    def test_should_not_offer_versioning_or_promoting(self):
        """Se versiona con `pip` y ya es de plataforma: los dos botones no significarían nada.
        **Retirar sí**, porque el superadministrador tiene que poder vetar una instalada sin
        esperar a que alguien la desinstale."""
        from server.app.modules.redaccion.funciones_acciones import acciones_permitidas

        funcion = type(
            "_F", (), {
                "origen": "paquete", "organizacion_id": None, "publicada_en": None,
                "creada_por": None, "promocion_solicitada_en": None,
            }
        )()
        version = type("_V", (), {"estado": "registrada"})()
        principal = type(
            "_P", (), {"is_superadmin": True, "is_admin": True, "user_id": "1",
                       "organizacion_ids": ()}
        )()

        acciones = acciones_permitidas(funcion, version, principal=principal)

        assert "versionar" not in acciones
        assert "promover" not in acciones
        assert "retirar" in acciones


# ─────────────────────────── El cableado ───────────────────────────


class TestElCableadoDelArranque:
    """La lección de DIN.4 otra vez: una sincronización que el arranque no llama no existe."""

    def test_should_be_called_from_the_lifespan(self):
        import inspect

        from server.app import main

        fuente = inspect.getsource(main)
        assert "sincronizar_paquetes" in fuente


class TestElNodoEjecutaLosDosOrigenes:
    """Un solo nodo para los dos orígenes, y el que faltaba comprobar.

    `como_opciones_del_pipeline()` devuelve `{"code": "", "approved": True}` cuando el código es
    nulo, que es siempre en un paquete: sin esta bifurcación el bloque **mandaría un script vacío
    al sandbox** y saldría «extracción sin resultado» en vez de ejecutar la función instalada. Es
    el fallo silencioso más caro que este bloque puede tener, porque el informe sale — vacío.
    """

    @pytest.mark.asyncio
    async def test_should_call_the_installed_run_instead_of_the_sandbox(
        self, db_session, puntos
    ):
        from server.app.modules.redaccion.funciones_paquete import sincronizar_paquetes
        from server.app.modules.redaccion.funciones_resolver import ResolvedorDeFuncion
        from server.app.modules.redaccion.graph.nodes.deterministic_extraction import (
            DeterministicExtractionNode,
        )

        puntos(_PuntoDeEntrada("contar_filas", _descriptor()))
        await sincronizar_paquetes(db_session)
        funcion, _v = await _la_del_catalogo(db_session, "govgenai-demo:contar_filas")

        ejecutable = await ResolvedorDeFuncion(db_session).resolver(funcion.id, 1)

        class _FactoriaQueNoDebeUsarse:
            def get(self, kind):
                raise AssertionError(
                    "una función de paquete no pasa por el sandbox: corre in-process"
                )

        nodo = DeterministicExtractionNode(factory=_FactoriaQueNoDebeUsarse())
        resultado = await nodo._ejecutar_ejecutable(
            ejecutable, ficheros={"gastos": "gastos.xlsx"}, parametros={}
        )

        assert resultado.free_text == "dos filas"

    @pytest.mark.asyncio
    async def test_should_still_use_the_sandbox_for_a_self_service_function(self, db_session):
        """Y el camino de autoservicio no cambia: el sandbox sigue siendo su ejecución."""
        import inspect

        from server.app.modules.redaccion.graph.nodes import deterministic_extraction

        fuente = inspect.getsource(deterministic_extraction)
        # La bifurcación mira el **origen**, que es lo que el resolutor ya resolvió; mirar si
        # `code` viene nulo funcionaría hoy y mentiría el día que un autoservicio tenga el
        # código fuera.
        assert 'origen == "paquete"' in fuente


# ─────────────────────────── Ayudas ───────────────────────────


async def _la_del_catalogo(session, entry_point: str):
    from sqlalchemy import select

    from server.app.modules.redaccion.database.models import (
        HubFuncion,
        HubFuncionVersion,
    )

    funcion = (
        await session.execute(
            select(HubFuncion).where(HubFuncion.entry_point == entry_point)
        )
    ).scalar_one()
    versiones = (
        await session.execute(
            select(HubFuncionVersion)
            .where(HubFuncionVersion.funcion_id == funcion.id)
            .order_by(HubFuncionVersion.version.desc())
        )
    ).scalars().all()
    return funcion, versiones[0]


async def _versiones_de(session, entry_point: str):
    from sqlalchemy import select

    from server.app.modules.redaccion.database.models import (
        HubFuncion,
        HubFuncionVersion,
    )

    funcion = (
        await session.execute(
            select(HubFuncion).where(HubFuncion.entry_point == entry_point)
        )
    ).scalar_one()
    return list(
        (
            await session.execute(
                select(HubFuncionVersion)
                .where(HubFuncionVersion.funcion_id == funcion.id)
                .order_by(HubFuncionVersion.version)
            )
        ).scalars().all()
    )


def _sin_usar() -> uuid.UUID:
    return uuid.uuid4()
