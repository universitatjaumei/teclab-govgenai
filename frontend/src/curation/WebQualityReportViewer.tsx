import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useGetSiteQualityReport } from '@/shared/api/generated/hub-content-quality/hub-content-quality'
import type { WebQualityReport, FindingTypeSection } from '@/shared/api/generated/model'
import { descargarConAutorizacion } from '@/shared/api/download'
import { enlaceExterno } from '@/shared/enlaces/enlaceExterno'

interface Props {
  siteId: string
}

export function WebQualityReportViewer({ siteId }: Props) {
  const { t } = useTranslation('curation')
  const { t: tc } = useTranslation('common')

  const { data: report, isLoading } = useGetSiteQualityReport(siteId)
  // CUR.4 — que secciones del informe se estan viendo enteras.
  const [desplegadas, setDesplegadas] = useState<Set<string>>(new Set())
  // CUR.5 — un fallo de descarga tiene que verse en la pantalla, no en la consola.
  const [errorDeDescarga, setErrorDeDescarga] = useState<string | null>(null)
  const alternar = (tipo: string) =>
    setDesplegadas((previas) => {
      const siguiente = new Set(previas)
      if (siguiente.has(tipo)) siguiente.delete(tipo)
      else siguiente.add(tipo)
      return siguiente
    })

  if (isLoading) return <p className="text-muted-foreground">{tc('loading')}</p>
  if (!report) return null

  const typedReport = report as WebQualityReport

  /**
   * CUR.5 — la descarga se pide con el token puesto.
   *
   * Era un `<a href download>`, o sea una navegación del navegador: sin cabecera de autorización,
   * 401, y el error de descarga de Chrome —«el fitxer no es troba disponible»—, que no menciona el
   * 401 y parece que el informe no exista.
   */
  const descargar = async (formato: 'docx' | 'pdf') => {
    setErrorDeDescarga(null)
    try {
      await descargarConAutorizacion(
        `/api/v1/hub/sites/${siteId}/report/export?format=${formato}`,
        `informe_calidad_${siteId}.${formato}`,
      )
    } catch (e) {
      setErrorDeDescarga(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <div className="border rounded-lg p-4 space-y-4 bg-muted/20" aria-label={t('report_title')}>
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-lg font-semibold">{t('report_title')} — {typedReport.site_name}</h2>
          <p className="text-xs text-muted-foreground">
            {t('report_generated')}: {new Date(typedReport.generated_at).toLocaleString()}
          </p>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            data-testid="btn-descargar-docx"
            onClick={() => descargar('docx')}
            className="text-xs px-3 py-1.5 rounded border hover:bg-accent"
          >
            {t('download_docx')}
          </button>
          {/* CUR.8 — el PDF sólo si esta instalación puede hacer uno. Del usuario: «o se quita el
              botón o se permite que la descarga sea en pdf». Que el fichero no mienta (VER.7) era
              lo mínimo; un botón que promete lo que no puede dar sigue siendo una promesa
              incumplida. Lo decide el servidor, que es quien sabe si tiene LibreOffice. */}
          {typedReport.pdf_available && (
            <button
              type="button"
              data-testid="btn-descargar-pdf"
              onClick={() => descargar('pdf')}
              className="text-xs px-3 py-1.5 rounded border hover:bg-accent"
            >
              {t('download_pdf')}
            </button>
          )}
        </div>
      </div>

      {!typedReport.pdf_available && (
        <p data-testid="aviso-sin-pdf" className="text-xs text-muted-foreground">
          {t('pdf_unavailable')}
        </p>
      )}

      {errorDeDescarga && (
        <p data-testid="error-descarga" className="text-xs text-destructive">
          {t('download_failed')}: {errorDeDescarga}
        </p>
      )}

      {/* Totals */}
      {Object.keys(typedReport.totals_by_type).length === 0 ? (
        <p className="text-sm text-muted-foreground">{t('report_no_findings')}</p>
      ) : (
        <div>
          <h3 className="text-sm font-semibold mb-2">{t('report_totals')}</h3>
          <div className="flex flex-wrap gap-2">
            {Object.entries(typedReport.totals_by_type).map(([type, count]) => (
              <span key={type} className="text-xs px-2 py-1 rounded bg-accent">
                {t(`type_${type}` as Parameters<typeof t>[0])}: <strong>{count}</strong>
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Sections */}
      {typedReport.sections.length > 0 && (
        <div className="space-y-4">
          <h3 className="text-sm font-semibold">{t('report_sections')}</h3>
          {typedReport.sections.map((section: FindingTypeSection) => (
            <div key={section.finding_type} className="border rounded p-3 space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium">
                  {t(`type_${section.finding_type}` as Parameters<typeof t>[0])} ({section.findings.length})
                </span>
              </div>
              <p className="text-xs text-muted-foreground italic">{t('report_recommendation')}: {section.recommendation}</p>
              {/* CUR.4 — las URLs, clickables y en otra pestaña; y el «+N más» se despliega en vez
                  de quedarse como un texto muerto. Del usuario: «ahora hay que copiar y pegar». */}
              <ul className="text-xs space-y-1">
                {(desplegadas.has(section.finding_type)
                  ? section.findings
                  : section.findings.slice(0, 5)
                ).map((f) => (
                  <li key={String(f.id)} className="flex gap-2 flex-wrap">
                    {f.page_url ? (
                      <a
                        href={enlaceExterno(f.page_url)}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-primary underline break-all"
                      >
                        {f.page_url}
                      </a>
                    ) : (
                      <span>—</span>
                    )}
                    {f.related_page_url && (
                      <span className="text-muted-foreground">
                        →{' '}
                        <a
                          href={enlaceExterno(f.related_page_url)}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-primary underline break-all"
                        >
                          {f.related_page_url}
                        </a>
                      </span>
                    )}
                  </li>
                ))}
                {section.findings.length > 5 && (
                  <li>
                    <button
                      type="button"
                      data-testid={`btn-desplegar-seccion-${section.finding_type}`}
                      onClick={() => alternar(section.finding_type)}
                      className="text-primary underline"
                    >
                      {desplegadas.has(section.finding_type)
                        ? t('collapse_versions')
                        : `+${section.findings.length - 5} ${t('show_rest')}`}
                    </button>
                  </li>
                )}
              </ul>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
