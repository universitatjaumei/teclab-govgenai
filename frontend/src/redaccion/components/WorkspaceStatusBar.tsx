import { useTranslation } from 'react-i18next'
import { useGetWorkspaceById } from '@/shared/api/generated/hub-redaccion/hub-redaccion'
import type { WorkspaceOut } from '@/shared/api/generated/model'
import { StatusBadge } from '@/shared/components/StatusBadge'
import { mapWorkspaceStatusToUserLabel } from '../utils/statusLabels'

const STATUS_ORDER = [
  'draft', 'ingesting', 'extracting', 'drafting',
  'in_review', 'assembled', 'exported',
]

interface Props {
  workspaceId: string
}

export function WorkspaceStatusBar({ workspaceId }: Props) {
  const { t } = useTranslation('common')
  const { t: tR } = useTranslation('redaccion')
  const { data: workspaceRaw, isLoading } = useGetWorkspaceById(workspaceId)
  const workspace = workspaceRaw as unknown as WorkspaceOut | undefined

  if (isLoading) return <div>{t('loading')}</div>
  if (!workspace) return null

  const { labelKey, tone } = mapWorkspaceStatusToUserLabel(workspace.status)
  const statusIndex = STATUS_ORDER.indexOf(workspace.status)

  return (
    <div className="flex items-center gap-3 px-4 py-2 bg-muted/30 border-b text-sm">
      <StatusBadge
        label={tR(labelKey)}
        tone={tone}
        data-testid="workspace-status-badge"
      />

      <div className="flex items-center gap-1">
        {STATUS_ORDER.map((s, i) => (
          <div
            key={s}
            className={`h-1.5 w-6 rounded-full ${
              i <= statusIndex ? 'bg-primary' : 'bg-muted'
            }`}
          />
        ))}
      </div>

    </div>
  )
}
