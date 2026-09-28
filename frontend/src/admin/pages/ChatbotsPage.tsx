import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import type { ChatbotRead, CorpusStatsOut } from '@/shared/api/generated/model'
import {
  useCreateChatbotApiV1HubChatbotsPost,
  useUpdateChatbotApiV1HubChatbotsChatbotIdPatch,
  useDeleteChatbotApiV1HubChatbotsChatbotIdDelete,
  useGetCorpusStatsApiV1HubChatbotsChatbotIdCorpusStatsGet,
  useListChildrenApiV1HubChatbotsChatbotIdChildrenGet,
  useRegenerateChunksApiV1HubChatbotsChatbotIdRegenerateChunksPost,
  useAssignChildApiV1HubChatbotsChatbotIdChildrenPost,
  getListChatbotsApiV1HubChatbotsGetQueryKey,
  getListChildrenApiV1HubChatbotsChatbotIdChildrenGetQueryKey,
  getGetCorpusStatsApiV1HubChatbotsChatbotIdCorpusStatsGetQueryKey,
  useOpcionesDeGrafoApiV1HubChatbotsOpcionesDeGrafoGet,
} from '@/shared/api/generated/hub-chatbots/hub-chatbots'
import { useListLlmConfigsApiV1HubLlmConfigsGet } from '@/shared/api/generated/hub-llm-configs/hub-llm-configs'
import { useListOrganizacionesApiV1HubOrganizacionesGet } from '@/shared/api/generated/hub-organizaciones/hub-organizaciones'
import { chatbotCreateSchema, type FormValues } from '../chatbots/schemas/chatbotSchemas'
import { mapApiErrorsToFormErrors } from '@/shared/utils/formErrors'
import { SelectorDeModoDeLengua } from '../components/SelectorDeModoDeLengua'
import { useChatbotsDeLaOrganizacion } from '@/shared/organizacion/useChatbotsDeLaOrganizacion'

// PLG.3 — la lista de modos **ya no vive aquí**: llega de `/hub/chatbots/opciones-de-grafo`,
// porque desde PLG.1 depende de qué paquetes haya instalados en el servidor.
//
// Lo que sí se queda son las **etiquetas de los modos del núcleo**, y no es una recaída: son
// traducciones de tres nombres que este repositorio sí conoce, con su texto de ayuda escrito por
// alguien que entiende la diferencia entre RAG y contexto largo. Un modo aportado por un paquete
// no tiene traducción —ni la vamos a inventar, que sería prometer una calidad que no podemos
// sostener— y se muestra con su nombre y la descripción que venga del servidor.
//
// O sea: el catálogo es del servidor; el diccionario de lo conocido, del cliente.
// Las claves van LITERALES y no interpoladas (`hub.chatbot_eje_${eje}`): el guardarrail de
// i18n de CAL.4 busca consumidores en el codigo, y una clave construida en tiempo de
// ejecucion le parece huerfana. Un eje sin etiqueta cae a su propio nombre.
const ETIQUETA_DE_EJE: Record<string, string> = {
  retrieval: 'hub.chatbot_eje_retrieval',
  merge: 'hub.chatbot_eje_merge',
  template: 'hub.chatbot_eje_template',
  language: 'hub.chatbot_eje_language',
}

const ETIQUETAS_DE_MODO: Record<string, { labelKey: string; hintKey: string }> = {
  RAG:               { labelKey: 'hub.chatbot_retrieval_rag',          hintKey: 'hub.chatbot_retrieval_hint_rag' },
  MD_LONG_CONTEXT:   { labelKey: 'hub.chatbot_retrieval_long_context', hintKey: 'hub.chatbot_retrieval_hint_long_context' },
  MD_AGENT_SELECTOR: { labelKey: 'hub.chatbot_retrieval_agentic',      hintKey: 'hub.chatbot_retrieval_hint_agentic' },
}

// SEC.4.1: solo el color. El estado y su motivo vienen del contrato —los calcula el
// servidor—, y el texto sale de i18n; aquí no se decide nada sobre disponibilidad.
const AVAILABILITY_STYLES: Record<string, string> = {
  available: 'bg-green-100 text-green-700 border-green-200',
  expired: 'bg-red-100 text-red-700 border-red-200',
  not_yet_open: 'bg-amber-100 text-amber-700 border-amber-200',
  budget_exhausted: 'bg-orange-100 text-orange-700 border-orange-200',
}

/** ISO del contrato → valor de un `<input type="datetime-local">` (sin zona ni segundos). */
function paraCampoDeFecha(iso: string | null | undefined): string {
  return iso ? iso.slice(0, 16) : ''
}

/** Valor del campo → lo que espera el contrato: vacío es `null`, no cadena vacía. */
function paraElContrato(valor: string): string | null {
  return valor ? new Date(valor).toISOString() : null
}

// FIX.1: aquí vivían `DEV_ORG_ID` y `DEV_LLM_ID`. Eran dos identificadores de la BD de
// desarrollo escritos a mano en React —lo que CLAUDE.md prohíbe—, y el del modelo tenía
// consecuencia funcional: no había forma de cambiar de modelo, y guardar cualquier edición
// reasignaba el chatbot a esa configuración sin decirlo. Ahora salen del contrato.

type LlmConfigOption = {
  id: string
  provider: string
  model_name: string
  label?: string | null
  is_default?: boolean
}

type OrganizacionOption = { id: string; name: string }

type EstrategiaOpcion = { nombre: string; descripcion?: string | null; origen: string }
type OpcionesDeGrafo = {
  perfiles: { nombre: string; configurable: boolean; descripcion?: string | null }[]
  modos: { nombre: string; descripcion?: string | null }[]
  estrategias: Record<string, EstrategiaOpcion[]>
  ejes: string[]
}

function etiquetaModelo(config: LlmConfigOption): string {
  // El `model_name` exacto va SIEMPRE, aunque haya etiqueta. Es lo que distingue
  // `gemini-2.0-flash` de `gemini-2.5-flash`, y lo que deja ver de un vistazo que
  // `gemini-2.5-flash-preview-tts` es de texto a voz y no sirve para chatear.
  const etiqueta = config.label?.trim()
  const base = `${config.provider} · ${config.model_name}`
  const conEtiqueta = etiqueta ? `${etiqueta} — ${base}` : base
  return config.is_default ? `${conEtiqueta} (por defecto)` : conEtiqueta
}

/** Cadena vacia = heredar de la organizacion (null); si no, el numero.
 *
 * Los tres estados importan: `null` hereda, `0` es sin limite y un numero es el techo.
 * Mandar `0` donde el usuario dejo el campo vacio le pondria "sin limite" sin pedirlo.
 */
function aCuota(valor: string): number | null {
  const limpio = valor.trim()
  if (limpio === '') return null
  const numero = Number(limpio)
  return Number.isFinite(numero) && numero >= 0 ? Math.trunc(numero) : null
}

export function ChatbotsPage() {
  const { t } = useTranslation('admin')
  const { t: tc } = useTranslation('common')
  const qc = useQueryClient()
  const [editing, setEditing] = useState<ChatbotRead | null>(null)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<ChatbotRead | null>(null)
  const [deleteError, setDeleteError] = useState('')
  const [copied, setCopied] = useState(false)
  const [assignOpen, setAssignOpen] = useState(false)
  const [selectedChildId, setSelectedChildId] = useState('')

  const { data: chatbotsRaw, isLoading } = useChatbotsDeLaOrganizacion()
  const chatbots: ChatbotRead[] = (chatbotsRaw as unknown as ChatbotRead[] | undefined) ?? []

  // FIX.1: los dos catálogos que antes eran constantes escritas a mano.
  const { data: configsRaw } = useListLlmConfigsApiV1HubLlmConfigsGet()
  const llmConfigs = (configsRaw as unknown as LlmConfigOption[] | undefined) ?? []
  const { data: orgsRaw } = useListOrganizacionesApiV1HubOrganizacionesGet()
  const organizaciones = (orgsRaw as unknown as OrganizacionOption[] | undefined) ?? []

  // PLG.3 — el catalogo de lo que ESTA INSTALACION ofrece. Antes eran cuatro literales
  // escritos en este fichero; ahora la lista depende de los paquetes instalados y solo el
  // servidor la conoce.
  const { data: opcionesRaw } = useOpcionesDeGrafoApiV1HubChatbotsOpcionesDeGrafoGet()
  const opciones = opcionesRaw as unknown as OpcionesDeGrafo | undefined
  const modosDisponibles = opciones?.modos ?? []
  const perfilesDisponibles = opciones?.perfiles ?? []
  const ejes = opciones?.ejes ?? []

  const createMutation = useCreateChatbotApiV1HubChatbotsPost({
    mutation: {
      onSuccess: () => {
        qc.invalidateQueries({ queryKey: getListChatbotsApiV1HubChatbotsGetQueryKey() })
        closeDialog()
      },
      onError: (error) => {
        mapApiErrorsToFormErrors(error, setError)
      },
    },
  })

  const updateMutation = useUpdateChatbotApiV1HubChatbotsChatbotIdPatch({
    mutation: {
      onSuccess: () => {
        qc.invalidateQueries({ queryKey: getListChatbotsApiV1HubChatbotsGetQueryKey() })
        closeDialog()
      },
      onError: (error) => {
        mapApiErrorsToFormErrors(error, setError)
      },
    },
  })

  const toggleMutation = useUpdateChatbotApiV1HubChatbotsChatbotIdPatch({
    mutation: {
      onSuccess: () => qc.invalidateQueries({ queryKey: getListChatbotsApiV1HubChatbotsGetQueryKey() }),
    },
  })

  const deleteMutation = useDeleteChatbotApiV1HubChatbotsChatbotIdDelete({
    mutation: {
      onSuccess: () => {
        qc.invalidateQueries({ queryKey: getListChatbotsApiV1HubChatbotsGetQueryKey() })
        setDeleteTarget(null)
        setDeleteError('')
      },
      onError: (err: unknown) => setDeleteError(err instanceof Error ? err.message : 'Error al eliminar'),
    },
  })

  const { register, handleSubmit, reset, watch, setValue, setError, formState: { errors } } = useForm<FormValues>({
    resolver: zodResolver(chatbotCreateSchema),
    defaultValues: {
      name: '',
      kind: 'atomic',
      system_prompt: '',
      is_active: true,
      retrieval_mode: 'RAG',
      retrieval_top_k: 8,
      use_prompt_caching: false,
      cache_ttl: 3600,
      public_graph_profile: 'PUBLIC_KB_RICH',
      language_mode: 'prefer',
      quality_threshold: 0.6,
      min_retrieval_results: 2,
      min_retrieval_score: 0.0,
      reranker_enabled: false,
      answer_template: 'generic',
      llm_config_id: '',
      organizacion_id: '',
      valid_from: '',
      valid_until: '',
      total_token_budget: 0,
      user_daily_token_quota: '',
      chatbot_daily_token_quota: '',
      anon_ip_daily_token_quota: '',
      unavailable_message: '',
    },
  })
  const selectedKind = watch('kind')
  const claveHint = ETIQUETAS_DE_MODO[watch('retrieval_mode')]?.hintKey
  const retrievalHint = claveHint ? t(claveHint) : undefined

  const { data: childrenRaw, isLoading: isLoadingChildren } = useListChildrenApiV1HubChatbotsChatbotIdChildrenGet(
    editing?.id ?? '',
    { query: { enabled: dialogOpen && !!editing && selectedKind === 'router' } },
  )
  const children: ChatbotRead[] = (childrenRaw as unknown as ChatbotRead[] | undefined) ?? []

  const { data: corpusStatsRaw } = useGetCorpusStatsApiV1HubChatbotsChatbotIdCorpusStatsGet(
    editing?.id ?? '',
    { query: { enabled: dialogOpen && !!editing } },
  )
  const corpusStats = corpusStatsRaw as unknown as CorpusStatsOut | undefined

  const assignChildMutation = useAssignChildApiV1HubChatbotsChatbotIdChildrenPost({
    mutation: {
      onSuccess: () => {
        qc.invalidateQueries({ queryKey: getListChatbotsApiV1HubChatbotsGetQueryKey() })
        qc.invalidateQueries({ queryKey: getListChildrenApiV1HubChatbotsChatbotIdChildrenGetQueryKey(editing?.id ?? '') })
        setAssignOpen(false)
        setSelectedChildId('')
      },
    },
  })

  const regenerateChunksMutation = useRegenerateChunksApiV1HubChatbotsChatbotIdRegenerateChunksPost({
    mutation: {
      onSuccess: () => {
        qc.invalidateQueries({ queryKey: getGetCorpusStatsApiV1HubChatbotsChatbotIdCorpusStatsGetQueryKey(editing?.id ?? '') })
      },
    },
  })

  function openCreate() {
    setEditing(null)
    setAssignOpen(false)
    setSelectedChildId('')
    reset({
      name: '',
      kind: 'atomic',
      system_prompt: '',
      is_active: true,
      retrieval_mode: 'RAG',
      retrieval_top_k: 8,
      use_prompt_caching: false,
      cache_ttl: 3600,
      public_graph_profile: 'PUBLIC_KB_RICH',
      language_mode: 'prefer',
      quality_threshold: 0.6,
      min_retrieval_results: 2,
      min_retrieval_score: 0.0,
      reranker_enabled: false,
      answer_template: 'generic',
      // Al crear se propone la configuración marcada por defecto, que es una sugerencia
      // visible en el desplegable y no un identificador oculto en el código.
      llm_config_id: (llmConfigs.find((c) => c.is_default) ?? llmConfigs[0])?.id ?? '',
      organizacion_id: organizaciones[0]?.id ?? '',
      // SEC.4.1: se crea sin ventana y sin techo, igual que el default del modelo.
      valid_from: '',
      valid_until: '',
      total_token_budget: 0,
      user_daily_token_quota: '',
      chatbot_daily_token_quota: '',
      anon_ip_daily_token_quota: '',
      unavailable_message: '',
    })
    setDialogOpen(true)
  }

  function openEdit(c: ChatbotRead) {
    setEditing(c)
    setCopied(false)
    setAssignOpen(false)
    setSelectedChildId('')
    reset({
      name: c.name,
      kind: (c.kind as 'atomic' | 'router') ?? 'atomic',
      system_prompt: c.system_prompt,
      is_active: c.is_active,
      retrieval_mode: c.retrieval_mode ?? 'RAG',
      retrieval_top_k: c.retrieval_top_k ?? 8,
      use_prompt_caching: c.use_prompt_caching ?? false,
      cache_ttl: c.cache_ttl ?? 3600,
      public_graph_profile: c.public_graph_profile ?? 'PUBLIC_KB_RICH',
      estrategias: (c as { estrategias?: Record<string, string> | null }).estrategias ?? {},
      language_mode: c.language_mode ?? 'prefer',
      quality_threshold: c.quality_threshold ?? 0.6,
      min_retrieval_results: c.min_retrieval_results ?? 2,
      min_retrieval_score: c.min_retrieval_score ?? 0.0,
      reranker_enabled: c.reranker_enabled ?? false,
      answer_template: c.answer_template ?? 'generic',
      // La del chatbot, no la de por defecto: es lo que impide que guardar una edición
      // cualquiera lo mueva de modelo sin que nadie lo haya pedido.
      llm_config_id: c.llm_config_id,
      organizacion_id: c.organizacion_id,
      // SEC.4.1: el `<input type="datetime-local">` no entiende zona horaria, así que se
      // recorta la ISO a `YYYY-MM-DDTHH:mm`. Sin recortar, el campo aparece vacío y guardar
      // borraría silenciosamente la fecha que ya tenía puesta.
      valid_from: paraCampoDeFecha(c.valid_from),
      valid_until: paraCampoDeFecha(c.valid_until),
      total_token_budget: c.total_token_budget ?? 0,
      user_daily_token_quota: c.user_daily_token_quota?.toString() ?? '',
      chatbot_daily_token_quota: c.chatbot_daily_token_quota?.toString() ?? '',
      anon_ip_daily_token_quota: c.anon_ip_daily_token_quota?.toString() ?? '',
      unavailable_message: c.unavailable_message ?? '',
    })
    setDialogOpen(true)
  }

  function copyId() {
    void navigator.clipboard.writeText(editing!.id)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  function installSnippet(id: string): string {
    const base = import.meta.env.VITE_API_URL ?? 'https://tu-api.ejemplo.com'
    return [
      `<div id="govgenai-widget"`,
      `     data-chatbot-id="${id}"`,
      `     data-lang="es"`,
      `     data-api-url="${base}/api/v1">`,
      `</div>`,
      `<script src="${base}/widget.iife.js"></script>`,
    ].join('\n')
  }

  function closeDialog() {
    setDialogOpen(false)
    setEditing(null)
    setAssignOpen(false)
    setSelectedChildId('')
    reset()
  }

  function openDelete(c: ChatbotRead) {
    closeDialog()
    deleteMutation.reset()
    setDeleteError('')
    setDeleteTarget(c)
  }

  function onSubmit(values: FormValues) {
    if (
      values.kind === 'atomic' &&
      values.retrieval_mode === 'MD_LONG_CONTEXT' &&
      (corpusStats?.total_tokens ?? 0) > 128_000
    ) {
      return
    }

    if (editing) {
      updateMutation.mutate({
        chatbotId: editing.id,
        data: {
          name: values.name,
          kind: values.kind,
          system_prompt: values.system_prompt,
          is_active: values.is_active,
          retrieval_mode: values.retrieval_mode,
          retrieval_top_k: values.retrieval_top_k,
          use_prompt_caching: values.use_prompt_caching,
          cache_ttl: values.cache_ttl,
          public_graph_profile: values.public_graph_profile,
          estrategias: values.estrategias,
          language_mode: values.language_mode,
          quality_threshold: values.quality_threshold,
          min_retrieval_results: values.min_retrieval_results,
          min_retrieval_score: values.min_retrieval_score,
          reranker_enabled: values.reranker_enabled,
          answer_template: values.answer_template,
          // SEC.4.1: vacio viaja como null. El backend distingue «sin ventana» de «con
          // fecha», y '' no es ninguna de las dos cosas.
          valid_from: paraElContrato(values.valid_from),
          valid_until: paraElContrato(values.valid_until),
          total_token_budget: values.total_token_budget,
        user_daily_token_quota: aCuota(values.user_daily_token_quota),
        chatbot_daily_token_quota: aCuota(values.chatbot_daily_token_quota),
        anon_ip_daily_token_quota: aCuota(values.anon_ip_daily_token_quota),
          unavailable_message: values.unavailable_message,
          llm_config_id: values.llm_config_id,
        },
      })
    } else {
      createMutation.mutate({
        data: {
          name: values.name,
          kind: values.kind,
          system_prompt: values.system_prompt,
          is_active: values.is_active,
          retrieval_mode: values.retrieval_mode,
          retrieval_top_k: values.retrieval_top_k,
          use_prompt_caching: values.use_prompt_caching,
          cache_ttl: values.cache_ttl,
          organizacion_id: values.organizacion_id,
          llm_config_id: values.llm_config_id,
          public_graph_profile: values.public_graph_profile,
          estrategias: values.estrategias,
          language_mode: values.language_mode,
          quality_threshold: values.quality_threshold,
          min_retrieval_results: values.min_retrieval_results,
          min_retrieval_score: values.min_retrieval_score,
          reranker_enabled: values.reranker_enabled,
          answer_template: values.answer_template,
          // SEC.4.1: vacio viaja como null. El backend distingue «sin ventana» de «con
          // fecha», y '' no es ninguna de las dos cosas.
          valid_from: paraElContrato(values.valid_from),
          valid_until: paraElContrato(values.valid_until),
          total_token_budget: values.total_token_budget,
        user_daily_token_quota: aCuota(values.user_daily_token_quota),
        chatbot_daily_token_quota: aCuota(values.chatbot_daily_token_quota),
        anon_ip_daily_token_quota: aCuota(values.anon_ip_daily_token_quota),
          unavailable_message: values.unavailable_message,
        },
      })
    }
  }

  const isPending = createMutation.isPending || updateMutation.isPending
  const showLongContextHardError =
    selectedKind === 'atomic' &&
    watch('retrieval_mode') === 'MD_LONG_CONTEXT' &&
    (corpusStats?.total_tokens ?? 0) > 128_000

  const assignableChildren = chatbots.filter(
    (cb) =>
      cb.id !== editing?.id &&
      cb.kind === 'atomic' &&
      cb.organizacion_id === (editing?.organizacion_id ?? organizaciones[0]?.id) &&
      cb.parent_chatbot_id === null,
  )

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">{t('hub.chatbots')}</h1>
        <button
          type="button"
          onClick={openCreate}
          className="px-3 py-2 bg-primary text-primary-foreground text-sm rounded-md"
        >
          {t('hub.new_chatbot')}
        </button>
      </div>

      {isLoading && <p className="text-muted-foreground text-sm">{tc('loading')}</p>}

      {!isLoading && chatbots.length === 0 && (
        <p className="text-muted-foreground text-sm py-8 text-center">{t('hub.no_chatbots')}</p>
      )}

      {chatbots.length > 0 && (
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-left text-muted-foreground">
              <th className="pb-2 font-medium">{t('hub.chatbot_name')}</th>
              <th className="pb-2 font-medium">Retrieval</th>
              <th className="pb-2 font-medium">{t('hub.chatbot_active')}</th>
              <th className="pb-2 font-medium">{t('hub.availability')}</th>
              <th className="pb-2" />
            </tr>
          </thead>
          <tbody>
            {chatbots.map((c) => (
              <tr
                key={c.id}
                className="border-b last:border-0 hover:bg-accent/30 cursor-pointer"
                onClick={() => openEdit(c)}
              >
                <td className="py-3 pr-4">{c.name}</td>
                <td className="py-3 pr-4">
                  <span className="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground border">
                    {(() => {
                      const clave = ETIQUETAS_DE_MODO[c.retrieval_mode]?.labelKey
                      // Sin traducción —un modo de un paquete— se muestra su nombre tal cual.
                      return clave ? t(clave) : c.retrieval_mode
                    })()}
                  </span>
                </td>
                <td className="py-3 pr-4">
                  {/* El interruptor de actividad. La etiqueta nombra el ESTADO, que es lo
                      que esta columna dice que muestra —su encabezado es «Activo»— y lo que ya
                      hacía la mitad verde.

                      Decía `tc('edit')` cuando el chatbot estaba inactivo, o sea «Editar», y lo
                      que hacía era activarlo. Se encontró verificando LANG.2 en el navegador y de
                      la peor manera: buscando el botón de editar de la fila se pincha esto y se
                      activa un asistente. Y no es un caso raro, porque el editar de verdad está
                      en el clic sobre la fila y no en un botón, así que cualquiera que busque
                      «Editar» acaba aquí.

                      `aria-pressed` porque es un interruptor: sin él un lector de pantalla lee
                      «Inactivo» como una etiqueta y no dice que se pueda pulsar para cambiarlo.
                      No se usa `aria-label` con el verbo («Activar») a propósito: el nombre
                      accesible tiene que contener el texto visible (WCAG 2.5.3), y decir una cosa
                      a la vista y otra al lector es el mismo defecto que se está arreglando. */}
                  <button
                    type="button"
                    aria-pressed={c.is_active}
                    onClick={(e) => {
                      e.stopPropagation()
                      toggleMutation.mutate({ chatbotId: c.id, data: { is_active: !c.is_active } })
                    }}
                    className={`text-xs px-2 py-0.5 rounded-full border transition-colors ${
                      c.is_active
                        ? 'bg-green-100 text-green-700 border-green-200 hover:bg-green-200'
                        : 'bg-gray-100 text-gray-500 border-gray-200 hover:bg-gray-200'
                    }`}
                  >
                    {c.is_active ? t('hub.chatbot_active') : t('hub.chatbot_inactive')}
                  </button>
                </td>
                <td className="py-3 pr-4">
                  {/* SEC.4.1: el estado lo calcula el servidor y aquí solo se pinta. Nada
                      de comparar fechas en el cliente: serían dos máquinas de estado, la
                      del panel y la del chat, y se contradirían. */}
                  <span
                    className={`text-xs px-2 py-0.5 rounded-full border ${
                      AVAILABILITY_STYLES[c.availability?.state ?? 'available'] ??
                      AVAILABILITY_STYLES.available
                    }`}
                  >
                    {t(`hub.availability_${c.availability?.state ?? 'available'}`)}
                  </span>
                </td>
                <td className="py-3 text-right">
                  <button
                    type="button"
                    onClick={(e) => { e.stopPropagation(); openDelete(c) }}
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
        <div
          role="dialog"
          aria-modal="true"
          className="fixed inset-0 flex items-center justify-center bg-black/40 z-50 p-4"
          onClick={(e) => { if (e.target === e.currentTarget) closeDialog() }}
        >
          <div className="bg-card rounded-lg w-full max-w-md shadow-lg flex flex-col max-h-[90vh]">
            {/* Cabecera fija — siempre visible */}
            <div className="flex items-center justify-between px-6 py-4 border-b shrink-0">
              <h2 className="text-lg font-semibold truncate">
                {editing ? tc('edit') + ' — ' + editing.name : t('hub.new_chatbot')}
              </h2>
              <button
                type="button"
                onClick={closeDialog}
                className="ml-3 p-1 text-muted-foreground hover:text-foreground transition-colors"
                aria-label={tc('cancel')}
              >
                ✕
              </button>
            </div>

            {/* Cuerpo scrollable */}
            <div className="overflow-y-auto flex-1 px-6 py-4 space-y-4">
              {editing && (
                <div className="space-y-3 rounded-md border bg-muted/40 p-3 text-sm">
                  <div>
                    <p className="font-medium text-muted-foreground mb-1">{t('hub.chatbot_id_label')}</p>
                    <div className="flex items-center gap-2">
                      <code className="flex-1 truncate rounded bg-background px-2 py-1 font-mono text-xs border">
                        {editing.id}
                      </code>
                      <button
                        type="button"
                        onClick={copyId}
                        className="shrink-0 px-2 py-1 text-xs border rounded-md hover:bg-accent transition-colors"
                      >
                        {copied ? t('hub.chatbot_id_copied') : t('hub.chatbot_id_copy')}
                      </button>
                    </div>
                  </div>

                  <div>
                    <p className="font-medium text-muted-foreground mb-1">{t('hub.chatbot_install_title')}</p>
                    <p className="text-muted-foreground text-xs mb-1">{t('hub.chatbot_install_desc')}</p>
                    <pre
                      data-testid="install-snippet"
                      className="overflow-x-auto rounded bg-background border px-3 py-2 text-xs font-mono leading-relaxed"
                    >
                      {installSnippet(editing.id)}
                    </pre>
                  </div>
                </div>
              )}

              <form onSubmit={handleSubmit(onSubmit)} className="space-y-3">
                <div>
                  <label htmlFor="chatbot-name" className="text-sm font-medium">{t('hub.chatbot_name')}</label>
                  <input
                    id="chatbot-name"
                    {...register('name')}
                    className="w-full mt-1 px-3 py-2 border rounded-md text-sm bg-background"
                  />
                  {errors.name && <p className="text-destructive text-xs mt-1">{errors.name.message}</p>}
                </div>
                <div>
                  <label htmlFor="chatbot-llm-config" className="text-sm font-medium">
                    {t('hub.chatbot_model')}
                  </label>
                  <select
                    id="chatbot-llm-config"
                    {...register('llm_config_id')}
                    className="w-full mt-1 px-3 py-2 border rounded-md text-sm bg-background"
                  >
                    {llmConfigs.length === 0 && <option value="">{t('hub.no_llm_configs')}</option>}
                    {llmConfigs.map((config) => (
                      <option key={config.id} value={config.id}>{etiquetaModelo(config)}</option>
                    ))}
                  </select>
                  <p className="text-xs text-muted-foreground mt-1">{t('hub.chatbot_model_hint')}</p>
                  {errors.llm_config_id && (
                    <p className="text-destructive text-xs mt-1">{errors.llm_config_id.message}</p>
                  )}
                </div>
                {!editing && (
                  <div>
                    <label htmlFor="chatbot-organizacion" className="text-sm font-medium">
                      {t('hub.chatbot_organizacion')}
                    </label>
                    <select
                      id="chatbot-organizacion"
                      {...register('organizacion_id')}
                      className="w-full mt-1 px-3 py-2 border rounded-md text-sm bg-background"
                    >
                      {organizaciones.map((org) => (
                        <option key={org.id} value={org.id}>{org.name}</option>
                      ))}
                    </select>
                    {errors.organizacion_id && (
                      <p className="text-destructive text-xs mt-1">{errors.organizacion_id.message}</p>
                    )}
                  </div>
                )}
                <div>
                  <label htmlFor="chatbot-kind" className="text-sm font-medium">{t('hub.chatbot_kind')}</label>
                  <select
                    id="chatbot-kind"
                    {...register('kind')}
                    className="w-full mt-1 px-3 py-2 border rounded-md text-sm bg-background"
                  >
                    <option value="atomic">{t('hub.chatbot_kind_atomic')}</option>
                    <option value="router">{t('hub.chatbot_kind_router')}</option>
                  </select>
                </div>
                <div>
                  <label htmlFor="chatbot-system-prompt" className="text-sm font-medium">{selectedKind === 'router' ? t('hub.chatbot_router_description') : t('hub.chatbot_prompt')}</label>
                  <textarea
                    id="chatbot-system-prompt"
                    {...register('system_prompt')}
                    rows={8}
                    className="w-full mt-1 px-3 py-2 border rounded-md text-sm bg-background resize-y"
                  />
                  {errors.system_prompt && <p className="text-destructive text-xs mt-1">{errors.system_prompt.message}</p>}
                </div>
                {editing && corpusStats && (
                  <div className="rounded-md border bg-blue-50 border-blue-200 p-3 space-y-1">
                    <p className="text-sm">
                      <span className="font-medium">{t('hub.chatbot_suggested')}</span>{' '}
                      <strong>{corpusStats.recommended_mode}</strong>
                      <span className="text-muted-foreground"> — {corpusStats.total_tokens.toLocaleString()} tokens</span>
                    </p>
                    <p className="text-xs text-muted-foreground">{corpusStats.recommendation_reason}</p>
                    {selectedKind === 'atomic' && watch('retrieval_mode') !== corpusStats.recommended_mode && (
                      <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-2 py-1">
                        Has elegido un modo distinto del recomendado para este corpus.
                      </p>
                    )}
                    {selectedKind === 'atomic' && watch('retrieval_mode') === 'RAG' && (
                      <div className="pt-1">
                        <button
                          type="button"
                          onClick={() => regenerateChunksMutation.mutate({ chatbotId: editing!.id })}
                          disabled={regenerateChunksMutation.isPending}
                          className="px-2 py-1 text-xs border rounded-md hover:bg-accent disabled:opacity-50"
                        >
                          {regenerateChunksMutation.isPending ? 'Regenerando...' : 'Recalcular chunks'}
                        </button>
                      </div>
                    )}
                  </div>
                )}

                {selectedKind === 'atomic' && (
                  <>
                    <div>
                      <label htmlFor="chatbot-retrieval-mode" className="text-sm font-medium">{t('hub.chatbot_retrieval_mode')}</label>
                      <select
                        id="chatbot-retrieval-mode"
                        {...register('retrieval_mode')}
                        className="w-full mt-1 px-3 py-2 border rounded-md text-sm bg-background"
                      >
                        {modosDisponibles.map(m => (
                          <option key={m.nombre} value={m.nombre}>
                            {ETIQUETAS_DE_MODO[m.nombre] ? t(ETIQUETAS_DE_MODO[m.nombre].labelKey) : m.nombre}
                          </option>
                        ))}
                      </select>
                      {retrievalHint && <p className="text-xs text-muted-foreground mt-1">{retrievalHint}</p>}
                    </div>
                    {watch('retrieval_mode') === 'RAG' && (
                      <div>
                        <label htmlFor="chatbot-top-k" className="text-sm font-medium">{t('hub.chatbot_top_k')}</label>
                        <input
                          type="number"
                          min={1}
                          max={50}
                          id="chatbot-top-k"
                            {...register('retrieval_top_k', { valueAsNumber: true })}
                          className="w-full mt-1 px-3 py-2 border rounded-md text-sm bg-background"
                        />
                        {errors.retrieval_top_k && <p className="text-destructive text-xs mt-1">{errors.retrieval_top_k.message}</p>}
                        <p className="text-xs text-muted-foreground mt-1">{t('hub.chatbot_top_k_hint')}</p>
                      </div>
                    )}
                    {watch('retrieval_mode') === 'MD_LONG_CONTEXT' && (
                      <div className="rounded-md border bg-muted/40 p-3 space-y-2">
                        <div className="flex items-center gap-2">
                          <input
                            type="checkbox"
                            id="use_prompt_caching"
                            {...register('use_prompt_caching')}
                            className="rounded"
                          />
                          <label htmlFor="use_prompt_caching" className="text-sm">
                            {t('hub.chatbot_prompt_caching')}
                          </label>
                        </div>
                        {watch('use_prompt_caching') && (
                          <div>
                            <label htmlFor="chatbot-cache-ttl" className="text-sm font-medium">{t('hub.chatbot_cache_ttl')}</label>
                            <input
                              type="number"
                              min={60}
                              max={86400}
                              id="chatbot-cache-ttl"
                            {...register('cache_ttl', { valueAsNumber: true })}
                              className="w-full mt-1 px-3 py-2 border rounded-md text-sm bg-background"
                            />
                            {errors.cache_ttl && <p className="text-destructive text-xs mt-1">{errors.cache_ttl.message}</p>}
                          </div>
                        )}
                      </div>
                    )}
                    {showLongContextHardError && (
                      <p className="text-destructive text-xs mt-1">
                        {t('hub.chatbot_long_context_error')}
                      </p>
                    )}
                    <div className="pt-2">
                      <p className="text-sm font-medium text-muted-foreground mb-2">{t('hub.chatbot_graph_section')}</p>
                      <div className="space-y-3 rounded-md border bg-muted/40 p-3">
                        <div>
                          <label htmlFor="chatbot-graph-profile" className="text-sm font-medium">{t('hub.chatbot_graph_profile')}</label>
                          {/* PLG.3 — la unica opcion estaba escrita aqui, asi que un perfil
                              instalado no habria aparecido nunca. Ahora la lista viene del
                              servidor, y los NO configurables salen deshabilitados con su
                              motivo en vez de ocultarse: ocultarlos dejaria sin explicar por
                              que un perfil que existe no se puede elegir. */}
                          <select
                            id="chatbot-graph-profile"
                            {...register('public_graph_profile')}
                            className="w-full mt-1 px-3 py-2 border rounded-md text-sm bg-background"
                          >
                            {perfilesDisponibles.map(p => (
                              <option key={p.nombre} value={p.nombre} disabled={!p.configurable}>
                                {p.nombre === 'PUBLIC_KB_RICH' ? t('hub.chatbot_graph_profile_rich') : p.nombre}
                                {p.configurable ? '' : ` — ${t('hub.chatbot_graph_profile_no_configurable')}`}
                              </option>
                            ))}
                          </select>
                        </div>
                        {/* LANG.2 — la lista venía escrita aquí y ofrecía `strict`, que la
                            factoría del grafo nunca compuso: una opción que no hacía nada, y
                            que desde LANG.1 además da 422. Ahora los modos y los idiomas los
                            trae el contrato, con el código del corpus (`val`, no `ca`). */}
                        <SelectorDeModoDeLengua
                          idPrefijo="chatbot-language"
                          valor={watch('language_mode') ?? 'prefer'}
                          onChange={(v) =>
                            setValue('language_mode', v, { shouldDirty: true })
                          }
                        />
                        {/* PLG.2/PLG.3 — un select por EJE, y los ejes salen de la respuesta:
                            no hay lista de ejes en React. «Heredar» manda la clave AUSENTE, no
                            una cadena vacia, porque la cascada distingue las dos cosas: ausente
                            hereda de la organizacion y, en su defecto, de la composicion del
                            perfil. */}
                        {ejes.length > 0 && (
                          <div className="space-y-2 rounded-md border border-dashed p-2">
                            <p className="text-xs font-medium text-muted-foreground">
                              {t('hub.chatbot_estrategias')}
                            </p>
                            {ejes.map(eje => {
                              const puestas = watch('estrategias') ?? {}
                              const disponibles = opciones?.estrategias?.[eje] ?? []
                              return (
                                <div key={eje}>
                                  <label htmlFor={`chatbot-estrategia-${eje}`} className="text-xs font-medium">
                                    {ETIQUETA_DE_EJE[eje] ? t(ETIQUETA_DE_EJE[eje]) : eje}
                                  </label>
                                  <select
                                    id={`chatbot-estrategia-${eje}`}
                                    value={puestas[eje] ?? ''}
                                    onChange={(e) => {
                                      const siguiente = { ...puestas }
                                      if (e.target.value) siguiente[eje] = e.target.value
                                      else delete siguiente[eje]
                                      setValue('estrategias', siguiente, { shouldDirty: true })
                                    }}
                                    className="w-full mt-1 px-3 py-2 border rounded-md text-sm bg-background"
                                  >
                                    <option value="">{t('hub.chatbot_estrategia_heredar')}</option>
                                    {disponibles.map(s => (
                                      <option key={s.nombre} value={s.nombre}>
                                        {s.nombre}{s.origen === 'paquete' ? ` (${t('hub.chatbot_estrategia_de_paquete')})` : ''}
                                      </option>
                                    ))}
                                  </select>
                                </div>
                              )
                            })}
                          </div>
                        )}
                        <div>
                          <label htmlFor="chatbot-quality-threshold" className="text-sm font-medium">{t('hub.chatbot_quality_threshold')}</label>
                          <input
                            type="number"
                            min={0}
                            max={1}
                            step={0.05}
                            id="chatbot-quality-threshold"
                            {...register('quality_threshold', { valueAsNumber: true })}
                            className="w-full mt-1 px-3 py-2 border rounded-md text-sm bg-background"
                          />
                        </div>
                        <div>
                          <label htmlFor="chatbot-min-results" className="text-sm font-medium">{t('hub.chatbot_min_results')}</label>
                          <input
                            type="number"
                            min={1}
                            max={20}
                            id="chatbot-min-results"
                            {...register('min_retrieval_results', { valueAsNumber: true })}
                            className="w-full mt-1 px-3 py-2 border rounded-md text-sm bg-background"
                          />
                        </div>
                        <div>
                          <label htmlFor="chatbot-min-score" className="text-sm font-medium">{t('hub.chatbot_min_score')}</label>
                          <input
                            type="number"
                            min={0}
                            max={1}
                            step={0.05}
                            id="chatbot-min-score"
                            {...register('min_retrieval_score', { valueAsNumber: true })}
                            className="w-full mt-1 px-3 py-2 border rounded-md text-sm bg-background"
                          />
                        </div>
                        <div className="flex items-center gap-2">
                          <input
                            type="checkbox"
                            id="reranker_enabled"
                            {...register('reranker_enabled')}
                            className="rounded"
                          />
                          <label htmlFor="reranker_enabled" className="text-sm">{t('hub.chatbot_reranker_enabled')}</label>
                        </div>
                        <div>
                          <label htmlFor="chatbot-answer-template" className="text-sm font-medium">{t('hub.chatbot_answer_template')}</label>
                          <select
                            id="chatbot-answer-template"
                            {...register('answer_template')}
                            className="w-full mt-1 px-3 py-2 border rounded-md text-sm bg-background"
                          >
                            <option value="generic">{t('hub.chatbot_answer_template_generic')}</option>
                            <option value="institutional">{t('hub.chatbot_answer_template_institutional')}</option>
                          </select>
                        </div>
                      </div>
                    </div>
                  </>
                )}
                {editing && selectedKind === 'router' && (
                  <div className="rounded-md border bg-muted/40 p-3 space-y-2">
                    <div className="flex items-center justify-between gap-2">
                      <p className="text-sm font-medium">Sub-chatbots</p>
                      <button
                        type="button"
                        onClick={() => setAssignOpen(true)}
                        className="px-2 py-1 text-xs border rounded-md hover:bg-accent"
                      >
                        Asignar hijo
                      </button>
                    </div>
                    {isLoadingChildren && <p className="text-xs text-muted-foreground">Cargando sub-chatbots...</p>}
                    {!isLoadingChildren && children.length === 0 && (
                      <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-2 py-1">
                        Este router no tiene sub-chatbots asignados
                      </p>
                    )}
                    {!isLoadingChildren && children.length > 0 && (
                      <ul className="space-y-1">
                        {children.map((child) => (
                          <li key={child.id} className="text-xs rounded border px-2 py-1 bg-background">
                            {child.name}
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                )}

                {assignOpen && editing && selectedKind === 'router' && (
                  <div className="rounded-md border p-3 space-y-2 bg-background">
                    <label htmlFor="chatbot-child-select" className="text-xs font-medium">{t('hub.chatbot_select_atomic')}</label>
                    <select
                      value={selectedChildId}
                      onChange={(e) => setSelectedChildId(e.target.value)}
                      className="w-full mt-1 px-3 py-2 border rounded-md text-sm bg-background"
                    >
                      <option value="">-- Seleccionar --</option>
                      {assignableChildren.map((cb) => (
                        <option key={cb.id} value={cb.id}>{cb.name}</option>
                      ))}
                    </select>
                    <div className="flex justify-end gap-2">
                      <button
                        type="button"
                        onClick={() => { setAssignOpen(false); setSelectedChildId('') }}
                        className="px-2 py-1 text-xs border rounded-md"
                      >
                        Cancelar
                      </button>
                      <button
                        type="button"
                        disabled={!selectedChildId || assignChildMutation.isPending}
                        onClick={() =>
                          assignChildMutation.mutate({
                            chatbotId: editing.id,
                            data: { child_chatbot_id: selectedChildId },
                          })
                        }
                        className="px-2 py-1 text-xs bg-primary text-primary-foreground rounded-md disabled:opacity-50"
                      >
                        Asignar
                      </button>
                    </div>
                  </div>
                )}

                <div className="flex items-center gap-2">
                  <input type="checkbox" id="is_active" {...register('is_active')} className="rounded" />
                  <label htmlFor="is_active" className="text-sm">{t('hub.chatbot_active')}</label>
                </div>

                {/* SEC.4.1: vigencia y techo de gasto. `is_active` es el interruptor manual;
                    esto es el que se apaga solo. Son cosas distintas y se editan aparte. */}
                <fieldset className="border rounded-md p-3 space-y-3">
                  <legend className="text-xs font-medium px-1">{t('hub.availability')}</legend>
                  <p className="text-xs text-muted-foreground">
                    {t('hub.availability_hint')}
                  </p>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label htmlFor="valid_from" className="block text-sm mb-1">
                        {t('hub.valid_from')}
                      </label>
                      <input
                        type="datetime-local"
                        id="valid_from"
                        {...register('valid_from')}
                        className="w-full px-2 py-1 border rounded-md text-sm"
                      />
                    </div>
                    <div>
                      <label htmlFor="valid_until" className="block text-sm mb-1">
                        {t('hub.valid_until')}
                      </label>
                      <input
                        type="datetime-local"
                        id="valid_until"
                        {...register('valid_until')}
                        className="w-full px-2 py-1 border rounded-md text-sm"
                      />
                    </div>
                  </div>
                  <div>
                    <label htmlFor="total_token_budget" className="block text-sm mb-1">
                      {t('hub.total_token_budget')}
                    </label>
                    <input
                      type="number"
                      id="total_token_budget"
                      min={0}
                      {...register('total_token_budget', { valueAsNumber: true })}
                      className="w-full px-2 py-1 border rounded-md text-sm"
                    />
                    {/* 0 = sin techo, igual que en el backend. Decirlo aquí evita que
                        alguien ponga 0 creyendo que bloquea el chatbot. */}
                    <p className="text-xs text-muted-foreground mt-1">
                      {t('hub.total_token_budget_hint')}
                    </p>
                    {errors.total_token_budget && (
                      <p className="text-xs text-destructive mt-1">
                        {errors.total_token_budget.message}
                      </p>
                    )}
                  </div>
                  {/* SEC.4: los tres techos diarios. Existian en la base de datos y los
                      aplicaba el servidor desde SEC.4, pero no habia forma de fijarlos que no
                      fuera un UPDATE a mano, asi que en la practica quedaban sin poner. */}
                  <div className="grid grid-cols-3 gap-2">
                    <div>
                      <label htmlFor="user_daily_token_quota" className="block text-sm mb-1">
                        {t('hub.user_daily_token_quota')}
                      </label>
                      <input
                        type="number"
                        id="user_daily_token_quota"
                        min={0}
                        {...register('user_daily_token_quota')}
                        className="w-full px-2 py-1 border rounded-md text-sm"
                        placeholder={t('hub.quota_inherit')}
                      />
                    </div>
                    <div>
                      <label htmlFor="chatbot_daily_token_quota" className="block text-sm mb-1">
                        {t('hub.chatbot_daily_token_quota')}
                      </label>
                      <input
                        type="number"
                        id="chatbot_daily_token_quota"
                        min={0}
                        {...register('chatbot_daily_token_quota')}
                        className="w-full px-2 py-1 border rounded-md text-sm"
                        placeholder={t('hub.quota_inherit')}
                      />
                    </div>
                    <div>
                      <label htmlFor="anon_ip_daily_token_quota" className="block text-sm mb-1">
                        {t('hub.anon_ip_daily_token_quota')}
                      </label>
                      <input
                        type="number"
                        id="anon_ip_daily_token_quota"
                        min={0}
                        {...register('anon_ip_daily_token_quota')}
                        className="w-full px-2 py-1 border rounded-md text-sm"
                        placeholder={t('hub.quota_inherit')}
                      />
                    </div>
                  </div>
                  <p className="text-xs text-muted-foreground -mt-1">
                    {t('hub.quota_hint')}
                  </p>
                  <div>
                    <label htmlFor="unavailable_message" className="block text-sm mb-1">
                      {t('hub.unavailable_message')}
                    </label>
                    <textarea
                      id="unavailable_message"
                      rows={2}
                      {...register('unavailable_message')}
                      className="w-full px-2 py-1 border rounded-md text-sm"
                      placeholder={t('hub.unavailable_message_placeholder')}
                    />
                    {errors.unavailable_message && (
                      <p className="text-xs text-destructive mt-1">
                        {errors.unavailable_message.message}
                      </p>
                    )}
                  </div>
                  {editing?.availability && (
                    <p className="text-xs text-muted-foreground">
                      {t('hub.availability')}:{' '}
                      <span data-testid="availability-state">
                        {t(`hub.availability_${editing.availability.state}`)}
                      </span>
                      {' · '}
                      {editing.availability.tokens_used} tokens
                    </p>
                  )}
                </fieldset>
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
                    disabled={isPending || showLongContextHardError}
                    className="px-3 py-2 bg-primary text-primary-foreground rounded-md text-sm disabled:opacity-50"
                  >
                    {tc('save')}
                  </button>
                </div>
              </form>
            </div>
          </div>
        </div>
      )}

      {/* Dialog confirmación borrado */}
      {deleteTarget && (
        <div role="dialog" aria-modal="true" className="fixed inset-0 flex items-center justify-center bg-black/40 z-50">
          <div className="bg-card rounded-lg p-6 w-full max-w-sm shadow-lg space-y-4">
            <p className="text-sm">{t('hub.delete_confirm')}</p>
            <p className="font-medium">{deleteTarget.name}</p>
            {deleteError && (
              <div className="rounded-md bg-destructive/10 border border-destructive/30 px-3 py-2">
                <p className="text-destructive text-sm font-medium">{deleteError}</p>
              </div>
            )}
            <div className="flex gap-2 justify-end">
              <button
                type="button"
                onClick={() => { setDeleteTarget(null); setDeleteError('') }}
                className="px-3 py-2 border rounded-md text-sm"
              >
                {tc('cancel')}
              </button>
              <button
                type="button"
                onClick={() => deleteMutation.mutate({ chatbotId: deleteTarget.id })}
                disabled={deleteMutation.isPending}
                className="px-3 py-2 bg-destructive text-destructive-foreground rounded-md text-sm disabled:opacity-50 min-w-[80px]"
              >
                {deleteMutation.isPending ? '...' : tc('delete')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
