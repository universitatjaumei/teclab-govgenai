"""Builder de informes de auditoría web por sitio (9Q.8).

Deploy: edge.

Agrega los hallazgos de un sitio en un WebQualityReport estructurado por tipo,
con recomendaciones accionables en español (claves internacionalizables en UI).
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Sequence

from server.app.modules.curation.report_exporter import se_puede_convertir_a_pdf
from server.app.modules.curation.report_contracts import (
    ContentFindingView,
    FindingTypeSection,
    WebQualityReport,
)

# Plantillas de recomendación por tipo de hallazgo (texto base en español).
_RECOMMENDATIONS: dict[str, str] = {
    "superseded": (
        "{n} página(s) obsoleta(s) detectada(s): considere despublicar las URLs "
        "sustituidas por versiones más recientes."
    ),
    "duplicate": (
        "{n} página(s) duplicada(s): elimine o redirija el contenido redundante "
        "para evitar problemas de indexación."
    ),
    "contradiction": (
        "{n} contradicción(es) semántica(s): revise y unifique la información "
        "entre las páginas afectadas."
    ),
    "empty": (
        "{n} página(s) vacía(s): elimine estas URLs o publique contenido antes "
        "del próximo ciclo de indexación."
    ),
    "thin": (
        "{n} página(s) con contenido escaso (pocos tokens): amplíe el texto "
        "o consolide con páginas relacionadas."
    ),
    "navigation": (
        "{n} página(s) de navegación (enlaces sin texto propio): no requieren cambios; "
        "no las proponga para el asistente, que no tendría nada que citar."
    ),
    "stale": (
        "{n} página(s) con contenido potencialmente desactualizado: revise y "
        "actualice la información o indique la fecha de última revisión."
    ),
    "crawl_error": (
        "{n} error(es) de crawl: verifique la disponibilidad de estas URLs y "
        "corrija posibles problemas de servidor o redirecciones rotas."
    ),
    "orphan_page": (
        "{n} página(s) huérfana(s): hay documentos ingeridos de páginas que ya "
        "no existen en el sitio; retire esos documentos del corpus."
    ),
}

_DEFAULT_RECOMMENDATION = (
    "{n} hallazgo(s) de tipo '{type}': revise las páginas afectadas."
)


def _make_recommendation(finding_type: str, count: int) -> str:
    template = _RECOMMENDATIONS.get(finding_type, _DEFAULT_RECOMMENDATION)
    return template.format(n=count, type=finding_type)


def _to_view(orm_finding: Any) -> ContentFindingView:
    signal = getattr(orm_finding, "signal_json", {}) or {}
    explanation = signal.get("explanation") or signal.get("error_message")
    related_url = signal.get("superseded_by")
    return ContentFindingView(
        id=orm_finding.id,
        finding_type=orm_finding.finding_type,
        severity=orm_finding.severity,
        status=orm_finding.status,
        confidence=orm_finding.confidence,
        page_url=orm_finding.source_url,
        related_page_url=related_url,
        detected_at=orm_finding.detected_at,
        explanation=explanation,
    )


class WebQualityReportBuilder:
    """Agrega hallazgos de un sitio en un WebQualityReport."""

    def __init__(self, findings_repo: Any, site_repo: Any) -> None:
        self._findings_repo = findings_repo
        self._site_repo = site_repo

    async def build(
        self,
        site_id: uuid.UUID,
        *,
        status_filter: Sequence[str] = ("new", "confirmed"),
    ) -> WebQualityReport:
        now = datetime.now(timezone.utc)

        site = await self._site_repo.get(site_id)
        site_name = site.name if site else str(site_id)

        # Recopilar hallazgos para cada status del filtro
        all_findings: list[Any] = []
        seen_ids: set[uuid.UUID] = set()
        for st in status_filter:
            for f in await self._findings_repo.list_by_site(site_id, status=st):
                if f.id not in seen_ids:
                    all_findings.append(f)
                    seen_ids.add(f.id)

        if not all_findings:
            return WebQualityReport(
                site_id=site_id,
                site_name=site_name,
                generated_at=now,
                totals_by_type={},
                totals_by_severity={},
                sections=[],
                pdf_available=se_puede_convertir_a_pdf(),
            )

        # Agrupar por tipo
        by_type: dict[str, list[Any]] = defaultdict(list)
        for f in all_findings:
            by_type[f.finding_type].append(f)

        # Totales
        totals_by_type = {ft: len(findings) for ft, findings in by_type.items()}
        totals_by_severity: dict[str, int] = defaultdict(int)
        for f in all_findings:
            totals_by_severity[f.severity] += 1

        # Secciones
        sections: list[FindingTypeSection] = []
        for finding_type, findings in sorted(by_type.items()):
            sections.append(
                FindingTypeSection(
                    finding_type=finding_type,
                    findings=[_to_view(f) for f in findings],
                    recommendation=_make_recommendation(finding_type, len(findings)),
                )
            )

        return WebQualityReport(
            site_id=site_id,
            site_name=site_name,
            generated_at=now,
            totals_by_type=totals_by_type,
            totals_by_severity=dict(totals_by_severity),
            sections=sections,
            # CUR.8 — para que la pantalla ofrezca el PDF sólo si esta máquina puede hacer uno.
            pdf_available=se_puede_convertir_a_pdf(),
        )
