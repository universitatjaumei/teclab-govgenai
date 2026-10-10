import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import {
  useListOrganizacionesApiV1HubOrganizacionesGet,
  useCreateOrganizacionApiV1HubOrganizacionesPost,
  useUpdateOrganizacionApiV1HubOrganizacionesOrganizacionIdPatch,
  useDeleteOrganizacionApiV1HubOrganizacionesOrganizacionIdDelete,
  getListOrganizacionesApiV1HubOrganizacionesGetQueryKey,
} from '@/shared/api/generated/hub-organizaciones/hub-organizaciones'
import type { OrganizacionRead } from '@/shared/api/generated/model'

/**
 * #252 — el servidor no borra una organización que todavía tiene datos: responde 409 con
 * `detail.pendiente`, cuánto le queda de cada cosa. Las claves las decide el servidor; aquí sólo
 * se traducen.
 */
function pendienteDelFallo(fallo: unknown): Record<string, number> | null {
  const detalle = (fallo as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (!detalle || typeof detalle !== 'object' || !('pendiente' in detalle)) return null
  const pendiente = (detalle as { pendiente?: unknown }).pendiente
  return pendiente && typeof pendiente === 'object' ? (pendiente as Record<string, number>) : null
}

const schema = z.object({
  name: z.string().min(1),
  partner_id: z.string().min(1),
  is_active: z.boolean(),
})
type FormValues = z.infer<typeof schema>

export function OrganizacionesPage() {
  const { t } = useTranslation('admin')
  const { t: tc } = useTranslation('common')
  const qc = useQueryClient()
  const [editing, setEditing] = useState<OrganizacionRead | null>(null)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<OrganizacionRead | null>(null)
  const [deleteError, setDeleteError] = useState('')
  const [deletePendiente, setDeletePendiente] = useState<Record<string, number> | null>(null)
  const [filter, setFilter] = useState('')

  const listQueryKey = getListOrganizacionesApiV1HubOrganizacionesGetQueryKey()
  const invalidateList = () => qc.invalidateQueries({ queryKey: listQueryKey })

  const { data: organizaciones = [], isLoading } = useListOrganizacionesApiV1HubOrganizacionesGet()

  const toBody = (values: FormValues) => ({
    name: values.name,
    partner_id: values.partner_id,
    is_active: values.is_active,
  })

  const createMutation = useCreateOrganizacionApiV1HubOrganizacionesPost({
    mutation: { onSuccess: () => { invalidateList(); closeDialog() } },
  })

  const updateMutation = useUpdateOrganizacionApiV1HubOrganizacionesOrganizacionIdPatch({
    mutation: { onSuccess: () => { invalidateList(); closeDialog() } },
  })

  const toggleMutation = useUpdateOrganizacionApiV1HubOrganizacionesOrganizacionIdPatch({
    mutation: { onSuccess: invalidateList },
  })

  const deleteMutation = useDeleteOrganizacionApiV1HubOrganizacionesOrganizacionIdDelete({
    mutation: {
      onSuccess: () => {
        invalidateList()
        setDeleteTarget(null)
        setDeleteError('')
        setDeletePendiente(null)
      },
      onError: (err: Error) => {
        const pendiente = pendienteDelFallo(err)
        setDeletePendiente(pendiente)
        setDeleteError(pendiente ? t('hub.delete_organizacion_con_datos') : err.message)
      },
    },
  })

  // PLAT.3 — los valores por defecto de RAG salieron de aquí a `/hub/valores-por-defecto`.
  // No se pierden: las columnas del modelo declaran los mismos valores que declaraba este
  // formulario, así que dar de alta una organización la deja igual configurada que antes.
  const { register, handleSubmit, reset, formState: { errors } } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { name: '', partner_id: '', is_active: true },
  })

  function openCreate() {
    setEditing(null)
    reset({ name: '', partner_id: '', is_active: true })
    setDialogOpen(true)
  }

  function openEdit(c: OrganizacionRead) {
    setEditing(c)
    reset({
      name: c.name,
      partner_id: c.partner_id,
      is_active: c.is_active,
    })
    setDialogOpen(true)
  }

  function closeDialog() {
    setDialogOpen(false)
    setEditing(null)
    reset()
  }

  function onSubmit(values: FormValues) {
    if (editing) {
      updateMutation.mutate({ organizacionId: editing.id, data: toBody(values) })
    } else {
      createMutation.mutate({ data: toBody(values) })
    }
  }

  const isPending = createMutation.isPending || updateMutation.isPending

  const filtered = filter
    ? organizaciones.filter((c) => c.name.toLowerCase().includes(filter.toLowerCase()))
    : organizaciones

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">{t('hub.organizaciones')}</h1>
        <button
          type="button"
          onClick={openCreate}
          className="px-3 py-2 bg-primary text-primary-foreground text-sm rounded-md"
        >
          {t('hub.new_organizacion')}
        </button>
      </div>

      <input
        type="text"
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        placeholder={t('hub.filter_placeholder')}
        className="w-full px-3 py-2 border rounded-md text-sm bg-background"
        aria-label={t('hub.filter_placeholder')}
      />

      {isLoading && <p className="text-muted-foreground text-sm">{tc('loading')}</p>}

      {!isLoading && filtered.length === 0 && (
        <p className="text-muted-foreground text-sm py-8 text-center">{t('hub.no_organizaciones')}</p>
      )}

      {filtered.length > 0 && (
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-left text-muted-foreground">
              <th className="pb-2 font-medium">{t('hub.organizacion_name')}</th>
              <th className="pb-2 font-medium">{t('hub.organizacion_admin')}</th>
              <th className="pb-2 font-medium">{t('hub.organizacion_chatbots')}</th>
              <th className="pb-2 font-medium">{t('hub.organizacion_active')}</th>
              <th className="pb-2" />
            </tr>
          </thead>
          <tbody>
            {filtered.map((c) => (
              <tr
                key={c.id}
                className="border-b last:border-0 hover:bg-accent/30 cursor-pointer"
                onClick={() => openEdit(c)}
              >
                <td className="py-3 pr-4">{c.name}</td>
                <td className="py-3 pr-4 text-muted-foreground">{c.partner_id}</td>
                <td className="py-3 pr-4">
                  <span className="text-xs px-2 py-0.5 rounded-full bg-secondary text-secondary-foreground border">
                    {c.chatbot_count}
                  </span>
                </td>
                <td className="py-3 pr-4">
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation()
                      toggleMutation.mutate({ organizacionId: c.id, data: { is_active: !c.is_active } })
                    }}
                    className={`text-xs px-2 py-0.5 rounded-full border transition-colors ${
                      c.is_active
                        ? 'bg-green-100 text-green-700 border-green-200 hover:bg-green-200'
                        : 'bg-gray-100 text-gray-500 border-gray-200 hover:bg-gray-200'
                    }`}
                  >
                    {c.is_active ? t('hub.organizacion_active') : tc('edit')}
                  </button>
                </td>
                <td className="py-3 text-right">
                  {/* PLAT.6 — al nivel de esta organización en la cascada visual. Quien mira
                      esta fila es quien quiere cambiarle el logotipo; hacerle buscar la
                      pantalla y volver a elegir la organización en un selector es trabajo
                      que ya está hecho aquí. */}
                  <Link
                    to={`/plataforma/identidad-visual?organizacion=${c.id}`}
                    onClick={(e) => e.stopPropagation()}
                    className="text-xs hover:underline px-2"
                  >
                    {t('hub.organizacion_identidad_visual')}
                  </Link>
                  <button
                    type="button"
                    onClick={(e) => { e.stopPropagation(); setDeleteTarget(c) }}
                    className="text-destructive text-xs hover:underline px-2"
                  >
                    {tc('delete')}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {/* Dialog crear / editar */}
      {dialogOpen && (
        <div role="dialog" aria-modal="true" className="fixed inset-0 flex items-center justify-center bg-black/40 z-50">
          <div className="bg-card rounded-lg p-6 w-full max-w-md shadow-lg space-y-4">
            <h2 className="text-lg font-semibold">
              {editing ? tc('edit') + ' — ' + editing.name : t('hub.new_organizacion')}
            </h2>
            <form onSubmit={handleSubmit(onSubmit)} className="space-y-3">
              <div>
                <label htmlFor="organizacion_name" className="text-sm font-medium">{t('hub.organizacion_name')}</label>
                <input
                  id="organizacion_name"
                  {...register('name')}
                  className="w-full mt-1 px-3 py-2 border rounded-md text-sm bg-background"
                />
                {errors.name && <p className="text-destructive text-xs mt-1">{errors.name.message}</p>}
              </div>
              <div>
                <label htmlFor="organizacion_admin_id" className="text-sm font-medium">{t('hub.organizacion_admin')}</label>
                <input
                  id="organizacion_admin_id"
                  {...register('partner_id')}
                  className="w-full mt-1 px-3 py-2 border rounded-md text-sm bg-background"
                />
                {errors.partner_id && <p className="text-destructive text-xs mt-1">{errors.partner_id.message}</p>}
              </div>
              <div className="flex items-center gap-2">
                <input type="checkbox" id="is_active" {...register('is_active')} className="rounded" />
                <label htmlFor="is_active" className="text-sm">{t('hub.organizacion_active')}</label>
              </div>
              <div className="flex gap-2 justify-end pt-2">
                <button
                  type="button"
                  onClick={closeDialog}
                  className="px-3 py-2 border rounded-md text-sm"
                >
                  {tc('cancel')}
                </button>
                <button
                  type="submit"
                  disabled={isPending}
                  className="px-3 py-2 bg-primary text-primary-foreground rounded-md text-sm disabled:opacity-50"
                >
                  {tc('save')}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Dialog confirmación borrado */}
      {deleteTarget && (
        <div role="dialog" aria-modal="true" className="fixed inset-0 flex items-center justify-center bg-black/40 z-50">
          <div className="bg-card rounded-lg p-6 w-full max-w-sm shadow-lg space-y-4">
            <p className="text-sm">{t('hub.delete_organizacion_confirm')}</p>
            <p className="font-medium">{deleteTarget.name}</p>
            {deleteError && <p className="text-destructive text-xs">{deleteError}</p>}
            {deletePendiente && (
              <ul className="text-destructive text-xs list-disc pl-5">
                {Object.entries(deletePendiente).map(([clave, cuantos]) => (
                  <li key={clave}>{t(`hub.organizacion_pendiente_${clave}`, { count: cuantos })}</li>
                ))}
              </ul>
            )}
            <div className="flex gap-2 justify-end">
              <button
                type="button"
                onClick={() => { setDeleteTarget(null); setDeleteError(''); setDeletePendiente(null) }}
                className="px-3 py-2 border rounded-md text-sm"
              >
                {tc('cancel')}
              </button>
              <button
                type="button"
                onClick={() => deleteMutation.mutate({ organizacionId: deleteTarget.id })}
                disabled={deleteMutation.isPending}
                className="px-3 py-2 bg-destructive text-destructive-foreground rounded-md text-sm disabled:opacity-50"
              >
                {tc('delete')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
