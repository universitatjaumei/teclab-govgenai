import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQueryClient } from '@tanstack/react-query'
import {
  useCambiarElAdaptadorApiV1AgentesAsistentesAsistenteAdaptadorPut,
  useEstadoDeLosAdaptadoresApiV1AgentesAsistentesGet,
} from '@/shared/api/generated/agentes/agentes'
import type { EstadoDelAdaptador } from '@/shared/api/generated/model'
import { mensajeDelFallo } from '@/utilidades/mensajeDelFallo'

/**
 * Si la integración con el asistente funciona, y corregirla sin publicar la extensión (#215).
 *
 * La extensión inserta el prompt en Gemini y lee la respuesta con unos selectores que sirve la
 * plataforma. Cuando Gemini cambia su página, las extensiones avisan de qué selector dejó de casar
 * y aquí se ve; se corrige y cada cambio es una versión nueva que todas toman sin actualizarse.
 * **Qué selectores hay lo dice el servidor**: la pantalla pinta los que recibe.
 */
export function IntegracionAsistentePage() {
  const { t } = useTranslation('agentes')
  const { data: adaptadores, isLoading, error } = useEstadoDeLosAdaptadoresApiV1AgentesAsistentesGet()

  return (
    <div className="space-y-6">
      <header className="space-y-2">
        <h1 className="text-xl font-semibold">{t('integracion.titulo')}</h1>
        <p className="text-sm text-muted-foreground">{t('integracion.intro')}</p>
      </header>
      {isLoading ? (
        <p className="text-sm text-muted-foreground">{t('cargando')}</p>
      ) : error ? (
        <p role="alert" className="text-sm text-destructive">
          {mensajeDelFallo(error, t('fallo'))}
        </p>
      ) : (
        (adaptadores ?? []).map((a) => <Adaptador key={`${a.asistente}-${a.version}`} adaptador={a} />)
      )}
    </div>
  )
}

function Adaptador({ adaptador }: { adaptador: EstadoDelAdaptador }) {
  const { t } = useTranslation('agentes')
  const queryClient = useQueryClient()
  const cambiar = useCambiarElAdaptadorApiV1AgentesAsistentesAsistenteAdaptadorPut()
  const [selectores, setSelectores] = useState<Record<string, string>>(adaptador.selectores)
  const [fallo, setFallo] = useState<string | null>(null)
  const cambiado = Object.entries(selectores).some(([k, v]) => adaptador.selectores[k] !== v)

  function guardar() {
    setFallo(null)
    cambiar.mutate(
      { asistente: adaptador.asistente, data: { selectores } },
      {
        onSuccess: () =>
          void queryClient.invalidateQueries({
            predicate: (consulta) => String(consulta.queryKey[0] ?? '').startsWith('/api/v1/agentes/asistentes'),
          }),
        onError: (e: unknown) => setFallo(mensajeDelFallo(e, t('fallo'))),
      },
    )
  }

  return (
    <section className="space-y-3 rounded-md border p-4" data-testid={`adaptador-${adaptador.asistente}`}>
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="font-medium">{adaptador.nombre}</h2>
        <span className="text-xs text-muted-foreground">{t('integracion.version', { version: adaptador.version })}</span>
        {adaptador.rota ? (
          <span data-testid="integracion-rota" className="rounded bg-red-100 px-2 py-0.5 text-xs text-red-900">
            {t('integracion.rota', {
              count: adaptador.fallos_de_la_version,
              selector: adaptador.ultimo_fallo_selector,
              fecha: adaptador.ultimo_fallo_en ? new Date(adaptador.ultimo_fallo_en).toLocaleString() : '',
            })}
          </span>
        ) : (
          <span data-testid="integracion-funciona" className="rounded bg-muted px-2 py-0.5 text-xs">
            {t('integracion.funciona')}
          </span>
        )}
      </div>
      <p className="text-xs text-muted-foreground">{t('integracion.como_corregir')}</p>
      <div className="space-y-2">
        {Object.entries(selectores).map(([clave, valor]) => (
          <label key={clave} className="block space-y-1 text-sm">
            <span className="font-mono text-xs">{clave}</span>
            <input
              value={valor}
              onChange={(e) => setSelectores({ ...selectores, [clave]: e.target.value })}
              aria-label={clave}
              className="w-full rounded-md border px-2 py-1 font-mono text-xs"
            />
          </label>
        ))}
      </div>
      <button
        type="button"
        onClick={guardar}
        disabled={!cambiado || cambiar.isPending}
        className="rounded-md bg-primary px-3 py-1.5 text-sm text-primary-foreground disabled:opacity-50"
      >
        {t('integracion.guardar')}
      </button>
      {fallo && (
        <p role="alert" className="text-sm text-destructive">
          {fallo}
        </p>
      )}
    </section>
  )
}
