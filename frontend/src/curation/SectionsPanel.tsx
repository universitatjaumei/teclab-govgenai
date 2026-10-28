import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQueryClient } from '@tanstack/react-query'
import { useForm, useWatch } from 'react-hook-form'
import { z } from 'zod'
import { zodResolver } from '@hookform/resolvers/zod'
import {
  useListSiteSections,
  useCreateSiteSection,
  usePatchSiteSection,
  useDeleteSiteSection,
  useTestSectionPattern,
  getListSiteSectionsQueryKey,
} from '@/shared/api/generated/hub-sites/hub-sites'
import type { PatternTestView, SectionView } from '@/shared/api/generated/model'
import { RunsPanel } from './RunsPanel'

/**
 * DIN.3 — las secciones de un sitio, parametrizables por quien cura.
 *
 * El contrato manda: la lista se construye de lo que devuelve el hook —incluida la cadencia
 * efectiva y la bandera de si es heredada, que las calcula el servidor— y el formulario valida
 * contra las mismas reglas que el backend. Aquí no se decide nada.
 */
const seccionSchema = z.object({
  name: z.string().min(1),
  pattern: z.string().min(1),
  pattern_kind: z.enum(['path_prefix', 'regex']).default('path_prefix'),
  // Vacío = hereda la cadencia del sitio. Es la semántica de DIN.1 y por eso no lleva default:
  // poner uno aquí convertiría «no lo he puesto» en «lo quiero así».
  //
  // El `preprocess` es imprescindible: un `<input type="number">` vacío entrega `''`, y
  // `z.coerce.number()` lo convierte en **0**, que no pasa el `min(1)` — el formulario se
  // quedaba sin guardar y sin decir por qué, porque el campo es opcional y nadie miraba su error.
  crawl_interval_hours: z.preprocess(
    (valor) => (valor === '' || valor === null ? undefined : valor),
    z.coerce.number().int().min(1).max(8760).optional(),
  ),
  mode: z.enum(['manual', 'automatic']).default('manual'),
  owner: z.string().optional(),
})

type SeccionFormInput = z.input<typeof seccionSchema>
type SeccionFormValues = z.output<typeof seccionSchema>

export function SectionsPanel({ siteId }: { siteId: string }) {
  const { t } = useTranslation('curation')
  const { t: tc } = useTranslation('common')
  const qc = useQueryClient()
  const [formOpen, setFormOpen] = useState(false)
  const [prueba, setPrueba] = useState<PatternTestView | null>(null)
  const [errorAlBorrar, setErrorAlBorrar] = useState<string | null>(null)

  const claveDeLista = getListSiteSectionsQueryKey(siteId)
  const { data: secciones = [], isLoading } = useListSiteSections(siteId)
  const invalidar = () => qc.invalidateQueries({ queryKey: claveDeLista })

  const crear = useCreateSiteSection({
    mutation: {
      onSuccess: () => {
        invalidar()
        setFormOpen(false)
        setPrueba(null)
        reset()
      },
    },
  })
  const editar = usePatchSiteSection({ mutation: { onSuccess: invalidar } })
  const probar = useTestSectionPattern()
  const borrar = useDeleteSiteSection({
    mutation: {
      onSuccess: () => {
        setErrorAlBorrar(null)
        invalidar()
      },
      // Una sección con selecciones colgando responde 409 y hay que decir por qué: el servidor
      // manda el motivo y la alternativa («desactívala»), así que se muestra tal cual.
      onError: (fallo: unknown) =>
        setErrorAlBorrar(fallo instanceof Error ? fallo.message : String(fallo)),
    },
  })

  const {
    register,
    handleSubmit,
    reset,
    control,
    getValues,
    formState: { errors },
  } = useForm<SeccionFormInput, unknown, SeccionFormValues>({
    resolver: zodResolver(seccionSchema),
    defaultValues: { pattern_kind: 'path_prefix', mode: 'manual' },
  })
  // `useWatch` y `getValues`, no `watch`: con `watch` el compilador de React salta el componente.
  const patron = useWatch({ control, name: 'pattern' })

  /**
   * Probar el patrón **antes** de guardar: cuántas páginas ya rastreadas casarían y una muestra.
   * Es lo que evita el regex que compila y no casa nada, que si no se descubre cuando la pasada
   * siguiente no ingiere nada.
   */
  const probarPatron = async () => {
    const informe = await probar.mutateAsync({
      siteId,
      data: { pattern: getValues('pattern'), pattern_kind: getValues('pattern_kind') ?? 'path_prefix' },
    })
    setPrueba(informe)
  }

  const onSubmit = (data: SeccionFormValues) =>
    crear.mutate({
      siteId,
      data: {
        name: data.name,
        pattern: data.pattern,
        pattern_kind: data.pattern_kind,
        crawl_interval_hours: data.crawl_interval_hours,
        mode: data.mode,
        owner: data.owner || undefined,
      },
    })

  return (
    <div className="space-y-3" data-testid={`secciones-${siteId}`}>
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">{t('sections_title')}</h3>
        <button
          type="button"
          className="text-xs px-2 py-1 rounded border hover:bg-accent"
          data-testid="btn-nueva-seccion"
          onClick={() => setFormOpen((abierto) => !abierto)}
        >
          {t('new_section')}
        </button>
      </div>
      <p className="text-xs text-muted-foreground">{t('sections_help')}</p>

      {errorAlBorrar && (
        <p className="text-xs text-destructive" data-testid="error-borrar-seccion">
          {errorAlBorrar}
        </p>
      )}

      {isLoading ? (
        <p className="text-xs text-muted-foreground">{tc('loading')}</p>
      ) : secciones.length === 0 ? (
        <p className="text-xs text-muted-foreground" data-testid="sin-secciones">
          {t('no_sections')}
        </p>
      ) : (
        <table className="w-full text-xs border-collapse" aria-label={t('sections_title')}>
          <thead>
            <tr className="border-b text-left text-muted-foreground">
              <th className="py-1 pr-3">{t('section_name')}</th>
              <th className="py-1 pr-3">{t('section_pattern')}</th>
              <th className="py-1 pr-3">{t('section_mode')}</th>
              <th className="py-1 pr-3">{t('section_cadence')}</th>
              <th className="py-1 pr-3">{t('section_owner')}</th>
              <th className="py-1 pr-3">{t('section_last_crawled')}</th>
              <th className="py-1" />
            </tr>
          </thead>
          <tbody>
            {(secciones as SectionView[]).map((seccion) => (
              <tr
                key={seccion.id}
                className={`border-b ${seccion.is_active ? '' : 'opacity-60'}`}
                data-testid={`seccion-${seccion.id}`}
              >
                <td className="py-1 pr-3 font-medium">{seccion.name}</td>
                <td className="py-1 pr-3 font-mono">{seccion.pattern}</td>
                <td className="py-1 pr-3">
                  <select
                    data-testid={`modo-${seccion.id}`}
                    aria-label={t('section_mode')}
                    value={seccion.mode}
                    onChange={(e) =>
                      editar.mutate({
                        siteId,
                        sectionId: seccion.id,
                        data: { mode: e.target.value as 'manual' | 'automatic' },
                      })
                    }
                    className="border rounded px-1 py-0.5"
                  >
                    <option value="manual">{t('section_mode_manual')}</option>
                    <option value="automatic">{t('section_mode_automatic')}</option>
                  </select>
                </td>
                {/* La cadencia se muestra con su procedencia: sin decir que es heredada, cambiar
                    la del sitio parecería no hacer nada en las secciones que la heredan. */}
                <td
                  className="py-1 pr-3"
                  data-testid={`cadencia-${seccion.id}`}
                  data-horas={seccion.crawl_interval_hours_effective}
                  data-heredada={seccion.crawl_interval_inherited}
                >
                  {t('section_cadence_hours', {
                    horas: seccion.crawl_interval_hours_effective,
                  })}{' '}
                  <span className="text-muted-foreground">
                    {seccion.crawl_interval_inherited
                      ? t('section_cadence_inherited')
                      : t('section_cadence_own')}
                  </span>
                </td>
                <td className="py-1 pr-3">{seccion.owner || '—'}</td>
                <td className="py-1 pr-3">
                  {seccion.last_crawled_at
                    ? new Date(seccion.last_crawled_at).toLocaleString()
                    : t('site_never_crawled')}
                </td>
                <td className="py-1 space-x-2">
                  <button
                    type="button"
                    className="px-2 py-0.5 rounded border hover:bg-accent"
                    onClick={() =>
                      editar.mutate({
                        siteId,
                        sectionId: seccion.id,
                        data: { is_active: !seccion.is_active },
                      })
                    }
                  >
                    {seccion.is_active ? t('section_deactivate') : t('section_activate')}
                  </button>
                  <button
                    type="button"
                    className="px-2 py-0.5 rounded border text-destructive hover:bg-destructive/10"
                    onClick={() => borrar.mutate({ siteId, sectionId: seccion.id })}
                  >
                    {tc('delete')}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {formOpen && (
        <form
          onSubmit={handleSubmit(onSubmit)}
          className="border rounded p-3 space-y-2"
          noValidate
          data-testid="form-seccion"
        >
          <div>
            <label className="text-xs font-medium">{t('section_name')}</label>
            <input
              {...register('name')}
              data-testid="campo-seccion-nombre"
              className="w-full border rounded px-2 py-1 text-xs mt-0.5"
            />
            {errors.name && <p className="text-xs text-destructive">{t('section_field_required')}</p>}
          </div>
          <div className="flex gap-2">
            <div className="flex-1">
              <label className="text-xs font-medium">{t('section_pattern')}</label>
              <input
                {...register('pattern')}
                data-testid="campo-seccion-patron"
                className="w-full border rounded px-2 py-1 text-xs mt-0.5 font-mono"
              />
              {errors.pattern && <p className="text-xs text-destructive">{t('section_field_required')}</p>}
            </div>
            <div>
              <label className="text-xs font-medium">{t('section_pattern_kind')}</label>
              <select
                {...register('pattern_kind')}
                data-testid="campo-seccion-clase"
                className="border rounded px-2 py-1 text-xs mt-0.5"
              >
                <option value="path_prefix">{t('section_kind_path_prefix')}</option>
                <option value="regex">{t('section_kind_regex')}</option>
              </select>
            </div>
          </div>
          <div className="flex gap-2">
            <div className="flex-1">
              <label className="text-xs font-medium">{t('section_cadence_own_label')}</label>
              <input
                {...register('crawl_interval_hours')}
                type="number"
                data-testid="campo-seccion-cadencia"
                className="w-full border rounded px-2 py-1 text-xs mt-0.5"
                placeholder={t('section_cadence_placeholder')}
              />
            </div>
            <div className="flex-1">
              <label className="text-xs font-medium">{t('section_owner')}</label>
              <input
                {...register('owner')}
                className="w-full border rounded px-2 py-1 text-xs mt-0.5"
              />
            </div>
          </div>

          {/* La prueba del patrón va ANTES de dejar guardar: un patrón que no casa nada se
              descubriría si no cuando la pasada siguiente no ingiere nada. */}
          <div className="space-y-1">
            <button
              type="button"
              data-testid="btn-probar-patron"
              disabled={!patron || probar.isPending}
              onClick={probarPatron}
              className="text-xs px-2 py-1 rounded border disabled:opacity-50"
            >
              {probar.isPending ? t('pattern_testing') : t('pattern_test')}
            </button>
            {prueba && (
              <div
                data-testid="resultado-patron"
                data-casan={prueba.matched}
                data-total={prueba.total}
                className="text-xs space-y-1"
              >
                <p>
                  {t('pattern_matched', { casan: prueba.matched, total: prueba.total })}
                </p>
                {prueba.matched === 0 ? (
                  <p className="text-destructive" data-testid="patron-no-casa-nada">
                    {t('pattern_matches_nothing')}
                  </p>
                ) : (
                  <ul className="font-mono text-muted-foreground">
                    {(prueba.sample ?? []).map((url) => (
                      <li key={url}>{url}</li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </div>

          <div className="flex justify-end gap-2">
            <button
              type="button"
              className="text-xs px-2 py-1 rounded border"
              onClick={() => setFormOpen(false)}
            >
              {tc('cancel')}
            </button>
            <button
              type="submit"
              data-testid="btn-guardar-seccion"
              className="text-xs px-3 py-1 rounded bg-primary text-primary-foreground"
            >
              {tc('save')}
            </button>
          </div>
        </form>
      )}

      {/* DIN.6 — el diario va aquí, junto a las secciones, porque es donde se mira lo que la
          automatización hizo con ellas: la cadencia y el modo de arriba explican qué debería
          pasar, y esto dice qué pasó. */}
      <div className="border-t pt-3">
        <RunsPanel siteId={siteId} />
      </div>
    </div>
  )
}
