import type { ReactNode } from 'react'
import { Loader2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Modal } from './Modal'

/** Confirmación modal de una acción destructiva.
 *
 * Nació para el corpus y vive en `shared` desde #358, cuando borrar un sitio de Curación pasó a
 * pedir confirmación. «Cancelar» se bloquea mientras se confirma: la petición ya ha salido, y
 * cerrar el diálogo haría creer que no se ha borrado nada (revisión de la PR #359). */
export function ConfirmDialog({
  title, description, confirmLabel, isPending, onConfirm, onCancel, destructive = false,
}: {
  title: string
  description: ReactNode
  confirmLabel: string
  isPending: boolean
  onConfirm: () => void
  onCancel: () => void
  destructive?: boolean
}) {
  const { t: tc } = useTranslation('common')

  return (
    <Modal
      onClose={isPending ? null : onCancel}
      className="bg-card"
      header={<h3 className={`text-lg font-semibold ${destructive ? 'text-destructive' : ''}`}>{title}</h3>}
      footer={
        <>
          <button type="button" onClick={onCancel} disabled={isPending} className="px-4 py-2 border rounded-md text-sm font-medium disabled:opacity-50">{tc('cancel')}</button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={isPending}
            className="px-4 py-2 bg-destructive text-destructive-foreground rounded-md text-sm font-medium disabled:opacity-50 flex items-center gap-2"
          >
            {isPending && <Loader2 className="w-4 h-4 animate-spin" />}
            {confirmLabel}
          </button>
        </>
      }
    >
      <div className="text-sm text-muted-foreground space-y-2">{description}</div>
    </Modal>
  )
}
