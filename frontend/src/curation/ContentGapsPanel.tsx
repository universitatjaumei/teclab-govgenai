import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQueryClient } from '@tanstack/react-query'
import { useChatbotsDeLaOrganizacion } from '@/shared/organizacion/useChatbotsDeLaOrganizacion'
import { useSeleccionValida } from '@/shared/organizacion/useSeleccionValida'
import {
  useListContentGaps,
  useAnalyzeContentGaps,
  getListContentGapsQueryKey,
} from '@/shared/api/generated/hub-content-quality/hub-content-quality'

/**
 * RAG.14 — cola de revisión de huecos de corpus.
 *
 * Vive junto a la cola de calidad de contenido porque es la misma tarea —revisar hallazgos
 * y decidir qué hacer— pero en su propio panel: los hallazgos de 9Q cuelgan de un sitio
 * web y estos cuelgan de un chatbot, así que el selector de arriba no puede ser el mismo.
 *
 * Sin esta pantalla el detector escribiría hallazgos que no vería nadie, que es la forma
 * más cara de no hacer nada.
 */

const BADGE: Record<string, string> = {
  critical: 'bg-red-100 text-red-800',
  warning: 'bg-yellow-100 text-yellow-800',
  info: 'bg-blue-100 text-blue-800',
}

type Gap = {
  id: string
  severity: string
  status: string
  count: number
  queries: string[]
  top_terms: string[]
  first_seen: string | null
  last_seen: string | null
}

export function ContentGapsPanel() {
  const { t } = useTranslation('curation')
  const qc = useQueryClient()
  const [chatbotId, setChatbotId] = useState('')

  const { data: chatbots = [] } = useChatbotsDeLaOrganizacion()

  // Issue #11 — al cambiar de organización, un chatbot de la anterior no puede quedarse
  // elegido: la consulta dependiente y las mutaciones irían contra otra organización.
  useSeleccionValida(chatbots, chatbotId, setChatbotId)
  const { data: gaps = [] } = useListContentGaps(
    { chatbot_id: chatbotId },
    { query: { enabled: !!chatbotId } }
  )

  const analizar = useAnalyzeContentGaps({
    mutation: {
      onSuccess: () => {
        if (chatbotId) {
          qc.invalidateQueries({
            queryKey: getListContentGapsQueryKey({ chatbot_id: chatbotId }),
          })
        }
      },
    },
  })

  return (
    <section className="space-y-4" data-testid="content-gaps">
      <header>
        <h2 className="text-lg font-semibold">{t('gaps_title')}</h2>
        <p className="text-sm text-gray-600">{t('gaps_hint')}</p>
      </header>

      <div className="flex items-end gap-3">
        <label className="flex flex-col text-sm">
          <span className="mb-1">{t('gaps_chatbot')}</span>
          <select
            className="border rounded px-2 py-1"
            value={chatbotId}
            onChange={(e) => setChatbotId(e.target.value)}
            aria-label={t('gaps_chatbot')}
          >
            <option value="" />
            {chatbots.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </label>
        {chatbotId && (
          <button
            className="border rounded px-3 py-1 text-sm"
            data-testid="analyze-gaps"
            disabled={analizar.isPending}
            onClick={() => analizar.mutate({ params: { chatbot_id: chatbotId } })}
          >
            {t('gaps_analyze')}
          </button>
        )}
      </div>

      {chatbotId && (gaps as Gap[]).length === 0 && (
        <p className="text-sm text-gray-500">{t('gaps_none')}</p>
      )}

      <ul className="space-y-3">
        {(gaps as Gap[]).map((gap) => (
          <li key={gap.id} className="border rounded p-3 space-y-2">
            <div className="flex items-center gap-2 text-sm">
              <span className={`px-2 py-0.5 rounded text-xs ${BADGE[gap.severity] ?? ''}`}>
                {gap.severity}
              </span>
              <strong>{gap.count}</strong>
              <span>{t('gaps_count')}</span>
              {gap.first_seen && gap.last_seen && (
                <span className="text-xs text-gray-500">
                  {t('gaps_range')} {gap.first_seen.slice(0, 10)} — {gap.last_seen.slice(0, 10)}
                </span>
              )}
            </div>
            {gap.top_terms.length > 0 && (
              <p className="text-xs text-gray-600">
                {t('gaps_terms')}: {gap.top_terms.join(', ')}
              </p>
            )}
            <ul className="text-sm list-disc pl-5">
              {gap.queries.map((q, i) => (
                <li key={i}>{q}</li>
              ))}
            </ul>
          </li>
        ))}
      </ul>
    </section>
  )
}
