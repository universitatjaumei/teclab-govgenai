import { describe, it, expect, beforeAll, afterEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import i18n from '@/shared/i18n'

const mockSites = vi.hoisted(() => ({ list: [] as object[] }))
const mockCandidates = vi.hoisted(() => ({ list: [] as object[] }))

vi.mock('@/shared/api/generated/hub-sites/hub-sites', () => ({
  useListSites: vi.fn(() => ({ data: mockSites.list, isLoading: false })),
  useListSelections: vi.fn(() => ({ data: [], isLoading: false })),
  useCreateSelection: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useDeleteSelection: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useListCandidates: vi.fn(() => ({ data: mockCandidates.list, isLoading: false })),
  useIngestPage: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  getListSelectionsQueryKey: vi.fn(() => ['listSelections']),
  // CUR.4 — la pantalla monta el visor del texto guardado, que lo usa para decidir si una
  // candidata merece publicarse. Sin este export el módulo doblado no resuelve el import.
  useGetPageContent: vi.fn(() => ({ data: undefined, isLoading: false })),
}))

const mockChatbots = vi.hoisted(() => ({ list: [] as object[] }))

vi.mock('@/shared/api/generated/hub-chatbots/hub-chatbots', () => ({
  useOpcionesDeGrafoApiV1HubChatbotsOpcionesDeGrafoGet: () => ({ data: { perfiles: [{ nombre: 'PUBLIC_KB_RICH', configurable: true }], modos: [{ nombre: 'RAG' }, { nombre: 'MD_LONG_CONTEXT' }, { nombre: 'MD_AGENT_SELECTOR' }], estrategias: { retrieval: [], merge: [], template: [], language: [] }, ejes: ['retrieval', 'merge', 'template', 'language'] } }),
  useListChatbotsApiV1HubChatbotsGet: vi.fn(() => ({ data: mockChatbots.list })),
}))

beforeAll(async () => {
  await i18n.changeLanguage('es')
})

afterEach(() => {
  vi.clearAllMocks()
  mockSites.list = []
  mockCandidates.list = []
  mockChatbots.list = []
})

const SITE = { id: 'site-001', name: 'Portal Institucional' }
const CHATBOT = { id: 'bot-001', name: 'Asistente normativo' }

const CANDIDATE_A = { page_id: 'page-a', url: 'https://ej.es/a', matched_rule: null, is_new: true }
const CANDIDATE_B = { page_id: 'page-b', url: 'https://ej.es/b', matched_rule: '/tramites', is_new: false }

function wrap(element: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{element}</MemoryRouter>
    </QueryClientProvider>
  )
}

function elegirSitioYChatbot() {
  fireEvent.change(screen.getByRole('combobox', { name: /seleccione un sitio/i }), { target: { value: SITE.id } })
  fireEvent.change(screen.getByRole('combobox', { name: /chatbot destino/i }), { target: { value: CHATBOT.id } })
}

describe('PublicationPage (curation)', () => {
  it('requiere sitio y chatbot antes de mostrar candidatas', async () => {
    mockSites.list = [SITE]
    mockChatbots.list = [CHATBOT]
    mockCandidates.list = [CANDIDATE_A]

    const { PublicationPage } = await import('../PublicationPage')
    render(wrap(<PublicationPage />))

    expect(screen.queryByText('https://ej.es/a')).not.toBeInTheDocument()

    elegirSitioYChatbot()

    await waitFor(() => {
      expect(screen.getByText('https://ej.es/a')).toBeInTheDocument()
    })
  })

  it('should_require_explicit_publish_action_per_page: cada candidata se ingiere con su propio botón, sin acción masiva', async () => {
    mockSites.list = [SITE]
    mockChatbots.list = [CHATBOT]
    mockCandidates.list = [CANDIDATE_A, CANDIDATE_B]

    const { useIngestPage } = await import('@/shared/api/generated/hub-sites/hub-sites')
    const mutateFn = vi.fn()
    ;(useIngestPage as ReturnType<typeof vi.fn>).mockReturnValue({ mutate: mutateFn, isPending: false })

    const { PublicationPage } = await import('../PublicationPage')
    render(wrap(<PublicationPage />))
    elegirSitioYChatbot()

    await waitFor(() => screen.getByText('https://ej.es/a'))

    // No existe ningún botón de "ingerir todo": tantos botones "Ingerir" como candidatas.
    expect(screen.queryByText(/ingerir todo/i)).not.toBeInTheDocument()
    const botones = screen.getAllByText(/^ingerir$/i)
    expect(botones).toHaveLength(2)

    // El segundo argumento es el `onSuccess` que refresca la tabla (CUR.8).
    fireEvent.click(botones[0])
    expect(mutateFn).toHaveBeenCalledTimes(1)
    expect(mutateFn).toHaveBeenCalledWith(
      { chatbotId: CHATBOT.id, pageId: CANDIDATE_A.page_id },
      expect.objectContaining({ onSuccess: expect.any(Function) }),
    )

    fireEvent.click(botones[1])
    expect(mutateFn).toHaveBeenCalledTimes(2)
    expect(mutateFn).toHaveBeenLastCalledWith(
      { chatbotId: CHATBOT.id, pageId: CANDIDATE_B.page_id },
      expect.objectContaining({ onSuccess: expect.any(Function) }),
    )
  })

  it('crea una nueva selección de corpus', async () => {
    mockSites.list = [SITE]
    mockChatbots.list = [CHATBOT]

    const { useCreateSelection } = await import('@/shared/api/generated/hub-sites/hub-sites')
    const mutateFn = vi.fn()
    ;(useCreateSelection as ReturnType<typeof vi.fn>).mockReturnValue({ mutate: mutateFn, isPending: false })

    const { PublicationPage } = await import('../PublicationPage')
    render(wrap(<PublicationPage />))
    elegirSitioYChatbot()

    fireEvent.click(await screen.findByText(/nueva selección/i))
    expect(screen.getByRole('dialog')).toBeTruthy()

    fireEvent.click(screen.getByText(/^guardar$/i))

    await waitFor(() => {
      expect(mutateFn).toHaveBeenCalled()
    })
    expect(mutateFn).toHaveBeenCalledWith({
      chatbotId: CHATBOT.id,
      data: {
        site_id: SITE.id,
        rule_type: 'path_prefix',
        rule_value: '',
        auto_ingest_new: true,
      },
    })
  })
})

describe('PublicationPage: una página de navegación no se publica (#345)', () => {
  it('su botón y su casilla están desactivados y la fila dice por qué, como dice el servidor', async () => {
    mockSites.list = [SITE]
    mockChatbots.list = [CHATBOT]
    mockCandidates.list = [{ ...CANDIDATE_A, de_navegacion: true }, CANDIDATE_B]

    const { PublicationPage } = await import('../PublicationPage')
    render(wrap(<PublicationPage />))
    elegirSitioYChatbot()

    await waitFor(() => screen.getByText('https://ej.es/a'))
    const botones = screen.getAllByText(/^ingerir$/i)
    expect(botones[0]).toBeDisabled()
    expect(botones[1]).toBeEnabled()
    const fila = screen.getByText('https://ej.es/a').closest('tr') as HTMLElement
    expect(fila.querySelector('input[type="checkbox"]')).toBeDisabled()
    expect(fila.textContent).toMatch(/navegaci/i)
  })
})
