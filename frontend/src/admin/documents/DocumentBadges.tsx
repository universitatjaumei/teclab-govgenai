import { AlertCircle, CheckCircle2, Clock, FileText, Globe, Loader2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { LANG_BADGE } from './constants'

/** Icono del origen del documento, junto al título en la tabla. */
export function SourceKindIcon({ kind }: { kind: string }) {
  if (kind === 'crawler') return <Globe className="w-4 h-4 text-muted-foreground shrink-0" />
  return <FileText className="w-4 h-4 text-muted-foreground shrink-0" />
}

/** Distintivo del origen: rastreado de la web o subido como Markdown (EXT.1). */
export function SourceKindBadge({ kind }: { kind: string }) {
  const { t } = useTranslation('admin')
  if (kind === 'crawler')
    return <span className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded bg-purple-100 text-purple-700 border border-purple-200"><Globe className="w-3 h-3" />{t('hub.kind_crawler')}</span>
  return <span className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded bg-gray-100 text-gray-700 border border-gray-200"><FileText className="w-3 h-3" />{t('hub.kind_upload')}</span>
}

/** Idioma del documento. Un código sin color asignado cae en gris, no rompe. */
export function LanguageBadge({ language }: { language: string }) {
  const cls = LANG_BADGE[language] ?? 'bg-gray-100 text-gray-700 border-gray-200'
  return (
    <span className={`inline-flex items-center text-xs px-2 py-0.5 rounded border font-medium ${cls}`}>
      {language.toUpperCase()}
    </span>
  )
}

/**
 * Estado de un trabajo de ingesta.
 *
 * La rama `default` es deliberada: `status` viaja como `str` en el contrato (ver CAL.2), así
 * que un valor que este código no conozca se pinta «En cola» en vez de dejar la celda vacía.
 */
export function JobStatusBadge({
  status,
  error,
  avisos = [],
}: {
  status: string
  error: string | null
  /** #285 — lo que un trabajo completado omitió a propósito, aparte de los fallos. */
  avisos?: readonly string[]
}) {
  const { t } = useTranslation('admin')
  switch (status) {
    case 'completed': return (
      <div>
        <span className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded bg-green-100 text-green-700 border border-green-200"><CheckCircle2 className="w-3 h-3" /> {t('hub.job_status_completed')}</span>
        {avisos.map(aviso => <p key={aviso} className="text-xs text-amber-700 mt-1 max-w-xs break-words">{aviso}</p>)}
      </div>
    )
    case 'running':   return <span className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded bg-blue-100 text-blue-700 border border-blue-200"><Loader2 className="w-3 h-3 animate-spin" /> {t('hub.job_status_running')}</span>
    case 'failed':    return (
      <div>
        <span className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded bg-red-100 text-red-700 border border-red-200"><AlertCircle className="w-3 h-3" /> {t('hub.job_status_failed')}</span>
        {error && <p className="text-xs text-red-600 mt-1 max-w-xs break-words">{error}</p>}
      </div>
    )
    default:          return <span className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded bg-gray-100 text-gray-700 border border-gray-200"><Clock className="w-3 h-3" /> {t('hub.job_status_pending')}</span>
  }
}
