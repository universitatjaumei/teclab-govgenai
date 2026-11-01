import { describe, it, expect, vi, beforeEach, beforeAll, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import i18n from '@/shared/i18n'

/**
 * El alcance del análisis semántico, cambiable después de crear el sitio (CUR.7).
 *
 * Sólo se fijaba al dar de alta el apartado, y es justo la decisión que se toma **después**: se
 * rastrea, se ve el informe, y entonces se decide si vale la pena pagar embeddings y llamadas al
 * modelo para buscar duplicados por significado. El `PATCH` del sitio ya lo aceptaba; lo que no
 * había era pantalla.
 */

const SITIO = {
  id: 's1',
  name: 'Escola de Doctorat',
  root_url: 'https://www.uji.es/centres/escola-doctorat/',
  status: 'active',
  audit_semantic_scope: 'ingested',
  last_crawled_at: '2026-08-19T10:00:00Z',
}

const mockPatch = vi.hoisted(() => ({ mutate: vi.fn() }))

vi.mock('@/shared/api/generated/hub-sites/hub-sites', () => ({
  useListSites: () => ({ data: [SITIO], isLoading: false }),
  useCreateSite: () => ({ mutate: vi.fn(), isPending: false }),
  useDeleteSite: () => ({ mutate: vi.fn(), isPending: false }),
  useTriggerSiteCrawl: () => ({ mutate: vi.fn(), isPending: false }),

  // #358 — la confirmación de borrado cuenta las páginas del sitio.

  useListSitePages: vi.fn(() => ({ data: undefined })),
  useReconnoiterSite: () => ({ mutateAsync: vi.fn(), isPending: false }),
  usePatchSite: () => mockPatch,
  getListSitesQueryKey: () => ['sites'],
}))

vi.mock('@/shared/api/download', () => ({ descargarConAutorizacion: vi.fn() }))

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


beforeAll(async () => {
  await i18n.changeLanguage('es')
})

beforeEach(() => vi.clearAllMocks())
afterEach(cleanup)

async function pantalla() {
  const { SitesPage } = await import('../SitesPage')
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={qc}>{<SitesPage />}</QueryClientProvider>)
  await screen.findByText('Escola de Doctorat')
}

describe('el alcance del análisis semántico', () => {
  it('se ve en la fila del sitio', async () => {
    await pantalla()

    const selector = screen.getByTestId('alcance-s1') as HTMLSelectElement
    expect(selector.value).toBe('ingested')
  })

  it('se puede cambiar sin volver a crear el sitio', async () => {
    await pantalla()

    fireEvent.change(screen.getByTestId('alcance-s1'), { target: { value: 'full' } })

    await waitFor(() =>
      expect(mockPatch.mutate).toHaveBeenCalledWith(
        { siteId: 's1', data: { audit_semantic_scope: 'full' } },
        expect.anything(),
      ),
    )
  })

  it('se puede apagar: buscar duplicados por significado cuesta modelo y embeddings', async () => {
    await pantalla()

    const opciones = [...(screen.getByTestId('alcance-s1') as HTMLSelectElement).options].map(
      (o) => o.value,
    )
    expect(opciones).toContain('off')
  })
})
