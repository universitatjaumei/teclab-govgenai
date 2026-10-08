import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useFocusStore, type CopilotActionKind } from '../useFocusStore'
import {
  askCopilotApiV1RedaccionCopilotAskPost,
  translateCopilotApiV1RedaccionCopilotTranslatePost,
} from '@/shared/api/generated/redaccion-copilot/redaccion-copilot'
import type { CopilotAnswer, CopilotTranslateResponse } from '@/shared/api/generated/model'

type Mode = 'ask' | 'chart' | 'etl' | 'script'

const MODE_TO_KIND: Record<Exclude<Mode, 'ask'>, CopilotActionKind> = {
  chart: 'chart_config',
  etl: 'etl_ops',
  script: 'script_proposal',
}

const INFORME_PILLS: ReadonlyArray<{ key: string; fallback: string }> = [
  { key: 'pills.informe.create_block', fallback: '¿Cómo creo un bloque IA?' },
  { key: 'pills.informe.reject_block', fallback: '¿Qué pasa si rechazo un bloque?' },
  { key: 'pills.informe.group_sum', fallback: 'Agrupa por mes y suma el importe' },
  { key: 'pills.informe.bar_chart', fallback: 'Gráfico de barras del total por región' },
]

const FLUJO_PILLS: ReadonlyArray<{ key: string; fallback: string }> = [
  { key: 'pills.flujo.add_trigger', fallback: '¿Cómo añado un trigger?' },
  { key: 'pills.flujo.data_pills', fallback: '¿Qué son las Data Pills?' },
  { key: 'pills.flujo.connect_slack', fallback: 'Conecta este flujo con Slack' },
  { key: 'pills.flujo.suggest_transform', fallback: 'Sugiere una transformación de datos' },
]

export function CopilotPanel() {
  const { t } = useTranslation('redaccion')
  const context = useFocusStore((s) => s.context)

  const [mode, setMode] = useState<Mode>('ask')
  const [input, setInput] = useState('')
  const [isPending, setIsPending] = useState(false)
  const [askResponse, setAskResponse] = useState<CopilotAnswer | null>(null)
  const [translateResponse, setTranslateResponse] = useState<CopilotTranslateResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [copiado, setCopiado] = useState(false)

  const pills = context?.type === 'flujo' ? FLUJO_PILLS : INFORME_PILLS

  const handleSend = async () => {
    if (!input.trim()) return
    setIsPending(true)
    setError(null)
    setAskResponse(null)
    setTranslateResponse(null)
    try {
      if (mode === 'ask') {
        const moduleHint = context?.type === 'flujo' ? 'general' : 'redaccion'
        const res = await askCopilotApiV1RedaccionCopilotAskPost({
          question: input,
          module: moduleHint,
          top_k: 4,
          // INF.10 — el informe abierto. El copiloto ya sabía en qué contexto estaba
          // («informe» o «flujo») y no **cuál**, así que respondía con la documentación del
          // proyecto: «no sé dónde aprobar los bloques» no tenía respuesta posible.
          workspace_id: context?.type === 'informe' ? context.entityId : null,
        })
        setAskResponse(res)
      } else {
        const res = await translateCopilotApiV1RedaccionCopilotTranslatePost({
          instruction: input,
          target_kind: MODE_TO_KIND[mode],
        })
        setTranslateResponse(res)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error inesperado')
    } finally {
      setIsPending(false)
    }
  }

  const handleCopy = async () => {
    if (!translateResponse) return
    await navigator.clipboard.writeText(JSON.stringify(translateResponse.payload, null, 2))
    setCopiado(true)
  }

  return (
    <div data-testid="copilot-panel" className="flex flex-col gap-3 h-full p-3">
      <div className="flex flex-wrap gap-1.5">
        {pills.map(({ key, fallback }) => (
          <button
            key={key}
            data-testid="copilot-pill"
            className="text-xs px-2 py-1 rounded-full border bg-muted hover:bg-accent transition-colors"
            onClick={() => setInput(t(`copilot.${key}`, fallback))}
          >
            {t(`copilot.${key}`, fallback)}
          </button>
        ))}
      </div>

      <div className="flex gap-1 text-xs">
        {(['ask', 'chart', 'etl', 'script'] as const).map((m) => (
          <button
            key={m}
            data-testid={`copilot-mode-${m}`}
            aria-pressed={mode === m}
            className={`px-2 py-1 rounded transition-colors ${
              mode === m
                ? 'bg-primary text-primary-foreground'
                : 'bg-muted text-foreground hover:bg-accent'
            }`}
            onClick={() => setMode(m)}
          >
            {t(`copilot.mode.${m}`, m)}
          </button>
        ))}
      </div>

      <textarea
        data-testid="copilot-input"
        className="border rounded-md p-2 text-sm resize-y bg-background"
        rows={3}
        placeholder={t('copilot.placeholder')}
        value={input}
        onChange={(e) => setInput(e.target.value)}
      />

      <button
        data-testid="copilot-send"
        className="px-3 py-1.5 rounded-md bg-primary text-primary-foreground text-sm disabled:opacity-50 self-start"
        disabled={isPending || !input.trim()}
        onClick={handleSend}
      >
        {isPending ? t('copilot.sending') : t('copilot.send')}
      </button>

      {error && (
        <p data-testid="copilot-error" className="text-xs text-destructive">
          {error}
        </p>
      )}

      {askResponse && (
        <div data-testid="copilot-answer" className="space-y-2 border-t pt-2 text-sm">
          <p className="whitespace-pre-wrap">{askResponse.answer}</p>
          {(askResponse.source_refs?.length ?? 0) > 0 && (
            <ul className="text-xs text-muted-foreground space-y-1">
              {askResponse.source_refs!.map((ref, i) => (
                <li key={`${ref.path}-${ref.chunk_idx}-${i}`}>
                  <span className="font-mono">{ref.path}</span> — {ref.excerpt}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {translateResponse && (
        <div data-testid="copilot-translate" className="space-y-2 border-t pt-2">
          <p className="text-xs text-muted-foreground">{translateResponse.kind}</p>
          <pre className="text-xs bg-muted p-2 rounded overflow-x-auto max-h-48">
            {JSON.stringify(translateResponse.payload, null, 2)}
          </pre>
          {/* GUI.5 — aquí había un botón «Aplicar» que **no hacía nada**: escribía la propuesta
              en `pendingAction` del store y `useCopilotAction`, el único que la lee, no lo usa
              ninguna pantalla. Un botón que no hace nada es peor que no tener botón, porque
              quien lo pulsa cree que ya está hecho. La propuesta se lee y se copia; aplicarla
              exige una pantalla que la reciba, y esa pantalla no existe todavía. */}
          <button
            data-testid="copilot-copy"
            className="px-3 py-1.5 rounded-md border text-sm hover:bg-accent"
            onClick={handleCopy}
          >
            {copiado
              ? t('copilot.copied')
              : t('copilot.copy')}
          </button>
          <p className="text-xs text-muted-foreground">
            {t('copilot.translate_hint')}
          </p>
        </div>
      )}
    </div>
  )
}
