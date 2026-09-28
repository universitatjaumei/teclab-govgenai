import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { useTranslation } from 'react-i18next'
import type { ReportUIContract, UIFieldDescriptor } from '@/shared/api/generated/model'
import { DynamicUploadSlots } from './DynamicUploadSlots'
import { DynamicFieldRenderer } from './DynamicFieldRenderer'

export function getLocalizedLabel(
  dict: Record<string, string>,
  locale: string,
): string {
  return dict[locale] ?? dict['es'] ?? dict['en'] ?? Object.values(dict)[0] ?? ''
}

function buildZodSchema(fields: UIFieldDescriptor[]) {
  const shape: Record<string, z.ZodTypeAny> = {}
  for (const f of fields) {
    shape[f.slot_id] = f.required
      ? z.string().min(1, { message: 'required' })
      : z.string().optional()
  }
  return z.object(shape)
}

export type ContractFormData = {
  fields: Record<string, string>
  files: Record<string, File[]>
}

interface Props {
  contract: ReportUIContract
  onSubmit: (data: ContractFormData) => void
  /**
   * INF.1 — slots cuyo fichero ya está subido en el informe. Un obligatorio que ya está
   * satisfecho no se vuelve a exigir: si no, reejecutar obligaría a resubir el mismo fichero.
   */
  satisfiedSlots?: string[]
  /**
   * Issue #86 — lo que ya se escribió en los campos manuales. Sin esto, reejecutar un informe
   * manda el formulario vacío y **borra** lo guardado, porque el endpoint de campos es un `PUT`.
   * Es el equivalente de `satisfiedSlots` para lo que se teclea.
   */
  savedFields?: Record<string, string>
  /** Hay una subida o una generación en marcha: se bloquea el envío y se dice. */
  submitting?: boolean
}

export function ReportUIContractRenderer({
  contract,
  onSubmit,
  satisfiedSlots = [],
  savedFields = {},
  submitting = false,
}: Props) {
  const { i18n, t } = useTranslation('common')
  const { t: tR } = useTranslation('redaccion')
  const [files, setFiles] = useState<Record<string, File[]>>({})
  /** INF.1 — slots de fichero obligatorios que están vacíos al intentar enviar. */
  const [ficherosQueFaltan, setFicherosQueFaltan] = useState<string[]>([])

  const schema = buildZodSchema(contract.manual_fields)
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm({ resolver: zodResolver(schema), values: savedFields })

  function handleFileChange(slotId: string, newFiles: File[]) {
    setFiles(prev => ({ ...prev, [slotId]: newFiles }))
    setFicherosQueFaltan(prev => prev.filter(id => id !== slotId))
  }

  function onValid(values: Record<string, unknown>) {
    // El zod cubre `manual_fields`, que son los que `react-hook-form` registra. Los ficheros
    // viven en estado propio —un `<input type="file">` no es un campo controlado—, así que su
    // obligatoriedad se comprueba aquí. Iba sin comprobar: un informe cuyo dato de partida es
    // un fichero se lanzaba vacío, fallaba dentro del grafo y el aviso solo se veía volviendo
    // atrás con el navegador (bloqueo A de las pruebas del 2026-08-20).
    const faltan = contract.dropzones
      .filter(dz => dz.required)
      .filter(dz => !(files[dz.slot_id]?.length) && !satisfiedSlots.includes(dz.slot_id))
      .map(dz => dz.slot_id)

    setFicherosQueFaltan(faltan)
    if (faltan.length > 0) return

    onSubmit({ fields: values as Record<string, string>, files })
  }

  return (
    <form onSubmit={handleSubmit(onValid)} noValidate>
      <DynamicUploadSlots
        dropzones={contract.dropzones}
        locale={i18n.language}
        onFileChange={handleFileChange}
        missingSlots={ficherosQueFaltan}
        missingMessage={tR('inputs.file_required')}
        satisfiedSlots={satisfiedSlots}
        satisfiedMessage={tR('inputs.file_already_uploaded')}
      />
      <DynamicFieldRenderer
        fields={contract.manual_fields}
        locale={i18n.language}
        register={register}
        errors={errors}
      />
      {/* INF.8 — iba sin una sola clase, así que el único disparador del informe parecía
          texto. Es la accion principal de la pantalla y ahora lo parece. */}
      <button
        type="submit"
        disabled={submitting}
        className="mt-3 px-4 py-2 text-sm font-medium bg-primary text-primary-foreground rounded-md disabled:opacity-50"
      >
        {submitting ? t('loading') : t('continue')}
      </button>
    </form>
  )
}
