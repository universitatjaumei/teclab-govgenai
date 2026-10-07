import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import {
  useListTemplates,
  useCreateWorkspace,
} from '@/shared/api/generated/hub-redaccion/hub-redaccion'
import type { TemplateOut } from '@/shared/api/generated/model'

export function GenericReportWizard() {
  const { t } = useTranslation('common')
  const navigate = useNavigate()
  const { data: templatesRaw, isLoading } = useListTemplates()
  const templates = (templatesRaw as unknown as TemplateOut[] | undefined) ?? []
  const { mutate: createWorkspace, isPending } = useCreateWorkspace()

  if (isLoading) return <div>{t('loading')}</div>

  function handleCreate(template: TemplateOut) {
    if (!template.current_version_id) return
    createWorkspace(
      { data: { template_version_id: template.current_version_id } },
      // Sin esto, el informe se creaba en la base y en pantalla no cambiaba nada:
      // indistinguible de un botón roto (VER.4).
      { onSuccess: (creado) => navigate(`/redaccion/workspaces/${creado.workspace_id}`) },
    )
  }

  return (
    <div className="space-y-2 p-4">
      {templates.map(tmpl => (
        <div
          key={tmpl.id}
          data-testid={`template-item-${tmpl.id}`}
          className="flex items-center justify-between px-4 py-3 border rounded-md bg-card"
        >
          <div>
            <span className="text-sm font-medium">{tmpl.name}</span>
            <span className="ml-2 text-xs text-muted-foreground">{tmpl.report_profile}</span>
          </div>
          <button
            type="button"
            data-testid={`btn-create-workspace-${tmpl.id}`}
            disabled={isPending || !tmpl.current_version_id}
            onClick={() => handleCreate(tmpl)}
            className="px-3 py-1 text-xs bg-primary text-primary-foreground rounded disabled:opacity-50"
          >
            {t('create_report')}
          </button>
        </div>
      ))}
    </div>
  )
}
