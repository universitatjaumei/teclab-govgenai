import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQueryClient } from '@tanstack/react-query'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { zodResolver } from '@hookform/resolvers/zod'
import {
  useListPats,
  useCreatePat,
  useRevokePat,
  useGetPatOpciones,
  getListPatsQueryKey,
} from '@/shared/api/generated/auth-pat/auth-pat'
import type { PatView, PatCreatedResponse } from '@/shared/api/generated/model'

// Los alcances y las organizaciones que se ofrecen los dice el servidor (#230): la lista escrita
// aquí a mano se quedó en cinco mientras el servidor llegaba a quince. Lo único que vive en la
// pantalla es la etiqueta, y un alcance sin traducir se muestra por su código.
function scopeLabelKey(scope: string): string {
  return `scope_${scope.replace(/:/g, '_')}`
}

const patSchema = z.object({
  name: z.string().min(1),
  scopes: z.array(z.string()).min(1),
  expires_at: z.string().optional().or(z.literal('')),
  organizacion_id: z.string().optional().or(z.literal('')),
})
type PatFormValues = z.infer<typeof patSchema>

export function AccessTokensPage() {
  const { t } = useTranslation('auth')
  const { t: tc } = useTranslation('common')
  const qc = useQueryClient()
  const { data: opciones } = useGetPatOpciones()
  const offeredScopes = opciones?.scopes ?? []
  const organizaciones = opciones?.organizaciones ?? []
  const canManage = offeredScopes.length > 0
  const nombreDeOrganizacion = (id: string | null | undefined) =>
    organizaciones.find((o) => o.id === id)?.nombre ?? id

  const [dialogOpen, setDialogOpen] = useState(false)
  const [created, setCreated] = useState<PatCreatedResponse | null>(null)
  const [copied, setCopied] = useState(false)

  const { data: pats = [], isLoading } = useListPats()

  const createMutation = useCreatePat({
    mutation: {
      onSuccess: (res) => {
        qc.invalidateQueries({ queryKey: getListPatsQueryKey() })
        setCreated(res)
        setDialogOpen(false)
        reset()
      },
    },
  })
  const revokeMutation = useRevokePat({
    mutation: {
      onSuccess: () => qc.invalidateQueries({ queryKey: getListPatsQueryKey() }),
    },
  })

  const { register, handleSubmit, reset, formState: { errors } } = useForm<PatFormValues>({
    resolver: zodResolver(patSchema),
    defaultValues: { scopes: [] },
  })

  const onSubmit = (data: PatFormValues) => {
    createMutation.mutate({
      data: {
        name: data.name,
        scopes: data.scopes,
        expires_at: data.expires_at ? new Date(data.expires_at).toISOString() : null,
        organizacion_id: data.organizacion_id || null,
      },
    })
  }

  const handleRevoke = (id: string) => {
    if (window.confirm(t('pat_revoke_confirm'))) {
      revokeMutation.mutate({ patId: id })
    }
  }

  const handleCopy = async () => {
    if (created) {
      await navigator.clipboard.writeText(created.token)
      setCopied(true)
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">{t('pat_title')}</h1>
          <p className="text-sm text-muted-foreground">{t('pat_subtitle')}</p>
        </div>
        {canManage && (
          <button
            className="px-3 py-1.5 rounded bg-primary text-primary-foreground text-sm"
            onClick={() => setDialogOpen(true)}
          >
            {t('pat_new')}
          </button>
        )}
      </div>

      {isLoading ? (
        <p className="text-muted-foreground">{tc('loading')}</p>
      ) : (pats as PatView[]).length === 0 ? (
        <p className="text-muted-foreground">{t('pat_none')}</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm border-collapse" aria-label={t('pat_title')}>
            <thead>
              <tr className="border-b text-left text-muted-foreground">
                <th className="py-2 pr-4">{t('pat_col_name')}</th>
                <th className="py-2 pr-4">{t('pat_col_prefix')}</th>
                <th className="py-2 pr-4">{t('pat_col_scopes')}</th>
                <th className="py-2 pr-4">{t('pat_col_organizacion')}</th>
                <th className="py-2 pr-4">{t('pat_col_last_used')}</th>
                <th className="py-2 pr-4">{t('pat_col_expires')}</th>
                <th className="py-2 pr-4">{t('pat_col_status')}</th>
                <th className="py-2" />
              </tr>
            </thead>
            <tbody>
              {(pats as PatView[]).map((pat) => (
                <tr key={pat.id} className="border-b">
                  <td className="py-2 pr-4 font-medium">{pat.name}</td>
                  <td className="py-2 pr-4 font-mono text-xs">{pat.token_prefix}…</td>
                  <td className="py-2 pr-4 text-xs text-muted-foreground">
                    {pat.scopes.join(', ')}
                  </td>
                  <td className="py-2 pr-4 text-xs">
                    {pat.organizacion_id ? nombreDeOrganizacion(pat.organizacion_id) : t('pat_sin_organizacion')}
                  </td>
                  <td className="py-2 pr-4 text-xs">
                    {pat.last_used_at ? new Date(pat.last_used_at).toLocaleString() : t('pat_never')}
                  </td>
                  <td className="py-2 pr-4 text-xs">
                    {pat.expires_at ? new Date(pat.expires_at).toLocaleDateString() : t('pat_no_expiry')}
                  </td>
                  <td className="py-2 pr-4">
                    <span className={`text-xs px-2 py-0.5 rounded-full ${pat.revoked_at ? 'bg-red-100 text-red-800' : 'bg-green-100 text-green-800'}`}>
                      {pat.revoked_at ? t('pat_status_revoked') : t('pat_status_active')}
                    </span>
                  </td>
                  <td className="py-2">
                    {!pat.revoked_at && canManage && (
                      <button
                        className="text-xs px-2 py-1 rounded border text-destructive hover:bg-destructive/10"
                        onClick={() => handleRevoke(pat.id)}
                        aria-label={t('pat_revoke')}
                      >
                        {t('pat_revoke')}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {dialogOpen && (
        <div role="dialog" aria-modal="true" aria-label={t('pat_modal_title')} className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-background rounded-lg shadow-lg p-6 w-full max-w-md max-h-[90vh] overflow-y-auto space-y-4">
            <h2 className="text-lg font-semibold">{t('pat_modal_title')}</h2>
            <form onSubmit={handleSubmit(onSubmit)} className="space-y-3" noValidate>
              <div>
                <label htmlFor="pat-name" className="text-sm font-medium">{t('pat_field_name')}</label>
                <input id="pat-name" {...register('name')} placeholder={t('pat_field_name_ph')}
                  className="w-full border rounded px-2 py-1.5 text-sm mt-1" />
                {errors.name && <p className="text-xs text-destructive mt-0.5">{tc('required')}</p>}
              </div>
              <fieldset>
                <legend className="text-sm font-medium">{t('pat_field_scopes')}</legend>
                <div className="space-y-1 mt-1">
                  {offeredScopes.map((scope) => (
                    <label key={scope} className="flex items-center gap-2 text-sm">
                      <input type="checkbox" value={scope} {...register('scopes')} />
                      {t(scopeLabelKey(scope), { defaultValue: scope })}
                    </label>
                  ))}
                </div>
                {errors.scopes && <p className="text-xs text-destructive mt-0.5">{tc('required')}</p>}
              </fieldset>
              <div>
                <label htmlFor="pat-organizacion" className="text-sm font-medium">{t('pat_field_organizacion')}</label>
                <select id="pat-organizacion" {...register('organizacion_id')}
                  className="w-full border rounded px-2 py-1.5 text-sm mt-1">
                  <option value="">{t('pat_sin_organizacion')}</option>
                  {organizaciones.map((o) => (
                    <option key={o.id} value={o.id}>{o.nombre}</option>
                  ))}
                </select>
                <p className="text-xs text-muted-foreground mt-0.5">{t('pat_field_organizacion_ayuda')}</p>
              </div>
              <div>
                <label htmlFor="pat-expiry" className="text-sm font-medium">{t('pat_field_expiry')}</label>
                <input id="pat-expiry" {...register('expires_at')} type="date"
                  className="w-full border rounded px-2 py-1.5 text-sm mt-1" />
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <button type="button" onClick={() => { setDialogOpen(false); reset() }} className="px-3 py-1.5 rounded border text-sm">{tc('cancel')}</button>
                <button type="submit" disabled={createMutation.isPending} className="px-3 py-1.5 rounded bg-primary text-primary-foreground text-sm">{t('pat_create')}</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {created && (
        <div role="dialog" aria-modal="true" aria-label={t('pat_created_title')} className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-background rounded-lg shadow-lg p-6 w-full max-w-md space-y-4">
            <h2 className="text-lg font-semibold">{t('pat_created_title')}</h2>
            <p className="text-sm text-destructive">{t('pat_once_warning')}</p>
            <code data-testid="pat-plaintext" className="block break-all bg-muted rounded p-2 text-xs font-mono">
              {created.token}
            </code>
            <div className="flex justify-end gap-2">
              <button onClick={handleCopy} className="px-3 py-1.5 rounded border text-sm">
                {copied ? t('pat_copied') : t('pat_copy')}
              </button>
              <button
                onClick={() => { setCreated(null); setCopied(false) }}
                className="px-3 py-1.5 rounded bg-primary text-primary-foreground text-sm"
              >
                {t('pat_close')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
