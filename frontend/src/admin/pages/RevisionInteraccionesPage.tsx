import { Fragment, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQueryClient } from '@tanstack/react-query'
import { Download, Star, ChevronDown, ChevronUp, Loader2 } from 'lucide-react'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts'
import {
  useGetInteractionsForReviewApiV1HubFeedbackChatbotIdReviewGet,
  useReviewInteractionApiV1HubFeedbackInteractionsInteractionIdReviewPatch,
  getGetInteractionsForReviewApiV1HubFeedbackChatbotIdReviewGetQueryKey,
} from '@/shared/api/generated/hub-feedback/hub-feedback'
import type { ChatbotRead, InteractionReviewOut } from '@/shared/api/generated/model'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { useChatbotsDeLaOrganizacion } from '@/shared/organizacion/useChatbotsDeLaOrganizacion'
import { useSeleccionValida } from '@/shared/organizacion/useSeleccionValida'

type Verdict = 'good' | 'bad' | 'mixed'
type ReviewStatus = 'pending' | 'reviewed' | 'all'

const VEREDICTOS: { valor: Verdict; clave: string; defecto: string; clase: string }[] = [
  { valor: 'good', clave: 'hub.reports_verdict_good', defecto: 'Adecuada', clase: 'text-green-600' },
  { valor: 'mixed', clave: 'hub.reports_verdict_mixed', defecto: 'Mejorable', clase: 'text-yellow-600' },
  { valor: 'bad', clave: 'hub.reports_verdict_bad', defecto: 'Inadecuada', clase: 'text-red-600' },
]

function StarRating({ score }: { score: number | null }) {
  if (score === null) return <span className="text-muted-foreground">—</span>
  return (
    <span className="flex gap-0.5">
      {[1, 2, 3, 4, 5].map((n) => (
        <Star
          key={n}
          className={`h-3.5 w-3.5 ${n <= score ? 'text-yellow-400 fill-yellow-400' : 'text-muted-foreground'}`}
        />
      ))}
    </span>
  )
}

function exportToCsv(chatbotId: string, interactions: InteractionReviewOut[]) {
  // REV.1: el veredicto viaja en el CSV. Es lo que Gerencia se lleva a una reunión, y si no
  // sale de aquí la revisión se queda dentro de la aplicación.
  const header = [
    'date',
    'user_message',
    'assistant_message',
    'score',
    'comment',
    'review_verdict',
    'review_note',
    'review_by',
    'review_at',
    // HIB.H: la fuente esperada y la respuesta de referencia salen también. Son lo que
    // convierte la revisión en algo medible más de una vez, y si no viajan en la
    // exportación se quedan dentro de la aplicación igual que le pasaba al veredicto.
    'review_expected_required',
    'review_expected_acceptable',
    'review_reference_answer',
  ]
  const escape = (s: string) => `"${s.replace(/"/g, '""')}"`
  // Documento y ancla juntos, separados por «|» entre fuentes: una hoja de cálculo no puede
  // con una lista anidada, y el ancla sin su documento no identifica ningún artículo.
  const fuentes = (lista: unknown): string =>
    Array.isArray(lista)
      ? lista
          .map((f) => {
            const r = f as { canonical_url?: string; document_id?: string; anchor?: string }
            const doc = r.canonical_url ?? r.document_id ?? ''
            return r.anchor ? `${doc}#${r.anchor}` : doc
          })
          .join(' | ')
      : ''
  const rows = interactions.map((i) => [
    i.created_at,
    escape(i.user_message),
    escape(i.assistant_message),
    String(i.feedback_score ?? ''),
    escape(i.feedback_text ?? ''),
    i.review_verdict ?? '',
    escape(i.review_note ?? ''),
    i.review_by ?? '',
    i.review_at ?? '',
    escape(
      fuentes((i.review_expected_sources as { required?: unknown } | null)?.required),
    ),
    escape(
      fuentes((i.review_expected_sources as { acceptable?: unknown } | null)?.acceptable),
    ),
    escape(i.review_reference_answer ?? ''),
  ])
  const csv = [header, ...rows].map((r) => r.join(',')).join('\n')
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `interactions-${chatbotId}.csv`
  a.click()
  URL.revokeObjectURL(url)
}

export function RevisionInteraccionesPage() {
  const { t } = useTranslation('admin')

  const [selectedChatbotId, setSelectedChatbotId] = useState('')
  const [onlyLowScores, setOnlyLowScores] = useState(false)
  const [expandedRow, setExpandedRow] = useState<string | null>(null)
  const [reviewStatus, setReviewStatus] = useState<ReviewStatus>('pending')
  const [verdictFilter, setVerdictFilter] = useState<Verdict | ''>('')
  const [notes, setNotes] = useState<Record<string, string>>({})

  const qc = useQueryClient()
  const { data: chatbotsRaw } = useChatbotsDeLaOrganizacion()
  const chatbots: ChatbotRead[] = (chatbotsRaw as unknown as ChatbotRead[] | undefined) ?? []

  // Issue #11 — al cambiar de organización, un chatbot de la anterior no puede quedarse
  // elegido: la consulta dependiente y las mutaciones irían contra otra organización.
  useSeleccionValida(chatbots, selectedChatbotId, setSelectedChatbotId)

  if (!selectedChatbotId && chatbots.length > 0) {
    setSelectedChatbotId(chatbots[0].id)
  }

  const { data: interactions = [], isLoading } =
    useGetInteractionsForReviewApiV1HubFeedbackChatbotIdReviewGet(
      selectedChatbotId,
      {
        only_low_scores: onlyLowScores,
        review_status: reviewStatus,
        ...(verdictFilter ? { verdict: verdictFilter } : {}),
      },
      { query: { enabled: !!selectedChatbotId } },
    )

  const { mutate: enviarVeredicto, isPending: enviandoVeredicto } =
    useReviewInteractionApiV1HubFeedbackInteractionsInteractionIdReviewPatch()

  const pendientes = interactions.filter((i) => !i.review_verdict).length

  function revisar(interaction: InteractionReviewOut, verdict: Verdict) {
    const note = (notes[interaction.id] ?? '').trim()
    // Un «mal» sin motivo no reformula nada: el backend lo rechaza con 422 y no tiene
    // sentido pedírselo. La nota es obligatoria justo donde sirve.
    //
    // La guarda se queda **además** del botón deshabilitado, y no en su lugar: el botón es lo
    // que la persona ve y esto es lo que aguanta si alguien llama a `revisar` desde otro sitio.
    // Lo que faltaba no era la guarda, era decirlo.
    if (verdict === 'bad' && !note) return

    enviarVeredicto(
      { interactionId: interaction.id, data: { verdict, note: note || null } },
      {
        onSuccess: () =>
          qc.invalidateQueries({
            queryKey:
              getGetInteractionsForReviewApiV1HubFeedbackChatbotIdReviewGetQueryKey(
                selectedChatbotId,
              ),
          }),
      },
    )
  }

  const scoredInteractions = interactions.filter((i) => i.feedback_score != null)
  const avgScore =
    scoredInteractions.length > 0
      ? scoredInteractions.reduce((s, i) => s + i.feedback_score!, 0) / scoredInteractions.length
      : null

  const scoreDistribution = [1, 2, 3, 4, 5].map((star) => ({
    star,
    count: scoredInteractions.filter((i) => i.feedback_score === star).length,
  }))

  return (
    <div className="space-y-4">
      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3">
        <select
          value={selectedChatbotId}
          onChange={(e) => setSelectedChatbotId(e.target.value)}
          className="rounded-md border bg-background px-3 py-1.5 text-sm"
        >
          {chatbots.map((cb) => (
            <option key={cb.id} value={cb.id}>
              {cb.name}
            </option>
          ))}
        </select>

        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={onlyLowScores}
            onChange={(e) => setOnlyLowScores(e.target.checked)}
            className="rounded"
          />
          {t('hub.reports_only_low', 'Solo puntuaciones bajas')}
        </label>

        <select
          value={reviewStatus}
          onChange={(e) => setReviewStatus(e.target.value as ReviewStatus)}
          aria-label={t('hub.reports_review_status', 'Estado de revisión')}
          className="rounded-md border bg-background px-3 py-1.5 text-sm"
        >
          <option value="pending">{t('hub.reports_status_pending', 'Sin revisar')}</option>
          <option value="reviewed">{t('hub.reports_status_reviewed', 'Revisadas')}</option>
          <option value="all">{t('hub.reports_status_all', 'Todas')}</option>
        </select>

        <select
          value={verdictFilter}
          onChange={(e) => setVerdictFilter(e.target.value as Verdict | '')}
          aria-label={t('hub.reports_verdict_filter', 'Veredicto')}
          className="rounded-md border bg-background px-3 py-1.5 text-sm"
        >
          <option value="">{t('hub.reports_verdict_any', 'Cualquier veredicto')}</option>
          {VEREDICTOS.map((v) => (
            <option key={v.valor} value={v.valor}>
              {t(v.clave, v.defecto)}
            </option>
          ))}
        </select>

        <button
          onClick={() => exportToCsv(selectedChatbotId, interactions)}
          disabled={interactions.length === 0}
          aria-label={t('hub.reports_export_csv', 'Exportar CSV')}
          className="ml-auto flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm hover:bg-accent disabled:opacity-50"
        >
          <Download className="h-3.5 w-3.5" />
          CSV
        </button>
      </div>

      {/* Metric cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle>{t('hub.reports_total', 'Total interacciones')}</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-bold">{interactions.length}</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>{t('hub.reports_pending_review', 'Pendientes de revisar')}</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-bold" data-testid="pending-count">
              {pendientes}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>{t('hub.reports_avg_score', 'Puntuación media')}</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-bold" data-testid="avg-score">
              {avgScore !== null ? avgScore.toFixed(1) : '—'}
            </p>
            {scoredInteractions.length > 0 && (
              <div className="mt-2 h-16">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={scoreDistribution} margin={{ top: 0, right: 0, left: -20, bottom: 0 }}>
                    <XAxis dataKey="star" tick={{ fontSize: 10 }} />
                    <YAxis tick={{ fontSize: 10 }} allowDecimals={false} />
                    <Tooltip />
                    <Bar dataKey="count" radius={[2, 2, 0, 0]}>
                      {scoreDistribution.map((entry) => (
                        <Cell
                          key={entry.star}
                          fill={entry.star <= 2 ? '#f87171' : entry.star === 3 ? '#facc15' : '#4ade80'}
                        />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Interactions table */}
      {isLoading ? (
        <div className="flex justify-center py-8">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </div>
      ) : interactions.length === 0 ? (
        <p className="py-8 text-center text-sm text-muted-foreground">
          {t('hub.reports_no_data', 'Sin interacciones para este chatbot')}
        </p>
      ) : (
        <div className="rounded-lg border">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-muted/50 text-left text-xs text-muted-foreground">
                <th className="px-3 py-2">{t('hub.reports_date', 'Fecha')}</th>
                <th className="px-3 py-2">{t('hub.reports_user_msg', 'Mensaje usuario')}</th>
                <th className="px-3 py-2">{t('hub.reports_score', 'Puntuación')}</th>
                <th className="px-3 py-2">{t('hub.reports_comment', 'Comentario')}</th>
                <th className="px-3 py-2">{t('hub.reports_review', 'Revisión')}</th>
                <th className="px-3 py-2 w-10" />
              </tr>
            </thead>
            <tbody>
              {interactions.map((interaction) => (
                <Fragment key={interaction.id}>
                  <tr className="border-b hover:bg-muted/30">
                    <td className="px-3 py-2 text-muted-foreground whitespace-nowrap">
                      {new Date(interaction.created_at).toLocaleDateString()}
                    </td>
                    <td className="px-3 py-2 max-w-xs truncate">
                      {interaction.user_message}
                    </td>
                    <td className="px-3 py-2">
                      <StarRating score={interaction.feedback_score ?? null} />
                    </td>
                    <td className="px-3 py-2 max-w-xs truncate text-muted-foreground">
                      {interaction.feedback_text ?? '—'}
                    </td>
                    <td className="px-3 py-2">
                      {interaction.review_verdict ? (
                        <span
                          className={
                            VEREDICTOS.find((v) => v.valor === interaction.review_verdict)
                              ?.clase ?? ''
                          }
                        >
                          {t(
                            `hub.reports_verdict_${interaction.review_verdict}`,
                            interaction.review_verdict,
                          )}
                        </span>
                      ) : (
                        <span className="text-muted-foreground">
                          {t('hub.reports_status_pending', 'Sin revisar')}
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      <button
                        aria-label={
                          expandedRow === interaction.id
                            ? t('hub.reports_collapse', 'Collapse')
                            : t('hub.reports_expand', 'Expand')
                        }
                        onClick={() =>
                          setExpandedRow(expandedRow === interaction.id ? null : interaction.id)
                        }
                        className="rounded p-0.5 hover:bg-accent"
                      >
                        {expandedRow === interaction.id ? (
                          <ChevronUp className="h-4 w-4" />
                        ) : (
                          <ChevronDown className="h-4 w-4" />
                        )}
                      </button>
                    </td>
                  </tr>
                  {expandedRow === interaction.id && (
                    <tr className="bg-muted/20">
                      <td colSpan={6} className="px-4 py-3 space-y-2">
                        <div>
                          <p className="text-xs font-medium text-muted-foreground mb-1">
                            {t('hub.reports_user_msg', 'Mensaje usuario')}
                          </p>
                          <p className="text-sm">{interaction.user_message}</p>
                        </div>
                        <div>
                          <p className="text-xs font-medium text-muted-foreground mb-1">
                            {t('hub.reports_assistant_msg', 'Respuesta asistente')}
                          </p>
                          <p className="text-sm">{interaction.assistant_message}</p>
                        </div>
                        {interaction.review_by && (
                          <p className="text-xs text-muted-foreground">
                            {t('hub.reports_reviewed_by', 'Revisada por')}{' '}
                            {interaction.review_by}
                            {interaction.review_at
                              ? ` · ${new Date(interaction.review_at).toLocaleString()}`
                              : ''}
                          </p>
                        )}
                      </td>
                    </tr>
                  )}
                  <tr className="border-b bg-muted/10">
                    <td colSpan={6} className="px-4 py-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <input
                          type="text"
                          value={notes[interaction.id] ?? interaction.review_note ?? ''}
                          onChange={(e) =>
                            setNotes({ ...notes, [interaction.id]: e.target.value })
                          }
                          placeholder={t(
                            'hub.reports_review_note',
                            'Qué habría que cambiar (obligatorio si es inadecuada)',
                          )}
                          aria-label={t('hub.reports_review_note', 'Nota de revisión')}
                          className="flex-1 min-w-[16rem] rounded-md border bg-background px-2 py-1 text-sm"
                        />
                        {VEREDICTOS.map((v) => {
                          // Un «mal» sin motivo no reformula nada, así que el botón no se
                          // puede pulsar — pero **se dice por qué**. Antes era un `return`
                          // silencioso en `revisar()`: se pulsaba, la fila no cambiaba y no
                          // aparecía ningún motivo. Lo destapó la verificación en navegador.
                          const faltaLaNota =
                            v.valor === 'bad' && !(notes[interaction.id] ?? '').trim()
                          return (
                            <button
                              key={v.valor}
                              onClick={() => revisar(interaction, v.valor)}
                              disabled={enviandoVeredicto || faltaLaNota}
                              // El `title` no es decoración: es el único sitio donde el motivo
                              // llega a quien usa un lector de pantalla sobre un botón gris.
                              title={
                                faltaLaNota
                                  ? t(
                                      'hub.reports_note_required',
                                      'Escribe qué habría que cambiar: un «inadecuada» sin motivo no permite reformular nada',
                                    )
                                  : undefined
                              }
                              className={`rounded-md border px-2 py-1 text-xs hover:bg-accent disabled:opacity-50 disabled:cursor-not-allowed ${v.clase}`}
                            >
                              {t(v.clave, v.defecto)}
                            </button>
                          )
                        })}
                        {!(notes[interaction.id] ?? '').trim() && (
                          <span
                            data-testid="nota-obligatoria"
                            className="text-xs text-muted-foreground"
                          >
                            {t(
                              'hub.reports_note_required',
                              'Escribe qué habría que cambiar: un «inadecuada» sin motivo no permite reformular nada',
                            )}
                          </span>
                        )}
                      </div>
                    </td>
                  </tr>
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
