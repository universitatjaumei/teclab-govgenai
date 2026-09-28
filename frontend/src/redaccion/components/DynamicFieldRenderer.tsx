import type { FieldErrors, FieldValues, UseFormRegister } from 'react-hook-form'
import type { UIFieldDescriptor } from '@/shared/api/generated/model'
import { getLocalizedLabel } from './ReportUIContractRenderer'

interface Props {
  fields: UIFieldDescriptor[]
  locale: string
  register: UseFormRegister<FieldValues>
  errors: FieldErrors
}

/**
 * Los campos que se teclean del informe.
 *
 * **Iban sin una sola clase**, así que el `input` se pintaba sin borde y sin separación: en la
 * plantilla del doctorado, al aparecer sus cuatro campos por primera vez (issue #86), lo que se
 * veía era una lista de cuatro frases sueltas. Un campo invisible es tan poco «dónde
 * rellenarlo» como no tenerlo, que es justo lo que la issue venía a arreglar. Nadie lo había
 * notado porque `manual_fields` llegaba vacío en las plantillas que se usaban.
 *
 * El aspecto es el mismo que el de las zonas de subida, incluido el asterisco del obligatorio:
 * son dos mitades del mismo formulario y no hay razón para que se distingan.
 */
export function DynamicFieldRenderer({ fields, locale, register, errors }: Props) {
  return (
    <div className="space-y-3">
      {fields.map(f => {
        const label = getLocalizedLabel(f.label, locale)
        const placeholder = getLocalizedLabel(f.placeholder ?? {}, locale)
        const error = errors[f.slot_id]
        const inputId = `field_${f.slot_id}`
        return (
          <div key={f.slot_id}>
            <label htmlFor={inputId} className="block text-sm font-medium mb-1">
              {label}
              {f.required && <span aria-hidden="true"> *</span>}
            </label>
            <input
              id={inputId}
              type={f.field_type === 'number' ? 'number' : 'text'}
              placeholder={placeholder}
              aria-required={f.required ?? false}
              {...register(f.slot_id)}
              className={`w-full rounded-md border px-3 py-2 text-sm bg-background ${
                error ? 'border-destructive' : 'border-input'
              }`}
            />
            {error && (
              <span role="alert" className="text-destructive text-xs">
                {String(error.message)}
              </span>
            )}
          </div>
        )
      })}
    </div>
  )
}
