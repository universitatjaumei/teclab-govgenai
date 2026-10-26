import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQueryClient } from '@tanstack/react-query'
import { useListSites } from '@/shared/api/generated/hub-sites/hub-sites'
import {
  useListSiteFindings,
  useTransitionFinding,
  getListSiteFindingsQueryKey,
} from '@/shared/api/generated/hub-content-quality/hub-content-quality'
import type { SiteView } from '@/shared/api/generated/model'
import { ContentGapsPanel } from './ContentGapsPanel'
import { PageContentDialog } from './PageContentDialog'
import { razonDelHallazgo, urlRelacionada } from './razonDelHallazgo'
import { enlaceExterno } from '@/shared/enlaces/enlaceExterno'
import type {
  HallazgoOut,
  HallazgoOutAccionesPermitidasItem,
  HallazgoOutSeverity,
} from '@/shared/api/generated/model'

interface Version {
  url: string
  date?: string | null
}

/** Las versiones que un hallazgo de grupo lleva dentro: serie por años o duplicado exacto. */
function versionesDe(f: HallazgoOut): Version[] {
  const versiones = f.signal?.versions
  return Array.isArray(versiones) ? (versiones as Version[]) : []
}

/** El texto del botón que lleva un hallazgo a cada estado. Qué botones hay lo dice el servidor. */
const ETIQUETA_DE_LA_ACCION = {
  confirmed: 'confirm',
  dismissed: 'dismiss',
  resolved: 'resolve',
  new: 'reopen',
} as const satisfies Record<HallazgoOutAccionesPermitidasItem, string>

const SEVERITY_BADGE: Record<HallazgoOutSeverity, string> = {
  critical: 'bg-red-100 text-red-800',
  warning: 'bg-yellow-100 text-yellow-800',
  info: 'bg-blue-100 text-blue-800',
}

/**
 * Hallazgos (CUR.2): la cola de revisión, con dos sujetos distintos que comparten pantalla
 * porque comparten tarea —revisar y decidir qué hacer—. Los de un sitio (9Q) y los huecos de
 * un chatbot (RAG.14, `ContentGapsPanel`) son la misma cola de curación aunque su sujeto en
 * `hub_content_findings` sea distinto.
 */
export function FindingsPage() {
  const { t } = useTranslation('curation')
  const { t: tc } = useTranslation('common')
  const qc = useQueryClient()
  // `razonDelHallazgo` compone la clave según el tipo del hallazgo, así que la recibe como texto.
  const traducir = (clave: string, opciones?: Record<string, unknown>) =>
    t(clave as Parameters<typeof t>[0], opciones)

  const [selectedSiteId, setSelectedSiteId] = useState<string>('')
  // CUR.9 — la cola arranca en lo **abierto**. La reconciliación retira los hallazgos que ya no se
  // detectan, y listarlos con la etiqueta «Resuelto» sería no haber resuelto nada: en el apartado
  // real son 109 filas caducadas entre las vivas. Lo cerrado se sigue pudiendo ver eligiéndolo.
  const [statusFilter, setStatusFilter] = useState<string>('open')
  const [typeFilter, setTypeFilter] = useState<string>('')
  // CUR.4 — qué grupo está desplegado y qué página se está leyendo.
  const [desplegado, setDesplegado] = useState<string | null>(null)
  const [paginaAbierta, setPaginaAbierta] = useState<string | null>(null)

  const { data: sites = [] } = useListSites()
  const { data: findings = [], isLoading: findingsLoading } = useListSiteFindings(
    selectedSiteId,
    { status: statusFilter || undefined, type: typeFilter || undefined },
    { query: { enabled: !!selectedSiteId } }
  )

  const transitionMutation = useTransitionFinding({
    mutation: {
      onSuccess: () => {
        if (selectedSiteId) {
          qc.invalidateQueries({ queryKey: getListSiteFindingsQueryKey(selectedSiteId) })
        }
      },
    },
  })

  const handleTransition = (findingId: string, newStatus: string) => {
    if (!selectedSiteId) return
    transitionMutation.mutate({
      siteId: selectedSiteId,
      findingId,
      data: { new_status: newStatus },
    })
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">{t('findings_title')}</h1>
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
        {selectedSiteId && (
          <>
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="border rounded px-2 py-1.5 text-sm"
              aria-label={t('filter_status')}
            >
              {/* CUR.9 — «Pendientes» es el defecto, y «Todos» sigue estando para auditar el
                  histórico: retirar no es esconder. */}
              <option value="open">{t('status_open')}</option>
              <option value="">{t('status_all')}</option>
              <option value="new">{t('status_new')}</option>
              <option value="confirmed">{t('status_confirmed')}</option>
              <option value="dismissed">{t('status_dismissed')}</option>
              <option value="resolved">{t('status_resolved')}</option>
            </select>
            <select
              value={typeFilter}
              onChange={(e) => setTypeFilter(e.target.value)}
              className="border rounded px-2 py-1.5 text-sm"
              aria-label={t('filter_type')}
            >
              <option value="">{t('filter_type')}</option>
              {/* RAS.5 — `needs_javascript` y `content_updated` los emite el backend desde RAS.2
                  y RAS.5. Sin estar aquí no se podían filtrar y su columna «Tipo» habría salido
                  con la clave de traducción en crudo: un hallazgo que la pantalla no sabe nombrar
                  no existe para quien cura. */}
              {/* DIN.4 — `page_gone` (desapareció y el apartado no automatiza) y
                  `retirada_masiva_detenida` (la salvaguarda paró una retirada entera). El
                  segundo es el más importante de la lista: si no se ve, la única señal de que la
                  automatización se detuvo se queda en el log del servidor. */}
              {['superseded','duplicate','contradiction','empty','thin','stale','crawl_error','orphan_page','needs_javascript','content_updated','version_series','page_gone','retirada_masiva_detenida','auto_ingesta_detenida'].map((ft) => (
                <option key={ft} value={ft}>{t(`type_${ft}` as Parameters<typeof t>[0])}</option>
              ))}
            </select>
          </>
        )}
      </div>

      {selectedSiteId && (
        findingsLoading ? (
          <p className="text-muted-foreground">{tc('loading')}</p>
        ) : (findings as { id: string; finding_type: string; severity: string; status: string; source_url?: string; detected_at: string }[]).length === 0 ? (
          <p className="text-muted-foreground">{t('no_findings')}</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm border-collapse" aria-label={t('findings_title')}>
              <thead>
                <tr className="border-b text-left text-muted-foreground">
                  <th className="py-2 pr-3">{t('finding_type')}</th>
                  <th className="py-2 pr-3">{t('finding_severity')}</th>
                  <th className="py-2 pr-3">{t('finding_status')}</th>
                  <th className="py-2 pr-3">{t('finding_url')}</th>
                  <th className="py-2 pr-3">{t('finding_reason')}</th>
                  <th className="py-2 pr-3">{t('finding_detected')}</th>
                  <th className="py-2" />
                </tr>
              </thead>
              <tbody>
                {findings.map((f) => (
                  <tr key={f.id} className="border-b align-top">
                    <td className="py-2 pr-3">
                      <span className="text-xs">{t(`type_${f.finding_type}` as Parameters<typeof t>[0])}</span>
                      {/* CUR.4 — un hallazgo de grupo habla de varias páginas: aquí se despliegan
                          con sus fechas, que es lo que se compara. Antes ponía «+4 más» y no se
                          podía abrir. */}
                      {versionesDe(f).length > 0 && (
                        <>
                          <button
                            type="button"
                            data-testid={`btn-desplegar-${f.id}`}
                            onClick={() => setDesplegado(desplegado === f.id ? null : f.id)}
                            className="block text-xs text-primary underline mt-1"
                          >
                            {desplegado === f.id
                              ? t('collapse_versions')
                              : t('expand_versions', { count: versionesDe(f).length })}
                          </button>
                          {desplegado === f.id && (
                            <ul data-testid={`versiones-${f.id}`} className="mt-1 space-y-0.5">
                              {versionesDe(f).map((v) => (
                                <li key={v.url} className="text-xs">
                                  <a
                                    href={enlaceExterno(v.url)}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="text-primary underline break-all"
                                  >
                                    {v.url}
                                  </a>
                                  {v.date && (
                                    <span className="text-muted-foreground">
                                      {' '}
                                      · {new Date(v.date).toLocaleDateString()}
                                    </span>
                                  )}
                                </li>
                              ))}
                            </ul>
                          )}
                        </>
                      )}
                    </td>
                    <td className="py-2 pr-3">
                      <span className={`text-xs px-2 py-0.5 rounded-full ${SEVERITY_BADGE[f.severity] ?? ''}`}>
                        {t(`severity_${f.severity}` as Parameters<typeof t>[0])}
                      </span>
                    </td>
                    <td className="py-2 pr-3 text-xs">{t(`status_${f.status}` as Parameters<typeof t>[0])}</td>
                    {/* CUR.4 — clickable y en otra pestaña: «ahora hay que copiar y pegar».
                        CUR.8 — y si el hallazgo habla de dos páginas, **las dos**: «se muestran una
                        serie de páginas duplicadas pero solo se menciona una». Un duplicado con una
                        sola URL no se puede juzgar. */}
                    <td className="py-2 pr-3 text-xs max-w-xs">
                      {f.source_url ? (
                        <a
                          data-testid={`enlace-${f.id}`}
                          href={enlaceExterno(f.source_url)}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-primary underline break-all"
                        >
                          {f.source_url}
                        </a>
                      ) : (
                        '—'
                      )}
                      <div className="space-x-2">
                        {f.page_id && (
                          <button
                            type="button"
                            data-testid={`btn-ver-contenido-${f.id}`}
                            onClick={() => setPaginaAbierta(f.page_id ?? null)}
                            className="text-xs text-primary underline"
                          >
                            {t('view_stored_content')}
                          </button>
                        )}
                      </div>
                      {urlRelacionada(f) && (
                        <div className="mt-1 pl-2 border-l-2 border-muted">
                          <a
                            data-testid={`enlace-relacionada-${f.id}`}
                            href={enlaceExterno(urlRelacionada(f))}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-primary underline break-all"
                          >
                            {urlRelacionada(f)}
                          </a>
                          {f.related_page_id && (
                            <button
                              type="button"
                              data-testid={`btn-ver-relacionada-${f.id}`}
                              onClick={() => setPaginaAbierta(f.related_page_id ?? null)}
                              className="block text-xs text-primary underline"
                            >
                              {t('view_stored_content')}
                            </button>
                          )}
                        </div>
                      )}
                    </td>
                    {/* CUR.8 — la razón, que es lo que hace revisable el hallazgo. */}
                    <td className="py-2 pr-3 text-xs max-w-sm" data-testid={`razon-${f.id}`}>
                      {razonDelHallazgo(f, traducir)}
                    </td>
                    <td className="py-2 pr-3 text-xs">{new Date(f.detected_at).toLocaleDateString()}</td>
                    {/* #277 — los botones salen de `acciones_permitidas`: la cola tenía su propia
                        máquina de estado y no ofrecía descartar un hallazgo confirmado ni reabrir
                        uno descartado, que el servidor sí admite. */}
                    <td className="py-2 space-x-1">
                      {f.acciones_permitidas.map((destino) => (
                        <button
                          key={destino}
                          data-testid={`accion-${destino}-${f.id}`}
                          className="text-xs px-1.5 py-0.5 rounded border"
                          onClick={() => handleTransition(f.id, destino)}
                        >
                          {t(ETIQUETA_DE_LA_ACCION[destino])}
                        </button>
                      ))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      )}

      {/* RAG.14: los huecos de corpus son entrada de trabajo para el curador, no un panel
          aparte del chatbot — docs/DECISION_CURACION_SEPARADA.md, "Sobre CorpusSelectionService". */}
      <ContentGapsPanel />

      {paginaAbierta && (
        <PageContentDialog pageId={paginaAbierta} onClose={() => setPaginaAbierta(null)} />
      )}
    </div>
  )
}
