import { describe, it, expect, beforeAll, afterEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor, act, within } from '@testing-library/react'
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
  // #358 — la confirmación de borrado dice cuántas páginas se pierden.
  useListSitePages: vi.fn(() => ({ data: [{ id: 'p1' }, { id: 'p2' }, { id: 'p3' }], isLoading: false })),
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
    const mutateAsync = vi.fn(() => Promise.resolve({}))
    ;(useTriggerSiteCrawl as ReturnType<typeof vi.fn>).mockReturnValue({ mutateAsync, isPending: false })

    mockSites.list = [SITE]
    const { SitesPage } = await import('../SitesPage')
    render(wrap(<SitesPage />))

    const crawlBtn = await screen.findAllByText(/rastrear ahora/i)
    fireEvent.click(crawlBtn[0])

    expect(mutateAsync).toHaveBeenCalledWith({ siteId: SITE.id })
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

describe('#357 — «Rastrear ahora» dice que ha empezado y cuándo ha terminado', () => {
  // El doble se restablece al acabar cada test: `mockReturnValue` persiste entre tests y el
  // resultado dependía del orden (revisión de la PR #359).
  afterEach(async () => {
    const { useTriggerSiteCrawl } = await import('@/shared/api/generated/hub-sites/hub-sites')
    ;(useTriggerSiteCrawl as ReturnType<typeof vi.fn>).mockImplementation(() => ({
      mutateAsync: vi.fn(() => Promise.resolve({})),
      isPending: false,
    }))
  })

  async function pulsar(resultado: () => Promise<unknown>, sitio: object = SITE) {
    const { useTriggerSiteCrawl } = await import('@/shared/api/generated/hub-sites/hub-sites')
    const mutateAsync = vi.fn(resultado)
    ;(useTriggerSiteCrawl as ReturnType<typeof vi.fn>).mockReturnValue({ mutateAsync, isPending: false })
    mockSites.list = [sitio]
    const { SitesPage } = await import('../SitesPage')
    const vista = render(wrap(<SitesPage />))
    const boton = (await screen.findAllByRole('button', { name: /rastrear ahora/i }))[0]
    await act(async () => {
      fireEvent.click(boton)
    })
    return { boton, vista }
  }

  it('avisa de que el rastreo ha empezado y de dónde se verá', async () => {
    await pulsar(() => Promise.resolve({}))

    const aviso = await screen.findByRole('status')
    expect(aviso.textContent).toMatch(/ha empezado/i)
    expect(aviso.textContent).toMatch(/último rastreo/i)
    expect(aviso.textContent).toMatch(/diario de pasadas/i)
  })

  it('no deja volver a pulsarlo mientras el rastreo dura', async () => {
    const { boton } = await pulsar(() => Promise.resolve({}))

    await screen.findByRole('status')
    expect(boton).toBeDisabled()
  })

  it('dice el error si no se ha podido lanzar, y deja reintentar', async () => {
    const { boton } = await pulsar(() => Promise.reject(new Error('El servidor no responde')))

    expect((await screen.findByRole('alert')).textContent).toMatch(/el servidor no responde/i)
    expect(boton).not.toBeDisabled()
  })

  it('cuando el sitio trae un «Último rastreo» posterior, dice que ha terminado', async () => {
    const { vista } = await pulsar(() => Promise.resolve({}))
    await screen.findByRole('status')

    mockSites.list = [{ ...SITE, last_crawled_at: new Date(Date.now() + 60_000).toISOString() }]
    const { SitesPage } = await import('../SitesPage')
    vista.rerender(wrap(<SitesPage />))

    // El estado vive en el componente: `rerender` con el mismo árbol lo conserva.
    await waitFor(() => expect(screen.getByRole('status').textContent).toMatch(/ha terminado/i))
  })
})

describe('#358 — «Eliminar» pide confirmación', () => {
  // Borraba con un clic, en cascada y sin deshacer: páginas, hallazgos revisados, secciones y
  // diario. Y el botón está en la misma fila que «Rastrear ahora».
  async function abrir(mutateFn = vi.fn()) {
    const { useDeleteSite } = await import('@/shared/api/generated/hub-sites/hub-sites')
    ;(useDeleteSite as ReturnType<typeof vi.fn>).mockImplementation(() => ({ mutate: mutateFn, isPending: false, reset: vi.fn() }))
    mockSites.list = [SITE]
    const { SitesPage } = await import('../SitesPage')
    render(wrap(<SitesPage />))
    fireEvent.click((await screen.findAllByRole('button', { name: /^eliminar$/i }))[0])
    return mutateFn
  }

  it('no borra al pulsar: abre una confirmación con el sitio y lo que se pierde', async () => {
    const mutateFn = await abrir()

    expect(mutateFn).not.toHaveBeenCalled()
    const dialogo = await screen.findByRole('dialog')
    expect(dialogo.textContent).toContain('Portal Institucional')
    expect(dialogo.textContent).toMatch(/3 páginas/)
    expect(dialogo.textContent).toMatch(/hallazgos/i)
    expect(dialogo.textContent).toMatch(/no se puede deshacer/i)
  })

  it('cancelar no envía nada', async () => {
    const mutateFn = await abrir()
    const dialogo = await screen.findByRole('dialog')
    fireEvent.click(within(dialogo).getByRole('button', { name: /cancelar/i }))

    expect(mutateFn).not.toHaveBeenCalled()
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('confirmar borra ese sitio', async () => {
    const mutateFn = await abrir()
    const dialogo = await screen.findByRole('dialog')
    fireEvent.click(within(dialogo).getByRole('button', { name: /^eliminar$/i }))

    expect(mutateFn.mock.calls[0][0]).toEqual({ siteId: SITE.id })
  })
})
