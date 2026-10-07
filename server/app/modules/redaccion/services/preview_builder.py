"""PreviewBuilderService — construye PreviewPayload desde workspace + manifest (1C.3).

Deploy: edge
Rechaza con PendingBlocksError si hay bloques no aprobados ni locked.
"""
from __future__ import annotations

import base64
import html as _html
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from pydantic import TypeAdapter

from server.app.modules.redaccion.contracts.preview import (
    PreviewAuditEntry,
    PreviewBlock,
    PreviewPayload,
    PreviewSection,
    TocEntry,
)
from server.app.modules.redaccion.contracts.template import SectionContract
from server.app.modules.redaccion.services.block_actions import bloques_pendientes

_log = logging.getLogger(__name__)

_NIL_UUID = UUID("00000000-0000-0000-0000-000000000000")
_section_adapter: TypeAdapter[list[SectionContract]] = TypeAdapter(list[SectionContract])

# INF.2 — `bloques_pendientes`, `TIPOS_DE_IA` y los estados aprobados vivían aquí, y el
# ensamblador del grafo usaba una regla distinta con el mismo nombre. Ahora la política vive en
# un solo módulo y este la consume: `services/block_actions.py`.


class PendingBlocksError(Exception):
    """Raised when blocks are not yet approved or locked."""

    def __init__(self, pending_block_ids: list[str]) -> None:
        super().__init__(
            f"Cannot build preview: blocks pending — {pending_block_ids}"
        )
        self.pending_block_ids = pending_block_ids


class PreviewBuilderService:
    """Builds a PreviewPayload from current workspace state."""

    def __init__(
        self,
        workspace_repo: Any,
        block_repo: Any,
        template_version_repo: Any,
        manifest_repo: Any,
        storage_service: Any = None,
        template_repo: Any = None,
    ) -> None:
        self._workspace_repo = workspace_repo
        self._block_repo = block_repo
        self._template_version_repo = template_version_repo
        self._manifest_repo = manifest_repo
        # PRO.5 — para traer la imagen de los gráficos, que vive en el almacén y no en la
        # base de datos. Sin almacén el bloque sale sin imagen, no revienta.
        self._storage = storage_service
        # #243 — para encabezar el informe con el nombre de la plantilla y no con el identificador
        # del espacio de trabajo, que es lo que salía en la vista previa y en el Word.
        self._template_repo = template_repo

    async def _imagenes_de(self, bloque: Any) -> dict[str, bytes]:
        """Las imágenes que el bloque referencia, traídas del almacén.

        Un gráfico que no está no puede tumbar el informe entero: el bloque sale sin imagen y
        queda constancia en el log. Es la misma decisión que `FileNormalizationNode` toma con
        un artefacto que ya no está.
        """
        contenido = bloque.content_json or {}
        grafico = contenido.get("chart") if isinstance(contenido, dict) else None
        clave = (grafico or {}).get("storage_key") if isinstance(grafico, dict) else None
        if not clave or self._storage is None:
            return {}
        try:
            return {clave: await self._storage.get(clave)}
        except Exception:  # noqa: BLE001
            _log.warning("No se pudo leer el gráfico %s del almacén", clave)
            return {}

    async def _titulo(self, template_version: Any, workspace_id: UUID) -> str:
        """El nombre de la plantilla; el identificador sólo si no hay de dónde sacarlo."""
        if self._template_repo is not None and template_version is not None:
            plantilla = await self._template_repo.get(template_version.template_id)
            if plantilla is not None and getattr(plantilla, "name", None):
                return plantilla.name
        return str(workspace_id)

    async def build_payload(self, workspace_id: UUID) -> PreviewPayload:
        workspace = await self._workspace_repo.get(workspace_id)
        if workspace is None:
            raise ValueError(f"Workspace {workspace_id} not found")

        blocks = await self._block_repo.list(workspace_id)

        pending = bloques_pendientes(blocks)
        if pending:
            raise PendingBlocksError(pending)

        template_version = await self._template_version_repo.get(
            workspace.template_version_id
        )
        manifests = await self._manifest_repo.list(workspace_id)
        manifest = max(manifests, key=lambda m: m.created_at) if manifests else None

        sections = _extract_sections(
            template_version.spec_json if template_version else {}
        )
        block_map = {b.block_id: b for b in blocks}

        toc: list[TocEntry] = []
        body: list[PreviewSection] = []
        for sec in sections:
            toc.append(TocEntry(level=1, title=sec.title))
            preview_blocks = [
                _build_preview_block(block_map[bid], await self._imagenes_de(block_map[bid]))
                for bid in sec.block_ids
                if bid in block_map
            ]
            body.append(PreviewSection(level=1, title=sec.title, blocks=preview_blocks))

        audit_annex = _build_audit_annex(blocks)

        cover = PreviewSection(
            level=0,
            title=await self._titulo(template_version, workspace_id),
            blocks=[],
        )

        return PreviewPayload(
            workspace_id=workspace_id,
            template_version_id=UUID(str(workspace.template_version_id)),
            cover=cover,
            toc=toc,
            body=body,
            audit_annex=audit_annex,
            manifest_id=UUID(str(manifest.id)) if manifest else _NIL_UUID,
            generated_at=datetime.now(timezone.utc),
        )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _extract_sections(spec_json: dict) -> list[SectionContract]:
    raw = spec_json.get("sections", [])
    return _section_adapter.validate_python(raw)


def _block_content_to_html(
    content: dict | None, imagenes: dict[str, bytes] | None = None
) -> str:
    """El HTML de un bloque para la vista previa y la impresión.

    PRO.3 — miraba sólo `text` y `value`, y el contenido de **cualquier extracción** es
    `{tables, metrics, free_text}`: ninguna tabla extraída se había visto nunca en la vista
    previa, ni por script ni por Excel ni por PDF. El bloque quedaba `extracted` con sus datos
    dentro y el informe salía en blanco.

    Todo se escapa: los datos vienen de un fichero que sube cualquiera.
    """
    if not content:
        return ""

    texto = content.get("text") or content.get("value") or ""
    if texto:
        return f"<p>{_html.escape(str(texto))}</p>"

    partes: list[str] = []

    # PRO.5 — el gráfico, incrustado como data URI: la vista de impresión tiene que ser
    # autónoma (se imprime, se guarda, se manda por correo) y un `src` a un endpoint la
    # dejaría en blanco fuera de la sesión.
    grafico = content.get("chart")
    if isinstance(grafico, dict):
        imagen = (imagenes or {}).get(grafico.get("storage_key", ""))
        if imagen:
            formato = "svg+xml" if grafico.get("format") == "svg" else "png"
            datos = base64.b64encode(imagen).decode("ascii")
            alternativo = _html.escape(str(grafico.get("chart_type") or "gráfico"))
            partes.append(
                f'<img src="data:image/{formato};base64,{datos}" alt="{alternativo}" />'
            )

    for tabla in content.get("tables") or []:
        partes.append(_tabla_a_html(tabla))

    metricas = content.get("metrics") or []
    if metricas:
        filas = "".join(
            "<li><strong>{nombre}</strong>: {valor}{unidad}</li>".format(
                nombre=_html.escape(str(m.get("name", ""))),
                valor=_html.escape(str(m.get("value", ""))),
                unidad=f" {_html.escape(str(m['unit']))}" if m.get("unit") else "",
            )
            for m in metricas
        )
        partes.append(f'<ul class="metricas">{filas}</ul>')

    libre = content.get("free_text")
    if libre:
        partes.append(f"<p>{_html.escape(str(libre))}</p>")

    return "".join(partes)


def _tabla_a_html(tabla: dict) -> str:
    nombre = tabla.get("name")
    cabeceras = tabla.get("headers") or []
    filas = tabla.get("rows") or []

    cabecera_html = ""
    if cabeceras:
        celdas = "".join(f"<th>{_html.escape(str(c))}</th>" for c in cabeceras)
        cabecera_html = f"<thead><tr>{celdas}</tr></thead>"

    cuerpo = "".join(
        "<tr>" + "".join(f"<td>{_html.escape(str(v))}</td>" for v in fila) + "</tr>"
        for fila in filas
    )
    titulo = f"<caption>{_html.escape(str(nombre))}</caption>" if nombre else ""
    return f"<table>{titulo}{cabecera_html}<tbody>{cuerpo}</tbody></table>"


def _extract_citation_uuids(citations_json: list | None) -> list[UUID]:
    if not citations_json:
        return []
    result = []
    for cit in citations_json:
        if isinstance(cit, dict) and cit.get("chunk_id"):
            try:
                result.append(UUID(str(cit["chunk_id"])))
            except (ValueError, AttributeError):
                pass
    return result


def _build_preview_block(block: Any, imagenes: dict[str, bytes] | None = None) -> PreviewBlock:
    return PreviewBlock(
        block_id=block.block_id,
        kind=block.kind,
        state=block.status,
        content=block.content_json,
        images=imagenes or {},
        html=_block_content_to_html(block.content_json, imagenes=imagenes),
        citations=_extract_citation_uuids(block.citations_json),
    )


def _build_audit_annex(blocks: list[Any]) -> list[PreviewAuditEntry]:
    seen: dict[UUID, PreviewAuditEntry] = {}
    for block in blocks:
        for chunk_id in _extract_citation_uuids(block.citations_json):
            if chunk_id not in seen:
                seen[chunk_id] = PreviewAuditEntry(chunk_id=chunk_id)
    return list(seen.values())
