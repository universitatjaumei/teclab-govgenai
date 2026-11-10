import type { FormHTMLAttributes, ReactNode } from 'react'
import { cn } from '@/lib/utils'

/** La ventana modal de todo el panel (#374).
 *
 * Cada diálogo montaba su propia capa centrada, y doce de diecisiete no limitaban la altura del
 * panel: un formulario más alto que la ventana —el de «Nueva web» de Curación— salía cortado por
 * arriba y por abajo, sin scroll que llegara a «Guardar». Aquí el panel no pasa de la altura de la
 * ventana (menos el margen de la capa) y lo que sobra se recorre con scroll **en el cuerpo**: la
 * cabecera y el pie, que es donde están los botones, quedan siempre a la vista.
 *
 * Con `form`, el panel entero es el `<form>`: así el botón de enviar puede ir en el pie fijo y
 * seguir dentro del formulario.
 *
 * Las clases que se pasan se mezclan con `cn`, así que un `p-4` sustituye al relleno por defecto
 * en vez de pelearse con él. */
export function Modal({
  children,
  header,
  footer,
  ariaLabel,
  ariaLabelledBy,
  onBackdropClick,
  className,
  headerClassName,
  bodyClassName,
  footerClassName,
  form,
  testId,
}: {
  children: ReactNode
  header?: ReactNode
  footer?: ReactNode
  ariaLabel?: string
  ariaLabelledBy?: string
  onBackdropClick?: () => void
  /** Clases del panel: la anchura (`max-w-sm`, `max-w-3xl`…) y el fondo, sobre todo. */
  className?: string
  headerClassName?: string
  bodyClassName?: string
  footerClassName?: string
  form?: FormHTMLAttributes<HTMLFormElement> & { 'data-testid'?: string }
  testId?: string
}) {
  const panel = cn(
    'flex flex-col w-full max-w-md max-h-full overflow-hidden rounded-lg shadow-lg bg-background',
    className,
  )
  const contenido = (
    <>
      {header && (
        <div data-modal-header className={cn('shrink-0 px-6 pt-6 pb-4', headerClassName)}>
          {header}
        </div>
      )}
      <div
        data-modal-body
        className={cn(
          'min-h-0 flex-1 overflow-y-auto overscroll-contain px-6 space-y-4',
          header ? 'pt-0' : 'pt-6',
          footer ? 'pb-1' : 'pb-6',
          bodyClassName,
        )}
      >
        {children}
      </div>
      {footer && (
        <div data-modal-footer className={cn('shrink-0 flex justify-end gap-2 px-6 pt-4 pb-6', footerClassName)}>
          {footer}
        </div>
      )}
    </>
  )

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={ariaLabel}
      aria-labelledby={ariaLabelledBy}
      data-testid={testId}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onBackdropClick ? (e) => { if (e.target === e.currentTarget) onBackdropClick() } : undefined}
    >
      {form ? (
        <form {...form} className={panel}>{contenido}</form>
      ) : (
        <div className={panel}>{contenido}</div>
      )}
    </div>
  )
}
