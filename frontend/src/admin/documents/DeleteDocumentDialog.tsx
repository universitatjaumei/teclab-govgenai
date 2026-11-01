import { useTranslation } from 'react-i18next'
import { ConfirmDialog } from '@/shared/components/ConfirmDialog'
import type { HubDocumentOut } from '@/shared/api/generated/model'

/**
 * Confirmación de borrado de un documento, con el aviso de las copias hermanas (DER.2).
 *
 * Con el documento duplicado por chatbot —se descartó compartirlo, ver el bloque COR—,
 * «borrar la norma» es ambiguo: puede significar quitarla de este asistente o retirarla del
 * corpus de la organización. El aviso sale **antes** de confirmar; decirlo después convierte
 * la información en un lamento, porque quien la lee ya ha borrado.
 *
 * Y el borrado en cascada se marca a mano: hacerlo por defecto sobre corpus normativo es
 * cómo se pierde una norma sin que nadie lo haya pedido.
 */
export function DeleteDocumentDialog({
  documento,
  copiasEnOtrosChatbots,
  borrarEnTodos,
  onBorrarEnTodosChange,
  isPending,
  onConfirm,
  onCancel,
}: {
  documento: HubDocumentOut
  copiasEnOtrosChatbots: number
  borrarEnTodos: boolean
  onBorrarEnTodosChange: (valor: boolean) => void
  isPending: boolean
  onConfirm: () => void
  onCancel: () => void
}) {
  const { t } = useTranslation('admin')

  return (
    <ConfirmDialog
      title={t('hub.delete_doc_title')}
      description={
        <>
          {t('hub.delete_doc_text')} <strong>{documento.title}</strong>
          {copiasEnOtrosChatbots > 0 && (
            <span className="mt-3 block rounded-md border border-amber-500/50 bg-amber-500/10 p-2 text-xs">
              <span data-testid="copias-aviso" className="block font-medium">
                {t('hub.delete_doc_copias', { count: copiasEnOtrosChatbots })}
              </span>
              <label className="mt-2 flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={borrarEnTodos}
                  onChange={(e) => onBorrarEnTodosChange(e.target.checked)}
                  className="rounded"
                />
                {t('hub.delete_doc_en_todos')}
              </label>
            </span>
          )}
        </>
      }
      confirmLabel={t('hub.delete_doc_confirm')}
      isPending={isPending}
      onConfirm={onConfirm}
      onCancel={onCancel}
      destructive
    />
  )
}
