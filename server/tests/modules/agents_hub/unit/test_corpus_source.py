"""Tests TDD — Fuente de corpus en carpeta local (Prompt ING.0.5).

El reconciliador no sabe de dónde viene el corpus: consume `CorpusSource`. SYNC.1 añade
una segunda implementación sobre el servicio MCP **sin tocar el reconciliador**.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest

FRONT = """---
id_publicacio: {id}
title: Norma {id}
language: ca
url_oficial: https://www.uji.es/{id}
{extra}---

# Norma {id}

Cos de la norma.
"""


def _md(directorio: Path, id_publicacio: str, extra: str = "") -> Path:
    ruta = directorio / f"{id_publicacio}.md"
    ruta.write_text(FRONT.format(id=id_publicacio, extra=extra), encoding="utf-8")
    return ruta


def _fuente(directorio: Path, **kwargs):
    from server.app.modules.agents_hub.ingestion.corpus.source import (
        LocalDirectorySource,
    )

    return LocalDirectorySource(directorio, **kwargs)


class TestProtocolo:

    def test_cumple_el_protocolo_corpus_source(self, tmp_path):
        from server.app.modules.agents_hub.ingestion.corpus.source import CorpusSource

        fuente = _fuente(tmp_path)
        assert isinstance(fuente, CorpusSource)

    def test_rechaza_un_directorio_que_no_existe(self, tmp_path):
        from server.app.modules.agents_hub.ingestion.corpus.manifest import (
            CorpusValidationError,
        )

        with pytest.raises(CorpusValidationError):
            _fuente(tmp_path / "no-existe")


class TestCenso:

    def test_no_es_censo_por_defecto(self, tmp_path):
        """El default seguro: sin declaración explícita, la poda no puede actuar."""
        assert _fuente(tmp_path).is_census() is False

    def test_declara_censo_cuando_se_le_dice(self, tmp_path):
        assert _fuente(tmp_path, is_census_declared=True).is_census() is True


class TestListado:

    @pytest.mark.asyncio
    async def test_lista_los_md_del_directorio(self, tmp_path):
        _md(tmp_path, "REG-001")
        _md(tmp_path, "REG-002")

        entradas = await _fuente(tmp_path).list_entries()

        assert {e.id_publicacio for e in entradas} == {"REG-001", "REG-002"}

    @pytest.mark.asyncio
    async def test_recorre_subdirectorios(self, tmp_path):
        (tmp_path / "administracio").mkdir()
        _md(tmp_path / "administracio", "REG-003")

        entradas = await _fuente(tmp_path).list_entries()

        assert entradas[0].relative_path == "administracio/REG-003.md"

    @pytest.mark.asyncio
    async def test_ignora_lo_que_no_es_markdown(self, tmp_path):
        _md(tmp_path, "REG-004")
        (tmp_path / "notas.txt").write_text("no soy markdown", encoding="utf-8")
        (tmp_path / "original.pdf").write_bytes(b"%PDF-1.4")

        entradas = await _fuente(tmp_path).list_entries()

        assert len(entradas) == 1

    @pytest.mark.asyncio
    async def test_toma_la_url_oficial_del_frontmatter(self, tmp_path):
        _md(tmp_path, "REG-005")

        entradas = await _fuente(tmp_path).list_entries()

        assert entradas[0].source_url == "https://www.uji.es/REG-005"

    @pytest.mark.asyncio
    async def test_rechaza_el_paquete_entero_si_una_entrada_no_cumple(self, tmp_path):
        """Un corpus a medias hace fallar la validación de forma aleatoria."""
        from server.app.modules.agents_hub.ingestion.corpus.manifest import (
            CorpusValidationError,
        )

        _md(tmp_path, "REG-006")
        _md(tmp_path, "REG-007", extra="content_class: regulation\n")

        with pytest.raises(CorpusValidationError) as exc:
            await _fuente(tmp_path).list_entries()

        assert "REG-007" in str(exc.value)
        assert "revisat" in str(exc.value)

    @pytest.mark.asyncio
    async def test_enumera_todas_las_entradas_malas(self, tmp_path):
        from server.app.modules.agents_hub.ingestion.corpus.manifest import (
            CorpusValidationError,
        )

        _md(tmp_path, "REG-008", extra="content_class: regulation\n")
        _md(tmp_path, "REG-009", extra="us_assistents: 'no'\n")

        with pytest.raises(CorpusValidationError) as exc:
            await _fuente(tmp_path).list_entries()

        mensaje = str(exc.value)
        assert "REG-008" in mensaje and "REG-009" in mensaje


class TestManifiesto:

    @pytest.mark.asyncio
    async def test_el_manifiesto_acota_lo_que_se_carga(self, tmp_path):
        """Con manifiesto, una carga parcial es explícita."""
        from server.app.modules.agents_hub.ingestion.corpus.manifest import (
            CorpusDocumentEntry,
            CorpusManifest,
        )

        _md(tmp_path, "REG-010")
        _md(tmp_path, "REG-011")
        manifiesto = CorpusManifest(
            chatbot_id=uuid.uuid4(),
            documents=[
                CorpusDocumentEntry(
                    relative_path="REG-010.md",
                    source_url="https://www.uji.es/REG-010",
                    language="ca",
                )
            ],
        )

        entradas = await _fuente(tmp_path, manifest=manifiesto).list_entries()

        assert len(entradas) == 1
        assert entradas[0].id_publicacio == "REG-010"

    @pytest.mark.asyncio
    async def test_manda_el_frontmatter_sobre_el_manifiesto(self, tmp_path):
        from server.app.modules.agents_hub.ingestion.corpus.manifest import (
            CorpusDocumentEntry,
            CorpusManifest,
        )

        _md(tmp_path, "REG-012", extra="nivell_acces: intern\n")
        manifiesto = CorpusManifest(
            chatbot_id=uuid.uuid4(),
            documents=[
                CorpusDocumentEntry(
                    relative_path="REG-012.md",
                    source_url="https://www.uji.es/otra",
                    language="es",
                    nivell_acces="public",
                )
            ],
        )

        entrada = (await _fuente(tmp_path, manifest=manifiesto).list_entries())[0]

        # El front-matter dice `ca` y el manifiesto `es`: manda el front-matter, y se guarda
        # con el codigo del corpus (`val`), que es la misma lengua escrita como la escribe todo
        # lo demas.
        assert entrada.language == "val"
        assert entrada.nivell_acces == "intern"

    @pytest.mark.asyncio
    async def test_avisa_si_el_manifiesto_declara_un_fichero_que_no_existe(self, tmp_path):
        from server.app.modules.agents_hub.ingestion.corpus.manifest import (
            CorpusDocumentEntry,
            CorpusManifest,
            CorpusValidationError,
        )

        manifiesto = CorpusManifest(
            chatbot_id=uuid.uuid4(),
            documents=[
                CorpusDocumentEntry(
                    relative_path="fantasma.md",
                    source_url="https://www.uji.es/x",
                    language="ca",
                )
            ],
        )

        with pytest.raises(CorpusValidationError) as exc:
            await _fuente(tmp_path, manifest=manifiesto).list_entries()

        assert "fantasma.md" in str(exc.value)


class TestCuerpo:

    @pytest.mark.asyncio
    async def test_read_body_devuelve_el_markdown_sin_frontmatter(self, tmp_path):
        _md(tmp_path, "REG-013")
        fuente = _fuente(tmp_path)
        entrada = (await fuente.list_entries())[0]

        cuerpo = await fuente.read_body(entrada)

        assert cuerpo.startswith("# Norma REG-013")
        assert "id_publicacio" not in cuerpo

    @pytest.mark.asyncio
    async def test_el_cuerpo_hashea_igual_que_hash_markdown_body(self, tmp_path):
        """El hash del reconciliador y el del contrato tienen que coincidir."""
        from server.app.modules.agents_hub.ingestion.corpus.frontmatter import (
            hash_markdown_body,
        )

        ruta = _md(tmp_path, "REG-014")
        fuente = _fuente(tmp_path)
        entrada = (await fuente.list_entries())[0]

        cuerpo = await fuente.read_body(entrada)

        assert hash_markdown_body(cuerpo) == hash_markdown_body(
            ruta.read_text(encoding="utf-8")
        )
