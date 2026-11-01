import { useTranslation } from 'react-i18next'
import { RefreshCw, Trash2 } from 'lucide-react'

import type { RecalculateCorpusOut } from '@/shared/api/generated/model'
import { Progress } from '@/components/ui/progress'
import { ConfirmDialog } from '@/shared/components/ConfirmDialog'
import { formatTokens } from './format'

/**
 * Las dos acciones que afectan al corpus entero, no a un documento.
 *
 * Van en la cabecera de la tabla y `RechunkStatus` va encima de ella, así que son dos
 * exportaciones y no una: comparten responsabilidad —el retroceso del corpus— pero ocupan
 * sitios distintos del DOM, y unirlas obligaría a mover una de las dos de su posición.
 *
 * Ninguna confirma por su cuenta: quien decide el texto de la advertencia es la página,
 * porque depende del modo de retrieval del chatbot.
 */
export function RechunkControls({
  onRecalculate,
  onClear,
  isRecalculating,
  isClearing,
}: {
  onRecalculate: () => void
  onClear: () => void
  isRecalculating: boolean
  isClearing: boolean
}) {
  const { t } = useTranslation('admin')

  return (
    <>
      <button
        type="button"
        onClick={onRecalculate}
        disabled={isRecalculating}
        className="flex items-center gap-2 text-xs px-3 py-1.5 border rounded hover:bg-accent transition-colors disabled:opacity-50"
      >
        <RefreshCw className="w-3 h-3" />{t('hub.recalculate_corpus')}
      </button>
      <button
        type="button"
        onClick={onClear}
        disabled={isClearing}
        className="flex items-center gap-2 text-xs px-3 py-1.5 text-destructive border border-destructive/30 rounded hover:bg-destructive/10 transition-colors disabled:opacity-50"
      >
        <Trash2 className="w-3 h-3" />{t('hub.clear_collection')}
      </button>
    </>
  )
}

/**
 * Advertencia previa al recálculo. Lo que se pierde depende del modo de retrieval: en RAG hay
 * que volver a generar embeddings —minutos y coste—, y en los demás sólo se tiran los chunks
 * vectoriales, con el markdown intacto. Decirlo antes evita la sorpresa cara.
 */
export function RechunkConfirmDialog({
  retrievalMode,
  documentCount,
  totalTokens,
  isPending,
  onConfirm,
  onCancel,
}: {
  retrievalMode: string | undefined
  documentCount: number
  totalTokens: number
  isPending: boolean
  onConfirm: () => void
  onCancel: () => void
}) {
  const { t } = useTranslation('admin')
  const estimatedMinutes = Math.max(1, Math.ceil(totalTokens / 120_000))

  return (
    <ConfirmDialog
      title={t('hub.recalculate_title')}
      description={
        retrievalMode === 'RAG'
          ? (
            <>
              {t('hub.recalculate_vector_text')}{' '}
              <strong>{documentCount}</strong> docs · ~{formatTokens(totalTokens)} tokens · ~{estimatedMinutes} min.
            </>
          )
          : (
            <>
              {t('hub.recalculate_non_vector_text')}{' '}
              <strong>{documentCount}</strong> docs.
            </>
          )
      }
      confirmLabel={t('hub.recalculate_confirm')}
      isPending={isPending}
      onConfirm={onConfirm}
      onCancel={onCancel}
    />
  )
}

/** Progreso y desenlace del último recálculo. */
export function RechunkStatus({
  isRecalculating,
  result,
  error,
}: {
  isRecalculating: boolean
  result: RecalculateCorpusOut | null
  error: string
}) {
  const { t } = useTranslation('admin')

  return (
    <>
      {isRecalculating && (
        <div className="rounded-md border p-3 bg-muted/20">
          <p className="text-xs text-muted-foreground mb-2">
            {t('hub.recalculate_in_progress')}
          </p>
          <Progress value={null} className="h-2" />
        </div>
      )}

      {result && (
        <div className="rounded-md border p-3 bg-green-50 border-green-200">
          <p className="text-xs text-green-800">
            {result.message} · docs: {result.documents_queued} · chunks +{result.chunks_created} / -{result.chunks_deleted}
          </p>
        </div>
      )}

      {error && (
        <div className="rounded-md border p-3 bg-destructive/10 border-destructive/30">
          <p className="text-xs text-destructive">{error}</p>
        </div>
      )}
    </>
  )
}
