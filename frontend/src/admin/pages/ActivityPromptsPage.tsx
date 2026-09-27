import { useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import {
  useListActivityPrompts,
  useUpdateActivityPrompt,
  useResetActivityPrompt,
  getListActivityPromptsQueryKey,
} from '@/shared/api/generated/hub-activity-prompts/hub-activity-prompts'
import {
  useListPromptsCatalog,
  getListPromptsCatalogQueryKey,
} from '@/shared/api/generated/hub-prompts-catalog/hub-prompts-catalog'
import { useUpdatePromptTemplateApiV1HubPromptTemplatesTemplateIdPatch } from '@/shared/api/generated/hub-prompt-templates/hub-prompt-templates'
import { useUpdateChatbotApiV1HubChatbotsChatbotIdPatch } from '@/shared/api/generated/hub-chatbots/hub-chatbots'
import type { ActivityPromptOut, PromptDelCatalogo } from '@/shared/api/generated/model'

/**
 * Biblioteca de prompts de las **actividades de plataforma** — PRO.2.1.
 *
 * La biblioteca que ya existía (`/hub/prompts`) sólo veía prompts de chatbot,
 * porque su tabla cuelga de uno. Los de las actividades del módulo de Informes —escribir un
 * script, auditarlo— vivían en Python: no se podían afinar sin desplegar ni se podía elegir
 * con qué nivel de modelo corre cada una.
 *
 * Dos cosas que esta pantalla hace a propósito, copiadas del editor del legacy:
 *
 * - El selector de nivel tiene **cuatro** opciones, y la primera **dice cuál es el defecto**
 *   («Por defecto: nivel 2»). Un hueco vacío no se puede interpretar.
 * - El texto por defecto se muestra como marcador, **no se copia** a la caja. Copiarlo
 *   congelaría el prompt: a partir de ahí, mejorarlo en el código no llegaría aquí.
 *
 * **REV.13 — y además las plantillas de los asistentes.** Quien revisó la plataforma preguntó
 * por qué hay prompts del sistema en Chatbots y prompts de actividad aquí. Son dos modelos
 * distintos —una plantilla cuelga de un chatbot y va por idioma; una actividad es única
 * global—, así que unificar las tablas sería meter dos cosas en una. Lo que faltaba era
 * **verlas juntas**: el catálogo (`/hub/prompts-catalog`) las agrega en sólo lectura y cada
 * edición sigue yendo a su router, que es donde vive su regla.
 */
const TIER_STYLES: Record<number, string> = {
  1: 'bg-green-100 text-green-800',
  2: 'bg-yellow-100 text-yellow-800',
  3: 'bg-red-100 text-red-800',
}

function VariablesDetectadas({ texto }: { texto: string }) {
  const { t } = useTranslation('admin')
  const encontradas = Array.from(new Set(texto.match(/\{\w+\}/g) ?? []))
  return (
    <p className="text-xs text-muted-foreground" data-testid="detected-vars">
      {t('hub.activity_prompts.detected_vars')}: {encontradas.length ? encontradas.join(', ') : '—'}
    </p>
  )
}

function ActividadCard({ actividad }: { actividad: ActivityPromptOut }) {
  const { t } = useTranslation('admin')
  const qc = useQueryClient()
  const guardar = useUpdateActivityPrompt()
  const restablecer = useResetActivityPrompt()

  const [tier, setTier] = useState<string>(
    actividad.override_tier != null ? String(actividad.override_tier) : '',
  )
  const [texto, setTexto] = useState<string>(actividad.template_text ?? '')

  function invalidar() {
    qc.invalidateQueries({ queryKey: getListActivityPromptsQueryKey() })
  }

  return (
    <div className="border rounded p-4 space-y-3 bg-card" data-testid={`activity-${actividad.activity}`}>
      <div className="flex items-center gap-2">
        <span className="font-medium text-sm">{actividad.activity}</span>
        <span className="text-xs text-muted-foreground">{actividad.purpose}</span>
        <span
          data-testid={`effective-tier-${actividad.activity}`}
          className={`ml-auto text-xs px-2 py-0.5 rounded-full font-medium ${
            TIER_STYLES[actividad.effective_tier] ?? 'bg-gray-100 text-gray-700'
          }`}
        >
          {t('hub.activity_prompts.tier')} {actividad.effective_tier}
          {' · '}
          {actividad.tier_source === 'override'
            ? t('hub.activity_prompts.source_override')
            : t('hub.activity_prompts.source_code')}
        </span>
      </div>

      <div className="space-y-1">
        <label className="text-xs text-muted-foreground" htmlFor={`tier-${actividad.activity}`}>
          {t('hub.activity_prompts.tier_label')}
        </label>
        <select
          id={`tier-${actividad.activity}`}
          data-testid={`tier-select-${actividad.activity}`}
          value={tier}
          onChange={e => setTier(e.target.value)}
          className="w-full text-sm border rounded px-2 py-1 bg-background"
        >
          <option value="">
            {t('hub.activity_prompts.tier_default', { tier: actividad.default_tier })}
          </option>
          <option value="1">{t('hub.activity_prompts.tier')} 1</option>
          <option value="2">{t('hub.activity_prompts.tier')} 2</option>
          <option value="3">{t('hub.activity_prompts.tier')} 3</option>
        </select>
      </div>

      <div className="space-y-1">
        <label className="text-xs text-muted-foreground" htmlFor={`text-${actividad.activity}`}>
          {t('hub.activity_prompts.text_label')}
        </label>
        <textarea
          id={`text-${actividad.activity}`}
          data-testid={`text-${actividad.activity}`}
          value={texto}
          onChange={e => setTexto(e.target.value)}
          rows={8}
          placeholder={actividad.default_template}
          className="w-full text-xs font-mono border rounded p-2"
        />
        <p className="text-xs text-muted-foreground">
          {t('hub.activity_prompts.empty_means_code')}
        </p>
        <VariablesDetectadas texto={texto || actividad.default_template} />
        <p className="text-xs text-muted-foreground">
          {t('hub.activity_prompts.available_vars')}:{' '}
          {actividad.variables.length ? actividad.variables.join(', ') : '—'}
        </p>
      </div>

      {guardar.isError && (
        <p className="text-xs text-red-700" data-testid={`error-${actividad.activity}`}>
          {t('hub.activity_prompts.save_failed')}
        </p>
      )}

      <div className="flex gap-2">
        <button
          type="button"
          data-testid={`save-${actividad.activity}`}
          disabled={guardar.isPending}
          onClick={() =>
            guardar.mutate(
              {
                activity: actividad.activity,
                data: {
                  override_tier: tier ? Number(tier) : null,
                  template_text: texto.trim() ? texto : null,
                },
              },
              { onSuccess: invalidar },
            )
          }
          className="px-3 py-1 text-sm bg-primary text-primary-foreground rounded disabled:opacity-50"
        >
          {t('hub.activity_prompts.save')}
        </button>
        <button
          type="button"
          data-testid={`reset-${actividad.activity}`}
          onClick={() =>
            restablecer.mutate(
              { activity: actividad.activity },
              {
                onSuccess: () => {
                  setTier('')
                  setTexto('')
                  invalidar()
                },
              },
            )
          }
          className="px-3 py-1 text-sm border rounded"
        >
          {t('hub.activity_prompts.reset')}
        </button>
      </div>
    </div>
  )
}
/**
 * Un prompt de asistente —su prompt base o una de sus plantillas—, editable sin salir de aquí
 * (REV.13).
 *
 * El catálogo es de **sólo lectura**, así que guardar sale hacia el router de cada uno: el
 * prompt base es una columna de `hub_chatbots` y se guarda con un PATCH del chatbot; una
 * plantilla vive en su tabla y se guarda con su `template_id`. Es lo que separa una pantalla
 * unificada de un listado bonito que no deja tocar la mitad de lo que enseña.
 */
function PlantillaCard({ plantilla }: { plantilla: PromptDelCatalogo }) {
  const { t } = useTranslation('admin')
  const qc = useQueryClient()
  const guardarPlantilla = useUpdatePromptTemplateApiV1HubPromptTemplatesTemplateIdPatch()
  const guardarBase = useUpdateChatbotApiV1HubChatbotsChatbotIdPatch()

  const esBase = plantilla.ambito === 'chatbot_base'
  const guardar = esBase ? guardarBase : guardarPlantilla

  const [texto, setTexto] = useState<string>(plantilla.template_text ?? '')
  const id = esBase ? `base-${plantilla.chatbot_id}` : (plantilla.template_id as string)

  return (
    <div className="border rounded p-4 space-y-3 bg-card" data-testid={`plantilla-${id}`}>
      <div className="flex items-center gap-2">
        <span className="font-medium text-sm">
          {esBase ? t('hub.activity_prompts.prompt_base') : plantilla.clave}
        </span>
        {plantilla.language && (
          <span className="text-xs text-muted-foreground">
            {t('hub.activity_prompts.plantilla_idioma')}: {plantilla.language}
          </span>
        )}
        {plantilla.version != null && (
          <span className="ml-auto text-xs text-muted-foreground">
            {t('hub.activity_prompts.plantilla_version')} {plantilla.version}
          </span>
        )}
      </div>

      <textarea
        data-testid={`texto-${id}`}
        aria-label={`${plantilla.chatbot_nombre} · ${plantilla.clave}`}
        value={texto}
        onChange={e => setTexto(e.target.value)}
        rows={8}
        className="w-full text-xs font-mono border rounded p-2"
      />

      {guardar.isError && (
        <p className="text-xs text-red-700" data-testid={`error-plantilla-${id}`}>
          {t('hub.activity_prompts.plantilla_guardar_fallo')}
        </p>
      )}

      <button
        type="button"
        data-testid={`guardar-${id}`}
        disabled={guardar.isPending}
        onClick={() => {
          const invalidar = {
            onSuccess: () =>
              qc.invalidateQueries({ queryKey: getListPromptsCatalogQueryKey() }),
          }
          if (esBase) {
            guardarBase.mutate(
              { chatbotId: plantilla.chatbot_id as string, data: { system_prompt: texto } },
              invalidar,
            )
          } else {
            guardarPlantilla.mutate(
              { templateId: plantilla.template_id as string, data: { template_text: texto } },
              invalidar,
            )
          }
        }}
        className="px-3 py-1 text-sm bg-primary text-primary-foreground rounded disabled:opacity-50"
      >
        {t('hub.activity_prompts.save')}
      </button>
    </div>
  )
}


/**
 * Sin tildes y en minúsculas, para que «grafico» encuentre «gráfico» (REV.7).
 *
 * Quien busca teclea rápido y sin acentos; una búsqueda que exige escribir «configuración»
 * con tilde no se usa dos veces.
 */
function normalizar(texto: string): string {
  // `NFD` separa la letra de su tilde y `\p{Diacritic}` borra la tilde suelta. Se usa la
  // propiedad Unicode y no un rango de caracteres literales: pegados en el fuente son
  // invisibles, y un editor que «arregle» la codificación del fichero rompería la búsqueda
  // sin dejar rastro de por qué.
  return texto
    .toLowerCase()
    .normalize('NFD')
    .replace(/\p{Diacritic}/gu, '')
}

export function ActivityPromptsPage() {
  const { t } = useTranslation('admin')
  const { data: actividades, isPending } = useListActivityPrompts()
  // REV.13 — el mismo catálogo del que sale la vista de conjunto. Las actividades siguen
  // viniendo de su endpoint porque llevan lo que el catálogo no puede llevar: el texto por
  // defecto, las variables y de dónde sale el nivel efectivo.
  const { data: catalogo } = useListPromptsCatalog()

  const [ambito, setAmbito] = useState('')
  const [modulo, setModulo] = useState('')
  const [busqueda, setBusqueda] = useState('')

  // `actividades ?? []` a secas creaba un array NUEVO en cada render mientras no hubiera datos,
  // asi que las dependencias de los dos `useMemo` de abajo cambiaban siempre y la memoizacion no
  // memoizaba nada: se recalculaban los modulos y el filtrado en cada pulsacion de tecla del
  // buscador. Con el `useMemo` la referencia es estable.
  const todas = useMemo(() => actividades ?? [], [actividades])

  /**
   * Los módulos que de verdad hay, sacados de los datos y **no de una lista escrita aquí**:
   * el catálogo de actividades es del servidor y crece cuando se cablea un consumidor nuevo.
   */
  const modulos = useMemo(
    () => [...new Set(todas.map(a => a.modulo))].sort(),
    [todas],
  )

  const visibles = useMemo(() => {
    const aguja = normalizar(busqueda.trim())
    if (ambito === 'chatbot') return []
    return todas.filter(a => {
      if (modulo && a.modulo !== modulo) return false
      if (!aguja) return true
      // Por la clave **y** por el «para qué sirve»: quien busca no recuerda
      // `configuracion_de_grafico`, recuerda que había algo de gráficos.
      return normalizar(`${a.activity} ${a.purpose}`).includes(aguja)
    })
  }, [todas, ambito, modulo, busqueda])

  /**
   * Las plantillas de asistente, agrupadas por el suyo. El filtro de módulo **no se les
   * aplica**: no tienen módulo, y hacer que un filtro que no les corresponde las esconda
   * sería la clase de sorpresa que hace desconfiar de una pantalla.
   */
  const porChatbot = useMemo(() => {
    if (ambito === 'plataforma') return []
    const aguja = normalizar(busqueda.trim())
    const grupos = new Map<string, { nombre: string; plantillas: PromptDelCatalogo[] }>()
    for (const fila of catalogo ?? []) {
      if (fila.ambito !== 'chatbot' && fila.ambito !== 'chatbot_base') continue
      if (!fila.chatbot_id) continue
      if (aguja && !normalizar(`${fila.clave} ${fila.chatbot_nombre ?? ''}`).includes(aguja)) {
        continue
      }
      const grupo = grupos.get(fila.chatbot_id) ?? {
        nombre: fila.chatbot_nombre ?? fila.chatbot_id,
        plantillas: [],
      }
      grupo.plantillas.push(fila)
      grupos.set(fila.chatbot_id, grupo)
    }
    return [...grupos.entries()].sort(([, a], [, b]) => a.nombre.localeCompare(b.nombre))
  }, [catalogo, ambito, busqueda])

  /**
   * Con un solo prompt un buscador es ruido; el catálogo empieza pequeño. Se cuentan los dos
   * ámbitos: con una actividad y cinco plantillas los filtros hacen falta igual (REV.13).
   */
  const cuantosHay =
    todas.length + (catalogo ?? []).filter(f => f.ambito !== 'plataforma').length
  const merecenFiltros = cuantosHay > 1

  const porModulo = useMemo(() => {
    const grupos = new Map<string, typeof visibles>()
    for (const actividad of visibles) {
      grupos.set(actividad.modulo, [...(grupos.get(actividad.modulo) ?? []), actividad])
    }
    return [...grupos.entries()].sort(([a], [b]) => a.localeCompare(b))
  }, [visibles])

  return (
    <div className="space-y-4" data-testid="activity-prompts-page">
      <div>
        <h1 className="text-lg font-semibold">{t('hub.activity_prompts.title')}</h1>
        <p className="text-sm text-muted-foreground">{t('hub.activity_prompts.intro')}</p>
        {/* REV.10 — el ámbito, dicho. Esta pantalla no lleva selector de organización porque
            no le corresponde: `HubActivityPrompt.activity` es único global, sin
            `organizacion_id`. Callarlo deja la duda de si el selector falta o es que no
            aplica — que es justo la pregunta que hizo quien la revisó. */}
        <p className="text-xs text-muted-foreground">{t('hub.activity_prompts.ambito')}</p>
      </div>

      {isPending && <p className="text-sm text-muted-foreground">…</p>}

      {merecenFiltros && (
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex flex-col gap-1">
            <label htmlFor="ap_busqueda" className="text-xs font-medium">
              {t('hub.activity_prompts.buscar')}
            </label>
            <input
              id="ap_busqueda"
              type="search"
              value={busqueda}
              onChange={e => setBusqueda(e.target.value)}
              placeholder={t('hub.activity_prompts.buscar_pista')}
              className="w-64 rounded-md border px-2 py-1.5 text-sm bg-background"
            />
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor="ap_ambito" className="text-xs font-medium">
              {t('hub.activity_prompts.ambito_label')}
            </label>
            <select
              id="ap_ambito"
              value={ambito}
              onChange={e => setAmbito(e.target.value)}
              className="rounded-md border px-2 py-1.5 text-sm bg-background"
            >
              <option value="">{t('hub.activity_prompts.ambito_todos')}</option>
              <option value="plataforma">{t('hub.activity_prompts.ambito_plataforma')}</option>
              <option value="chatbot">{t('hub.activity_prompts.ambito_chatbot')}</option>
            </select>
          </div>
          {/* El módulo sólo existe en las actividades. Dejar el filtro puesto mientras se
              miran plantillas invita a usarlo y a no entender por qué no hace nada. */}
          {ambito !== 'chatbot' && (
          <div className="flex flex-col gap-1">
            <label htmlFor="ap_modulo" className="text-xs font-medium">
              {t('hub.activity_prompts.modulo')}
            </label>
            <select
              id="ap_modulo"
              value={modulo}
              onChange={e => setModulo(e.target.value)}
              className="rounded-md border px-2 py-1.5 text-sm bg-background"
            >
              <option value="">{t('hub.activity_prompts.todos_los_modulos')}</option>
              {modulos.map(codigo => (
                <option key={codigo} value={codigo}>
                  {t(`hub.activity_prompts.modulos.${codigo}` as Parameters<typeof t>[0], {
                    defaultValue: codigo,
                  })}
                </option>
              ))}
            </select>
          </div>
          )}
        </div>
      )}

      {/* Una pantalla en blanco tras escribir se lee como «se ha roto». */}
      {!isPending && visibles.length === 0 && porChatbot.length === 0 && (
        <p data-testid="sin-resultados" className="text-sm text-muted-foreground">
          {t('hub.activity_prompts.sin_resultados')}
        </p>
      )}

      {porModulo.map(([codigo, delGrupo]) => (
        <section key={codigo} data-testid={`grupo-${codigo}`} className="space-y-3">
          {/* El encabezado se pinta siempre que haya grupo, también con uno solo: dice de
              quién es lo que hay debajo, que es la pregunta que trae aquí a la gente. */}
          <h2 className="text-sm font-semibold text-muted-foreground">
            {t(`hub.activity_prompts.modulos.${codigo}` as Parameters<typeof t>[0], {
              defaultValue: codigo,
            })}
          </h2>
          {delGrupo.map(actividad => (
            <ActividadCard key={actividad.activity} actividad={actividad} />
          ))}
        </section>
      ))}

      {porChatbot.length > 0 && (
        <p className="text-xs text-muted-foreground">
          {t('hub.activity_prompts.plantillas_intro')}
        </p>
      )}

      {porChatbot.map(([id, grupo]) => (
        <section key={id} data-testid={`grupo-chatbot-${id}`} className="space-y-3">
          <h2 className="text-sm font-semibold text-muted-foreground">{grupo.nombre}</h2>
          {grupo.plantillas.map(plantilla => (
            <PlantillaCard
              key={plantilla.template_id ?? `base-${plantilla.chatbot_id}`}
              plantilla={plantilla}
            />
          ))}
        </section>
      ))}
    </div>
  )
}
