import { useTranslation } from 'react-i18next'
import { ChevronDown, ChevronUp, Loader2, Trash2 } from 'lucide-react'

import type { IngestionJob } from '@/shared/api/generated/model'
import { Progress } from '@/components/ui/progress'
import { JobStatusBadge } from './DocumentBadges'

/**
 * Detalle técnico de la ingesta, plegado por defecto.
 *
 * Va cerrado porque el administrador que gestiona el corpus razona en documentos, no en
 * trabajos; los jobs sólo importan cuando algo se atasca. Quien decide si consultar el
 * servidor es la página: mientras `open` sea `false` no hay consulta que hacer.
 *
 * Un job en curso no se puede borrar — lo impide también el servidor con un 409.
 */
export function IngestionJobsPanel({
  open,
  onToggle,
  jobs,
  isLoading,
  onDeleteJob,
}: {
  open: boolean
  onToggle: () => void
  jobs: IngestionJob[]
  isLoading: boolean
  onDeleteJob: (jobId: string) => void
}) {
  const { t } = useTranslation('admin')
  const { t: tc } = useTranslation('common')

  return (
    <div className="border rounded-lg overflow-hidden">
      <button
        type="button"
        onClick={onToggle}
        className="w-full flex items-center justify-between p-4 bg-muted/10 text-sm font-medium hover:bg-muted/20 transition-colors"
      >
        <span>{t('hub.jobs_technical')}</span>
        {open ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
      </button>
      {open && (
        isLoading ? (
          <div className="p-6 text-center text-muted-foreground text-sm flex items-center justify-center gap-2">
            <Loader2 className="w-4 h-4 animate-spin" />{tc('loading')}
          </div>
        ) : jobs.length === 0 ? (
          <div className="p-6 text-center text-muted-foreground text-sm">
            {t('hub.no_jobs')}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b bg-muted/10 text-left text-muted-foreground">
                  <th className="px-4 py-3 font-medium">{t('hub.job_file')}</th>
                  <th className="px-4 py-3 font-medium">{t('hub.job_status')}</th>
                  <th className="px-4 py-3 font-medium">{t('hub.job_chunks')}</th>
                  <th className="px-4 py-3 font-medium">{t('hub.job_date')}</th>
                  <th className="px-4 py-3" />
                </tr>
              </thead>
              <tbody>
                {jobs.map(job => (
                  <tr key={job.id} className="border-b last:border-0 hover:bg-accent/20">
                    <td className="px-4 py-3 max-w-[200px] truncate text-xs" title={job.original_filename ?? job.source_url}>
                      {job.original_filename ?? job.source_url.split('/').pop() ?? 'Documento'}
                    </td>
                    <td className="px-4 py-3"><JobStatusBadge status={job.status} error={job.error_message ?? null} /></td>
                    <td className="px-4 py-3 text-xs text-muted-foreground">
                      {job.status === 'running'
                        ? <div className="w-16"><Progress value={null} className="h-2" /></div>
                        : job.chunks_processed}
                    </td>
                    <td className="px-4 py-3 text-xs text-muted-foreground">{new Date(job.created_at).toLocaleString()}</td>
                    <td className="px-4 py-3">
                      <button
                        type="button"
                        onClick={() => onDeleteJob(job.id)}
                        // #277 — lo decide el servidor, con la regla que aplica al borrar.
                        disabled={!job.acciones_permitidas.includes('borrar')}
                        className="p-1 text-muted-foreground hover:text-destructive disabled:opacity-30 transition-colors"
                        title={t('hub.delete_job')}
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      )}
    </div>
  )
}
