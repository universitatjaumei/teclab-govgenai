import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { UIDropzoneDescriptor } from '@/shared/api/generated/model'
import { getLocalizedLabel } from '../utils/getLocalizedLabel'

interface Props {
  dropzones: UIDropzoneDescriptor[]
  locale: string
  onFileChange: (slotId: string, files: File[]) => void
  /** INF.1 — slots obligatorios que estaban vacíos al intentar enviar. */
  missingSlots?: string[]
  /** Texto del aviso, ya traducido: este componente no llama a i18n para el aviso. */
  missingMessage?: string
  /** INF.1 — slots cuyo fichero ya está en el informe de una ejecución anterior. */
  satisfiedSlots?: string[]
  /** Texto que lo dice, ya traducido. */
  satisfiedMessage?: string
}

/**
 * Las zonas de subida del informe (INF.8).
 *
 * De las pruebas humanas del 2026-08-20: «Aparece esta información como texto sin que se sepa
 * que *Tria un fitxer* es un botón». Era un `<input type="file">` desnudo, así que el navegador
 * pintaba su propio control **en su propio idioma** —de ahí el catalán en una pantalla en
 * castellano— y nada indicaba dónde había que pulsar.
 *
 * El `input` sigue existiendo y sigue siendo el que recibe el fichero: se oculta visualmente
 * pero **no** con `display:none`, y la etiqueta lo referencia con `htmlFor`, así que el foco,
 * el teclado y el lector de pantalla siguen funcionando igual. Lo que cambia es que el texto y
 * el aspecto los pone la aplicación.
 */
export function DynamicUploadSlots({
  dropzones,
  locale,
  onFileChange,
  missingSlots = [],
  missingMessage = '',
  satisfiedSlots = [],
  satisfiedMessage = '',
}: Props) {
  const { t } = useTranslation('redaccion')
  const [elegidos, setElegidos] = useState<Record<string, string>>({})
  const arrastrando = useRef<string | null>(null)

  function recibir(slotId: string, ficheros: File[]) {
    setElegidos((previos) => ({
      ...previos,
      [slotId]: ficheros.map((f) => f.name).join(', '),
    }))
    onFileChange(slotId, ficheros)
  }

  return (
    <div className="space-y-3">
      {dropzones.map((dz) => {
        const label = getLocalizedLabel(dz.label, locale)
        const inputId = `dropzone_${dz.slot_id}`
        const errorId = `${inputId}_error`
        const falta = missingSlots.includes(dz.slot_id)
        const yaSubido = !falta && satisfiedSlots.includes(dz.slot_id)
        const nombre = elegidos[dz.slot_id]

        return (
          <div key={dz.slot_id}>
            <label htmlFor={inputId} className="block text-sm font-medium mb-1">
              {label}
              {dz.required && <span aria-hidden="true"> *</span>}
            </label>

            {/* La zona: es la etiqueta del input, así que pulsarla y arrastrar encima hacen lo
                mismo que el control del navegador, pero con el texto de la aplicación. */}
            <label
              htmlFor={inputId}
              data-testid={`zona-${dz.slot_id}`}
              onDragOver={(e) => {
                e.preventDefault()
                arrastrando.current = dz.slot_id
              }}
              onDrop={(e) => {
                e.preventDefault()
                arrastrando.current = null
                recibir(dz.slot_id, Array.from(e.dataTransfer.files ?? []))
              }}
              className={`flex flex-col items-center justify-center gap-1 w-full px-4 py-6 border-2 border-dashed rounded-md cursor-pointer text-center transition-colors ${
                falta
                  ? 'border-destructive bg-destructive/5'
                  : 'border-input hover:border-primary hover:bg-accent/40'
              }`}
            >
              <span className="text-sm font-medium">{t('inputs.drop_here')}</span>
              <span className="text-xs text-muted-foreground">
                {(dz.accept ?? []).length > 0
                  ? t('inputs.accepted_formats', { formatos: (dz.accept ?? []).join(', ') })
                  : t('inputs.any_format')}
              </span>
            </label>

            <input
              id={inputId}
              type="file"
              accept={(dz.accept ?? []).join(',')}
              multiple={dz.multiple ?? false}
              aria-required={dz.required ?? false}
              aria-invalid={falta}
              aria-describedby={falta ? errorId : undefined}
              onChange={(e) => recibir(dz.slot_id, Array.from(e.target.files ?? []))}
              // Oculto a la vista pero **no** para el teclado ni para el lector de pantalla:
              // `display:none` lo sacaría del orden de tabulación y dejaría la zona inservible
              // sin ratón.
              className="sr-only"
            />

            {/* El fichero elegido, con su nombre. El control del navegador lo decía y el
                nuestro tenía que seguir diciéndolo. */}
            {nombre && (
              <p data-testid={`elegido-${dz.slot_id}`} className="text-xs mt-1">
                {t('inputs.chosen', { nombre })}
              </p>
            )}

            {falta && (
              <p id={errorId} role="alert" className="text-xs text-destructive mt-1">
                {label}: {missingMessage}
              </p>
            )}
            {yaSubido && !nombre && (
              <p data-testid={`slot-satisfecho-${dz.slot_id}`} className="text-xs text-muted-foreground mt-1">
                {satisfiedMessage}
              </p>
            )}
          </div>
        )
      })}
    </div>
  )
}
