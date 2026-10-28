import { Fragment, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQueryClient } from '@tanstack/react-query'
import { useForm, useWatch } from 'react-hook-form'
import { z } from 'zod'
import { zodResolver } from '@hookform/resolvers/zod'
import {
  useListSites,
  useCreateSite,
  useDeleteSite,
  useTriggerSiteCrawl,
  useReconnoiterSite,
  usePatchSite,
  getListSitesQueryKey,
} from '@/shared/api/generated/hub-sites/hub-sites'
import type { ReconnaissanceView, SiteView } from '@/shared/api/generated/model'
import { descargarConAutorizacion } from '@/shared/api/download'
import { useOrganizacionElegida } from '@/shared/organizacion/useOrganizacionElegida'
import { SectionsPanel } from './SectionsPanel'

const siteSchema = z.object({
  name: z.string().min(1),
  root_url: z.string().url(),
  sitemap_url: z.string().url().optional().or(z.literal('')),
  crawl_interval_hours: z.coerce.number().int().min(1).default(24),
  audit_semantic_scope: z.enum(['ingested', 'full', 'off']).default('ingested'),
  // RAS.5 — el rastreo se acota por apartado, que es como tiene sentido usarlo: cada apartado
  // del portal tiene un responsable distinto y un informe del portal completo no lo lee nadie.
  // El spider ya leía esto; lo que no había era forma de fijarlo desde ninguna pantalla.
  url_regex_filter: z
    .string()
    .optional()
    .refine(
      (valor) => {
        if (!valor) return true
        try {
          new RegExp(valor)
          return true
        } catch {
          return false
        }
      },
      { message: 'regex' },
    ),
  crawl_depth: z.coerce.number().int().min(0).max(10).default(1),
  max_pages: z.coerce.number().int().min(1).max(100000).default(50),
  // La cortesía viene puesta: rastrear despacio y respetar robots.txt es el defecto, y quitarlo
  // exige decirlo aquí, donde queda a la vista de quien da de alta el apartado.
  delay_seconds: z.coerce.number().min(0).max(60).default(1),
  respect_robots: z.boolean().default(true),
  // CUR.1 — de dónde saca este portal la fecha que publica cada página. En `www.uji.es` está en
  // `.clockBarDate`, con la unidad responsable al lado. Sin esto, «desactualizada» se adivina.
  content_date_selector: z.string().optional(),
  content_date_format: z.string().default('%d/%m/%Y'),
  // CUR.2.1 — los criterios de juicio son de cada sitio, y por tanto de cada organización: un
  // portal de normativa y uno de noticias no envejecen igual, y donde uno publica series vigentes
  // otro versiona convocatorias. Estaban en el código.
  stale_days: z.coerce.number().int().min(1).max(36500).default(365),
  thin_min_tokens: z.coerce.number().int().min(0).max(100000).default(120),
  version_series_policy: z.enum(['series', 'superseded', 'off']).default('series'),
})

/** Hasta dónde baja el reconocimiento previo (CUR.6). El mismo número que el contrato. */
const PROFUNDIDAD_DEL_SONDEO = 3

type SiteFormInput = z.input<typeof siteSchema>
type SiteFormValues = z.output<typeof siteSchema>

export function SitesPage() {
  const { t } = useTranslation('curation')
  const { t: tc } = useTranslation('common')
  const qc = useQueryClient()
  const [dialogOpen, setDialogOpen] = useState(false)
  // DIN.3 — las secciones de un sitio se despliegan bajo su fila: son trabajo de curación sobre
  // un sitio ya dado de alta, no parte del alta.
  const [sitioDesplegado, setSitioDesplegado] = useState<string | null>(null)
  // REV.10 — la misma elección de organización que el resto del panel, no un selector nuevo.
  const { elegida: organizacionElegida } = useOrganizacionElegida()

  const { data: sites = [], isLoading } = useListSites()
  const createMutation = useCreateSite({
    mutation: {
      onSuccess: () => {
        qc.invalidateQueries({ queryKey: getListSitesQueryKey() })
        setDialogOpen(false)
        reset()
      },
    },
  })
  const deleteMutation = useDeleteSite({
    mutation: {
      onSuccess: () => qc.invalidateQueries({ queryKey: getListSitesQueryKey() }),
    },
  })
  const crawlMutation = useTriggerSiteCrawl()
  // CUR.7 — cambiar el alcance semántico de un sitio ya creado.
  const patchMutation = usePatchSite()

  const cambiarAlcance = (siteId: string, alcance: string) =>
    patchMutation.mutate(
      { siteId, data: { audit_semantic_scope: alcance } },
      { onSuccess: () => qc.invalidateQueries({ queryKey: getListSitesQueryKey() }) },
    )

  // CUR.6 — el reconocimiento previo: cuántas páginas tiene el apartado y cuánto costaría.
  const reconocerMutation = useReconnoiterSite()
  const [reconocimiento, setReconocimiento] = useState<ReconnaissanceView | null>(null)
  const [errorReconocimiento, setErrorReconocimiento] = useState<string | null>(null)

  const { register, handleSubmit, reset, control, getValues, formState: { errors } } = useForm<SiteFormInput, unknown, SiteFormValues>({
    resolver: zodResolver(siteSchema),
    defaultValues: {
      crawl_interval_hours: 24,
      audit_semantic_scope: 'ingested',
      crawl_depth: 1,
      max_pages: 50,
      delay_seconds: 1,
      respect_robots: true,
      content_date_format: '%d/%m/%Y',
      stale_days: 365,
      thin_min_tokens: 120,
      version_series_policy: 'series',
    },
  })
  // `useWatch` y `getValues`, no `watch`: con `watch` el compilador de React salta el componente.
  const urlRaiz = useWatch({ control, name: 'root_url' })

  /**
   * CUR.6 — reconocer la URL del formulario sin haber creado el sitio.
   *
   * Los parámetros del sondeo son los del **rastreo que se lanzaría**: el filtro acota el apartado
   * y la pausa es la que va a dominar el reloj. Con dos segundos por página, mil URLs son media
   * hora, y ése es el número que responde «de golpe o por subapartados».
   */
  const parametrosDelSondeo = () => ({
    root_url: getValues('root_url'),
    url_regex_filter: getValues('url_regex_filter') || undefined,
    delay_seconds: Number(getValues('delay_seconds') ?? 1),
    respect_robots: !!getValues('respect_robots'),
    // Profundidad **del sondeo**, no la del rastreo configurado. Medido contra el portal: con la
    // profundidad 1 que trae el formulario, el reconocimiento devolvía 11 URLs de un apartado que
    // tiene 349 —o sea, contestaba a otra pregunta—. Lo que se quiere saber es cuánto hay ahí.
    crawl_depth: PROFUNDIDAD_DEL_SONDEO,
  })

  const reconocer = async () => {
    setErrorReconocimiento(null)
    setReconocimiento(null)
    try {
      const informe = await reconocerMutation.mutateAsync({ data: parametrosDelSondeo() })
      setReconocimiento(informe)
    } catch (fallo) {
      setErrorReconocimiento(fallo instanceof Error ? fallo.message : String(fallo))
    }
  }

  const descargarElSitemap = async () => {
    setErrorReconocimiento(null)
    try {
      await descargarConAutorizacion(
        '/api/v1/hub/site-reconnaissance',
        'sitemap.csv',
        { ...parametrosDelSondeo(), formato: 'csv' },
      )
    } catch (fallo) {
      setErrorReconocimiento(fallo instanceof Error ? fallo.message : String(fallo))
    }
  }

  const onSubmit = (data: SiteFormValues) => {
    createMutation.mutate({
      // De quién es el sitio. `POST /hub/sites` lo recibe como parámetro de consulta y sin él
      // responde **403 «Indica la organización del sitio»** a quien no sea superadministrador
      // (SEC.8.1: sin organización el sitio queda fuera de toda cascada y de todo listado
      // acotado). La pantalla no lo enviaba, así que un administrador de organización **no podía
      // crear un sitio desde la interfaz** — y es la única forma de crearlo. Lo destapó el
      // montaje de la verificación de DIN.7.
      //
      // Sin organización elegida no se inventa ninguna: un superadministrador puede querer un
      // sitio de plataforma, y ésa es su decisión, no la de esta pantalla.
      ...(organizacionElegida ? { params: { organizacion_id: organizacionElegida } } : {}),
      data: {
        name: data.name,
        root_url: data.root_url,
        sitemap_url: data.sitemap_url || undefined,
        crawl_interval_hours: data.crawl_interval_hours,
        audit_semantic_scope: data.audit_semantic_scope,
        crawl_config: {
          url_regex_filter: data.url_regex_filter || undefined,
          crawl_depth: data.crawl_depth,
          max_pages: data.max_pages,
          delay_seconds: data.delay_seconds,
          respect_robots: data.respect_robots,
          content_date_selector: data.content_date_selector || undefined,
          content_date_format: data.content_date_format,
          stale_days: data.stale_days,
          thin_min_tokens: data.thin_min_tokens,
          version_series_policy: data.version_series_policy,
        },
      },
    })
  }

  const handleCrawl = (siteId: string) => {
    crawlMutation.mutate({ siteId })
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">{t('sites_title')}</h1>
        <button
          className="px-3 py-1.5 rounded bg-primary text-primary-foreground text-sm"
          data-testid="btn-nuevo-sitio"
          onClick={() => setDialogOpen(true)}
        >
          {t('new_site')}
        </button>
      </div>

      {isLoading ? (
        <p className="text-muted-foreground">{tc('loading')}</p>
      ) : sites.length === 0 ? (
        <p className="text-muted-foreground">{t('no_sites')}</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm border-collapse" aria-label={t('sites_title')}>
            <thead>
              <tr className="border-b text-left text-muted-foreground">
                <th className="py-2 pr-4">{t('site_name')}</th>
                <th className="py-2 pr-4">{t('site_root_url')}</th>
                <th className="py-2 pr-4">{t('site_last_crawled')}</th>
                <th className="py-2 pr-4">{t('site_status')}</th>
                <th className="py-2 pr-4">{t('site_audit_scope')}</th>
                <th className="py-2" />
              </tr>
            </thead>
            <tbody>
              {(sites as SiteView[]).map((site) => (
                <Fragment key={site.id}>
                <tr className="border-b hover:bg-accent/30">
                  <td className="py-2 pr-4 font-medium">{site.name}</td>
                  <td className="py-2 pr-4 text-xs text-muted-foreground truncate max-w-xs">{site.root_url}</td>
                  <td className="py-2 pr-4 text-xs">
                    {site.last_crawled_at
                      ? new Date(site.last_crawled_at).toLocaleString()
                      : t('site_never_crawled')}
                  </td>
                  <td className="py-2 pr-4">
                    <span className={`text-xs px-2 py-0.5 rounded-full ${site.status === 'active' ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}`}>
                      {site.status}
                    </span>
                  </td>
                  {/* CUR.7 — el alcance semántico se fijaba sólo al crear el sitio, y es la
                      decisión que se toma después: se rastrea, se lee el informe, y entonces se
                      decide si vale pagar embeddings y llamadas al modelo. */}
                  <td className="py-2 pr-4">
                    <select
                      data-testid={`alcance-${site.id}`}
                      aria-label={t('site_audit_scope')}
                      value={site.audit_semantic_scope ?? 'ingested'}
                      onChange={(e) => cambiarAlcance(site.id, e.target.value)}
                      className="text-xs border rounded px-1 py-0.5"
                    >
                      <option value="ingested">{t('scope_ingested')}</option>
                      <option value="full">{t('scope_full')}</option>
                      <option value="off">{t('scope_off')}</option>
                    </select>
                  </td>
                  <td className="py-2 space-x-2">
                    <button
                      className="text-xs px-2 py-1 rounded border hover:bg-accent"
                      onClick={() => handleCrawl(site.id)}
                      aria-label={t('crawl_now')}
                    >
                      {t('crawl_now')}
                    </button>
                    {/* DIN.3 — parametrizar los apartados del sitio: es lo que convierte
                        «añadir el apartado de becas» en un formulario. */}
                    <button
                      className="text-xs px-2 py-1 rounded border hover:bg-accent"
                      data-testid={`btn-secciones-${site.id}`}
                      aria-expanded={sitioDesplegado === site.id}
                      onClick={() =>
                        setSitioDesplegado((abierto) =>
                          abierto === site.id ? null : site.id,
                        )
                      }
                    >
                      {t('sections_title')}
                    </button>
                    <button
                      className="text-xs px-2 py-1 rounded border text-destructive hover:bg-destructive/10"
                      onClick={() => deleteMutation.mutate({ siteId: site.id })}
                      aria-label={tc('delete')}
                    >
                      {tc('delete')}
                    </button>
                  </td>
                </tr>
                {sitioDesplegado === site.id && (
                  <tr className="border-b bg-accent/10">
                    <td colSpan={6} className="py-3 px-2">
                      <SectionsPanel siteId={site.id} />
                    </td>
                  </tr>
                )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {dialogOpen && (
        <div role="dialog" aria-modal="true" aria-label={t('new_site')} className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-background rounded-lg shadow-lg p-6 w-full max-w-md space-y-4">
            <h2 className="text-lg font-semibold">{t('new_site')}</h2>
            <form onSubmit={handleSubmit(onSubmit)} className="space-y-3" noValidate data-testid="form-sitio">
              <div>
                <label className="text-sm font-medium">{t('site_name')}</label>
                <input {...register('name')} data-testid="campo-nombre" className="w-full border rounded px-2 py-1.5 text-sm mt-1" />
                {errors.name && <p className="text-xs text-destructive mt-0.5">{tc('required')}</p>}
              </div>
              <div>
                <label className="text-sm font-medium">{t('site_root_url')}</label>
                <input {...register('root_url')} data-testid="campo-url" className="w-full border rounded px-2 py-1.5 text-sm mt-1" type="url" />
                {errors.root_url && <p className="text-xs text-destructive mt-0.5">{tc('invalid_url')}</p>}
              </div>
              <div>
                <label className="text-sm font-medium">{t('site_sitemap_url')}</label>
                <input {...register('sitemap_url')} className="w-full border rounded px-2 py-1.5 text-sm mt-1" type="url" />
              </div>

              {/* CUR.6 — «valorar la extensión del sitio y si conviene hacerlo todo de golpe o por
                  subapartados». El portal no publica sitemap (404 medido en RAS.4), así que se
                  construye recorriendo: un sondeo corto que no guarda nada. */}
              <fieldset className="border-t pt-3 space-y-2">
                <legend className="text-sm font-medium">{t('recon_title')}</legend>
                <p className="text-xs text-muted-foreground">{t('recon_help')}</p>
                <button
                  type="button"
                  data-testid="btn-reconocer"
                  disabled={!urlRaiz || reconocerMutation.isPending}
                  onClick={reconocer}
                  className="text-xs px-2 py-1 rounded border disabled:opacity-50"
                >
                  {reconocerMutation.isPending ? t('recon_running') : t('recon_run')}
                </button>

                {errorReconocimiento && (
                  <p data-testid="error-reconocimiento" className="text-xs text-destructive">
                    {t('recon_failed')}: {errorReconocimiento}
                  </p>
                )}

                {reconocimiento && (
                  <div className="space-y-2">
                    <p className="text-xs" data-testid="total-urls">
                      {t('recon_total', {
                        urls: reconocimiento.urls_encontradas,
                        sondeadas: reconocimiento.paginas_sondeadas,
                      })}
                    </p>
                    <p className="text-xs font-medium" data-testid="estimacion-rastreo">
                      {t('recon_estimate', {
                        minutos: Math.round(reconocimiento.segundos_estimados / 60),
                        porPagina: reconocimiento.segundos_por_pagina.toFixed(1),
                      })}
                    </p>
                    {reconocimiento.truncado && (
                      <p data-testid="aviso-sondeo-truncado" className="text-xs text-amber-700">
                        {t('recon_truncated', { motivo: reconocimiento.motivo_de_parada ?? '' })}
                      </p>
                    )}
                    <table className="w-full text-xs border-collapse" data-testid="apartados-del-sitio">
                      <thead>
                        <tr className="border-b text-left text-muted-foreground">
                          <th className="py-1 pr-2">{t('recon_section')}</th>
                          <th className="py-1 pr-2">{t('recon_section_urls')}</th>
                          <th className="py-1">{t('recon_section_example')}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {reconocimiento.apartados.map((a) => (
                          <tr key={a.apartado} className="border-b">
                            <td className="py-1 pr-2 font-mono">{a.apartado}</td>
                            <td className="py-1 pr-2">{a.urls}</td>
                            <td className="py-1 truncate max-w-[16rem] text-muted-foreground">
                              {a.ejemplos[0] ?? '—'}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    <button
                      type="button"
                      data-testid="btn-descargar-csv"
                      onClick={descargarElSitemap}
                      className="text-xs px-2 py-1 rounded border"
                    >
                      {t('recon_download_csv')}
                    </button>
                  </div>
                )}
              </fieldset>
              <div>
                <label className="text-sm font-medium">{t('site_interval')}</label>
                <input {...register('crawl_interval_hours')} type="number" min={1} className="w-full border rounded px-2 py-1.5 text-sm mt-1" />
              </div>
              <div>
                <label className="text-sm font-medium">{t('site_audit_scope')}</label>
                <select {...register('audit_semantic_scope')} className="w-full border rounded px-2 py-1.5 text-sm mt-1">
                  <option value="ingested">{t('scope_ingested')}</option>
                  <option value="full">{t('scope_full')}</option>
                </select>
              </div>
              {/* El apartado y la cortesía: lo que convierte «rastrear un portal» en «rastrear
                  este apartado, despacio y por donde el servidor deja». */}
              <fieldset className="border-t pt-3 space-y-3">
                <legend className="text-sm font-medium">{t('site_crawl_section')}</legend>
                <div>
                  <label className="text-sm font-medium" htmlFor="url_regex_filter">
                    {t('site_url_filter')}
                  </label>
                  <input
                    {...register('url_regex_filter')}
                    id="url_regex_filter"
                    data-testid="campo-url-regex"
                    placeholder="/centres/escola-doctorat/"
                    className="w-full border rounded px-2 py-1.5 text-sm mt-1 font-mono"
                  />
                  <p className="text-xs text-muted-foreground mt-0.5">{t('site_url_filter_help')}</p>
                  {errors.url_regex_filter && (
                    <p data-testid="error-url-regex" className="text-xs text-destructive mt-0.5">
                      {t('site_url_filter_invalid')}
                    </p>
                  )}
                </div>
                <div className="grid grid-cols-3 gap-2">
                  <div>
                    <label className="text-sm font-medium" htmlFor="crawl_depth">
                      {t('site_depth')}
                    </label>
                    <input {...register('crawl_depth')} id="crawl_depth" data-testid="campo-profundidad" type="number" min={0} max={10} className="w-full border rounded px-2 py-1.5 text-sm mt-1" />
                  </div>
                  <div>
                    <label className="text-sm font-medium" htmlFor="max_pages">
                      {t('site_max_pages')}
                    </label>
                    <input {...register('max_pages')} id="max_pages" data-testid="campo-max-paginas" type="number" min={1} className="w-full border rounded px-2 py-1.5 text-sm mt-1" />
                  </div>
                  <div>
                    <label className="text-sm font-medium" htmlFor="delay_seconds">
                      {t('site_delay')}
                    </label>
                    <input {...register('delay_seconds')} id="delay_seconds" data-testid="campo-pausa" type="number" min={0} step={0.5} className="w-full border rounded px-2 py-1.5 text-sm mt-1" />
                  </div>
                </div>
                <label className="flex items-center gap-2 text-sm">
                  <input {...register('respect_robots')} data-testid="campo-robots" type="checkbox" />
                  {t('site_respect_robots')}
                </label>
                {/* CUR.1 — la fecha que el propio portal publica en cada página. Con ella,
                    «desactualizada» es un dato; sin ella se adivina por el año de la URL. */}
                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <label className="text-sm font-medium" htmlFor="content_date_selector">
                      {t('site_date_selector')}
                    </label>
                    <input
                      {...register('content_date_selector')}
                      id="content_date_selector"
                      data-testid="campo-selector-fecha"
                      placeholder=".clockBarDate"
                      className="w-full border rounded px-2 py-1.5 text-sm mt-1 font-mono"
                    />
                  </div>
                  <div>
                    <label className="text-sm font-medium" htmlFor="content_date_format">
                      {t('site_date_format')}
                    </label>
                    <input
                      {...register('content_date_format')}
                      id="content_date_format"
                      data-testid="campo-formato-fecha"
                      className="w-full border rounded px-2 py-1.5 text-sm mt-1 font-mono"
                    />
                  </div>
                </div>
                <p className="text-xs text-muted-foreground">{t('site_date_help')}</p>
              </fieldset>

              {/* CUR.2.1 — los criterios con los que se juzga el contenido de ESTE sitio. Vivían en
                  el código, así que todas las organizaciones compartían el mismo. */}
              <fieldset className="border-t pt-3 space-y-3">
                <legend className="text-sm font-medium">{t('site_criteria_section')}</legend>
                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <label className="text-sm font-medium" htmlFor="stale_days">
                      {t('site_stale_days')}
                    </label>
                    <input {...register('stale_days')} id="stale_days" data-testid="campo-antiguedad" type="number" min={1} className="w-full border rounded px-2 py-1.5 text-sm mt-1" />
                  </div>
                  <div>
                    <label className="text-sm font-medium" htmlFor="thin_min_tokens">
                      {t('site_thin_tokens')}
                    </label>
                    <input {...register('thin_min_tokens')} id="thin_min_tokens" data-testid="campo-pobreza" type="number" min={0} className="w-full border rounded px-2 py-1.5 text-sm mt-1" />
                  </div>
                </div>
                <div>
                  <label className="text-sm font-medium" htmlFor="version_series_policy">
                    {t('site_series_policy')}
                  </label>
                  <select {...register('version_series_policy')} id="version_series_policy" data-testid="campo-politica-series" className="w-full border rounded px-2 py-1.5 text-sm mt-1">
                    <option value="series">{t('series_policy_series')}</option>
                    <option value="superseded">{t('series_policy_superseded')}</option>
                    <option value="off">{t('series_policy_off')}</option>
                  </select>
                  <p className="text-xs text-muted-foreground mt-0.5">{t('site_series_help')}</p>
                </div>
                <p className="text-xs text-muted-foreground">{t('site_courtesy_help')}</p>
              </fieldset>

              <div className="flex justify-end gap-2 pt-2">
                <button type="button" onClick={() => { setDialogOpen(false); reset() }} className="px-3 py-1.5 rounded border text-sm">{tc('cancel')}</button>
                <button type="submit" disabled={createMutation.isPending} className="px-3 py-1.5 rounded bg-primary text-primary-foreground text-sm">{tc('save')}</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
