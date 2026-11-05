import { describe, it, expect, beforeAll, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, waitFor, act, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import i18n from '@/shared/i18n'
import { AuthProvider } from '@/shared/auth'
import { LLMConfigsPage } from '../LLMConfigsPage'
import {
  useListLlmConfigsApiV1HubLlmConfigsGet,
  useListProvidersApiV1HubLlmConfigsProvidersGet,
  useListAvailableModelsApiV1HubLlmConfigsAvailableModelsProviderIdGet,
  useCreateLlmConfigApiV1HubLlmConfigsPost,
  useUpdateLlmConfigApiV1HubLlmConfigsConfigIdPatch,
  useDeleteLlmConfigApiV1HubLlmConfigsConfigIdDelete,
  useCreateProviderApiV1HubLlmConfigsProvidersPost,
  useUpdateProviderApiV1HubLlmConfigsProvidersProviderIdPatch,
  useDeleteProviderApiV1HubLlmConfigsProvidersProviderIdDelete,
  testLlmConnectionApiV1HubLlmConfigsConfigIdTestPost,
} from '@/shared/api/generated/hub-llm-configs/hub-llm-configs'

// Desde CAL.2 la pantalla consume los hooks generados: axios no pasa por `fetch`,
// así que un stub global de `fetch` ya no intercepta nada.
vi.mock('@/shared/api/generated/hub-llm-configs/hub-llm-configs', () => ({
  useListLlmConfigsApiV1HubLlmConfigsGet: vi.fn(),
  useListProvidersApiV1HubLlmConfigsProvidersGet: vi.fn(),
  useListAvailableModelsApiV1HubLlmConfigsAvailableModelsProviderIdGet: vi.fn(),
  useCreateLlmConfigApiV1HubLlmConfigsPost: vi.fn(),
  useUpdateLlmConfigApiV1HubLlmConfigsConfigIdPatch: vi.fn(),
  useDeleteLlmConfigApiV1HubLlmConfigsConfigIdDelete: vi.fn(),
  useCreateProviderApiV1HubLlmConfigsProvidersPost: vi.fn(),
  useUpdateProviderApiV1HubLlmConfigsProvidersProviderIdPatch: vi.fn(),
  useDeleteProviderApiV1HubLlmConfigsProvidersProviderIdDelete: vi.fn(),
  testLlmConnectionApiV1HubLlmConfigsConfigIdTestPost: vi.fn(),
  getListLlmConfigsApiV1HubLlmConfigsGetQueryKey: vi.fn(() => ['/api/v1/hub/llm-configs']),
  getListProvidersApiV1HubLlmConfigsProvidersGetQueryKey: vi.fn(() => ['/api/v1/hub/llm-configs/providers']),
}))

const TOKEN = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.' +
  btoa(JSON.stringify({ sub: '1', email: 'admin@test.com', role: 'admin', exp: 9999999999 }))
    .replace(/=/g, '').replace(/\+/g, '-').replace(/\//g, '_') +
  '.signature'

beforeAll(async () => {
  await i18n.changeLanguage('es')
  localStorage.setItem('access_token', TOKEN)
})

const deleteConfigMutate = vi.fn()
const mutationDouble = (mutate = vi.fn()) => ({ mutate, isPending: false }) as any

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(useListProvidersApiV1HubLlmConfigsProvidersGet).mockReturnValue({ data: [], isLoading: false } as any)
  vi.mocked(useListAvailableModelsApiV1HubLlmConfigsAvailableModelsProviderIdGet).mockReturnValue({ data: undefined } as any)
  vi.mocked(useCreateLlmConfigApiV1HubLlmConfigsPost).mockReturnValue(mutationDouble())
  vi.mocked(useUpdateLlmConfigApiV1HubLlmConfigsConfigIdPatch).mockReturnValue(mutationDouble())
  vi.mocked(useCreateProviderApiV1HubLlmConfigsProvidersPost).mockReturnValue(mutationDouble())
  vi.mocked(useUpdateProviderApiV1HubLlmConfigsProvidersProviderIdPatch).mockReturnValue(mutationDouble())
  vi.mocked(useDeleteProviderApiV1HubLlmConfigsProvidersProviderIdDelete).mockReturnValue(mutationDouble())
  vi.mocked(useDeleteLlmConfigApiV1HubLlmConfigsConfigIdDelete).mockReturnValue(mutationDouble(deleteConfigMutate))
})

afterEach(() => { vi.unstubAllGlobals() })

const DEMO_CONFIG = {
  id: 'cfg-0001-0000-0000-000000000001',
  provider: 'google',
  model_name: 'gemini-2.0-flash',
  temperature: 0.7,
  max_tokens: 2048,
  api_key_secret_name: 'GOOGLE_API_KEY',
  tier: 1,
  label: 'Gemini Flash',
  is_default: true,
}

function renderPage(configs: object[] = []) {
  vi.mocked(useListLlmConfigsApiV1HubLlmConfigsGet).mockReturnValue({
    data: configs,
    isLoading: false,
  } as any)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <AuthProvider>
          <LLMConfigsPage />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>
  )
}

describe('LLMConfigsPage', () => {
  it('should_list_llm_configs_with_tier_chips', async () => {
    renderPage([DEMO_CONFIG])
    await waitFor(() => {
      expect(screen.getByText('Gemini Flash')).toBeDefined()
      expect(screen.getByText('Tier 1')).toBeDefined()
    })
  })

  it('should_open_create_form', async () => {
    renderPage([])
    await waitFor(() => screen.getByRole('button', { name: /nueva config/i }))
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /nueva config/i }))
    })
    expect(screen.getByRole('dialog')).toBeDefined()
  })

  it('should_show_latency_badge_after_test_connection', async () => {
    vi.mocked(testLlmConnectionApiV1HubLlmConfigsConfigIdTestPost).mockResolvedValue({
      ok: true,
      latency_ms: 342,
    })
    renderPage([DEMO_CONFIG])

    await waitFor(() => screen.getByRole('button', { name: /probar/i }))
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /probar/i }))
    })
    await waitFor(() => {
      expect(screen.getByTestId(`test-ok-${DEMO_CONFIG.id}`).textContent).toContain('342 ms')
    })
  })

  it('should_show_affected_chatbots_before_delete', async () => {
    // El motivo del 409 llega en `detail`; el interceptor de `client.ts` lo pasa a
    // `error.message`, que es lo que la pantalla pinta. Aquí se dobla ese contrato.
    const DETALLE = 'No se puede eliminar: hay chatbots usando esta configuración'
    vi.mocked(useDeleteLlmConfigApiV1HubLlmConfigsConfigIdDelete).mockImplementation(
      ((options?: any) => ({
        mutate: () => options?.mutation?.onError?.(new Error(DETALLE)),
        isPending: false,
      })) as any,
    )
    renderPage([DEMO_CONFIG])

    await waitFor(() => {
      expect(screen.getAllByRole('button', { name: /eliminar/i }).length).toBeGreaterThan(0)
    })
    await act(async () => {
      const deleteButtons = screen.getAllByRole('button', { name: /eliminar/i })
      fireEvent.click(deleteButtons[deleteButtons.length - 1])
    })
    await waitFor(() => screen.getByRole('dialog'))
    await act(async () => {
      const btns = screen.getAllByRole('button', { name: /eliminar/i })
      fireEvent.click(btns[btns.length - 1])
    })
    await waitFor(() => {
      expect(screen.getByTestId('delete-error').textContent).toContain('chatbots')
    })
  })
})

describe('Revisión de la PR #356 — los decimales del modelo no bloquean el guardado', () => {
  // Mismo defecto que #351: con `step="0.1"`, un top_p de 0,95 —habitual, y el servidor lo
  // acepta— era inválido para el navegador, que bloqueaba el envío sin ninguna petición.
  it('should_accept_values_that_are_not_multiples_of_0_1', async () => {
    renderPage([{ ...DEMO_CONFIG, temperature: 0.25, top_p: 0.95 }])
    await waitFor(() => screen.getByText('Gemini Flash'))
    await act(async () => {
      fireEvent.click(screen.getByText('Gemini Flash'))
    })

    const temperatura = document.getElementById('llm-temperature') as HTMLInputElement
    const topP = document.getElementById('llm-top-p') as HTMLInputElement
    expect(topP).toHaveValue(0.95)
    expect(temperatura.checkValidity()).toBe(true)
    expect(topP.checkValidity()).toBe(true)
  })
})

describe('#372 — el panel sabe editar un proveedor Vertex y su región', () => {
  const VERTEX_GLOBAL = {
    id: 'vertex-global',
    name: 'Google Vertex AI (global, fuera de la UE)',
    provider_type: 'google_vertexai',
    base_url: null,
    location: 'global',
  }

  function conProveedores(providers: object[]) {
    vi.mocked(useListProvidersApiV1HubLlmConfigsProvidersGet).mockReturnValue({ data: providers, isLoading: false } as any)
  }

  it('should_keep_the_vertex_type_and_region_when_saving_a_provider', async () => {
    // Antes el `<select>` no tenía `google_vertexai`: al editar se perdía el tipo, y guardar
    // podía convertir el proveedor en `openai_compatible` y romper todos sus modelos.
    const updateMutate = vi.fn()
    vi.mocked(useUpdateProviderApiV1HubLlmConfigsProvidersProviderIdPatch).mockReturnValue(mutationDouble(updateMutate))
    conProveedores([VERTEX_GLOBAL])
    renderPage([])

    await waitFor(() => screen.getByText(VERTEX_GLOBAL.name))
    await act(async () => { fireEvent.click(screen.getByText(VERTEX_GLOBAL.name)) })

    expect(document.getElementById('provider-type')).toHaveValue('google_vertexai')
    expect(document.getElementById('provider-location')).toHaveValue('global')

    await act(async () => { fireEvent.click(screen.getByRole('button', { name: /guardar/i })) })
    await waitFor(() => expect(updateMutate).toHaveBeenCalled())
    const { data } = updateMutate.mock.calls[0][0]
    expect(data.provider_type).toBe('google_vertexai')
    expect(data.location).toBe('global')
  })

  it('should_offer_every_provider_type_the_server_uses', async () => {
    // El mismo defecto con el reranker: `discovery_engine` tampoco tenía opción, y guardarlo
    // desde el panel le cambiaba el tipo.
    conProveedores([{ ...VERTEX_GLOBAL, id: 'vertex-ranking', name: 'Vertex AI Ranking', provider_type: 'discovery_engine', location: null }])
    renderPage([])
    await waitFor(() => screen.getByText('Vertex AI Ranking'))
    await act(async () => { fireEvent.click(screen.getByText('Vertex AI Ranking')) })
    expect(document.getElementById('provider-type')).toHaveValue('discovery_engine')
  })

  it('should_show_the_region_of_each_provider', async () => {
    conProveedores([VERTEX_GLOBAL])
    renderPage([])
    await waitFor(() => expect(screen.getByTestId('provider-location-vertex-global').textContent).toBe('global'))
  })

  it('should_clear_the_key_variable_when_an_existing_model_moves_to_vertex', async () => {
    // Al editar no se pisa la variable elegida, salvo al pasar a Vertex: allí no se usa, y
    // dejar GOOGLE_API_KEY haría creer que el modelo sigue colgando de la clave de AI Studio.
    const updateMutate = vi.fn()
    vi.mocked(useUpdateLlmConfigApiV1HubLlmConfigsConfigIdPatch).mockReturnValue(mutationDouble(updateMutate))
    conProveedores([{ id: 'google', name: 'Google', provider_type: 'google_genai', base_url: null, location: null }, VERTEX_GLOBAL])
    renderPage([DEMO_CONFIG])
    await waitFor(() => screen.getByText('Gemini Flash'))
    await act(async () => { fireEvent.click(screen.getByText('Gemini Flash')) })
    expect(document.getElementById('llm-api-key')).toHaveValue('GOOGLE_API_KEY')

    await act(async () => {
      fireEvent.change(document.getElementById('llm-provider')!, { target: { value: 'vertex-global' } })
    })
    expect(document.getElementById('llm-api-key')).toHaveValue('')

    await act(async () => { fireEvent.click(screen.getByRole('button', { name: /guardar/i })) })
    await waitFor(() => expect(updateMutate).toHaveBeenCalled())
    expect(updateMutate.mock.calls[0][0].data.provider).toBe('vertex-global')
  })

  it('should_not_suggest_an_ai_studio_key_for_a_vertex_model', async () => {
    // El nombre contiene «Google», y la sugerencia buscaba por nombre: un modelo de Vertex
    // recibía GOOGLE_API_KEY, que no usa.
    conProveedores([VERTEX_GLOBAL])
    renderPage([{ ...DEMO_CONFIG, provider: 'vertex-global', api_key_secret_name: null }])
    await waitFor(() => screen.getByText('Gemini Flash'))
    await act(async () => { fireEvent.click(screen.getByText('Gemini Flash')) })

    expect(document.getElementById('llm-api-key')).toHaveValue('')
  })
})

describe('Revisión de la PR #373 — el servidor dice qué tipos hay', () => {
  function conProveedores(providers: object[]) {
    vi.mocked(useListProvidersApiV1HubLlmConfigsProvidersGet).mockReturnValue({ data: providers, isLoading: false } as any)
  }

  it('should_offer_exactly_the_provider_types_of_the_contract', async () => {
    // La lista escrita a mano perdía tipos —`local` seguía faltando— y cada uno que faltaba
    // se reescribía al guardar. Ahora sale del enum que genera Orval.
    const { HubProviderCreateProviderType } = await import('@/shared/api/generated/model')
    conProveedores([{ id: 'bge', name: 'BGE local', provider_type: 'local', base_url: null, location: null }])
    renderPage([])
    await waitFor(() => screen.getByText('BGE local'))
    await act(async () => { fireEvent.click(screen.getByText('BGE local')) })

    const select = document.getElementById('provider-type') as HTMLSelectElement
    expect([...select.options].map(o => o.value).sort()).toEqual(Object.values(HubProviderCreateProviderType).sort())
    expect(select).toHaveValue('local')
  })

  it('should_show_the_region_only_for_vertex', async () => {
    // El reranker usa una región fija: dejar editarla allí haría que el panel mintiera sobre
    // dónde se tratan los datos.
    conProveedores([{ id: 'vertex-ranking', name: 'Vertex AI Ranking', provider_type: 'discovery_engine', base_url: null, location: null }])
    renderPage([])
    await waitFor(() => screen.getByText('Vertex AI Ranking'))
    await act(async () => { fireEvent.click(screen.getByText('Vertex AI Ranking')) })
    expect(document.getElementById('provider-location')).toBeNull()

    await act(async () => {
      fireEvent.change(document.getElementById('provider-type')!, { target: { value: 'google_vertexai' } })
    })
    expect(document.getElementById('provider-location')).not.toBeNull()
  })
})
