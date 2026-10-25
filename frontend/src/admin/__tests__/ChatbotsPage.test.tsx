import { describe, it, expect, beforeAll, afterEach, vi } from 'vitest'
import { render, screen, waitFor, act, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import i18n from '@/shared/i18n'
import { AuthProvider } from '@/shared/auth'
import type { ChatbotRead, CorpusStatsOut } from '@/shared/api/generated/model'
import { ChatbotsPage } from '../pages/ChatbotsPage'

const { mockAssignMutate, mockUpdateMutate, mockData } = vi.hoisted(() => ({
  mockAssignMutate: vi.fn(),
  // SEC.4.1: hace falta ver QUE se envia, no solo que se envie algo.
  mockUpdateMutate: vi.fn(),
  mockData: {
    chatbots: [] as ChatbotRead[],
    children: [] as ChatbotRead[],
    corpusStats: undefined as CorpusStatsOut | undefined,
  },
}))

vi.mock('@/shared/api/generated/hub-chatbots/hub-chatbots', () => ({
  useOpcionesDeGrafoApiV1HubChatbotsOpcionesDeGrafoGet: () => ({ data: { perfiles: [{ nombre: 'PUBLIC_KB_RICH', configurable: true }], modos: [{ nombre: 'RAG' }, { nombre: 'MD_LONG_CONTEXT' }, { nombre: 'MD_AGENT_SELECTOR' }], estrategias: { retrieval: [], merge: [], template: [], language: [] }, ejes: ['retrieval', 'merge', 'template', 'language'] } }),
  useListChatbotsApiV1HubChatbotsGet: vi.fn(() => ({ data: mockData.chatbots, isLoading: false })),
  useListChildrenApiV1HubChatbotsChatbotIdChildrenGet: vi.fn(() => ({ data: mockData.children, isLoading: false })),
  useGetCorpusStatsApiV1HubChatbotsChatbotIdCorpusStatsGet: vi.fn(() => ({ data: mockData.corpusStats })),
  useCreateChatbotApiV1HubChatbotsPost: vi.fn(() => ({ mutate: vi.fn(), isPending: false, reset: vi.fn() })),
  useUpdateChatbotApiV1HubChatbotsChatbotIdPatch: vi.fn(() => ({ mutate: mockUpdateMutate, isPending: false, reset: vi.fn() })),
  useDeleteChatbotApiV1HubChatbotsChatbotIdDelete: vi.fn(() => ({ mutate: vi.fn(), isPending: false, reset: vi.fn() })),
  useAssignChildApiV1HubChatbotsChatbotIdChildrenPost: vi.fn(() => ({ mutate: mockAssignMutate, isPending: false })),
  useRegenerateChunksApiV1HubChatbotsChatbotIdRegenerateChunksPost: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  getListChatbotsApiV1HubChatbotsGetQueryKey: vi.fn(() => ['/api/v1/hub/chatbots']),
  getListChildrenApiV1HubChatbotsChatbotIdChildrenGetQueryKey: vi.fn((id: string) => [`/api/v1/hub/chatbots/${id}/children`]),
  getGetCorpusStatsApiV1HubChatbotsChatbotIdCorpusStatsGetQueryKey: vi.fn((id: string) => [`/api/v1/hub/chatbots/${id}/corpus-stats`]),
}))

// FIX.1: la página lee dos catálogos del contrato en vez de dos constantes hardcodeadas.
vi.mock('@/shared/api/generated/hub-llm-configs/hub-llm-configs', () => ({
  useListLlmConfigsApiV1HubLlmConfigsGet: vi.fn(() => ({
    data: [
      { id: '00000000-0000-0000-0000-000000000001', provider: 'google', model_name: 'gemini-2.5-flash', label: '', tier: 1, purpose: 'chat', is_default: true },
    ],
    isLoading: false,
  })),
}))

vi.mock('@/shared/api/generated/hub-organizaciones/hub-organizaciones', () => ({
  useListOrganizacionesApiV1HubOrganizacionesGet: vi.fn(() => ({
    data: [{ id: '00000000-0000-0000-0000-000000000010', name: 'UJI' }],
    isLoading: false,
  })),
}))

const TOKEN = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.' +
  btoa(JSON.stringify({ sub: '1', email: 'admin@test.com', role: 'admin', exp: 9999999999 }))
    .replace(/=/g, '').replace(/\+/g, '-').replace(/\//g, '_') +
  '.signature'

const writeTextMock = vi.fn().mockResolvedValue(undefined)

beforeAll(async () => {
  await i18n.changeLanguage('es')
  localStorage.setItem('access_token', TOKEN)
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText: writeTextMock },
    writable: true,
    configurable: true,
  })
})

afterEach(() => {
  vi.clearAllMocks()
  mockData.chatbots = []
  mockData.children = []
  mockData.corpusStats = undefined
})

const DEMO_CHATBOT: ChatbotRead = {
  id: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
  puede_ser_hijo: true,
  name: 'Bot Demo',
  organizacion_id: '00000000-0000-0000-0000-000000000010',
  llm_config_id: '00000000-0000-0000-0000-000000000001',
  system_prompt: 'Eres útil.',
  sources: [],
  is_active: true,
  retrieval_mode: 'RAG',
  retrieval_top_k: 8,
  use_prompt_caching: false,
  cache_ttl: 3600,
  kind: 'atomic',
  parent_chatbot_id: null,
  // SEC.2.1: el contrato dice para quién es el chatbot. Quien lo aplica es el backend.
  access_mode: 'authenticated',
  allowed_roles: [],
  allowed_saml_groups: [],
  // SEC.4.1: la ventana de vigencia y el techo acumulado. `availability` es
  // derivado y de solo lectura: lo calcula el servidor.
  valid_from: null,
  valid_until: null,
  total_token_budget: null,
  unavailable_message: '',
  public_graph_profile: 'PUBLIC_KB_RICH',
  language_mode: 'prefer',
  quality_threshold: 0.6,
  min_retrieval_results: 2,
  min_retrieval_score: 0.25,
  reranker_enabled: true,
  answer_template: 'generic',
  context_token_budget: null,
  chunk_size: null,
  chunk_overlap: null,
  chunking_strategy: null,
  query_rewriting_enabled: null,
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:00:00Z',
}

const ROUTER_CHATBOT: ChatbotRead = {
  ...DEMO_CHATBOT,
  id: 'bbbbbbbb-bbbb-cccc-dddd-eeeeeeeeeeee',
  name: 'Router UJI',
  kind: 'router',
}

const CHILD_CHATBOT: ChatbotRead = {
  ...DEMO_CHATBOT,
  id: 'cccccccc-bbbb-cccc-dddd-eeeeeeeeeeee',
  name: 'RRHH',
}

const DEMO_CORPUS_STATS: CorpusStatsOut = {
  total_documents: 2,
  total_tokens: 120000,
  by_language: { es: 100000, ca: 20000 },
  recommended_mode: 'MD_AGENT_SELECTOR',
  recommendation_reason: 'Recomendado MD_AGENT_SELECTOR para este tamaño de corpus.',
  limite_contexto_largo: 128000,
  cabe_en_contexto_largo: true,
}

function renderPage(chatbots: ChatbotRead[] = [], children: ChatbotRead[] = [], corpusStats?: CorpusStatsOut) {
  mockData.chatbots = chatbots
  mockData.children = children
  mockData.corpusStats = corpusStats
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <AuthProvider>
          <ChatbotsPage />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>
  )
}

async function openEditDialog(chatbot = DEMO_CHATBOT, allChatbots: ChatbotRead[] = [chatbot], children: ChatbotRead[] = [], corpusStats?: CorpusStatsOut) {
  renderPage(allChatbots, children, corpusStats)
  await waitFor(() => screen.getByText(chatbot.name))
  await act(async () => {
    fireEvent.click(screen.getByText(chatbot.name))
  })
  await waitFor(() => screen.getByRole('dialog'))
}

describe('ChatbotsPage', () => {
  it('should_show_empty_state_when_no_chatbots', async () => {
    renderPage([])
    await waitFor(() => {
      expect(screen.getByText('No hay chatbots creados')).toBeDefined()
    })
  })

  it('should_list_chatbots_from_api', async () => {
    renderPage([DEMO_CHATBOT])
    await waitFor(() => {
      expect(screen.getByText('Bot Demo')).toBeDefined()
    })
  })

  it('should_show_new_chatbot_button', async () => {
    renderPage([])
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /nuevo chatbot/i })).toBeDefined()
    })
  })

  it('should_open_form_on_new_chatbot_click', async () => {
    renderPage([])
    await waitFor(() => screen.getByRole('button', { name: /nuevo chatbot/i }))
    await act(async () => {
      screen.getByRole('button', { name: /nuevo chatbot/i }).click()
    })
    expect(screen.getByRole('dialog')).toBeDefined()
  })

  it('should_show_delete_button_per_chatbot', async () => {
    renderPage([DEMO_CHATBOT])
    await waitFor(() => screen.getByText('Bot Demo'))
    expect(screen.getByRole('button', { name: /eliminar/i })).toBeDefined()
  })

  it('should_show_chatbot_id_in_edit_dialog', async () => {
    await openEditDialog()
    expect(screen.getByText(DEMO_CHATBOT.id)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /copiar/i })).toBeInTheDocument()
  })

  it('should_copy_chatbot_id_to_clipboard', async () => {
    await openEditDialog()
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /copiar/i }))
    })
    expect(writeTextMock).toHaveBeenCalledWith(DEMO_CHATBOT.id)
  })

  it('should_show_install_snippet_in_edit_dialog', async () => {
    await openEditDialog()
    const snippet = screen.getByTestId('install-snippet')
    expect(snippet.textContent).toContain(`data-chatbot-id="${DEMO_CHATBOT.id}"`)
  })

  // #279 — el fragmento se pega en OTRA web: una ruta relativa apuntaba a la anfitriona. Con la
  // imagen de producción `VITE_API_URL` va vacía, y salía `data-api-url="/api/v1"`.
  it('should_give_absolute_urls_in_the_install_snippet', async () => {
    vi.stubEnv('VITE_API_URL', '')
    try {
      await openEditDialog()
      const texto = screen.getByTestId('install-snippet').textContent ?? ''
      expect(texto).toContain(`data-api-url="${window.location.origin}/api/v1"`)
      expect(texto).toContain(`src="${window.location.origin}/widget.iife.js"`)
      expect(texto).not.toContain('ejemplo.com')
    } finally {
      vi.unstubAllEnvs()
    }
  })

  it('should_show_kind_selector_in_form', async () => {
    renderPage([])
    await waitFor(() => screen.getByRole('button', { name: /nuevo chatbot/i }))
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /nuevo chatbot/i }))
    })
    expect(screen.getByText(/tipo de chatbot/i)).toBeInTheDocument()
  })

  it('should_hide_retrieval_mode_when_kind_is_router', async () => {
    renderPage([])
    await waitFor(() => screen.getByRole('button', { name: /nuevo chatbot/i }))
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /nuevo chatbot/i }))
    })

    const kindSelect = screen.getByLabelText(/tipo de chatbot/i)
    await act(async () => {
      fireEvent.change(kindSelect, { target: { value: 'router' } })
    })

    expect(screen.queryByText(/modo de retrieval/i)).not.toBeInTheDocument()
  })

  it('should_show_children_section_for_router_chatbots', async () => {
    await openEditDialog(ROUTER_CHATBOT, [ROUTER_CHATBOT], [])
    expect(screen.getByRole('button', { name: /asignar hijo/i })).toBeInTheDocument()
  })

  it('should_warn_when_router_has_no_children', async () => {
    await openEditDialog(ROUTER_CHATBOT, [ROUTER_CHATBOT], [])
    expect(screen.getByText(/no tiene sub-chatbots asignados/i)).toBeInTheDocument()
  })

  it('should_assign_child_via_modal', async () => {
    await openEditDialog(ROUTER_CHATBOT, [ROUTER_CHATBOT, CHILD_CHATBOT], [])
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /asignar hijo/i }))
    })

    const select = screen.getByDisplayValue('-- Seleccionar --')
    await act(async () => {
      fireEvent.change(select, { target: { value: CHILD_CHATBOT.id } })
    })

    const assignButtons = screen.getAllByRole('button', { name: /^asignar$/i })
    await act(async () => {
      fireEvent.click(assignButtons[assignButtons.length - 1])
    })

    expect(mockAssignMutate).toHaveBeenCalledWith(
      expect.objectContaining({
        chatbotId: ROUTER_CHATBOT.id,
        data: expect.objectContaining({ child_chatbot_id: CHILD_CHATBOT.id }),
      })
    )
  })

  it('should_show_recommendation_banner_with_reason', async () => {
    await openEditDialog(DEMO_CHATBOT, [DEMO_CHATBOT], [], DEMO_CORPUS_STATS)
    expect(screen.getByText(/sugerido:/i)).toBeInTheDocument()
    expect(screen.getByText(/recomendado md_agent_selector/i)).toBeInTheDocument()
  })

  it('should_warn_when_user_picks_non_recommended_mode', async () => {
    await openEditDialog(DEMO_CHATBOT, [DEMO_CHATBOT], [], DEMO_CORPUS_STATS)
    await waitFor(() => screen.getByText(/sugerido:/i))

    const retrievalSelect = screen.getByLabelText(/modo de retrieval/i)
    await act(async () => {
      fireEvent.change(retrievalSelect, { target: { value: 'RAG' } })
    })

    expect(screen.getByText(/modo distinto del recomendado/i)).toBeInTheDocument()
  })

  it('should_show_chunk_regeneration_button_only_for_vector_mode', async () => {
    await openEditDialog(DEMO_CHATBOT, [DEMO_CHATBOT], [], DEMO_CORPUS_STATS)
    expect(screen.getByRole('button', { name: /recalcular chunks/i })).toBeInTheDocument()

    const retrievalSelect = screen.getByLabelText(/modo de retrieval/i)
    await act(async () => {
      fireEvent.change(retrievalSelect, { target: { value: 'MD_AGENT_SELECTOR' } })
    })

    expect(screen.queryByRole('button', { name: /recalcular chunks/i })).not.toBeInTheDocument()
  })
  // ── SEC.4.1: vigencia y presupuesto ───────────────────────────────────────────
  //
  // Estos tests existen porque el badge se implementó y el formulario no: la lista
  // enseñaba "Disponible" y no había ningún sitio donde poner la fecha, así que la
  // función era inalcanzable desde la interfaz.

  it('should_render_the_availability_window_fields_in_the_form', async () => {
    await openEditDialog()

    expect(screen.getByLabelText(/disponible desde/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/disponible hasta/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/presupuesto total/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/mensaje cuando no está disponible/i)).toBeInTheDocument()
  })

  it('should_preload_the_dates_the_chatbot_already_has', async () => {
    // El `datetime-local` no entiende zona: si no se recorta la ISO, el campo sale vacío
    // y guardar borraría la fecha en silencio.
    const conVentana: ChatbotRead = {
      ...DEMO_CHATBOT,
      valid_until: '2026-09-30T23:59:00+00:00',
      total_token_budget: 50000,
      unavailable_message: 'El plazo terminó.',
    }
    await openEditDialog(conVentana, [conVentana])

    expect(screen.getByLabelText(/disponible hasta/i)).toHaveValue('2026-09-30T23:59')
    expect(screen.getByLabelText(/presupuesto total/i)).toHaveValue(50000)
    expect(screen.getByLabelText(/mensaje cuando no está disponible/i)).toHaveValue('El plazo terminó.')
  })

  it('should_send_the_window_to_the_api_when_saving', async () => {
    await openEditDialog()

    await act(async () => {
      fireEvent.change(screen.getByLabelText(/disponible hasta/i), {
        target: { value: '2026-09-30T23:59' },
      })
      fireEvent.change(screen.getByLabelText(/mensaje cuando no está disponible/i), {
        target: { value: 'Plazo cerrado.' },
      })
    })
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /guardar/i }))
    })

    await waitFor(() => expect(mockUpdateMutate).toHaveBeenCalled())
    const enviado = mockUpdateMutate.mock.calls[0][0].data
    expect(enviado.valid_until).toContain('2026-09-30')
    expect(enviado.unavailable_message).toBe('Plazo cerrado.')
  })

  it('should_send_null_when_the_date_is_left_empty', async () => {
    // Vacío es «sin ventana». Mandar '' rompería la validación de fecha del backend en
    // vez de significar «ninguna».
    const conVentana: ChatbotRead = { ...DEMO_CHATBOT, valid_until: '2026-09-30T23:59:00+00:00' }
    await openEditDialog(conVentana, [conVentana])

    await act(async () => {
      fireEvent.change(screen.getByLabelText(/disponible hasta/i), { target: { value: '' } })
    })
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /guardar/i }))
    })

    await waitFor(() => expect(mockUpdateMutate).toHaveBeenCalled())
    expect(mockUpdateMutate.mock.calls[0][0].data.valid_until).toBeNull()
  })

  it('should_show_the_derived_state_the_server_calculated', async () => {
    const caducado: ChatbotRead = {
      ...DEMO_CHATBOT,
      availability: {
        state: 'expired',
        reason: 'expired',
        tokens_used: 120,
        total_token_budget: null,
      },
    }
    renderPage([caducado])

    await waitFor(() => screen.getByText('Bot Demo'))
    expect(screen.getByText('Caducado')).toBeInTheDocument()
  })
})

/**
 * El interruptor de actividad nombraba otra acción: decía «Editar» y activaba.
 *
 * **Encontrado verificando LANG.2 en el navegador**, y de la peor manera: buscando el botón de
 * editar de la fila pinché el chip de la columna «Activo», que en un chatbot inactivo se pintaba
 * con `tc('edit')`. No abrió ningún diálogo — **activó el asistente**, y hubo que devolverlo a
 * `is_active: false` por API.
 *
 * No es un caso raro: es lo que le pasa a cualquiera que busque «Editar» en la fila, porque el
 * editar de verdad está en el clic sobre la fila y no en un botón.
 *
 * **La etiqueta pasa a nombrar el estado**, que es lo que la columna dice que muestra —su
 * encabezado es «Activo»— y lo que ya hacía la mitad verde. Así el color y el texto dicen lo
 * mismo, y el texto no promete una acción que no ocurre. Con `aria-pressed`, porque es un
 * interruptor: sin él un lector de pantalla lee «Inactivo» como etiqueta y no dice que se pueda
 * pulsar para cambiarlo.
 */
describe('El interruptor de actividad nombra el estado, no otra acción', () => {
  const INACTIVO: ChatbotRead = { ...DEMO_CHATBOT, id: 'bot-inactivo', name: 'Bot Parado', is_active: false }

  it('should_not_label_an_inactive_chatbot_as_edit', async () => {
    renderPage([INACTIVO])
    await waitFor(() => screen.getByText('Bot Parado'))

    expect(screen.queryByRole('button', { name: /^editar$/i })).toBeNull()
  })

  it('should_label_an_inactive_chatbot_as_inactive', async () => {
    renderPage([INACTIVO])
    await waitFor(() => screen.getByText('Bot Parado'))

    expect(screen.getByRole('button', { name: /inactivo/i })).toBeTruthy()
  })

  it('should_keep_labelling_an_active_chatbot_as_active', async () => {
    renderPage([DEMO_CHATBOT])
    await waitFor(() => screen.getByText('Bot Demo'))

    expect(screen.getByRole('button', { name: /^activo$/i })).toBeTruthy()
  })

  it('should_announce_it_as_a_toggle', async () => {
    renderPage([INACTIVO])
    await waitFor(() => screen.getByText('Bot Parado'))

    expect(screen.getByRole('button', { name: /inactivo/i }).getAttribute('aria-pressed')).toBe('false')
  })

  it('should_announce_an_active_one_as_pressed', async () => {
    renderPage([DEMO_CHATBOT])
    await waitFor(() => screen.getByText('Bot Demo'))

    expect(screen.getByRole('button', { name: /^activo$/i }).getAttribute('aria-pressed')).toBe('true')
  })

  it('should_still_activate_an_inactive_chatbot_when_clicked', async () => {
    renderPage([INACTIVO])
    await waitFor(() => screen.getByText('Bot Parado'))

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /inactivo/i }))
    })

    // Un solo argumento: el interruptor no pasa opciones a `mutate`, a diferencia del
    // guardado del formulario. Escribí `expect.anything()` de segundo y el rojo era mío.
    expect(mockUpdateMutate).toHaveBeenCalledWith({
      chatbotId: 'bot-inactivo',
      data: { is_active: true },
    })
  })

  it('should_not_open_the_edit_dialog_when_toggling', async () => {
    /** El clic lleva `stopPropagation` porque la fila entera abre el diálogo. Si se perdiera,
     *  cambiar el estado abriría además el formulario. */
    renderPage([INACTIVO])
    await waitFor(() => screen.getByText('Bot Parado'))

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /inactivo/i }))
    })

    expect(screen.queryByRole('dialog')).toBeNull()
  })
})
