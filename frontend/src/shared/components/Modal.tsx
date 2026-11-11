import { useId, useLayoutEffect, useRef, useState, type FormHTMLAttributes, type ReactNode } from 'react'
import FocusLock from 'react-focus-lock'
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
 * Sin `ariaLabel` ni `ariaLabelledBy`, el diálogo toma su nombre del encabezado de la cabecera. Y la capa sólo
 * cierra si el clic **empieza y acaba** en ella: seleccionar texto y soltar fuera manda el `click`
 * a la capa y cerraba el chatbot perdiendo lo escrito (revisión de la PR #375).
 *
 * Con teclado (#376): el foco entra al abrir —en la ventana misma, que se anuncia por su nombre,
 * y no en su primer botón, que en «archivar plantilla» era «Retirar» (revisión de la PR #377)—, Tab no sale de la ventana, Escape llama a `onClose`
 * y al cerrar el foco vuelve a quien la abrió —el `FocusLock returnFocus` de DrawerHub—. Una
 * ventana que sustituye a otra (formulario → resultado) es **la misma** `Modal` con otro
 * contenido: si fueran dos, la segunda guardaría como «quien la abrió» un botón de la primera,
 * ya retirado, y el foco acabaría en <body> (revisión de la PR #377, en Tokens).
 * `onClose` es obligatorio a propósito: cada ventana decide si se puede cerrar, y `null` es
 * «ahora no» (`ConfirmDialog` mientras borra). Escape se escucha en la capa y no en `window`:
 * así, con dos ventanas apiladas, cierra sólo la de arriba, que es donde está el foco. */
export function Modal({
  children,
  header,
  footer,
  ariaLabel,
  ariaLabelledBy,
  onBackdropClick,
  onClose,
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
  /** Lo que hace Escape; `null` si ahora no se puede cerrar. */
  onClose: (() => void) | null
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
  const cabecera = useRef<HTMLDivElement>(null)
  // El nombre sale del primer encabezado de la cabecera, no de toda ella: la del chatbot lleva
  // también el aspa de cerrar y se anunciaba «Nou chatbot ✕» (#376, visto en el navegador).
  const [idDelNombre, setIdDelNombre] = useState<string>()
  useLayoutEffect(() => {
    const titulo = cabecera.current?.querySelector('h1, h2, h3, h4, h5, h6')
    if (titulo && !titulo.id) titulo.id = `${idCabecera}-titulo`
    setIdDelNombre(titulo ? titulo.id : cabecera.current ? idCabecera : undefined)
  }, [idCabecera, header])
  const panel = cn(
    'flex flex-col w-full max-w-md max-h-full overflow-hidden rounded-lg shadow-lg bg-background',
    className,
  )
  const contenido = (
    <>
      {header && (
        <div data-modal-header ref={cabecera} id={idCabecera} className={cn('shrink-0 px-6 pt-6 pb-4', headerClassName)}>
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
    <FocusLock returnFocus>
      <div
        // `data-autofocus`: el foco inicial va a la ventana y no al primer botón. Si un campo
        // ya lo tiene por `autoFocus`, FocusLock lo respeta.
        data-autofocus
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label={ariaLabel}
        aria-labelledby={ariaLabelledBy ?? (ariaLabel ? undefined : idDelNombre)}
        data-testid={testId}
        className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 outline-none"
        onMouseDown={(e) => { pulsadoEnLaCapa.current = e.target === e.currentTarget }}
        onClick={onBackdropClick ? (e) => {
          if (e.target === e.currentTarget && pulsadoEnLaCapa.current) onBackdropClick()
        } : undefined}
        onKeyDown={(e) => {
          if (e.key !== 'Escape') return
          // La de arriba se queda el Escape: sin esto, con dos apiladas cerrarían las dos, y el
          // de DrawerHub, que escucha en `window`, cerraría el cajón.
          e.stopPropagation()
          // Un hijo que ya usó el Escape —un desplegable, cancelar una composición IME, que
          // Safari marca con `keyCode` 229 y no con `isComposing`— se lo queda: cerrar la
          // ventana entera tiraría lo escrito (revisión de la PR #377).
          if (e.defaultPrevented || e.nativeEvent.isComposing || e.keyCode === 229) return
          onClose?.()
        }}
      >
        {form ? (
          <form {...form} className={panel}>{contenido}</form>
        ) : (
          <div className={panel}>{contenido}</div>
        )}
      </div>
    </FocusLock>
  )
}
