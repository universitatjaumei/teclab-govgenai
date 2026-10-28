"""Fuentes de corpus curado (ING.0.5). Deploy: edge.

El reconciliador (`reconciler.py`) no sabe de dónde viene el corpus: consume este
protocolo. Hoy hay una implementación —una carpeta local de `.md`, que es el mecanismo
de mantenimiento mientras no exista el pipeline de publicación— y SYNC.1 añadirá la
segunda, contra el servicio MCP de datasets. **Añadir una fuente no debe tocar el
reconciliador.**

`is_census()` es la pieza delicada: declara si la fuente entrega el corpus **completo**.
Solo con un censo se puede detectar una retirada, porque solo entonces «ausente» significa
algo. Una carga parcial que se interpretara como censo retiraría cientos de normas.
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from server.app.modules.agents_hub.ingestion.corpus.faq import (
    assert_formato_faq,
    debe_validarse_como_faq,
)
from server.app.modules.agents_hub.ingestion.corpus.frontmatter import parse_frontmatter
from server.app.modules.agents_hub.ingestion.markdown_utils import extract_title_from_markdown
from server.app.modules.agents_hub.ingestion.corpus.manifest import (
    CorpusDocumentEntry,
    CorpusManifest,
    CorpusValidationError,
    entry_from_frontmatter,
    merge_frontmatter,
)

EXTENSIONES = (".md", ".markdown")


def _entrada(
    ruta: str,
    texto: str,
    *,
    url_por_defecto: str = "",
    base: CorpusDocumentEntry | None = None,
) -> CorpusDocumentEntry:
    """La entrada de un `.md`: su front-matter, sobre la del manifiesto si la hay.

    FAQ.1: una FAQ mal formateada se ingiere sin protestar y responde peor a partir de
    entonces, así que se comprueba aquí, con el resto del contrato.
    """
    metadata, cuerpo = parse_frontmatter(texto)
    if debe_validarse_como_faq(metadata):
        assert_formato_faq(cuerpo)
    if base is not None:
        return merge_frontmatter(base, metadata)
    return entry_from_frontmatter(
        metadata,
        relative_path=ruta,
        source_url=metadata.get("url_oficial") or url_por_defecto or ruta,
    )


@runtime_checkable
class CorpusSource(Protocol):
    """Origen de un paquete de corpus.

    `runtime_checkable` para que la fuente de SYNC.1 pueda comprobarse con `isinstance`
    en su propio test en lugar de descubrir el desajuste en ejecución.
    """

    def is_census(self) -> bool:
        """True si estas entradas son el corpus COMPLETO."""
        ...

    async def list_entries(self) -> list[CorpusDocumentEntry]: ...

    async def read_body(self, entry: CorpusDocumentEntry) -> str:
        """Markdown sin front-matter, tal como se hashea y se trocea."""
        ...


class LocalDirectorySource:
    """Carpeta de `.md` en disco, con manifiesto opcional.

    El front-matter del fichero **manda** sobre la entrada del manifiesto; el manifiesto
    existe para los corpus que no lo traen (histórico sin convertir, consolidados del BOE).
    """

    def __init__(
        self,
        directory: Path | str,
        manifest: CorpusManifest | None = None,
        is_census_declared: bool = False,
        default_source_url: str = "",
    ) -> None:
        self.directory = Path(directory)
        self.manifest = manifest
        self._is_census = is_census_declared
        self.default_source_url = default_source_url
        if not self.directory.is_dir():
            raise CorpusValidationError(f"No es un directorio: {self.directory}")

    def is_census(self) -> bool:
        return self._is_census

    def _ruta(self, entry: CorpusDocumentEntry) -> Path:
        return self.directory / entry.relative_path.replace("\\", "/")

    def _ficheros(self) -> list[str]:
        rutas = [
            p for p in sorted(self.directory.rglob("*"))
            if p.is_file() and p.suffix.lower() in EXTENSIONES
        ]
        return [p.relative_to(self.directory).as_posix() for p in rutas]

    async def list_entries(self) -> list[CorpusDocumentEntry]:
        """Una entrada por `.md`, con el front-matter aplicado sobre el manifiesto.

        Recorre el **manifiesto** si lo hay —así una carga acotada es explícita— y en su
        defecto todos los `.md` del directorio.
        """
        del_manifiesto = {
            e.relative_path.replace("\\", "/"): e
            for e in (self.manifest.documents if self.manifest else ())
        }
        rutas = list(del_manifiesto) if del_manifiesto else self._ficheros()

        entradas: list[CorpusDocumentEntry] = []
        errores: list[str] = []
        for ruta in rutas:
            fichero = self.directory / ruta
            if not fichero.is_file():
                errores.append(f"  {ruta}: el manifiesto lo declara y no existe")
                continue
            try:
                entradas.append(
                    _entrada(
                        ruta,
                        fichero.read_text(encoding="utf-8-sig", errors="replace"),
                        url_por_defecto=self.default_source_url,
                        base=del_manifiesto.get(ruta),
                    )
                )
            except Exception as exc:  # noqa: BLE001 — se acumulan todos los errores del paquete y se rechaza entero
                errores.append(f"  {ruta}: {exc}")

        if errores:
            raise CorpusValidationError(
                "El paquete no cumple el contrato y no se ingiere nada "
                f"({len(errores)} de {len(rutas)} entradas):\n" + "\n".join(errores)
            )
        return entradas

    async def read_body(self, entry: CorpusDocumentEntry) -> str:
        _, body = parse_frontmatter(
            self._ruta(entry).read_text(encoding="utf-8-sig", errors="replace")
        )
        return body


class MarkdownSubido:
    """Un `.md` subido por el panel (#265): entra por el reconciliador, como el de consola.

    Lo único que añade el panel son la URL y el idioma del formulario, que mandan cuando la
    persona los rellena —«Sustituir documento» los rellena con los del documento sustituido,
    y sin eso el reconciliador no lo encontraría—. Y `source_kind` sigue siendo `upload` si el
    front-matter no dice otra cosa: es lo que la tabla del panel enseña como origen.

    No es un censo: un fichero suelto no dice nada de los que no están.

    Sin URL en el formulario ni `url_oficial` en el front-matter, la URL es `url_por_defecto`
    —la clave de almacenamiento del trabajo, que es única— y no el nombre del fichero: el
    reconciliador identifica por URL y lengua, y dos documentos distintos subidos con el mismo
    nombre se sustituían entre sí (#265b).
    """

    def __init__(
        self,
        nombre: str,
        texto: str,
        *,
        url_por_defecto: str = "",
        canonical_url: str | None = None,
        language: str | None = None,
    ) -> None:
        self._nombre = nombre
        self._url_por_defecto = url_por_defecto
        self._texto = texto
        self._canonical_url = canonical_url
        self._language = language

    def is_census(self) -> bool:
        return False

    async def list_entries(self) -> list[CorpusDocumentEntry]:
        entrada = _entrada(self._nombre, self._texto, url_por_defecto=self._url_por_defecto)
        cambios: dict = {"extra": {"source_kind": "upload", **entrada.extra}}
        if not entrada.title:
            # #285 — sin `title:`, el reconciliador titulaba con el nombre del fichero y su
            # extensión (`norma.md`). Antes de #265 era `norma`; y el H1, que es el título que
            # el documento se da a sí mismo, no se miraba en ninguno de los dos casos.
            cuerpo = parse_frontmatter(self._texto)[1]
            cambios["title"] = extract_title_from_markdown(cuerpo) or Path(self._nombre).stem
        if self._canonical_url:
            cambios["source_url"] = self._canonical_url
        if self._language:
            cambios["language"] = self._language
        # `model_validate` y no `model_copy`: `model_copy` no pasa por los validadores, y el `ca`
        # del selector del panel se quedaba sin normalizar a `val` (#265b).
        return [type(entrada).model_validate({**entrada.model_dump(), **cambios})]

    async def read_body(self, entry: CorpusDocumentEntry) -> str:  # noqa: ARG002 — una fuente de un solo documento no necesita la entrada para leerlo
        return parse_frontmatter(self._texto)[1]
