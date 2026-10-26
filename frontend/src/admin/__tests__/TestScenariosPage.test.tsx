import { describe, it, expect, beforeAll, afterEach, vi } from 'vitest'
import { render, screen, waitFor, fireEvent, act } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import i18n from '@/shared/i18n'
import { AuthProvider } from '@/shared/auth'
import type { ChatbotRead, RunRead, ScenarioRead } from '@/shared/api/generated/model'
import { TestScenariosPage } from '../pages/TestScenariosPage'

/**
 * Tests RAG.13 — la página se construye desde el contrato, no desde campos inventados.
 *
 * Por eso los dobles devuelven objetos tipados `ScenarioRead` / `RunRead`: si el backend
 * cambia el contrato, esto deja de compilar, que es exactamente lo que debe pasar. Un
 * doble con `any` convertiría un cambio de contrato en un fallo silencioso en producción.
 */

const { mockRun, mockVerdict, mockData, opcionesRun } = vi.hoisted(() => ({
  mockRun: vi.fn(),
  mockVerdict: vi.fn(),
  // FIX.1: se guardan las opciones con que se registra la mutación para poder disparar su
  // `onError` desde el test. Sin esto no hay forma de comprobar que un fallo se ve, que es
  // justo lo que faltaba: el 500 dejaba la pantalla idéntica.
  opcionesRun: { actual: null as { mutation?: { onError?: (e: unknown) => void } } | null },
  mockData: {
    chatbots: [] as ChatbotRead[],
    scenarios: [] as ScenarioRead[],
    runs: [] as RunRead[],
  },
}))

vi.mock('@/shared/api/generated/hub-test-scenarios/hub-test-scenarios', () => ({
  useListScenariosApiV1HubChatbotsChatbotIdTestScenariosGet: vi.fn(() => ({
    data: mockData.scenarios,
    isLoading: false,
  })),
  useListRunsApiV1HubChatbotsChatbotIdTestScenariosScenarioIdRunsGet: vi.fn(() => ({
    data: mockData.runs,
    isLoading: false,
  })),
  useCreateScenarioApiV1HubChatbotsChatbotIdTestScenariosPost: vi.fn(() => ({
    mutate: vi.fn(),
    isPending: false,
  })),
  useUpdateScenarioApiV1HubChatbotsChatbotIdTestScenariosScenarioIdPatch: vi.fn(() => ({
    mutate: vi.fn(),
    isPending: false,
  })),
  useDeleteScenarioApiV1HubChatbotsChatbotIdTestScenariosScenarioIdDelete: vi.fn(() => ({
    mutate: vi.fn(),
    isPending: false,
  })),
  useRunScenarioApiV1HubChatbotsChatbotIdTestScenariosScenarioIdRunPost: vi.fn((opciones) => {
    opcionesRun.actual = opciones
    return { mutate: mockRun, isPending: false }
  }),
  useSetVerdictApiV1HubChatbotsChatbotIdTestScenariosRunsRunIdVerdictPatch: vi.fn(() => ({
    mutate: mockVerdict,
    isPending: false,
  })),
  getListScenariosApiV1HubChatbotsChatbotIdTestScenariosGetQueryKey: vi.fn(() => ['s']),
  getListRunsApiV1HubChatbotsChatbotIdTestScenariosScenarioIdRunsGetQueryKey: vi.fn(() => ['r']),
}))

vi.mock('@/shared/api/generated/hub-chatbots/hub-chatbots', () => ({
  useOpcionesDeGrafoApiV1HubChatbotsOpcionesDeGrafoGet: () => ({ data: { perfiles: [{ nombre: 'PUBLIC_KB_RICH', configurable: true }], modos: [{ nombre: 'RAG' }, { nombre: 'MD_LONG_CONTEXT' }, { nombre: 'MD_AGENT_SELECTOR' }], estrategias: { retrieval: [], merge: [], template: [], language: [] }, ejes: ['retrieval', 'merge', 'template', 'language'] } }),
  useListChatbotsApiV1HubChatbotsGet: vi.fn(() => ({
    data: mockData.chatbots,
    isLoading: false,
  })),
}))

const CHATBOT_ID = '00000000-0000-0000-0000-000000000100'
const SCENARIO_ID = '00000000-0000-0000-0000-000000000200'
const RUN_ID = '00000000-0000-0000-0000-000000000300'

const TOKEN =
  'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.' +
  btoa(JSON.stringify({ sub: '1', email: 'admin@test.com', role: 'admin', exp: 9999999999 }))
    .replace(/=/g, '')
    .replace(/\+/g, '-')
    .replace(/\//g, '_') +
  '.signature'

function unChatbot(): ChatbotRead {
  return {
    id: CHATBOT_ID,
    puede_ser_hijo: true,
    name: 'Assistent normatiu',
    organizacion_id: '00000000-0000-0000-0000-000000000010',
    llm_config_id: '00000000-0000-0000-0000-000000000001',
    system_prompt: 'Ets un assistent.',
    sources: [],
    is_active: true,
    retrieval_mode: 'RAG',
    retrieval_top_k: 8,
    use_prompt_caching: false,
    cache_ttl: 3600,
    kind: 'atomic',
    parent_chatbot_id: null,
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
    min_retrieval_score: 0,
    reranker_enabled: false,
    answer_template: 'generic',
    context_token_budget: null,
    chunk_size: null,
    chunk_overlap: null,
    chunking_strategy: null,
    query_rewriting_enabled: null,
    created_at: '2026-08-01T00:00:00Z',
    updated_at: '2026-08-01T00:00:00Z',
  }
}

function unEscenario(): ScenarioRead {
  return {
    id: SCENARIO_ID,
    chatbot_id: CHATBOT_ID,
    name: 'Dieta a Madrid',
    prompt: 'quant cobro de dieta per anar a Madrid?',
    history: null,
    expectation_note: 'Debe citar REG-020.',
    created_by: 'admin@uji.es',
    created_at: '2026-08-01T00:00:00Z',
    updated_at: '2026-08-01T00:00:00Z',
  }
}

function unRun(overrides: Partial<RunRead> = {}): RunRead {
  return {
    id: RUN_ID,
    scenario_id: SCENARIO_ID,
    executed_at: '2026-08-01T10:00:00Z',
    answer: "L'import de la dieta és de 53,34 euros.",
    sources: [
      {
        document_id: '00000000-0000-0000-0000-000000000400',
        title: 'Reglament indemnitzacions',
        url: 'https://www.uji.es/REG-020',
        score: 0.91,
      },
    ],
    bypass_snapshot: null,
    verdict: null,
    verdict_note: null,
    verdict_by: null,
    ...overrides,
  }
}

beforeAll(async () => {
  await i18n.changeLanguage('es')
  localStorage.setItem('access_token', TOKEN)
})

afterEach(() => {
  vi.clearAllMocks()
  mockData.chatbots = []
  mockData.scenarios = []
  mockData.runs = []
})

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <AuthProvider>
          <TestScenariosPage />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>
  )
}

describe('TestScenariosPage', () => {
  it('renderiza los escenarios que llegan del contrato', async () => {
    mockData.chatbots = [unChatbot()]
    mockData.scenarios = [unEscenario()]

    renderPage()

    await waitFor(() => {
      expect(screen.getByText('Dieta a Madrid')).toBeInTheDocument()
    })
    expect(
      screen.getByText('quant cobro de dieta per anar a Madrid?')
    ).toBeInTheDocument()
    expect(screen.getByText(/Debe citar REG-020/)).toBeInTheDocument()
  })

  it('ejecuta un escenario y muestra la respuesta con sus fuentes', async () => {
    mockData.chatbots = [unChatbot()]
    mockData.scenarios = [unEscenario()]
    mockData.runs = [unRun()]

    renderPage()

    await waitFor(() => {
      expect(screen.getByText('Dieta a Madrid')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByTestId(`run-${SCENARIO_ID}`))
    expect(mockRun).toHaveBeenCalled()

    expect(screen.getByText(/53,34 euros/)).toBeInTheDocument()
    const fuente = screen.getByText('Reglament indemnitzacions')
    expect(fuente).toHaveAttribute('href', 'https://www.uji.es/REG-020')
  })

  it('envía el veredicto humano', async () => {
    mockData.chatbots = [unChatbot()]
    mockData.scenarios = [unEscenario()]
    mockData.runs = [unRun()]

    renderPage()

    await waitFor(() => {
      expect(screen.getByTestId(`verdict-good-${RUN_ID}`)).toBeInTheDocument()
    })

    fireEvent.click(screen.getByTestId(`verdict-good-${RUN_ID}`))

    expect(mockVerdict).toHaveBeenCalledWith(
      expect.objectContaining({
        runId: RUN_ID,
        data: expect.objectContaining({ verdict: 'good' }),
      }),
      expect.anything()
    )
  })

  it('no muestra el contexto capturado si el run no lo trae', async () => {
    mockData.chatbots = [unChatbot()]
    mockData.scenarios = [unEscenario()]
    mockData.runs = [unRun()]

    renderPage()

    await waitFor(() => {
      expect(screen.getByText(/53,34 euros/)).toBeInTheDocument()
    })
    expect(screen.queryByTestId(`context-${RUN_ID}`)).not.toBeInTheDocument()
  })

  it('muestra el contexto capturado cuando el run lo trae', async () => {
    mockData.chatbots = [unChatbot()]
    mockData.scenarios = [unEscenario()]
    mockData.runs = [
      unRun({
        bypass_snapshot: {
          system_prompt: 'SYSTEM del chatbot',
          quality_gate: { score: 0.82, passed: true },
        },
      }),
    ]

    renderPage()

    await waitFor(() => {
      expect(screen.getByTestId(`context-${RUN_ID}`)).toBeInTheDocument()
    })
  })

  it('no deja ninguna cadena de interfaz sin traducir', async () => {
    mockData.chatbots = [unChatbot()]
    mockData.scenarios = []

    renderPage()

    // Una clave sin traducción se renderiza como la propia clave: 'hub.test_scenarios.x'.
    await waitFor(() => {
      expect(screen.queryByText(/hub\.test_scenarios\./)).not.toBeInTheDocument()
    })
  })
})

describe('TestScenariosPage — FIX.1: los fallos se ven y los escenarios se editan', () => {
  it('should_show_an_error_when_the_run_fails', async () => {
    mockData.chatbots = [unChatbot()]
    mockData.scenarios = [unEscenario()]
    renderPage()

    await screen.findByTestId(`run-${SCENARIO_ID}`)
    // El backend devuelve 500 cuando el modelo del chatbot no responde. Antes de FIX.1 eso
    // no producía ningún cambio observable en la pantalla.
    act(() => {
      opcionesRun.actual?.mutation?.onError?.(new Error('Request failed with status code 500'))
    })

    const aviso = await screen.findByRole('alert')
    expect(aviso.textContent).toContain('500')
  })

  it('should_edit_an_existing_scenario', async () => {
    mockData.chatbots = [unChatbot()]
    mockData.scenarios = [unEscenario()]
    renderPage()

    fireEvent.click(await screen.findByTestId(`edit-${SCENARIO_ID}`))

    // El PATCH existía desde RAG.13 y no lo usaba nadie: se creaba un escenario y ya no se
    // podía corregir. El formulario debe abrirse relleno con lo que hay.
    await waitFor(() => {
      expect(screen.getByDisplayValue('Dieta a Madrid')).toBeInTheDocument()
    })
  })
})
