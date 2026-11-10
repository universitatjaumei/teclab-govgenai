import { useId, useRef, type FormHTMLAttributes, type ReactNode } from 'react'
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
 * en vez de pelearse con él.
 *
 * Sin `ariaLabel` ni `ariaLabelledBy`, el diálogo toma su nombre de la cabecera. Y la capa sólo
 * cierra si el clic **empieza y acaba** en ella: seleccionar texto y soltar fuera manda el `click`
 * a la capa y cerraba el chatbot perdiendo lo escrito (revisión de la PR #375). */
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
  /** Sin `className`: el panel es el formulario, y sus clases van en `className`. */
  form?: Omit<FormHTMLAttributes<HTMLFormElement>, 'className'> & { 'data-testid'?: string }
  testId?: string
}) {
  const idCabecera = useId()
  const pulsadoEnLaCapa = useRef(false)
  const panel = cn(
    'flex flex-col w-full max-w-md max-h-full overflow-hidden rounded-lg shadow-lg bg-background',
    className,
  )
  const contenido = (
    <>
      {header && (
        <div data-modal-header id={idCabecera} className={cn('shrink-0 px-6 pt-6 pb-4', headerClassName)}>
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
      aria-labelledby={ariaLabelledBy ?? (header && !ariaLabel ? idCabecera : undefined)}
      data-testid={testId}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onMouseDown={(e) => { pulsadoEnLaCapa.current = e.target === e.currentTarget }}
      onClick={onBackdropClick ? (e) => {
        if (e.target === e.currentTarget && pulsadoEnLaCapa.current) onBackdropClick()
      } : undefined}
    >
      {form ? (
        <form {...form} className={panel}>{contenido}</form>
      ) : (
        <div className={panel}>{contenido}</div>
      )}
    </div>
  )
}
