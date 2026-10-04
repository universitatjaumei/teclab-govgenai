import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQueryClient } from '@tanstack/react-query'
import {
  useConexionesDeLaExtensionApiV1AgentesExtensionConexionesGet,
  useRevocarConexionDeLaExtensionApiV1AgentesExtensionConexionesConexionIdDelete,
} from '@/shared/api/generated/agentes/agentes'
import { mensajeDelFallo } from '@/utilidades/mensajeDelFallo'

/**
 * Dónde está conectada la extensión del navegador de quien mira, y cómo desconectarla (#176).
 *
 * Desconectar desde la extensión sólo olvida el token en ese navegador; **revocarlo es aquí**, y
 * es lo que hay que hacer con un ordenador perdido o prestado.
 */
export function ConexionesDeLaExtension() {
  const { t } = useTranslation('agentes')
  const queryClient = useQueryClient()
  const conexiones = useConexionesDeLaExtensionApiV1AgentesExtensionConexionesGet()
  const revocar = useRevocarConexionDeLaExtensionApiV1AgentesExtensionConexionesConexionIdDelete()
  const [fallo, setFallo] = useState<string | null>(null)

  const refrescar = () =>
    void queryClient.invalidateQueries({
      predicate: (consulta) => String(consulta.queryKey[0] ?? '').startsWith('/api/v1/agentes/extension'),
    })

  const lista = conexiones.data ?? []
  return (
    <section className="space-y-2 rounded-md border p-4" data-testid="conexiones-extension">
      <h2 className="font-medium">{t('extension.titulo')}</h2>
      <p className="text-xs text-muted-foreground">{t('extension.intro')}</p>
      {lista.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t('extension.ninguna')}</p>
      ) : (
        <ul className="space-y-1 text-xs">
          {lista.map((c) => (
            <li key={c.id} className="flex flex-wrap items-center gap-2">
              <code>{c.prefijo}…</code>
              <span>{t('extension.conectada', { fecha: new Date(c.creado_en).toLocaleString() })}</span>
              <span className="text-muted-foreground">
                {c.ultimo_uso_en
                  ? t('extension.usada', { fecha: new Date(c.ultimo_uso_en).toLocaleString() })
                  : t('extension.sin_usar')}
              </span>
              {c.caduca_en && (
                <span className="text-muted-foreground">
                  {t('extension.caduca', { fecha: new Date(c.caduca_en).toLocaleDateString() })}
                </span>
              )}
              <button
                type="button"
                onClick={() => {
                  setFallo(null)
                  revocar.mutate(
                    { conexionId: c.id },
                    { onSuccess: refrescar, onError: (e: unknown) => setFallo(mensajeDelFallo(e, t('extension.fallo'))) },
                  )
                }}
                className="rounded-md border px-2 py-0.5"
              >
                {t('extension.revocar')}
              </button>
            </li>
          ))}
        </ul>
      )}
      {fallo && (
        <p role="alert" className="text-sm text-destructive">
          {fallo}
        </p>
      )}
    </section>
  )
}
