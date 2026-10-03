import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useConectarLaExtensionApiV1AgentesExtensionConectarPost } from '@/shared/api/generated/agentes/agentes'
import type { ConexionEmitida } from '@/shared/api/generated/model'
import { mensajeDelFallo } from '@/utilidades/mensajeDelFallo'

/**
 * La página que abre la extensión del navegador al pulsar «Conectar» (#176).
 *
 * La persona ya está aquí con su sesión; confirma, el servidor emite un token que **sólo sirve
 * para consultar** y la página vuelve a la extensión con el token en el fragmento, que no llega a
 * ningún servidor. **A qué destino se vuelve lo decide el servidor**: sólo emite para una
 * extensión declarada, así que esta página no redirige a ninguna dirección que él no haya
 * aceptado.
 *
 * El botón es explícito a propósito: sin él, cualquier página que abriera esta dirección se
 * llevaría un token sin que la persona hubiera decidido nada.
 */
export function ConectarExtensionPage() {
  const { t } = useTranslation('agentes')
  const conectar = useConectarLaExtensionApiV1AgentesExtensionConectarPost()
  const [fallo, setFallo] = useState<string | null>(null)
  const destino = useMemo(() => new URLSearchParams(window.location.search).get('destino') ?? '', [])

  function confirmar() {
    setFallo(null)
    conectar.mutate(
      { data: { destino } },
      {
        onSuccess: (r: ConexionEmitida) => window.location.assign(`${destino}#token=${encodeURIComponent(r.token)}`),
        onError: (e: unknown) => setFallo(mensajeDelFallo(e, t('extension.fallo'))),
      },
    )
  }

  return (
    <div className="mx-auto max-w-md space-y-4 p-8">
      <h1 className="text-xl font-semibold">{t('extension.conectar_titulo')}</h1>
      <p className="text-sm">{t('extension.conectar_texto')}</p>
      <p className="text-xs text-muted-foreground">{t('extension.no_es_control')}</p>
      <button
        type="button"
        onClick={confirmar}
        disabled={!destino || conectar.isPending}
        className="rounded-md bg-primary px-3 py-1.5 text-sm text-primary-foreground disabled:opacity-50"
      >
        {t('extension.conectar')}
      </button>
      {fallo && (
        <p role="alert" className="text-sm text-destructive">
          {fallo}
        </p>
      )}
    </div>
  )
}
