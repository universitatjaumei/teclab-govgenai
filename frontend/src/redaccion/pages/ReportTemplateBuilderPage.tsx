import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useQueryClient } from '@tanstack/react-query'
import {
  useListTemplates,
  usePatchTemplate,
  useArchiveTemplate,
  useRestoreTemplate,
  getListTemplatesQueryKey,
} from '@/shared/api/generated/hub-redaccion/hub-redaccion'
import type { TemplateOut } from '@/shared/api/generated/model'
import { useAuth } from '@/shared/auth'

/**
 * Gestión de plantillas de informe (GUI.1 + GUI.2).
 *
 * Encontrado por el usuario probando: «se han creado muchas plantillas, se ven en dos pantallas
 * y no hay ninguna opción para borrarlas o editarlas». No faltaba el botón: faltaban los
 * endpoints, así que la lista de una instalación sólo podía crecer.
 *
 * Dos decisiones que se ven aquí:
 *
 * 1. **Se retira, no se borra.** Un informe firmado no puede quedarse sin la plantilla con la
 *    que se hizo, así que archivar la saca de las listas y deja los informes intactos. El
 *    diálogo lo dice, porque quien retira algo necesita saber qué se lleva por delante.
 * 2. **Aquí ya no se crean plantillas.** El alta que había mandaba `spec_json: {}`: una
 *    plantilla sin bloques da un informe vacío y no hay editor de bloques con el que
 *    arreglarla. Se crea describiendo el informe, que es donde el modelo propone la estructura.
 */
export function ReportTemplateBuilderPage() {
  const { t } = useTranslation('redaccion')
  const { t: tc } = useTranslation('common')
  const { user } = useAuth()
  const qc = useQueryClient()

  const [verRetiradas, setVerRetiradas] = useState(false)
  const [renombrando, setRenombrando] = useState<string | null>(null)
  const [nombreNuevo, setNombreNuevo] = useState('')
  const [aRetirar, setARetirar] = useState<TemplateOut | null>(null)

  const { data: plantillasRaw, isLoading } = useListTemplates(
    verRetiradas ? { include_archived: true } : undefined,
  )
  const plantillas = (plantillasRaw as unknown as TemplateOut[] | undefined) ?? []

  const { mutate: renombrar, isPending: renombrandoEnCurso } = usePatchTemplate()
  const { mutate: archivar, isPending: archivandoEnCurso } = useArchiveTemplate()
  const { mutate: recuperar } = useRestoreTemplate()

  if (!user || !['superadmin', 'admin'].includes(user.role)) {
    return <div data-testid="access-denied">{t('templates.no_permission')}</div>
  }

  if (isLoading) return <div>{tc('loading')}</div>

  const refrescar = { onSuccess: () => qc.invalidateQueries({ queryKey: getListTemplatesQueryKey() }) }

  function empezarARenombrar(plantilla: TemplateOut) {
    setRenombrando(plantilla.id)
    setNombreNuevo(plantilla.name)
  }

  function guardarNombre(id: string) {
    renombrar(
      { templateId: id, data: { name: nombreNuevo.trim() } },
      { ...refrescar, onSettled: () => setRenombrando(null) },
    )
  }

  function confirmarRetirada() {
    if (!aRetirar) return
    archivar({ templateId: aRetirar.id }, { ...refrescar, onSettled: () => setARetirar(null) })
  }

  return (
    <div className="space-y-4 p-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            data-testid="toggle-archivadas"
            checked={verRetiradas}
            onChange={(e) => setVerRetiradas(e.target.checked)}
          />
          {t('templates.show_archived')}
        </label>
        <Link
          data-testid="enlace-crear-describiendo"
          to="/redaccion/draft"
          className="px-3 py-1.5 text-sm bg-primary text-primary-foreground rounded"
        >
          {t('templates.create_by_describing')}
        </Link>
      </div>

      {plantillas.length === 0 && (
        <p className="text-sm text-muted-foreground">{t('templates.empty')}</p>
      )}

      <ul className="space-y-2">
        {plantillas.map((tmpl) => (
          <li
            key={tmpl.id}
            data-testid={`template-item-${tmpl.id}`}
            className="flex items-center justify-between gap-3 flex-wrap px-3 py-2 border rounded"
          >
            {renombrando === tmpl.id ? (
              <div className="flex items-center gap-2 flex-1">
                <input
                  data-testid={`input-nombre-${tmpl.id}`}
                  value={nombreNuevo}
                  onChange={(e) => setNombreNuevo(e.target.value)}
                  aria-label={t('templates.name_label')}
                  className="flex-1 border rounded px-2 py-1 text-sm"
                />
                <button
                  type="button"
                  data-testid={`btn-guardar-nombre-${tmpl.id}`}
                  disabled={!nombreNuevo.trim() || renombrandoEnCurso}
                  onClick={() => guardarNombre(tmpl.id)}
                  className="px-3 py-1 text-xs bg-primary text-primary-foreground rounded disabled:opacity-50"
                >
                  {t('templates.save_name')}
                </button>
                <button
                  type="button"
                  data-testid={`btn-cancelar-nombre-${tmpl.id}`}
                  onClick={() => setRenombrando(null)}
                  className="px-3 py-1 text-xs border rounded"
                >
                  {tc('cancel')}
                </button>
              </div>
            ) : (
              <>
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-sm font-medium">{tmpl.name}</span>
                  <span className="text-xs text-muted-foreground">{tmpl.report_profile}</span>
                  {tmpl.archived && (
                    <span
                      data-testid={`marca-archivada-${tmpl.id}`}
                      className="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground"
                    >
                      {t('templates.archived_badge')}
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  {tmpl.archived ? (
                    <button
                      type="button"
                      data-testid={`btn-recuperar-${tmpl.id}`}
                      onClick={() => recuperar({ templateId: tmpl.id }, refrescar)}
                      className="px-3 py-1 text-xs border rounded hover:bg-accent"
                    >
                      {t('templates.restore')}
                    </button>
                  ) : (
                    <>
                      <button
                        type="button"
                        data-testid={`btn-renombrar-${tmpl.id}`}
                        onClick={() => empezarARenombrar(tmpl)}
                        className="px-3 py-1 text-xs border rounded hover:bg-accent"
                      >
                        {t('templates.rename')}
                      </button>
                      <button
                        type="button"
                        data-testid={`btn-archivar-${tmpl.id}`}
                        onClick={() => setARetirar(tmpl)}
                        className="px-3 py-1 text-xs border rounded hover:bg-accent"
                      >
                        {t('templates.archive')}
                      </button>
                    </>
                  )}
                </div>
              </>
            )}
          </li>
        ))}
      </ul>

      {/* Confirmación: nada se retira de un solo clic, y el aviso dice qué NO se pierde.
          Va **encima** de la página y no al final: con diecisiete plantillas en la lista, un
          cuadro al final del documento queda fuera de pantalla y pulsar «Retirar» parece no
          hacer nada. Visto en el navegador al capturar la guía. */}
      {aRetirar && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
        <div
          role="dialog"
          aria-modal="true"
          aria-label={t('templates.archive_title')}
          className="border rounded-lg p-4 bg-card space-y-3 max-w-lg w-full shadow-lg"
        >
          <h2 className="text-sm font-medium">
            {t('templates.archive_title', { name: aRetirar.name })}
          </h2>
          <p data-testid="aviso-archivar" className="text-sm text-muted-foreground">
            {t('templates.archive_warning')}
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              data-testid="confirmar-archivar"
              disabled={archivandoEnCurso}
              onClick={confirmarRetirada}
              className="px-4 py-2 text-sm bg-destructive text-destructive-foreground rounded disabled:opacity-50"
            >
              {t('templates.archive_confirm')}
            </button>
            <button
              type="button"
              data-testid="cancelar-archivar"
              onClick={() => setARetirar(null)}
              className="px-4 py-2 text-sm border rounded"
            >
              {tc('cancel')}
            </button>
          </div>
        </div>
        </div>
      )}
    </div>
  )
}
