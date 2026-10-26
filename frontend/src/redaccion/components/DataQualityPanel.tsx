import { useTranslation } from 'react-i18next'
import { useGetWorkspaceWarnings } from '@/shared/api/generated/hub-redaccion/hub-redaccion'

const SEVERITY_CLASSES: Record<string, string> = {
  error: 'bg-destructive/10 text-destructive border-destructive/30',
  warning: 'bg-yellow-50 text-yellow-700 border-yellow-200',
  info: 'bg-blue-50 text-blue-700 border-blue-200',
}

interface Props {
  workspaceId: string
}

export function DataQualityPanel({ workspaceId }: Props) {
  const { t } = useTranslation('common')
  const { data: warningsRaw, isLoading } = useGetWorkspaceWarnings(workspaceId)
  const warnings = warningsRaw ?? []

  if (isLoading) return <div>{t('loading')}</div>
  if (warnings.length === 0) return null

  return (
    <ul className="space-y-1 p-3">
      {warnings.map((w, i) => (
        <li
          key={i}
          className={`flex items-start gap-2 text-xs px-3 py-2 rounded border ${SEVERITY_CLASSES[w.severity ?? 'warning'] ?? SEVERITY_CLASSES.warning}`}
        >
          <span
            data-testid={`severity-${w.severity}`}
            className="font-medium uppercase"
          >
            {w.severity}
          </span>
          <span>{w.message}</span>
        </li>
      ))}
    </ul>
  )
}
