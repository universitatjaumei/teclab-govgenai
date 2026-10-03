import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  useGuionApiV1AgentesGuionGet,
  useTokensDelGuionApiV1AgentesTokensGet,
  useEmitirTokenDelGuionApiV1AgentesTokensPost,
  useRevocarTokenDelGuionApiV1AgentesTokensTokenIdDelete,
  useSubirHojaApiV1AgentesAgenteIdIndiceHojaPost,
} from '@/shared/api/generated/agentes/agentes'
import type { AgenteView, InformeDeCarga, TokenDelGuionEmitido } from '@/shared/api/generated/model'
import { apiBaseUrl } from '@/shared/api/client'
import { mensajeDelFallo } from '@/utilidades/mensajeDelFallo'
import { useQueryClient } from '@tanstack/react-query'

/**
 * Cómo se mantiene el índice de un agente (#174; decisión del usuario, 2026-10-03).
 *
 * **Lo normal es un guion de Apps Script que corre a diario** en el Drive de la unidad: recorre la
 * carpeta, resume lo nuevo y manda el índice. Aquí está lo que hace falta para instalarlo —el
 * guion, el identificador del agente, la dirección de la plataforma y un token que sólo sirve para
 * esto— y la vía secundaria, subir la hoja a mano. **Nada de esto lo decide la pantalla**: el
 * guion y su huella los da el servidor, y el token lo emite el servidor.
 */
export function ActualizacionDelIndice({ agente }: { agente: AgenteView }) {
  const { t } = useTranslation('agentes')
  const queryClient = useQueryClient()
  const [viendoGuion, setViendoGuion] = useState(false)
  const [emitido, setEmitido] = useState<TokenDelGuionEmitido | null>(null)
  const [informe, setInforme] = useState<InformeDeCarga | null>(null)
  const [fallo, setFallo] = useState<string | null>(null)

  // La API cuelga del origen de la página, salvo que el despliegue diga otra cosa.
  const plataforma = apiBaseUrl || window.location.origin

  const guion = useGuionApiV1AgentesGuionGet({ query: { enabled: viendoGuion } })
  const tokens = useTokensDelGuionApiV1AgentesTokensGet()
  const emitir = useEmitirTokenDelGuionApiV1AgentesTokensPost()
  const revocar = useRevocarTokenDelGuionApiV1AgentesTokensTokenIdDelete()
  const subirHoja = useSubirHojaApiV1AgentesAgenteIdIndiceHojaPost()

  const refrescar = () =>
    void queryClient.invalidateQueries({
      predicate: (consulta) => String(consulta.queryKey[0] ?? '').startsWith('/api/v1/agentes'),
    })
  const alFallar = (e: unknown) => setFallo(mensajeDelFallo(e, t('fallo')))

  function emitirToken() {
    setFallo(null)
    emitir.mutate(
      { data: { nombre: `Guion · ${agente.nombre}` } },
      {
        onSuccess: (r: TokenDelGuionEmitido) => {
          setEmitido(r)
          refrescar()
        },
        onError: alFallar,
      },
    )
  }

  function cargarHoja(fichero: File | undefined) {
    if (!fichero) return
    setFallo(null)
    setInforme(null)
    subirHoja.mutate(
      { agenteId: agente.id, data: { file: fichero } },
      {
        onSuccess: (r: InformeDeCarga) => {
          setInforme(r)
          refrescar()
        },
        onError: alFallar,
      },
    )
  }

  return (
    <div className="space-y-4 rounded-md border p-3">
      <section className="space-y-2">
        <h3 className="text-sm font-medium">{t('actualizacion.automatica')}</h3>
        <p className="text-xs text-muted-foreground">{t('actualizacion.intro')}</p>
        <dl className="grid gap-x-4 gap-y-1 text-sm sm:grid-cols-[max-content_1fr]">
          <dt className="text-muted-foreground">{t('actualizacion.agente_id')}</dt>
          <dd>
            <code data-testid="agente-id">{agente.id}</code>
          </dd>
          <dt className="text-muted-foreground">{t('actualizacion.plataforma_url')}</dt>
          <dd>
            <code data-testid="plataforma-url">{plataforma}</code>
          </dd>
        </dl>
        <ol className="list-decimal space-y-1 pl-5 text-xs">
          <li>{t('actualizacion.paso_hoja')}</li>
          <li>{t('actualizacion.paso_guion')}</li>
          <li>{t('actualizacion.paso_propiedades')}</li>
          <li>{t('actualizacion.paso_diario')}</li>
        </ol>

        <button type="button" onClick={() => setViendoGuion((v) => !v)} className="rounded-md border px-2 py-1 text-xs">
          {t(viendoGuion ? 'actualizacion.ocultar_guion' : 'actualizacion.ver_guion')}
        </button>
        {viendoGuion && guion.data && (
          <div className="space-y-1">
            <p className="text-xs text-muted-foreground">
              {t('actualizacion.version_y_huella', { version: guion.data.version, huella: guion.data.sha256.slice(0, 12) })}
            </p>
            <label className="block text-xs font-medium" htmlFor={`guion_${agente.id}`}>{t('actualizacion.codigo')}</label>
            <textarea
              id={`guion_${agente.id}`}
              readOnly
              rows={8}
              data-testid="codigo-del-guion"
              value={guion.data.codigo}
              className="w-full rounded-md border bg-muted px-2 py-1 font-mono text-xs"
            />
            <label className="block text-xs font-medium" htmlFor={`manifiesto_${agente.id}`}>{t('actualizacion.manifiesto')}</label>
            <textarea
              id={`manifiesto_${agente.id}`}
              readOnly
              rows={4}
              value={guion.data.manifiesto}
              className="w-full rounded-md border bg-muted px-2 py-1 font-mono text-xs"
            />
          </div>
        )}
      </section>

      <section className="space-y-2">
        <h3 className="text-sm font-medium">{t('actualizacion.tokens')}</h3>
        <p className="text-xs text-muted-foreground">{t('actualizacion.tokens_intro')}</p>
        <button
          type="button"
          onClick={emitirToken}
          disabled={emitir.isPending}
          className="rounded-md bg-primary px-3 py-1 text-xs text-primary-foreground disabled:opacity-50"
        >
          {t('actualizacion.emitir')}
        </button>
        {emitido && (
          <div className="space-y-1">
            <label className="block text-xs font-medium" htmlFor={`token_${agente.id}`}>{t('actualizacion.token_emitido')}</label>
            <input
              id={`token_${agente.id}`}
              readOnly
              data-testid="token-emitido"
              value={emitido.token}
              className="w-full rounded-md border bg-muted px-2 py-1 font-mono text-xs"
            />
            <p className="text-xs font-medium">{t('actualizacion.solo_una_vez')}</p>
          </div>
        )}
        {(tokens.data ?? []).length > 0 && (
          <ul className="space-y-1 text-xs">
            {(tokens.data ?? []).map((tk) => (
              <li key={tk.id} className="flex flex-wrap items-center gap-2">
                <span>{tk.nombre}</span>
                <code>{tk.prefijo}…</code>
                <span className="text-muted-foreground">
                  {tk.ultimo_uso_en
                    ? t('actualizacion.usado', { fecha: new Date(tk.ultimo_uso_en).toLocaleString() })
                    : t('actualizacion.sin_usar')}
                </span>
                <button
                  type="button"
                  onClick={() => revocar.mutate({ tokenId: tk.id }, { onSuccess: refrescar, onError: alFallar })}
                  className="rounded-md border px-2 py-0.5"
                >
                  {t('actualizacion.revocar')}
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="space-y-1">
        <h3 className="text-sm font-medium">{t('actualizacion.a_mano')}</h3>
        <label htmlFor={`hoja_${agente.id}`} className="text-sm font-medium">{t('hoja_del_indice')}</label>
        <input
          id={`hoja_${agente.id}`}
          type="file"
          accept=".csv,.xlsx"
          disabled={subirHoja.isPending}
          onChange={(e) => cargarHoja(e.target.files?.[0])}
          className="block text-sm"
        />
        <p className="text-xs text-muted-foreground">{t('pistas.hoja_del_indice')}</p>
        {informe && (
          <p className="text-sm" data-testid="informe-de-carga" role="status">
            {t('informe_de_carga', {
              nuevas: t('nuevas', { count: informe.nuevas }),
              actualizadas: t('actualizadas', { count: informe.actualizadas }),
              sin_cambios: t('sin_cambios', { count: informe.sin_cambios }),
              retiradas: t('retiradas', { count: informe.retiradas }),
            })}
          </p>
        )}
      </section>

      {fallo && <p className="text-sm text-destructive" role="alert">{fallo}</p>}
    </div>
  )
}
