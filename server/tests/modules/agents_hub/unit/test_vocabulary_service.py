"""Tests TDD — Vocabulario controlado como dato versionado (Prompt ING.0.1).

Los ámbitos y las submaterias son DATO (filas en tabla), no código: el vocabulario
está pendiente de validación por Secretaría General y tiene que seguir siendo
revisable. Los EJES sí son estructura (StrEnum), porque añadir un eje exige código
que lo consuma.

Fakes en memoria: sin BD ni CSV real salvo en los tests del parser, que usan tmp_path.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest


# ───────────────────────── Helpers / fakes ─────────────────────────


def _term(codi: str, **kw):
    from server.app.modules.agents_hub.services.vocabulary_service import (
        VocabularyTermDTO,
    )

    defaults = dict(
        axis="submateria",
        codi=codi,
        nom_primari=codi.replace("-", " ").capitalize(),
        nom_secundari=None,
        parent_codi="administracio",
        descripcio_router=None,
        ordre=0,
        vigent=True,
        substituit_per_codi=None,
    )
    defaults.update(kw)
    return VocabularyTermDTO(**defaults)


def _ambit(codi: str, **kw):
    return _term(codi, axis="ambit", parent_codi=None, **kw)


class _FakeVocabularySource:
    """Implementa VocabularySource sin BD."""

    def __init__(self, terms_by_org: dict[uuid.UUID, list] | None = None) -> None:
        self._terms_by_org = terms_by_org or {}
        self.calls: list[tuple[str, uuid.UUID]] = []

    async def list_vocabulary(self, axis: str, organizacion_id: uuid.UUID) -> list:
        self.calls.append((axis, organizacion_id))
        return [t for t in self._terms_by_org.get(organizacion_id, []) if t.axis == axis]


class _FakeVocabularyStore:
    """Implementa VocabularyStore registrando las escrituras."""

    def __init__(self, existing: list | None = None) -> None:
        self.terms = list(existing or [])
        self.created: list = []
        self.updated: list = []

    async def fetch(self, axis: str, organizacion_id: uuid.UUID) -> list:
        return [t for t in self.terms if t.axis == axis]

    async def create(self, term, organizacion_id: uuid.UUID) -> None:
        self.created.append(term)
        self.terms.append(term)

    async def update(self, term, organizacion_id: uuid.UUID) -> None:
        self.updated.append(term)
        self.terms = [t for t in self.terms if not (t.axis == term.axis and t.codi == term.codi)]
        self.terms.append(term)

    @property
    def writes(self) -> int:
        return len(self.created) + len(self.updated)


def _service(terms: list, organizacion_id: uuid.UUID | None = None):
    from server.app.modules.agents_hub.services.vocabulary_service import (
        VocabularyService,
    )

    org_id = organizacion_id or uuid.uuid4()
    source = _FakeVocabularySource({org_id: terms})
    return VocabularyService(source=source, organizacion_id=org_id), source, org_id


# ───────────────────────── Ejes: estructura, no dato ─────────────────────────


class TestVocabularyAxis:

    def test_axes_are_a_str_enum_in_code(self):
        from server.app.modules.agents_hub.services.vocabulary_service import (
            VocabularyAxis,
        )

        assert VocabularyAxis.AMBIT == "ambit"
        assert VocabularyAxis.SUBMATERIA == "submateria"
        assert {"rang", "colectiu", "tipus"} <= {a.value for a in VocabularyAxis}


# ───────────────────────── validate ─────────────────────────


class TestValidate:

    @pytest.mark.asyncio
    async def test_should_reject_unknown_submateria_codes(self):
        svc, _, _ = _service([_term("execucio-de-la-despesa")])
        unknown = await svc.validate("submateria", ["execucio-de-la-despesa", "inventada"])
        assert unknown == ["inventada"]

    @pytest.mark.asyncio
    async def test_should_accept_codes_present_and_vigent(self):
        svc, _, _ = _service([_term("dietes"), _term("convenis")])
        assert await svc.validate("submateria", ["dietes", "convenis"]) == []

    @pytest.mark.asyncio
    async def test_should_reject_code_marked_not_vigent(self):
        svc, _, _ = _service([_term("retribucions", vigent=False)])
        assert await svc.validate("submateria", ["retribucions"]) == ["retribucions"]

    @pytest.mark.asyncio
    async def test_should_list_all_unknown_codes_not_just_the_first(self):
        svc, _, _ = _service([_term("dietes")])
        unknown = await svc.validate("submateria", ["nope1", "dietes", "nope2"])
        assert unknown == ["nope1", "nope2"]

    @pytest.mark.asyncio
    async def test_should_accept_empty_code_list(self):
        svc, _, _ = _service([_term("dietes")])
        assert await svc.validate("submateria", []) == []


# ───────────────────────── resolve (renombrados y fusiones) ─────────────────────────


class TestResolve:

    @pytest.mark.asyncio
    async def test_should_resolve_renamed_code_to_its_replacement(self):
        svc, _, _ = _service([
            _term("rrhh-ptgas", vigent=False, substituit_per_codi="rrhh-ptgas-condicions"),
            _term("rrhh-ptgas-condicions"),
        ])
        assert await svc.resolve("submateria", "rrhh-ptgas") == "rrhh-ptgas-condicions"

    @pytest.mark.asyncio
    async def test_should_follow_a_chain_of_substitutions(self):
        svc, _, _ = _service([
            _term("a", vigent=False, substituit_per_codi="b"),
            _term("b", vigent=False, substituit_per_codi="c"),
            _term("c"),
        ])
        assert await svc.resolve("submateria", "a") == "c"

    @pytest.mark.asyncio
    async def test_should_return_the_code_itself_when_vigent(self):
        svc, _, _ = _service([_term("dietes")])
        assert await svc.resolve("submateria", "dietes") == "dietes"

    @pytest.mark.asyncio
    async def test_should_raise_on_substitution_cycle(self):
        from server.app.modules.agents_hub.services.vocabulary_service import (
            VocabularyCycleError,
        )

        svc, _, _ = _service([
            _term("a", vigent=False, substituit_per_codi="b"),
            _term("b", vigent=False, substituit_per_codi="a"),
        ])
        with pytest.raises(VocabularyCycleError):
            await svc.resolve("submateria", "a")

    @pytest.mark.asyncio
    async def test_should_raise_on_unknown_code(self):
        from server.app.modules.agents_hub.services.vocabulary_service import (
            VocabularyTermNotFoundError,
        )

        svc, _, _ = _service([_term("dietes")])
        with pytest.raises(VocabularyTermNotFoundError):
            await svc.resolve("submateria", "inventada")

    @pytest.mark.asyncio
    async def test_should_raise_when_substitution_points_nowhere(self):
        from server.app.modules.agents_hub.services.vocabulary_service import (
            VocabularyTermNotFoundError,
        )

        svc, _, _ = _service([_term("a", vigent=False, substituit_per_codi="fantasma")])
        with pytest.raises(VocabularyTermNotFoundError):
            await svc.resolve("submateria", "a")


# ───────────────────────── Índice del Nivel 0 ─────────────────────────


class TestRouterIndex:

    @pytest.mark.asyncio
    async def test_should_build_router_index_grouped_by_ambit(self):
        svc, _, _ = _service([
            _ambit("administracio", nom_primari="Administració"),
            _ambit("academica", nom_primari="Acadèmica"),
            _term("dietes", parent_codi="administracio", nom_primari="Dietes"),
            _term("avaluacio", parent_codi="academica", nom_primari="Avaluació"),
        ])
        index = await svc.build_router_index()

        assert "Administració" in index
        assert "Acadèmica" in index
        # cada submateria aparece bajo su ámbito
        pos_admin = index.index("Administració")
        pos_dietes = index.index("dietes")
        pos_acad = index.index("Acadèmica")
        pos_avaluacio = index.index("avaluacio")
        assert pos_admin < pos_dietes
        assert pos_acad < pos_avaluacio

    @pytest.mark.asyncio
    async def test_should_include_router_description_in_index(self):
        svc, _, _ = _service([
            _ambit("administracio"),
            _term("dietes", descripcio_router="Imports i justificació de dietes"),
        ])
        index = await svc.build_router_index()
        assert "Imports i justificació de dietes" in index

    @pytest.mark.asyncio
    async def test_should_exclude_non_vigent_terms_from_index(self):
        svc, _, _ = _service([
            _ambit("administracio"),
            _term("dietes"),
            _term("obsoleta", vigent=False, substituit_per_codi="dietes"),
        ])
        index = await svc.build_router_index()
        assert "dietes" in index
        assert "obsoleta" not in index

    @pytest.mark.asyncio
    async def test_should_order_submaterias_by_ordre_then_codi(self):
        svc, _, _ = _service([
            _ambit("administracio"),
            _term("zeta", ordre=1),
            _term("alfa", ordre=2),
        ])
        index = await svc.build_router_index()
        assert index.index("zeta") < index.index("alfa")

    @pytest.mark.asyncio
    async def test_should_omit_ambit_without_vigent_submaterias(self):
        svc, _, _ = _service([
            _ambit("administracio", nom_primari="Administració"),
            _ambit("transversal", nom_primari="Transversal"),
            _term("dietes", parent_codi="administracio"),
        ])
        index = await svc.build_router_index()
        assert "Transversal" not in index


# ───────────────────────── Alcance por organización ─────────────────────────


class TestOrganizationScope:

    @pytest.mark.asyncio
    async def test_should_scope_vocabulary_by_organizacion(self):
        from server.app.modules.agents_hub.services.vocabulary_service import (
            VocabularyService,
        )

        org_a, org_b = uuid.uuid4(), uuid.uuid4()
        source = _FakeVocabularySource({
            org_a: [_term("dietes")],
            org_b: [_term("altra-cosa")],
        })
        svc_a = VocabularyService(source=source, organizacion_id=org_a)
        svc_b = VocabularyService(source=source, organizacion_id=org_b)

        assert await svc_a.validate("submateria", ["dietes"]) == []
        assert await svc_b.validate("submateria", ["dietes"]) == ["dietes"]

    @pytest.mark.asyncio
    async def test_should_always_query_its_own_organizacion(self):
        org_id = uuid.uuid4()
        svc, source, _ = _service([_term("dietes")], organizacion_id=org_id)
        await svc.validate("submateria", ["dietes"])
        assert all(called_org == org_id for _, called_org in source.calls)


# ───────────────────────── Frontera edge/cloud ─────────────────────────


class TestConfigProviderBoundary:

    @pytest.mark.asyncio
    async def test_should_expose_vocabulary_through_config_provider(self):
        """El protocolo ConfigProvider es la vía de acceso desde edge."""
        from server.app.modules.agents_hub.services.config_provider import (
            ConfigProvider,
        )

        assert hasattr(ConfigProvider, "list_vocabulary")

    def test_local_config_provider_implements_list_vocabulary(self):
        from server.app.modules.agents_hub.services.config_provider import (
            LocalConfigProvider,
        )

        assert callable(getattr(LocalConfigProvider, "list_vocabulary", None))

    def test_vocabulary_service_module_does_not_import_orm_models(self):
        """El servicio es edge: no puede importar el modelo de configuración."""
        from pathlib import Path

        import server.app.modules.agents_hub.services.vocabulary_service as mod

        source = Path(mod.__file__).read_text(encoding="utf-8")
        assert "config_models" not in source
        assert "HubVocabularyTerm" not in source


# ───────────────────────── Modelo: el vocabulario es dato ─────────────────────────


class TestVocabularyModel:

    def test_model_exists_with_natural_key(self):
        from server.app.modules.agents_hub.database.config_models import (
            HubVocabularyTerm,
        )

        cols = HubVocabularyTerm.__table__.c
        for name in (
            "organizacion_id",
            "axis",
            "codi",
            "nom_primari",
            "nom_secundari",
            "parent_codi",
            "descripcio_router",
            "ordre",
            "vigent",
            "substituit_per_codi",
        ):
            assert name in cols, f"falta la columna {name}"

    def test_should_not_declare_check_constraint_on_codi(self):
        """Guardarraíl del diseño: un CHECK sobre los códigos impediría revisar
        el vocabulario, que es justo lo que este prompt debe permitir."""
        from sqlalchemy import CheckConstraint

        from server.app.modules.agents_hub.database.config_models import (
            HubVocabularyTerm,
        )

        checks = [
            c for c in HubVocabularyTerm.__table__.constraints
            if isinstance(c, CheckConstraint)
        ]
        offending = [c for c in checks if "codi" in str(c.sqltext)]
        assert offending == [], f"CHECK sobre códigos de vocabulario: {offending}"

    def test_unique_constraint_on_org_axis_codi(self):
        from sqlalchemy import UniqueConstraint

        from server.app.modules.agents_hub.database.config_models import (
            HubVocabularyTerm,
        )

        uniques = [
            set(c.columns.keys())
            for c in HubVocabularyTerm.__table__.constraints
            if isinstance(c, UniqueConstraint)
        ]
        assert {"organizacion_id", "axis", "codi"} in uniques

    def test_is_config_base_not_operational(self):
        """Es configuración institucional: se sincroniza cloud→edge."""
        from server.app.modules.agents_hub.database.config_models import (
            HubConfigBase,
            HubVocabularyTerm,
        )

        assert issubclass(HubVocabularyTerm, HubConfigBase)


# ───────────────────────── Carga desde CSV ─────────────────────────


AMBITS_CSV = (
    "codi;nom_val;nom_es;assistent;propietari_proposat;docs_314_aprox;"
    "docs_globals_aprox;descripcio_router\n"
    "administracio;Administració;Administración;Assistent de Gerència;Gerència;49;84;"
    "Pressupost, despesa, contractació, dietes\n"
    "academica;Acadèmica;Académica;Assistent Acadèmic;VR Estudis;75;78;"
    "Accés, matrícula, avaluació\n"
)

SUBMATERIES_CSV = (
    "codi;ambit;nom_val;nom_es;abast;normes_exemple\n"
    "indemnitzacions-i-dietes;administracio;Indemnitzacions i dietes;"
    "Indemnizaciones y dietas;Imports de dietes i justificació;REG-020, INS-004\n"
    "avaluacio;academica;Avaluació;Evaluación;Sistemes d'avaluació;REG-003\n"
)


def _write(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


class TestCsvParsing:

    def test_should_parse_ambits_csv(self, tmp_path):
        from server.app.modules.agents_hub.vocabulary.load import parse_vocabulary_csv

        terms = parse_vocabulary_csv(_write(tmp_path, "ambits.csv", AMBITS_CSV), "ambit")
        by_codi = {t.codi: t for t in terms}
        assert set(by_codi) == {"administracio", "academica"}
        assert by_codi["administracio"].nom_primari == "Administració"
        assert by_codi["administracio"].nom_secundari == "Administración"
        assert by_codi["administracio"].parent_codi is None
        assert "contractació" in by_codi["administracio"].descripcio_router

    def test_should_parse_submateries_csv_with_parent(self, tmp_path):
        from server.app.modules.agents_hub.vocabulary.load import parse_vocabulary_csv

        terms = parse_vocabulary_csv(
            _write(tmp_path, "submateries.csv", SUBMATERIES_CSV), "submateria"
        )
        by_codi = {t.codi: t for t in terms}
        assert by_codi["indemnitzacions-i-dietes"].parent_codi == "administracio"
        assert by_codi["avaluacio"].parent_codi == "academica"
        # 'abast' es la descripción que ve el router
        assert "dietes" in by_codi["indemnitzacions-i-dietes"].descripcio_router

    def test_should_tolerate_unquoted_commas_in_trailing_column(self, tmp_path):
        """normes_exemple lleva comas sin comillas en el CSV real: no debe romper."""
        from server.app.modules.agents_hub.vocabulary.load import parse_vocabulary_csv

        terms = parse_vocabulary_csv(
            _write(tmp_path, "submateries.csv", SUBMATERIES_CSV), "submateria"
        )
        assert len(terms) == 2

    def test_should_preserve_file_order_as_ordre(self, tmp_path):
        from server.app.modules.agents_hub.vocabulary.load import parse_vocabulary_csv

        terms = parse_vocabulary_csv(
            _write(tmp_path, "submateries.csv", SUBMATERIES_CSV), "submateria"
        )
        assert [t.ordre for t in terms] == [0, 1]

    def test_should_reject_row_without_codi(self, tmp_path):
        from server.app.modules.agents_hub.vocabulary.load import (
            VocabularyCsvError,
            parse_vocabulary_csv,
        )

        bad = "codi;ambit;nom_val;nom_es;abast;normes_exemple\n;administracio;X;X;X;X\n"
        with pytest.raises(VocabularyCsvError):
            parse_vocabulary_csv(_write(tmp_path, "bad.csv", bad), "submateria")


class TestApplyTerms:

    @pytest.mark.asyncio
    async def test_should_create_terms_on_first_load(self, tmp_path):
        from server.app.modules.agents_hub.vocabulary.load import (
            apply_terms,
            parse_vocabulary_csv,
        )

        store = _FakeVocabularyStore([_ambit("administracio"), _ambit("academica")])
        terms = parse_vocabulary_csv(
            _write(tmp_path, "submateries.csv", SUBMATERIES_CSV), "submateria"
        )
        report = await apply_terms(store, terms, uuid.uuid4())

        assert report.created == 2
        assert report.updated == 0
        assert report.unchanged == 0

    @pytest.mark.asyncio
    async def test_should_be_idempotent_on_second_csv_load(self, tmp_path):
        from server.app.modules.agents_hub.vocabulary.load import (
            apply_terms,
            parse_vocabulary_csv,
        )

        store = _FakeVocabularyStore([_ambit("administracio"), _ambit("academica")])
        terms = parse_vocabulary_csv(
            _write(tmp_path, "submateries.csv", SUBMATERIES_CSV), "submateria"
        )
        org_id = uuid.uuid4()
        await apply_terms(store, terms, org_id)
        writes_after_first = store.writes

        report = await apply_terms(store, terms, org_id)

        assert report.unchanged == 2
        assert report.created == 0
        assert report.updated == 0
        assert store.writes == writes_after_first, "la segunda pasada no debe escribir"

    @pytest.mark.asyncio
    async def test_should_update_changed_term_by_natural_key(self, tmp_path):
        from server.app.modules.agents_hub.vocabulary.load import (
            apply_terms,
            parse_vocabulary_csv,
        )

        store = _FakeVocabularyStore([_ambit("administracio"), _ambit("academica")])
        org_id = uuid.uuid4()
        await apply_terms(
            store,
            parse_vocabulary_csv(
                _write(tmp_path, "s1.csv", SUBMATERIES_CSV), "submateria"
            ),
            org_id,
        )

        renamed = SUBMATERIES_CSV.replace("Indemnitzacions i dietes", "Dietes")
        report = await apply_terms(
            store,
            parse_vocabulary_csv(_write(tmp_path, "s2.csv", renamed), "submateria"),
            org_id,
        )

        assert report.updated == 1
        assert report.unchanged == 1
        assert report.created == 0

    @pytest.mark.asyncio
    async def test_should_reject_csv_with_dangling_parent_codi(self, tmp_path):
        from server.app.modules.agents_hub.vocabulary.load import (
            VocabularyCsvError,
            apply_terms,
            parse_vocabulary_csv,
        )

        store = _FakeVocabularyStore([_ambit("administracio")])  # falta 'academica'
        terms = parse_vocabulary_csv(
            _write(tmp_path, "submateries.csv", SUBMATERIES_CSV), "submateria"
        )
        with pytest.raises(VocabularyCsvError) as exc:
            await apply_terms(store, terms, uuid.uuid4())

        assert "academica" in str(exc.value)

    @pytest.mark.asyncio
    async def test_should_not_write_anything_when_a_parent_is_dangling(self, tmp_path):
        from server.app.modules.agents_hub.vocabulary.load import (
            VocabularyCsvError,
            apply_terms,
            parse_vocabulary_csv,
        )

        store = _FakeVocabularyStore([_ambit("administracio")])
        terms = parse_vocabulary_csv(
            _write(tmp_path, "submateries.csv", SUBMATERIES_CSV), "submateria"
        )
        with pytest.raises(VocabularyCsvError):
            await apply_terms(store, terms, uuid.uuid4())

        assert store.writes == 0, "el CSV se rechaza entero, no a medias"

    @pytest.mark.asyncio
    async def test_should_report_plan_without_writing_in_dry_run(self, tmp_path):
        from server.app.modules.agents_hub.vocabulary.load import (
            apply_terms,
            parse_vocabulary_csv,
        )

        store = _FakeVocabularyStore([_ambit("administracio"), _ambit("academica")])
        terms = parse_vocabulary_csv(
            _write(tmp_path, "submateries.csv", SUBMATERIES_CSV), "submateria"
        )
        report = await apply_terms(store, terms, uuid.uuid4(), dry_run=True)

        assert report.created == 2
        assert store.writes == 0


class TestSupersedeTerm:
    """Renombrar/fusionar: fila nueva + la vieja marcada. La cadena ES la traza.

    Desviación documentada respecto al plan: el barrido de documentos afectados
    (reclassify) se hace en ING.0.2, que es donde existen las columnas
    submateries/ambit_principal de hub_documents. Aquí solo el lado vocabulario.
    """

    @pytest.mark.asyncio
    async def test_should_mark_old_term_as_superseded(self):
        from server.app.modules.agents_hub.vocabulary.load import supersede_term

        store = _FakeVocabularyStore([_term("vella"), _term("nova")])
        await supersede_term(store, "submateria", "vella", "nova", uuid.uuid4())

        updated = {t.codi: t for t in store.updated}
        assert updated["vella"].vigent is False
        assert updated["vella"].substituit_per_codi == "nova"

    @pytest.mark.asyncio
    async def test_should_refuse_when_replacement_does_not_exist(self):
        from server.app.modules.agents_hub.vocabulary.load import (
            VocabularyCsvError,
            supersede_term,
        )

        store = _FakeVocabularyStore([_term("vella")])
        with pytest.raises(VocabularyCsvError):
            await supersede_term(store, "submateria", "vella", "fantasma", uuid.uuid4())
        assert store.writes == 0

    @pytest.mark.asyncio
    async def test_should_refuse_to_supersede_a_term_with_itself(self):
        from server.app.modules.agents_hub.vocabulary.load import (
            VocabularyCsvError,
            supersede_term,
        )

        store = _FakeVocabularyStore([_term("vella")])
        with pytest.raises(VocabularyCsvError):
            await supersede_term(store, "submateria", "vella", "vella", uuid.uuid4())
