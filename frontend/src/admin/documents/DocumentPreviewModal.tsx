import { useTranslation } from 'react-i18next'
import { Loader2 } from 'lucide-react'

import type { HubDocumentDetailOut } from '@/shared/api/generated/model'
import { Modal } from '@/shared/components/Modal'

/** Vista del markdown ingestado, que es lo que acaba viendo el modelo. */
export function DocumentPreviewModal({
  detail,
  isLoading,
  onClose,
}: {
  detail: HubDocumentDetailOut | undefined
  isLoading: boolean
  onClose: () => void
}) {
  const { t: tc } = useTranslation('common')

  return (
    <Modal
      className="bg-card max-w-3xl shadow-xl"
      headerClassName="flex items-center justify-between p-4 border-b"
      bodyClassName="p-4"
      header={
        <>
          <h3 className="text-base font-semibold truncate">
            {isLoading ? tc('loading') : detail?.title}
          </h3>
          <button
            type="button"
            onClick={onClose}
            className="p-1 text-muted-foreground hover:text-foreground"
          >✕</button>
        </>
      }
    >
      {isLoading ? (
        <div className="flex items-center justify-center gap-2 text-muted-foreground py-8">
          <Loader2 className="w-5 h-5 animate-spin" />{tc('loading')}
        </div>
      ) : (
        <pre className="text-xs whitespace-pre-wrap font-mono text-foreground/80">
          {detail?.markdown_content}
        </pre>
      )}
    </Modal>
  )
}
