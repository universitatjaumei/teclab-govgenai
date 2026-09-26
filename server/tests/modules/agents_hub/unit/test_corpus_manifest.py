"""Tests TDD — Front-matter como portador + manifiesto derivado (Prompt ING.0.3).

El `.md` es autodescriptivo: los metadatos viajan en su front-matter. El manifiesto
sigue existiendo para corpus que no lo trae (histórico, BOE), y cuando ambos hablan
del mismo campo **manda el front-matter**.

La decisión con más consecuencias del prompt: **el hash se calcula sobre el CUERPO**,
nunca sobre el front-matter. Así reetiquetar una norma no dispara re-troceado ni
re-embedding, y cambiar el texto sí.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest


CUERPO = """# Reglament sobre indemnitzacions

##### Article 14. Import de la dieta {#art-14}

L'import de la dieta és de 53,34 euros.
"""

FRONTMATTER = """---
id_publicacio: REG-020
title: Reglament sobre indemnitzacions
language: ca
content_class: regulation
revisat_per: Secretaria General
revisat_el: 2026-07-01T10:00:00+00:00
ambit_principal: administracio
submateries: [indemnitzacions-i-dietes]
nivell_acces: public
rang: reglament
url_oficial: https://www.uji.es/REG-020
termes_bilingues: [despesa/gasto, dieta]
---
"""


def _md(frontmatter: str = FRONTMATTER, cuerpo: str = CUERPO) -> str:
    return frontmatter + "\n" + cuerpo


# ───────────────────────── Parser de front-matter ─────────────────────────


class TestParser:

    def test_should_parse_frontmatter_and_strip_it_from_body(self):
        from server.app.modules.agents_hub.ingestion.corpus.frontmatter import (
            parse_frontmatter,
        )

        meta, body = parse_frontmatter(_md())

        assert meta["id_publicacio"] == "REG-020"
        assert meta["submateries"] == ["indemnitzacions-i-dietes"]
        assert body.startswith("# Reglament sobre indemnitzacions")
        assert "id_publicacio" not in body
        assert "---" not in body.splitlines()[0]

    def test_should_treat_md_without_frontmatter_as_empty_metadata(self):
        from server.app.modules.agents_hub.ingestion.corpus.frontmatter import (
            parse_frontmatter,
        )

        meta, body = parse_frontmatter(CUERPO)

        assert meta == {}
        assert body == CUERPO

    def test_tolera_bom_y_crlf(self):
        """Los .md vienen de una tubería en Windows y de ficheros con BOM."""
        from server.app.modules.agents_hub.ingestion.corpus.frontmatter import (
            parse_frontmatter,
        )

        crudo = "\ufeff" + _md().replace("\n", "\r\n")
        meta, body = parse_frontmatter(crudo)

        assert meta["id_publicacio"] == "REG-020"
        assert body.lstrip().startswith("# Reglament")

    def test_rechaza_frontmatter_con_yaml_invalido(self):
        from server.app.modules.agents_hub.ingestion.corpus.frontmatter import (
            FrontmatterError,
            parse_frontmatter,
        )

        with pytest.raises(FrontmatterError):
            parse_frontmatter("---\nid_publicacio: [sin cerrar\n---\n\n# T\n")

    def test_rechaza_frontmatter_que_no_es_un_mapa(self):
        from server.app.modules.agents_hub.ingestion.corpus.frontmatter import (
            FrontmatterError,
            parse_frontmatter,
        )

        with pytest.raises(FrontmatterError):
            parse_frontmatter("---\n- uno\n- dos\n---\n\n# T\n")

    def test_frontmatter_vacio_es_metadatos_vacios(self):
        from server.app.modules.agents_hub.ingestion.corpus.frontmatter import (
            parse_frontmatter,
        )

        meta, body = parse_frontmatter("---\n---\n\n# T\n")
        assert meta == {}
        assert body.strip() == "# T"

    def test_un_separador_horizontal_en_el_cuerpo_no_es_frontmatter(self):
        """'* * * *' y '---' aparecen como separadores en el corpus real."""
        from server.app.modules.agents_hub.ingestion.corpus.frontmatter import (
            parse_frontmatter,
        )

        crudo = "# Titol\n\nText\n\n---\n\nMes text\n"
        meta, body = parse_frontmatter(crudo)
        assert meta == {}
        assert body == crudo


# ───────────────────────── El hash va sobre el cuerpo ─────────────────────────


class TestHashDelCuerpo:

    def test_should_hash_body_without_frontmatter(self):
        """El test central del prompt."""
        from server.app.modules.agents_hub.ingestion.corpus.frontmatter import (
            hash_markdown_body,
        )
        from server.app.modules.agents_hub.ingestion.hasher import hash_content

        assert hash_markdown_body(_md()) == hash_content(CUERPO)

    def test_should_not_change_hash_when_only_metadata_changes(self):
        from server.app.modules.agents_hub.ingestion.corpus.frontmatter import (
            hash_markdown_body,
        )

        reetiquetado = FRONTMATTER.replace(
            "submateries: [indemnitzacions-i-dietes]",
            "submateries: [indemnitzacions-i-dietes, retribucions-i-gratificacions]",
        )
        assert hash_markdown_body(_md()) == hash_markdown_body(_md(reetiquetado))

    def test_should_change_hash_when_body_changes(self):
        from server.app.modules.agents_hub.ingestion.corpus.frontmatter import (
            hash_markdown_body,
        )

        corregido = CUERPO.replace("53,34", "55,00")
        assert hash_markdown_body(_md()) != hash_markdown_body(_md(cuerpo=corregido))

    def test_hash_coincide_con_y_sin_frontmatter_para_el_mismo_cuerpo(self):
        """Un .md que gana front-matter después NO debe reingerirse."""
        from server.app.modules.agents_hub.ingestion.corpus.frontmatter import (
            hash_markdown_body,
        )

        assert hash_markdown_body(CUERPO) == hash_markdown_body(_md())

    def test_el_hash_no_depende_del_final_de_linea(self):
        """El corpus se produce en Windows y el sync puede entregarlo con LF: el mismo
        documento con distinto final de línea no debe reingerirse."""
        from server.app.modules.agents_hub.ingestion.corpus.frontmatter import (
            hash_markdown_body,
        )

        assert hash_markdown_body(_md()) == hash_markdown_body(
            _md().replace("\n", "\r\n")
        )


# ───────────────────────── Contrato de entrada ─────────────────────────


def _entrada(**kwargs):
    from server.app.modules.agents_hub.ingestion.corpus.manifest import (
        CorpusDocumentEntry,
    )

    defaults = dict(
        relative_path="administracio/REG-020.md",
        source_url="https://www.uji.es/REG-020",
        language="ca",
    )
    defaults.update(kwargs)
    return CorpusDocumentEntry(**defaults)


class TestRutas:

    @pytest.mark.parametrize(
        "ruta",
        [
            "/absoluta/REG-020.md",
            "C:\\Users\\fabra\\REG-020.md",
            "../fuera/REG-020.md",
            "administracio/../../etc/passwd.md",
            "\\\\servidor\\share\\REG-020.md",
        ],
    )
    def test_should_reject_absolute_or_parent_paths(self, ruta: str):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            _entrada(relative_path=ruta)

    def test_acepta_ruta_relativa_con_subdirectorios(self):
        assert _entrada(relative_path="administracio/eco/REG-020.md")

    @pytest.mark.parametrize("extension", [".md", ".markdown"])
    def test_acepta_extensiones_de_markdown(self, extension: str):
        assert _entrada(relative_path=f"REG-020{extension}")

    def test_rechaza_extension_que_no_es_markdown(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            _entrada(relative_path="REG-020.pdf")


class TestRevisionObligatoria:

    def test_should_require_review_for_regulation_class(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as exc:
            _entrada(content_class="regulation")
        assert "revisat" in str(exc.value)

    def test_regulation_con_revision_completa_es_valida(self):
        entrada = _entrada(
            content_class="regulation",
            revisat_per="Secretaria General",
            revisat_el=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )
        assert entrada.revisat_per == "Secretaria General"

    def test_regulation_con_revisor_pero_sin_fecha_es_invalida(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            _entrada(content_class="regulation", revisat_per="SG")

    def test_should_allow_missing_review_for_faq_class(self):
        assert _entrada(content_class="faq").revisat_per is None

    def test_should_allow_missing_review_for_generic_class(self):
        assert _entrada(content_class="generic").revisat_per is None


class TestEnumeracionesCerradas:

    @pytest.mark.parametrize("valor", ["public", "intern", "restringit"])
    def test_acepta_los_niveles_de_acceso(self, valor: str):
        assert _entrada(nivell_acces=valor).nivell_acces == valor

    def test_rechaza_nivel_de_acceso_inventado(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            _entrada(nivell_acces="secreto")

    def test_should_require_motiu_exclusio_when_us_assistents_is_no(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as exc:
            _entrada(us_assistents="no")
        assert "motiu_exclusio" in str(exc.value)

    def test_us_assistents_no_con_motivo_es_valido(self):
        entrada = _entrada(us_assistents="no", motiu_exclusio="derogat")
        assert entrada.motiu_exclusio == "derogat"

    def test_defaults_conservadores(self):
        entrada = _entrada()
        assert entrada.nivell_acces == "public"
        assert entrada.us_assistents == "si"
        assert entrada.content_class == "generic"
        assert entrada.submateries == ()


class TestDesdeElFrontmatter:

    def test_construye_la_entrada_desde_el_frontmatter(self):
        from server.app.modules.agents_hub.ingestion.corpus.frontmatter import (
            parse_frontmatter,
        )
        from server.app.modules.agents_hub.ingestion.corpus.manifest import (
            entry_from_frontmatter,
        )

        meta, _ = parse_frontmatter(_md())
        entrada = entry_from_frontmatter(
            meta, relative_path="administracio/REG-020.md", source_url=meta["url_oficial"]
        )

        assert entrada.id_publicacio == "REG-020"
        assert entrada.ambit_principal == "administracio"
        assert entrada.submateries == ("indemnitzacions-i-dietes",)

    def test_las_claves_desconocidas_van_a_extra(self):
        """Es lo que permite que los 56 campos del esquema fluyan a doc_metadata sin
        que el contrato tenga que enumerarlos."""
        from server.app.modules.agents_hub.ingestion.corpus.frontmatter import (
            parse_frontmatter,
        )
        from server.app.modules.agents_hub.ingestion.corpus.manifest import (
            entry_from_frontmatter,
        )

        meta, _ = parse_frontmatter(_md())
        entrada = entry_from_frontmatter(
            meta, relative_path="a.md", source_url="https://www.uji.es/x"
        )

        assert entrada.extra["rang"] == "reglament"
        assert entrada.extra["termes_bilingues"] == ["despesa/gasto", "dieta"]
        assert "id_publicacio" not in entrada.extra

    def test_should_prefer_frontmatter_over_manifest_entry(self):
        from server.app.modules.agents_hub.ingestion.corpus.manifest import (
            merge_frontmatter,
        )

        del_manifiesto = _entrada(
            language="es", ambit_principal="academica", submateries=("avaluacio",)
        )
        resultado = merge_frontmatter(
            del_manifiesto,
            {"language": "ca", "submateries": ["indemnitzacions-i-dietes"]},
        )

        # `ca` entra y `val` sale: son la misma lengua y el corpus la escribe `val`. Lo que
        # este test comprueba es que manda el front-matter sobre el manifiesto, y manda: el
        # manifiesto decia `es`.
        assert resultado.language == "val"
        assert resultado.submateries == ("indemnitzacions-i-dietes",)
        # lo que el front-matter NO dice se conserva del manifiesto
        assert resultado.ambit_principal == "academica"
        assert resultado.source_url == del_manifiesto.source_url

    def test_frontmatter_vacio_deja_la_entrada_del_manifiesto_intacta(self):
        from server.app.modules.agents_hub.ingestion.corpus.manifest import (
            merge_frontmatter,
        )

        original = _entrada(ambit_principal="academica")
        assert merge_frontmatter(original, {}) == original


# ───────────────────────── Manifiesto ─────────────────────────


class TestManifiesto:

    def test_should_roundtrip_manifest_json(self, tmp_path):
        from server.app.modules.agents_hub.ingestion.corpus.manifest import (
            CorpusManifest,
            load_manifest,
        )

        manifiesto = CorpusManifest(
            chatbot_id=uuid.uuid4(),
            created_at=datetime(2026, 7, 28, tzinfo=timezone.utc),
            documents=[
                _entrada(),
                # url propia: dos documentos distintos no comparten url oficial, y desde
                # VIS.3 compartirla declarándose ambos canónicos es un error del paquete.
                _entrada(
                    relative_path="b.md",
                    content_class="faq",
                    source_url="https://www.uji.es/FAQ-001",
                ),
            ],
        )
        destino = tmp_path / "manifest.json"
        destino.write_text(manifiesto.model_dump_json(), encoding="utf-8")

        recargado = load_manifest(destino)

        assert recargado == manifiesto
        assert len(recargado.documents) == 2

    def test_carga_manifiesto_en_yaml(self, tmp_path):
        from server.app.modules.agents_hub.ingestion.corpus.manifest import load_manifest

        destino = tmp_path / "manifest.yaml"
        destino.write_text(
            "chatbot_id: " + str(uuid.uuid4()) + "\n"
            "created_at: 2026-07-28T00:00:00+00:00\n"
            "documents:\n"
            "  - relative_path: a.md\n"
            "    source_url: https://www.uji.es/a\n"
            "    language: ca\n",
            encoding="utf-8",
        )
        assert len(load_manifest(destino).documents) == 1

    def test_rechaza_rutas_relativas_duplicadas(self):
        from pydantic import ValidationError

        from server.app.modules.agents_hub.ingestion.corpus.manifest import CorpusManifest

        with pytest.raises(ValidationError):
            CorpusManifest(
                chatbot_id=uuid.uuid4(),
                documents=[_entrada(), _entrada()],
            )

    def test_should_error_when_two_documents_share_url_without_being_siblings(self):
        """VIS.3: dos canónicas para la misma norma es un error, no una eleccion a ciegas.

        Si el paquete declara canónicas la versión valenciana y la castellana de la misma
        norma, elegir una por orden de aparición indexaría el mismo contenido dos veces sin
        que nadie lo hubiera decidido. Falla antes de tocar la BD, con las dos rutas.
        """
        from pydantic import ValidationError

        from server.app.modules.agents_hub.ingestion.corpus.manifest import CorpusManifest

        with pytest.raises(ValidationError) as error:
            CorpusManifest(
                chatbot_id=uuid.uuid4(),
                documents=[
                    _entrada(relative_path="reg-020-ca.md", language="ca",
                             id_publicacio="REG-020"),
                    _entrada(relative_path="reg-020-es.md", language="es",
                             id_publicacio="REG-021"),
                ],
            )

        mensaje = str(error.value)
        assert "reg-020-ca.md" in mensaje and "reg-020-es.md" in mensaje

    def test_should_accept_two_language_siblings_sharing_one_url(self):
        """Compartir URL solo es legitimo entre hermanas idiomaticas: la misma norma publicada
        en una sola direccion. Son 5 de las 57 parejas del corpus real (una pagina de preguntas
        frecuentes, un PDF del DOGV con las dos lenguas dentro)."""
        from server.app.modules.agents_hub.ingestion.corpus.manifest import CorpusManifest

        manifiesto = CorpusManifest(
            chatbot_id=uuid.uuid4(),
            documents=[
                _entrada(relative_path="reg-020-ca.md", language="ca",
                         id_publicacio="REG-020"),
                _entrada(
                    relative_path="reg-020-es.md", language="es",
                    id_publicacio="REG-020-es", versio_idiomatica_de="REG-020",
                ),
            ],
        )

        assert len(manifiesto.documents) == 2


# ───────────────────────── Validación contra el vocabulario ─────────────────────────


class _FakeVocabulary:
    """Sustituye a VocabularyService: solo necesita validate(axis, codis)."""

    def __init__(self, conocidos: dict[str, set[str]]) -> None:
        self.conocidos = conocidos

    async def validate(self, axis: str, codis: list[str]) -> list[str]:
        conocidos = self.conocidos.get(axis, set())
        return [c for c in codis if c not in conocidos]


class TestVocabulario:

    @pytest.mark.asyncio
    async def test_should_reject_unknown_submateria_against_vocabulary(self):
        from server.app.modules.agents_hub.ingestion.corpus.manifest import (
            CorpusValidationError,
            assert_vocabulary,
        )

        vocabulario = _FakeVocabulary(
            {"ambit": {"administracio"}, "submateria": {"indemnitzacions-i-dietes"}}
        )
        entradas = [
            _entrada(ambit_principal="administracio", submateries=("inventada",))
        ]

        with pytest.raises(CorpusValidationError) as exc:
            await assert_vocabulary(entradas, vocabulario)
        assert "inventada" in str(exc.value)

    @pytest.mark.asyncio
    async def test_acepta_codigos_conocidos(self):
        from server.app.modules.agents_hub.ingestion.corpus.manifest import (
            assert_vocabulary,
        )

        vocabulario = _FakeVocabulary(
            {"ambit": {"administracio"}, "submateria": {"indemnitzacions-i-dietes"}}
        )
        await assert_vocabulary(
            [
                _entrada(
                    ambit_principal="administracio",
                    submateries=("indemnitzacions-i-dietes",),
                )
            ],
            vocabulario,
        )

    @pytest.mark.asyncio
    async def test_should_list_all_unknown_codes_not_just_the_first(self):
        from server.app.modules.agents_hub.ingestion.corpus.manifest import (
            CorpusValidationError,
            assert_vocabulary,
        )

        vocabulario = _FakeVocabulary({"ambit": set(), "submateria": set()})
        entradas = [
            _entrada(relative_path="a.md", ambit_principal="mal-ambit"),
            _entrada(relative_path="b.md", submateries=("mala-1", "mala-2")),
            _entrada(relative_path="c.md", submateries_internes=("mala-3",)),
            _entrada(relative_path="d.md", ambits_secundaris=("mal-secundario",)),
        ]

        with pytest.raises(CorpusValidationError) as exc:
            await assert_vocabulary(entradas, vocabulario)

        mensaje = str(exc.value)
        for codigo in ("mal-ambit", "mala-1", "mala-2", "mala-3", "mal-secundario"):
            assert codigo in mensaje, f"{codigo} no aparece en el error"

    @pytest.mark.asyncio
    async def test_el_error_dice_en_que_fichero_esta_cada_codigo(self):
        from server.app.modules.agents_hub.ingestion.corpus.manifest import (
            CorpusValidationError,
            assert_vocabulary,
        )

        vocabulario = _FakeVocabulary({"ambit": set(), "submateria": set()})
        with pytest.raises(CorpusValidationError) as exc:
            await assert_vocabulary(
                [_entrada(relative_path="administracio/REG-020.md", submateries=("mala",))],
                vocabulario,
            )
        assert "administracio/REG-020.md" in str(exc.value)

    @pytest.mark.asyncio
    async def test_no_consulta_el_vocabulario_si_no_hay_codigos(self):
        from server.app.modules.agents_hub.ingestion.corpus.manifest import (
            assert_vocabulary,
        )

        class _Explota:
            async def validate(self, axis, codis):
                raise AssertionError("no deberia consultarse")

        await assert_vocabulary([_entrada()], _Explota())
