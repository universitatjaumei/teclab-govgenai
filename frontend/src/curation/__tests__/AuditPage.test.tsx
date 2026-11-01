import { describe, it, expect, beforeAll, afterEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import i18n from '@/shared/i18n'

const mockSites = vi.hoisted(() => ({ list: [] as object[] }))
const mockReport = vi.hoisted(() => ({ data: null as object | null }))

vi.mock('@/shared/api/generated/hub-sites/hub-sites', () => ({
  useListSites: vi.fn(() => ({ data: mockSites.list, isLoading: false })),
}))

vi.mock('@/shared/api/generated/hub-content-quality/hub-content-quality', () => ({
  useAnalyzeSite: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useGetSiteQualityReport: vi.fn(() => ({ data: mockReport.data, isLoading: false })),
  getListSiteFindingsQueryKey: vi.fn(() => ['listSiteFindings']),
}))

beforeAll(async () => {
  await i18n.changeLanguage('es')
})

afterEach(() => {
  vi.clearAllMocks()
  mockSites.list = []
  mockReport.data = null
})

const SITE = { id: 'site-001', name: 'Portal Institucional' }

function wrap(element: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{element}</MemoryRouter>
    </QueryClientProvider>
  )
}

describe('AuditPage (curation)', () => {
  it('renderiza el selector de sitio', async () => {
    mockSites.list = [SITE]
    const { AuditPage } = await import('../AuditPage')
    render(wrap(<AuditPage />))
    await waitFor(() => {
      expect(screen.getByRole('combobox', { name: /seleccione un sitio/i })).toBeTruthy()
    })
  })

  it('"Analizar ahora" invoca useAnalyzeSite', async () => {
    const { useAnalyzeSite } = await import('@/shared/api/generated/hub-content-quality/hub-content-quality')
    const mutateFn = vi.fn()
    ;(useAnalyzeSite as ReturnType<typeof vi.fn>).mockReturnValue({ mutate: mutateFn, isPending: false })

    mockSites.list = [SITE]
    const { AuditPage } = await import('../AuditPage')
    render(wrap(<AuditPage />))

    const selector = screen.getByRole('combobox', { name: /seleccione un sitio/i })
    fireEvent.change(selector, { target: { value: SITE.id } })

    fireEvent.click(screen.getByText(/analizar ahora/i))
    expect(mutateFn).toHaveBeenCalledWith({ siteId: SITE.id })
  })

  it('muestra el informe en cuanto se elige un sitio, sin pasos intermedios', async () => {
    mockSites.list = [SITE]
    mockReport.data = {
      site_id: 'site-001',
      site_name: 'Portal Institucional',
      generated_at: '2026-06-06T12:00:00Z',
      totals_by_type: { stale: 3 },
      totals_by_severity: { info: 3 },
      sections: [],
    }

    const { AuditPage } = await import('../AuditPage')
    render(wrap(<AuditPage />))

    const selector = screen.getByRole('combobox', { name: /seleccione un sitio/i })
    fireEvent.change(selector, { target: { value: SITE.id } })

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /informe de auditoría/i })).toBeTruthy()
      expect(screen.getByText(/desactualizada/i)).toBeTruthy()
    })
  })
})

describe('WebQualityReportViewer (vía AuditPage)', () => {
  it('muestra mensaje vacío si no hay hallazgos', async () => {
    mockSites.list = [SITE]
    mockReport.data = {
      site_id: 'site-001',
      site_name: 'Portal',
      generated_at: '2026-06-06T12:00:00Z',
      totals_by_type: {},
      totals_by_severity: {},
      sections: [],
    }

    const { AuditPage } = await import('../AuditPage')
    render(wrap(<AuditPage />))
    fireEvent.change(screen.getByRole('combobox', { name: /seleccione un sitio/i }), { target: { value: SITE.id } })

    await waitFor(() => {
      expect(screen.getByText(/sin hallazgos/i)).toBeTruthy()
    })
  })

  it('muestra botones de descarga DOCX y PDF', async () => {
    mockSites.list = [SITE]
    mockReport.data = {
      site_id: 'site-001',
      site_name: 'Portal',
      generated_at: '2026-06-06T12:00:00Z',
      totals_by_type: { stale: 1 },
      totals_by_severity: { info: 1 },
      sections: [],
      // CUR.8 — el botón de PDF sólo sale si el servidor puede hacer uno.
      pdf_available: true,
    }

    const { AuditPage } = await import('../AuditPage')
    render(wrap(<AuditPage />))
    fireEvent.change(screen.getByRole('combobox', { name: /seleccione un sitio/i }), { target: { value: SITE.id } })

    await waitFor(() => {
      expect(screen.getByText(/descargar docx/i)).toBeTruthy()
      expect(screen.getByText(/descargar pdf/i)).toBeTruthy()
    })
  })
})

describe('#360 — «Analizar ahora» dice qué ha pasado', () => {
  async function con(estado: object) {
    const { useAnalyzeSite } = await import('@/shared/api/generated/hub-content-quality/hub-content-quality')
    ;(useAnalyzeSite as ReturnType<typeof vi.fn>).mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
      variables: { siteId: SITE.id },
      ...estado,
    })
    mockSites.list = [SITE]
    const { AuditPage } = await import('../AuditPage')
    render(wrap(<AuditPage />))
    fireEvent.change(screen.getByRole('combobox', { name: /seleccione un sitio/i }), {
      target: { value: SITE.id },
    })
  }

  it('avisa de que ha empezado', async () => {
    await con({ isSuccess: true, isError: false })

    expect((await screen.findByRole('status')).textContent).toMatch(/ha empezado/i)
  })

  it('si el sitio ya se está rastreando, dice por qué no', async () => {
    await con({
      isSuccess: false,
      isError: true,
      error: new Error('Ya hay un rastreo de este sitio en marcha.'),
    })

    expect((await screen.findByRole('alert')).textContent).toMatch(/ya hay un rastreo/i)
  })
})
