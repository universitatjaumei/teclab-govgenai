"""FUN.1 — el catálogo de funciones: la entidad, sus versiones y sus dos guardas.

Hoy el código de un script aprobado **se incrusta copiado** en el bloque de cada plantilla
(`options={"code": …, "approved": True}`). Dos plantillas que necesitan la misma extracción son
dos propuestas, dos aprobaciones y dos copias; un error en un script usado por N plantillas se
arregla N veces. `HubScriptProposal` es una cola de aprobación con `target_template_id`, no un
catálogo.

Este prompt pone las dos tablas. Lo que fijan estos tests es lo que los seis prompts siguientes
dan por hecho:

* **Una versión registrada es inmutable.** Corregir es publicar otra versión. Sin esto, «arreglar
  una vez» sería «cambiar en silencio informes ya aprobados» y el `RunManifest` dejaría de ser
  reproducible.
* **Cada origen tiene su forma, y la capa de servicio la hace cumplir.** Autoservicio exige
  código, finalidad y quién declara; paquete exige `entry_point` y semver y **prohíbe** código,
  porque el código de un paquete no vive aquí.
* **El nivel de la Instrucció 02/2026 se deriva, no se guarda.** Nivel 2 es «de mi organización y
  sin publicar»; nivel 3 es «publicada» o «de paquete». Una columna `nivel` sería un tercer sitio
  donde vive el mismo hecho, y podría discrepar de los otros dos.
* **Suspender exige motivo.** Una versión suspendida hace fallar en alto al bloque que la
  referencia (FUN.3), y ese fallo tiene que poder decir por qué.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError


# ──────────────────────────── Lo que declara el modelo ────────────────────────────


class TestLoQueDeclaraElModelo:

    def test_should_declare_its_scope_in_both_tables(self):
        """**Desviación documentada respecto al prompt.** FUN.1 pedía `__ambito__` «porque el
        guardarraíl de MT.1 lo exige», y ese guardarraíl recorre sólo `HubConfigBase`. Estas dos
        tablas son operacionales —el código y la declaración los escribe una persona de la
        organización, que es el criterio con el que `hub_lexicon_pairs` acabó en el lado edge—,
        así que el ámbito se declara igual (documenta la cascada) y lo comprueba este test, que
        es el que falta.
        """
        from server.app.core.ambito import Ambito, ambito_de
        from server.app.modules.redaccion.database.models import (
            HubFuncion,
            HubFuncionVersion,
        )

        assert ambito_de(HubFuncion).ambito is Ambito.HEREDABLE
        derivada = ambito_de(HubFuncionVersion)
        assert derivada.ambito is Ambito.DERIVADA
        # «Derivada» a secas no le sirve a nadie que lea el inventario: dice por dónde.
        assert derivada.via == "funcion_id"

    def test_should_live_on_the_edge_side(self):
        """El código de una función de autoservicio es texto escrito por una persona de la
        organización. Ése es el criterio que mandó `hub_lexicon_pairs` al lado operacional, y no
        «es configuración»."""
        from server.app.modules.agents_hub.database.base import HubOperationalBase
        from server.app.modules.redaccion.database.models import (
            HubFuncion,
            HubFuncionVersion,
        )

        assert issubclass(HubFuncion, HubOperationalBase)
        assert issubclass(HubFuncionVersion, HubOperationalBase)

    def test_should_keep_the_packaged_entry_point_unique(self):
        from server.app.modules.redaccion.database.models import HubFuncion

        columna = HubFuncion.__table__.c.entry_point
        assert columna.nullable is True
        assert columna.unique is True

    def test_should_not_navigate_across_bases(self):
        """Sin `relationship()` cross-base, como siempre: las claves ajenas se quedan en el DDL y
        la navegación se hace por consulta explícita."""
        from server.app.modules.redaccion.database.models import (
            HubFuncion,
            HubFuncionVersion,
        )

        for modelo in (HubFuncion, HubFuncionVersion):
            assert not list(modelo.__mapper__.relationships)


# ──────────────────────────── El nivel se deriva ────────────────────────────


class TestElNivelSeDeriva:
    """Nivel 2 y nivel 3 de la Instrucció 02/2026, calculados y no guardados."""

    @staticmethod
    def _funcion(**kw):
        from server.app.modules.redaccion.database.models import HubFuncion

        datos = {
            "nombre": "Extraer tabla del ERP",
            "descripcion": "",
            "organizacion_id": uuid.uuid4(),
            "origen": "autoservicio",
        }
        datos.update(kw)
        return HubFuncion(**datos)

    def test_should_be_level_two_while_it_belongs_to_one_organizacion(self):
        assert self._funcion().nivel == 2

    def test_should_be_level_three_once_published(self):
        from datetime import datetime, timezone

        assert self._funcion(publicada_en=datetime.now(timezone.utc)).nivel == 3

    def test_should_be_level_three_when_it_comes_from_a_package(self):
        """Una función empaquetada es desarrollo corporativo: nace en nivel 3 porque la instala
        quien opera el despliegue, no una organización."""
        funcion = self._funcion(
            origen="paquete",
            organizacion_id=None,
            entry_point="paquete_demo:extraer",
        )

        assert funcion.nivel == 3


# ──────────────────────────── Las guardas del servicio ────────────────────────────


class TestLaFormaDeCadaOrigen:
    """La coherencia por origen vive en la capa de servicio, no en un `CheckConstraint`: son
    cuatro reglas cruzadas entre dos tablas y el mensaje tiene que decir qué falta."""

    @staticmethod
    def _registrar(**kw):
        from server.app.modules.redaccion.funciones_service import (
            datos_de_version_coherentes,
        )

        datos = {
            "origen": "autoservicio",
            "code": "result = {'tables': [], 'metrics': {}, 'free_text': ''}",
            "finalidad": "Extraer la tabla de gastos del ERP",
            "declarada_por": uuid.uuid4(),
            "categorias_datos": ["datos_economicos_y_financieros"],
            "version_paquete": None,
            "entry_point": None,
        }
        datos.update(kw)
        return datos_de_version_coherentes(**datos)

    def test_should_accept_a_well_formed_self_service_version(self):
        self._registrar()  # no levanta

    @pytest.mark.parametrize(
        ("falta", "trozo"),
        [("code", "código"), ("finalidad", "finalidad"), ("declarada_por", "declara")],
    )
    def test_should_refuse_a_self_service_version_that_is_missing_its_papers(
        self, falta, trozo
    ):
        """La declaración responsable no es opcional: es lo que la Instrucció exige registrar
        **antes** de compartir (§8.2), y es lo que la revisión posterior lee."""
        from server.app.modules.redaccion.funciones_service import FuncionIncoherente

        with pytest.raises(FuncionIncoherente) as fallo:
            self._registrar(**{falta: None})

        assert trozo in str(fallo.value).lower()

    def test_should_refuse_a_self_service_version_with_a_package_version(self):
        from server.app.modules.redaccion.funciones_service import FuncionIncoherente

        with pytest.raises(FuncionIncoherente):
            self._registrar(version_paquete="1.2.0")

    def test_should_accept_a_well_formed_packaged_version(self):
        self._registrar(
            origen="paquete",
            code=None,
            finalidad="Explotar el ERP común",
            declarada_por=None,
            version_paquete="1.2.0",
            entry_point="paquete_demo:extraer",
        )

    def test_should_refuse_a_packaged_version_that_carries_code(self):
        """El código de un paquete vive en el paquete. Guardarlo aquí sería una copia que
        divergiría del `pip install` sin que nada avisara."""
        from server.app.modules.redaccion.funciones_service import FuncionIncoherente

        with pytest.raises(FuncionIncoherente) as fallo:
            self._registrar(
                origen="paquete",
                version_paquete="1.2.0",
                entry_point="paquete_demo:extraer",
                declarada_por=None,
            )

        assert "código" in str(fallo.value).lower()

    @pytest.mark.parametrize("falta", ["version_paquete", "entry_point"])
    def test_should_refuse_a_packaged_version_without_its_identity(self, falta):
        from server.app.modules.redaccion.funciones_service import FuncionIncoherente

        datos = {
            "origen": "paquete",
            "code": None,
            "declarada_por": None,
            "version_paquete": "1.2.0",
            "entry_point": "paquete_demo:extraer",
        }
        datos[falta] = None

        with pytest.raises(FuncionIncoherente):
            self._registrar(**datos)


class TestLaGuardaDeInmutabilidad:
    """Una versión registrada no se edita jamás — misma razón que el registro de auditoría."""

    @staticmethod
    def _version(estado: str):
        from server.app.modules.redaccion.database.models import HubFuncionVersion

        return HubFuncionVersion(
            id=uuid.uuid4(),
            funcion_id=uuid.uuid4(),
            version=1,
            code="result = {}",
            contrato_entrada={},
            contrato_salida={},
            code_sha256="0" * 64,
            estado=estado,
            finalidad="Extraer",
            categorias_datos=[],
        )

    @pytest.mark.parametrize("estado", ["registrada", "suspendida", "retirada"])
    @pytest.mark.parametrize("campo", ["code", "contrato_entrada", "finalidad"])
    def test_should_refuse_to_edit_a_version_that_is_no_longer_a_draft(self, estado, campo):
        from server.app.modules.redaccion.funciones_service import (
            VersionInmutable,
            asegurar_editable,
        )

        with pytest.raises(VersionInmutable) as fallo:
            asegurar_editable(self._version(estado), {campo: "otra cosa"})

        assert "versión nueva" in str(fallo.value)

    def test_should_let_a_draft_be_edited(self):
        from server.app.modules.redaccion.funciones_service import asegurar_editable

        asegurar_editable(self._version("draft"), {"code": "result = {}"})  # no levanta

    def test_should_let_a_registered_version_change_state_and_review_fields(self):
        """Cambiar de estado y anotar la revisión **sí** se admite: son de otra persona y de otro
        momento, y es justo el circuito de la Instrucció §8.4."""
        from server.app.modules.redaccion.funciones_service import asegurar_editable

        asegurar_editable(
            self._version("registrada"),
            {
                "estado": "suspendida",
                "motivo_suspension": "usa una ruta absoluta",
                "revision_resultado": "correcciones",
                "revisada_por": uuid.uuid4(),
            },
        )

    def test_should_refuse_to_suspend_without_a_reason(self):
        """El bloque anclado a una versión suspendida falla en alto **con el motivo** (FUN.3):
        sin motivo, ese fallo no podría explicarse."""
        from server.app.modules.redaccion.funciones_service import (
            FuncionIncoherente,
            asegurar_editable,
        )

        with pytest.raises(FuncionIncoherente) as fallo:
            asegurar_editable(self._version("registrada"), {"estado": "suspendida"})

        assert "motivo" in str(fallo.value).lower()


class TestElHashSeCalculaAlEscribir:

    def test_should_hash_the_code_that_will_run(self):
        """`code_sha256` es lo que el `RunManifest` registra para poder decir qué corrió. Se
        calcula al escribir, no lo aporta quien llama."""
        from server.app.modules.redaccion.funciones_service import sha256_del_codigo

        codigo = "result = {'tables': [], 'metrics': {}, 'free_text': 'hola'}"
        import hashlib

        assert sha256_del_codigo(codigo) == hashlib.sha256(codigo.encode()).hexdigest()
        assert len(sha256_del_codigo(codigo)) == 64


# ──────────────────────────── Contra la base ────────────────────────────


class TestContraLaBase:

    @pytest.mark.asyncio
    async def test_should_refuse_two_versions_with_the_same_ordinal(self, db_session):
        from server.app.modules.redaccion.database.models import (
            HubFuncion,
            HubFuncionVersion,
        )

        funcion = HubFuncion(
            nombre="Extraer tabla del ERP",
            descripcion="",
            organizacion_id=uuid.uuid4(),
            origen="autoservicio",
        )
        db_session.add(funcion)
        await db_session.flush()
        for _ in range(2):
            db_session.add(
                HubFuncionVersion(
                    funcion_id=funcion.id,
                    version=1,
                    code="result = {}",
                    contrato_entrada={},
                    contrato_salida={},
                    code_sha256="0" * 64,
                    estado="registrada",
                    finalidad="Extraer",
                    categorias_datos=[],
                )
            )

        with pytest.raises(IntegrityError):
            await db_session.flush()

    @pytest.mark.asyncio
    async def test_should_round_trip_the_contract_and_the_declaration(self, db_session):
        from server.app.modules.redaccion.database.models import (
            HubFuncion,
            HubFuncionVersion,
        )

        funcion = HubFuncion(
            nombre="Extraer gastos",
            descripcion="",
            organizacion_id=uuid.uuid4(),
            origen="autoservicio",
        )
        db_session.add(funcion)
        await db_session.flush()
        entrada = {
            "slots": [{"nombre": "datos", "kind": "excel", "obligatorio": True}],
            "parametros": [{"name": "umbral", "type": "number", "label": "Umbral"}],
        }
        version = HubFuncionVersion(
            funcion_id=funcion.id,
            version=1,
            code="result = {}",
            contrato_entrada=entrada,
            contrato_salida={"kind": "ExtractionResult"},
            code_sha256="0" * 64,
            estado="registrada",
            finalidad="Extraer la tabla de gastos",
            categorias_datos=["datos_economicos_y_financieros", "sin_datos_personales"],
            declarada_por=uuid.uuid4(),
        )
        db_session.add(version)
        await db_session.flush()
        db_session.expunge_all()

        leida = await db_session.get(HubFuncionVersion, version.id)
        assert leida.contrato_entrada == entrada
        assert leida.categorias_datos == [
            "datos_economicos_y_financieros",
            "sin_datos_personales",
        ]
        assert leida.finalidad == "Extraer la tabla de gastos"

    @pytest.mark.asyncio
    async def test_should_delete_the_versions_with_their_function(self, db_session):
        from sqlalchemy import func, select

        from server.app.modules.redaccion.database.models import (
            HubFuncion,
            HubFuncionVersion,
        )

        funcion = HubFuncion(
            nombre="Con versiones",
            descripcion="",
            organizacion_id=uuid.uuid4(),
            origen="autoservicio",
        )
        db_session.add(funcion)
        await db_session.flush()
        db_session.add(
            HubFuncionVersion(
                funcion_id=funcion.id,
                version=1,
                code="result = {}",
                contrato_entrada={},
                contrato_salida={},
                code_sha256="0" * 64,
                estado="registrada",
                finalidad="x",
                categorias_datos=[],
            )
        )
        await db_session.flush()

        await db_session.delete(funcion)
        await db_session.flush()

        quedan = (
            await db_session.execute(
                select(func.count())
                .select_from(HubFuncionVersion)
                .where(HubFuncionVersion.funcion_id == funcion.id)
            )
        ).scalar_one()
        assert quedan == 0


class TestElListadoAcotado:
    """Lo que ve una organización: las suyas y las publicadas. Nunca las no publicadas de otra."""

    @pytest.mark.asyncio
    async def test_should_scope_the_catalogue_to_the_organizacion_and_the_published(
        self, db_session
    ):
        from server.app.modules.redaccion.database.models import HubFuncion
        from server.app.modules.redaccion.funciones_service import (
            consulta_de_catalogo,
        )
        from datetime import datetime, timezone

        mia = uuid.uuid4()
        ajena = uuid.uuid4()
        propia = HubFuncion(
            nombre="Mia sin publicar", descripcion="", organizacion_id=mia,
            origen="autoservicio",
        )
        de_otra = HubFuncion(
            nombre="Ajena sin publicar", descripcion="", organizacion_id=ajena,
            origen="autoservicio",
        )
        publicada_por_otra = HubFuncion(
            nombre="Ajena publicada", descripcion="", organizacion_id=ajena,
            origen="autoservicio", publicada_en=datetime.now(timezone.utc),
        )
        de_paquete = HubFuncion(
            nombre="De paquete", descripcion="", organizacion_id=None,
            origen="paquete", entry_point="demo:extraer",
            publicada_en=datetime.now(timezone.utc),
        )
        db_session.add_all([propia, de_otra, publicada_por_otra, de_paquete])
        await db_session.flush()

        filas = (
            await db_session.execute(consulta_de_catalogo(organizacion_id=mia))
        ).scalars().all()
        nombres = {f.nombre for f in filas}

        assert "Mia sin publicar" in nombres
        assert "Ajena publicada" in nombres
        assert "De paquete" in nombres
        assert "Ajena sin publicar" not in nombres
