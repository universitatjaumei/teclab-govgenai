import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQueryClient } from '@tanstack/react-query'
import {
  useListSites,
  useListSitePages,
  useProponerPagina,
  useRetirarPropuestaDePagina,
  getListSitePagesQueryKey,
} from '@/shared/api/generated/hub-sites/hub-sites'
import type { PageView } from '@/shared/api/generated/model'
import { mensajeDelFallo } from '@/utilidades/mensajeDelFallo'
import { PageContentDialog } from './PageContentDialog'

/**
 * Las páginas de un sitio, para proponer las que deberían alimentar un asistente (2026-10-08).
 *
 * Piloto del asistente de la Escuela de Doctorado: quien cura revisa la web y, a la vez, marca
 * qué páginas deberían alimentarlo; quien crea el asistente decide en Publicación. La marca es
 * del servidor —quién y cuándo— y es de la página, no de un asistente: se propone antes de que
 * exista. Proponer no publica nada.
 *
 * No había ninguna pantalla con todas las páginas de un sitio: la lista de Troballes sólo enseña
 * las que tienen un problema, y la mayoría de las que irían a un asistente no tienen ninguno.
 */
/** Los estados que da el rastreo a una página. Otro, si apareciera, se enseña tal cual.
 *  Claves escritas enteras: el guardarraíl de claves sin uso no ve las que se componen. */
const ETIQUETA_DE_ESTADO: Record<string, string> = {
  active: 'pages_status_active',
  error: 'pages_status_error',
  gone: 'pages_status_gone',
}

export function PaginesPage() {
  const { t, i18n } = useTranslation('curation')
  const qc = useQueryClient()
  const [siteId, setSiteId] = useState('')
  const [soloPropuestas, setSoloPropuestas] = useState(false)
  const [paginaAbierta, setPaginaAbierta] = useState<string | null>(null)
  const [fallo, setFallo] = useState<string | null>(null)

  const { data: sitios = [] } = useListSites()
  const { data: paginas = [], isLoading, isError, error } = useListSitePages(
    siteId,
    soloPropuestas ? { propuestas: true } : undefined,
    { query: { enabled: !!siteId } },
  )
  const { mutate: proponer } = useProponerPagina()
  const { mutate: retirar } = useRetirarPropuestaDePagina()

  function alternar(pagina: PageView) {
    setFallo(null)
    const opciones = {
      onSuccess: () => qc.invalidateQueries({ queryKey: getListSitePagesQueryKey(siteId) }),
      onError: (e: unknown) => setFallo(mensajeDelFallo(e, t('pages_error'))),
    }
    if (pagina.propuesta_at) retirar({ siteId, pageId: pagina.id }, opciones)
    else proponer({ siteId, pageId: pagina.id }, opciones)
  }

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-xl font-semibold">{t('pages_title')}</h2>
        <p className="text-sm text-muted-foreground">{t('pages_intro')}</p>
      </div>

      <div className="flex flex-wrap items-center gap-4">
        <select
          aria-label={t('pages_site')}
          value={siteId}
          onChange={(e) => setSiteId(e.target.value)}
          className="rounded-md border px-2 py-1.5 text-sm"
        >
          <option value="">{t('select_site')}</option>
          {sitios.map((s) => (
            <option key={s.id} value={s.id}>{s.name}</option>
          ))}
        </select>
        <label className="flex items-center gap-1.5 text-sm">
          <input
            type="checkbox"
            checked={soloPropuestas}
            onChange={(e) => setSoloPropuestas(e.target.checked)}
          />
          {t('pages_only_proposed')}
        </label>
      </div>

      {fallo && (
        <p role="alert" className="rounded-md border border-destructive/40 bg-destructive/10 p-2 text-sm text-destructive">
          {fallo}
        </p>
      )}

      {siteId && (isLoading ? (
        <p className="text-sm text-muted-foreground">{t('pages_loading')}</p>
      ) : isError ? (
        // Revisión de la PR #246: un fallo al cargar se leía como «no hay páginas».
        <p role="alert" className="rounded-md border border-destructive/40 bg-destructive/10 p-2 text-sm text-destructive">
          {mensajeDelFallo(error, t('pages_load_error'))}
        </p>
      ) : paginas.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t('pages_empty')}</p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-left">
              <th className="py-2">{t('pages_col_page')}</th>
              <th>{t('pages_col_status')}</th>
              <th>{t('pages_col_proposed')}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {(paginas as PageView[]).map((p) => (
              <tr key={p.id} data-testid={`pagina-${p.id}`} className="border-b align-top">
                <td className="py-2 pr-4">
                  <div className="font-medium">{p.title ?? p.url}</div>
                  <a href={p.url} target="_blank" rel="noreferrer" className="break-all text-xs text-muted-foreground underline">
                    {p.url}
                  </a>
                </td>
                <td className="pr-4">
                  {ETIQUETA_DE_ESTADO[p.status] ? t(ETIQUETA_DE_ESTADO[p.status]) : p.status}
                </td>
                <td className="pr-4">
                  <label className="flex items-center gap-1.5">
                    <input
                      type="checkbox"
                      checked={!!p.propuesta_at}
                      onChange={() => alternar(p)}
                      aria-label={t('pages_propose_aria', { page: p.title ?? p.url })}
                    />
                    {p.propuesta_at && (
                      <span className="text-xs text-muted-foreground">
                        {t('pages_proposed_by', {
                          who: p.propuesta_por ?? '—',
                          date: new Date(p.propuesta_at).toLocaleDateString(i18n.language),
                        })}
                      </span>
                    )}
                  </label>
                </td>
                <td>
                  <button type="button" onClick={() => setPaginaAbierta(p.id)} className="text-xs underline">
                    {t('view_stored_content')}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ))}

      {paginaAbierta && <PageContentDialog pageId={paginaAbierta} onClose={() => setPaginaAbierta(null)} />}
    </div>
  )
}
