import { describe, it, expect, beforeAll, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import i18n from '@/shared/i18n'

/**
 * Proponer páginas para un asistente mientras se cura la web (2026-10-08).
 *
 * Piloto del asistente de la Escuela de Doctorado: quien cura revisa la web y, a la vez, marca
 * qué páginas deberían alimentarlo; quien crea el asistente decide en Publicación. La marca es
 * del servidor (quién y cuándo), no de la pantalla: aquí sólo se pinta y se cambia.
 */
const proponer = vi.fn()
const retirar = vi.fn()

vi.mock('@/shared/api/generated/hub-sites/hub-sites', () => ({
  useListSites: vi.fn(() => ({ data: [{ id: 'sitio-1', name: 'Escola de Doctorat' }] })),
  useListSitePages: vi.fn(),
  useProponerPagina: vi.fn(() => ({ mutate: proponer, isPending: false })),
  useRetirarPropuestaDePagina: vi.fn(() => ({ mutate: retirar, isPending: false })),
  getListSitePagesQueryKey: vi.fn(() => ['pages']),
  useGetPageContent: vi.fn(() => ({ data: undefined, isLoading: true })),
}))

import { useListSitePages } from '@/shared/api/generated/hub-sites/hub-sites'
import { PaginesPage } from '../PaginesPage'

const PAGINAS = [
  {
    id: 'p-beques', site_id: 'sitio-1', url: 'https://www.uji.es/escola-doctorat/beques/',
    title: 'Beques', status: 'active', token_count: 500, superseded: false, quality_score: null,
    last_crawled_at: null, propuesta_at: '2026-10-08T09:00:00Z', propuesta_por: 'curadora@uji.es',
  },
  {
    id: 'p-tesis', site_id: 'sitio-1', url: 'https://www.uji.es/escola-doctorat/tesis/',
    title: 'Dipòsit de tesi', status: 'active', token_count: 800, superseded: false,
    quality_score: null, last_crawled_at: null, propuesta_at: null, propuesta_por: null,
  },
]

function pintar() {
  vi.mocked(useListSitePages).mockReturnValue({ data: PAGINAS, isLoading: false } as never)
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <PaginesPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  fireEvent.change(screen.getByRole('combobox', { name: /lloc/i }), { target: { value: 'sitio-1' } })
}

beforeAll(async () => {
  await i18n.changeLanguage('ca')
})

beforeEach(() => {
  vi.clearAllMocks()
})

describe('Pàgines: proposar per a l\'assistent', () => {
  it('llista les pàgines del lloc amb la marca que diu el servidor', () => {
    pintar()

    const beques = screen.getByTestId('pagina-p-beques')
    expect(within(beques).getByRole('checkbox')).toBeChecked()
    expect(beques.textContent).toContain('curadora@uji.es')
    expect(within(screen.getByTestId('pagina-p-tesis')).getByRole('checkbox')).not.toBeChecked()
  })

  it('marcar una pàgina la proposa', () => {
    pintar()

    fireEvent.click(within(screen.getByTestId('pagina-p-tesis')).getByRole('checkbox'))

    expect(proponer).toHaveBeenCalledWith(
      { siteId: 'sitio-1', pageId: 'p-tesis' },
      expect.anything(),
    )
  })

  it('desmarcar-la retira la proposta', () => {
    pintar()

    fireEvent.click(within(screen.getByTestId('pagina-p-beques')).getByRole('checkbox'))

    expect(retirar).toHaveBeenCalledWith(
      { siteId: 'sitio-1', pageId: 'p-beques' },
      expect.anything(),
    )
  })

  it('es pot veure només les proposades, i ho filtra el servidor', () => {
    pintar()

    fireEvent.click(screen.getByLabelText(/només les proposades/i))

    const crides = vi.mocked(useListSitePages).mock.calls
    expect(crides[crides.length - 1][1]).toEqual({ propuestas: true })
  })
})

describe('Pàgines: el que la revisió de la PR #246 va trobar', () => {
  it("l'estat de la pàgina ix traduït, no com a codi", () => {
    pintar()
    const fila = screen.getByTestId('pagina-p-beques')
    expect(fila.textContent).toContain('Activa')
    expect(fila.textContent).not.toContain('active')
  })

  it('si la llista no es pot carregar, ho diu en lloc de «no hi ha pàgines»', () => {
    vi.mocked(useListSitePages).mockReturnValue({
      data: undefined, isLoading: false, isError: true,
      error: { response: { data: { detail: 'Sense accés al mòdul' } } },
    } as never)
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <PaginesPage />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    fireEvent.change(screen.getByRole('combobox', { name: /lloc/i }), { target: { value: 'sitio-1' } })

    expect(screen.getByRole('alert').textContent).toContain('Sense accés al mòdul')
  })
})
