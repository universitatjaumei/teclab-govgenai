import { describe, it, expect, beforeAll, afterEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import i18n from '@/shared/i18n'

const mockSites = vi.hoisted(() => ({ list: [] as object[] }))
const mockFindings = vi.hoisted(() => ({ list: [] as object[] }))

vi.mock('@/shared/api/generated/hub-sites/hub-sites', () => ({
  useListSites: vi.fn(() => ({ data: mockSites.list, isLoading: false })),
}))

vi.mock('@/shared/api/generated/hub-content-quality/hub-content-quality', () => ({
  useListSiteFindings: vi.fn(() => ({ data: mockFindings.list, isLoading: false })),
  useTransitionFinding: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  getListSiteFindingsQueryKey: vi.fn(() => ['listSiteFindings']),
  // La página monta ContentGapsPanel (RAG.14) debajo de los hallazgos de sitio; el mock del
  // módulo es total, así que omitir estos tres rompe la página entera.
  useListContentGaps: vi.fn(() => ({ data: [], isLoading: false })),
  useAnalyzeContentGaps: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  getListContentGapsQueryKey: vi.fn(() => ['listContentGaps']),
}))

vi.mock('@/shared/api/generated/hub-chatbots/hub-chatbots', () => ({
  useOpcionesDeGrafoApiV1HubChatbotsOpcionesDeGrafoGet: () => ({ data: { perfiles: [{ nombre: 'PUBLIC_KB_RICH', configurable: true }], modos: [{ nombre: 'RAG' }, { nombre: 'MD_LONG_CONTEXT' }, { nombre: 'MD_AGENT_SELECTOR' }], estrategias: { retrieval: [], merge: [], template: [], language: [] }, ejes: ['retrieval', 'merge', 'template', 'language'] } }),
  useListChatbotsApiV1HubChatbotsGet: vi.fn(() => ({ data: [], isLoading: false })),
}))

beforeAll(async () => {
  await i18n.changeLanguage('es')
})

afterEach(() => {
  vi.clearAllMocks()
  mockSites.list = []
  mockFindings.list = []
})

const SITE = { id: 'site-001', name: 'Portal Institucional' }

const FINDING = {
  id: 'finding-001',
  site_id: 'site-001',
  finding_type: 'stale',
  severity: 'info',
  status: 'new',
  acciones_permitidas: ['confirmed', 'dismissed'],
  confidence: 1.0,
  source_url: 'https://ej.es/tramites/2020',
  detected_at: '2026-06-06T00:00:00Z',
  reviewed_at: null,
}

function wrap(element: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{element}</MemoryRouter>
    </QueryClientProvider>
  )
}

describe('FindingsPage (curation)', () => {
  it('tabla de hallazgos renderiza badge de severidad correcto', async () => {
    mockSites.list = [SITE]
    mockFindings.list = [FINDING]

    const { FindingsPage } = await import('../FindingsPage')
    render(wrap(<FindingsPage />))

    fireEvent.change(screen.getByRole('combobox', { name: /seleccione un sitio/i }), { target: { value: SITE.id } })

    await waitFor(() => {
      const badges = screen.getAllByText(/^info$/i)
      expect(badges.length).toBeGreaterThan(0)
    })
  })

  it('Confirmar invoca useTransitionFinding', async () => {
    mockSites.list = [SITE]
    mockFindings.list = [FINDING]

    const { useTransitionFinding } = await import('@/shared/api/generated/hub-content-quality/hub-content-quality')
    const mutateFn = vi.fn()
    ;(useTransitionFinding as ReturnType<typeof vi.fn>).mockReturnValue({ mutate: mutateFn, isPending: false })

    const { FindingsPage } = await import('../FindingsPage')
    render(wrap(<FindingsPage />))

    fireEvent.change(screen.getByRole('combobox', { name: /seleccione un sitio/i }), { target: { value: SITE.id } })

    await waitFor(() => {
      expect(screen.getByText(/confirmar/i)).toBeTruthy()
    })
    fireEvent.click(screen.getByText(/confirmar/i))

    expect(mutateFn).toHaveBeenCalledWith({
      siteId: SITE.id,
      findingId: FINDING.id,
      data: { new_status: 'confirmed' },
    })
  })

  it('should_list_corpus_gaps_from_rag14_as_curation_input: monta el panel de huecos de corpus junto a los hallazgos de sitio', async () => {
    mockSites.list = [SITE]
    const { FindingsPage } = await import('../FindingsPage')
    render(wrap(<FindingsPage />))

    // ContentGapsPanel se monta siempre, sin depender de elegir un sitio: los huecos de
    // RAG.14 cuelgan de un chatbot, no de un sitio.
    expect(screen.getByTestId('content-gaps')).toBeInTheDocument()
    expect(screen.getByText(/huecos de corpus/i)).toBeInTheDocument()
  })
})
