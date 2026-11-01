import { describe, it, expect, beforeAll, afterEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import i18n from '@/shared/i18n'

const mockSites = vi.hoisted(() => ({ list: [] as object[] }))

vi.mock('@/shared/api/generated/hub-sites/hub-sites', () => ({
  useListSites: vi.fn(() => ({ data: mockSites.list, isLoading: false })),
  useCreateSite: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useDeleteSite: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useTriggerSiteCrawl: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  // CUR.6 — el formulario de alta ofrece el reconocimiento previo del apartado.
  useReconnoiterSite: vi.fn(() => ({ mutateAsync: vi.fn(), isPending: false })),
  // CUR.7 — la fila del sitio deja cambiar el alcance del análisis semántico.
  usePatchSite: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  getListSitesQueryKey: vi.fn(() => ['listSites']),
}))

// DIN.7 — `SitesPage` resuelve de qué organización es el sitio que se crea (sin ella el
// servidor responde 403). El hook se dobla aquí porque este fichero no prueba esa elección:
// la prueba `ElAltaDeSitioDiceSuOrganizacion` sí, y sin el doble la pantalla lanzaría la
// consulta real de organizaciones.
vi.mock('@/shared/organizacion/useOrganizacionElegida', () => ({
  useOrganizacionElegida: () => ({
    organizaciones: [{ id: 'org-1', name: 'Organización' }],
    elegida: 'org-1',
    elegir: vi.fn(),
    hayVarias: false,
  }),
}))

const TOKEN =
  'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.' +
  btoa(JSON.stringify({ sub: '1', email: 'admin@test.com', role: 'admin', exp: 9999999999 }))
    .replace(/=/g, '').replace(/\+/g, '-').replace(/\//g, '_') +
  '.signature'

beforeAll(async () => {
  await i18n.changeLanguage('es')
  localStorage.setItem('access_token', TOKEN)
})

afterEach(() => {
  vi.clearAllMocks()
  mockSites.list = []
})

const SITE = {
  id: 'site-001',
  name: 'Portal Institucional',
  root_url: 'https://ej.es',
  sitemap_url: null,
  spider_type: 'generic',
  crawl_interval_hours: 24,
  audit_semantic_scope: 'ingested',
  last_crawled_at: null,
  status: 'active',
  created_at: '2026-06-06T00:00:00Z',
  organizacion_id: null,
}

function wrap(element: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{element}</MemoryRouter>
    </QueryClientProvider>
  )
}

describe('SitesPage (curation)', () => {
  it('muestra la lista de sitios', async () => {
    mockSites.list = [SITE]
    const { SitesPage } = await import('../SitesPage')
    render(wrap(<SitesPage />))
    await waitFor(() => {
      expect(screen.getByText('Portal Institucional')).toBeTruthy()
    })
  })

  it('"Rastrear ahora" invoca useTriggerSiteCrawl', async () => {
    const { useTriggerSiteCrawl } = await import('@/shared/api/generated/hub-sites/hub-sites')
    const mutateFn = vi.fn()
    ;(useTriggerSiteCrawl as ReturnType<typeof vi.fn>).mockReturnValue({ mutate: mutateFn, isPending: false })

    mockSites.list = [SITE]
    const { SitesPage } = await import('../SitesPage')
    render(wrap(<SitesPage />))

    const crawlBtn = await screen.findAllByText(/rastrear ahora/i)
    fireEvent.click(crawlBtn[0])

    expect(mutateFn.mock.calls[0][0]).toEqual({ siteId: SITE.id })
  })

  it('muestra formulario al pulsar "Nuevo sitio"', async () => {
    const { SitesPage } = await import('../SitesPage')
    render(wrap(<SitesPage />))

    fireEvent.click(screen.getByText(/nuevo sitio/i))
    await waitFor(() => {
      expect(screen.getByRole('dialog')).toBeTruthy()
    })
  })

  it('no depende de ningún chatbot: no hay selector de chatbot en la pantalla', async () => {
    mockSites.list = [SITE]
    const { SitesPage } = await import('../SitesPage')
    render(wrap(<SitesPage />))
    await waitFor(() => screen.getByText('Portal Institucional'))
    expect(screen.queryByText(/chatbot/i)).not.toBeInTheDocument()
  })

  it('al eliminar un sitio, invalida la lista para que se refresque sola (MAN.1)', async () => {
    // Hallazgo de MAN.1: el DELETE funcionaba en el servidor (204) pero la fila se
    // quedaba en la tabla porque useDeleteSite no invalidaba getListSitesQueryKey al
    // terminar. Sin esto el usuario ve el sitio "borrado" seguir en pantalla hasta
    // que recarga a mano.
    const { useDeleteSite, getListSitesQueryKey } = await import('@/shared/api/generated/hub-sites/hub-sites')
    let onSuccess: (() => void) | undefined
    ;(useDeleteSite as ReturnType<typeof vi.fn>).mockImplementation((opts?: { mutation?: { onSuccess?: () => void } }) => {
      onSuccess = opts?.mutation?.onSuccess
      return { mutate: vi.fn(), isPending: false }
    })

    mockSites.list = [SITE]
    const { SitesPage } = await import('../SitesPage')
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const invalidateSpy = vi.spyOn(qc, 'invalidateQueries')
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter><SitesPage /></MemoryRouter>
      </QueryClientProvider>,
    )
    await waitFor(() => screen.getByText('Portal Institucional'))

    expect(onSuccess).toBeTypeOf('function')
    onSuccess!()

    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: getListSitesQueryKey() })
  })
})

describe('#357 — «Rastrear ahora» dice que ha empezado', () => {
  async function pulsar(mutateFn = vi.fn(), extra: object = {}) {
    const { useTriggerSiteCrawl } = await import('@/shared/api/generated/hub-sites/hub-sites')
    ;(useTriggerSiteCrawl as ReturnType<typeof vi.fn>).mockReturnValue({ mutate: mutateFn, isPending: false, ...extra })
    mockSites.list = [SITE]
    const { SitesPage } = await import('../SitesPage')
    render(wrap(<SitesPage />))
    fireEvent.click((await screen.findAllByRole('button', { name: /rastrear ahora/i }))[0])
    return mutateFn.mock.calls[0]?.[1] as { onSuccess: () => void; onError: (e: Error) => void } | undefined
  }

  it('avisa de que el rastreo ha empezado y de dónde se verá', async () => {
    const opciones = await pulsar()
    act(() => opciones!.onSuccess())

    const aviso = await screen.findByRole('status')
    expect(aviso.textContent).toMatch(/ha empezado/i)
    expect(aviso.textContent).toMatch(/último rastreo/i)
  })

  it('dice el error si no se ha podido lanzar', async () => {
    const opciones = await pulsar()
    act(() => opciones!.onError(new Error('El servidor no responde')))

    expect((await screen.findByRole('alert')).textContent).toMatch(/el servidor no responde/i)
  })

  it('no deja pulsarlo otra vez mientras se envía', async () => {
    const { useTriggerSiteCrawl } = await import('@/shared/api/generated/hub-sites/hub-sites')
    ;(useTriggerSiteCrawl as ReturnType<typeof vi.fn>).mockReturnValue({
      mutate: vi.fn(),
      isPending: true,
      variables: { siteId: SITE.id },
    })
    mockSites.list = [SITE]
    const { SitesPage } = await import('../SitesPage')
    render(wrap(<SitesPage />))

    const boton = (await screen.findAllByRole('button', { name: /rastrear ahora/i }))[0]
    expect(boton).toBeDisabled()
  })
})
