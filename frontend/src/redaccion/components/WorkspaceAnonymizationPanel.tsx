/**
 * Panel de auditoría NER y configuración del modo de anonimización por workspace.
 * Deploy: edge — Fase 13.2
 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQueryClient } from '@tanstack/react-query'

import type { AnonymizationMode } from '@/shared/api/generated/model'
// AIS.4 — el cliente generado, no un módulo a mano. El anterior llamaba con `fetch` crudo y sin
// credencial, así que los tres endpoints —que exigen sesión y módulo— devolvían 401 y este panel
// no funcionaba desde el navegador. El hook generado pasa por el interceptor de
// `shared/api/client.ts`, que es el único sitio donde se construye la cabecera.
import {
  getGetAnonymizationSummaryQueryKey,
  useGetAnonymizationSummary,
  usePatchAnonymizationMode,
} from '@/shared/api/generated/redaccion-anonymization/redaccion-anonymization'

interface WorkspaceAnonymizationPanelProps {
  workspaceId: string
  workspaceStatus: string
}

const MODES = [
  'off',
  'detect_only',
  'replace',
  'replace_with_disposition_7',
] as const

const LOCKED_STATUSES = new Set(['drafting', 'in_review', 'assembled', 'exported'])

export function WorkspaceAnonymizationPanel({
  workspaceId,
  workspaceStatus,
}: WorkspaceAnonymizationPanelProps) {
  const { t } = useTranslation('redaccion')
  const isLocked = LOCKED_STATUSES.has(workspaceStatus)

  const qc = useQueryClient()
  const { data: summary, isLoading } = useGetAnonymizationSummary(workspaceId)

  // La invalidación la hacía el módulo manual en su `onSuccess`; el cliente generado no opina
  // sobre la caché, así que se declara aquí — y con la clave que él mismo construye, no con una
  // cadena escrita a mano que dejaría de coincidir en cuanto cambiara la ruta.
  const refrescarResumen = () => {
    qc.invalidateQueries({ queryKey: getGetAnonymizationSummaryQueryKey(workspaceId) })
  }

  const patchMode = usePatchAnonymizationMode({ mutation: { onSuccess: refrescarResumen } })

  const currentMode = summary?.current_workspace_mode ?? 'replace'
  const [selectedMode, setSelectedMode] = useState<string>(currentMode)

  const handleModeChange = (mode: string) => {
    if (isLocked) return
    setSelectedMode(mode)
  }

  const handleApplyMode = () => {
    // El hook generado recibe la ruta y el cuerpo juntos: el `workspaceId` ya no va curried.
    patchMode.mutate({ workspaceId, data: { mode: selectedMode as AnonymizationMode } })
  }

  // Issue #169 — este botón refresca la vista, que es lo que de verdad se quería de él: ver el
  // resultado de una anonimización ya aplicada, o el de la iteración anterior.
  //
  // Llamaba a `POST /re-analyze`, que devolvía 202 «encolado» **sin encolar nada**. Se retiró esa
  // ruta en vez de implementarle la cola, porque el resumen ya lo sirve el `GET`: desde la issue
  // #98 cada ejecución escribe el suyo en el manifiesto.
  const handleRefrescar = () => {
    refrescarResumen()
  }

  if (isLoading) {
    return <div className="p-4 text-sm text-muted-foreground">{t('anonymization.loading', 'Cargando…')}</div>
  }

  return (
    <div data-testid="workspace-anonymization-panel" className="space-y-4 p-4">
      {/* Sección 1 — Modo */}
      <section aria-labelledby="anon-mode-heading">
        <h3 id="anon-mode-heading" className="text-sm font-semibold mb-2">
          {t('anonymization.mode_label')}
        </h3>

        {isLocked && (
          <p
            data-testid="anon-mode-locked-msg"
            className="text-xs text-amber-600 mb-2"
          >
            {t('anonymization.mode_locked')}
          </p>
        )}

        <div className="space-y-2">
          {MODES.map(mode => (
            <label key={mode} className="flex items-start gap-2 cursor-pointer">
              <input
                type="radio"
                name="anon-mode"
                value={mode}
                checked={(summary?.current_workspace_mode ?? selectedMode) === mode}
                disabled={isLocked}
                onChange={() => handleModeChange(mode)}
                className="mt-0.5"
              />
              <span className="text-sm">
                <span className="font-medium">{t(`anonymization.modes.${mode}`)}</span>
                <br />
                <span className="text-xs text-muted-foreground">
                  {t(`anonymization.mode_descriptions.${mode}`)}
                </span>
              </span>
            </label>
          ))}
        </div>

        {(summary?.current_workspace_mode === 'replace_with_disposition_7') && (
          <span
            data-testid="anon-badge-lopdgdd"
            className="inline-block mt-2 px-2 py-0.5 text-xs font-bold bg-blue-100 text-blue-800 rounded"
          >
            {t('anonymization.badge_lopdgdd')}
          </span>
        )}

        {!isLocked && (
          <button
            type="button"
            data-testid="btn-change-mode"
            onClick={handleApplyMode}
            disabled={patchMode.isPending}
            className="mt-3 text-sm px-3 py-1 bg-primary text-primary-foreground rounded"
          >
            {t('anonymization.btn_change_mode')}
          </button>
        )}
      </section>

      {/* Sección 2 — Tabla de conteos */}
      <section aria-labelledby="anon-counts-heading">
        <h3 id="anon-counts-heading" className="text-sm font-semibold mb-2">
          {t('anonymization.table_title')}
        </h3>

        {/*
          Issue #170 — sin modelo lingüístico la anonimización sigue cogiendo DNI, correos, IBAN
          y las cabeceras de formulario, y deja pasar los nombres que sólo aparecen dentro de la
          prosa. El resumen se vería idéntico: sus conteos, su total. Sin este aviso, «no había
          nombres» y «no se buscaron» son la misma pantalla.

          La comparación es explícita contra `false` porque `null` es otra cosa: en modo `off` no
          se escaneó, y avisar allí sería reclamar una capa que nadie pidió.
        */}
        {summary?.ner_disponible === false && (
          <p
            data-testid="anon-ner-degradado"
            className="text-xs text-amber-600 mb-2"
          >
            {t('anonymization.ner_no_disponible')}
          </p>
        )}

        {!summary || summary.total_spans === 0 ? (
          <p className="text-xs text-muted-foreground">{t('anonymization.no_run')}</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left text-xs text-muted-foreground">
                <th className="py-1 pr-4">{t('anonymization.col_type')}</th>
                <th className="py-1">{t('anonymization.col_count')}</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(summary.counts_by_type).map(([type, count]) => (
                <tr key={type} className="border-b last:border-0">
                  <td className="py-1 pr-4 font-mono text-xs">{type}</td>
                  <td
                    data-testid={`anon-type-${type}`}
                    className="py-1"
                  >
                    {count}
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <td className="py-1 text-xs font-semibold">{t('anonymization.total')}</td>
                <td
                  data-testid="anon-total-spans"
                  className="py-1 font-semibold"
                >
                  {summary.total_spans}
                </td>
              </tr>
            </tfoot>
          </table>
        )}
      </section>

      {/* Sección 3 — Acciones */}
      <section>
        <button
          type="button"
          data-testid="btn-refrescar-resumen"
          onClick={handleRefrescar}
          className="text-sm px-3 py-1 border rounded"
        >
          {t('anonymization.btn_refrescar')}
        </button>
      </section>
    </div>
  )
}
