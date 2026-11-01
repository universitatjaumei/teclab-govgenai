import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQueryClient } from '@tanstack/react-query'
import { useListSites } from '@/shared/api/generated/hub-sites/hub-sites'
import {
  useAnalyzeSite,
  getListSiteFindingsQueryKey,
} from '@/shared/api/generated/hub-content-quality/hub-content-quality'
import type { SiteView } from '@/shared/api/generated/model'
import { mensajeDelFallo } from '@/utilidades/mensajeDelFallo'
import { WebQualityReportViewer } from './WebQualityReportViewer'

/**
 * Auditoría (CUR.2): el informe de calidad vale por sí solo, sin chatbot — es la salida
 * principal de la curación, no un efecto secundario del RAG (`docs/DECISION_CURACION_SEPARADA.md`).
 */
export function AuditPage() {
  const { t } = useTranslation('curation')
  const qc = useQueryClient()

  const [selectedSiteId, setSelectedSiteId] = useState<string>('')

  const { data: sites = [] } = useListSites()

  const analyzeMutation = useAnalyzeSite({
    mutation: {
      onSuccess: () => {
        if (selectedSiteId) {
          qc.invalidateQueries({ queryKey: getListSiteFindingsQueryKey(selectedSiteId) })
        }
      },
    },
  })

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">{t('quality_title')}</h1>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <select
          value={selectedSiteId}
          onChange={(e) => setSelectedSiteId(e.target.value)}
          className="border rounded px-2 py-1.5 text-sm"
          aria-label={t('select_site')}
        >
          <option value="">{t('select_site')}</option>
          {(sites as SiteView[]).map((s) => (
            <option key={s.id} value={s.id}>{s.name}</option>
          ))}
        </select>
        <button
          className="px-3 py-1.5 rounded border text-sm disabled:opacity-50"
          disabled={!selectedSiteId || analyzeMutation.isPending}
          onClick={() => selectedSiteId && analyzeMutation.mutate({ siteId: selectedSiteId })}
        >
          {t('analyze_now')}
        </button>
      </div>

      {/* #360 — lanza lo mismo que «Rastrear ahora» y, como él, no decía nada: ni que había
          empezado ni, ahora que el servidor responde 409 si el sitio ya se rastrea, por qué no. */}
      {analyzeMutation.variables?.siteId === selectedSiteId && analyzeMutation.isSuccess && (
        <p role="status" className="text-xs text-green-800">{t('crawl_started')}</p>
      )}
      {analyzeMutation.variables?.siteId === selectedSiteId && analyzeMutation.isError && (
        <p role="alert" className="text-xs text-destructive">
          {t('crawl_failed', { error: mensajeDelFallo(analyzeMutation.error, t('crawl_failed_unknown')) })}
        </p>
      )}

      {selectedSiteId && <WebQualityReportViewer siteId={selectedSiteId} />}
    </div>
  )
}
