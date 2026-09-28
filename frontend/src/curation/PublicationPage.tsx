import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQueryClient } from '@tanstack/react-query'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { zodResolver } from '@hookform/resolvers/zod'
import {
  useListSites,
  useListSelections,
  useCreateSelection,
  useDeleteSelection,
  useListCandidates,
  useIngestPage,
  getListSelectionsQueryKey,
  getListCandidatesQueryKey,
} from '@/shared/api/generated/hub-sites/hub-sites'
import type { CandidatePageView, SiteView } from '@/shared/api/generated/model'
import { PageContentDialog } from './PageContentDialog'
import { useChatbotsDeLaOrganizacion } from '@/shared/organizacion/useChatbotsDeLaOrganizacion'

const selSchema = z.object({
  rule_type: z.enum(['path_prefix', 'sitemap_section', 'manual']).default('path_prefix'),
  rule_value: z.string().optional(),
  auto_ingest_new: z.boolean().default(true),
})

type SelFormInput = z.input<typeof selSchema>
type SelFormValues = z.output<typeof selSchema>

/**
 * El paso de publicación (CUR.2): decidir qué página entra al corpus de qué chatbot.
 *
 * `docs/DECISION_CURACION_SEPARADA.md`: `CorpusSelectionService` es el punto exacto donde la
 * materia prima se convierte en corpus, y antes de CUR.2 estaba enterrado como un panel que
 * sólo aparecía al pulsar una fila de `SitesPage`. Aquí es una página propia con su propio
 * selector de sitio: la publicación no es un detalle de gestionar sitios, es la decisión que
 * importa.
 *
 * Cada página candidata se ingiere con su propio botón — no hay «ingerir todo el sitio». Eso
 * es a propósito: automatizarlo sería devolver la promesa de ingesta automática que
 * `docs/DECISION_CURACION_SEPARADA.md` retira explícitamente.
 */
export function PublicationPage() {
  const { t } = useTranslation('curation')
  const { t: tc } = useTranslation('common')
  const qc = useQueryClient()
  const [selDialogOpen, setSelDialogOpen] = useState(false)
  // CUR.4 — la pagina cuyo texto guardado se esta leyendo antes de decidir si se publica.
  const [paginaAbierta, setPaginaAbierta] = useState<string | null>(null)
  // CUR.5 — las paginas marcadas para publicar. Del usuario: «no pueden desmarcarse algunas.
  // Convenria que se pudiera elegir».
  const [marcadas, setMarcadas] = useState<Set<string>>(new Set())
  // CUR.8 — cuántas se acaban de enviar a ingerir, para poder decirlo.
  const [enviadasAIngerir, setEnviadasAIngerir] = useState<number | null>(null)
  const [selectedSiteId, setSelectedSiteId] = useState<string>('')
  const [selectedChatbotId, setSelectedChatbotId] = useState<string>('')

  const { data: sites = [] } = useListSites()
  const { data: chatbots = [] } = useChatbotsDeLaOrganizacion()
  const { data: selections = [] } = useListSelections(selectedChatbotId, {
    query: { enabled: !!selectedChatbotId },
  })
  const { data: candidates = [] } = useListCandidates(
    selectedSiteId,
    { chatbot_id: selectedChatbotId },
    { query: { enabled: !!selectedSiteId && !!selectedChatbotId } },
  )

  const createSelMutation = useCreateSelection({
    mutation: {
      onSuccess: () => {
        qc.invalidateQueries({ queryKey: getListSelectionsQueryKey(selectedChatbotId) })
        setSelDialogOpen(false)
        reset()
      },
    },
  })
  const deleteSelMutation = useDeleteSelection()
  const ingestMutation = useIngestPage()

  const { register, handleSubmit, reset } = useForm<SelFormInput, unknown, SelFormValues>({
    resolver: zodResolver(selSchema),
    defaultValues: { rule_type: 'path_prefix', auto_ingest_new: true },
  })

  const onSubmit = (data: SelFormValues) => {
    if (!selectedChatbotId || !selectedSiteId) return
    createSelMutation.mutate({
      chatbotId: selectedChatbotId,
      data: {
        site_id: selectedSiteId,
        rule_type: data.rule_type,
        rule_value: data.rule_value,
        auto_ingest_new: data.auto_ingest_new,
      },
    })
  }

  /**
   * CUR.8 — ingerir **y decirlo**.
   *
   * Del usuario: «he seleccionado 4 páginas para que fueran cargadas en chatbot demo pero no sé si
   * ha funcionado». Había funcionado —cinco páginas con sus fragmentos en la base—, pero la pantalla
   * no decía nada: la mutación se lanzaba sin `onSuccess`, así que la tabla no se refrescaba y las
   * filas seguían igual. Una acción sin acuse de recibo se repite o se abandona.
   *
   * El servidor responde 202 y la ingesta sigue en segundo plano —embebe con el modelo del
   * chatbot—, así que el aviso dice que tarda: prometer «hecho» sería mentir por unos segundos.
   */
  const enviarAIngerir = (pageIds: string[]) => {
    if (!selectedChatbotId || pageIds.length === 0) return
    setEnviadasAIngerir(pageIds.length)
    pageIds.forEach((pageId) =>
      ingestMutation.mutate(
        { chatbotId: selectedChatbotId, pageId },
        { onSuccess: () => qc.invalidateQueries({ queryKey: getListCandidatesQueryKey(selectedSiteId) }) },
      ),
    )
  }

  const handleIngest = (pageId: string) => enviarAIngerir([pageId])

  /**
   * CUR.5 — marcar, desmarcar e ingerir lo marcado.
   *
   * Sigue sin haber «ingerir todo el sitio»: cada página entra al corpus porque alguien la marcó.
   * Lo que desaparece es tener que pulsar trescientas cuarenta y nueve veces para publicar un
   * apartado. Una página que ya está en el corpus no se puede marcar — para eso está `is_ingested`.
   */
  const publicables = (candidates as CandidatePageView[]).filter((c) => !c.is_ingested)

  const alternarMarca = (pageId: string) =>
    setMarcadas((previas) => {
      const siguiente = new Set(previas)
      if (siguiente.has(pageId)) siguiente.delete(pageId)
      else siguiente.add(pageId)
      return siguiente
    })

  const marcarTodo = () =>
    setMarcadas((previas) =>
      previas.size === publicables.length
        ? new Set()
        : new Set(publicables.map((c) => String(c.page_id))),
    )

  const ingerirLoMarcado = () => {
    enviarAIngerir([...marcadas])
    setMarcadas(new Set())
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">{t('publish_title')}</h1>
        <p className="text-sm text-muted-foreground">{t('publish_desc')}</p>
      </div>

      {/* Selectores de sitio y chatbot destino */}
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
        <select
          value={selectedChatbotId}
          onChange={(e) => setSelectedChatbotId(e.target.value)}
          className="border rounded px-2 py-1.5 text-sm"
          aria-label={t('candidates_chatbot')}
        >
          <option value="">{t('candidates_chatbot')}</option>
          {(chatbots as { id: string; name: string }[]).map((cb) => (
            <option key={cb.id} value={cb.id}>{cb.name}</option>
          ))}
        </select>
      </div>

      {selectedSiteId && selectedChatbotId && (
        <>
          {/* Selections */}
          <section>
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-sm font-semibold">{t('selections_title')}</h3>
              <button
                className="text-xs px-2 py-1 rounded border"
                onClick={() => setSelDialogOpen(true)}
              >
                {t('new_selection')}
              </button>
            </div>
            {selections.length === 0 ? (
              <p className="text-xs text-muted-foreground">{t('no_selections')}</p>
            ) : (
              <ul className="text-sm space-y-1">
                {(selections as { id: string; rule_type: string; rule_value?: string | null; auto_ingest_new: boolean }[]).map((sel) => (
                  <li key={sel.id} className="flex items-center gap-2">
                    <span className="text-xs bg-accent px-1.5 py-0.5 rounded">{sel.rule_type}</span>
                    <span className="flex-1 truncate">{sel.rule_value ?? '—'}</span>
                    {sel.auto_ingest_new && <span className="text-xs text-green-600">{t('sel_auto_ingest')}</span>}
                    <button
                      className="text-xs text-destructive hover:underline"
                      onClick={() => deleteSelMutation.mutate({ chatbotId: selectedChatbotId, selectionId: sel.id })}
                    >
                      {tc('delete')}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>

          {/* Candidatas: cada fila publica por su cuenta, y CUR.5 añade marcar varias */}
          <section>
            {enviadasAIngerir !== null && (
              <div
                data-testid="aviso-ingesta"
                className="mb-2 text-xs rounded border border-green-600/40 bg-green-50 text-green-900 px-2 py-1.5 flex items-center gap-2"
              >
                <span className="flex-1">{t('ingest_sent', { count: enviadasAIngerir })}</span>
                <button
                  type="button"
                  data-testid="btn-refrescar-candidatas"
                  onClick={() => qc.invalidateQueries({ queryKey: getListCandidatesQueryKey(selectedSiteId) })}
                  className="underline"
                >
                  {t('refresh_candidates')}
                </button>
                <button type="button" onClick={() => setEnviadasAIngerir(null)} aria-label={tc('cancel')}>
                  ×
                </button>
              </div>
            )}
            <div className="flex items-center justify-between mb-2 gap-3 flex-wrap">
              <h3 className="text-sm font-semibold">{t('candidates_title')}</h3>
              {(candidates as CandidatePageView[]).length > 0 && (
                <div className="flex items-center gap-2">
                  <span className="text-xs text-muted-foreground" data-testid="resumen-corpus">
                    {t('candidates_summary', {
                      publicables: publicables.length,
                      ingeridas: (candidates as CandidatePageView[]).length - publicables.length,
                    })}
                  </span>
                  <button
                    type="button"
                    data-testid="btn-ingerir-marcadas"
                    disabled={marcadas.size === 0 || ingestMutation.isPending}
                    onClick={ingerirLoMarcado}
                    className="text-xs px-2 py-1 rounded border disabled:opacity-50"
                  >
                    {t('ingest_selected', { count: marcadas.size })}
                  </button>
                </div>
              )}
            </div>
            {(candidates as CandidatePageView[]).length === 0 ? (
              <p className="text-xs text-muted-foreground">{t('no_candidates')}</p>
            ) : (
              <table className="w-full text-xs border-collapse" aria-label={t('candidates_title')}>
                <thead>
                  <tr className="border-b text-left text-muted-foreground">
                    <th className="py-1 pr-2">
                      <input
                        type="checkbox"
                        data-testid="marca-todo"
                        aria-label={t('select_all')}
                        checked={publicables.length > 0 && marcadas.size === publicables.length}
                        onChange={marcarTodo}
                      />
                    </th>
                    <th className="py-1 pr-2">{t('candidate_url')}</th>
                    <th className="py-1 pr-2">{t('candidate_matched_rule')}</th>
                    <th className="py-1 pr-2">{t('candidate_is_new')}</th>
                    <th className="py-1 pr-2">{t('candidate_corpus_state')}</th>
                    <th className="py-1" />
                  </tr>
                </thead>
                <tbody>
                  {(candidates as CandidatePageView[]).map((c) => (
                    <tr key={String(c.page_id)} className="border-b">
                      <td className="py-1 pr-2">
                        <input
                          type="checkbox"
                          data-testid={`marca-${c.page_id}`}
                          aria-label={c.url}
                          disabled={!!c.is_ingested}
                          checked={marcadas.has(String(c.page_id))}
                          onChange={() => alternarMarca(String(c.page_id))}
                        />
                      </td>
                      {/* CUR.4 — para decidir si una página merece entrar en el corpus hay que
                          poder abrirla y, sobre todo, leer **el texto que se guardó**, que es lo
                          que el asistente va a citar y no lo que se ve en el portal. */}
                      <td className="py-1 pr-2 max-w-xs">
                        <a
                          data-testid={`enlace-candidata-${c.page_id}`}
                          href={c.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-primary underline break-all"
                        >
                          {c.url}
                        </a>
                      </td>
                      <td className="py-1 pr-2">{c.matched_rule ?? '—'}</td>
                      <td className="py-1 pr-2">{c.is_new ? '✓' : '—'}</td>
                      {/* CUR.5 — «que se vea lo que ya está ingerido, para no volver a publicarlo».
                          Antes la fila desaparecía, y una fila que se va no dice si la ingesta
                          funcionó o si la página nunca fue candidata. */}
                      <td className="py-1 pr-2" data-testid={`estado-corpus-${c.page_id}`}>
                        {c.is_ingested ? (
                          <span className="text-green-700">{t('candidate_ingested')}</span>
                        ) : (
                          <span className="text-muted-foreground">{t('candidate_not_ingested')}</span>
                        )}
                      </td>
                      <td className="py-1 space-x-1">
                        <button
                          type="button"
                          data-testid={`btn-ver-candidata-${c.page_id}`}
                          className="px-2 py-0.5 rounded border text-xs"
                          onClick={() => setPaginaAbierta(String(c.page_id))}
                        >
                          {t('view_stored_content')}
                        </button>
                        <button
                          className="px-2 py-0.5 rounded border text-xs"
                          onClick={() => handleIngest(String(c.page_id))}
                          disabled={ingestMutation.isPending || !!c.is_ingested}
                        >
                          {t('ingest')}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        </>
      )}

      {/* Selection dialog */}
      {selDialogOpen && (
        <div role="dialog" aria-modal="true" aria-label={t('new_selection')} className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-background rounded-lg shadow-lg p-6 w-full max-w-sm space-y-4">
            <h2 className="text-base font-semibold">{t('new_selection')}</h2>
            <form onSubmit={handleSubmit(onSubmit)} className="space-y-3" noValidate>
              <div>
                <label className="text-sm font-medium">{t('sel_rule_type')}</label>
                <select {...register('rule_type')} className="w-full border rounded px-2 py-1.5 text-sm mt-1">
                  <option value="path_prefix">{t('sel_rule_path_prefix')}</option>
                  <option value="sitemap_section">{t('sel_rule_sitemap_section')}</option>
                  <option value="manual">{t('sel_rule_manual')}</option>
                </select>
              </div>
              <div>
                <label className="text-sm font-medium">{t('sel_rule_value')}</label>
                <input {...register('rule_value')} className="w-full border rounded px-2 py-1.5 text-sm mt-1" />
              </div>
              <div className="flex items-center gap-2">
                <input type="checkbox" {...register('auto_ingest_new')} id="auto_ingest" />
                <label htmlFor="auto_ingest" className="text-sm">{t('sel_auto_ingest')}</label>
              </div>
              <div className="flex justify-end gap-2 pt-1">
                <button type="button" onClick={() => { setSelDialogOpen(false); reset() }} className="px-3 py-1.5 rounded border text-sm">{tc('cancel')}</button>
                <button type="submit" disabled={createSelMutation.isPending} className="px-3 py-1.5 rounded bg-primary text-primary-foreground text-sm">{tc('save')}</button>
              </div>
            </form>
          </div>
        </div>
      )}
      {paginaAbierta && (
        <PageContentDialog pageId={paginaAbierta} onClose={() => setPaginaAbierta(null)} />
      )}

    </div>
  )
}
